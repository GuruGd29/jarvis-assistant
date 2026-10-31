"""Text for Hermes cron jobs, sent to Telegram as-is.

  jarvis-briefing    the morning briefing, as a finished message
  jarvis-weekly      the Sunday evening summary of the week, as a finished message
  jarvis-monthly     the money report for last month, on the 1st
  jarvis-task-sync   copies dated Jarvis tasks into the iCloud calendar "Jarvis Tasks"; prints only on failure
  jarvis-reminders   reminders that are due now; prints nothing when none are due
"""
import re
from collections import Counter
from datetime import date, datetime, timedelta

from . import calendars, health, mail, money, renewals, tasks


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


def weekly() -> None:
    """Sunday evening: the past seven days and the week ahead, from the same sources as the briefing."""
    today = tasks.today()
    week_start = today - timedelta(days=6)
    lines = [f"📊 Your week, Guru: {week_start:%d %b} – {today:%d %b}"]

    try:
        week = money.summary(str(week_start), str(today))
        before = money.summary(str(week_start - timedelta(days=7)), str(week_start - timedelta(days=1)))
        spent, previous = week["spending_total"], before["spending_total"]
        change = _change(spent, previous, " vs the week before")
        lines.append(f"\n💸 Spent ₹{spent:,.2f} in {len(week['spending'])} payments{change}")
        lines += _insight_lines(money.insights(str(week_start), str(today)), top=4)
    except Exception as error:
        lines.append(f"\n💸 Spending unavailable ({type(error).__name__})")

    done = tasks.list_tasks("done")
    lines.append(f"\n✅ Done this week: {len(done)} task{'s' if len(done) != 1 else ''}")
    lines += [f"  • {t['title']}" for t in done[:5]]
    overdue = tasks.list_tasks("overdue")
    if overdue:
        lines.append("\n⚠️ Still overdue\n" + "\n".join(_task_line(t) for t in overdue))

    try:
        if health.list_medications():
            a = health.adherence(7)
            missed = f", {len(a['not_answered'])} not answered" if a["not_answered"] else ""
            lines.append(f"\n💊 Medicines: {a['taken']} taken, {a['skipped']} skipped{missed}")
    except Exception as error:
        lines.append(f"\n💊 Medicines unavailable ({type(error).__name__})")

    agenda = calendars.list_events(*calendars.day_range(today + timedelta(days=1), 7))
    lines.append("\n📅 Coming up")
    for event in agenda["events"]:
        day = date.fromisoformat(event["start"][:10])
        when = f"{day:%a %d %b}" + ("" if event["all_day"] else f" {event['start'][-5:]}")
        lines.append(f"  • {when} {event['title']}")
    if not agenda["events"]:
        lines.append("  • nothing on the calendar")
    upcoming = tasks.list_tasks("upcoming")
    if upcoming:
        lines.append("\n🗓️ Due next week\n" + "\n".join(_task_line(t) for t in upcoming))
    try:
        soon = renewals.upcoming(14, today)
        if soon:
            lines.append("\n🔔 Renewals in the next 2 weeks")
            lines += [f"  • {date.fromisoformat(r['date']):%a %d %b} {r['item']} {r['what']}"
                      + (f" ({r['amount']})" if r["amount"] else "") for r in soon]
    except Exception as error:
        lines.append(f"\n🔔 Renewals unavailable ({type(error).__name__})")
    print("\n".join(lines))


def _change(now: float, before: float, versus: str = "") -> str:
    """" (↑ 25%)", or " (×8)" for big jumps; nothing when the earlier amount is too small to compare."""
    if before < 1000:
        return ""
    if now >= 3 * before:
        return f" (×{now / before:.0f}{versus})"
    pct = (now - before) / before * 100
    return f" ({'↑' if pct >= 0 else '↓'} {abs(pct):.0f}%{versus})"


def _insight_lines(i: dict, top: int) -> list[str]:
    """Category totals with the change from the period before, then unusual and new payments."""
    lines = []
    for c in i["by_category"][:top]:
        lines.append(f"  • {c['category']}: ₹{c['total']:,.0f}{_change(c['total'], c['previous'])}")
    if i["unusual_payments"]:
        lines.append("  Unusually large: " + "; ".join(
            re.sub(r"^\d{4}-\d{2}-\d{2} ", "", u).split(" (")[0] for u in i["unusual_payments"][:3]))
    return lines


def monthly() -> None:
    """On the 1st: last month by category against the month before, unusual payments and new merchants."""
    first_of_this = tasks.today().replace(day=1)
    last_month_end = first_of_this - timedelta(days=1)
    start = last_month_end.replace(day=1)
    i = money.insights(str(start), str(last_month_end))
    # The headline uses the exact spending total (refunds subtracted), the same figure Jarvis quotes.
    total = money.summary(str(start), str(last_month_end))["spending_total"]
    before_start = (start - timedelta(days=1)).replace(day=1)
    previous = money.summary(str(before_start), str(start - timedelta(days=1)))["spending_total"]
    change = _change(total, previous, f" vs {before_start:%B}")
    lines = [f"📈 {start:%B} money report, Guru", f"\n💸 Spent ₹{total:,.2f}{change}", "\nBy category"]
    lines += _insight_lines(i, top=8)
    if i["new_merchants"]:
        lines.append(f"\n🆕 New this month: {', '.join(i['new_merchants'][:8])}")
    lines.append("\n(HDFC, ICICI and IDFC alert emails only; categories are guessed from merchant names.)")
    print("\n".join(lines))


def task_sync() -> None:
    if "apple" not in calendars.configured_sources():
        return
    try:
        calendars.sync_tasks_to_icloud(tasks.list_tasks("open"))
    except Exception as error:
        # Every 15 minutes: say it once an hour at most, not on every failed run.
        if datetime.now().minute < 15:
            print(f"⚠️ Jarvis couldn't copy your tasks to the iPhone calendar ({type(error).__name__}).")


def google_check() -> None:
    """Daily: say so when Jarvis can no longer reach Google (a revoked or broken sign-in)."""
    if not calendars.GOOGLE_TOKEN.exists():
        return
    fix = "Re-connect it: run  ~/jarvis-system/.venv/bin/jarvis-auth google  on your Mac (about 30 seconds)."
    try:
        calendars._google_service().calendarList().list(maxResults=1).execute()
    except Exception as error:
        print(f"⚠️ Jarvis can't reach your Google Calendar ({type(error).__name__}). {fix}")
        return
    # The Google app is published ("In production"), so sign-ins no longer expire after GOOGLE_TESTING_DAYS;
    # the check above still reports a sign-in that stops working.


def reminders() -> None:
    for d in health.take_due_doses():
        dose = f" {d['dose']}" if d.get("dose") else ""
        print(f"💊 Time for {d['name']}{dose}.\n(dose #{d['id']}: reply \"taken {d['id']}\" or \"skip {d['id']}\")\n")
    for t in tasks.take_due_reminders():
        notes = f"\n{t['notes']}" if t.get("notes") else ""
        print(f"⏰ Reminder: {t['title']}{notes}\n(task #{t['id']}: reply \"done {t['id']}\" or \"snooze {t['id']} 30\")\n")
