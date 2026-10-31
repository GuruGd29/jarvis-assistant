"""Text for Hermes cron jobs, sent to Telegram as-is.

  jarvis-briefing    the morning briefing, as a finished message
  jarvis-reminders   reminders that are due now; prints nothing when none are due
"""
from collections import Counter
from datetime import date, timedelta

from . import calendars, health, mail, money, tasks


def _task_line(t: dict) -> str:
    flags = " ❗" if t.get("priority") == 1 else ""
    due = f" ({date.fromisoformat(t['due_on']):%a %d %b})" if t.get("due_on") else ""
    return f"  • #{t['id']} {t['title']}{due}{flags}"


def briefing() -> None:
    """Written here rather than by the model: the Mac often wakes only briefly at 7:30, and a
    model reply that outlasts the wake-up fails, while this takes seconds."""
    today = tasks.today()
    lines = [f"☀️ Good morning, Guru! {today:%A %d %B}"]

    start, end = calendars.day_range(today)
    agenda = calendars.list_events(start, end)
    if not agenda["sources"]:
        lines.append("\n📅 No calendars connected")
    elif not agenda["events"]:
        lines.append("\n📅 No events today")
    else:
        lines.append("\n📅 Today")
        for event in agenda["events"]:
            when = "All day" if event["all_day"] else f"{event['start'][-5:]}–{(event['end'] or '')[-5:]}"
            where = f" @ {event['location']}" if event.get("location") else ""
            lines.append(f"  • {when} {event['title']}{where}")
    for source, error in agenda["errors"].items():
        lines.append(f"  ⚠️ Couldn't read your {source} calendar ({error})")
    tomorrow_start, tomorrow_end = calendars.day_range(today + timedelta(days=1))
    first_tomorrow = next((e for e in calendars.list_events(tomorrow_start, tomorrow_end)["events"]
                           if not e["all_day"]), None)
    if first_tomorrow:
        lines.append(f"  Tomorrow starts with {first_tomorrow['start'][-5:]} {first_tomorrow['title']}")

    try:
        inbox = mail.inbox_overview(days=1)
        if not inbox["unread"]:
            lines.append("\n📧 No unread email")
        else:
            lines.append(f"\n📧 {inbox['unread']} unread email{'s' if inbox['unread'] != 1 else ''} (last 24 h)")
            # Bank alerts arrive in bursts with the same subject: one line per sender and subject.
            seen = Counter((m["from"], m["subject"]) for b in ("important", "other") for m in inbox["groups"][b])
            for (sender, subject), count in list(seen.items())[:5]:
                lines.append(f"  • {sender}{f' ×{count}' if count > 1 else ''}: {subject}")
            bulk = len(inbox["groups"]["newsletters/updates"])
            if bulk:
                lines.append(f"  + {bulk} newsletters/updates")
    except Exception as error:
        lines.append(f"\n📧 Couldn't read Gmail ({type(error).__name__})")

    try:
        medicines = health.doses_today()
        if medicines:
            lines.append("\n💊 Medicines today\n" + "\n".join(f"  • {m}" for m in medicines))
        missed = health.adherence(1)["not_answered"]
        if missed:
            lines.append("  Not marked taken yesterday: " + "; ".join(missed))
    except Exception as error:
        lines.append(f"\n💊 Medicines unavailable ({type(error).__name__})")

    try:
        yesterday = money.summary(str(today - timedelta(days=1)))
        count = len(yesterday["spending"])
        lines.append(f"\n💸 Yesterday you spent ₹{yesterday['spending_total']:,.2f} ({count} payment{'s' if count != 1 else ''})")
    except Exception as error:
        lines.append(f"\n💸 Spending unavailable ({type(error).__name__})")

    overdue = tasks.list_tasks("overdue")
    due_today = [t for t in tasks.list_tasks("today") if t["due_on"] == today.isoformat()]
    upcoming = [t for t in tasks.list_tasks("upcoming") if t["due_on"] > today.isoformat()]
    if not (overdue or due_today or upcoming):
        lines.append("\n✅ No tasks due this week")
    for heading, items in (("⚠️ Overdue", overdue), ("✅ Due today", due_today), ("🗓️ This week", upcoming)):
        if items:
            lines.append(f"\n{heading}\n" + "\n".join(_task_line(t) for t in items))
    print("\n".join(lines))


def google_check() -> None:
    """Daily: warn on Telegram before the Testing-mode Google sign-in expires, or once it has."""
    from datetime import datetime, timezone

    if not calendars.GOOGLE_TOKEN.exists():
        return
    fix = "Re-connect it: run  ~/jarvis-system/.venv/bin/jarvis-auth google  on your Mac (about 30 seconds)."
    try:
        calendars._google_service().calendarList().list(maxResults=1).execute()
    except Exception as error:
        print(f"⚠️ Jarvis can't reach your Google Calendar ({type(error).__name__}). {fix}")
        return
    if calendars.GOOGLE_SIGNED_IN_AT.exists():
        signed_in = datetime.fromisoformat(calendars.GOOGLE_SIGNED_IN_AT.read_text().strip())
        days_left = calendars.GOOGLE_TESTING_DAYS - (datetime.now(timezone.utc) - signed_in).days
        if days_left <= 1:
            print(f"⏳ Jarvis's Google Calendar sign-in expires within a day. {fix}")


def reminders() -> None:
    for d in health.take_due_doses():
        dose = f" {d['dose']}" if d.get("dose") else ""
        print(f"💊 Time for {d['name']}{dose}.\n(dose #{d['id']}: reply \"taken {d['id']}\" or \"skip {d['id']}\")\n")
    for t in tasks.take_due_reminders():
        notes = f"\n{t['notes']}" if t.get("notes") else ""
        print(f"⏰ Reminder: {t['title']}{notes}\n(task #{t['id']}: reply \"done {t['id']}\" or \"snooze {t['id']} 30\")\n")
