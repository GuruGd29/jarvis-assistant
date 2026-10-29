"""Text for Hermes cron jobs.

  jarvis-briefing    today's facts for the morning briefing (Jarvis turns them into a message)
  jarvis-reminders   reminders that are due now, sent as-is; prints nothing when none are due
"""
from datetime import timedelta

from . import calendars, health, mail, money, tasks


def _task_line(t: dict) -> str:
    flags = " [high]" if t.get("priority") == 1 else ""
    due = f" (due {t['due_on']})" if t.get("due_on") else ""
    return f"- #{t['id']} {t['title']}{due}{flags}"


def briefing() -> None:
    today = tasks.today()
    print(f"MORNING BRIEFING FACTS for {today:%A %d %B %Y}. Use only these facts.")

    start, end = calendars.day_range(today)
    agenda = calendars.list_events(start, end)
    print("\nToday's events:")
    if not agenda["sources"]:
        print("- (no calendars connected)")
    for event in agenda["events"]:
        when = "all day" if event["all_day"] else f"{event['start'][-5:]}-{(event['end'] or '')[-5:]}"
        where = f" @ {event['location']}" if event.get("location") else ""
        print(f"- {when} {event['title']}{where} [{event['source']}: {event['calendar']}]")
    if agenda["sources"] and not agenda["events"]:
        print("- none")
    for source, error in agenda["errors"].items():
        print(f"- WARNING: could not read {source} calendar ({error})")

    tomorrow_start, tomorrow_end = calendars.day_range(today + timedelta(days=1))
    first_tomorrow = next((e for e in calendars.list_events(tomorrow_start, tomorrow_end)["events"]
                           if not e["all_day"]), None)
    if first_tomorrow:
        print(f"\nFirst event tomorrow: {first_tomorrow['start'][-5:]} {first_tomorrow['title']}")

    print("\nEmail (unread, last 24 hours):")
    try:
        inbox = mail.inbox_overview(days=1)
        if not inbox["unread"]:
            print("- none")
        for bucket in ("important", "other"):
            for m in inbox["groups"][bucket][:5]:
                print(f"- [{bucket}] {m['from']}: {m['subject']}")
        bulk = len(inbox["groups"]["newsletters/updates"])
        if bulk:
            print(f"- plus {bulk} newsletters/updates")
    except Exception as error:
        print(f"- WARNING: could not read Gmail ({type(error).__name__})")

    try:
        medicines = health.doses_today()
        if medicines:
            print("\nMedicines today:\n" + "\n".join(f"- {m}" for m in medicines))
        missed = health.adherence(1)["not_answered"]
        if missed:
            print("Not marked taken in the last 24 hours: " + "; ".join(missed))
    except Exception as error:
        print(f"\nMedicines: unavailable ({type(error).__name__})")

    try:
        yesterday = money.summary(str(today - timedelta(days=1)))
        print(f"\nYesterday's spending: ₹{yesterday['spending_total']:,.2f} ({len(yesterday['spending'])} payments)")
    except Exception as error:
        print(f"\nYesterday's spending: unavailable ({type(error).__name__})")

    overdue = tasks.list_tasks("overdue")
    due_today = [t for t in tasks.list_tasks("today") if t["due_on"] == today.isoformat()]
    upcoming = [t for t in tasks.list_tasks("upcoming") if t["due_on"] > today.isoformat()]
    for heading, items in (("Overdue tasks", overdue), ("Due today", due_today), ("Due in the next 7 days", upcoming)):
        print(f"\n{heading}:")
        print("\n".join(_task_line(t) for t in items) if items else "- none")


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
