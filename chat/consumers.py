import asyncio
import json
import time
import uuid
from collections import deque

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from .content import MOOD_KEYS
from .matchmaker import matchmaker
from .models import Report, Block

MAX_MESSAGE_LEN = 1000
RATE_WINDOW_SECONDS = 5
RATE_MAX_MESSAGES = 6
MAX_INTERESTS = 5

# ---- voice / video calls (WebRTC signaling only; audio and video never pass through the server) ----
CALL_KINDS = {"voice", "video"}
RING_SECONDS = 30            # an unanswered call stops ringing after this long
MAX_SDP_LEN = 60000
MAX_ICE_PER_CALL = 400
DECLINE_REASONS = {"declined", "media", "busy"}
END_REASONS = {"hangup", "failed", "media"}


def clean_interests(raw):
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        if isinstance(item, str):
            item = " ".join(item.lower().split())[:24]
            if item and item not in out:
                out.append(item)
    return out[:MAX_INTERESTS]


def clean_sdp(raw, expected_type):
    """Only a well-formed offer/answer is ever forwarded to the other person."""
    if not isinstance(raw, dict) or raw.get("type") != expected_type:
        return None
    sdp = raw.get("sdp")
    if not isinstance(sdp, str) or not (0 < len(sdp) <= MAX_SDP_LEN):
        return None
    return {"type": expected_type, "sdp": sdp}


def clean_candidate(raw):
    if not isinstance(raw, dict):
        return None
    cand = raw.get("candidate")
    if not isinstance(cand, str) or len(cand) > 2000:
        return None
    mid, idx, ufrag = raw.get("sdpMid"), raw.get("sdpMLineIndex"), raw.get("usernameFragment")
    return {"candidate": cand,
            "sdpMid": mid if isinstance(mid, str) and len(mid) <= 64 else None,
            "sdpMLineIndex": idx if isinstance(idx, int) and 0 <= idx < 64 else None,
            "usernameFragment": ufrag if isinstance(ufrag, str) and len(ufrag) <= 256 else None}


class ChatConsumer(AsyncWebsocketConsumer):
    """Anonymous random chat. Messages are relayed live and never stored."""

    async def connect(self):
        session = self.scope.get("session")
        sid = session.get("anon_id") if session else None
        nick = session.get("nickname") if session else None
        if not sid or not nick:
            await self.close(code=4401)
            return
        self.sid, self.nick = sid, nick
        self.partner = None        # channel name of current partner
        self.partner_sid = None
        self.interests, self.mood = [], ""
        self.sent_times = deque()
        self.call = None           # {'id','kind','role','state'} while a call is ringing or active
        self._ring_task = None
        self._ice_count = 0
        await self.accept()
        await matchmaker.register(self)

    async def disconnect(self, code):
        if not hasattr(self, "sid"):
            return
        await self.clear_call()
        await self.leave_partner()
        await matchmaker.unregister(self)

    # ---------- helpers ----------
    async def send_json(self, obj):
        await self.send(text_data=json.dumps(obj))

    async def to_partner(self, payload, unpair=False):
        if self.partner:
            await self.channel_layer.send(self.partner, {
                "type": "relay", "from": self.channel_name,
                "unpair": unpair, "payload": payload,
            })

    async def leave_partner(self):
        await self.clear_call()          # leaving a person always ends any call with them
        if self.partner:
            await self.to_partner({"type": "partner_left"}, unpair=True)
        self.partner = self.partner_sid = None

    def rate_limited(self):
        now = time.monotonic()
        while self.sent_times and now - self.sent_times[0] > RATE_WINDOW_SECONDS:
            self.sent_times.popleft()
        if len(self.sent_times) >= RATE_MAX_MESSAGES:
            return True
        self.sent_times.append(now)
        return False

    # ---------- incoming ----------
    async def receive(self, text_data=None, bytes_data=None):
        try:
            data = json.loads(text_data or "")
        except ValueError:
            return
        if not isinstance(data, dict):
            return
        handler = {
            "find": self.on_find, "next": self.on_find, "end": self.on_end,
            "message": self.on_message, "typing": self.on_typing,
            "block": self.on_block, "report": self.on_report,
            "call_request": self.on_call_request, "call_accept": self.on_call_accept,
            "call_decline": self.on_call_decline, "call_cancel": self.on_call_cancel,
            "call_end": self.on_call_end,
            "call_offer": self.on_call_signal, "call_answer": self.on_call_signal,
            "call_ice": self.on_call_signal, "call_media": self.on_call_signal,
        }.get(data.get("type"))
        if handler:
            await handler(data)

    async def on_find(self, data):
        await self.leave_partner()
        if "interests" in data:
            self.interests = clean_interests(data.get("interests"))
        if data.get("mood") in MOOD_KEYS:
            self.mood = data["mood"]
        other = matchmaker.pair(self)
        await self.send_json({"type": "searching"})
        if other:
            await self.connect_pair(other)

    async def connect_pair(self, other):
        self.partner, self.partner_sid = other.channel_name, other.sid
        other.partner, other.partner_sid = self.channel_name, self.sid
        shared = sorted(set(self.interests) & set(other.interests))
        await self.send_json({"type": "matched", "partner": {
            "nickname": other.nick, "mood": other.mood, "shared": shared}})
        await self.channel_layer.send(other.channel_name, {
            "type": "relay", "from": self.channel_name,
            "payload": {"type": "matched", "partner": {
                "nickname": self.nick, "mood": self.mood, "shared": shared}},
        })

    async def on_end(self, data):
        matchmaker.dequeue(self)
        await self.leave_partner()
        await self.send_json({"type": "ended"})

    async def on_message(self, data):
        if not self.partner:
            return
        text = data.get("text")
        if not isinstance(text, str):
            return
        text = text.strip()[:MAX_MESSAGE_LEN]
        if not text:
            return
        if self.rate_limited():
            await self.send_json({"type": "error", "code": "rate_limit",
                                  "message": "You're sending messages too fast. Slow down a little."})
            return
        await self.to_partner({"type": "message", "text": text, "ts": int(time.time() * 1000)})

    async def on_typing(self, data):
        await self.to_partner({"type": "typing", "on": bool(data.get("on"))})

    async def on_block(self, data):
        if self.partner_sid:
            matchmaker.block(self.sid, self.partner_sid) # Keeps it in memory
            await self.save_block(self.sid, self.partner_sid) # SAVES TO DATABASE
        await self.leave_partner()
        await self.send_json({"type": "blocked"})

    async def on_report(self, data):
        reason = data.get("reason")
        details = data.get("details")
        details = details.strip()[:500] if isinstance(details, str) else ""
        if reason not in dict(Report.REASONS) or not self.partner_sid:
            return
        await self.save_report(reason, details)
        matchmaker.block(self.sid, self.partner_sid)
        await self.leave_partner()
        await self.send_json({"type": "reported"})

    @database_sync_to_async
    def save_report(self, reason, details):
        Report.objects.create(reporter_id=self.sid, reported_id=self.partner_sid,
                              reason=reason, details=details)

    @database_sync_to_async
    def save_block(self, owner_sid, blocked_sid):
        Block.objects.get_or_create(owner=owner_sid, blocked=blocked_sid)

    # ---------- voice / video calls ----------
    # The server only passes small signaling messages between the two matched people.
    # A call exists only while both are paired; every message must carry the call's random id,
    # and messages from anyone who isn't the current partner are dropped before they get here.
    def my_call(self, call_id, *, role=None, state=None):
        c = self.call
        if not c or c["id"] != call_id:
            return None
        if role and c["role"] != role:
            return None
        if state and c["state"] != state:
            return None
        return c

    async def clear_call(self):
        self.call = None
        self._ice_count = 0
        if self._ring_task:
            self._ring_task.cancel()
            self._ring_task = None

    async def call_error(self, code, message):
        await self.send_json({"type": "call_error", "code": code, "message": message})

    async def on_call_request(self, data):
        kind = data.get("kind")
        if kind not in CALL_KINDS:
            return
        if not self.partner:
            await self.call_error("no_partner", "You need to be chatting with someone to start a call.")
            return
        if self.call:
            await self.call_error("busy", "You're already in a call.")
            return
        call_id = uuid.uuid4().hex
        self.call = {"id": call_id, "kind": kind, "role": "caller", "state": "ringing"}
        await self.send_json({"type": "call_ringing", "id": call_id, "kind": kind})
        await self.to_partner({"type": "call_incoming", "id": call_id, "kind": kind})
        self._ring_task = asyncio.ensure_future(self._ring_timeout(call_id))

    async def _ring_timeout(self, call_id):
        try:
            await asyncio.sleep(RING_SECONDS)
        except asyncio.CancelledError:
            return
        if self.my_call(call_id, role="caller", state="ringing"):
            self.call = None
            self._ring_task = None
            await self.to_partner({"type": "call_cancelled", "id": call_id, "reason": "no_answer"})
            await self.send_json({"type": "call_closed", "id": call_id, "reason": "no_answer"})

    async def on_call_accept(self, data):
        c = self.my_call(data.get("id"), role="callee", state="ringing")
        if not c or not self.partner:
            return
        c["state"] = "active"
        await self.to_partner({"type": "call_accepted", "id": c["id"]})

    async def on_call_decline(self, data):
        c = self.my_call(data.get("id"), role="callee", state="ringing")
        if not c or not self.partner:
            return
        reason = data.get("reason") if data.get("reason") in DECLINE_REASONS else "declined"
        await self.clear_call()
        await self.to_partner({"type": "call_declined", "id": c["id"], "reason": reason})

    async def on_call_cancel(self, data):
        c = self.my_call(data.get("id"), role="caller", state="ringing")
        if not c:
            return
        await self.clear_call()
        await self.to_partner({"type": "call_cancelled", "id": c["id"], "reason": "cancelled"})

    async def on_call_end(self, data):
        c = self.my_call(data.get("id"))
        if not c:
            return
        reason = data.get("reason") if data.get("reason") in END_REASONS else "hangup"
        await self.clear_call()
        await self.to_partner({"type": "call_ended", "id": c["id"], "reason": reason})

    async def on_call_signal(self, data):
        """offer / answer / ICE candidates / mic+camera state: only inside an accepted call."""
        c = self.my_call(data.get("id"), state="active")
        if not c or not self.partner:
            return
        kind = data.get("type")
        if kind == "call_offer" and c["role"] == "caller":
            sdp = clean_sdp(data.get("sdp"), "offer")
            out = {"type": "call_offer", "id": c["id"], "sdp": sdp} if sdp else None
        elif kind == "call_answer" and c["role"] == "callee":
            sdp = clean_sdp(data.get("sdp"), "answer")
            out = {"type": "call_answer", "id": c["id"], "sdp": sdp} if sdp else None
        elif kind == "call_ice":
            cand = clean_candidate(data.get("candidate"))
            self._ice_count += 1
            out = ({"type": "call_ice", "id": c["id"], "candidate": cand}
                   if cand and self._ice_count <= MAX_ICE_PER_CALL else None)
        elif kind == "call_media":
            out = {"type": "call_media", "id": c["id"],
                   "mic": bool(data.get("mic")), "cam": bool(data.get("cam"))}
        else:
            out = None
        if out:
            await self.to_partner(out)

    async def on_peer_call_event(self, p):
        """Called for every call_* message that arrives from the current partner.
        Returns True if it should be passed on to this person's browser."""
        t, cid = p.get("type"), p.get("id")
        if t == "call_incoming":
            if self.call or p.get("kind") not in CALL_KINDS or not isinstance(cid, str):
                await self.to_partner({"type": "call_declined", "id": cid, "reason": "busy"})
                return False
            self.call = {"id": cid, "kind": p["kind"], "role": "callee", "state": "ringing"}
            return True
        if not self.call or self.call["id"] != cid:
            return False                                   # not about our call: ignore it
        c = self.call
        if t == "call_accepted":
            if c["role"] != "caller" or c["state"] != "ringing":
                return False
            c["state"] = "active"
            if self._ring_task:
                self._ring_task.cancel()
                self._ring_task = None
            return True
        if t in ("call_declined", "call_cancelled", "call_ended"):
            await self.clear_call()
            return True
        if t in ("call_offer", "call_answer", "call_ice", "call_media"):
            return c["state"] == "active"
        return False

    # ---------- channel-layer events ----------
    async def relay(self, event):
        if event.get("unpair"):
            if self.partner == event.get("from"):
                self.partner = self.partner_sid = None
                await self.clear_call()
                await self.send_json(event["payload"])
            return
        if not event.get("system") and event.get("from") != self.partner:
            return  # stale message from someone we're no longer paired with
        payload = event["payload"]
        if not event.get("system") and str(payload.get("type", "")).startswith("call_"):
            if not await self.on_peer_call_event(payload):
                return
        await self.send_json(payload)