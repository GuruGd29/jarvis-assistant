"""Watches (docs/watches.md): Jarvis checks a redBus fare, BookMyShow bookings or something on a web page on a
schedule, and tells the user when it finds what they asked for.

The local AI only helps when a watch is created, turning a sentence into its details; every check after that is the
plain site reader in sites.py. One check runs at a time, spaced out. A watch whose day has passed goes back to Saved,
so it can be started again for another day.
"""
import asyncio
import json
import logging
import re
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from . import config, sites

log = logging.getLogger("jarvis.watches")
TZ = ZoneInfo(config.TIMEZONE)
KINDS = ("bus", "movie", "page")
EVERY = {"bus": (5, 10, 15, 30), "movie": (5, 10, 15, 30), "page": (15, 60, 360, 1440)}  # minutes the app offers
DEFAULT_EVERY = {"bus": 10, "movie": 15, "page": 60}
GAP_SECONDS = 20            # between two checks, so the sites see a person's pace
CHECK_TIMEOUT = 150         # a check taking longer is given up
ALERT_AFTER_FAILURES = 3    # checks in a row that couldn't read the site before the user is told
_LOCK = asyncio.Lock()      # one browser at a time: background checks and "Test now" take turns


def _db() -> psycopg.Connection:
    return psycopg.connect(config.DB_DSN, row_factory=dict_row, autocommit=True)


def _now() -> datetime:
    return datetime.now(TZ)


def _money(amount) -> str:
    return config.money(float(amount), decimals=False)


def _clock(iso: str) -> str:
    return datetime.fromisoformat(iso).strftime("%-I:%M %p").lower()


def _day(d: date | str) -> str:
    d = date.fromisoformat(d) if isinstance(d, str) else d
    return f"{d:%a} {d.day} {d:%b}"


# --- what the user asked for ----------------------------------------------------------------------------------------

_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")


def parse_day(text: str | None, today: date) -> date | None:
    """A day as people say it: today, tonight, tomorrow, Friday, next Sunday, 8 Nov, Nov 8, 8/11, 2026-11-08."""
    t = (text or "").strip().lower()
    if not t:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", t):
        return date.fromisoformat(t)
    if "day after tomorrow" in t:
        return today + timedelta(days=2)
    if "tomorrow" in t:
        return today + timedelta(days=1)
    if re.search(r"\b(today|tonight|this (morning|evening|afternoon))\b", t):
        return today
    month = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
    m = re.search(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?(?:\s+of)?\s+{month}\b", t) or re.search(
        rf"\b{month}\s+(\d{{1,2}})(?:st|nd|rd|th)?\b", t)
    if m:
        day_s, mon_s = (m.group(1), m.group(2)) if m.group(1).isdigit() else (m.group(2), m.group(1))
        return _next(today, _MONTHS.index(mon_s[:3]) + 1, int(day_s))
    m = re.search(r"\b(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2,4}))?\b", t)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        d, mo = (b, a) if config.DATE_ORDER.startswith("m") else (a, b)
        return _next(today, mo, d)
    for i, name in enumerate(_WEEKDAYS):
        if re.search(rf"\b{name[:3]}(?:{name[3:]})?\b", t):
            ahead = (i - today.weekday()) % 7
            return today + timedelta(days=ahead or (7 if "next" in t else 0))
    return None


def _next(today: date, month: int, day: int) -> date | None:
    """That day this year, or next year once it has passed."""
    try:
        d = date(today.year, month, day)
        return d if d >= today else date(today.year + 1, month, day)
    except ValueError:
        return None


# Times of day as people say them, for buses (a window) and movies (shows after).
_PARTS_OF_DAY = {"night": ("20:00", "02:00"), "evening": ("17:00", "23:00"), "morning": ("05:00", "12:00"),
                 "afternoon": ("12:00", "17:00")}
_STOP = r"(?=\s+(?:on|by|at|tomorrow|today|tonight|this|next|under|below|less|for|in|around|after|before|bus|buses)\b|\s*\d|[,.]|$)"


def part_of_day(text: str) -> tuple[str, str] | None:
    for word, span in _PARTS_OF_DAY.items():
        if re.search(rf"\b{word}\b|\btonight\b" if word == "night" else rf"\b{word}\b", text.lower()):
            return span
    return None


def places(text: str) -> tuple[str, str] | None:
    """ "Silk Board to Tambaram on Friday" -> ("Silk Board", "Tambaram"): the two places either side of "to"."""
    m = re.search(rf"(?:\bfrom\s+)?([A-Za-z][A-Za-z .'-]{{1,40}}?)\s+to\s+([A-Za-z][A-Za-z .'-]{{1,40}}?){_STOP}", text)
    if not m:
        return None
    src = re.sub(r"^(?:a\s+|any\s+|the\s+)?(?:bus(?:es)?|tickets?)\s+(?:from\s+)?", "", m.group(1).strip(), flags=re.I)
    return src.strip(), m.group(2).strip()


def _clock_or(value, default: str) -> str:
    value = (value or "").strip()
    return value if re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", value) else default


FILL_SCHEMA = {"type": "object", "properties": {
    "kind": {"type": "string", "enum": list(KINDS)},
    "from_city": {"type": "string"}, "boarding_point": {"type": "string"},
    "to_city": {"type": "string"}, "dropping_point": {"type": "string"},
    "day": {"type": "string"}, "leave_from": {"type": "string"}, "leave_to": {"type": "string"},
    "max_price": {"type": ["number", "null"]},
    "movie": {"type": "string"}, "city": {"type": "string"},
    "theatres": {"type": "array", "items": {"type": "string"}}, "shows_after": {"type": "string"},
    "url": {"type": "string"}}, "required": ["kind"]}
_FILL_PROMPT = """Turn the request into a watch. Answer in JSON only.
kind: "bus" for bus tickets or fares, "movie" for movie tickets or bookings opening, "page" for anything else (a link).
Bus: from_city and to_city are cities (Bangalore, Chennai, Thanjavur, Hyderabad...). A place inside a city is a
boarding_point (in from_city) or dropping_point (in to_city), and still give its city: Silk Board, Madiwala, Majestic,
Electronic City are in Bangalore; Tambaram, Koyambedu, Guindy are in Chennai. leave_from and leave_to are 24-hour
HH:MM: night 20:00 to 02:00, evening 17:00 to 23:00, morning 05:00 to 12:00, afternoon 12:00 to 17:00; not said:
00:00 to 23:59. max_price only when the user gave a price, else null.
Movie: movie is the film's name; city only if said; theatres only if named; shows_after HH:MM if a time of day
was said (evening 17:00, night 20:00).
day: the day exactly as the user said it ("Friday", "tomorrow", "8 Nov"), or "" if none.
Today is {today}.
Request: {text}"""


async def fill(text: str) -> dict:
    """The watch's details from a sentence, by the local AI; the user checks them before saving."""
    async with httpx.AsyncClient(timeout=180) as client:
        response = await client.post(f"{config.OLLAMA_URL}/api/generate", json={
            "model": config.CHAT_MODEL, "stream": False, "format": FILL_SCHEMA, "keep_alive": "2h",
            "prompt": _FILL_PROMPT.format(today=f"{_now():%A %d %B %Y}", text=text[:500]),
            "options": {"temperature": 0}})  # the model's own num_ctx, so it is not reloaded
    response.raise_for_status()
    return form_from(json.loads(response.json()["response"]), text, _now().date())


def form_from(a: dict, text: str, today: date) -> dict:
    """The model's answer as a form the app shows; the day is worked out here, not by the model."""
    link = re.search(r"https?://\S+", text)
    kind = "page" if link else a.get("kind") if a.get("kind") in KINDS else "bus"
    day = parse_day(a.get("day"), today) or parse_day(text, today)
    span = part_of_day(text)  # read here: the small model often leaves the time of day out
    if kind == "bus":
        price = a.get("max_price")
        params = {"from": (a.get("from_city") or "").strip(), "to": (a.get("to_city") or "").strip(),
                  "boarding": (a.get("boarding_point") or "").strip(), "dropping": (a.get("dropping_point") or "").strip(),
                  "leave_from": _clock_or(a.get("leave_from"), "00:00"), "leave_to": _clock_or(a.get("leave_to"), "23:59"),
                  "max_price": round(price) if isinstance(price, (int, float)) and price > 0 else None}
        for key in ("boarding", "dropping"):  # only places the user said: the model sometimes borrows the examples
            if params[key] and sites._norm(params[key]) not in sites._norm(text):
                params[key] = ""
        if span and (params["leave_from"], params["leave_to"]) == ("00:00", "23:59"):
            params["leave_from"], params["leave_to"] = span
        # "Silk Board to Tambaram": a named place that is not the city is the boarding (or dropping) point.
        named = places(text)
        if named:
            for place, city, key in ((named[0], "from", "boarding"), (named[1], "to", "dropping")):
                if not params[key] and sites._norm(place) != sites._norm(params[city] or place):
                    params[key] = place
                params[city] = params[city] or place
    elif kind == "movie":
        params = {"movie": (a.get("movie") or "").strip(), "city": (a.get("city") or last_city()).strip(),
                  "theatres": [t.strip() for t in a.get("theatres") or [] if t.strip()],
                  "after": _clock_or(a.get("shows_after"), span[0] if span else "00:00")}
    else:
        params = {"url": link.group(0) if link else (a.get("url") or "").strip()}
    return {"kind": kind, "params": params, "day": day.isoformat() if day else None, "every": DEFAULT_EVERY[kind]}


def last_city() -> str:
    """The city of the last movie watch: most people watch movies in one city."""
    with _db() as conn:
        row = conn.execute("SELECT params->>'city' AS city FROM watches WHERE kind = 'movie' ORDER BY id DESC LIMIT 1")\
            .fetchone()
    return (row or {}).get("city") or ""


def clean(kind: str, params: dict, day: str | None) -> tuple[dict, date | None]:
    """Checked details, or ValueError with what to fix."""
    if kind not in KINDS:
        raise ValueError("Pick bus, movie or web page.")
    p = {k: v for k, v in (params or {}).items() if v not in (None, "", [])}
    when = date.fromisoformat(day) if day else None
    if kind != "page":
        if not when:
            raise ValueError("Pick the day to watch.")
        if when < _now().date():
            raise ValueError("That day has passed. Pick today or a later day.")
    if kind == "bus":
        if not p.get("from") or not p.get("to"):
            raise ValueError("Fill in both cities: where from and where to.")
        p["leave_from"], p["leave_to"] = _clock_or(p.get("leave_from"), "00:00"), _clock_or(p.get("leave_to"), "23:59")
        if p.get("max_price") is not None:
            p["max_price"] = _positive(p["max_price"], "The price")
    elif kind == "movie":
        if not p.get("movie") or not p.get("city"):
            raise ValueError("Fill in the movie and the city.")
        p["after"] = _clock_or(p.get("after"), "00:00")
        p["theatres"] = [t for t in p.get("theatres") or [] if t.strip()]
    else:
        if urlparse(p.get("url", "")).scheme not in ("http", "https"):
            raise ValueError("Paste the page's link (starting with https://).")
        if not p.get("selector"):
            raise ValueError("Tap “Read page”, then pick what to watch.")
        if p.get("what") == "price":
            p["below"] = _positive(p.get("below"), "The price to watch for")
    return p, when


def _positive(value, what: str) -> int:
    try:
        number = round(float(value))
    except (TypeError, ValueError):
        number = 0
    if number <= 0:
        raise ValueError(f"{what} must be a number above zero.")
    return number


def title_for(kind: str, p: dict) -> str:
    if kind == "bus":
        return f"{p.get('boarding') or p.get('from')} → {p.get('dropping') or p.get('to')}"
    if kind == "movie":
        return f"{p.get('movie_name') or p.get('movie')} · {', '.join(p.get('theatres') or []) or p.get('city', '').title()}"
    return (p.get("name") or urlparse(p.get("url", "")).hostname or "Web page")[:60]


def until_for(kind: str, p: dict, day: date | None) -> datetime | None:
    """When watching stops: the end of the bus window, the end of the movie day; never for a web page."""
    if kind == "bus":
        return sites.window(day, p.get("leave_from"), p.get("leave_to"))[1].replace(tzinfo=TZ)
    if kind == "movie":
        return datetime.combine(day, time(23, 59)).replace(tzinfo=TZ)
    return None


# --- one check ------------------------------------------------------------------------------------------------------

async def _read(kind: str, p: dict, day: date | None) -> dict:
    if kind == "bus":
        return await sites.redbus(p, day)
    if kind == "movie":
        resolved = {}
        if not p.get("code"):
            found = await sites.bookmyshow_movie(p["movie"], p["city"])
            resolved = {k: found[k] for k in ("slug", "code")} | {"city_slug": found["city"]}
            if found.get("movie"):
                resolved["movie_name"] = found["movie"]
        q = {**p, **resolved}
        return {**await sites.bookmyshow({**q, "city": q.get("city_slug") or sites._slug(q["city"])}, day),
                "resolved": resolved}
    return await sites.page_value(p)


async def check(kind: str, p: dict, day: date | None) -> dict:
    """Check now (waiting for any check already running): {ok, value, met, summary, items, url, resolved} or
    {ok: False, error}."""
    async with _LOCK:
        try:
            raw = await asyncio.wait_for(_read(kind, p, day), CHECK_TIMEOUT)
        except asyncio.TimeoutError:
            return {"ok": False, "error": "The site took too long to answer."}
        except sites.Blocked as error:
            return {"ok": False, "blocked": True,
                    "error": f"{error}. Jarvis doesn't get around blocks; it tries again at the next check."}
        except (sites.NotFound, sites.PageChanged, ValueError) as error:
            return {"ok": False, "error": str(error)}
        except Exception as error:  # a browser or network failure: the next check tries again
            log.warning("watch check failed: %r", error)
            return {"ok": False, "error": f"Couldn't check: {str(error).splitlines()[0][:160]}"}
    return {"ok": True, **raw, **evaluate(kind, {**p, **(raw.get("resolved") or {})}, raw)}


def evaluate(kind: str, p: dict, r: dict) -> dict:
    """Is this what the user asked for, and a one-line summary of what the check saw."""
    if kind == "bus":
        cheapest, limit = r.get("value"), p.get("max_price")
        if cheapest is None:
            return {"met": False, "summary": "No buses in this window with seats"}
        top = r["items"][0]
        if limit and cheapest >= limit:
            return {"met": False, "summary": f"Cheapest {_money(cheapest)} · not under {_money(limit)} yet"}
        return {"met": True, "summary": f"{_money(cheapest)} · {top['name']}, {_clock(top['leaves'])}"}
    if kind == "movie":
        if not r.get("open"):
            return {"met": False, "summary": "Bookings not open yet"}
        if not r.get("items"):
            return {"met": False, "summary": "Open, but no shows yet at your theatres and time"}
        first = r["items"][0]
        return {"met": True, "summary": f"Open · {first['name']}: {', '.join(first['times'][:3])}"}
    if p.get("what") == "price":  # in the page's own currency, as the page writes it
        value, below, text = r.get("value"), p.get("below"), r.get("text") or ""
        if value is None:
            return {"met": False, "summary": f"Says “{text}”"}
        sign = re.match(r"[^\d]*", text).group(0).strip()
        if value >= below:
            return {"met": False, "summary": f"{text} · not under {sign}{below:,} yet"}
        return {"met": True, "summary": text}
    changed = r.get("text") != p.get("baseline")
    return {"met": changed, "summary": f"Now says “{r.get('text')}”" if changed else f"Says “{r.get('text')}”"}


def message(w: dict, r: dict) -> tuple[str, str]:
    """The notification for a find."""
    p, kind = w["params"], w["kind"]
    if kind == "bus":
        top = r["items"][0]
        title = (f"Bus under {_money(p['max_price'])}: {_money(r['value'])}" if p.get("max_price")
                 else f"Bus from {_money(r['value'])}")
        return title, f"{top['name']}, {_clock(top['leaves'])} · {w['title']}, {_day(w['watch_on'])}. Open Jarvis to book."
    if kind == "movie":
        shows = "; ".join(f"{v['name']}: {', '.join(v['times'][:4])}" for v in r["items"][:3])
        return f"{p.get('movie_name') or p['movie']} bookings are open", f"{_day(w['watch_on'])} · {shows}. Open Jarvis to book."
    if p.get("what") == "price":
        return f"Price dropped: {r['text']}", f"{w['title']} is now {r['text']} (you asked for under {p['below']:,})."
    return f"{w['title']} changed", f"It now says “{r.get('text')}”."


# --- the watches the user keeps -------------------------------------------------------------------------------------

def _plain(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _row(r: dict | None) -> dict | None:
    return {k: _plain(v) for k, v in r.items()} if r else None


def create(kind: str, params: dict, day: str | None, every: int, resolved: dict | None = None) -> dict:
    p, when = clean(kind, {**(params or {}), **(resolved or {})}, day)
    if kind == "page" and p.get("what") != "price":
        p.setdefault("baseline", p.get("sample"))
    every = every if every in EVERY[kind] else DEFAULT_EVERY[kind]
    with _db() as conn:
        row = conn.execute(
            "INSERT INTO watches (kind, title, params, every_minutes, watch_on, until_at, next_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, now()) RETURNING *",
            (kind, title_for(kind, p), Jsonb(p), every, when, until_for(kind, p, when))).fetchone()
        conn.execute("INSERT INTO watch_uses (watch_id, watch_on) VALUES (%s, %s)", (row["id"], when))
    return _row(row)


def start(watch_id: int, day: str | None, every: int | None) -> dict:
    """Start a saved (or paused) watch again, for a new day: a fresh use, nothing found yet."""
    w = get(watch_id)
    p, when = clean(w["kind"], w["params"], day)
    every = every if every in EVERY[w["kind"]] else w["every_minutes"]
    with _db() as conn:
        conn.execute("UPDATE watch_uses SET ended_at = now() WHERE watch_id = %s AND ended_at IS NULL", (watch_id,))
        conn.execute("INSERT INTO watch_uses (watch_id, watch_on) VALUES (%s, %s)", (watch_id, when))
        row = conn.execute(
            "UPDATE watches SET state = 'watching', watch_on = %s, until_at = %s, every_minutes = %s, next_at = now(), "
            "failures = 0, found_at = NULL, found = NULL, seen = true WHERE id = %s RETURNING *",
            (when, until_for(w["kind"], p, when), every, watch_id)).fetchone()
    return _row(row)


def change(watch_id: int, params: dict | None = None, every: int | None = None, paused: bool | None = None) -> dict:
    w = get(watch_id)
    p = w["params"]
    if params is not None:
        p, _ = clean(w["kind"], {**p, **params}, w.get("watch_on"))
    every = every if every in EVERY[w["kind"]] else w["every_minutes"]
    state = w["state"]
    if paused is True and state == "watching":
        state = "paused"
    elif paused is False and state == "paused":
        state = "watching"
    when = date.fromisoformat(w["watch_on"]) if w.get("watch_on") else None
    with _db() as conn:
        row = conn.execute(
            "UPDATE watches SET params = %s, title = %s, every_minutes = %s, state = %s, until_at = %s, "
            "next_at = CASE WHEN %s = 'watching' THEN now() ELSE NULL END WHERE id = %s RETURNING *",
            (Jsonb(p), title_for(w["kind"], p), every, state, until_for(w["kind"], p, when) if when else None, state,
             watch_id)).fetchone()
    return _row(row)


def delete(watch_id: int) -> None:
    with _db() as conn:
        conn.execute("DELETE FROM watches WHERE id = %s", (watch_id,))


def seen(watch_id: int) -> None:
    with _db() as conn:
        conn.execute("UPDATE watches SET seen = true WHERE id = %s", (watch_id,))


def get(watch_id: int) -> dict:
    with _db() as conn:
        row = conn.execute("SELECT * FROM watches WHERE id = %s", (watch_id,)).fetchone()
    if not row:
        raise LookupError("no such watch")
    return _row(row)


def listing() -> dict:
    """The Watches tab: what found something (not looked at yet), what is being watched, and the saved ones."""
    with _db() as conn:
        rows = conn.execute(
            "SELECT w.*, u.watch_on AS last_on, u.best AS last_best FROM watches w LEFT JOIN LATERAL ("
            "  SELECT watch_on, best FROM watch_uses WHERE watch_id = w.id AND ended_at IS NOT NULL "
            "  ORDER BY id DESC LIMIT 1) u ON true ORDER BY w.created_at DESC").fetchall()
    rows = [_row(r) for r in rows]
    found = [r for r in rows if r["found_at"] and not r["seen"]]
    return {"found": found, "watching": [r for r in rows if r not in found and r["state"] in ("watching", "paused")],
            "saved": [r for r in rows if r not in found and r["state"] == "saved"]}


def detail(watch_id: int) -> dict:
    w = get(watch_id)
    with _db() as conn:
        use = conn.execute("SELECT started_at FROM watch_uses WHERE watch_id = %s ORDER BY id DESC LIMIT 1",
                           (watch_id,)).fetchone()
        points = conn.execute(
            "SELECT checked_at, value FROM watch_checks WHERE watch_id = %s AND ok AND value IS NOT NULL "
            "AND checked_at >= %s ORDER BY checked_at", (watch_id, use["started_at"] if use else _now())).fetchall()
        uses = conn.execute(
            "SELECT watch_on, best, found_at, ended_at FROM watch_uses WHERE watch_id = %s AND ended_at IS NOT NULL "
            "ORDER BY id DESC LIMIT 8", (watch_id,)).fetchall()
        lowest = conn.execute("SELECT min(value) AS v FROM watch_checks WHERE watch_id = %s AND ok", (watch_id,))\
            .fetchone()["v"]
    return {**w, "points": [float(p["value"]) for p in points][-60:], "uses": [_row(u) for u in uses],
            "lowest": _plain(lowest), "every_choices": EVERY[w["kind"]]}


def found_unseen() -> list[dict]:
    """For the Today screen: finds the user has not looked at yet."""
    with _db() as conn:
        rows = conn.execute("SELECT id, kind, title, found, found_at, result FROM watches WHERE found_at IS NOT NULL "
                            "AND NOT seen ORDER BY found_at DESC").fetchall()
    return [{"id": r["id"], "kind": r["kind"], "title": r["title"], "summary": (r["found"] or {}).get("text"),
             "url": (r["result"] or {}).get("url")} for r in rows]


# --- the background checks ------------------------------------------------------------------------------------------

def _end_finished() -> None:
    """Watches whose day has passed go back to Saved; checks older than 30 days go."""
    with _db() as conn:
        for row in conn.execute("UPDATE watches SET state = 'saved', next_at = NULL "
                                "WHERE state IN ('watching', 'paused') AND until_at < now() RETURNING id").fetchall():
            conn.execute("UPDATE watch_uses SET ended_at = now() WHERE watch_id = %s AND ended_at IS NULL", (row["id"],))
        conn.execute("DELETE FROM watch_checks WHERE checked_at < now() - interval '30 days'")


def _next_due() -> dict | None:
    with _db() as conn:
        return _row(conn.execute("SELECT * FROM watches WHERE state = 'watching' AND next_at <= now() "
                                 "ORDER BY next_at LIMIT 1").fetchone())


def record(w: dict, r: dict) -> tuple[str, str] | None:
    """Store a background check; returns the notification to send when it found something new."""
    next_at = _now() + timedelta(minutes=w["every_minutes"])
    with _db() as conn:
        if r.get("resolved"):
            conn.execute("UPDATE watches SET params = params || %s WHERE id = %s", (Jsonb(r["resolved"]), w["id"]))
            w = {**w, "params": {**w["params"], **r["resolved"]}}
        if not r["ok"]:
            failures = w["failures"] + 1
            conn.execute("UPDATE watches SET result = %s, checked_at = now(), failures = %s, next_at = %s WHERE id = %s",
                         (Jsonb(r), failures, next_at, w["id"]))
            conn.execute("INSERT INTO watch_checks (watch_id, ok) VALUES (%s, false)", (w["id"],))
            return ("A watch needs you", f"{w['title']}: {r['error']}") if failures == ALERT_AFTER_FAILURES else None
        conn.execute("INSERT INTO watch_checks (watch_id, ok, value, met) VALUES (%s, true, %s, %s)",
                     (w["id"], r.get("value"), r["met"]))
        use = conn.execute("SELECT * FROM watch_uses WHERE watch_id = %s AND ended_at IS NULL ORDER BY id DESC LIMIT 1",
                           (w["id"],)).fetchone()
        if use and r.get("value") is not None:
            conn.execute("UPDATE watch_uses SET best = LEAST(coalesce(best, %s), %s) WHERE id = %s",
                         (r["value"], r["value"], use["id"]))
        news = _is_news(w, r, use)
        stored = {k: v for k, v in r.items() if k != "resolved"}
        conn.execute("UPDATE watches SET result = %s, checked_at = now(), failures = 0, next_at = %s WHERE id = %s",
                     (Jsonb(stored), next_at, w["id"]))
        if not news:
            return None
        conn.execute("UPDATE watches SET found_at = now(), found = %s, seen = false WHERE id = %s",
                     (Jsonb({"value": r.get("value"), "text": r["summary"]}), w["id"]))
        if w["kind"] == "page" and w["params"].get("what") != "price":
            conn.execute("UPDATE watches SET params = params || %s WHERE id = %s",
                         (Jsonb({"baseline": r.get("text")}), w["id"]))  # the next change is news again
        if use:
            conn.execute("UPDATE watch_uses SET found_at = coalesce(found_at, now()) WHERE id = %s", (use["id"],))
    return message(w, r)


def _is_news(w: dict, r: dict, use: dict | None) -> bool:
    """Tell the user once per find: again only when a price drops further (or a page changes again)."""
    if not r["met"]:
        return False
    if w["kind"] == "page" and w["params"].get("what") != "price":
        return True
    found_now = w.get("found_at") and (not use or datetime.fromisoformat(w["found_at"]) >= use["started_at"])
    if not found_now:
        return True
    before = (w.get("found") or {}).get("value")
    return w["kind"] != "movie" and before is not None and r.get("value") is not None and r["value"] < before


async def runner() -> None:
    """Check due watches one at a time, for as long as the app runs."""
    from .web import notify

    await asyncio.sleep(20)  # let the app finish starting
    while True:
        try:
            await asyncio.to_thread(_end_finished)
            w = await asyncio.to_thread(_next_due)
            if w:
                day = date.fromisoformat(w["watch_on"]) if w.get("watch_on") else None
                result = await check(w["kind"], w["params"], day)
                news = await asyncio.to_thread(record, w, result)
                if news:
                    await asyncio.to_thread(notify.notify, "watches", news[0], news[1], {"url": f"/#watches/{w['id']}"})
        except Exception:
            log.exception("watch runner")
        await asyncio.sleep(GAP_SECONDS)


async def options(url: str) -> dict:
    """What could be watched on a web page (for the app's "Read page")."""
    async with _LOCK:
        try:
            return await asyncio.wait_for(sites.page_options(url), CHECK_TIMEOUT)
        except asyncio.TimeoutError:
            raise ValueError("The page took too long to load.") from None
        except (sites.Blocked, sites.NotFound) as error:
            raise ValueError(str(error)) from None
