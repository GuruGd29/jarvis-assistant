"""Notifications: every message goes to the app's Activity list; it pops up on the phone only when
the user switched that kind on in Settings (and not during quiet hours).

  echo "text" | jarvis-notify reminders     store (and push, if on) each paragraph as one notification
  echo "text" | jarvis-notify reports --one store the whole text as one notification
  jarvis-notify --test                      send a test notification to every registered phone

Hermes cron scripts pipe their output through this. It prints the text back unchanged while the
"Also send to Telegram" setting is on, so Hermes still delivers it there; otherwise it prints nothing.
"""
import argparse
import base64
import json
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .. import config

# Shown in Settings in this order. Only reminders start switched on: the user wants few notifications.
KINDS = {
    "reminders": ("Reminders & medicines", "Task reminders and medicine times", True),
    "renewals": ("Bills & renewals", "30 and 2 days before one-off dates, 2 days before subscriptions", False),
    "problems": ("Important problems", "Google sign-in expiring, a sync or backup failing", False),
    "reports": ("Daily, weekly & monthly reports", "Morning brief, Sunday summary, money report, memory clean-up", False),
    "replies": ("Chat replies", "When Jarvis finishes a reply while the app is closed", False),
}
DEFAULTS = {
    "push": {kind: on for kind, (_, _, on) in KINDS.items()},
    "quiet": {"on": False, "from": "23:00", "to": "07:00"},
    "telegram_until": "2026-11-07",   # keep Telegram copies for a week while the app is new
}
TZ = ZoneInfo(config.TIMEZONE)  # quiet hours and dates follow the user, not the server clock
VAPID_KEY = config.SECRETS_DIR / "vapid-private.pem"
# Push services (Apple, Google, Mozilla) want a contact in the token: JARVIS_CONTACT_EMAIL, or the project page.
VAPID_SUB = f"mailto:{config.CONTACT_EMAIL}" if config.CONTACT_EMAIL else "https://github.com/GuruGd29/jarvis-assistant"


def connect() -> psycopg.Connection:
    return psycopg.connect(config.DB_DSN, row_factory=dict_row, autocommit=True)


# --- settings -------------------------------------------------------------------------------------

def get_settings() -> dict:
    with connect() as conn:
        row = conn.execute("SELECT value FROM app_settings WHERE key = 'notifications'").fetchone()
    saved = row["value"] if row else {}
    merged = {**DEFAULTS, **saved}
    merged["push"] = {**DEFAULTS["push"], **saved.get("push", {})}
    merged["quiet"] = {**DEFAULTS["quiet"], **saved.get("quiet", {})}
    return merged


def save_settings(changes: dict) -> dict:
    current = get_settings()
    if isinstance(changes.get("push"), dict):
        current["push"].update({k: bool(v) for k, v in changes["push"].items() if k in KINDS})
    if isinstance(changes.get("quiet"), dict):
        quiet = changes["quiet"]
        current["quiet"]["on"] = bool(quiet.get("on", current["quiet"]["on"]))
        for edge in ("from", "to"):
            value = str(quiet.get(edge, current["quiet"][edge]))
            datetime.strptime(value, "%H:%M")  # raises on a bad time
            current["quiet"][edge] = value
    if "telegram" in changes:
        # Turning it back on later gives another week of copies (the default date may have passed).
        week = (datetime.now(TZ).date() + timedelta(days=7)).isoformat()
        current["telegram_until"] = max(DEFAULTS["telegram_until"], week) if changes["telegram"] else ""
    with connect() as conn:
        conn.execute("""INSERT INTO app_settings (key, value) VALUES ('notifications', %s)
                        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()""",
                     (Jsonb(current),))
    return current


def telegram_copy_on(settings: dict | None = None) -> bool:
    until = (settings or get_settings()).get("telegram_until") or ""
    return bool(until) and datetime.now(TZ).date().isoformat() <= until


def _quiet_now(settings: dict) -> bool:
    quiet = settings["quiet"]
    if not quiet["on"]:
        return False
    now = datetime.now(TZ).strftime("%H:%M")
    start, end = quiet["from"], quiet["to"]
    return start <= now < end if start < end else (now >= start or now < end)


# --- push -----------------------------------------------------------------------------------------

def _vapid():
    from py_vapid import Vapid02  # RFC 8292 "vapid t=…, k=…" headers, which Apple requires

    if not VAPID_KEY.exists():
        key = Vapid02()
        key.generate_keys()
        key.save_key(str(VAPID_KEY))
        VAPID_KEY.chmod(0o600)
    return Vapid02.from_file(str(VAPID_KEY))


def public_key() -> str:
    """The key the browser needs to subscribe (uncompressed EC point, base64url)."""
    from cryptography.hazmat.primitives import serialization

    raw = _vapid().public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def subscribe(sub: dict, user_agent: str | None) -> None:
    keys = sub.get("keys") or {}
    if not (sub.get("endpoint", "").startswith("https://") and keys.get("p256dh") and keys.get("auth")):
        raise ValueError("not a push subscription")
    with connect() as conn:
        conn.execute("""INSERT INTO push_subscriptions (endpoint, p256dh, auth, user_agent) VALUES (%s, %s, %s, %s)
                        ON CONFLICT (endpoint) DO UPDATE SET p256dh = EXCLUDED.p256dh, auth = EXCLUDED.auth""",
                     (sub["endpoint"], keys["p256dh"], keys["auth"], (user_agent or "")[:200]))


def unsubscribe(endpoint: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM push_subscriptions WHERE endpoint = %s", (endpoint,))


def push_all(payload: dict) -> int:
    """Send to every registered phone; drop subscriptions the push service says are gone. Returns sent count."""
    from pywebpush import WebPushException, webpush

    vapid = _vapid()
    sent = 0
    with connect() as conn:
        subs = conn.execute("SELECT endpoint, p256dh, auth FROM push_subscriptions").fetchall()
        for sub in subs:
            info = {"endpoint": sub["endpoint"], "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]}}
            try:
                webpush(info, json.dumps(payload), vapid_private_key=vapid, vapid_claims={"sub": VAPID_SUB},
                        ttl=6 * 3600, timeout=15)
                conn.execute("UPDATE push_subscriptions SET last_ok_at = now() WHERE endpoint = %s", (sub["endpoint"],))
                sent += 1
            except WebPushException as error:
                if error.response is not None and error.response.status_code in (404, 410):
                    conn.execute("DELETE FROM push_subscriptions WHERE endpoint = %s", (sub["endpoint"],))
                else:
                    print(f"push failed: {error}", file=sys.stderr)
    return sent


# --- notifications --------------------------------------------------------------------------------

def notify(kind: str, title: str, body: str, data: dict | None = None) -> dict:
    """Store one notification in Activity, and push it if that kind is on and it is not quiet hours."""
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind}")
    settings = get_settings()
    want_push = settings["push"].get(kind, False) and not _quiet_now(settings)
    with connect() as conn:
        # Activity keeps 90 days; older entries go as new ones arrive.
        conn.execute("DELETE FROM activity WHERE created_at < now() - interval '90 days'")
        row = conn.execute("INSERT INTO activity (kind, title, body, data) VALUES (%s, %s, %s, %s) RETURNING id",
                           (kind, title[:120], body[:2000], Jsonb(data or {}))).fetchone()
        pushed = False
        if want_push:
            pushed = push_all({"id": row["id"], "kind": kind, "title": title[:120], "body": body[:300],
                               "url": (data or {}).get("url", "/#activity")}) > 0
            conn.execute("UPDATE activity SET pushed = %s WHERE id = %s", (pushed, row["id"]))
    return {"id": row["id"], "pushed": pushed}


def activity(limit: int = 50) -> list[dict]:
    with connect() as conn:
        rows = conn.execute("""SELECT id, kind, title, body, data, pushed, created_at, read_at FROM activity
                               ORDER BY created_at DESC LIMIT %s""", (limit,)).fetchall()
    return [{**r, "created_at": r["created_at"].isoformat(), "read_at": r["read_at"] and r["read_at"].isoformat()}
            for r in rows]


def mark_read() -> None:
    with connect() as conn:
        conn.execute("UPDATE activity SET read_at = now() WHERE read_at IS NULL")


def _split(text: str, whole: bool) -> list[tuple[str, str]]:
    """(title, body) pairs: the first line is the title, the rest the body."""
    blocks = [text.strip()] if whole else [b.strip() for b in text.strip().split("\n\n")]
    out = []
    for block in filter(None, blocks):
        first, _, rest = block.partition("\n")
        out.append((first.strip(), rest.strip() or first.strip()))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("kind", nargs="?", choices=list(KINDS))
    parser.add_argument("--one", action="store_true", help="the whole input is one notification")
    parser.add_argument("--test", action="store_true")
    args = parser.parse_args()
    if args.test:
        print(f"sent to {push_all({'title': 'Jarvis', 'body': 'Notifications are working.', 'kind': 'test', 'url': '/'})} phone(s)")
        return
    if not args.kind:
        parser.error("kind is required")
    text = sys.stdin.read()
    if not text.strip():
        return
    try:
        for title, body in _split(text, args.one):
            notify(args.kind, title, body)
    except Exception as error:  # the Telegram copy below still goes out
        print(f"jarvis-notify: {type(error).__name__}: {error}", file=sys.stderr)
    if telegram_copy_on():
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
