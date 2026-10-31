"""Fast checks for the text rules that are easy to break silently. No database, network or model needed.

  .venv/bin/python -m unittest discover tests
"""
import unittest
from datetime import date
from unittest import mock

from jarvis import calendars, learn, money, renewals, search
from jarvis.briefing import _change
from jarvis.web import notify

SAT = date(2026, 10, 31)  # a Saturday


class MoneyPeriods(unittest.TestCase):
    def period(self, text):
        return money.period_from_text(text, SAT)

    def test_english_tamil_and_tanglish(self):
        self.assertEqual(self.period("how much did I spend last month"), ("2026-09-01", "2026-09-30"))
        self.assertEqual(self.period("இந்த மாசம் எவ்வளவு செலவு பண்ணேன்?"), ("2026-10-01", "2026-10-31"))
        self.assertEqual(self.period("intha maasam evlo selavu"), ("2026-10-01", "2026-10-31"))
        self.assertEqual(self.period("nethu kaasu evlo pochu"), ("2026-10-30", "2026-10-30"))
        self.assertEqual(self.period("pona vaaram selavu"), ("2026-10-19", "2026-10-25"))
        self.assertEqual(self.period("kadaisi 10 naal selavu"), ("2026-10-22", "2026-10-31"))

    def test_questions_for_the_files_are_not_money_lookups(self):
        for text in ("What subscriptions do I pay for?", "Netflix ku evlo pay panren?",
                     "how much do I pay for Spotify", "when does my car insurance expire"):
            self.assertIsNone(self.period(text), text)

    def test_today_still_counts(self):
        self.assertEqual(self.period("how much did I pay today"), ("2026-10-31", "2026-10-31"))


class MoneyCategories(unittest.TestCase):
    def test_categories(self):
        cases = {"ZOMATO": "Food & dining", "ETERNAL LIMITED": "Food & dining", "HSR CAFE": "Food & dining",
                 "NANDINI MILK PARLOUR": "Groceries", "OLA CABS": "Travel & fuel", "LIC OF INDIA": "Loans & credit",
                 "Euronet Services India Pvt L": "Cash withdrawals", "kamlesh.joshi95-3@okicici": "Sent to people",
                 "Mr Vallarasu Devendran": "Sent to people", "Coca Cola Store": "Other", "Public Store": "Other"}
        for name, expected in cases.items():
            self.assertEqual(money.category(name), expected, name)

    def test_change_labels(self):
        self.assertEqual(_change(1250, 1000), " (↑ 25%)")
        self.assertEqual(_change(5000, 1000), " (×5)")
        self.assertEqual(_change(500, 400), "")  # too small to compare


class Renewals(unittest.TestCase):
    def when(self, line):
        return renewals._when(line, SAT)

    def test_dates_and_repeats(self):
        self.assertEqual(self.when("Netflix Standard - INR 499 per month - renews on the 5th"), (date(2026, 11, 5), "monthly"))
        self.assertEqual(self.when("Google One 200 GB - INR 1,300 per year - renews 2 February"), (date(2027, 2, 2), "yearly"))
        self.assertEqual(self.when("Date of expiry: 09 June 2031"), (date(2031, 6, 9), "once"))
        self.assertEqual(self.when("The policy is valid from 15 March 2026 to 14 March 2027"), (date(2027, 3, 14), "once"))
        self.assertEqual(self.when("Renewal due 05/12/2026"), (date(2026, 12, 5), "once"))  # day/month/year

    def test_names(self):
        self.assertEqual(renewals._name("Netflix Standard - INR 499 per month", "subs"), "Netflix Standard")
        self.assertEqual(renewals._name("Date of expiry: 09 June 2031", "passport details"), "Passport details")


class CalendarQuestions(unittest.TestCase):
    def period(self, text):
        empty = {"events": [], "errors": {}, "sources": ["google"]}
        with mock.patch.object(calendars, "list_events", return_value=empty):
            result = calendars.agenda_for_text(text, SAT)
        return result and result["period"]

    def test_days(self):
        self.assertEqual(self.period("What is on my calendar tomorrow?"), "TOMORROW, Sun 01 Nov")
        self.assertEqual(self.period("naalaiku enna meeting irukku?"), "TOMORROW, Sun 01 Nov")
        self.assertEqual(self.period("next week schedule enna?"), "next week, Mon 02 Nov to Sun 08 Nov")
        self.assertEqual(self.period("am I busy on Monday"), "Monday, Mon 02 Nov")
        self.assertIsNone(self.period("what is my insurance plan"))


class Search(unittest.TestCase):
    def test_tanglish_is_normalised_for_ranking(self):
        self.assertEqual(search._ranking_query("naan enna subscriptions ku pay panren?"), "what subscriptions pay")
        self.assertEqual(search._ranking_query("en car insurance eppo mudiyum?"), "car insurance when mudiyum?")
        self.assertEqual(search._ranking_query("When does my car insurance expire?"), "When does my car insurance expire?")


class Memory(unittest.TestCase):
    def test_one_day_facts_are_not_kept(self):
        self.assertTrue(learn._ONE_DAY.search("User has a dental appointment tomorrow."))
        self.assertFalse(learn._ONE_DAY.search("User goes to the gym every morning."))

    def test_commands(self):
        self.assertEqual(learn._REMEMBER.match("remember that my GP is Dr. Rao")[1], "my GP is Dr. Rao")
        self.assertIsNone(learn._REMEMBER.match("remember to call mom"))  # a reminder, not a fact
        self.assertEqual(learn._FORGET.match("forget about my old car")[1], "my old car")


class Notifications(unittest.TestCase):
    def test_split_into_title_and_body(self):
        text = "⏰ Reminder: Call Ravi\n(task #3)\n\n💊 Time for Vitamin D3\n(dose #9)\n"
        self.assertEqual(notify._split(text, False), [("⏰ Reminder: Call Ravi", "(task #3)"),
                                                      ("💊 Time for Vitamin D3", "(dose #9)")])
        self.assertEqual(len(notify._split(text, True)), 1)

    def test_quiet_hours_across_midnight(self):
        quiet = {"quiet": {"on": True, "from": "23:00", "to": "07:00"}}
        for now, expected in (("23:30", True), ("06:59", True), ("07:00", False), ("12:00", False)):
            with mock.patch.object(notify, "datetime") as fake:
                fake.now.return_value.strftime.return_value = now
                self.assertEqual(notify._quiet_now(quiet), expected, now)


if __name__ == "__main__":
    unittest.main()
