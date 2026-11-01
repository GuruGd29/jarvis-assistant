"""Data for the app's Today, Money and More screens, from the same sources Jarvis uses in chat."""
import threading
import time
from datetime import date, datetime, timedelta

from .. import calendars, config, health, learn, money, renewals, tasks


def _greeting(now: datetime) -> str:
    h = now.hour  # night is 9 pm to 5 am
    return "Good night" if h >= 21 or h < 5 else "Good morning" if h < 12 else "Good afternoon" if h < 17 else "Good evening"


def _event(e: dict) -> dict:
    day = date.fromisoformat(e["start"][:10])
    return {"day": day.isoformat(), "time": None if e["all_day"] else e["start"][-5:],
            "end": None if e["all_day"] or not e.get("end") else e["end"][-5:],
            "title": e["title"], "where": e.get("location"), "source": e["source"], "calendar": e.get("calendar")}


def medicines_today() -> list[dict]:
    """Today's doses with their status; a dose not yet due has no row until it is reminded or answered."""
    now = datetime.now(health.TZ)
    out = []
    with health._connect() as conn:
        for med in health.list_medications():
            if med["weekdays"] is not None and now.weekday() not in med["weekdays"]:
                continue
            for hhmm in med["times"]:
                due = datetime.combine(now.date(), datetime.strptime(hhmm, "%H:%M").time(), health.TZ)
                row = conn.execute("SELECT status FROM medication_doses WHERE medication_id = %s AND due_at = %s",
                                   (med["id"], due)).fetchone()
                out.append({"medication_id": med["id"], "time": hhmm, "name": med["name"], "dose": med["dose"],
                            "status": row["status"] if row else "due", "past": due <= now})
    return sorted(out, key=lambda d: d["time"])


def mark_medicine(medication_id: int, hhmm: str, status: str) -> dict:
    """Mark today's dose taken, skipped or (undo) due; works before the reminder has fired too."""
    if status not in ("taken", "skipped", "due"):
        raise ValueError("status must be taken, skipped or due")
    due = datetime.combine(tasks.today(), datetime.strptime(hhmm, "%H:%M").time(), health.TZ)
    with health._connect() as conn:
        conn.execute("""INSERT INTO medication_doses (medication_id, due_at, reminded_at) VALUES (%s, %s, now())
                        ON CONFLICT DO NOTHING""", (medication_id, due))
        conn.execute("""UPDATE medication_doses SET status = %s, answered_at = CASE WHEN %s = 'due' THEN NULL ELSE now() END
                        WHERE medication_id = %s AND due_at = %s""", (status, status, medication_id, due))
    return {"ok": True}


# Google + iCloud take ~5 s to read, so Today uses a copy at most AGENDA_STALE old and refreshes it in the
# background (the server also refreshes it every few minutes).
AGENDA_STALE = 120
_agenda = {"day": None, "value": None, "at": 0.0, "busy": False}
_agenda_lock = threading.Lock()


def _read_agenda(day: date) -> None:
    try:
        value = calendars.list_events(*calendars.day_range(day, 8))
        _agenda.update(day=day, value=value, at=time.time())
    finally:
        _agenda["busy"] = False


def agenda(day: date, wait: bool = True) -> dict | None:
    with _agenda_lock:
        fresh = _agenda["day"] == day and time.time() - _agenda["at"] <= AGENDA_STALE
        start = not fresh and not _agenda["busy"]
        if start:
            _agenda["busy"] = True
    usable = _agenda["day"] == day and _agenda["value"] is not None
    if start and (usable or not wait):
        threading.Thread(target=_read_agenda, args=(day,), daemon=True).start()
    elif start:
        _read_agenda(day)                       # nothing usable yet (first open, or a new day): wait once
    deadline = time.time() + 30
    while wait and not (_agenda["day"] == day and _agenda["value"] is not None) and time.time() < deadline:
        time.sleep(0.2)                         # another request is already reading
    if _agenda["day"] == day and _agenda["value"] is not None:
        return _agenda["value"]
    return {"events": [], "errors": {"calendars": "took too long to answer"}, "sources": calendars.configured_sources()}


def today() -> dict:
    now = datetime.now(health.TZ)
    day = now.date()
    agenda_now = agenda(day)
    open_tasks = tasks.list_tasks("open")
    week_end = (day + timedelta(days=7)).isoformat()
    due_soon = [t for t in open_tasks if t.get("due_on") and t["due_on"] <= week_end]
    spent = money.summary(str(day))
    return {
        "date": day.isoformat(), "greeting": _greeting(now),
        "events": [_event(e) for e in agenda_now["events"]][:12],
        "calendar_errors": list(agenda_now["errors"]), "calendars_connected": bool(agenda_now["sources"]),
        "tasks": [{"id": t["id"], "title": t["title"], "due_on": t.get("due_on"), "remind_at": t.get("remind_at"),
                   "priority": t.get("priority"), "notes": t.get("notes")} for t in open_tasks],
        "due_soon": len(due_soon),
        "medicines": medicines_today(),
        "renewals": renewals.upcoming(30, day),
        "spent_today": spent["spending_total"], "payments_today": len(spent["spending"]),
    }


def complete_task(task_id: int, done: bool) -> dict:
    return tasks.update_task(task_id, status="done" if done else "open")


# Reading Reminders through the Mac app takes 10-20 s, so the app always gets the last copy at once and a
# copy older than REMINDERS_STALE is refreshed in the background.
REMINDERS_STALE = 240
_reminders = {"value": None, "at": 0.0, "busy": False}
_reminders_lock = threading.Lock()


def _refresh_reminders() -> None:
    try:
        calendars._REMINDERS_CACHE.clear()  # force a fresh read
        value = calendars.iphone_reminders()
        _reminders.update(value=value, at=time.time())
    except Exception as error:
        _reminders.update(value={"available": False, "reason": f"Couldn't read iPhone Reminders ({type(error).__name__})"},
                          at=time.time())
    finally:
        _reminders["busy"] = False


def iphone_reminders(wait: bool = True) -> dict | None:
    with _reminders_lock:
        stale = time.time() - _reminders["at"] > REMINDERS_STALE
        start = stale and not _reminders["busy"]
        if start:
            _reminders["busy"] = True
    if start and _reminders["value"] is None and wait:
        _refresh_reminders()            # first read ever: the caller has to wait once
    elif start:
        threading.Thread(target=_refresh_reminders, daemon=True).start()
    deadline = time.time() + 40
    while wait and _reminders["value"] is None and time.time() < deadline:  # the first read is still running
        time.sleep(0.5)
    return _reminders["value"] if _reminders["value"] is not None or not wait else \
        {"available": False, "reason": "iPhone Reminders are taking too long to load. Try again in a minute."}


PERIODS = ("today", "week", "month", "year")


def _range(period: str, on: date, today: date) -> tuple[date, date, str]:
    """The period holding `on` (for a week, the 7 days ending on it), never past today, and its label."""
    year = lambda d: "" if d.year == today.year else f" {d:%Y}"  # noqa: E731
    if period == "today":
        return on, on, f"{on:%a %d %b}{year(on)}"
    if period == "week":
        start = on - timedelta(days=6)
        return start, on, f"{start:%d %b} – {on:%d %b}{year(on)}"
    if period == "month":
        start = on.replace(day=1)
        return start, min((start + timedelta(days=31)).replace(day=1) - timedelta(days=1), today), f"{start:%B}{year(start)}"
    end = min(on.replace(month=12, day=31), today)
    return on.replace(month=1, day=1), end, f"{on:%Y} so far" if end == today else f"{on:%Y}"


def _before(period: str, start: date, end: date) -> tuple[date, date]:
    """What a period is compared with: the same days of the month or year before, else the days just before."""
    if period == "month":
        first = (start - timedelta(days=1)).replace(day=1)
        return first, min(first + (end - start), start - timedelta(days=1))
    if period == "year":
        back = lambda d: d.replace(year=d.year - 1, day=28) if (d.month, d.day) == (2, 29) else d.replace(year=d.year - 1)  # noqa: E731
        return back(start), back(end)
    span = (end - start).days + 1
    return start - timedelta(days=span), start - timedelta(days=1)


def _steps(period: str, start: date, end: date, today: date) -> tuple[str, str | None]:
    """The `on` dates of the period before and after this one; no later one once this period reaches today."""
    if period in ("month", "year"):
        earlier, later = start - timedelta(days=1), end + timedelta(days=1)
    else:
        span = (end - start).days + 1
        earlier, later = end - timedelta(days=span), min(end + timedelta(days=span), today)
    return str(earlier), str(later) if end < today else None


def money_view(period: str, on: str | None = None) -> dict:
    """The Money screen for the period holding `on` (YYYY-MM-DD; default today)."""
    if period not in PERIODS:
        raise ValueError("unknown period")
    today = tasks.today()
    start, end, label = _range(period, min(date.fromisoformat(on), today) if on else today, today)
    prev_start, prev_end = _before(period, start, end)
    now = money.summary(str(start), str(end))
    before = money.summary(str(prev_start), str(prev_end))
    insights = money.insights(str(start), str(end), (prev_start, prev_end))
    earlier, later = _steps(period, start, end, today)
    with money.psycopg.connect(config.DB_DSN) as conn:
        daily = dict(conn.execute(
            f"""SELECT occurred_on, sum({money.NET_AMOUNT}) FROM transactions
               WHERE occurred_on BETWEEN %s AND %s AND ({money.SPENDING} OR {money.REFUND})
               GROUP BY occurred_on""", (start, end)).fetchall())
        first = conn.execute("SELECT min(occurred_on) FROM transactions").fetchone()[0]
    if first is None or start <= first:  # nothing older to show
        earlier = None
    # Daily totals for the small line chart (weekly totals for a whole year).
    points, cursor = [], start
    step = 7 if period == "year" else 1
    while cursor <= end:
        points.append(round(sum(float(daily.get(cursor + timedelta(days=i), 0)) for i in range(step)), 2))
        cursor += timedelta(days=step)
    return {
        "period": period, "label": label, "spent": now["spending_total"], "payments": len(now["spending"]),
        "previous": before["spending_total"], "refunds": now["refunds_total"], "received": now["received_total"],
        "own_transfers": now["own_account_transfers_total"], "card_bills": now["card_bill_payments_total"],
        "categories": insights["by_category"], "unusual": insights["unusual_rows"],
        "new_merchants": insights["new_merchants"], "points": points, "note": now["note"],
        "card_purchases": now["credit_card_purchases_total"], "small": money.small_amount(),
        "on": str(end), "today": str(today), "earlier": earlier, "later": later,
        "list": money.payments(str(start), str(end)),
    }


def cards_view() -> dict:
    return {"cards": money.cards(tasks.today()), "today": str(tasks.today())}


def more() -> dict:
    with learn._connect() as conn:
        docs = conn.execute("SELECT count(*) FROM documents").fetchone()[0]
        facts = conn.execute("SELECT count(*) FROM facts WHERE kind = 'fact'").fetchone()[0]
        episodes = conn.execute("SELECT count(*) FROM facts WHERE kind = 'episode'").fetchone()[0]
    review = 0
    if learn.REVIEW_FILE.exists():
        import json

        review = len(json.loads(learn.REVIEW_FILE.read_text()).get("suggestions", []))
    soon = renewals.upcoming(30)
    return {"documents": docs, "facts": facts, "episodes": episodes, "memory_review": review,
            "next_renewal": soon[0] if soon else None, "open_tasks": len(tasks.list_tasks("open"))}
