"""Registered-user storage in Django's own database (SQLite by default).

Same methods as MemoryStore / FirestoreStore, so services.py and the views don't change.
Select it with DATA_BACKEND=django (the default).
"""
from django.db import transaction
from django.db.models import F, Q

from . import models as m

USER_FIELDS = ("email", "nickname", "nickname_lower", "age", "gender", "bio",
               "interests", "visibility", "photo_url", "created_at")


def _user(row):
    out = {f: getattr(row, f) for f in USER_FIELDS}
    return {k: v for k, v in out.items() if v is not None}     # unset fields are simply absent


def _request(r):
    return {"from_uid": r.from_uid, "to_uid": r.to_uid, "status": r.status, "ts": r.ts}


def _conversation(c):
    return {"id": c.cid, "uids": [c.user_a, c.user_b], "last_message": c.last_message,
            "last_ts": c.last_ts, "last_sender": c.last_sender,
            "unread": {c.user_a: c.unread_a, c.user_b: c.unread_b},
            "cleared": {c.user_a: c.cleared_a, c.user_b: c.cleared_b}}


class DjangoStore:
    name = "django"

    # ---- users ----
    def user_get(self, uid):
        row = m.UserProfile.objects.filter(pk=uid).first()
        return _user(row) if row else None

    def user_get_many(self, uids):
        return {r.uid: _user(r) for r in m.UserProfile.objects.filter(pk__in=list(uids))}

    def user_set(self, uid, data):
        fields = {k: v for k, v in data.items() if k in USER_FIELDS}
        with transaction.atomic():
            m.UserProfile.objects.update_or_create(uid=uid, defaults=fields)

    def user_search(self, prefix, limit=30):
        rows = (m.UserProfile.objects.filter(nickname_lower__startswith=prefix)
                .exclude(nickname_lower="")[:limit])
        return [dict(_user(r), uid=r.uid) for r in rows]

    # ---- blocks ----
    def block_add(self, uid, other):
        m.Block.objects.get_or_create(owner=uid, blocked=other)

    def block_remove(self, uid, other):
        m.Block.objects.filter(owner=uid, blocked=other).delete()

    def block_list(self, uid):
        return set(m.Block.objects.filter(owner=uid).values_list("blocked", flat=True))

    # ---- friend requests ----
    def req_get(self, rid):
        r = m.FriendRequest.objects.filter(pk=rid).first()
        return _request(r) if r else None

    def req_set(self, rid, data):
        m.FriendRequest.objects.update_or_create(rid=rid, defaults={
            "from_uid": data["from_uid"], "to_uid": data["to_uid"],
            "status": data["status"], "ts": data.get("ts", 0)})

    def req_delete(self, rid):
        m.FriendRequest.objects.filter(pk=rid).delete()

    def req_incoming(self, uid):
        return [(r.rid, _request(r)) for r in m.FriendRequest.objects.filter(to_uid=uid, status="pending")]

    def req_outgoing(self, uid):
        return [(r.rid, _request(r)) for r in m.FriendRequest.objects.filter(from_uid=uid, status="pending")]

    # ---- friendships ----
    def friend_add(self, a, b):
        a, b = sorted([a, b])
        m.Friendship.objects.get_or_create(user_a=a, user_b=b)

    def friend_remove(self, a, b):
        a, b = sorted([a, b])
        m.Friendship.objects.filter(user_a=a, user_b=b).delete()

    def friend_ids(self, uid):
        rows = m.Friendship.objects.filter(Q(user_a=uid) | Q(user_b=uid))
        return [r.user_b if r.user_a == uid else r.user_a for r in rows]

    # ---- conversations ----
    def conv_get(self, cid):
        c = m.Conversation.objects.filter(pk=cid).first()
        return _conversation(c) if c else None

    def conv_list(self, uid):
        return [_conversation(c) for c in m.Conversation.objects.filter(Q(user_a=uid) | Q(user_b=uid))]

    def conv_append(self, cid, uids, sender, text, ts):
        a, b = sorted(uids)
        with transaction.atomic():
            conv, _ = m.Conversation.objects.get_or_create(cid=cid, defaults={"user_a": a, "user_b": b})
            msg = m.Message.objects.create(conversation=conv, sender=sender, text=text, ts=ts)
            other_unread = "unread_b" if sender == conv.user_a else "unread_a"
            m.Conversation.objects.filter(pk=cid).update(
                last_message=text[:80], last_ts=ts, last_sender=sender, **{other_unread: F(other_unread) + 1})
        return str(msg.pk)

    def conv_mark_read(self, cid, uid):
        m.Conversation.objects.filter(pk=cid, user_a=uid).update(unread_a=0)
        m.Conversation.objects.filter(pk=cid, user_b=uid).update(unread_b=0)

    def conv_clear(self, cid, uid, ts):
        m.Conversation.objects.filter(pk=cid, user_a=uid).update(cleared_a=ts, unread_a=0)
        m.Conversation.objects.filter(pk=cid, user_b=uid).update(cleared_b=ts, unread_b=0)

    def msg_list(self, cid, after_ts=0, limit=200):
        rows = m.Message.objects.filter(conversation_id=cid, ts__gt=after_ts).order_by("-ts", "-id")[:limit]
        return [{"id": str(r.pk), "sender": r.sender, "text": r.text, "ts": r.ts} for r in reversed(list(rows))]

    # ---- notifications ----
    def notif_add(self, uid, data):
        n = m.Notification.objects.create(uid=uid, type=data["type"], from_uid=data.get("from_uid", ""),
                                          text=data["text"], ts=data["ts"], read=data.get("read", False))
        return str(n.pk)

    def notif_list(self, uid, limit=30):
        rows = m.Notification.objects.filter(uid=uid).order_by("-ts", "-id")[:limit]
        return [{"id": str(n.pk), "type": n.type, "from_uid": n.from_uid, "text": n.text,
                 "ts": n.ts, "read": n.read} for n in rows]

    def notif_mark_all(self, uid):
        m.Notification.objects.filter(uid=uid, read=False).update(read=True)

    # ---- pictures are saved by chat/media.py (the media/ folder), not here ----
    def avatar_put(self, uid, data, content_type):
        raise NotImplementedError("Profile pictures are saved by chat.media")

    def avatar_get(self, uid):
        return None