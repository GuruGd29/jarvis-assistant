"""Medicine reminders and lab results. Jarvis tracks and flags; it never diagnoses or changes doses."""
import csv
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row

from . import config

TZ = ZoneInfo(config.TIMEZONE)
_DAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
# A dose is reminded once, as soon as its time has passed, unless more than this late (e.g. Mac was off).
_LATE_LIMIT = timedelta(hours=2)


def _connect():
    return psycopg.connect(config.DB_DSN, row_factory=dict_row)


# --- Medicines -----------------------------------------------------------------

def _parse_times(times: str) -> list[str]:
    out = []
    for raw in re.split(r"[,;/ ]+(?:and )?", times.strip().lower()):
        if not raw:
            continue
        m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", raw)
        if not m:
            raise ValueError(f"time {raw!r} not understood; use HH:MM like 08:00 or 8pm")
        hour, minute = int(m[1]), int(m[2] or 0)
        if m[3] == "pm" and hour < 12:
            hour += 12
        if m[3] == "am" and hour == 12:
            hour = 0
        if hour > 23 or minute > 59:
            raise ValueError(f"time {raw!r} is not a valid time of day")
        out.append(f"{hour:02d}:{minute:02d}")
    return sorted(set(out))


def _parse_weekdays(days: str | None) -> list[int] | None:
    if not days or days.strip().lower() in ("daily", "every day", "everyday"):
        return None
    found = sorted({_DAYS[d[:3]] for d in re.findall(r"[a-z]+", days.lower()) if d[:3] in _DAYS})
    if not found:
        raise ValueError("days not understood; use names like 'mon,thu' or 'daily'")
    return found


def add_medication(name: str, times: str, dose: str | None = None, days: str | None = None,
                   start_on: str | None = None, end_on: str | None = None, notes: str | None = None) -> dict:
    with _connect() as conn:
        return conn.execute(
            """INSERT INTO medications (name, dose, times, weekdays, start_on, end_on, notes)
               VALUES (%s, %s, %s, %s, COALESCE(%s::date, current_date), %s, %s)
               RETURNING id, name, dose, times, weekdays, start_on::text, end_on::text""",
            (name.strip(), dose, _parse_times(times), _parse_weekdays(days), start_on, end_on, notes)).fetchone()


def list_medications(include_stopped: bool = False) -> list[dict]:
    with _connect() as conn:
        return conn.execute(
            f"""SELECT id, name, dose, times, weekdays, start_on::text, end_on::text, active FROM medications
                {'' if include_stopped else 'WHERE active'} ORDER BY id""").fetchall()


def stop_medication(medication_id: int) -> dict:
    with _connect() as conn:
        row = conn.execute("UPDATE medications SET active = false WHERE id = %s RETURNING id, name", (medication_id,)).fetchone()
    if row is None:
        raise ValueError(f"no medicine with id {medication_id}")
    return row


def take_due_doses(now: datetime | None = None) -> list[dict]:
    """Create today's doses whose time has come and return those not yet reminded (each fires once)."""
    now = now or datetime.now(TZ)
    today = now.date()
    with _connect() as conn:
        for med in conn.execute("SELECT * FROM medications WHERE active").fetchall():
            if med["start_on"] > today or (med["end_on"] and med["end_on"] < today):
                continue
            if med["weekdays"] is not None and today.weekday() not in med["weekdays"]:
                continue
            for hhmm in med["times"]:
                due = datetime.combine(today, datetime.strptime(hhmm, "%H:%M").time(), TZ)
                if due <= now:
                    conn.execute("INSERT INTO medication_doses (medication_id, due_at) VALUES (%s, %s) "
                                 "ON CONFLICT DO NOTHING", (med["id"], due))
        rows = conn.execute(
            """UPDATE medication_doses d SET reminded_at = now()
               FROM medications m
               WHERE m.id = d.medication_id AND d.reminded_at IS NULL AND d.status = 'due'
                 AND d.due_at <= %s AND d.due_at > %s
               RETURNING d.id, m.name, m.dose, d.due_at""", (now, now - _LATE_LIMIT)).fetchall()
        # Doses that were never reminded (e.g. Mac asleep) are marked reminded so they don't fire hours late.
        conn.execute("UPDATE medication_doses SET reminded_at = now() WHERE reminded_at IS NULL AND due_at <= %s",
                     (now - _LATE_LIMIT,))
    return rows


def mark_dose(dose_id: int, status: str = "taken") -> dict:
    if status not in ("taken", "skipped"):
        raise ValueError("status must be taken or skipped")
    with _connect() as conn:
        row = conn.execute(
            """UPDATE medication_doses d SET status = %s, answered_at = now() FROM medications m
               WHERE d.id = %s AND m.id = d.medication_id
               RETURNING d.id, m.name, m.dose, d.status, to_char(d.due_at AT TIME ZONE %s, 'YYYY-MM-DD HH24:MI') AS due""",
            (status, dose_id, config.TIMEZONE)).fetchone()
    if row is None:
        raise ValueError(f"no dose with id {dose_id}")
    return row


def adherence(days: int = 7) -> dict:
    """Doses taken, skipped and not answered over the last N days."""
    with _connect() as conn:
        rows = conn.execute(
            """SELECT m.name, m.dose, d.status, to_char(d.due_at AT TIME ZONE %s, 'YYYY-MM-DD HH24:MI') AS due
               FROM medication_doses d JOIN medications m ON m.id = d.medication_id
               WHERE d.due_at > now() - make_interval(days => %s) ORDER BY d.due_at""",
            (config.TIMEZONE, days)).fetchall()
    return {"days": days,
            "taken": sum(r["status"] == "taken" for r in rows),
            "skipped": sum(r["status"] == "skipped" for r in rows),
            "not_answered": [f"{r['due']} {r['name']} {r['dose'] or ''}".strip() for r in rows if r["status"] == "due"]}


def doses_today() -> list[str]:
    today = datetime.now(TZ).date()
    out = []
    for med in list_medications():
        if med["weekdays"] is None or today.weekday() in med["weekdays"]:
            out += [f"{t} {med['name']} {med['dose'] or ''}".strip() for t in med["times"]]
    return sorted(out)


# --- Lab results ---------------------------------------------------------------

def _parse_value(text: str) -> tuple[float, str | None] | None:
    m = re.match(r"\s*([<>]?\s*[\d,]*\.?\d+)\s*(.*)$", text)
    if not m:
        return None
    return float(m[1].replace(",", "").lstrip("<> ")), (m[2].strip() or None)


def _parse_range(text: str) -> tuple[float | None, float | None]:
    t = text.lower().replace(",", "")
    if m := re.search(r"([\d.]+)\s*[-–to]+\s*([\d.]+)", t):
        return float(m[1]), float(m[2])
    if m := re.search(r"(?:below|under|less than|<|up to)\s*([\d.]+)", t):
        return None, float(m[1])
    if m := re.search(r"(?:above|over|more than|>)\s*([\d.]+)", t):
        return float(m[1]), None
    return None, None


def add_lab_result(test: str, value: str, tested_on: str, reference: str | None = None,
                   source: str = "told to Jarvis") -> dict:
    parsed = _parse_value(value)
    if parsed is None:
        raise ValueError(f"value {value!r} has no number")
    low, high = _parse_range(reference or "")
    with _connect() as conn:
        return conn.execute(
            """INSERT INTO lab_results (test, value, unit, ref_low, ref_high, ref_text, tested_on, source)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (test, tested_on, source) DO UPDATE SET value = EXCLUDED.value, unit = EXCLUDED.unit,
                 ref_low = EXCLUDED.ref_low, ref_high = EXCLUDED.ref_high, ref_text = EXCLUDED.ref_text
               RETURNING id, test, value::float, unit, tested_on::text, ref_text""",
            (test.strip(), parsed[0], parsed[1], low, high, reference, date.fromisoformat(tested_on), source)).fetchone()


def _flag(row: dict) -> str:
    if row["ref_low"] is not None and row["value"] < row["ref_low"]:
        return "LOW"
    if row["ref_high"] is not None and row["value"] > row["ref_high"]:
        return "HIGH"
    return "in range" if row["ref_low"] is not None or row["ref_high"] is not None else "no reference range"


def lab_results(test: str | None = None) -> dict:
    """History for one test (name match), or the latest value of every test, each flagged LOW/HIGH/in range."""
    with _connect() as conn:
        if test:
            rows = conn.execute("""SELECT * FROM lab_results WHERE test ILIKE %s ORDER BY test, tested_on""",
                                (f"%{test}%",)).fetchall()
        else:
            rows = conn.execute("""SELECT DISTINCT ON (lower(test)) * FROM lab_results
                                   ORDER BY lower(test), tested_on DESC""").fetchall()
    items = [f"{r['tested_on']} {r['test']}: {float(r['value']):g} {r['unit'] or ''} (ref {r['ref_text'] or 'n/a'}) "
             f"-> {_flag(r)} [{r['source']}]" for r in rows]
    return {"results": items, "out_of_range": [i for i in items if "-> LOW" in i or "-> HIGH" in i],
            "note": "Flags compare with the report's reference range; they are not a diagnosis. Discuss changes with a doctor."}


def _table_rows(text: str) -> list[list[str]]:
    """Cells of each table line: split on pipes in a Markdown table, so "7,500" and "1,50,000" stay whole,
    and as CSV otherwise (quoted fields may hold commas)."""
    rows = []
    for line in text.splitlines():
        if line.count("|") >= 2:
            rows.append([c.strip() for c in line.strip().strip("|").split("|")])
        elif line.count(",") >= 2:
            rows.append([c.strip() for c in next(csv.reader([line]))])
    return rows


def import_lab_reports(folder: Path | None = None) -> dict:
    """Read 'Test | Result | Reference range' tables from Markdown/CSV/text reports in ~/Jarvis/health."""
    folder = folder or config.DATA_ROOT / "health"
    added, files = 0, 0
    for path in sorted(folder.rglob("*")):
        if path.suffix.lower() not in (".md", ".txt", ".csv") or path.name.startswith("."):
            continue
        text = path.read_text(errors="replace")
        day = None
        if m := re.search(r"(\d{1,2} (?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]* \d{4})", text, re.I):
            day = datetime.strptime(re.sub(r"\b([A-Za-z]{3})[A-Za-z]*", r"\1", m[1]), "%d %b %Y").date()
        elif m := re.search(r"(\d{4}-\d{2}(?:-\d{2})?)", path.name):
            day = date.fromisoformat(m[1] if len(m[1]) == 10 else m[1] + "-01")
        if day is None:
            continue
        rows = _table_rows(text)
        found = 0
        for cells in rows:
            if len(cells) >= 2 and _parse_value(cells[1]) and not set(cells[1]) <= set("-: "):
                add_lab_result(cells[0], cells[1], str(day), cells[2] if len(cells) > 2 else None, path.name)
                found += 1
        if found:
            files += 1
            added += found
    return {"files": files, "results_saved": added}
