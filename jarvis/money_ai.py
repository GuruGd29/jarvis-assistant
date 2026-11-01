"""Bank emails from banks without a built-in reader, read by the local AI.

The model fills a fixed form (Ollama structured output) for each email; nothing it says is stored unless it
checks out: the amount must appear in the email exactly as the model copied it, the currency must be the user's
(JARVIS_CURRENCY), and the date must be near the email's own date. Each email is read once and the outcome is
remembered in `money_ai_seen`, so a "not a transaction" answer is not asked again.

Reading needs the chat model, and a read pushes the current chat out of the model's memory (minutes to rebuild on
a CPU server), so by default it runs once a night: `jarvis-money-sync --ai` (JARVIS_MONEY_AI=nightly).
"""
import json
import re
from datetime import date, datetime, timedelta

import httpx

from . import config

# What the model must return. Amounts are text copied from the email, so they can be checked against it.
SCHEMA = {
    "type": "object",
    "properties": {
        "email_type": {"type": "string", "enum": ["transaction", "card_statement", "other"]},
        "kind": {"type": "string", "enum": ["account_debit", "account_credit", "card_purchase", "card_refund",
                                             "card_bill_payment", "card_payment_received", "none"]},
        "amount": {"type": "string"},
        "currency": {"type": "string"},
        "bank": {"type": "string"},
        "card_or_account": {"type": "string", "enum": ["credit card", "debit card", "account", "unknown"]},
        "last_digits": {"type": "string"},
        "counterparty": {"type": "string"},
        "date": {"type": "string"},
        "statement_total_due": {"type": "string"},
        "statement_minimum_due": {"type": "string"},
        "statement_due_date": {"type": "string"},
    },
    "required": ["email_type", "kind", "amount", "currency", "bank", "card_or_account", "last_digits",
                 "counterparty", "date", "statement_total_due", "statement_minimum_due", "statement_due_date"],
}

_PROMPT = """You read one email from a bank and fill in a form. Copy text exactly as written in the email; never \
calculate, convert or guess. Use "" for anything the email does not say.

email_type: "transaction" if the email reports one payment, purchase, refund, transfer or deposit that already \
happened (an alert that also shows an available limit or balance is still a transaction); "card_statement" only \
if it announces a credit card bill with BOTH a total amount due and a payment due date; otherwise "other" \
(offers, OTPs, login alerts, declined or failed payments, reminders, newsletters).
kind (for a transaction): account_debit = money left a bank account (UPI, transfer, debit order, ATM, debit card is \
NOT this, see card_purchase); account_credit = money arrived in a bank account; card_purchase = paid with a credit or \
debit card; card_refund = a refund or reversal to a card; card_bill_payment = the user paid a credit card bill from \
a bank account; card_payment_received = a card company confirms it received a bill payment; otherwise "none".
amount: the transaction amount exactly as written, digits and separators only (e.g. "1,250.00"), no currency sign.
currency: the ISO code of the amount's currency (e.g. INR, USD, EUR, GBP).
bank: the bank's short name (e.g. "SBI", "Chase", "Barclays").
card_or_account and last_digits: which card or account, and the digits of its number shown in the email (e.g. "4321").
counterparty: the merchant, payee or sender, as written.
date: the transaction date as YYYY-MM-DD.
statement_total_due, statement_minimum_due, statement_due_date: only for a card_statement; amounts as written, \
date as YYYY-MM-DD.

Email received {received}.
Subject: {subject}

{body}"""

# Our kinds, so AI-read rows follow the same rules as the built-in readers (spending, cards, bill payments).
_KINDS = {"account_debit": ("account_debit", "debit"), "account_credit": ("deposit_credit", "credit"),
          "card_purchase": ("card_spend", "debit"), "card_refund": ("card_refund", "credit"),
          "card_bill_payment": ("card_bill_payment", "debit"),
          "card_payment_received": ("card_payment_confirmation", "credit")}
_OWN_CURRENCY = {config.CURRENCY, config.CURRENCY_SYMBOL} | ({"INR", "RS", "RS.", "₹"} if config.CURRENCY == "INR" else set())


def ask_model(subject: str, body: str, received: datetime) -> dict:
    response = httpx.post(f"{config.OLLAMA_URL}/api/generate", timeout=900, json={
        "model": config.CHAT_MODEL, "stream": False, "format": SCHEMA, "keep_alive": "2h",
        "prompt": _PROMPT.format(received=f"{received:%Y-%m-%d}", subject=subject, body=body[:4000]),
        "options": {"temperature": 0},  # the model's own num_ctx, so it is not reloaded
    })
    response.raise_for_status()
    return json.loads(response.json()["response"])


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _amount_in(text: str, written: str) -> float | None:
    """The amount, if the model's copy of it really is in the email; None otherwise."""
    written = _flat(written).strip(" .")
    if not re.fullmatch(r"\d[\d,.' ]*", written) or not re.search(
            rf"(?<!\d)(?<!\d[.,]){re.escape(written)}(?![\d]|[.,]\d)", _flat(text)):
        return None
    value = _number(written)
    return value if value and value > 0 else None


def _number(written: str) -> float | None:
    """A number as a bank writes it, in any style: 1,50,000.00 · 1,250.00 · 1.234,56 · 2 499,00 · 1'234.50.
    The bank's style, not the user's, so: with both separators the last one is the decimal point; a lone
    separator followed by exactly three digits groups thousands, by one or two digits it is the decimal point."""
    plain = re.sub(r"[\s']", "", written)
    seps = [c for c in plain if c in ".,"]
    if not seps:
        return float(plain)
    last = plain.rfind(seps[-1])
    if len(set(seps)) == 2 or (len(seps) == 1 and len(plain) - last - 1 in (1, 2)):
        whole, frac = plain[:last], plain[last + 1:]
    else:
        whole, frac = plain, ""
    whole = re.sub(r"[.,]", "", whole)
    if not whole.isdigit() or (frac and not frac.isdigit()):
        return None
    return float(f"{whole}.{frac or 0}")


def _day(text: str, near: date, before: int, after: int) -> date | None:
    try:
        day = date.fromisoformat(text.strip())
    except ValueError:
        return None
    return day if near - timedelta(days=before) <= day <= near + timedelta(days=after) else None


def read_email(subject: str, body: str, received: datetime, answer: dict | None = None) -> tuple[str, dict | None]:
    """("transaction", row) or ("card_statement", row), or (reason, None) when nothing should be stored.
    `answer` is the model's form, for tests; normally the model is asked here."""
    a = answer if answer is not None else ask_model(subject, body, received)
    text = f"{subject}\n{body}"
    bank = re.sub(r"[^A-Za-z0-9 &.-]", "", a.get("bank") or "").strip()[:20] or "Bank"
    digits = re.sub(r"\D", "", a.get("last_digits") or "")[-4:]
    kind_of = a.get("card_or_account")
    instrument = (f"{bank} card {digits}" if kind_of == "credit card" else f"{bank} debit card {digits}"
                  if kind_of == "debit card" else f"{bank} a/c {digits}").strip()
    currency = (a.get("currency") or "").strip().upper()
    if currency and currency not in _OWN_CURRENCY:
        return "other_currency", None  # like the built-in readers: foreign-currency charges are not counted

    if a.get("email_type") == "card_statement":
        total = _amount_in(text, a.get("statement_total_due") or "")
        due_on = _day(a.get("statement_due_date") or "", received.date(), 0, 62)
        if total is not None and due_on is not None and kind_of == "credit card":
            minimum = _amount_in(text, a.get("statement_minimum_due") or "")
            return "card_statement", {"card": instrument, "name": f"{bank} credit card", "statement_on": received.date(),
                                      "total_due": total, "min_due": minimum, "due_on": due_on}
        if a.get("kind") not in _KINDS:  # not a bill after all; a purchase alert is checked as a transaction below
            return "statement_not_clear", None
        a = {**a, "email_type": "transaction"}

    if a.get("email_type") != "transaction" or a.get("kind") not in _KINDS:
        return "not_a_transaction", None
    amount = _amount_in(text, a.get("amount") or "")
    if amount is None:
        return "amount_not_in_email", None
    kind, direction = _KINDS[a["kind"]]
    if kind in ("card_spend", "card_refund", "card_payment_confirmation") and kind_of not in ("credit card", "debit card"):
        instrument = f"{bank} card {digits}".strip()
    return "transaction", {
        "bank": bank, "instrument": instrument, "kind": kind, "direction": direction, "amount": amount,
        "counterparty": _flat(a.get("counterparty") or "")[:80] or None,
        "occurred_on": _day(a.get("date") or "", received.date(), 7, 1) or received.date(), "reference": None}
