import json
import time
from collections import deque

from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from . import presence, services


class DMConsumer(AsyncWebsocketConsumer):
    """Live private messaging for signed-in users. Messages are saved via services.send_dm."""

    async def connect(self):
        s = self.scope.get("session")
        if not s or not s.get("registered") or not s.get("uid"):
            await self.close(code=4401)
            return
        self.uid = s["uid"]
        self.group = f"user_{self.uid}"
        self.sent = deque()
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()
        if presence.add(self.uid):
            await self.announce(True)

    async def disconnect(self, code):
        if not hasattr(self, "uid"):
            return
        await self.channel_layer.group_discard(self.group, self.channel_name)
        if presence.remove(self.uid):
            await self.announce(False)

    async def announce(self, online):
        for fid in await sync_to_async(services.get_store().friend_ids)(self.uid):
            await self.channel_layer.group_send(f"user_{fid}", {"type": "push", "payload": {
                "type": "presence", "uid": self.uid, "online": online}})

    def rate_limited(self):
        now = time.monotonic()
        while self.sent and now - self.sent[0] > 5:
            self.sent.popleft()
        if len(self.sent) >= 8:
            return True
        self.sent.append(now)
        return False

    async def receive(self, text_data=None, bytes_data=None):
        try:
            data = json.loads(text_data or "")
        except ValueError:
            return
        if not isinstance(data, dict) or not isinstance(data.get("to", data.get("with")), str):
            return
        kind = data.get("type")
        if kind == "dm":
            await self.on_dm(data["to"], data.get("text"))
        elif kind == "typing":
            if await sync_to_async(services.are_friends)(self.uid, data["to"]):
                await self.channel_layer.group_send(f"user_{data['to']}", {"type": "push", "payload": {
                    "type": "typing", "uid": self.uid, "on": bool(data.get("on"))}})
        elif kind == "read":
            await sync_to_async(services.mark_read)(self.uid, data["with"])
            await self.channel_layer.group_send(self.group, {"type": "push", "payload": {
                "type": "read", "with": data["with"]}})

    async def on_dm(self, to, text):
        if self.rate_limited():
            await self.send_error("You're sending messages too fast.")
            return
        try:
            msg = await sync_to_async(services.send_dm)(self.uid, to, text)
        except services.ServiceError as exc:
            await self.send_error(str(exc))
            return
        for uid in (self.uid, to):
            await self.channel_layer.group_send(f"user_{uid}", {"type": "push", "payload": {
                "type": "dm", "message": msg, "with": to if uid == self.uid else self.uid}})

    async def send_error(self, message):
        await self.send(text_data=json.dumps({"type": "error", "message": message}))

    async def push(self, event):
        await self.send(text_data=json.dumps(event["payload"]))
