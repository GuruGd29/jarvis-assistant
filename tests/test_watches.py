"""Watches: reading what the user asked for, and deciding what counts as found. No browser, network or database.

  .venv/bin/python -m unittest discover tests
"""
import unittest
from datetime import date, datetime

from jarvis import sites, watches

MONDAY = date(2026, 11, 2)


class Days(unittest.TestCase):
    def test_days_as_people_say_them(self):
        for said, day in [("today", MONDAY), ("tonight", MONDAY), ("tomorrow", date(2026, 11, 3)),
                          ("day after tomorrow", date(2026, 11, 4)), ("Friday", date(2026, 11, 6)),
                          ("on friday night", date(2026, 11, 6)), ("Sunday", date(2026, 11, 8)),
                          ("monday", MONDAY), ("next Monday", date(2026, 11, 9)), ("8 Nov", date(2026, 11, 8)),
                          ("Nov 8", date(2026, 11, 8)), ("8th November", date(2026, 11, 8)),
                          ("2026-11-08", date(2026, 11, 8)), ("1 Nov", date(2027, 11, 1))]:
            self.assertEqual(watches.parse_day(said, MONDAY), day, said)
        self.assertIsNone(watches.parse_day("", MONDAY))
        self.assertIsNone(watches.parse_day("whenever", MONDAY))

    def test_times_of_day_and_places(self):
        self.assertEqual(watches.part_of_day("Friday night"), ("20:00", "02:00"))
        self.assertEqual(watches.part_of_day("tonight"), ("20:00", "02:00"))
        self.assertEqual(watches.part_of_day("9th Nov morning"), ("05:00", "12:00"))
        self.assertIsNone(watches.part_of_day("on Friday"))
        self.assertEqual(watches.places("Silk Board to Tambaram on Friday night"), ("Silk Board", "Tambaram"))
        self.assertEqual(watches.places("bus from Bangalore to Thanjavur tomorrow"), ("Bangalore", "Thanjavur"))
        self.assertEqual(watches.places("Madiwala to Koyambedu 9th Nov"), ("Madiwala", "Koyambedu"))


class Filling(unittest.TestCase):
    def test_the_sentence_fills_what_the_small_model_leaves_out(self):
        model = {"kind": "bus", "from_city": "Bangalore", "to_city": "Chennai", "boarding_point": "",
                 "dropping_point": "", "day": "Friday", "leave_from": "", "leave_to": "", "max_price": 500}
        form = watches.form_from(model, "Silk Board to Tambaram on Friday night, under ₹500", MONDAY)
        self.assertEqual(form["day"], "2026-11-06")
        self.assertEqual(form["params"], {"from": "Bangalore", "to": "Chennai", "boarding": "Silk Board",
                                          "dropping": "Tambaram", "leave_from": "20:00", "leave_to": "02:00",
                                          "max_price": 500})

    def test_a_misspelt_city_is_the_city_not_a_boarding_point(self):
        model = {"kind": "bus", "from_city": "Bangalore", "to_city": "Mannargudi", "day": "Thursday", "max_price": 500}
        params = watches.form_from(model, "Banglore to Mannargudi on Thursday night under 500", MONDAY)["params"]
        self.assertEqual((params["from"], params["boarding"], params["dropping"]), ("Bangalore", "", ""))
        for a, b in [("Banglore", "Bangalore"), ("Bengaluru", "Bangalore"), ("Madras", "Chennai"), ("Trichy", "Tiruchirappalli")]:
            self.assertTrue(sites.same_place(a, b), (a, b))
        for a, b in [("Silk Board", "Bangalore"), ("Tambaram", "Chennai"), ("Majestic", "Bengaluru")]:
            self.assertFalse(sites.same_place(a, b), (a, b))

    def test_a_place_the_user_never_said_is_dropped(self):
        model = {"kind": "bus", "from_city": "Bangalore", "to_city": "Chennai", "boarding_point": "Majestic",
                 "dropping_point": "Tambaram", "day": "tonight", "max_price": None}
        params = watches.form_from(model, "Majestic to Chennai tonight", MONDAY)["params"]
        self.assertEqual((params["boarding"], params["dropping"]), ("Majestic", ""))

    def test_a_link_makes_a_web_page_watch(self):
        form = watches.form_from({"kind": "bus"}, "watch the price on https://www.amazon.in/dp/B09XS7JWHH", MONDAY)
        self.assertEqual((form["kind"], form["params"]["url"]), ("page", "https://www.amazon.in/dp/B09XS7JWHH"))


class Reading(unittest.TestCase):
    def test_a_night_window_ends_the_next_morning(self):
        start, end = sites.window(date(2026, 11, 6), "20:00", "02:00")
        self.assertEqual((start, end), (datetime(2026, 11, 6, 20), datetime(2026, 11, 7, 2)))
        self.assertEqual(sites.window(date(2026, 11, 6), "05:00", "12:00")[1], datetime(2026, 11, 6, 12))

    def test_the_fare_is_what_the_user_pays(self):
        bus = {"fareList": [1221, 1810], "fareDetailsBySeatType": {
            "SEATER": [{"originalPrice": 1221, "discountedPrice": 1099}],
            "SLEEPER": [{"originalPrice": 1810, "discountedPrice": 1629}]}}
        self.assertEqual(sites._fare(bus), 1099)
        self.assertEqual(sites._fare({"fareList": [950, 1200]}), 950)
        self.assertIsNone(sites._fare({}))

    def test_boarding_points_match_by_name(self):
        grid = {"0": {"name": "Others", "associatedRouteIds": [1]},
                "1": {"name": "Central Silk Board", "associatedRouteIds": [2, 3]},
                "2": {"name": "Majestic (Kempegowda Bus Station)", "associatedRouteIds": [4]}}
        self.assertEqual(sites._stops(grid, "Silk Board")[0], {2, 3})
        self.assertEqual(sites._stops(grid, "majestic")[0], {4})
        self.assertEqual(sites._stops(grid, "Hebbal")[0], set())
        self.assertIsNone(sites._stops(grid, "")[0])

    def test_theatres_and_show_times(self):
        block = "PVR: Superplex Forum Mall, Kanakapura Road\nCancellation available\n09:45 PM\nLUXE\n10:30 PM\nPXL"
        venue = sites._venue(block)
        self.assertEqual(venue, {"name": "PVR: Superplex Forum Mall, Kanakapura Road", "times": ["9:45 PM", "10:30 PM"]})
        self.assertTrue(sites._words("PVR Forum") <= sites._words(venue["name"]))
        self.assertEqual(sites._minutes("9:45 PM"), 21 * 60 + 45)
        self.assertEqual(sites._minutes("12:10 AM"), 10)

    def test_prices_on_pages(self):
        self.assertEqual(sites.price_of("₹24,990"), 24990)
        self.assertEqual(sites.price_of("Rs. 1,299.50"), 1299.5)
        self.assertIsNone(sites.price_of("In stock"))


class Finding(unittest.TestCase):
    bus = {"items": [{"name": "KEN Travels", "leaves": "2026-11-06T21:45", "fare": 449, "seats": 31}], "value": 449}

    def test_a_bus_under_the_price_is_found(self):
        self.assertTrue(watches.evaluate("bus", {"max_price": 500}, self.bus)["met"])
        missed = watches.evaluate("bus", {"max_price": 400}, self.bus)
        self.assertFalse(missed["met"])
        self.assertIn("not under", missed["summary"])
        self.assertFalse(watches.evaluate("bus", {"max_price": 500}, {"items": [], "value": None})["met"])

    def test_movie_bookings(self):
        self.assertFalse(watches.evaluate("movie", {}, {"open": False, "items": []})["met"])
        self.assertFalse(watches.evaluate("movie", {}, {"open": True, "items": []})["met"])
        found = watches.evaluate("movie", {}, {"open": True, "items": [{"name": "PVR Forum", "times": ["7:10 PM"]}]})
        self.assertTrue(found["met"])

    def test_web_pages(self):
        self.assertTrue(watches.evaluate("page", {"what": "price", "below": 22000}, {"value": 21990, "text": "₹21,990"})["met"])
        pounds = watches.evaluate("page", {"what": "price", "below": 40}, {"value": 51.77, "text": "£51.77"})
        self.assertEqual(pounds, {"met": False, "summary": "£51.77 · not under £40 yet"})
        self.assertFalse(watches.evaluate("page", {"what": "price", "below": 22000}, {"value": 24990, "text": "₹24,990"})["met"])
        self.assertTrue(watches.evaluate("page", {"what": "text", "baseline": "Out of stock"}, {"text": "In stock"})["met"])

    def test_told_once_then_only_when_it_gets_cheaper(self):
        use = {"started_at": datetime(2026, 11, 2, 10, tzinfo=watches.TZ)}
        fresh = {"kind": "bus", "params": {}, "found_at": None, "found": None}
        told = {"kind": "bus", "params": {}, "found_at": "2026-11-02T12:00:00+05:30", "found": {"value": 449}}
        self.assertTrue(watches._is_news(fresh, {"met": True, "value": 449}, use))
        self.assertFalse(watches._is_news(told, {"met": True, "value": 449}, use))
        self.assertTrue(watches._is_news(told, {"met": True, "value": 399}, use))
        self.assertFalse(watches._is_news(told, {"met": False, "value": 399}, use))
        earlier = {**told, "found_at": "2026-11-01T12:00:00+05:30"}  # found in an earlier use: news again
        self.assertTrue(watches._is_news(earlier, {"met": True, "value": 449}, use))

    def test_what_to_fix_before_saving(self):
        with self.assertRaisesRegex(ValueError, "both cities"):
            watches.clean("bus", {"from": "Bangalore"}, "2099-01-01")
        with self.assertRaisesRegex(ValueError, "day has passed"):
            watches.clean("bus", {"from": "A", "to": "B"}, "2020-01-01")
        with self.assertRaisesRegex(ValueError, "Read page"):
            watches.clean("page", {"url": "https://example.com"}, None)
        params, _ = watches.clean("bus", {"from": "Bangalore", "to": "Chennai", "boarding": "Banglore",
                                          "dropping": "Tambaram"}, "2099-01-01")
        self.assertEqual((params.get("boarding"), params.get("dropping")), (None, "Tambaram"))
        params, day = watches.clean("bus", {"from": "A", "to": "B", "max_price": "499"}, "2099-01-01")
        self.assertEqual((params["max_price"], params["leave_from"], day), (499, "00:00", date(2099, 1, 1)))


if __name__ == "__main__":
    unittest.main()
