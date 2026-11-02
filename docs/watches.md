# Watches

A watch is something Jarvis checks for you on a schedule, telling you when it finds what you asked for:

| Kind | Site | Tells you when |
|---|---|---|
| 🚌 **Bus fare** | redBus | the cheapest bus from your boarding point to your dropping point, leaving in your time window, is under your price (or any bus has seats, if you give no price) |
| 🎬 **Movie bookings** | BookMyShow | bookings open for the movie on your day, at your theatres (or any theatre), for shows after your time |
| 🌐 **Any web page** | any site that allows it | a price on the page drops under your number, or some words on it change ("Out of stock" → "In stock") |

Open the **Watches** tab and tap **+**. Type or say what you want, like *"Silk Board to Tambaram on Friday night,
under ₹500"*, and tap **Fill in**: Jarvis's AI fills in the details for you to check. Or pick a type and fill them in
yourself. **Test now** does one real check, so you can see it reads the right thing, then **Save watch**.

- You're told **once** when it finds something, on your phone (Settings → Notifications → Watches) and on the
  **Today** screen, and again only if it gets better (a lower price, or the page changes again).
- A bus or movie watch stops when its day has passed and moves to **Saved**. Tap **Start** to watch the same route or
  theatres again for another day; nothing else needs filling in. A web page watch checks until you pause it.
- Checks run one at a time, at least 20 seconds apart, every 5 to 30 minutes (web pages: every 15 minutes to once a
  day). After 3 checks in a row that can't read the site, you're told so you can look.

## How a check works

The AI is only used when you create a watch. Each check after that is a short, plain script (`jarvis/sites.py`):

- **redBus:** opens the results page for your route and day, and reads the bus list and the boarding and dropping
  points from the data that page loads. Any city works: Jarvis looks up redBus's city codes from the route page.
- **BookMyShow:** opens the movie's page of theatres and show times for your day. Until bookings for that day open,
  BookMyShow shows the first open day instead, which is how Jarvis knows they are not open yet.
- **A web page:** **Read page** opens it once and lists its prices and words like "In stock"; you pick one, and each
  check reads that same spot.

redBus and BookMyShow refuse hidden (headless) browsers, so each check opens a normal Chrome window placed
off-screen for 10 to 30 seconds and closes it. On a Mac, keyboard focus goes straight back to the app you were in.

## Be fair to the sites

redBus and BookMyShow forbid automatic checks in their terms. Watches are meant for one person, checking gently:
one check at a time, no faster than every 5 minutes. **Jarvis never gets around a block.** If a site shows a block
page or a CAPTCHA, the check stops and the watch says so. BlaBlaCar already blocks automatic checks, so rides can't
be watched. Jarvis only tells you; you always book and pay yourself.

## Setup

[Playwright](https://playwright.dev) (Apache 2.0) drives the browser. It is in `requirements.lock`; its browser
(about 380 MB) is downloaded once:

```bash
.venv/bin/playwright install chromium
```

A Mac needs nothing else, but it must be on and awake for checks to run. A Linux server has no screen, so
`install.sh` also installs Xvfb (a virtual screen, free and open source) and the app service starts under
`xvfb-run` (`deploy/systemd/jarvis-web.service`).

Each check uses about 300 to 500 MB of memory while it runs and roughly 1 to 3 MB of data. The checks' history is
kept 30 days.
