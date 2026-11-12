import json
from unittest import mock

from asgiref.sync import sync_to_async
from channels.testing import WebsocketCommunicator
from django.test import Client, TransactionTestCase

from . import presence, services, store
from .consumers_dm import DMConsumer
from .models import Report

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 50
PROFILE = {"nickname": "Ann", "age": "25", "gender": "female", "bio": "Hi there",
           "interests": "Music, Hiking", "visibility": "public"}


def fresh_store():
    store._store = store.MemoryStore()
    presence._conns.clear()
    return store._store


def signin(uid, nickname=None, **over):
    """Log a test client in through the real /auth/google/ view (token check mocked)."""
    c = Client()
    with mock.patch("chat.views_app.firebase_auth.verify_google_token",
                    return_value={"uid": uid, "email": f"{uid}@example.com"}):
        r = c.post("/auth/google/", json.dumps({"id_token": "x"}), content_type="application/json")
    assert r.status_code == 200, r.content
    if nickname:
        data = dict(PROFILE, nickname=nickname, **over)
        r = c.post("/profile/save/", data)
        assert r.status_code == 302, r.content
    return c


def post(c, url, body):
    return c.post(url, json.dumps(body), content_type="application/json")


class LoginAndProfileTests(TransactionTestCase):
    def setUp(self):
        fresh_store()

    def test_bad_token_rejected(self):
        from .firebase_auth import AuthError
        with mock.patch("chat.views_app.firebase_auth.verify_google_token", side_effect=AuthError("nope")):
            r = Client().post("/auth/google/", json.dumps({"id_token": "bad"}), content_type="application/json")
        self.assertEqual(r.status_code, 401)

    def test_login_then_profile_modal_then_dashboard(self):
        c = signin("u1")
        page = c.get("/dashboard/")
        self.assertContains(page, "Set up your profile")
        self.assertEqual(c.get("/friends/").status_code, 302)           # profile first
        self.assertEqual(c.get("/chat/").status_code, 302)
        bad = c.post("/profile/save/", dict(PROFILE, age="17"))
        self.assertContains(bad, "must be 18")
        ok = c.post("/profile/save/", PROFILE)
        self.assertRedirects(ok, "/dashboard/")
        self.assertContains(c.get("/dashboard/"), "Welcome back, Ann.")
        self.assertEqual(c.get("/chat/").status_code, 200)               # random chat uses profile nickname

    def test_photo_validation_and_upload(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        c = signin("u1")
        bad = c.post("/profile/save/", dict(PROFILE, photo=SimpleUploadedFile("a.png", b"not an image")))
        self.assertContains(bad, "JPEG, PNG or WebP")
        c.post("/profile/save/", dict(PROFILE, photo=SimpleUploadedFile("a.png", PNG)))
        self.assertEqual(services.get_profile("u1")["photo_url"], "/avatar/u1/")
        self.assertEqual(c.get("/avatar/u1/").status_code, 200)

    def test_email_never_exposed(self):
        a, b = signin("u1", "Ann"), signin("u2", "Bob")
        self.assertIn("u1@example.com", str(store._store.users["u1"]))      # stored privately
        for url in ("/api/users/search/?q=an", "/u/u1/"):
            body = b.get(url).content.decode()
            self.assertNotIn("example.com", body)


class AnonymousBlockedTests(TransactionTestCase):
    def setUp(self):
        fresh_store()
        self.anon = Client()
        self.anon.post("/enter/", {"nickname": "Anon", "age_confirmed": "on", "rules_accepted": "on"})

    def test_pages_redirect(self):
        for url in ("/dashboard/", "/friends/", "/messages/", "/profile/", "/u/u1/"):
            self.assertEqual(self.anon.get(url).status_code, 302, url)

    def test_api_returns_401(self):
        for url in ("/api/users/search/?q=ann", "/api/friends/", "/api/messages/u1/", "/api/notifications/"):
            self.assertEqual(self.anon.get(url).status_code, 401, url)
        for url in ("/api/friends/request/", "/api/friends/respond/", "/api/block/", "/api/report/",
                    "/api/messages/u1/delete/"):
            self.assertEqual(post(self.anon, url, {"uid": "u1"}).status_code, 401, url)

    async def test_anonymous_cannot_open_dm_socket(self):
        comm = WebsocketCommunicator(DMConsumer.as_asgi(), "/ws/dm/")
        comm.scope["session"] = {"anon_id": "abc", "nickname": "Anon"}
        ok, _ = await comm.connect()
        self.assertFalse(ok)

    def test_anonymous_chat_leaves_nothing_in_store(self):
        self.assertEqual(store._store.users, {})
        self.assertEqual(store._store.convs, {})


class FriendTests(TransactionTestCase):
    def setUp(self):
        fresh_store()
        self.a, self.b = signin("u1", "Ann"), signin("u2", "Bob")

    def test_search_request_accept_remove(self):
        res = self.a.get("/api/users/search/?q=bo").json()["results"]
        self.assertEqual([r["nickname"] for r in res], ["Bob"])
        self.assertEqual(post(self.a, "/api/friends/request/", {"uid": "u2"}).status_code, 200)
        self.assertEqual(post(self.a, "/api/friends/request/", {"uid": "u2"}).status_code, 400)  # duplicate
        notes = self.b.get("/api/notifications/").json()["notifications"]
        self.assertIn("Ann sent you a friend request", notes[0]["text"])
        incoming = self.b.get("/api/friends/").json()["incoming"]
        self.assertEqual(len(incoming), 1)
        # only the recipient can answer
        self.assertEqual(post(self.a, "/api/friends/respond/", {"request_id": "u1_u2", "accept": True}).status_code, 400)
        self.assertEqual(post(self.b, "/api/friends/respond/", {"request_id": "u1_u2", "accept": True}).status_code, 200)
        self.assertEqual([f["nickname"] for f in self.a.get("/api/friends/").json()["friends"]], ["Bob"])
        self.assertIn("Bob accepted", self.a.get("/api/notifications/").json()["notifications"][0]["text"])
        post(self.a, "/api/friends/remove/", {"uid": "u2"})
        self.assertEqual(self.b.get("/api/friends/").json()["friends"], [])

    def test_decline_and_resend(self):
        post(self.a, "/api/friends/request/", {"uid": "u2"})
        post(self.b, "/api/friends/respond/", {"request_id": "u1_u2", "accept": False})
        self.assertEqual(self.b.get("/api/friends/").json()["incoming"], [])
        self.assertEqual(post(self.a, "/api/friends/request/", {"uid": "u2"}).status_code, 200)

    def test_mutual_requests_become_friends(self):
        post(self.a, "/api/friends/request/", {"uid": "u2"})
        post(self.b, "/api/friends/request/", {"uid": "u1"})
        self.assertEqual(len(self.a.get("/api/friends/").json()["friends"]), 1)

    def test_block_hides_and_prevents(self):
        post(self.b, "/api/block/", {"uid": "u1"})
        self.assertEqual(self.a.get("/api/users/search/?q=bo").json()["results"], [])
        self.assertEqual(post(self.a, "/api/friends/request/", {"uid": "u2"}).status_code, 400)
        self.assertEqual(self.a.get("/u/u2/").status_code, 404)

    def test_private_profile_not_searchable_and_cannot_add_self(self):
        c = signin("u3", "Cara", visibility="private")
        self.assertEqual(self.a.get("/api/users/search/?q=ca").json()["results"], [])
        self.assertEqual(self.a.get("/u/u3/").status_code, 404)
        self.assertEqual(post(c, "/api/friends/request/", {"uid": "u3"}).status_code, 400)

    def test_friends_only_hides_details_from_strangers(self):
        signin("u3", "Cara", visibility="friends")
        res = self.a.get("/api/users/search/?q=ca").json()["results"][0]
        self.assertFalse(res["full"]); self.assertNotIn("bio", res)

    def test_report_saved(self):
        post(self.a, "/api/report/", {"uid": "u2", "reason": "spam", "details": "links"})
        self.assertEqual(list(Report.objects.values_list("reporter_id", "reported_id", "reason")), [("u1", "u2", "spam")])
        self.assertEqual(post(self.a, "/api/report/", {"uid": "u2", "reason": "bogus"}).status_code, 400)


async def dm_client(uid):
    comm = WebsocketCommunicator(DMConsumer.as_asgi(), "/ws/dm/")
    comm.scope["session"] = {"registered": True, "uid": uid, "nickname": uid}
    ok, _ = await comm.connect()
    assert ok
    return comm


async def until(comm, kind, limit=10):
    for _ in range(limit):
        m = await comm.receive_json_from(timeout=2)
        if m["type"] == kind:
            return m
    raise AssertionError(kind)


class DirectMessageTests(TransactionTestCase):
    def setUp(self):
        self.st = fresh_store()
        for uid in ("u1", "u2", "u3"):
            self.st.user_set(uid, {"nickname": uid.upper(), "nickname_lower": uid, "visibility": "public"})
        self.st.friend_add("u1", "u2")

    async def test_live_delivery_saved_history_unread_delete(self):
        a, b = await dm_client("u1"), await dm_client("u2")
        await a.send_json_to({"type": "dm", "to": "u2", "text": " hello Bob "})
        got = await until(b, "dm")
        self.assertEqual((got["message"]["text"], got["with"]), ("hello Bob", "u1"))
        echo = await until(a, "dm")
        self.assertEqual(echo["with"], "u2")                                       # sender sees it too

        convs = await sync_to_async(services.list_conversations)("u2")
        self.assertEqual((convs[0]["profile"]["nickname"], convs[0]["unread"]), ("U1", 1))
        hist = await sync_to_async(services.history)("u2", "u1")                   # "past conversation"
        self.assertEqual([m["text"] for m in hist], ["hello Bob"])
        self.assertEqual((await sync_to_async(services.list_conversations)("u2"))[0]["unread"], 0)

        await b.send_json_to({"type": "typing", "to": "u1", "on": True})
        self.assertTrue((await until(a, "typing"))["on"])

        await sync_to_async(services.delete_conversation)("u1", "u2")              # delete for u1 only
        self.assertEqual(await sync_to_async(services.list_conversations)("u1"), [])
        self.assertEqual(len(await sync_to_async(services.list_conversations)("u2")), 1)
        await a.disconnect(); await b.disconnect()

    async def test_non_friend_rejected_and_rate_limited(self):
        a = await dm_client("u1")
        await a.send_json_to({"type": "dm", "to": "u3", "text": "hi stranger"})
        self.assertIn("friends", (await until(a, "error"))["message"])
        self.assertEqual(self.st.convs, {})
        for i in range(10):
            await a.send_json_to({"type": "dm", "to": "u2", "text": f"m{i}"})
        self.assertIn("too fast", (await until(a, "error"))["message"])
        await a.disconnect()

    async def test_presence_broadcast_to_friends(self):
        b = await dm_client("u2")
        a = await dm_client("u1")
        self.assertTrue((await until(b, "presence"))["online"])
        await a.disconnect()
        self.assertFalse((await until(b, "presence"))["online"])
        await b.disconnect()

    async def test_blocked_cannot_message(self):
        self.st.block_add("u2", "u1")
        a = await dm_client("u1")
        await a.send_json_to({"type": "dm", "to": "u2", "text": "hey"})
        await until(a, "error")
        await a.disconnect()
