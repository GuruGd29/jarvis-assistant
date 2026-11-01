"""Tasks and reminders in Postgres. Dates are in the user's timezone (config.TIMEZONE)."""
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row

from . import config

TZ = ZoneInfo(config.TIMEZONE)
_COLUMNS = "id, title, notes, due_on, remind_at, priority, status, created_at, completed_at"


def _connect() -> psycopg.Connection:
    return psycopg.connect(config.DB_DSN, row_factory=dict_row)


def _plain(row: dict) -> dict:
    """JSON-friendly row with reminder times shown in local time."""
    out = {k: v for k, v in row.items() if v is not None}
    for key in ("due_on",):
        if key in out:
            out[key] = out[key].isoformat()
    for key in ("remind_at", "created_at", "completed_at"):
        if key in out:
            out[key] = out[key].astimezone(TZ).strftime("%Y-%m-%d %H:%M")
    return out


def parse_local_datetime(value: str) -> datetime:
    """'2026-10-28 18:00' or ISO 8601; naive times are taken as the user's local time."""
    moment = datetime.fromisoformat(value.strip())
    return moment if moment.tzinfo else moment.replace(tzinfo=TZ)


def today() -> date:
    return datetime.now(TZ).date()


_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_DAY = rf"(?P<day>today|tonight|tomorrow|day after tomorrow|(?:on |this |next )?(?:{'|'.join(_WEEKDAYS)}))"
_CLOCK = r"at (?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<ampm>[ap]\.?m\.?)?"
_DAY_THEN_CLOCK = re.compile(rf"\s+{_DAY}\s+{_CLOCK}$", re.I)
_CLOCK_THEN_DAY = re.compile(rf"\s+{_CLOCK}\s+{_DAY}$", re.I)
_IN_MINUTES = re.compile(r"\s+in\s+(\d{1,3})\s*(min(?:ute)?s?|hours?|hrs?)$", re.I)


def reminder_from_text(text: str, now: datetime | None = None) -> tuple[str, str, str] | None:
    """'Remind me to call the plumber tomorrow at 10 am' -> ('Call the plumber', '2026-11-02', '2026-11-02 10:00').
    Only plain English with a clear day and time, or 'in 30 minutes'; anything else is left to the model, which
    sometimes got tomorrow's date wrong or wrote the add_task call as text instead of making it."""
    m = re.fullmatch(r"\s*(?:(?:please|can you|could you)\s+)?remind me\s+(?:to\s+|about\s+)?(.+?)\s*[.!?]?\s*",
                     text or "", re.I)
    if not m:
        return None
    now = now or datetime.now(TZ)
    rest = m[1]
    if w := _IN_MINUTES.search(rest):
        moment = now + timedelta(minutes=int(w[1]) * (60 if w[2].lower().startswith("h") else 1))
    elif w := _DAY_THEN_CLOCK.search(rest) or _CLOCK_THEN_DAY.search(rest):
        day_text = w["day"].lower()
        if (weekday := day_text.split()[-1]) in _WEEKDAYS:
            day = now.date() + timedelta(days=(_WEEKDAYS.index(weekday) - now.weekday()) % 7 or 7)
        else:
            day = now.date() + timedelta(days={"today": 0, "tonight": 0, "tomorrow": 1, "day after tomorrow": 2}[day_text])
        hour, minute, ampm = int(w["hour"]), int(w["minute"] or 0), (w["ampm"] or "").lower()[:1]
        if ampm:
            if not 1 <= hour <= 12:
                return None
            hour = hour % 12 + (12 if ampm == "p" else 0)
        elif day_text == "tonight" and hour < 12:
            hour += 12
        elif hour < 13 and w["minute"] is None:
            return None  # "at 6" could be morning or evening
        if hour > 23 or minute > 59:
            return None
        moment = datetime(day.year, day.month, day.day, hour, minute, tzinfo=now.tzinfo or TZ)
    else:
        return None
    title = rest[:w.start()].strip(" ,")
    if not title or moment <= now:
        return None
    return title[0].upper() + title[1:], moment.date().isoformat(), moment.strftime("%Y-%m-%d %H:%M")


def add_task(title: str, due_on: str | None = None, remind_at: str | None = None,
             priority: int = 2, notes: str | None = None) -> dict:
    with _connect() as conn:
        row = conn.execute(
            f"INSERT INTO tasks (title, notes, due_on, remind_at, priority) VALUES (%s, %s, %s, %s, %s) RETURNING {_COLUMNS}",
            (title.strip(), notes, date.fromisoformat(due_on) if due_on else None,
             parse_local_datetime(remind_at) if remind_at else None, min(3, max(1, priority))),
        ).fetchone()
    return _plain(row)


def list_tasks(scope: str = "open") -> list[dict]:
    """scope: today (due today or overdue), overdue, upcoming (next 7 days), open (all open), done (last 7 days)."""
    where = {
        "today": "status = 'open' AND due_on <= %(today)s",
        "overdue": "status = 'open' AND due_on < %(today)s",
        "upcoming": "status = 'open' AND due_on BETWEEN %(today)s AND %(today)s + 7",
        "open": "status = 'open'",
        "done": "status = 'done' AND completed_at > now() - interval '7 days'",
    }.get(scope, "status = 'open'")
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT {_COLUMNS} FROM tasks WHERE {where} ORDER BY due_on NULLS LAST, priority, id",
            {"today": today()},
        ).fetchall()
    return [_plain(r) for r in rows]


def update_task(task_id: int, *, status: str | None = None, due_on: str | None = None,
                remind_at: str | None = None, title: str | None = None) -> dict:
    sets, params = [], {"id": task_id}
    if status:
        if status not in ("open", "done", "cancelled"):
            raise ValueError("status must be open, done or cancelled")
        sets.append("status = %(status)s")
        sets.append("completed_at = CASE WHEN %(status)s = 'done' THEN now() ELSE NULL END")
        params["status"] = status
    if due_on is not None:
        sets.append("due_on = %(due_on)s")
        params["due_on"] = date.fromisoformat(due_on) if due_on else None
    if remind_at is not None:
        sets.append("remind_at = %(remind_at)s, reminded_at = NULL")
        params["remind_at"] = parse_local_datetime(remind_at) if remind_at else None
    if title:
        sets.append("title = %(title)s")
        params["title"] = title.strip()
    if not sets:
        raise ValueError("nothing to change")
    with _connect() as conn:
        row = conn.execute(f"UPDATE tasks SET {', '.join(sets)} WHERE id = %(id)s RETURNING {_COLUMNS}", params).fetchone()
    if row is None:
        raise ValueError(f"no task with id {task_id}")
    return _plain(row)


def take_due_reminders() -> list[dict]:
    """Reminders whose time has come, marked as sent in the same statement so each fires once."""
    with _connect() as conn:
        rows = conn.execute(
            f"""UPDATE tasks SET reminded_at = now()
                WHERE status = 'open' AND reminded_at IS NULL AND remind_at <= now()
                RETURNING {_COLUMNS}"""
        ).fetchall()
    return [_plain(r) for r in rows]


def snooze_reminder(task_id: int, minutes: int) -> dict:
    when = (datetime.now(TZ) + timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M")
    return update_task(task_id, remind_at=when)
