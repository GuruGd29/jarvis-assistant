"""End-to-end checks of the running app server (read-only: nothing is created, sent or changed).
Skipped when the server is not running.

  .venv/bin/python -m unittest tests.test_api        (JARVIS_WEB_URL to point elsewhere)
"""
import json
import os
import unittest
import urllib.error
import urllib.request

BASE = os.environ.get("JARVIS_WEB_URL", "http://127.0.0.1:8791")


def call(path, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(BASE + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read()


def running() -> bool:
    try:
        return call("/api/health")[0] in (200, 503)
    except OSError:
        return False


@unittest.skipUnless(running(), f"app server not running at {BASE}")
class Pages(unittest.TestCase):
    def test_shell_and_static_files(self):
        for path, kind in (("/", "text/html"), ("/sw.js", "javascript"), ("/manifest.webmanifest", "manifest+json"),
                           ("/static/app.js", "javascript"), ("/static/app.css", "text/css"),
                           ("/static/icons/apple-touch-icon.png", "image/png")):
            status, headers, _ = call(path)
            self.assertEqual(status, 200, path)
            self.assertIn(kind, headers.get("content-type", ""), path)

    def test_headers(self):
        _, headers, _ = call("/")
        self.assertIn("default-src 'self'", headers.get("content-security-policy", ""))
        self.assertEqual(headers.get("x-content-type-options"), "nosniff")
        self.assertEqual(call("/static/app.js")[1].get("cache-control"), "no-cache")  # updates reach the phone
        self.assertEqual(call("/api/settings")[1].get("cache-control"), "no-store")


@unittest.skipUnless(running(), f"app server not running at {BASE}")
class Data(unittest.TestCase):
    def get(self, path):
        status, _, body = call(path)
        self.assertEqual(status, 200, path)
        return json.loads(body)

    def test_health(self):
        health = self.get("/api/health")
        self.assertTrue(health["ok"], health)

    def test_today(self):
        today = self.get("/api/today")
        for key in ("date", "greeting", "events", "tasks", "medicines", "renewals", "spent_today", "calendars_connected"):
            self.assertIn(key, today)

    def test_money_every_period(self):
        for period in ("today", "week", "month", "year"):
            money = self.get(f"/api/money?period={period}")
            self.assertEqual(money["period"], period)
            self.assertGreaterEqual(money["spent"], 0)
            self.assertEqual(sum(c["payments"] for c in money["categories"]) >= 0, True)

    def test_more_settings_activity_chats(self):
        self.assertIn("facts", self.get("/api/more"))
        settings = self.get("/api/settings")
        self.assertEqual([k["kind"] for k in settings["kinds"]], ["reminders", "renewals", "problems", "reports", "replies"])
        self.assertIsInstance(self.get("/api/activity"), list)
        self.assertIsInstance(self.get("/api/chats"), list)
        self.assertEqual(len(self.get("/api/push/key")["key"]), 87)


@unittest.skipUnless(running(), f"app server not running at {BASE}")
class BadInput(unittest.TestCase):
    """Wrong requests get a clear 4xx with a JSON error, never a crash."""

    def check(self, status_expected, path, method="GET", body=None):
        status, _, raw = call(path, method, body)
        self.assertEqual(status, status_expected, path)
        self.assertIn("error", json.loads(raw), path)

    def test_rejected(self):
        self.check(404, "/api/chats/no-such-chat")
        self.check(404, "/api/chats/no-such-chat/send", "POST", {"text": "hi"})
        self.check(400, "/api/money?period=decade")
        self.check(400, "/api/medicine", "POST", {"status": "eaten"})
        self.check(400, "/api/settings", "PUT", {"quiet": {"from": "25:99"}})
        self.check(400, "/api/push/subscribe", "POST", {"endpoint": "not-a-url"})
        self.check(404, "/api/tasks/999999999/done", "POST", {"done": True})


if __name__ == "__main__":
    unittest.main()
