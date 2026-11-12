"""Clearing Activity (More -> Activity -> Clear) and bringing it back with Undo. No database: notify is stood in for.

  .venv/bin/python -m unittest tests.test_activity
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from starlette.testclient import TestClient

from jarvis import config
from jarvis.web import login, notify, server

WHEN = "2026-11-12T09:30:00.123456+05:30"


class ClearTest(unittest.TestCase):
    def setUp(self):
        folder = Path(tempfile.mkdtemp())  # no sign-in set up, so the app answers from this computer
        for patch in [mock.patch.object(config, "SECRETS_DIR", folder),
                      mock.patch.object(login, "PASSWORD_FILE", folder / "web-password"),
                      mock.patch.object(login, "KEY_FILE", folder / "web-session.key"),
                      mock.patch.object(login, "GOOGLE_FILE", folder / "google-login.json"),
                      mock.patch.object(login, "SIRI_KEY_FILE", folder / "siri-key")]:
            patch.start()
            self.addCleanup(patch.stop)
        self.client = TestClient(server.app, base_url="https://127.0.0.1")

    def test_clear_hides_everything_and_says_how_to_undo(self):
        with mock.patch.object(notify, "clear_activity", return_value={"cleared": 3, "undo": WHEN}) as clear:
            r = self.client.delete("/api/activity")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"cleared": 3, "undo": WHEN})
        clear.assert_called_once_with()

    def test_undo_brings_back_that_clear(self):
        with mock.patch.object(notify, "undo_clear", return_value=3) as undo:
            r = self.client.post("/api/activity/undo", json={"undo": WHEN})
        self.assertEqual(r.json(), {"restored": 3})
        undo.assert_called_once_with(WHEN)

    def test_undo_without_a_time_changes_nothing(self):
        with mock.patch.object(notify, "connect", side_effect=AssertionError("the database was touched")):
            for body in [{}, {"undo": None}, {"undo": "yesterday"}, {"undo": "2026-11-12T09:30:00"}]:
                r = self.client.post("/api/activity/undo", json=body)
                self.assertEqual((r.status_code, r.json()), (400, {"error": "nothing to undo"}), body)

    def test_reading_and_marking_read_still_work(self):
        with mock.patch.object(notify, "activity", return_value=[]) as listing, \
                mock.patch.object(notify, "mark_read") as mark_read, \
                mock.patch.object(notify, "clear_activity", side_effect=AssertionError("cleared")):
            self.assertEqual(self.client.get("/api/activity").json(), [])
            self.assertEqual(self.client.post("/api/activity").json(), [])
        mark_read.assert_called_once_with()
        self.assertEqual(listing.call_count, 2)


if __name__ == "__main__":
    unittest.main()
