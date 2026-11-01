"""Google Calendar and iCloud Calendar behind one interface.

Credentials live in ~/jarvis-system/secrets/ and are written only by `jarvis-auth`:
  google-client.json  OAuth "Desktop app" client downloaded from Google Cloud (you place it)
  google-token.json   created by `jarvis-auth google`
  icloud.json         created by `jarvis-auth icloud` (Apple ID + app-specific password)
"""
import json
import re
import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from . import config

TZ = ZoneInfo(config.TIMEZONE)
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",  # create events (only after the user approves)
    "https://www.googleapis.com/auth/gmail.readonly",   # read and sort mail; Jarvis cannot send, draft or delete
    "https://www.googleapis.com/auth/drive.readonly",   # copy the Drive folder "Jarvis"; cannot change Drive
]
GOOGLE_CLIENT = config.SECRETS_DIR / "google-client.json"
GOOGLE_TOKEN = config.SECRETS_DIR / "google-token.json"
# While the Google app is in "Testing", its sign-in expires 7 days after it was granted.
GOOGLE_SIGNED_IN_AT = config.SECRETS_DIR / "google-signed-in-at"
GOOGLE_TESTING_DAYS = 7
ICLOUD_SECRET = config.SECRETS_DIR / "icloud.json"
ICLOUD_URL = "https://caldav.icloud.com"
TASKS_CALENDAR = "Jarvis Tasks"


def _event(source: str, calendar: str, title: str, start, end, location: str | None) -> dict:
    all_day = not isinstance(start, datetime)
    if not all_day:
        start, end = start.astimezone(TZ), end.astimezone(TZ) if end else None
    return {
        "source": source,
        "calendar": calendar,
        "title": title or "(no title)",
        "all_day": all_day,
        "start": start.strftime("%Y-%m-%d") if all_day else start.strftime("%Y-%m-%d %H:%M"),
        "end": (end.strftime("%Y-%m-%d") if all_day else end.strftime("%Y-%m-%d %H:%M")) if end else None,
        "location": location or None,
        "_sort": datetime.combine(start, datetime.min.time(), TZ) if all_day else start,
    }


# --- Google ------------------------------------------------------------------

def google_credentials():
    """The shared Google sign-in (calendar, Gmail, Drive), refreshed and saved when needed."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    # Use the scopes the user actually granted (saved in the token), so a sign-in made before a scope
    # was added keeps working for everything else.
    creds = Credentials.from_authorized_user_file(str(GOOGLE_TOKEN))
    if not creds.valid and creds.refresh_token:
        creds.refresh(Request())
        GOOGLE_TOKEN.write_text(creds.to_json())
        GOOGLE_TOKEN.chmod(0o600)
    return creds


def _google_service():
    from googleapiclient.discovery import build

    return build("calendar", "v3", credentials=google_credentials(), cache_discovery=False)


def _google_events(start: datetime, end: datetime) -> list[dict]:
    service = _google_service()
    events = []
    for cal in service.calendarList().list().execute().get("items", []):
        if not cal.get("selected", True):
            continue
        items = service.events().list(
            calendarId=cal["id"], timeMin=start.isoformat(), timeMax=end.isoformat(),
            singleEvents=True, orderBy="startTime", maxResults=250,
        ).execute().get("items", [])
        for item in items:
            s, e = item.get("start", {}), item.get("end", {})
            if "dateTime" in s:
                begin, finish = datetime.fromisoformat(s["dateTime"]), datetime.fromisoformat(e["dateTime"])
            else:
                begin, finish = date.fromisoformat(s["date"]), date.fromisoformat(e["date"]) - timedelta(days=1)
            events.append(_event("google", cal.get("summaryOverride") or cal.get("summary", "Google"),
                                 item.get("summary"), begin, finish, item.get("location")))
    return events


def _google_create(title: str, start: datetime, end: datetime, location: str | None, notes: str | None) -> dict:
    body = {"summary": title, "start": {"dateTime": start.isoformat(), "timeZone": config.TIMEZONE},
            "end": {"dateTime": end.isoformat(), "timeZone": config.TIMEZONE}}
    if location:
        body["location"] = location
    if notes:
        body["description"] = notes
    created = _google_service().events().insert(calendarId="primary", body=body).execute()
    return {"source": "google", "id": created["id"], "link": created.get("htmlLink")}


# --- iCloud ------------------------------------------------------------------

def _icloud_calendars():
    import caldav

    secret = json.loads(ICLOUD_SECRET.read_text())
    client = caldav.DAVClient(url=ICLOUD_URL, username=secret["username"], password=secret["password"])
    wanted = set(secret.get("calendars") or [])
    calendars = client.principal().calendars()
    # "Jarvis Tasks" mirrors Jarvis's own task list (sync_tasks_to_icloud); reading it back would show tasks twice.
    return [c for c in calendars if (not wanted or c.get_display_name() in wanted)
            and c.get_display_name() != TASKS_CALENDAR]


def _icloud_events(start: datetime, end: datetime) -> list[dict]:
    events = []
    for cal in _icloud_calendars():
        name = cal.get_display_name()
        for found in cal.search(start=start, end=end, event=True, expand=True):
            for component in found.icalendar_instance.walk("VEVENT"):
                begin = component.decoded("dtstart")
                finish = component.decoded("dtend") if component.get("dtend") else None
                if isinstance(begin, date) and not isinstance(begin, datetime) and finish:
                    finish = finish - timedelta(days=1)
                events.append(_event("apple", name, str(component.get("summary", "")), begin, finish,
                                     str(component.get("location")) if component.get("location") else None))
    return events


def _icloud_create(calendar_name: str | None, title: str, start: datetime, end: datetime,
                   location: str | None, notes: str | None) -> dict:
    from icalendar import Calendar, Event

    calendars = _icloud_calendars()
    target = next((c for c in calendars if c.get_display_name() == calendar_name), None) or calendars[0]
    event = Event()
    uid = f"{uuid.uuid4()}@jarvis"
    event.add("uid", uid)
    event.add("summary", title)
    event.add("dtstart", start)
    event.add("dtend", end)
    event.add("dtstamp", datetime.now(TZ))
    if location:
        event.add("location", location)
    if notes:
        event.add("description", notes)
    ical = Calendar()
    ical.add("prodid", "-//Jarvis//EN")
    ical.add("version", "2.0")
    ical.add_component(event)
    target.save_event(ical.to_ical().decode())
    return {"source": "apple", "calendar": target.get_display_name(), "id": uid}


def sync_tasks_to_icloud(open_tasks: list[dict]) -> dict:
    """Mirror open Jarvis tasks that have a date into the iCloud calendar "Jarvis Tasks" (created if
    missing), so they show on the iPhone. One way: only events Jarvis made in that calendar are ever
    changed or removed; a task with a reminder time is a 15-minute event, otherwise all day."""
    import caldav
    from icalendar import Calendar, Event

    secret = json.loads(ICLOUD_SECRET.read_text())
    principal = caldav.DAVClient(url=ICLOUD_URL, username=secret["username"], password=secret["password"]).principal()
    target = next((c for c in principal.calendars() if c.get_display_name() == TASKS_CALENDAR), None)
    if target is None:
        target = principal.make_calendar(name=TASKS_CALENDAR, supported_calendar_component_set=["VEVENT"])

    wanted = {}
    for t in open_tasks:
        if not (t.get("due_on") or t.get("remind_at")):
            continue
        event = Event()
        event.add("uid", f"jarvis-task-{t['id']}@jarvis")
        event.add("summary", f"☑️ {t['title']}" + (" ❗" if t.get("priority") == 1 else ""))
        if t.get("remind_at"):
            begin = datetime.strptime(t["remind_at"], "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
            event.add("dtstart", begin)
            event.add("dtend", begin + timedelta(minutes=15))
        else:
            day = date.fromisoformat(t["due_on"])
            event.add("dtstart", day)
            event.add("dtend", day + timedelta(days=1))
        event.add("dtstamp", datetime.now(TZ))
        event.add("description", f"Jarvis task #{t['id']}" + (f"\n{t['notes']}" if t.get("notes") else "")
                  + f"\nReply \"done {t['id']}\" to Jarvis when finished.")
        ical = Calendar()
        ical.add("prodid", "-//Jarvis//EN")
        ical.add("version", "2.0")
        ical.add_component(event)
        wanted[str(event["uid"])] = ical

    added = updated = removed = 0
    existing = {}
    for found in target.events():
        uid = str(found.icalendar_component.get("uid", ""))
        if uid.startswith("jarvis-task-"):
            existing[uid] = found
    for uid, ical in wanted.items():
        new_event = ical.walk("VEVENT")[0]
        old = existing.get(uid)
        if old is not None:
            old_event = old.icalendar_component
            same = all(str(old_event.get(k)) == str(new_event.get(k)) for k in ("summary", "description")) \
                and old_event.get("dtstart").to_ical() == new_event.get("dtstart").to_ical()
            if same:
                continue
            old.delete()
            updated += 1
        else:
            added += 1
        target.save_event(ical.to_ical().decode())
    for uid, old in existing.items():
        if uid not in wanted:  # done, cancelled or no longer dated
            old.delete()
            removed += 1
    return {"added": added, "updated": updated, "removed": removed, "calendar": TASKS_CALENDAR}


# --- iPhone Reminders (Mac only) --------------------------------------------
# Apple keeps upgraded iCloud Reminders out of CalDAV, so they are read through the Mac's Reminders
# app. This works only on a Mac where the user allowed access; on a server it reports that instead.
_REMINDERS_JS = """
const app = Application('Reminders');
const out = [];
for (const l of app.lists()) {
  const r = l.reminders.whose({completed: false});
  const names = r.name(), dues = r.dueDate(), notes = r.body();
  for (let i = 0; i < names.length; i++)
    out.push({list: l.name(), title: names[i], due: dues[i] ? dues[i].toISOString() : null, notes: notes[i] || null});
}
JSON.stringify(out);
"""
_REMINDERS_CACHE: dict = {}
REMINDERS_CACHE_SECONDS = 300  # reading Reminders takes ~12 s, so repeat questions reuse the last read


def iphone_reminders() -> dict:
    import shutil
    import subprocess
    import time

    if not config.APPLE_REMINDERS:
        return {"available": False, "off": True, "reason": "Reading iPhone Reminders is off (JARVIS_APPLE_REMINDERS=on)."}
    if shutil.which("osascript") is None:
        return {"available": False, "reason": "iPhone Reminders can only be read on the Mac."}
    if time.time() - _REMINDERS_CACHE.get("at", 0) > REMINDERS_CACHE_SECONDS:
        done = subprocess.run(["osascript", "-l", "JavaScript", "-e", _REMINDERS_JS],
                              capture_output=True, text=True, timeout=60)
        if done.returncode != 0:
            return {"available": False, "reason": f"Reminders app refused: {done.stderr.strip()[:200]}"}
        items = []
        for r in json.loads(done.stdout):
            due = r.pop("due")
            if due:
                local = datetime.fromisoformat(due.replace("Z", "+00:00")).astimezone(TZ)
                r["due"] = f"{local:%Y-%m-%d}" if (local.hour, local.minute) == (0, 0) else f"{local:%Y-%m-%d %H:%M}"
            items.append(r)
        items.sort(key=lambda r: r.get("due") or "9999")
        _REMINDERS_CACHE.update(at=time.time(), items=items)
    return {"available": True, "open_reminders": _REMINDERS_CACHE["items"]}


# --- Public ------------------------------------------------------------------

def configured_sources() -> list[str]:
    sources = []
    if GOOGLE_TOKEN.exists():
        sources.append("google")
    if ICLOUD_SECRET.exists():
        sources.append("apple")
    return sources


def list_events(start: datetime, end: datetime) -> dict:
    """Events from every configured calendar, merged and sorted. A failing source is reported, not fatal."""
    events, errors = [], {}
    for source, fetch in (("google", _google_events), ("apple", _icloud_events)):
        if source not in configured_sources():
            continue
        try:
            events.extend(fetch(start, end))
        except Exception as error:
            errors[source] = f"{type(error).__name__}: {error}"
    events.sort(key=lambda e: e["_sort"])
    for e in events:
        del e["_sort"]
    return {"events": events, "errors": errors, "sources": configured_sources()}


def day_range(day: date, days: int = 1) -> tuple[datetime, datetime]:
    start = datetime.combine(day, datetime.min.time(), TZ)
    return start, start + timedelta(days=days)


# A calendar question in English, Tamil or Tanglish, and the days it asks about; used to fetch the
# agenda before the model replies, so it needs no tool call. Tamil vowel signs are not \w, so no \b there.
_CALENDAR_WORDS = re.compile(r"\b(calendar|schedule|agenda|meetings?|appointments?|events?|busy)\b"
                             r"|காலண்டர்|அட்டவணை|சந்திப்பு|மீட்டிங்|அப்பாயின்ட்|நிகழ்ச்சி|நிகழ்வு", re.I)
_DAY_AFTER = re.compile(r"day after tomorrow|naa?lai?\s*maru\s*naa?l|நாளை மறுநாள்", re.I)
_TOMORROW = re.compile(r"tomorrow|\bnaa?lai?(ku|kku)?\b|நாளை", re.I)
_NEXT_WEEK = re.compile(r"(next|adutha|அடுத்த)\s*(week|vaa?ram|வாரம்)", re.I)
_THIS_WEEK = re.compile(r"\bweek\b|\bvaa?ra[mt]|வாரம்|வாரத்", re.I)
_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def agenda_for_text(text: str, today: date | None = None) -> dict | None:
    """The agenda a calendar question asks about (default today), or None if it is not about the calendar."""
    if not _CALENDAR_WORDS.search(text or ""):
        return None
    today = today or datetime.now(TZ).date()
    low = text.lower()
    weekday = next((i for i, name in enumerate(_WEEKDAYS) if name in low), None)
    if _DAY_AFTER.search(low):
        first, days, when = today + timedelta(days=2), 1, "the day after tomorrow"
    elif _TOMORROW.search(low):
        first, days, when = today + timedelta(days=1), 1, "TOMORROW"
    elif _NEXT_WEEK.search(low):
        first, days, when = today + timedelta(days=7 - today.weekday()), 7, "next week"
    elif _THIS_WEEK.search(low):
        first, days, when = today, 7 - today.weekday(), "the rest of this week"
    elif weekday is not None:
        first, days, when = today + timedelta(days=(weekday - today.weekday()) % 7), 1, _WEEKDAYS[weekday].title()
    else:
        first, days, when = today, 1, "TODAY"
    last = first + timedelta(days=days - 1)
    # The small model mixes up "today" and "tomorrow" when it only sees a date, so say both.
    label = f"{when}, {first:%a %d %b}" + (f" to {last:%a %d %b}" if days > 1 else "")
    return {"period": label, **list_events(*day_range(first, days))}


def create_event(source: str, title: str, start: datetime, end: datetime, calendar: str | None = None,
                 location: str | None = None, notes: str | None = None) -> dict:
    if source == "google":
        return _google_create(title, start, end, location, notes)
    if source == "apple":
        return _icloud_create(calendar, title, start, end, location, notes)
    raise ValueError("source must be google or apple")
