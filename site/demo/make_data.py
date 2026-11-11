"""Make the online demo's data (site/demo/data.json) from a throwaway Jarvis filled with made-up data.

The demo on the project page is the real phone app (web/app) with the server replaced by these recorded answers.
So the data must look exactly like the real server's: this fills an empty database with invented money, tasks,
medicines, documents and watches, asks the real app server for every screen, and saves the answers. Run it again
when the app's screens change.

  JARVIS_DEMO=1 JARVIS_DB_NAME=jarvis_demo JARVIS_DATA_ROOT=/tmp/demo-files JARVIS_SECRETS_DIR=/tmp/demo-secrets \\
    JARVIS_OWNER_NAME=Priya JARVIS_LOCALE=en_IN JARVIS_CURRENCY=INR JARVIS_TIMEZONE=Asia/Kolkata \\
    .venv/bin/python site/demo/make_data.py

It needs Postgres with pgvector (for the throwaway database) and Ollama with bge-m3 (to index the invented
documents). It refuses to run against Jarvis's own database or folders. Every name, number and place is made up.
"""
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

if os.environ.get("JARVIS_DEMO") != "1":
    sys.exit("make_data.py fills a throwaway database: run it with JARVIS_DEMO=1 (see the top of this file)")
if os.environ.get("JARVIS_DB_NAME", "jarvis") == "jarvis":
    sys.exit("make_data.py refuses to touch Jarvis's own database: set JARVIS_DB_NAME to a throwaway one")
for setting in ("JARVIS_DATA_ROOT", "JARVIS_SECRETS_DIR"):
    if not os.environ.get(setting):
        sys.exit(f"set {setting} to an empty throwaway folder")

import psycopg  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from jarvis import config, health, ingest, tasks, watches  # noqa: E402
from jarvis.web import notify, server  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).with_name("data.json")
TODAY = tasks.today()
day = lambda n: TODAY - timedelta(days=n)  # noqa: E731
ahead = lambda n: TODAY + timedelta(days=n)  # noqa: E731


def documents() -> dict[str, str]:
    return {
        "documents/car-insurance.md": f"""# Car insurance

Insurer: Sundaram Star Motor Insurance. Policy number SSM-4471-2026 for the Hyundai i20 (KA-01-AB-1234).
The policy renews on {ahead(9):%d %B %Y}. Premium: ₹12,480 a year, paid by card.
Roadside help: 1800-000-1234.
""",
        "documents/passport.md": f"""# Passport

Passport for Priya Raman. The passport is valid until {ahead(400):%d %B %Y}.
Renewal can be applied for a year before expiry at the Passport Seva Kendra.
""",
        "finance/rent-agreement.md": f"""# Rent agreement

Flat 3B, Lakeview Apartments. Monthly rent ₹18,000, paid on the 5th to Mr. Suresh Babu.
The agreement is valid until {ahead(21):%d %B %Y} and renews for 11 months at a 5% higher rent.
Deposit: ₹1,00,000.
""",
        "health/blood-test.md": f"""# Blood test, {day(30):%d %B %Y}

Haemoglobin 12.1 g/dL (normal 12.0-15.5). Vitamin D 18 ng/mL: LOW (normal 30-100).
HbA1c 5.4%. Cholesterol 182 mg/dL. The doctor suggested Vitamin D3 every night for 8 weeks.
""",
        "notes/wifi.md": "# Home Wi-Fi\n\nNetwork: Lakeview-3B. The router is in the hall cupboard.\n",
        "notes/trip-ideas.md": "# Trip ideas\n\nCoorg in December; Pondicherry for a long weekend; Munnar in the rains.\n",
    }


TRANSACTIONS = [  # (days ago, bank, instrument, kind, direction, amount, counterparty)
    (0, "HDFC", "HDFC a/c 1234", "upi_debit", "debit", 240, "BLUE TOKAI COFFEE"),
    (0, "HDFC", "HDFC a/c 1234", "upi_debit", "debit", 186, "NAMMA METRO"),
    (1, "HDFC", "HDFC a/c 1234", "upi_debit", "debit", 1240, "MORE SUPERMARKET"),
    (1, "ICICI", "ICICI card 5678", "card_spend", "debit", 449, "SWIGGY"),
    (2, "HDFC", "HDFC a/c 1234", "upi_debit", "debit", 320, "UBER INDIA"),
    (2, "HDFC", "HDFC a/c 1234", "card_bill_payment", "debit", 8000, "Amazon Pay Credit Card Bill Payments"),
    (2, "ICICI", "ICICI card 5678", "card_spend", "debit", 2399, "AMAZON"),
    (3, "HDFC", "HDFC a/c 1234", "upi_debit", "debit", 680, "APOLLO PHARMACY"),
    (3, "HDFC", "HDFC a/c 1234", "upi_debit", "debit", 95, "NANDINI MILK PARLOUR"),
    (4, "ICICI", "ICICI card 5678", "card_spend", "debit", 649, "NETFLIX"),
    (5, "HDFC", "HDFC a/c 1234", "upi_debit", "debit", 18000, "SURESH BABU"),
    (5, "HDFC", "HDFC a/c 1234", "upi_debit", "debit", 560, "PVR CINEMAS"),
    (6, "HDFC", "HDFC a/c 1234", "upi_debit", "debit", 1890, "BIGBASKET"),
    (8, "HDFC", "HDFC a/c 1234", "upi_debit", "debit", 2150, "BESCOM ELECTRICITY"),
    (9, "ICICI", "ICICI card 5678", "card_spend", "debit", 3499, "MYNTRA"),
    (10, "HDFC", "HDFC a/c 1234", "upi_debit", "debit", 799, "AIRTEL BROADBAND"),
    (12, "HDFC", "HDFC a/c 1234", "upi_debit", "debit", 450, "ZOMATO"),
    (14, "HDFC", "HDFC a/c 1234", "upi_credit", "credit", 85000, "ACME SOFTWARE SALARY"),
    (15, "ICICI", "ICICI card 5678", "card_spend", "debit", 1299, "DECATHLON"),
    (16, "HDFC", "HDFC a/c 1234", "card_bill_payment", "debit", 6000, "ICICI Credit Card Bill Payment"),
    (18, "HDFC", "HDFC a/c 1234", "upi_debit", "debit", 2600, "INDIAN OIL PETROL"),
    (21, "HDFC", "HDFC a/c 1234", "upi_debit", "debit", 1450, "MORE SUPERMARKET"),
    (24, "HDFC", "HDFC a/c 1234", "upi_debit", "debit", 900, "CULT FIT"),
    (27, "ICICI", "ICICI card 5678", "card_spend", "debit", 5600, "MAKEMYTRIP"),
    (35, "HDFC", "HDFC a/c 1234", "upi_debit", "debit", 18000, "SURESH BABU"),
    (40, "HDFC", "HDFC a/c 1234", "upi_debit", "debit", 2300, "BESCOM ELECTRICITY"),
    (44, "HDFC", "HDFC a/c 1234", "upi_credit", "credit", 85000, "ACME SOFTWARE SALARY"),
    (60, "HDFC", "HDFC a/c 1234", "upi_debit", "debit", 12480, "SUNDARAM INSURANCE"),
    (90, "HDFC", "HDFC a/c 1234", "upi_debit", "debit", 4200, "CROMA"),
]


def fill() -> None:
    with psycopg.connect(config.DB_DSN, autocommit=True) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        for sql in sorted((ROOT / "sql").glob("*.sql")):
            conn.execute(sql.read_text())
        conn.execute("TRUNCATE transactions, card_statements, tasks, medication_doses, medications, watches, "
                     "activity, web_chats, documents RESTART IDENTITY CASCADE")
        for i, (ago, bank, instrument, kind, direction, amount, who) in enumerate(TRANSACTIONS):
            conn.execute("""INSERT INTO transactions (gmail_id, bank, instrument, kind, direction, amount, counterparty,
                            occurred_on) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                         (f"demo-{i}", bank, instrument, kind, direction, amount, who, day(ago)))
        conn.execute("""INSERT INTO card_statements (gmail_id, card, name, statement_on, total_due, min_due, due_on)
                        VALUES ('demo-statement', 'ICICI card 5678', 'Amazon Pay ICICI', %s, 14250, 720, %s)""",
                     (day(6), ahead(12)))

    config.SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    (config.SECRETS_DIR / "money.json").write_text(json.dumps(
        {"own_names": ["priya raman"], "own_account_suffixes": ["1234"], "alert_senders": []}))
    for rel, text in documents().items():
        path = config.DATA_ROOT / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    for folder in config.DOMAINS:
        (config.DATA_ROOT / folder).mkdir(parents=True, exist_ok=True)
    index_all()

    tasks.add_task("Pay the water bill", due_on=str(TODAY), priority=1)
    tasks.add_task("Book the car service", due_on=str(ahead(3)))
    tasks.add_task("Call Amma about Diwali plans", due_on=str(ahead(1)))
    tasks.add_task("Renew the gym membership", due_on=str(ahead(6)))
    health.add_medication("Vitamin D3", "21:00", dose="1 tablet")
    health.add_medication("Iron", "08:30", dose="1 tablet after breakfast")

    bus = watches.create("bus", {"from": "Bengaluru", "to": "Chennai", "leave_from": "20:00", "leave_to": "23:59",
                                 "max_price": 700}, str(ahead(2)), 10)
    watches.record(bus, {"ok": True, "value": 649, "met": True, "summary": "₹649 · KPN Travels, 9:45 pm",
                         "items": [{"name": "KPN Travels", "leaves": f"{ahead(2)}T21:45", "seats": 6,
                                    "type": "A/C Sleeper (2+1)", "fare": 649},
                                   {"name": "SRS Travels", "leaves": f"{ahead(2)}T22:30", "seats": 11,
                                    "type": "A/C Sleeper (2+1)", "fare": 720},
                                   {"name": "Orange Tours", "leaves": f"{ahead(2)}T23:15", "seats": 3,
                                    "type": "Volvo Multi-Axle A/C Seater", "fare": 780}]})
    movie = watches.create("movie", {"movie": "The Long Monsoon", "city": "Bengaluru", "after": "18:00",
                                     "theatres": ["PVR Forum Mall"]}, str(ahead(4)), 30)
    watches.record(movie, {"ok": True, "open": False, "met": False, "summary": "Bookings not open yet", "items": []})

    notify.notify("reports", "Good morning, Priya", "2 events today · Pay the water bill is due · ₹186 spent so far.")
    notify.notify("reminders", "Pay the water bill", "Due today.")
    notify.notify("watches", "Bus under ₹700: ₹649", "KPN Travels, 9:45 pm · Bengaluru to Chennai. Open Jarvis to book.")


def index_all() -> None:
    from pgvector.psycopg import register_vector
    with psycopg.connect(config.DB_DSN) as conn:
        register_vector(conn)
        ingest.full_pass(conn)


def record() -> dict:
    client = TestClient(server.app, base_url="http://127.0.0.1")

    def get(path: str):
        response = client.get(path)
        response.raise_for_status()
        return response.json()

    out = {"made_on": TODAY.isoformat(), "screens": {}}
    for path in ("/api/today", "/api/iphone-reminders", "/api/cards", "/api/more", "/api/settings", "/api/activity",
                 "/api/files", "/api/watches", "/api/watches/places"):
        out["screens"][path] = get(path)
    for period in ("today", "week", "month", "year"):
        out["screens"][f"/api/money?period={period}"] = get(f"/api/money?period={period}")
    for w in out["screens"]["/api/watches"]["watching"] + out["screens"]["/api/watches"].get("saved", []) \
            + out["screens"]["/api/watches"].get("found", []):
        out["screens"][f"/api/watches/{w['id']}"] = get(f"/api/watches/{w['id']}")
    for folder in out["screens"]["/api/files"].get("folders", []):
        for f in folder.get("files", []):
            out["screens"][f"/api/files/view?path={f['path']}"] = get(f"/api/files/view?path={f['path']}")
    # The calendar comes from Google or iCloud, which the demo can't have: invented events, in the server's shape.
    out["screens"]["/api/today"]["events"] = [
        {"day": TODAY.isoformat(), "time": "10:00", "end": "10:30", "title": "Team stand-up", "where": "Google Meet",
         "source": "google", "calendar": "Work"},
        {"day": TODAY.isoformat(), "time": "18:30", "end": "19:30", "title": "Yoga class", "where": "Cult, HSR",
         "source": "google", "calendar": "Personal"},
        {"day": ahead(1).isoformat(), "time": None, "end": None, "title": "Deepa's birthday", "where": None,
         "source": "icloud", "calendar": "Family"},
    ]
    out["screens"]["/api/today"]["calendars_connected"] = True
    # Memory is learnt from real chats over weeks; the demo shows what that looks like.
    out["screens"]["/api/more"].update({"facts": 23, "episodes": 9})
    return out


if __name__ == "__main__":
    fill()
    data = record()
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(data['screens'])} screens, made on {data['made_on']}")
