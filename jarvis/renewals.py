"""Bills, renewals and expiry dates found in the user's indexed files, and Telegram alerts before them.

Read from the text of ~/Jarvis files on every run (nothing is stored), so a new or changed file is
picked up as soon as it is indexed. Lines that mention renewing, expiring or being valid until a date:

  "Netflix Standard - INR 499 per month - renews on the 5th"      monthly, on the 5th
  "Google One 200 GB - INR 1,300 per year - renews 2 February"     yearly, every 2 February
  "Date of expiry: 09 June 2031"                                   once, on that date
  "The policy is valid from 15 March 2026 to 14 March 2027"        once, on the last date in the line

  jarvis-renewal-alerts   alerts ALERT_DAYS before each date (Hermes cron, 9 am); prints nothing otherwise
"""
import re
from calendar import monthrange
from datetime import date, timedelta
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from . import config, tasks

# Monthly and yearly subscriptions renew by themselves: 2 days' notice is enough. A one-off date
# (passport, insurance, a membership end) needs time to act, so it also gets a warning a month ahead.
ALERT_DAYS = {"monthly": (2,), "yearly": (2,), "once": (30, 2)}
_KEYWORDS = re.compile(r"renew|expir|valid\s+(?:from|till|until|up\s*to|upto|to)|due\s+(?:on|date)|maturity", re.I)
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
_MONTH = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
_DAY_MONTH_YEAR = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+{_MONTH},?\s+(\d{{4}})\b", re.I)
_MONTH_DAY_YEAR = re.compile(rf"\b{_MONTH}\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", re.I)
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_NUMERIC = re.compile(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})\b")  # Indian order: day/month/year
_DAY_MONTH = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+{_MONTH}(?!\w|,?\s+\d{{4}})", re.I)
_MONTHLY = re.compile(r"\bon\s+the\s+(\d{1,2})(?:st|nd|rd|th)\b", re.I)
_AMOUNT = re.compile(r"(?:INR|Rs\.?|₹)\s*([\d,]+(?:\.\d{1,2})?)", re.I)


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _next_monthly(day: int, today: date) -> date:
    year, month = today.year, today.month
    for _ in range(3):
        # "The 31st" falls on the last day of shorter months (30 Nov, 28 or 29 Feb) rather than skipping them.
        found = _safe_date(year, month, min(day, monthrange(year, month)[1]))
        if found and found >= today:
            return found
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return today


def _when(line: str, today: date) -> tuple[date, str] | None:
    """The next date a line refers to, and how often it repeats."""
    fixed = []
    for m in _DAY_MONTH_YEAR.finditer(line):
        fixed.append((m.start(), _safe_date(int(m[3]), _MONTHS[m[2][:3].lower()], int(m[1]))))
    for m in _MONTH_DAY_YEAR.finditer(line):
        fixed.append((m.start(), _safe_date(int(m[3]), _MONTHS[m[1][:3].lower()], int(m[2]))))
    for m in _ISO.finditer(line):
        fixed.append((m.start(), _safe_date(int(m[1]), int(m[2]), int(m[3]))))
    for m in _NUMERIC.finditer(line):
        fixed.append((m.start(), _safe_date(int(m[3]), int(m[2]), int(m[1]))))
    fixed = [(pos, d) for pos, d in fixed if d]
    if fixed:  # "valid from X to Y": the last date is the one that matters
        return max(fixed)[1], "once"
    if m := _MONTHLY.search(line):
        return _next_monthly(int(m[1]), today), "monthly"
    if m := _DAY_MONTH.search(line):
        month, day = _MONTHS[m[2][:3].lower()], int(m[1])
        found = _safe_date(today.year, month, day)
        if found and found < today:
            found = _safe_date(today.year + 1, month, day)
        return (found, "yearly") if found else None
    return None


def _name(line: str, title: str) -> str:
    if " - " in line:
        return line.split(" - ", 1)[0].strip()
    label = line.split(":", 1)[0].strip() if ":" in line else ""
    if label and not re.search(r"date|expir|valid|renew|due", label, re.I):
        return label
    return title[:1].upper() + title[1:]


def upcoming(days: int = 60, today: date | None = None) -> list[dict]:
    """Renewals and expiries in the next `days` days, soonest first."""
    today = today or tasks.today()
    with psycopg.connect(config.DB_DSN, row_factory=dict_row) as conn:
        rows = conn.execute("""SELECT d.path, coalesce(d.title, '') AS title, c.content
                               FROM chunks c JOIN documents d ON d.id = c.document_id
                               WHERE c.content ~* '(renew|expir|valid|due|maturity)'
                               ORDER BY d.id, c.ord""").fetchall()
    found, seen = [], set()
    for row in rows:
        for line in row["content"].splitlines():
            line = " ".join(line.split())
            if not _KEYWORDS.search(line):
                continue
            when = _when(line, today)
            if not when or not (today <= when[0] <= today + timedelta(days=days)):
                continue
            name = _name(line, row["title"])
            if (name, when[0]) in seen:
                continue
            seen.add((name, when[0]))
            amount = _AMOUNT.search(line)
            found.append({"item": name, "date": when[0].isoformat(), "repeats": when[1],
                          "what": "expires" if re.search(r"expir|valid", line, re.I) else "renews",
                          "amount": f"₹{amount[1]}" if amount else None,
                          "source": Path(row["path"]).name, "line": line})
    return sorted(found, key=lambda r: r["date"])


def alerts() -> None:
    today = tasks.today()
    for r in upcoming(max(max(days) for days in ALERT_DAYS.values()), today):
        days_left = (date.fromisoformat(r["date"]) - today).days
        if days_left not in ALERT_DAYS[r["repeats"]]:
            continue
        amount = f", {r['amount']}" if r["amount"] else ""
        print(f"🔔 {r['item']} {r['what']} in {days_left} days "
              f"({date.fromisoformat(r['date']):%a %d %b}){amount}.\n(from {r['source']})\n")
