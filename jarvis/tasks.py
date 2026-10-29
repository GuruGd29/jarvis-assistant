"""Tasks and reminders in Postgres. Dates are in the user's timezone (config.TIMEZONE)."""
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
