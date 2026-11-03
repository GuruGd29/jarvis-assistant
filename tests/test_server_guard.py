"""The checks the app makes on a server (JARVIS_HOSTS set): only its own address, no changes from other websites,
push sign-ups only for real push services. No server, network or database.

  .venv/bin/python -m unittest tests.test_server_guard
"""
import unittest
from unittest import mock

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from jarvis import config
from jarvis.web import notify
from jarvis.web.server import ServerGuard


def ok(request):
    return PlainTextResponse("ok")


class Guard(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(config, "HOSTS", ["10.8.0.1"])
        patcher.start()
        self.addCleanup(patcher.stop)
        app = Starlette(routes=[Route("/api/x", ok, methods=["GET", "POST"])], middleware=[Middleware(ServerGuard)])
        self.client = TestClient(app, base_url="https://10.8.0.1")

    def test_its_own_address_and_the_server_itself(self):
        self.assertEqual(self.client.get("/api/x").status_code, 200)
        self.assertEqual(self.client.post("/api/x", headers={"Origin": "https://10.8.0.1",
                                                             "Sec-Fetch-Site": "same-origin"}).status_code, 200)
        self.assertEqual(self.client.get("/api/x", headers={"Host": "127.0.0.1:8791"}).status_code, 200)

    def test_other_addresses_are_refused(self):
        # a web page whose name was pointed at the server (DNS rebinding) arrives with its own name
        self.assertEqual(self.client.get("/api/x", headers={"Host": "evil.example:443"}).status_code, 421)

    def test_changes_from_other_websites_are_refused(self):
        self.assertEqual(self.client.post("/api/x", headers={"Origin": "https://evil.example"}).status_code, 403)
        self.assertEqual(self.client.post("/api/x", headers={"Sec-Fetch-Site": "cross-site"}).status_code, 403)
        # reading is left alone: the browser itself keeps other websites from seeing the answer
        self.assertEqual(self.client.get("/api/x", headers={"Sec-Fetch-Site": "cross-site"}).status_code, 200)

    def test_push_sign_ups_only_for_push_services(self):
        keys = {"p256dh": "k", "auth": "a"}
        with self.assertRaisesRegex(ValueError, "push service"):
            notify.subscribe({"endpoint": "https://169.254.169.254/latest", "keys": keys}, None)
        with mock.patch.object(notify, "connect") as connect:
            notify.subscribe({"endpoint": "https://web.push.apple.com/QAbc", "keys": keys}, "iPhone")
            notify.subscribe({"endpoint": "https://fcm.googleapis.com/fcm/send/abc", "keys": keys}, "Android")
            self.assertEqual(connect.call_count, 2)


if __name__ == "__main__":
    unittest.main()
