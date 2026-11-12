"""Instant answers: everyday questions the app answers straight from Jarvis's data, without the AI model.

On a server without a graphics card the model needs half a minute or more for a question that comes with its data;
these take about a second. Only short, plain questions qualify: what's on the calendar, today's medicines, how much
was spent. One that needs thinking (why, should, can I, compare...), names a shop or category, is written in Tamil
script (the reply must be in Tamil) or comes with a file goes to the model as before. The app and Siri use this;
Telegram goes straight to Hermes.

Hermes keeps every other message of a chat. These answers are kept here, shown in the chat in time order, and passed
to Hermes with the user's next message there, so a follow-up ("and tomorrow?") still has them.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from .. import calendars, config, health, money
from . import data, notify

LABEL = "Answered instantly from your data"
MAX_WORDS = 12
_TAMIL_SCRIPT = re.compile(r"[஀-௿]")
# Words that ask for thinking, advice or a change rather than a list: the model answers those.
_NEEDS_THINKING = re.compile(
    r"\b(why|should|could i|would|can i|compare\w*|plan\w*|suggest\w*|advi[cs]e|help|free|available|cancel|move|add|book|"
    r"remind\w*|change|delete|remove|reduce|save|budget|than|vs|versus|more|less|enough|afford|usual\w*|average|"
    r"normal|if|explain|summar\w*|tips?|ideas?|best|worst|biggest|largest|most|missed|miss|week|month|yesterday|"
    r"days|ago)\b", re.I)
_SPENDING = re.compile(r"\b(spen[dt]|spending|expenses?)\b|\b(selav|chelav)", re.I)
# "spend on food", "at Swiggy", "for petrol": a shop or category, which needs the model to pick payments out.
_NAMED = re.compile(r"\b(on|at|for|to|from|with|in)\s+(?!(the|this|last|past|today|yesterday|my|a|week|month|days?|"
                    r"so|far)\b)[a-z]", re.I)
_PERIOD_WORDS = re.compile(r"\b(week|month|yesterday|days)\b", re.I)


def answer(text: str, now: datetime | None = None) -> str | None:
    """The instant answer to a message, or None when the model should answer it."""
    text = (text or "").strip()
    if not text or _TAMIL_SCRIPT.search(text) or len(text.split()) > MAX_WORDS:
        return None
    if _SPENDING.search(text):
        # Money questions may name a period ("this week", "last month"), so only the thinking words apply here.
        thinking = _NEEDS_THINKING.search(_PERIOD_WORDS.sub(" ", text))
        if thinking or _NAMED.search(text):
            return None
        period = money.period_from_text(text)
        return spending_answer(*period) if period else None
    if health.MEDICINE_WORDS.search(text):
        return None if _NEEDS_THINKING.search(text) else medicines_answer(health.today_doses(now))
    if _NEEDS_THINKING.search(_PERIOD_WORDS.sub(" ", text)):
        return None
    period = calendars.agenda_period(text)
    if period is None:
        return None
    first, days, label = period
    today = datetime.now(calendars.TZ).date()
    if today <= first and first + timedelta(days=days) <= today + timedelta(days=data.AGENDA_DAYS):
        # The Today screen's copy of the coming days, kept fresh in the background: no ~5 s wait on Google and Apple.
        listing = data.agenda(today)
        if "calendars" in listing["errors"]:
            return None  # the copy isn't there yet; the model reads the calendars itself
        listing = calendars.events_within(listing, first, days)
    else:
        listing = calendars.list_events(*calendars.day_range(first, days))
    if not listing["sources"]:
        return None  # no calendar connected: the model explains how to connect one
    return calendar_answer({"period": label, **listing})


# --- the answers ----------------------------------------------------------------------------------------------

_WHEN = {"TODAY": "Today", "TOMORROW": "Tomorrow", "the day after tomorrow": "The day after tomorrow",
         "the rest of this week": "The rest of this week", "next week": "Next week"}
_SOURCE = {"google": "Google", "apple": "Apple"}


def calendar_answer(agenda: dict) -> str:
    when, _, dates = agenda["period"].partition(", ")
    # A weekday ("Friday, Fri 13 Nov") already shows in the date.
    title = f"**{dates}**" if when.lower() in calendars._WEEKDAYS else f"**{_WHEN.get(when, when)}, {dates}**"
    days = {e["start"][:10] for e in agenda["events"]}
    lines = [title]
    for e in agenda["events"]:
        day = date.fromisoformat(e["start"][:10])
        prefix = f"{day:%a %d %b}, " if len(days) > 1 or " to " in dates else ""
        if e["all_day"]:
            when_text = "all day"
        else:
            end = (e["end"] or "")[-5:]
            when_text = e["start"][-5:] + (f"–{end}" if end else "")
        where = f" · {e['location']}" if e.get("location") else ""
        lines.append(f"- {prefix}{when_text} {e['title']}{where}")
    if not agenda["events"]:
        lines.append("Nothing on your calendar.")
    for source in agenda["errors"]:
        lines.append(f"\nI couldn't read your {_SOURCE.get(source, source)} calendar just now, "
                     "so this may be incomplete.")
    return "\n".join(lines)


_STATUS = {"taken": "taken ✓", "skipped": "skipped", "due": "not answered yet", "later": "later today"}


def medicines_answer(doses: list[dict]) -> str:
    if not doses:
        return "No medicines are scheduled for today."
    lines = ["**Today's medicines**"]
    for d in doses:
        name = f"{d['name']} {d['dose'] or ''}".strip()
        lines.append(f"- {d['time']} {name} — {_STATUS.get(d['status'], d['status'])}")
    return "\n".join(lines)


def _period_words(start: date, end: date, today: date) -> str:
    if start == end == today:
        return "today"
    if start == end == today - timedelta(days=1):
        return "yesterday"
    if start == end:
        return f"on {start:%a %d %b}"
    return f"from {start:%a %d %b} to {end:%a %d %b}"


def spending_answer(start: str, end: str, today: date | None = None) -> str:
    today = today or datetime.now(calendars.TZ).date()
    s = money.summary(start, end)
    when = _period_words(date.fromisoformat(start), date.fromisoformat(end), today)
    count = len(s["spending"])
    if not count:
        return f"No spending in your bank alerts {when}."
    d = s["display"]
    lines = [f"You spent **{d['spending_total']}** {when}, in {count} payment{'s' if count != 1 else ''}."]
    if start != end:
        cats = money.insights(start, end)["by_category"][:4]
        if cats:
            lines.append("Most on: " + " · ".join(f"{c['category']} {config.money(c['total'], decimals=False)}"
                                                    for c in cats))
    extra = [f"Refunds {d['refunds_total']}" if s["refunds_total"] else "",
             f"received {d['received_total']}" if s["received_total"] else ""]
    if any(extra):
        line = " · ".join(x for x in extra if x)
        lines.append(line[0].upper() + line[1:])
    lines.append("_From bank alert emails; cash isn't included._")
    return "\n".join(lines)


# --- keeping them with the chat -------------------------------------------------------------------------------

def save(session_id: str, question: str, reply: str) -> None:
    with notify.connect() as conn:
        conn.execute("INSERT INTO web_instant (session_id, question, answer) VALUES (%s, %s, %s)",
                     (session_id, question, reply))


def messages(session_id: str) -> list[dict]:
    """This chat's instant answers as app messages, with their times for merging into Hermes's."""
    with notify.connect() as conn:
        rows = conn.execute("SELECT question, answer, extract(epoch FROM created_at) AS at FROM web_instant "
                            "WHERE session_id = %s ORDER BY created_at", (session_id,)).fetchall()
    out = []
    for r in rows:
        out.append({"role": "user", "text": r["question"], "at": float(r["at"])})
        out.append({"role": "assistant", "text": r["answer"], "tools": [LABEL], "at": float(r["at"]) + 0.001})
    return out


NOTE_START = "[Jarvis answered these earlier in this chat straight from the user's data (not the model):"
NOTE_END = "[end of earlier answers]"
NOTE = re.compile(r"\n*" + re.escape(NOTE_START) + r"[\s\S]*?\n" + re.escape(NOTE_END))


def note_for_model(session_id: str) -> str:
    """The instant answers Hermes hasn't seen yet in this chat (marked as seen), as a note for the next message."""
    with notify.connect() as conn:
        rows = conn.execute("UPDATE web_instant SET told_model = true WHERE session_id = %s AND NOT told_model "
                            "RETURNING question, answer, created_at", (session_id,)).fetchall()
    if not rows:
        return ""
    parts = [f"Q: {r['question']}\nA: {r['answer'][:600]}" for r in sorted(rows, key=lambda r: r["created_at"])[-3:]]
    return "\n\n" + NOTE_START + "\n" + "\n\n".join(parts) + "\n" + NOTE_END
