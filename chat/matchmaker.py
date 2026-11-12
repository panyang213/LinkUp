"""In-memory matchmaking for anonymous chat.

Everything here lives in this process's RAM only. Nothing is written to disk and no
message content ever passes through this module. When a user disconnects, their
entry is removed.

NOTE for production: the waiting queue is per-process. If you run several server
processes, move the queue into Redis (the channel layer already uses Redis).
"""
from channels.layers import get_channel_layer

MAX_BLOCK_ENTRIES = 5000


class Matchmaker:
    def __init__(self):
        self.users = {}    # channel_name -> consumer (everyone connected)
        self.waiting = []  # consumers currently searching
        self.blocks = {}   # session id -> set of session ids they blocked

    @property
    def online(self):
        return len(self.users)

    async def register(self, consumer):
        self.users[consumer.channel_name] = consumer
        await self.broadcast_online()

    async def unregister(self, consumer):
        self.users.pop(consumer.channel_name, None)
        self.dequeue(consumer)
        await self.broadcast_online()

    def dequeue(self, consumer):
        if consumer in self.waiting:
            self.waiting.remove(consumer)

    def is_blocked(self, a, b):
        return b.sid in self.blocks.get(a.sid, ()) or a.sid in self.blocks.get(b.sid, ())

    def block(self, blocker_sid, blocked_sid):
        if len(self.blocks) < MAX_BLOCK_ENTRIES:
            self.blocks.setdefault(blocker_sid, set()).add(blocked_sid)

    def pair(self, consumer):
        """Return the best waiting partner (removing them from the queue), or queue
        `consumer` and return None. Has no awaits, so it can't be interleaved."""
        best, best_score = None, -1
        for other in self.waiting:
            if other is consumer or other.sid == consumer.sid:
                continue
            if self.is_blocked(consumer, other):
                continue
            score = len(set(consumer.interests) & set(other.interests))
            if score > best_score:
                best, best_score = other, score
        if best:
            self.waiting.remove(best)
            return best
        if consumer not in self.waiting:
            self.waiting.append(consumer)
        return None

    async def broadcast_online(self):
        layer = get_channel_layer()
        payload = {"type": "online", "count": self.online}
        for channel in list(self.users):
            await layer.send(channel, {"type": "relay", "system": True, "payload": payload})


matchmaker = Matchmaker()
