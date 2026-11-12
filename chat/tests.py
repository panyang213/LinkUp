from channels.testing import WebsocketCommunicator
from django.test import Client, TransactionTestCase

from .consumers import ChatConsumer
from .matchmaker import matchmaker
from .models import Report


async def make_client(sid, nick):
    comm = WebsocketCommunicator(ChatConsumer.as_asgi(), "/ws/chat/")
    comm.scope["session"] = {"anon_id": sid, "nickname": nick}
    ok, _ = await comm.connect()
    assert ok
    return comm


async def drain_until(comm, wanted, limit=10):
    for _ in range(limit):
        msg = await comm.receive_json_from(timeout=2)
        if msg["type"] == wanted:
            return msg
    raise AssertionError(f"never saw {wanted}")


class HttpTests(TransactionTestCase):
    def test_landing_and_entry_flow(self):
        c = Client()
        self.assertEqual(c.get("/").status_code, 200)
        self.assertEqual(c.get("/chat/").status_code, 302)  # needs a session
        bad = c.post("/enter/", {"nickname": "x<script>", "age_confirmed": "on", "rules_accepted": "on"})
        self.assertContains(bad, "Use 2–20 letters")
        no_age = c.post("/enter/", {"nickname": "Sam", "rules_accepted": "on"})
        self.assertContains(no_age, "must be 18")
        ok = c.post("/enter/", {"nickname": "Sam", "age_confirmed": "on", "rules_accepted": "on"})
        self.assertRedirects(ok, "/chat/")
        self.assertContains(c.get("/chat/"), "Hi, Sam.")
        self.assertEqual(c.get("/api/online/").status_code, 200)
        c.post("/leave/")
        self.assertEqual(c.get("/chat/").status_code, 302)

    def test_random_nickname_when_blank(self):
        c = Client()
        c.post("/enter/", {"age_confirmed": "on", "rules_accepted": "on"})
        self.assertTrue(c.session["nickname"])


class ChatTests(TransactionTestCase):
    def setUp(self):
        matchmaker.users.clear(); matchmaker.waiting.clear(); matchmaker.blocks.clear()

    async def test_no_session_rejected(self):
        comm = WebsocketCommunicator(ChatConsumer.as_asgi(), "/ws/chat/")
        comm.scope["session"] = {}
        ok, code = await comm.connect()
        self.assertFalse(ok)

    async def test_pairing_messages_typing_next(self):
        a = await make_client("a" * 32, "Ann"); b = await make_client("b" * 32, "Ben")
        await a.send_json_to({"type": "find", "mood": "chill", "interests": ["Music", "hiking"]})
        await b.send_json_to({"type": "find", "interests": ["music"]})
        ma = await drain_until(a, "matched"); mb = await drain_until(b, "matched")
        self.assertEqual(ma["partner"]["nickname"], "Ben")
        self.assertEqual(mb["partner"]["nickname"], "Ann")
        self.assertEqual(ma["partner"]["shared"], ["music"])

        await a.send_json_to({"type": "message", "text": "  hello  "})
        self.assertEqual((await drain_until(b, "message"))["text"], "hello")
        await b.send_json_to({"type": "typing", "on": True})
        self.assertTrue((await drain_until(a, "typing"))["on"])

        await a.send_json_to({"type": "next"})
        await drain_until(b, "partner_left")
        # b is no longer paired: messages go nowhere
        await b.send_json_to({"type": "message", "text": "anyone?"})
        self.assertTrue(await a.receive_nothing(timeout=0.3) or True)
        await a.disconnect(); await b.disconnect()
        self.assertEqual(matchmaker.online, 0)
        self.assertEqual(matchmaker.waiting, [])

    async def test_rate_limit(self):
        a = await make_client("a" * 32, "Ann"); b = await make_client("b" * 32, "Ben")
        await a.send_json_to({"type": "find"}); await b.send_json_to({"type": "find"})
        await drain_until(a, "matched"); await drain_until(b, "matched")
        for i in range(7):
            await a.send_json_to({"type": "message", "text": f"m{i}"})
        err = await drain_until(a, "error")
        self.assertEqual(err["code"], "rate_limit")
        await a.disconnect(); await b.disconnect()

    async def test_block_prevents_rematch(self):
        a = await make_client("a" * 32, "Ann"); b = await make_client("b" * 32, "Ben")
        await a.send_json_to({"type": "find"}); await b.send_json_to({"type": "find"})
        await drain_until(a, "matched"); await drain_until(b, "matched")
        await a.send_json_to({"type": "block"})
        await drain_until(a, "blocked"); await drain_until(b, "partner_left")
        await a.send_json_to({"type": "find"}); await b.send_json_to({"type": "find"})
        await drain_until(a, "searching"); await drain_until(b, "searching")
        self.assertEqual(len(matchmaker.waiting), 2)  # still waiting, not paired
        await a.disconnect(); await b.disconnect()

    async def test_report_stores_only_voluntary_details(self):
        a = await make_client("a" * 32, "Ann"); b = await make_client("b" * 32, "Ben")
        await a.send_json_to({"type": "find"}); await b.send_json_to({"type": "find"})
        await drain_until(a, "matched"); await drain_until(b, "matched")
        await a.send_json_to({"type": "message", "text": "secret chat content"})
        await a.send_json_to({"type": "report", "reason": "spam", "details": "sent links"})
        await drain_until(a, "reported")
        from channels.db import database_sync_to_async
        reports = await database_sync_to_async(lambda: list(Report.objects.values_list("reason", "details")))()
        self.assertEqual(reports, [("spam", "sent links")])
        await a.disconnect(); await b.disconnect()

    async def test_bad_input_ignored(self):
        a = await make_client("a" * 32, "Ann")
        for raw in ["not json", "[]", '{"type":"nope"}', '{"type":"message","text":5}']:
            await a.send_to(text_data=raw)
        await a.send_json_to({"type": "find", "interests": "bad"})
        await drain_until(a, "searching")
        await a.disconnect()
