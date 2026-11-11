"""Asking Jarvis from Siri or a Shortcut (docs/siri.md): the key, /api/ask, and the text Siri reads out."""
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from starlette.testclient import TestClient

from jarvis import config
from jarvis.web import hermes, login, notify, server


class SpokenTest(unittest.TestCase):
    def test_markdown_is_read_as_words(self):
        reply = "**Your total** is ₹1,200.\n\n- Food: ₹800\n- *Travel*: ₹400\n\n### Notes\n1. See [the bill](https://x.y)."
        self.assertEqual(server.spoken(reply), "Your total is ₹1,200.\n\nFood: ₹800\nTravel: ₹400\n\nNotes\nSee the bill.")

    def test_sums_and_plain_text_stay(self):
        self.assertEqual(server.spoken("2 * 3 = 6"), "2 * 3 = 6")
        self.assertEqual(server.spoken("Good morning!"), "Good morning!")


class AskTest(unittest.TestCase):
    def setUp(self):
        folder = Path(tempfile.mkdtemp())
        self.patches = [
            mock.patch.object(config, "SECRETS_DIR", folder),
            mock.patch.object(login, "PASSWORD_FILE", folder / "web-password"),
            mock.patch.object(login, "KEY_FILE", folder / "web-session.key"),
            mock.patch.object(login, "GOOGLE_FILE", folder / "google-login.json"),
            mock.patch.object(login, "SIRI_KEY_FILE", folder / "siri-key"),
            mock.patch.object(login, "_throttle", login.Throttle()),
            mock.patch.object(login, "_key_throttle", login.Throttle()),
            mock.patch.object(server, "_new_chat_id", mock.AsyncMock(return_value="chat-1")),
            mock.patch.object(server, "_touch_chat", lambda *args: None),
            mock.patch.object(notify, "notify", mock.Mock()),
        ]
        for patch in self.patches:
            patch.start()
            self.addCleanup(patch.stop)
        login.set_password("a long test password")
        self.key = login.new_siri_key()
        self.client = TestClient(server.app, base_url="https://127.0.0.1", follow_redirects=False)

    def answer(self, text="Two meetings today.", delay=0.0):
        async def stream_turn(session_id, question, read_timeout=600):
            await asyncio.sleep(delay)
            yield {"t": "done", "text": text}
        return mock.patch.object(hermes, "stream_turn", stream_turn)

    def ask(self, key=None, text="What's on today?"):
        headers = {"Authorization": f"Bearer {key or self.key}"}
        return self.client.post("/api/ask", json={"text": text}, headers=headers)

    def test_answer_with_the_key(self):
        with self.answer("**Two** meetings today."):
            reply = self.ask()
        self.assertEqual(reply.status_code, 200)
        self.assertEqual(reply.json(), {"reply": "Two meetings today.", "chat": "chat-1"})

    def test_key_file_holds_only_a_hash(self):
        stored = login.SIRI_KEY_FILE.read_text()
        self.assertNotIn(self.key, stored)
        self.assertEqual(login.SIRI_KEY_FILE.stat().st_mode & 0o777, 0o600)

    def test_wrong_or_missing_key(self):
        with self.answer():
            wrong = self.ask(key="jarvis_not-the-key")
            self.assertEqual(wrong.status_code, 401)
            self.assertIn("Siri key isn't right", wrong.json()["reply"])
            self.assertEqual(self.client.post("/api/ask", json={"text": "hi"}).status_code, 401)  # no key, no sign-in

    def test_key_opens_only_ask(self):
        headers = {"Authorization": f"Bearer {self.key}"}
        for path in ("/api/today", "/api/more", "/api/siri"):
            self.assertEqual(self.client.get(path, headers=headers).status_code, 401, path)

    def test_new_key_replaces_the_old(self):
        old, self.key = self.key, login.new_siri_key()
        with self.answer():
            self.assertEqual(self.ask(key=old).status_code, 401)
            self.assertEqual(self.ask().status_code, 200)

    def test_turned_off(self):
        login.remove_siri_key()
        with self.answer():
            self.assertEqual(self.ask().status_code, 401)

    def test_guessing_keys_slows_down(self):
        with self.answer():
            for _ in range(5):
                self.ask(key="jarvis_guess")
            blocked = self.ask()  # even the right key waits now
        self.assertEqual(blocked.status_code, 429)
        self.assertIn("Too many wrong Siri keys", blocked.json()["reply"])

    def test_slow_answer_comes_later(self):
        with self.answer(delay=1.0), mock.patch.object(config, "SIRI_WAIT", 0.2):
            reply = self.ask()
        self.assertEqual(reply.status_code, 200)
        self.assertTrue(reply.json()["pending"])
        self.assertIn("notification", reply.json()["reply"])

    def test_jarvis_down_is_spoken(self):
        failing = mock.AsyncMock(side_effect=server.httpx.ConnectError("refused"))
        with mock.patch.object(server, "_new_chat_id", failing):
            reply = TestClient(server.app, base_url="https://127.0.0.1", raise_server_exceptions=False).post(
                "/api/ask", json={"text": "hi"}, headers={"Authorization": f"Bearer {self.key}"})
        self.assertEqual(reply.status_code, 503)
        self.assertIn("restarting", reply.json()["reply"])

    def test_empty_question(self):
        self.assertIn("didn't catch", self.ask(text="  ").json()["reply"])

    def test_signed_in_app_makes_and_turns_off_keys(self):
        self.assertEqual(self.client.post("/login", data={"password": "a long test password"}).status_code, 303)
        status = self.client.get("/api/siri").json()
        self.assertEqual(status, {"on": True, "url": "https://127.0.0.1/api/ask"})
        made = self.client.post("/api/siri").json()
        self.assertTrue(made["key"].startswith("jarvis_") and made["on"])
        self.assertEqual(self.client.delete("/api/siri").json(), {"on": False})
        self.assertFalse(login.siri_key_on())


if __name__ == "__main__":
    unittest.main()
