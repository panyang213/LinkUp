"""Storage layer for registered users.

Two interchangeable backends with identical methods:
  * FirestoreStore  - production (Firebase Firestore + Storage)
  * MemoryStore     - local development/tests when no Firebase credentials are set

Only registered-user data ever goes through here. Anonymous chats never touch it.

Firestore layout
  users/{uid}                       profile (+ private email, never sent to other users)
  users/{uid}/blocked/{otherUid}
  users/{uid}/notifications/{id}
  friend_requests/{from}_{to}       status: pending | accepted | rejected
  friendships/{uidA__uidB}          uids: [a, b]
  conversations/{uidA__uidB}        uids, last_message, last_ts, unread{uid:n}, cleared{uid:ts}
  conversations/{id}/messages/{id}  sender, text, ts
"""
import copy
import threading
import time
import uuid
from collections import defaultdict


class MemoryStore:
    name = "memory"

    def __init__(self):
        self.lock = threading.RLock()
        self.users, self.reqs, self.convs = {}, {}, {}
        self.blocks = defaultdict(set)
        self.friend_map = defaultdict(set)
        self.msgs = defaultdict(list)
        self.notifs = defaultdict(list)
        self.avatars = {}

    # users
    def user_get(self, uid):
        with self.lock:
            return copy.deepcopy(self.users.get(uid))

    def user_set(self, uid, data):
        with self.lock:
            self.users.setdefault(uid, {}).update(copy.deepcopy(data))

    def user_get_many(self, uids):
        with self.lock:
            return {u: copy.deepcopy(self.users[u]) for u in uids if u in self.users}

    def user_search(self, prefix, limit=30):
        with self.lock:
            out = [dict(u, uid=uid) for uid, u in self.users.items()
                   if u.get("nickname_lower", "").startswith(prefix)]
        return out[:limit]

    # blocks
    def block_add(self, uid, other):
        with self.lock:
            self.blocks[uid].add(other)

    def block_remove(self, uid, other):
        with self.lock:
            self.blocks[uid].discard(other)

    def block_list(self, uid):
        with self.lock:
            return set(self.blocks[uid])

    # friend requests
    def req_get(self, rid):
        with self.lock:
            return copy.deepcopy(self.reqs.get(rid))

    def req_set(self, rid, data):
        with self.lock:
            self.reqs[rid] = copy.deepcopy(data)

    def req_delete(self, rid):
        with self.lock:
            self.reqs.pop(rid, None)

    def req_incoming(self, uid):
        with self.lock:
            return [(k, copy.deepcopy(v)) for k, v in self.reqs.items()
                    if v["to_uid"] == uid and v["status"] == "pending"]

    def req_outgoing(self, uid):
        with self.lock:
            return [(k, copy.deepcopy(v)) for k, v in self.reqs.items()
                    if v["from_uid"] == uid and v["status"] == "pending"]

    # friendships
    def friend_add(self, a, b):
        with self.lock:
            self.friend_map[a].add(b); self.friend_map[b].add(a)

    def friend_remove(self, a, b):
        with self.lock:
            self.friend_map[a].discard(b); self.friend_map[b].discard(a)

    def friend_ids(self, uid):
        with self.lock:
            return list(self.friend_map[uid])

    # conversations
    def conv_get(self, cid):
        with self.lock:
            return copy.deepcopy(self.convs.get(cid))

    def conv_list(self, uid):
        with self.lock:
            return [dict(copy.deepcopy(c), id=cid) for cid, c in self.convs.items() if uid in c["uids"]]

    def conv_append(self, cid, uids, sender, text, ts):
        with self.lock:
            mid = uuid.uuid4().hex
            self.msgs[cid].append({"id": mid, "sender": sender, "text": text, "ts": ts})
            conv = self.convs.setdefault(cid, {"uids": list(uids), "unread": {}, "cleared": {}})
            conv.update(last_message=text[:80], last_ts=ts, last_sender=sender)
            other = next(u for u in uids if u != sender)
            conv["unread"][other] = conv["unread"].get(other, 0) + 1
            return mid

    def conv_mark_read(self, cid, uid):
        with self.lock:
            if cid in self.convs:
                self.convs[cid]["unread"][uid] = 0

    def conv_clear(self, cid, uid, ts):
        with self.lock:
            if cid in self.convs:
                self.convs[cid]["cleared"][uid] = ts
                self.convs[cid]["unread"][uid] = 0

    def msg_list(self, cid, after_ts=0, limit=200):
        with self.lock:
            rows = [m for m in self.msgs[cid] if m["ts"] > after_ts]
        return copy.deepcopy(rows[-limit:])

    # notifications
    def notif_add(self, uid, data):
        with self.lock:
            nid = uuid.uuid4().hex
            self.notifs[uid].append(dict(data, id=nid))
            return nid

    def notif_list(self, uid, limit=30):
        with self.lock:
            return copy.deepcopy(sorted(self.notifs[uid], key=lambda n: -n["ts"])[:limit])

    def notif_mark_all(self, uid):
        with self.lock:
            for n in self.notifs[uid]:
                n["read"] = True

    # avatars
    def avatar_put(self, uid, data, content_type):
        with self.lock:
            self.avatars[uid] = (data, content_type)
        return f"/avatar/{uid}/"

    def avatar_get(self, uid):
        with self.lock:
            return self.avatars.get(uid)


class FirestoreStore:
    name = "firestore"

    def __init__(self):
        from firebase_admin import firestore
        self.fs = firestore
        self.db = firestore.client()

    @staticmethod
    def _eq(query, field, op, value):
        from google.cloud.firestore_v1.base_query import FieldFilter
        return query.where(filter=FieldFilter(field, op, value))

    # users
    def user_get(self, uid):
        d = self.db.collection("users").document(uid).get()
        return d.to_dict() if d.exists else None

    def user_set(self, uid, data):
        self.db.collection("users").document(uid).set(data, merge=True)

    def user_get_many(self, uids):
        """One round trip for many users (instead of one request each)."""
        uids = list(uids)
        if not uids:
            return {}
        refs = [self.db.collection("users").document(u) for u in uids]
        return {d.id: d.to_dict() for d in self.db.get_all(refs) if d.exists}

    def user_search(self, prefix, limit=30):
        q = self.db.collection("users")
        q = self._eq(q, "nickname_lower", ">=", prefix)
        q = self._eq(q, "nickname_lower", "<=", prefix + "\uf8ff").limit(limit)
        return [dict(d.to_dict(), uid=d.id) for d in q.stream()]

    # blocks
    def block_add(self, uid, other):
        self.db.collection("users").document(uid).collection("blocked").document(other).set({"ts": 1})

    def block_remove(self, uid, other):
        self.db.collection("users").document(uid).collection("blocked").document(other).delete()

    def block_list(self, uid):
        return {d.id for d in self.db.collection("users").document(uid).collection("blocked").stream()}

    # friend requests
    def req_get(self, rid):
        d = self.db.collection("friend_requests").document(rid).get()
        return d.to_dict() if d.exists else None

    def req_set(self, rid, data):
        self.db.collection("friend_requests").document(rid).set(data)

    def req_delete(self, rid):
        self.db.collection("friend_requests").document(rid).delete()

    def _reqs(self, field, uid):
        q = self._eq(self.db.collection("friend_requests"), field, "==", uid)
        return [(d.id, d.to_dict()) for d in q.stream() if d.to_dict().get("status") == "pending"]

    def req_incoming(self, uid):
        return self._reqs("to_uid", uid)

    def req_outgoing(self, uid):
        return self._reqs("from_uid", uid)

    # friendships
    @staticmethod
    def _pid(a, b):
        return "__".join(sorted([a, b]))

    def friend_add(self, a, b):
        self.db.collection("friendships").document(self._pid(a, b)).set({"uids": sorted([a, b])})

    def friend_remove(self, a, b):
        self.db.collection("friendships").document(self._pid(a, b)).delete()

    def friend_ids(self, uid):
        q = self._eq(self.db.collection("friendships"), "uids", "array_contains", uid)
        return [next(u for u in d.to_dict()["uids"] if u != uid) for d in q.stream()]

    # conversations
    def conv_get(self, cid):
        d = self.db.collection("conversations").document(cid).get()
        return d.to_dict() if d.exists else None

    def conv_list(self, uid):
        q = self._eq(self.db.collection("conversations"), "uids", "array_contains", uid)
        return [dict(d.to_dict(), id=d.id) for d in q.stream()]

    def conv_append(self, cid, uids, sender, text, ts):
        ref = self.db.collection("conversations").document(cid)
        _, mref = ref.collection("messages").add({"sender": sender, "text": text, "ts": ts})
        other = next(u for u in uids if u != sender)
        ref.set({"uids": sorted(uids), "last_message": text[:80], "last_ts": ts, "last_sender": sender,
                 "unread": {other: self.fs.Increment(1)}}, merge=True)
        return mref.id

    def conv_mark_read(self, cid, uid):
        self.db.collection("conversations").document(cid).set({"unread": {uid: 0}}, merge=True)

    def conv_clear(self, cid, uid, ts):
        self.db.collection("conversations").document(cid).set(
            {"cleared": {uid: ts}, "unread": {uid: 0}}, merge=True)

    def msg_list(self, cid, after_ts=0, limit=200):
        q = self.db.collection("conversations").document(cid).collection("messages")
        q = self._eq(q, "ts", ">", after_ts).order_by("ts", direction=self.fs.Query.DESCENDING).limit(limit)
        rows = [dict(d.to_dict(), id=d.id) for d in q.stream()]
        return list(reversed(rows))

    # notifications
    def notif_add(self, uid, data):
        _, ref = self.db.collection("users").document(uid).collection("notifications").add(data)
        return ref.id

    def notif_list(self, uid, limit=30):
        q = self.db.collection("users").document(uid).collection("notifications") \
            .order_by("ts", direction=self.fs.Query.DESCENDING).limit(limit)
        return [dict(d.to_dict(), id=d.id) for d in q.stream()]

    def notif_mark_all(self, uid):
        col = self.db.collection("users").document(uid).collection("notifications")
        batch = self.db.batch()
        for d in self._eq(col, "read", "==", False).stream():
            batch.update(d.reference, {"read": True})
        batch.commit()

    # avatars (Firebase Storage)
    def avatar_put(self, uid, data, content_type):
        from firebase_admin import storage
        blob = storage.bucket().blob(f"avatars/{uid}")
        blob.upload_from_string(data, content_type=content_type)
        blob.make_public()  # needs fine-grained bucket access; see README
        return f"{blob.public_url}?v={int(time.time())}"

    def avatar_get(self, uid):
        return None


class CachingStore:
    """Wraps a store and remembers user profiles for a short time.

    Almost every page needs the same few profiles (yours, your friends'). Each Firestore read from
    far away costs hundreds of milliseconds, so a 30-second memory cache removes most of them.
    Writes through this process clear the entry. With several server processes a change made by
    another process can take up to TTL seconds to show up.
    """
    TTL = 30

    def __init__(self, inner):
        self._inner = inner
        self._users = {}
        self._lock = threading.Lock()

    def __getattr__(self, name):            # everything else goes straight to the real store
        return getattr(self._inner, name)

    def _cached(self, uid):
        with self._lock:
            hit = self._users.get(uid)
        if hit and time.monotonic() - hit[0] < self.TTL:
            return True, copy.deepcopy(hit[1])
        return False, None

    def _remember(self, uid, doc):
        with self._lock:
            self._users[uid] = (time.monotonic(), copy.deepcopy(doc))

    def user_get(self, uid):
        found, doc = self._cached(uid)
        if found:
            return doc
        doc = self._inner.user_get(uid)
        self._remember(uid, doc)
        return doc

    def user_get_many(self, uids):
        out, missing = {}, []
        for uid in set(uids):
            found, doc = self._cached(uid)
            if found:
                if doc:
                    out[uid] = doc
            else:
                missing.append(uid)
        if missing:
            fetched = self._inner.user_get_many(missing)
            for uid in missing:
                self._remember(uid, fetched.get(uid))
                if uid in fetched:
                    out[uid] = copy.deepcopy(fetched[uid])
        return out

    def user_set(self, uid, data):
        self._inner.user_set(uid, data)
        with self._lock:
            self._users.pop(uid, None)


_store = None


def get_store():
    """DATA_BACKEND=django (default): Django's own database. firestore: Firebase. memory: tests/demo."""
    global _store
    if _store is None:
        from django.conf import settings
        backend = settings.DATA_BACKEND
        if backend == "firestore":
            from . import firebase_auth
            firebase_auth.init_app()
            _store = CachingStore(FirestoreStore())
        elif backend == "memory":
            _store = CachingStore(MemoryStore())
        else:
            from .store_db import DjangoStore
            _store = DjangoStore()
    return _store