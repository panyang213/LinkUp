import json
import time
from collections import deque

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from .content import MOOD_KEYS
from .matchmaker import matchmaker
from .models import Report

MAX_MESSAGE_LEN = 1000
RATE_WINDOW_SECONDS = 5
RATE_MAX_MESSAGES = 6
MAX_INTERESTS = 5


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
        await self.accept()
        await matchmaker.register(self)

    async def disconnect(self, code):
        if not hasattr(self, "sid"):
            return
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
            matchmaker.block(self.sid, self.partner_sid)
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

    # ---------- channel-layer events ----------
    async def relay(self, event):
        if event.get("unpair"):
            if self.partner == event.get("from"):
                self.partner = self.partner_sid = None
                await self.send_json(event["payload"])
            return
        if not event.get("system") and event.get("from") != self.partner:
            return  # stale message from someone we're no longer paired with
        await self.send_json(event["payload"])
