"""Reading the sites watches look at (docs/watches.md), with Playwright.

redBus and BookMyShow refuse hidden (headless) browsers, so each check opens a normal Chrome window placed
off-screen, loads as few pages as it needs and closes it. On a Mac, keyboard focus goes straight back to the app the
user was in. Nothing here gets around a block: a site that refuses raises Blocked, and the watch tells the user.
"""
import asyncio
import os
import re
import subprocess
import sys
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from urllib.parse import parse_qs, urlencode, urlparse

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import async_playwright

NAV_TIMEOUT_MS = 45_000
WINDOW = ["--window-position=-3000,-3000", "--window-size=1280,900"]
_BLOCK_PAGE = re.compile(r"you have been blocked|attention required|access denied|unusual traffic|verify you are (a )?human"
                         r"|are you a robot", re.I)
_TIME = re.compile(r"\b(\d{1,2}):(\d{2})\s*([AP]M)\b", re.I)


class Blocked(RuntimeError):
    """The site refused the check (a block page, or HTTP 403/429)."""


class NotFound(RuntimeError):
    """The site has nothing for what was asked: an unknown city, boarding point or movie."""


class PageChanged(RuntimeError):
    """The part of the page a watch reads is no longer there."""


def _front_app() -> str | None:
    """The app the user is in (macOS), from Launch Services: no permission prompt needed."""
    asn = subprocess.run(["lsappinfo", "front"], capture_output=True, text=True).stdout.strip()
    info = subprocess.run(["lsappinfo", "info", "-only", "bundleid", asn], capture_output=True, text=True).stdout
    match = re.search(r'bundleID="([^"]+)"', info)
    return match and match.group(1)


@asynccontextmanager
async def browser_page():
    """One fresh browser with one tab. A second tab would take the keyboard focus again, so callers reuse this one."""
    if sys.platform != "darwin" and not os.environ.get("DISPLAY"):
        raise RuntimeError("Watches need a screen to open a browser on; on a server, start Jarvis with xvfb-run "
                           "(docs/watches.md).")
    previous = _front_app() if sys.platform == "darwin" else None
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=False, args=WINDOW)
        try:
            page = await browser.new_page(viewport={"width": 1280, "height": 900})
            if previous:
                subprocess.run(["open", "-b", previous], check=False)
            page.set_default_timeout(NAV_TIMEOUT_MS)
            yield page
        finally:
            await browser.close()


async def _open(page, url: str) -> None:
    site = urlparse(url).hostname or url
    try:
        response = await page.goto(url, wait_until="domcontentloaded")
    except PlaywrightError as error:
        if "ERR_HTTP2_PROTOCOL_ERROR" in str(error) or "ERR_CONNECTION_RESET" in str(error):
            raise Blocked(f"{site} refused the connection") from None
        raise RuntimeError(f"Couldn't open {site}: {str(error).splitlines()[0][:120]}") from None
    if response and response.status in (403, 429):
        raise Blocked(f"{site} refused the check ({response.status})")


async def _refuse_block_page(page) -> None:
    title = await page.title()
    text = await page.evaluate("document.body ? document.body.innerText.slice(0, 600) : ''")
    if _BLOCK_PAGE.search(title) or _BLOCK_PAGE.search(text):
        raise Blocked(f"{urlparse(page.url).hostname} showed a block page")


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", (text or "").lower()))


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def window(day: date, leave_from: str, leave_to: str) -> tuple[datetime, datetime]:
    """The departure window on local clock time; an end at or before the start is on the next day (8 pm to 2 am)."""
    start = datetime.combine(day, datetime.strptime(leave_from or "00:00", "%H:%M").time())
    end = datetime.combine(day, datetime.strptime(leave_to or "23:59", "%H:%M").time())
    return start, end + timedelta(days=1) if end <= start else end


# --- redBus ---------------------------------------------------------------------------------------------------------

REDBUS = "https://www.redbus.in"


async def _redbus_cities(page, src: str, dst: str) -> dict:
    """redBus's city ids: its route page sends the browser on to a search with them in the address."""
    await _open(page, f"{REDBUS}/bus-tickets/{_slug(src)}-to-{_slug(dst)}")
    try:
        await page.wait_for_function("location.search.includes('fromCityId')", timeout=20_000)
    except PlaywrightError:
        await _refuse_block_page(page)
        raise NotFound(f"redBus has no buses from {src} to {dst}") from None
    query = parse_qs(urlparse(page.url).query)
    return {"from_id": query["fromCityId"][0], "to_id": query["toCityId"][0],
            "from_name": query.get("fromCityName", [src])[0], "to_name": query.get("toCityName", [dst])[0]}


def _redbus_url(p: dict, day: date) -> str:
    when = day.strftime("%d-%b-%Y")
    query = {"fromCityName": p["from_name"], "fromCityId": p["from_id"], "srcCountry": "IND", "fromCityType": "CITY",
             "toCityName": p["to_name"], "toCityId": p["to_id"], "destCountry": "IND", "toCityType": "CITY",
             "onward": when, "doj": when}
    return f"{REDBUS}/bus-tickets/{_slug(p['from_name'])}-to-{_slug(p['to_name'])}?{urlencode(query)}"


async def _redbus_day(page, p: dict, day: date) -> tuple[list, dict]:
    """Every bus on the day and the boarding/dropping points, from the feeds the results page loads."""
    feeds = {}

    async def keep(response):
        for name in ("searchResults", "filters"):
            if f"/rpw/api/{name}" in response.url and name not in feeds:
                try:
                    feeds[name] = (response.url, response.request.post_data, await response.json())
                except PlaywrightError:
                    pass

    page.on("response", keep)
    try:
        await _open(page, _redbus_url(p, day))
        for _ in range(60):
            if len(feeds) == 2:
                break
            await asyncio.sleep(0.5)
    finally:
        page.remove_listener("response", keep)
    if "searchResults" not in feeds:
        await _refuse_block_page(page)
        raise RuntimeError("redBus didn't send its bus list")
    url, body, first = feeds["searchResults"]
    data = first.get("data") or {}
    buses = list(data.get("inventories") or [])
    total = (data.get("metaData") or {}).get("totalCount") or len(buses)
    # The page asks for 10 buses at a time as you scroll; the same request for 100 at a time gets the rest in a few.
    for _ in range(5):
        if len(buses) >= total:
            break
        more_url = re.sub(r"limit=\d+", "limit=100", re.sub(r"offset=\d+", f"offset={len(buses)}", url))
        more = await page.evaluate(
            "([u, b]) => fetch(u, {method: 'POST', credentials: 'include', headers: {'content-type': 'application/json'},"
            " body: b}).then(r => r.ok ? r.json() : null).catch(() => null)", [more_url, body or "{}"])
        batch = ((more or {}).get("data") or {}).get("inventories") or []
        if not batch:
            break
        buses += batch
    filters = ((feeds.get("filters") or ("", "", {}))[2].get("data") or {}).get("filterTypeMeta") or {}
    return buses, filters


def _stops(grid: dict, wanted: str) -> tuple[set | None, list[str]]:
    """The routes that stop at the point the user named (None: no point named), and the point names on offer."""
    names = [g.get("name", "") for g in grid.values() if g.get("name") and g.get("name") != "Others"]
    if not wanted:
        return None, names
    w = _norm(wanted)
    routes = set()
    for g in grid.values():
        n = _norm(g.get("name"))
        if n and (w in n or n in w):
            routes.update(g.get("associatedRouteIds") or [])
    return routes, names


def _fare(bus: dict) -> float | None:
    """What the user pays: the lowest discounted seat price (the list price when there is no discount)."""
    paid = [f.get("discountedPrice") for seats in (bus.get("fareDetailsBySeatType") or {}).values() for f in seats]
    paid = [x for x in paid if x]
    listed = [x for x in bus.get("fareList") or [] if x]
    return min(paid or listed) if (paid or listed) else None


async def redbus(p: dict, day: date) -> dict:
    """Buses from the boarding point to the dropping point leaving in the window, cheapest first."""
    start, end = window(day, p.get("leave_from"), p.get("leave_to"))
    resolved = {}
    found, missing = [], []
    async with browser_page() as page:
        if not p.get("from_id"):
            resolved = await _redbus_cities(page, p["from"], p["to"])
            p = {**p, **resolved}
        for d in sorted({start.date(), end.date()}):
            buses, filters = await _redbus_day(page, p, d)
            boarding, b_names = _stops(filters.get("gridBoardingPoints") or {}, p.get("boarding"))
            dropping, d_names = _stops(filters.get("gridDroppingPoints") or {}, p.get("dropping"))
            if boarding == set():
                missing.append(f"no boarding point called “{p['boarding']}” (it has {', '.join(b_names[:6])})")
            if dropping == set():
                missing.append(f"no dropping point called “{p['dropping']}” (it has {', '.join(d_names[:6])})")
            for bus in buses:
                leaves = datetime.strptime(bus["departureTime"], "%Y-%m-%d %H:%M:%S")
                fare = _fare(bus)
                if not fare or not start <= leaves <= end or not bus.get("availableSeats"):
                    continue
                if (boarding is not None and bus.get("routeId") not in boarding) or (
                        dropping is not None and bus.get("routeId") not in dropping):
                    continue
                found.append({"name": bus.get("travelsName", "Bus"), "type": bus.get("busType", ""),
                              "leaves": leaves.isoformat(timespec="minutes"), "fare": fare,
                              "seats": bus.get("availableSeats")})
    if missing and not found:
        raise NotFound(f"redBus has {'; '.join(dict.fromkeys(missing))}.")
    found.sort(key=lambda b: (b["fare"], b["leaves"]))
    return {"items": found[:12], "count": len(found), "value": found[0]["fare"] if found else None,
            "url": _redbus_url(p, start.date()), "resolved": resolved}


# --- BookMyShow -----------------------------------------------------------------------------------------------------

BMS = "https://in.bookmyshow.com"
# A movie link, with the city when BookMyShow knows the visitor's region and without it when not.
_BMS_MOVIE = re.compile(r"/movies/(?:([a-z-]+)/)?([a-z0-9-]+)/(ET\d+)", re.I)


async def bookmyshow_movie(name: str, city: str) -> dict:
    """The movie's page name and code, from a BookMyShow link or by name from the city's now-showing list or, before
    release, the upcoming list. BookMyShow allows one page per fresh browser, so each list gets its own."""
    match = _BMS_MOVIE.search(name or "")
    if match:
        return {"city": match.group(1) or _slug(city), "slug": match.group(2), "code": match.group(3)}
    want = _norm(name)
    for listing in (f"/explore/movies-{_slug(city)}", f"/explore/upcoming-movies-{_slug(city)}"):
        async with browser_page() as page:
            await _open(page, BMS + listing)
            await page.wait_for_timeout(4000)
            await _refuse_block_page(page)
            links = await page.evaluate("Array.from(document.querySelectorAll('a[href*=\"/movies/\"]'))"
                                        ".map(a => [a.innerText.split('\\n')[0], a.href])")
        for title, href in links:
            match = _BMS_MOVIE.search(href or "")
            if match and want and (_norm(title) == want or (len(want) > 3 and want in _norm(title))):
                return {"city": match.group(1) or _slug(city), "slug": match.group(2), "code": match.group(3),
                        "movie": title}
    raise NotFound(f"BookMyShow has no “{name}” in {city.title()} yet. Paste the movie's BookMyShow link instead.")


_VENUES_JS = """() => {
  const time = /\\b\\d{1,2}:\\d{2}\\s*[AP]M\\b/i, out = [], seen = new Set();
  for (const a of document.querySelectorAll('a[href*="/cinemas/"][href*="/buytickets/"]')) {
    let box = a;
    for (let i = 0; i < 8 && box && !time.test(box.innerText || ''); i++) box = box.parentElement;
    if (!box || seen.has(box)) continue;
    seen.add(box);
    out.push(box.innerText);
  }
  return out;
}"""


def _venue(block: str) -> dict:
    lines = [line.strip() for line in block.splitlines() if line.strip()]
    name = next((line for line in lines if not _TIME.search(line)), "Cinema")
    times = [f"{int(h)}:{m} {ap.upper()}" for h, m, ap in _TIME.findall(block)]
    return {"name": name, "times": list(dict.fromkeys(times))}


def _minutes(clock: str) -> int:
    h, m, ap = _TIME.search(clock).groups()
    return (int(h) % 12 + (12 if ap.upper() == "PM" else 0)) * 60 + int(m)


async def bookmyshow(p: dict, day: date) -> dict:
    """Shows on the day at the chosen theatres (any, if none chosen) after the chosen time. When bookings for the day
    are not open yet, BookMyShow sends the browser to the first open day instead."""
    want = f"{day:%Y%m%d}"
    url = f"{BMS}/movies/{p['city']}/{p['slug']}/buytickets/{p['code']}/{want}"
    async with browser_page() as page:
        await _open(page, url)
        await page.wait_for_timeout(5000)
        await _refuse_block_page(page)
        shown = re.search(r"/(\d{8})(?:[/?#]|$)", urlparse(page.url).path + "/")
        is_open = bool(shown and shown.group(1) == want)
        blocks = await page.evaluate(_VENUES_JS) if is_open else []
    after = _minutes(datetime.strptime(p.get("after") or "00:00", "%H:%M").strftime("%I:%M %p"))
    wanted = [_words(t) for t in p.get("theatres") or [] if _words(t)]  # "PVR Forum": a theatre with both words
    venues = []
    for v in map(_venue, blocks):
        if wanted and not any(w <= _words(v["name"]) for w in wanted):
            continue
        times = [t for t in v["times"] if _minutes(t) >= after]
        if times:
            venues.append({**v, "times": times})
    return {"open": is_open, "items": venues, "count": sum(len(v["times"]) for v in venues), "url": url,
            "theatres_open": len(blocks)}


# --- any web page ---------------------------------------------------------------------------------------------------

_OPTIONS_JS = """() => {
  const path = el => {
    const parts = [];
    while (el && el.nodeType === 1 && parts.length < 7) {
      if (el.id && !/\\d{4,}/.test(el.id)) { parts.unshift('#' + CSS.escape(el.id)); break; }
      let i = 1, s = el;
      while ((s = s.previousElementSibling)) if (s.tagName === el.tagName) i++;
      parts.unshift(el.tagName.toLowerCase() + ':nth-of-type(' + i + ')');
      el = el.parentElement;
    }
    return parts.join(' > ');
  };
  const price = /^(₹|rs\\.?|inr|\\$|€|£)\\s?[\\d,]+(\\.\\d+)?$/i;
  const words = /^(in stock|out of stock|sold out|currently unavailable|unavailable|available|book now|book tickets|notify me|coming soon|add to cart|buy now)$/i;
  const out = [], seen = new Set();
  for (const el of document.querySelectorAll('body *')) {
    if (el.children.length > 3) continue;
    const text = (el.innerText || '').replace(/\\s+/g, ' ').trim();
    if (!text || text.length > 40 || !(price.test(text) || words.test(text))) continue;
    const box = el.getBoundingClientRect();
    if (!box.width || !box.height) continue;
    const what = price.test(text) ? 'price' : 'text';
    if (seen.has(what + text)) continue;
    seen.add(what + text);
    out.push({what, text, selector: path(el), size: parseFloat(getComputedStyle(el).fontSize) || 0, top: box.top});
  }
  out.sort((a, b) => (b.what === 'price') - (a.what === 'price') || b.size - a.size || a.top - b.top);
  return out.slice(0, 6);
}"""


def price_of(text: str) -> float | None:
    """The first amount in the text: "₹24,990" -> 24990, "Rs. 1,299.50" -> 1299.5."""
    match = re.search(r"\d[\d,]*(?:\.\d+)?", text or "")
    return float(match.group(0).replace(",", "")) if match else None


async def page_options(url: str) -> dict:
    """What could be watched on a page: its prices, and words like "In stock" or "Sold out"."""
    async with browser_page() as page:
        await _open(page, url)
        await page.wait_for_timeout(4000)
        await _refuse_block_page(page)
        title = await page.title()
        options = await page.evaluate(_OPTIONS_JS)
    return {"title": title, "options": [{k: o[k] for k in ("what", "text", "selector")} for o in options]}


async def page_value(p: dict) -> dict:
    """What the chosen part of the page says now."""
    async with browser_page() as page:
        await _open(page, p["url"])
        await page.wait_for_timeout(4000)
        await _refuse_block_page(page)
        text = await page.evaluate("s => { const e = document.querySelector(s); return e ? e.innerText : null; }",
                                   p["selector"])
    if text is None:
        raise PageChanged("The page changed and the part this watch reads is gone. Open the watch to pick it again.")
    text = re.sub(r"\s+", " ", text).strip()[:120]
    return {"text": text, "value": price_of(text) if p.get("what") == "price" else None, "url": p["url"]}
