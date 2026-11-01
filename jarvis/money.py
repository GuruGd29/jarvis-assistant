"""Money from bank alert emails: parse them into `transactions`, then sum in SQL.

HDFC, ICICI and IDFC (India) have exact built-in readers. Alerts from any other bank in secrets/money.json
"alert_senders" are read by the local AI (money_ai.py), when JARVIS_MONEY_AI allows it.

Totals are computed here, never by the model. "Spending" = debits that are not transfers between
the user's own accounts (secrets/money.json) and not credit card purchases: a credit card counts when
its bill is paid, so the bill payment is the spending and the purchases on the card are left out.
Card statement emails (bill amount and due date) go into `card_statements`.

  jarvis-money-sync [--days 90]   read alert emails into the table (idempotent; prints nothing unless --verbose)
"""
import argparse
import json
import re
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row

from . import calendars, config, mail

TZ = ZoneInfo(config.TIMEZONE)
SETTINGS = config.SECRETS_DIR / "money.json"
_AMT = r"(?:Rs\.?|INR|₹)\s*([\d,]+(?:\.\d{1,2})?)"
CARD_BILL_PAYEE = re.compile(r"credit ?card bill|ccbillpay|card ?bill ?pay", re.I)
# A purchase on a credit card (not a debit card): counted later, when the card bill is paid.
CREDIT_CARD_PURCHASE = "kind IN ('card_spend', 'card_refund') AND instrument ~ ' card ' AND instrument !~ 'debit card'"
SPENDING = f"direction = 'debit' AND NOT is_self AND NOT ({CREDIT_CARD_PURCHASE})"
# Which card a bill payment went to, from the payee name.
CARD_PAYEE_BANK = [("ICICI", re.compile(r"amazon ?pay|icici", re.I)), ("IDFC", re.compile(r"idfc", re.I)),
                   ("HDFC", re.compile(r"hdfc", re.I))]
STATEMENT_QUERY = 'subject:("credit card statement")'
# Banks with an exact built-in reader below (matched on the sender's address); others are read by the AI.
BUILT_IN_SENDERS = ("hdfcbank", "icici", "idfcfirstbank")
AI_READS_PER_RUN = 40  # about 20-40 minutes on a 2-core server; the rest wait for the next run


def has_reader(sender: str) -> bool:
    return any(bank in sender for bank in BUILT_IN_SENDERS)


def _settings() -> dict:
    return json.loads(SETTINGS.read_text())


def _amount(text: str) -> float:
    return float(text.replace(",", ""))


def _day(text: str, fallback: date) -> date:
    for fmt in ("%d-%m-%y", "%d %b, %Y", "%b %d, %Y", "%d-%b-%Y", "%d %b %Y"):
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            continue
    return fallback


def parse_alert(sender: str, subject: str, body: str, received: datetime) -> dict | None:
    """One transaction from one alert email, or None if it is not a transaction alert."""
    t = re.sub(r"\s+", " ", body)
    fallback = received.date()

    if "hdfcbank" in sender:
        if m := re.search(_AMT + r" is debited from your account ending (\d{4}) towards VPA (\S+) \(([^)]*)\) on ([\d-]+)\.?"
                          r"(?:.*?reference no\.?:? ?(\d+))?", t, re.I):
            return dict(bank="HDFC", instrument=f"HDFC a/c {m[2]}", kind="upi_debit", direction="debit", amount=_amount(m[1]),
                        counterparty=m[4].strip() or m[3], occurred_on=_day(m[5], fallback), reference=m[6])
        if m := re.search(_AMT + r" has been successfully credited to your HDFC Bank account ending in (\d{4}).*?Date: ([\d-]+)"
                          r".*?Sender: ([^(]+?) \(VPA: ?(\S+?)\)(?:.*?Reference No\.?:? ?(\d+))?", t, re.I):
            return dict(bank="HDFC", instrument=f"HDFC a/c {m[2]}", kind="upi_credit", direction="credit", amount=_amount(m[1]),
                        counterparty=m[4].strip(), occurred_on=_day(m[3], fallback), reference=m[6])
        if m := re.search(_AMT + r" has been debited from your account ending x*(\d{4}) on ([\d-]+) and credited to the account "
                          r"ending x*(\d{4}) via IMPS(?:.*?Reference No:? ?(\d+))?", t, re.I):
            return dict(bank="HDFC", instrument=f"HDFC a/c {m[2]}", kind="imps_debit", direction="debit", amount=_amount(m[1]),
                        counterparty=f"account ending {m[4]}", occurred_on=_day(m[3], fallback), reference=m[5])
        if m := re.search(_AMT + r" has been debited from your HDFC Bank Credit Card ending (\d{4}) towards (.+?) on "
                          r"(\d{1,2} \w{3}, \d{4})", t, re.I):
            return dict(bank="HDFC", instrument=f"HDFC card {m[2]}", kind="card_spend", direction="debit", amount=_amount(m[1]),
                        counterparty=m[3].strip(), occurred_on=_day(m[4], fallback), reference=None)
        if m := re.search(_AMT + r" is debited from your HDFC Bank Debit Card ending (\d{4}) at (.+?) on "
                          r"(\d{1,2} \w{3}, \d{4})", t, re.I):
            return dict(bank="HDFC", instrument=f"HDFC debit card {m[2]}", kind="card_spend", direction="debit",
                        amount=_amount(m[1]), counterparty=m[3].strip(), occurred_on=_day(m[4], fallback), reference=None)
        if m := re.search(r"Rs\.? ?" + _AMT + r" is deducted from your account ending X*(\d{4}) and added to EMI .*? on "
                          r"(\d{1,2}-\w{3}-\d{4})", t, re.I):
            return dict(bank="HDFC", instrument=f"HDFC a/c {m[2]}", kind="emi_debit", direction="debit", amount=_amount(m[1]),
                        counterparty="loan EMI", occurred_on=_day(m[3], fallback), reference=None)
        if m := re.search(r"Amount received: " + _AMT + r" Account: X*(\d{4}) Date: (\d{1,2}-\w{3}-\d{4})"
                          r"(?: Reference Details: (.+?) Available Balance)?", t, re.I):
            source = re.sub(r"^[A-Z]{2,4}-[\s-]*X*\d*\s*-\s*", "", (m[4] or "").strip()) or "deposit"
            return dict(bank="HDFC", instrument=f"HDFC a/c {m[2]}", kind="deposit_credit", direction="credit",
                        amount=_amount(m[1]), counterparty=source, occurred_on=_day(m[3], fallback), reference=None)
        if m := re.search(r"reversal of " + _AMT + r" has been initiated to your HDFC Bank Credit Card ending (\d{4}) "
                          r"From Merchant: (.+?) Date Time: (\d{1,2} \w{3}, \d{4})", t, re.I):
            return dict(bank="HDFC", instrument=f"HDFC card {m[2]}", kind="card_refund", direction="credit", amount=_amount(m[1]),
                        counterparty=m[3].strip(), occurred_on=_day(m[4], fallback), reference=None)

    if "icici" in sender:
        if m := re.search(r"Credit Card XX(\d{4}) has been used for a transaction of " + _AMT +
                          r" on (\w{3} \d{1,2}, \d{4}).*?Info: (.+?)\. The Available", t, re.I):
            return dict(bank="ICICI", instrument=f"ICICI card {m[1]}", kind="card_spend", direction="debit", amount=_amount(m[2]),
                        counterparty=m[4].strip(), occurred_on=_day(m[3], fallback), reference=None)
        if m := re.search(r"received payment of " + _AMT + r" on your ICICI Bank Credit Card account .*?(\d{4}) on "
                          r"([\d]{1,2}-\w{3}-\d{4})", t, re.I):
            # The money already left the bank as a card bill payment; this email only confirms it arrived.
            return dict(bank="ICICI", instrument=f"ICICI card {m[2]}", kind="card_payment_confirmation", direction="credit",
                        amount=_amount(m[1]), counterparty="card bill payment", occurred_on=_day(m[3], fallback), reference=None)

    if "idfcfirstbank" in sender:
        if m := re.search(_AMT + r" spent on your IDFC FIRST BANK Credit Card ending X*(\d{4}) at (.+?) on (\d{1,2} \w{3} \d{4})",
                          t, re.I):
            return dict(bank="IDFC", instrument=f"IDFC card {m[2]}", kind="card_spend", direction="debit", amount=_amount(m[1]),
                        counterparty=m[3].strip(), occurred_on=_day(m[4], fallback), reference=None)
        if m := re.search(r"Payment of " + _AMT + r" was received on your .*?Credit Card ending with X*(\d{4}) on "
                          r"(\d{1,2} \w{3} \d{4})", t, re.I):
            return dict(bank="IDFC", instrument=f"IDFC card {m[2]}", kind="card_payment_confirmation", direction="credit",
                        amount=_amount(m[1]), counterparty="card bill payment", occurred_on=_day(m[3], fallback), reference=None)
    return None


def _credit_card_purchase(r: dict) -> bool:
    return r["kind"] in ("card_spend", "card_refund") and " card " in r["instrument"] and "debit card" not in r["instrument"]


def _date(text: str) -> date:
    for fmt in ("%d/%b/%Y", "%B %d, %Y", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            pass
    raise ValueError(f"unknown date {text!r}")


def parse_statement(subject: str, body: str, received: datetime) -> dict | None:
    """Bill amount and due date from a credit card statement email; None when they are only in the PDF (HDFC)."""
    text = re.sub(r"\s+", " ", body)
    if "FIRST" in subject and (m := re.search(r"ending with X*(\d{4}).*?Statement Date (\S+) Total Amount Due ([\d,.]+)"
                                               r".*?Payment Due Date (\S+)", text)):
        return dict(card=f"IDFC card {m[1]}", name="IDFC FIRST Power Plus", statement_on=_date(m[2]),
                    total_due=_amount(m[3]), min_due=None, due_on=_date(m[4]))
    if "ICICI" in subject and (m := re.search(r"Payment due by (\w+ \d{1,2}, \d{4}) ICICI Bank Credit Card XX(\d{4}) "
                                               r"Minimum Amount Due: " + _AMT + " Total Amount Due: " + _AMT, text)):
        period_end = re.search(r"to (\w+ \d{1,2}, \d{4})", subject)
        return dict(card=f"ICICI card {m[2]}", name=re.sub(r" Credit Card Statement.*", "", subject).replace(" Bank", ""),
                    statement_on=_date(period_end[1]) if period_end else received.date(),
                    total_due=_amount(m[4]), min_due=_amount(m[3]), due_on=_date(m[1]))
    return None


def _is_self(txn: dict, settings: dict) -> bool:
    who = (txn.get("counterparty") or "").lower()
    if any(name in re.sub(r"^(mr|mrs|ms|dr)\.? ", "", who) for name in settings["own_names"]):
        return True
    return txn["kind"] == "imps_debit" and any(who.endswith(s) for s in settings["own_account_suffixes"])


def _read_politely(service, gmail_id: str) -> dict:
    """Gmail allows a limited number of reads per minute; pace them and wait out rate-limit errors."""
    from googleapiclient.errors import HttpError

    for attempt in range(6):
        try:
            time.sleep(0.25)
            return mail.read_message(gmail_id, max_chars=3000, service=service)
        except HttpError as error:
            if error.resp.status not in (403, 429) or "rate" not in str(error).lower():
                raise
            time.sleep(20 * (attempt + 1))
    raise RuntimeError("Gmail kept rate-limiting; try again later")


def sync(days: int = 2, verbose: bool = False, ai: bool | None = None) -> dict:
    """Read new alert emails into `transactions`. Emails from banks without a built-in reader go to the AI when
    `ai` is true (default: only when JARVIS_MONEY_AI=always; the nightly job passes --ai)."""
    if ai is None:
        ai = config.MONEY_AI == "always"
    ai = ai and config.MONEY_AI != "off"
    if not SETTINGS.exists() or not calendars.GOOGLE_TOKEN.exists():
        return {"skipped": "Google is not connected or secrets/money.json has no banks yet (docs/money.md)"}
    settings = _settings()
    if not settings.get("alert_senders"):
        return {"skipped": "no alert_senders in secrets/money.json"}
    senders = " OR ".join(f"from:{s}" for s in settings["alert_senders"])
    service = mail._service()
    query = f"({senders}) newer_than:{days}d"
    ids, token = [], None
    while True:
        page = service.users().messages().list(userId="me", q=query, maxResults=100, pageToken=token).execute()
        ids += [m["id"] for m in page.get("messages", [])]
        token = page.get("nextPageToken")
        if not token:
            break

    counts = {"seen": len(ids), "added": 0, "skipped_known": 0, "not_a_transaction": 0, "read_by_ai": 0,
              "waiting_for_ai": 0}
    with psycopg.connect(config.DB_DSN) as conn:
        known = {r[0] for r in conn.execute(
            "SELECT gmail_id FROM transactions WHERE gmail_id = ANY(%s) "
            "UNION SELECT gmail_id FROM money_ai_seen WHERE gmail_id = ANY(%s)", (ids, ids))}
        for gmail_id in ids:
            if gmail_id in known:
                counts["skipped_known"] += 1
                continue
            msg = _read_politely(service, gmail_id)
            received = datetime.strptime(msg["received"], "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
            body = msg["body"].removeprefix("<<<EMAIL").removesuffix("EMAIL>>>")
            sender = msg["from_address"].lower()
            txn = parse_alert(sender, msg["subject"], body, received)
            if txn is None and not has_reader(sender):
                if not ai or counts["read_by_ai"] >= AI_READS_PER_RUN:
                    counts["waiting_for_ai"] += 1
                    continue
                txn = _read_with_ai(conn, gmail_id, msg, body, received)
                counts["read_by_ai"] += 1
            if txn is None:
                counts["not_a_transaction"] += 1
                continue
            if txn["kind"] == "upi_debit" and CARD_BILL_PAYEE.search(txn["counterparty"] or ""):
                txn["kind"] = "card_bill_payment"  # paying a card bill: this is the spending, not the card purchases
            txn.update(gmail_id=gmail_id, subject=msg["subject"], occurred_at=received, is_self=_is_self(txn, settings))
            conn.execute(
                """INSERT INTO transactions (gmail_id, bank, instrument, kind, direction, amount, counterparty,
                       occurred_on, occurred_at, reference, is_self, subject)
                   VALUES (%(gmail_id)s, %(bank)s, %(instrument)s, %(kind)s, %(direction)s, %(amount)s, %(counterparty)s,
                       %(occurred_on)s, %(occurred_at)s, %(reference)s, %(is_self)s, %(subject)s)
                   ON CONFLICT (gmail_id) DO NOTHING""", txn)
            conn.commit()  # keep progress if a later message hits Google's rate limit
            counts["added"] += 1
        counts["statements_added"] = _sync_statements(service, conn, days)
    if verbose:
        print(counts)
    return counts


def _read_with_ai(conn, gmail_id: str, msg: dict, body: str, received: datetime) -> dict | None:
    """One email from a bank without a built-in reader: a transaction to store, or None. A card statement is
    stored here. The outcome is remembered, so the email is not read again."""
    from . import money_ai

    try:
        outcome, row = money_ai.read_email(msg["subject"], body, received)
    except Exception as error:  # the model is busy or down: not remembered, so the next run tries again
        print(f"⚠️ Jarvis couldn't read a bank email from {msg['from']} with the AI ({type(error).__name__}); "
              "it will try again on the next run.")
        return None
    if outcome == "card_statement":
        conn.execute(
            """INSERT INTO card_statements (gmail_id, card, name, statement_on, total_due, min_due, due_on)
               VALUES (%(gmail_id)s, %(card)s, %(name)s, %(statement_on)s, %(total_due)s, %(min_due)s, %(due_on)s)
               ON CONFLICT (gmail_id) DO NOTHING""", row | {"gmail_id": gmail_id})
    conn.execute("INSERT INTO money_ai_seen (gmail_id, outcome, detail) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                 (gmail_id, "saved" if row else outcome, msg["subject"][:200]))
    conn.commit()
    return row if outcome == "transaction" else None


def _sync_statements(service, conn, days: int) -> int:
    ids = [m["id"] for m in service.users().messages().list(
        userId="me", q=f"{STATEMENT_QUERY} newer_than:{days}d", maxResults=50).execute().get("messages", [])]
    known = {r[0] for r in conn.execute("SELECT gmail_id FROM card_statements WHERE gmail_id = ANY(%s)", (ids,))}
    added = 0
    for gmail_id in ids:
        if gmail_id in known:
            continue
        msg = _read_politely(service, gmail_id)
        received = datetime.strptime(msg["received"], "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
        statement = parse_statement(msg["subject"], msg["body"], received)
        if statement is None:
            continue
        conn.execute(
            """INSERT INTO card_statements (gmail_id, card, name, statement_on, total_due, min_due, due_on)
               VALUES (%(gmail_id)s, %(card)s, %(name)s, %(statement_on)s, %(total_due)s, %(min_due)s, %(due_on)s)
               ON CONFLICT (gmail_id) DO NOTHING""", statement | {"gmail_id": gmail_id})
        conn.commit()
        added += 1
    return added


def _paid_to(counterparty: str | None, bank: str) -> bool:
    """Whether a card bill payment went to this bank's card: by the known payee names, else by the bank's name."""
    who = counterparty or ""
    named = next((b for b, rx in CARD_PAYEE_BANK if rx.search(who)), None)
    return named == bank if named else bank.lower() in who.lower()


def cards(today: date | None = None) -> list[dict]:
    """Each credit card: its latest bill, the part payments made towards it since the statement, what is
    left before the due date, and the purchases since the statement (they go on the next bill)."""
    today = today or date.today()
    with psycopg.connect(config.DB_DSN, row_factory=dict_row) as conn:
        statements = conn.execute(
            "SELECT DISTINCT ON (card) card, name, statement_on, total_due, min_due, due_on FROM card_statements "
            "ORDER BY card, statement_on DESC").fetchall()
        purchases = conn.execute(
            f"SELECT instrument, kind, occurred_on, amount, counterparty FROM transactions WHERE {CREDIT_CARD_PURCHASE} "
            "AND occurred_on >= %s ORDER BY occurred_on DESC, occurred_at DESC", (today - timedelta(days=90),)).fetchall()
        payments = conn.execute(
            "SELECT occurred_on, amount, counterparty FROM transactions WHERE kind = 'card_bill_payment' "
            "AND occurred_on >= %s ORDER BY occurred_on DESC, occurred_at DESC", (today - timedelta(days=90),)).fetchall()
    out = {s["card"]: dict(s) for s in statements}
    for r in purchases:
        out.setdefault(r["instrument"], {"card": r["instrument"], "name": None, "statement_on": None,
                                         "total_due": None, "min_due": None, "due_on": None})
    result = []
    for c in sorted(out.values(), key=lambda c: (c["due_on"] is None, c["due_on"] or date.max, c["card"])):
        bank = c["card"].split()[0]
        # No statement (HDFC sends it only as a PDF): show the last 30 days instead of the billing cycle.
        since_day = c["statement_on"] or today - timedelta(days=30)
        paid = [p for p in payments if p["occurred_on"] > since_day and _paid_to(p["counterparty"], bank)]
        bought = [r for r in purchases if r["instrument"] == c["card"] and r["occurred_on"] > since_day]
        paid_total = round(float(sum(p["amount"] for p in paid)), 2)
        due = float(c["total_due"]) if c["total_due"] is not None else None
        result.append({
            "card": c["card"], "name": c["name"] or f"{bank} credit card", "bank": bank, "last4": c["card"].split()[-1],
            "statement_on": str(c["statement_on"]) if c["statement_on"] else None,
            "since": str(since_day),
            "total_due": due, "min_due": float(c["min_due"]) if c["min_due"] is not None else None,
            "due_on": str(c["due_on"]) if c["due_on"] else None,
            "paid": paid_total,
            "left": round(max(due - paid_total, 0.0), 2) if due is not None else None,
            "extra": round(max(paid_total - due, 0.0), 2) if due is not None else 0.0,
            "payments": [{"date": str(p["occurred_on"]), "amount": float(p["amount"])} for p in paid],
            "purchases": [{"date": str(r["occurred_on"]), "amount": float(r["amount"]), "merchant": r["counterparty"] or "",
                           "refund": r["kind"] == "card_refund"} for r in bought],
            "purchases_total": round(float(sum(-r["amount"] if r["kind"] == "card_refund" else r["amount"] for r in bought)), 2),
        })
    return result


def summary(start: str, end: str | None = None) -> dict:
    """Exact money totals for start..end (YYYY-MM-DD, inclusive), with the transactions behind them."""
    first = date.fromisoformat(start)
    last = date.fromisoformat(end) if end else first
    with psycopg.connect(config.DB_DSN, row_factory=dict_row) as conn:
        rows = conn.execute(
            """SELECT occurred_on, instrument, kind, direction, amount, counterparty, is_self
               FROM transactions WHERE occurred_on BETWEEN %s AND %s ORDER BY occurred_on, occurred_at""",
            (first, last)).fetchall()
    spent = [r for r in rows if r["direction"] == "debit" and not r["is_self"] and not _credit_card_purchase(r)]
    refunds = [r for r in rows if r["kind"] == "card_refund" and not _credit_card_purchase(r)]
    received = [r for r in rows if r["kind"] in ("upi_credit", "deposit_credit") and not r["is_self"]]
    total = lambda items: round(float(sum(r["amount"] for r in items)), 2)
    line = lambda r: f"{r['occurred_on']} {r['instrument']} {r['kind']} {config.money(r['amount'])} {r['counterparty'] or ''}".strip()
    result = {
        "period": f"{first} to {last}" if last != first else str(first),
        "spending_total": round(total(spent) - total(refunds), 2),
        "spending": [line(r) for r in spent],
        "refunds_total": total(refunds),
        "received_total": total(received),
        "own_account_transfers_total": total([r for r in rows if r["is_self"]]),
        "card_bill_payments_total": total([r for r in rows if r["kind"] == "card_bill_payment"]),
        "credit_card_purchases_total": total([r for r in rows if r["kind"] == "card_spend" and _credit_card_purchase(r)]),
        "note": "Totals come from bank alert emails only; cash and payments without an alert email are not included. "
                "Credit cards count when the bill is paid, not per purchase.",
    }
    # The same totals written in the user's currency and style, for chat and reports.
    result["display"] = {k: config.money(v) for k, v in result.items() if k.endswith("_total")}
    return result


# Categories from the merchant name, first match wins; anything else that looks like a person's
# name or a UPI id is "Sent to people". Extend the lists as new merchants show up.
CATEGORIES = [
    ("Credit card bills", CARD_BILL_PAYEE.pattern),  # before Shopping: "Amazon Pay Credit Card Bill" is not shopping
    ("Food & dining", r"zomato|eternal limited|swiggy|caf[eé]|restaurant|hotel|\btea\b|bakery|bakes|food|delicacy|"
                      r"dhaba|biryani|juice|\bmess\b|kitchen|militery|military|pizza|burger|coffee|chai|chaha|tiffin|"
                      r"\bbun\b|\bqsr\b|paan|\bpan shop|\bkfc\b|ahaara|\beat"),
    ("Groceries", r"super ?market|milk|nandini|bigbasket|blinkit|zepto|dmart|instamart|fresh|grocer|vegetable|fruit|"
               r"\begg\b|coconut|flower"),
    ("Travel & fuel", r"flight|makemytrip|redbus|irctc|\buber\b|\bola\b|rapido|metro|fuel|petrol|indigo|air ?india|"
                      r"\bcabs?\b|travel"),
    ("Shopping", r"amazon|flipkart|myntra|ajio|meesho|gift|stories|high ?street|\bmall\b|trends|decathlon|clothing|"
                 r"fashion"),
    ("Bills & subscriptions", r"airtel|\bjio\b|vodafone|bescom|electric|broadband|netflix|spotify|google|apple|oracle|"
                              r"ctrlx|recharge|insurance|hostinger|\baws\b"),
    ("Loans & credit", r"\bemi\b|loan|slice|credit card|\blic\b"),
    ("Cash withdrawals", r"euronet|\batm\b|\bcash\b"),
    ("Health", r"pharma|medical|hospital|clinic|apollo|medplus|diagnos|\blabs?\b"),
    ("Entertainment", r"club|resort|\bpvr\b|inox|bookmyshow|movie|\bbar\b|tasmac"),
]
_CATEGORY_RES = [(name, re.compile(pattern, re.I)) for name, pattern in CATEGORIES]
_BUSINESS = re.compile(r"\b(pvt|private|ltd|limited|llp|services|india|technologies|store|shop|centre|center|"
                       r"enterprises|traders|agency)\b", re.I)


def small_amount(today: date | None = None) -> float:
    """Below this, a change between two periods is too small to compare: 10 times the usual payment of the
    last 90 days, so it fits any currency (about 1,000 on rupee data)."""
    today = today or date.today()
    with psycopg.connect(config.DB_DSN) as conn:
        usual = conn.execute(
            f"SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY amount) FROM transactions "
            f"WHERE occurred_on > %s AND {SPENDING}", (today - timedelta(days=90),)).fetchone()[0]
    return round(float(usual or 0) * 10, 2)


def category(counterparty: str | None) -> str:
    name = (counterparty or "").strip()
    for label, pattern in _CATEGORY_RES:
        if pattern.search(name):
            return label
    words = name.replace(".", " ").split()
    if "@" in name or re.match(r"^(mr|mrs|ms|dr)\b", name, re.I) or (
            1 <= len(words) <= 4 and len(name) >= 4 and not _BUSINESS.search(name)
            and all(w.isalpha() for w in words)):
        return "Sent to people"
    return "Other"


def insights(start: str, end: str) -> dict:
    """Spending by category for start..end against the same number of days before it, plus unusual
    payments (well above the usual size) and merchants not paid in the 60 days before."""
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    span = (last - first).days + 1
    prev_first = first - timedelta(days=span)
    with psycopg.connect(config.DB_DSN, row_factory=dict_row) as conn:
        rows = conn.execute(
            f"""SELECT occurred_on, kind, amount, counterparty FROM transactions
               WHERE occurred_on BETWEEN %s AND %s AND {SPENDING}""", (first - timedelta(days=60), last)).fetchall()
    now = [r for r in rows if r["occurred_on"] >= first]
    before = [r for r in rows if prev_first <= r["occurred_on"] < first]
    history = {(r["counterparty"] or "").strip().lower() for r in rows if r["occurred_on"] < first}

    def by_category(items):
        out: dict[str, float] = {}
        for r in items:
            out[category(r["counterparty"])] = out.get(category(r["counterparty"]), 0.0) + float(r["amount"])
        return out

    current, previous = by_category(now), by_category(before)
    cats = [{"category": c, "total": round(t, 2), "previous": round(previous.get(c, 0.0), 2),
             "payments": sum(1 for r in now if category(r["counterparty"]) == c)}
            for c, t in sorted(current.items(), key=lambda kv: kv[1], reverse=True)]
    amounts = sorted(float(r["amount"]) for r in rows)
    typical = amounts[len(amounts) // 2] if amounts else 0.0
    # Unusual = among the largest 5% of payments and at least 10 times the usual size; no fixed amount, so it
    # works in any currency (on real rupee data it matches the old "over ₹5,000" rule).
    floor = max(amounts[int(len(amounts) * 0.95)], typical * 10) if amounts else 0.0
    large = [r for r in sorted(now, key=lambda r: r["amount"], reverse=True)
             if r["kind"] != "card_bill_payment" and float(r["amount"]) >= floor][:5]
    unusual = [f"{r['occurred_on']} {config.money(r['amount'])} {r['counterparty'] or ''} ({category(r['counterparty'])})"
               for r in large]
    new = sorted({(r["counterparty"] or "").strip() for r in now
                  if (r["counterparty"] or "").strip() and (r["counterparty"] or "").strip().lower() not in history})
    return {"period": f"{first} to {last}", "compared_with": f"{prev_first} to {first - timedelta(days=1)}",
            "by_category": cats, "unusual_payments": unusual, "new_merchants": new[:10],
            "unusual_rows": [{"on": str(r["occurred_on"]), "amount": float(r["amount"]), "counterparty": r["counterparty"],
                              "category": category(r["counterparty"])} for r in large],
            "note": "From bank alert emails only; categories are guessed from merchant names."}


_MONEY_WORDS = re.compile(r"\b(spen[dt]|spending|expenses?|paid|pay(ment)?s?|transactions?|debited|credited|"
                          r"received|money|upi|how much)\b"
                          # Tamil and Tanglish stems ("selavu", "kattinen"); Tamil vowel signs are not \w, so no \b there.
                          r"|\b(selav|chelav|panam|kaasu|kasu|kattin|anuppin)|செலவ|பணம்|காசு|கட்டண|கட்டின|செலுத்த|அனுப்பின", re.I)
# Periods in English, Tamil and Tanglish; "last week" is checked before "week", and so on.
_YESTERDAY = re.compile(r"yesterday|நேற்று|நேத்து|\bne(t|th)(r|th)?u|\bnethaiku|\bnethiku", re.I)
_LAST = r"(?:last|pona|pone|kadantha|போன|கடந்த)\s*"
_WEEK = r"(?:week|vaa?ram|vaa?rath|வாரம்|வாரத்)"
_MONTH = r"(?:month|maa?sam|maa?sath|maa?tham|maa?thath|மாசம்|மாசத்|மாதம்|மாதத்)"
# "What subscriptions do I pay for?" is answered by the user's files, not by bank-alert totals.
_NOT_SPENDING = re.compile(r"\b(subscriptions?|premiums?|polic(y|ies)|insurance)\b|சந்தா|பிரீமியம்|பாலிசி|காப்பீடு|இன்சூரன்ஸ்", re.I)
_TODAY = re.compile(r"today|இன்று|இன்னைக்கு|\bin+aik+u|\binn?iki", re.I)
_LAST_DAYS = re.compile(r"(?:last|kadaisi|கடைசி)\s*(\d{1,3})\s*(?:days?|naa?l|நாள்|நாட்)", re.I)


def period_from_text(text: str, today: date | None = None) -> tuple[str, str] | None:
    """The date range a money question asks about, or None if it is not a money question."""
    if not _MONEY_WORDS.search(text or "") or _NOT_SPENDING.search(text or ""):
        return None
    today = today or datetime.now(TZ).date()
    low = text.lower()
    if _YESTERDAY.search(low):
        day = today - timedelta(days=1)
        return str(day), str(day)
    if re.search(_LAST + _WEEK, low):
        start = today - timedelta(days=today.weekday() + 7)
        return str(start), str(start + timedelta(days=6))
    if re.search(_WEEK, low):
        return str(today - timedelta(days=today.weekday())), str(today)
    if re.search(_LAST + _MONTH, low):
        last_end = today.replace(day=1) - timedelta(days=1)
        return str(last_end.replace(day=1)), str(last_end)
    if re.search(_MONTH, low):
        return str(today.replace(day=1)), str(today)
    if m := _LAST_DAYS.search(low):
        return str(today - timedelta(days=int(m[1]) - 1)), str(today)
    if _TODAY.search(low):
        return str(today), str(today)
    # "How much do I pay for Netflix?" has no period: it asks about a plan in the user's files, not today's alerts.
    if all(m.group(0).lower() in ("pay", "pays", "payment", "payments", "how much") for m in _MONEY_WORDS.finditer(text)):
        return None
    return str(today), str(today)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--days", type=int, default=2)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--ai", action="store_true", help="also read emails from banks without a built-in reader "
                        "with the local AI (the nightly job; unless JARVIS_MONEY_AI=off)")
    args = parser.parse_args()
    sync(args.days, args.verbose, ai=True if args.ai else None)


if __name__ == "__main__":
    main()
