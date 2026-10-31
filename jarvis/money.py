"""Money from bank alert emails: parse HDFC / ICICI alerts into `transactions`, then sum in SQL.

Totals are computed here, never by the model. "Spending" = debits that are not transfers between
the user's own accounts (secrets/money.json) and not credit card bill payments, minus card refunds.

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

from . import config, mail

TZ = ZoneInfo(config.TIMEZONE)
SETTINGS = config.SECRETS_DIR / "money.json"
_AMT = r"(?:Rs\.?|INR|₹)\s*([\d,]+(?:\.\d{1,2})?)"
CARD_BILL_PAYEE = re.compile(r"credit ?card bill|ccbillpay|card ?bill ?pay", re.I)


def _settings() -> dict:
    return json.loads(SETTINGS.read_text())


def _amount(text: str) -> float:
    return float(text.replace(",", ""))


def _day(text: str, fallback: date) -> date:
    for fmt in ("%d-%m-%y", "%d %b, %Y", "%b %d, %Y", "%d-%b-%Y"):
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


def sync(days: int = 2, verbose: bool = False) -> dict:
    settings = _settings()
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

    counts = {"seen": len(ids), "added": 0, "skipped_known": 0, "not_a_transaction": 0}
    with psycopg.connect(config.DB_DSN) as conn:
        known = {r[0] for r in conn.execute("SELECT gmail_id FROM transactions WHERE gmail_id = ANY(%s)", (ids,))}
        for gmail_id in ids:
            if gmail_id in known:
                counts["skipped_known"] += 1
                continue
            msg = _read_politely(service, gmail_id)
            received = datetime.strptime(msg["received"], "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
            body = msg["body"].removeprefix("<<<EMAIL").removesuffix("EMAIL>>>")
            txn = parse_alert(msg["from_address"].lower(), msg["subject"], body, received)
            if txn is None:
                counts["not_a_transaction"] += 1
                continue
            if txn["kind"] == "upi_debit" and CARD_BILL_PAYEE.search(txn["counterparty"] or ""):
                txn["kind"] = "card_bill_payment"  # paying a card bill; the card purchases are counted instead
            txn.update(gmail_id=gmail_id, subject=msg["subject"], occurred_at=received, is_self=_is_self(txn, settings))
            conn.execute(
                """INSERT INTO transactions (gmail_id, bank, instrument, kind, direction, amount, counterparty,
                       occurred_on, occurred_at, reference, is_self, subject)
                   VALUES (%(gmail_id)s, %(bank)s, %(instrument)s, %(kind)s, %(direction)s, %(amount)s, %(counterparty)s,
                       %(occurred_on)s, %(occurred_at)s, %(reference)s, %(is_self)s, %(subject)s)
                   ON CONFLICT (gmail_id) DO NOTHING""", txn)
            conn.commit()  # keep progress if a later message hits Google's rate limit
            counts["added"] += 1
    if verbose:
        print(counts)
    return counts


def summary(start: str, end: str | None = None) -> dict:
    """Exact money totals for start..end (YYYY-MM-DD, inclusive), with the transactions behind them."""
    first = date.fromisoformat(start)
    last = date.fromisoformat(end) if end else first
    with psycopg.connect(config.DB_DSN, row_factory=dict_row) as conn:
        rows = conn.execute(
            """SELECT occurred_on, instrument, kind, direction, amount, counterparty, is_self
               FROM transactions WHERE occurred_on BETWEEN %s AND %s ORDER BY occurred_on, occurred_at""",
            (first, last)).fetchall()
    spent = [r for r in rows if r["direction"] == "debit" and not r["is_self"] and r["kind"] != "card_bill_payment"]
    refunds = [r for r in rows if r["kind"] == "card_refund"]
    received = [r for r in rows if r["kind"] in ("upi_credit", "deposit_credit") and not r["is_self"]]
    total = lambda items: round(float(sum(r["amount"] for r in items)), 2)
    line = lambda r: f"{r['occurred_on']} {r['instrument']} {r['kind']} ₹{r['amount']:,.2f} {r['counterparty'] or ''}".strip()
    return {
        "period": f"{first} to {last}" if last != first else str(first),
        "spending_total": round(total(spent) - total(refunds), 2),
        "spending": [line(r) for r in spent],
        "refunds_total": total(refunds),
        "received_total": total(received),
        "own_account_transfers_total": total([r for r in rows if r["is_self"]]),
        "card_bill_payments_total": total([r for r in rows if r["kind"] == "card_bill_payment"]),
        "note": "Totals come from HDFC and ICICI alert emails only; cash and other banks are not included.",
    }


# Categories from the merchant name, first match wins; anything else that looks like a person's
# name or a UPI id is "Sent to people". Extend the lists as new merchants show up.
CATEGORIES = [
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
            """SELECT occurred_on, kind, amount, counterparty FROM transactions
               WHERE occurred_on BETWEEN %s AND %s AND direction = 'debit' AND NOT is_self
                 AND kind <> 'card_bill_payment'""", (first - timedelta(days=60), last)).fetchall()
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
    unusual = [f"{r['occurred_on']} ₹{r['amount']:,.2f} {r['counterparty'] or ''} ({category(r['counterparty'])})"
               for r in sorted(now, key=lambda r: r["amount"], reverse=True)
               if float(r["amount"]) >= max(5000.0, typical * 10)][:5]
    new = sorted({(r["counterparty"] or "").strip() for r in now
                  if (r["counterparty"] or "").strip() and (r["counterparty"] or "").strip().lower() not in history})
    return {"period": f"{first} to {last}", "compared_with": f"{prev_first} to {first - timedelta(days=1)}",
            "by_category": cats, "unusual_payments": unusual, "new_merchants": new[:10],
            "note": "From HDFC and ICICI alert emails only; categories are guessed from merchant names."}


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
    args = parser.parse_args()
    sync(args.days, args.verbose)


if __name__ == "__main__":
    main()
