"""Instant answers (jarvis/web/instant.py): which questions skip the model, what the answers say, and how they sit in
a chat. No database, calendar or model: those are stood in for.

  .venv/bin/python -m unittest tests.test_instant
"""
import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest import mock

from starlette.testclient import TestClient

from jarvis import calendars, config, health, money
from jarvis.web import hermes, instant, login, server

AGENDA = {"period": "TODAY, Thu 12 Nov", "sources": ["google", "apple"], "errors": {}, "events": [
    {"source": "google", "calendar": "Work", "title": "Standup", "all_day": False, "start": "2026-11-12 10:00",
     "end": "2026-11-12 10:15", "location": "Office"},
    {"source": "apple", "calendar": "Home", "title": "Diwali", "all_day": True, "start": "2026-11-12",
     "end": "2026-11-13", "location": None}]}


class WhichQuestions(unittest.TestCase):
    """Plain everyday questions are answered here; anything that needs thinking goes to the model."""

    def setUp(self):
        for name, target in [("calendar_answer", "calendar"), ("medicines_answer", "medicines"),
                             ("spending_answer", "spending")]:
            patch = mock.patch.object(instant, name, return_value=target)
            patch.start()
            self.addCleanup(patch.stop)
        for patch in [mock.patch.object(calendars, "list_events", return_value={k: AGENDA[k] for k in
                                                                                ("sources", "errors", "events")}),
                      mock.patch.object(health, "today_doses", return_value=[])]:
            patch.start()
            self.addCleanup(patch.stop)

    def test_plain_questions_get_an_instant_answer(self):
        for text, kind in [("What's on my calendar today?", "calendar"), ("Any meetings tomorrow?", "calendar"),
                           ("Am I busy this week?", "calendar"), ("Show my schedule for Friday", "calendar"),
                           ("Did I take my medicines today?", "medicines"), ("my tablets", "medicines"),
                           ("How much did I spend this week?", "spending"), ("What did I spend today?", "spending"),
                           ("How much did I spend last month?", "spending"),
                           ("How much did I spend in the last 7 days", "spending"),
                           ("inniki evlo selavu", "spending")]:
            self.assertEqual(instant.answer(text), kind, text)

    def test_questions_that_need_thinking_go_to_the_model(self):
        for text in ["Am I free at 4 tomorrow?", "Add a meeting tomorrow at 10", "Can I fit a haircut in my calendar?",
                     "Why is my calendar so full this week?", "Move my 3 pm meeting",
                     "How much did I spend on food this week?", "How much did I spend at Swiggy?",
                     "Did I spend more this week than last week?", "How much did I spend this week compared to last?",
                     "Which medicines did I miss this week?", "Add a medicine: Vitamin D at 9 am",
                     "Should I take my tablets after food?", "Hi", "Tell me a story", "",
                     "என் காலண்டரில் இன்று என்ன இருக்கிறது?",
                     "What's on my calendar today and can you also tell me what the weather will be like later?"]:
            self.assertIsNone(instant.answer(text), text)

    def test_no_calendar_connected_goes_to_the_model(self):
        with mock.patch.object(calendars, "list_events", return_value={"sources": [], "errors": {}, "events": []}):
            self.assertIsNone(instant.answer("What's on my calendar today?"))


class Answers(unittest.TestCase):
    def test_calendar_for_one_day(self):
        self.assertEqual(instant.calendar_answer(AGENDA),
                         "**Today, Thu 12 Nov**\n- 10:00–10:15 Standup · Office\n- all day Diwali")

    def test_calendar_for_several_days_shows_each_date_and_a_missing_calendar(self):
        agenda = {**AGENDA, "period": "the rest of this week, Thu 12 Nov to Sun 15 Nov",
                  "errors": {"apple": "timeout"}, "events": [{**AGENDA["events"][0], "start": "2026-11-13 10:00",
                                                              "end": "2026-11-13 10:15", "location": None}]}
        self.assertEqual(instant.calendar_answer(agenda),
                         "**The rest of this week, Thu 12 Nov to Sun 15 Nov**\n- Fri 13 Nov, 10:00–10:15 Standup\n"
                         "\nI couldn't read your Apple calendar just now, so this may be incomplete.")

    def test_empty_calendar_and_weekday(self):
        agenda = {**AGENDA, "period": "Friday, Fri 13 Nov", "events": []}
        self.assertEqual(instant.calendar_answer(agenda), "**Fri 13 Nov**\nNothing on your calendar.")

    def test_medicines(self):
        doses = [{"time": "08:00", "name": "Metformin", "dose": "500 mg", "status": "taken"},
                 {"time": "14:00", "name": "Vitamin D", "dose": None, "status": "due"},
                 {"time": "21:00", "name": "Atorvastatin", "dose": "10 mg", "status": "later"}]
        self.assertEqual(instant.medicines_answer(doses),
                         "**Today's medicines**\n- 08:00 Metformin 500 mg — taken ✓\n"
                         "- 14:00 Vitamin D — not answered yet\n- 21:00 Atorvastatin 10 mg — later today")
        self.assertEqual(instant.medicines_answer([]), "No medicines are scheduled for today.")

    def test_spending(self):
        summary = {"spending": ["a", "b", "c"], "spending_total": 1500.0, "refunds_total": 0.0,
                   "received_total": 200.0, "display": {"spending_total": "₹1,500.00", "refunds_total": "₹0.00",
                                                        "received_total": "₹200.00"}}
        cats = {"by_category": [{"category": "Food", "total": 1000.0}, {"category": "Travel", "total": 500.0}]}
        with mock.patch.object(money, "summary", return_value=summary), \
                mock.patch.object(money, "insights", return_value=cats), \
                mock.patch.object(config, "money", side_effect=lambda v, decimals=True: f"₹{v:,.0f}"):
            week = instant.spending_answer("2026-11-09", "2026-11-12", today=date(2026, 11, 12))
            day = instant.spending_answer("2026-11-12", "2026-11-12", today=date(2026, 11, 12))
        self.assertEqual(week, "You spent **₹1,500.00** from Mon 09 Nov to Thu 12 Nov, in 3 payments.\n"
                               "Most on: Food ₹1,000 · Travel ₹500\nReceived ₹200.00\n"
                               "_From bank alert emails; cash isn't included._")
        self.assertTrue(day.startswith("You spent **₹1,500.00** today, in 3 payments.\nReceived"), day)
        with mock.patch.object(money, "summary", return_value={**summary, "spending": []}):
            self.assertEqual(instant.spending_answer("2026-11-11", "2026-11-11", today=date(2026, 11, 12)),
                             "No spending in your bank alerts yesterday.")

    def test_today_doses_reads_answers_and_the_clock(self):
        meds = [{"id": 1, "name": "Metformin", "dose": "500 mg", "times": ["20:00", "08:00"], "weekdays": None,
                 "start_on": "2026-01-01", "end_on": None},
                {"id": 2, "name": "Weekly", "dose": None, "times": ["09:00"], "weekdays": [0], "start_on": "2026-01-01",
                 "end_on": None}]
        conn = mock.MagicMock()
        conn.__enter__.return_value.execute.return_value.fetchall.return_value = [
            {"medication_id": 1, "hhmm": "08:00", "status": "taken"}]
        with mock.patch.object(health, "list_medications", return_value=meds), \
                mock.patch.object(health, "_connect", return_value=conn):
            doses = health.today_doses(datetime(2026, 11, 12, 12, 0, tzinfo=health.TZ))  # a Thursday
        self.assertEqual([(d["time"], d["name"], d["status"]) for d in doses],
                         [("08:00", "Metformin", "taken"), ("20:00", "Metformin", "later")])


class InChat(unittest.TestCase):
    def setUp(self):
        folder = Path(tempfile.mkdtemp())  # no sign-in set up, so the app answers from this computer
        for patch in [mock.patch.object(config, "SECRETS_DIR", folder),
                      mock.patch.object(login, "PASSWORD_FILE", folder / "web-password"),
                      mock.patch.object(login, "KEY_FILE", folder / "web-session.key"),
                      mock.patch.object(login, "GOOGLE_FILE", folder / "google-login.json"),
                      mock.patch.object(login, "SIRI_KEY_FILE", folder / "siri-key"),
                      mock.patch.object(server, "_known_chat", return_value=True),
                      mock.patch.object(server, "_touch_chat")]:
            patch.start()
            self.addCleanup(patch.stop)
        self.client = TestClient(server.app, base_url="https://127.0.0.1")

    def test_an_instant_answer_never_reaches_the_model(self):
        with mock.patch.object(instant, "answer", return_value="**Today**\n- 10:00 Standup"), \
                mock.patch.object(instant, "save") as save, \
                mock.patch.object(hermes, "stream_turn", side_effect=AssertionError("the model was asked")):
            r = self.client.post("/api/chats/s1/send", json={"text": "What's on my calendar today?"})
        events = [json.loads(line) for line in r.text.splitlines()]
        self.assertEqual(events, [{"t": "tool", "label": instant.LABEL},
                                  {"t": "done", "text": "**Today**\n- 10:00 Standup"}])
        save.assert_called_once_with("s1", "What's on my calendar today?", "**Today**\n- 10:00 Standup")

    def test_other_questions_go_to_the_model_with_earlier_instant_answers(self):
        sent = []

        async def stream_turn(session_id, text):
            sent.append(text)
            yield {"t": "done", "text": "Tomorrow you have nothing."}

        note = "\n\n" + instant.NOTE_START + "\nQ: calendar today?\nA: Standup\n" + instant.NOTE_END
        with mock.patch.object(instant, "answer", return_value=None), \
                mock.patch.object(instant, "note_for_model", return_value=note), \
                mock.patch.object(hermes, "stream_turn", stream_turn):
            r = self.client.post("/api/chats/s1/send", json={"text": "and tomorrow?"})
        self.assertEqual(json.loads(r.text.splitlines()[-1]), {"t": "done", "text": "Tomorrow you have nothing."})
        self.assertEqual(sent, ["and tomorrow?" + note])
        self.assertEqual(instant.NOTE.sub("", sent[0]), "and tomorrow?")

    def test_a_broken_instant_answer_falls_back_to_the_model(self):
        async def stream_turn(session_id, text):
            yield {"t": "done", "text": "From the model"}

        with mock.patch.object(instant, "answer", side_effect=RuntimeError("calendar down")), \
                mock.patch.object(instant, "note_for_model", return_value=""), \
                mock.patch.object(hermes, "stream_turn", stream_turn):
            r = self.client.post("/api/chats/s1/send", json={"text": "What's on my calendar today?"})
        self.assertEqual(json.loads(r.text.splitlines()[-1])["text"], "From the model")

    def test_chat_shows_instant_answers_in_time_order(self):
        async def messages(session_id):
            return [{"role": "user", "text": "and tomorrow?", "at": 200.0},
                    {"role": "assistant", "text": "Nothing.", "tools": [], "at": 210.0}]

        answered = [{"role": "user", "text": "calendar today?", "at": 100.0},
                    {"role": "assistant", "text": "Standup", "tools": [instant.LABEL], "at": 100.001}]
        with mock.patch.object(hermes, "messages", messages), \
                mock.patch.object(instant, "messages", return_value=answered):
            got = self.client.get("/api/chats/s1").json()["messages"]
        self.assertEqual([m["text"] for m in got], ["calendar today?", "Standup", "and tomorrow?", "Nothing."])

    def test_siri_gets_the_instant_answer_spoken(self):
        with mock.patch.object(server, "_new_chat_id", mock.AsyncMock(return_value="s2")), \
                mock.patch.object(instant, "answer", return_value="**Today's medicines**\n- 08:00 Metformin — taken ✓"), \
                mock.patch.object(instant, "save"), \
                mock.patch.object(hermes, "stream_turn", side_effect=AssertionError("the model was asked")):
            r = self.client.post("/api/ask", json={"text": "my medicines today"})
        self.assertEqual(r.json(), {"reply": "Today's medicines\n08:00 Metformin — taken ✓", "chat": "s2"})


if __name__ == "__main__":
    unittest.main()
