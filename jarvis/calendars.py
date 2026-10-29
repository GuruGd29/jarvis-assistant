"""Google Calendar and iCloud Calendar behind one interface.

Credentials live in ~/jarvis-system/secrets/ and are written only by `jarvis-auth`:
  google-client.json  OAuth "Desktop app" client downloaded from Google Cloud (you place it)
  google-token.json   created by `jarvis-auth google`
  icloud.json         created by `jarvis-auth icloud` (Apple ID + app-specific password)
"""
import json
import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from . import config

TZ = ZoneInfo(config.TIMEZONE)
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",  # create events (only after the user approves)
    "https://www.googleapis.com/auth/gmail.readonly",   # read and sort mail; Jarvis cannot send, draft or delete
]
GOOGLE_CLIENT = config.SECRETS_DIR / "google-client.json"
GOOGLE_TOKEN = config.SECRETS_DIR / "google-token.json"
# While the Google app is in "Testing", its sign-in expires 7 days after it was granted.
GOOGLE_SIGNED_IN_AT = config.SECRETS_DIR / "google-signed-in-at"
GOOGLE_TESTING_DAYS = 7
ICLOUD_SECRET = config.SECRETS_DIR / "icloud.json"
ICLOUD_URL = "https://caldav.icloud.com"


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
    """The shared Google sign-in (calendar + Gmail), refreshed and saved when needed."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    creds = Credentials.from_authorized_user_file(str(GOOGLE_TOKEN), GOOGLE_SCOPES)
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
    return [c for c in calendars if not wanted or c.get_display_name() in wanted]


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


def create_event(source: str, title: str, start: datetime, end: datetime, calendar: str | None = None,
                 location: str | None = None, notes: str | None = None) -> dict:
    if source == "google":
        return _google_create(title, start, end, location, notes)
    if source == "apple":
        return _icloud_create(calendar, title, start, end, location, notes)
    raise ValueError("source must be google or apple")
