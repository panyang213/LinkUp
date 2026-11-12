"""Rules for registered users: profiles, friends, blocks, private messages, notifications.

Every function takes the *acting* user's uid from the server session, never from the
client, so one user can't act as another. Anonymous users have no uid and can't reach this.
"""
import time

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from . import presence
from .store import get_store

MAX_DM_LEN = 1000
VISIBILITY = [("public", "Everyone signed in"), ("friends", "Friends only"), ("private", "Hidden from search")]
GENDERS = [("female", "Female"), ("male", "Male"), ("nonbinary", "Non-binary"), ("prefer_not", "Prefer not to say")]


class ServiceError(Exception):
    pass


def now_ms():
    return int(time.time() * 1000)


def pair_id(a, b):
    return "__".join(sorted([a, b]))


def push(uid, payload):
    """Send a live event to every open tab of `uid` (best effort)."""
    try:
        async_to_sync(get_channel_layer().group_send)(f"user_{uid}", {"type": "push", "payload": payload})
    except Exception:
        pass


# ---------- profiles ----------
def get_profile(uid):
    return get_store().user_get(uid)


def save_profile(uid, data, email=None):
    doc = dict(data, nickname_lower=data["nickname"].lower())
    if email is not None:
        doc["email"] = email  # private: never included by public_profile()
    get_store().user_set(uid, doc)


def public_profile(doc, uid, viewer_uid, is_friend=False):
    """What `viewer_uid` may see about `uid`. Email and auth details are never included."""
    out = {"uid": uid, "nickname": doc.get("nickname", "User"), "photo_url": doc.get("photo_url", ""),
           "visibility": doc.get("visibility", "public"), "full": False}
    if viewer_uid == uid or is_friend or doc.get("visibility", "public") == "public":
        out.update(full=True, bio=doc.get("bio", ""), interests=doc.get("interests", []),
                   age=doc.get("age"), gender=doc.get("gender", ""))
    out["online"] = presence.is_online(uid)
    return out


def relationship(me, other):
    st = get_store()
    if other in st.block_list(me) or me in st.block_list(other):
        return "blocked"
    if other in st.friend_ids(me):
        return "friends"
    sent, received = st.req_get(f"{me}_{other}"), st.req_get(f"{other}_{me}")
    if sent and sent["status"] == "pending":
        return "request_sent"
    if received and received["status"] == "pending":
        return "request_received"
    return "none"


def view_profile(me, other):
    doc = get_store().user_get(other)
    if not doc or not doc.get("nickname"):
        return None
    rel = relationship(me, other) if me != other else "self"
    if rel == "blocked":
        return None
    if doc.get("visibility") == "private" and rel not in ("friends", "self", "request_received"):
        return None
    prof = public_profile(doc, other, me, rel == "friends")
    prof["relationship"] = rel
    return prof


def search_users(me, query):
    query = " ".join(query.lower().split())
    if len(query) < 2:
        return []
    st = get_store()
    # Fetch the viewer's own lists ONCE instead of once per search result.
    my_blocks, friends = st.block_list(me), set(st.friend_ids(me))
    incoming = {r["from_uid"] for _, r in st.req_incoming(me)}
    outgoing = {r["to_uid"] for _, r in st.req_outgoing(me)}
    out = []
    for row in st.user_search(query, 30):
        uid = row["uid"]
        if uid == me or uid in my_blocks or row.get("visibility") == "private":
            continue
        if me in st.block_list(uid):
            continue
        prof = public_profile(row, uid, me, uid in friends)
        prof["relationship"] = ("friends" if uid in friends else "request_sent" if uid in outgoing
                                else "request_received" if uid in incoming else "none")
        out.append(prof)
        if len(out) >= 20:
            break
    return out


# ---------- notifications ----------
def notify(uid, type_, from_uid, text):
    n = {"type": type_, "from_uid": from_uid, "text": text, "ts": now_ms(), "read": False}
    n["id"] = get_store().notif_add(uid, n)
    push(uid, {"type": "notification", "notification": n})


def list_notifications(uid):
    return get_store().notif_list(uid)


def mark_notifications_read(uid):
    get_store().notif_mark_all(uid)


# ---------- friends ----------
def _nick(uid):
    d = get_store().user_get(uid)
    return d.get("nickname", "Someone") if d else "Someone"


def send_request(me, other):
    st = get_store()
    if me == other:
        raise ServiceError("You can't add yourself.")
    if not st.user_get(other) or not st.user_get(other).get("nickname"):
        raise ServiceError("That user doesn't exist.")
    rel = relationship(me, other)
    if rel == "blocked":
        raise ServiceError("You can't send a request to this user.")
    if rel == "friends":
        raise ServiceError("You're already friends.")
    if rel == "request_sent":
        raise ServiceError("Request already sent.")
    if rel == "request_received":
        return respond_request(me, f"{other}_{me}", True)
    st.req_set(f"{me}_{other}", {"from_uid": me, "to_uid": other, "status": "pending", "ts": now_ms()})
    notify(other, "friend_request", me, f"{_nick(me)} sent you a friend request.")
    return "request_sent"


def respond_request(me, request_id, accept):
    st = get_store()
    req = st.req_get(request_id)
    if not req or req["to_uid"] != me or req["status"] != "pending":
        raise ServiceError("This request is no longer available.")
    if accept:
        if req["from_uid"] in st.block_list(me) or me in st.block_list(req["from_uid"]):
            raise ServiceError("You can't accept this request.")
        st.friend_add(me, req["from_uid"])
        st.req_set(request_id, dict(req, status="accepted"))
        notify(req["from_uid"], "friend_accept", me, f"{_nick(me)} accepted your friend request.")
        return "friends"
    st.req_set(request_id, dict(req, status="rejected"))
    return "none"


def remove_friend(me, other):
    st = get_store()
    st.friend_remove(me, other)
    for rid in (f"{me}_{other}", f"{other}_{me}"):
        st.req_delete(rid)
    push(other, {"type": "friend_removed", "uid": me})


def block_user(me, other):
    if me == other:
        raise ServiceError("You can't block yourself.")
    remove_friend(me, other)
    get_store().block_add(me, other)


def are_friends(a, b):
    return b in get_store().friend_ids(a)


def friend_lists(me):
    st = get_store()
    ids = st.friend_ids(me)
    incoming, outgoing = st.req_incoming(me), st.req_outgoing(me)
    wanted = set(ids) | {r["from_uid"] for _, r in incoming} | {r["to_uid"] for _, r in outgoing}
    users = st.user_get_many(list(wanted))          # one batched read instead of one per person

    friends = [public_profile(users[u], u, me, True) for u in ids if users.get(u, {}).get("nickname")]
    friends.sort(key=lambda f: (not f["online"], f["nickname"].lower()))

    def with_profile(rows, key):
        return [{"request_id": rid, "profile": public_profile(users[r[key]], r[key], me, False)}
                for rid, r in rows if users.get(r[key], {}).get("nickname")]

    return {"friends": friends, "incoming": with_profile(incoming, "from_uid"),
            "outgoing": with_profile(outgoing, "to_uid")}


# ---------- private messages ----------
def _visible(conv, me):
    return conv.get("cleared", {}).get(me, 0) < conv.get("last_ts", 0)   # not deleted by this user


def list_conversations(me, friends=None):
    """`friends` may be passed in (a set of uids) to avoid re-reading the friend list."""
    st = get_store()
    convs = [c for c in st.conv_list(me) if _visible(c, me)]
    if not convs:
        return []
    friends = set(st.friend_ids(me)) if friends is None else friends
    others = {c["id"]: next(u for u in c["uids"] if u != me) for c in convs}
    users = st.user_get_many(list(set(others.values())))   # one batched read
    out = []
    for conv in convs:
        other = others[conv["id"]]
        d = users.get(other)
        if not d or not d.get("nickname"):
            continue
        out.append({"profile": public_profile(d, other, me, other in friends),
                    "last_message": conv.get("last_message", ""), "last_ts": conv.get("last_ts", 0),
                    "last_mine": conv.get("last_sender") == me,
                    "unread": conv.get("unread", {}).get(me, 0)})
    out.sort(key=lambda c: -c["last_ts"])
    return out


def history(me, other):
    st = get_store()
    cid = pair_id(me, other)
    conv = st.conv_get(cid)
    if not conv or me not in conv["uids"]:
        return []
    msgs = st.msg_list(cid, after_ts=conv.get("cleared", {}).get(me, 0))
    st.conv_mark_read(cid, me)
    return msgs


def send_dm(me, other, text):
    if not isinstance(text, str):
        raise ServiceError("Invalid message.")
    text = text.strip()[:MAX_DM_LEN]
    if not text:
        raise ServiceError("Message is empty.")
    st = get_store()
    if relationship(me, other) != "friends":
        raise ServiceError("You can only message accepted friends.")
    cid, ts = pair_id(me, other), now_ms()
    mid = st.conv_append(cid, [me, other], me, text, ts)
    return {"id": mid, "sender": me, "text": text, "ts": ts}


def mark_read(me, other):
    get_store().conv_mark_read(pair_id(me, other), me)


def delete_conversation(me, other):
    get_store().conv_clear(pair_id(me, other), me, now_ms())


def nav_counts(me):
    """Cheap numbers for the sidebar badges (2 reads, no per-person lookups)."""
    st = get_store()
    unread = sum(c.get("unread", {}).get(me, 0) for c in st.conv_list(me) if _visible(c, me))
    return {"pending_requests": len(st.req_incoming(me)), "unread_total": unread}