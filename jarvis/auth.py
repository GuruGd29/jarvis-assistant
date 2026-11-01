"""Connect Jarvis to your calendars. Run these yourself; secrets never pass through chat.

  jarvis-auth google   needs secrets/google-client.json (OAuth "Desktop app" client); opens Google's consent page
                       (on a server: --port 8085, with `ssh -L 8085:127.0.0.1:8085` from your computer; docs/google.md)
  jarvis-auth icloud   asks for your Apple ID and an app-specific password (appleid.apple.com > Sign-In and Security)
  jarvis-auth status   shows which calendars are connected
"""
import argparse
import getpass
import json
import os
import sys
from datetime import datetime, timezone

from . import calendars, config


def _write_secret(path, text: str) -> None:
    config.SECRETS_DIR.mkdir(mode=0o700, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(text)


def google(port: int = 0) -> None:
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not calendars.GOOGLE_CLIENT.exists():
        sys.exit(f"Put your OAuth client file at {calendars.GOOGLE_CLIENT} first (Google Cloud > APIs & Services > Credentials > Desktop app).")
    flow = InstalledAppFlow.from_client_secrets_file(str(calendars.GOOGLE_CLIENT), calendars.GOOGLE_SCOPES)
    # A fixed port lets a server's sign-in come back through an SSH tunnel; no browser to open there.
    creds = flow.run_local_server(port=port, prompt="consent", open_browser=port == 0)
    _write_secret(calendars.GOOGLE_TOKEN, creds.to_json())
    _write_secret(calendars.GOOGLE_SIGNED_IN_AT, datetime.now(timezone.utc).isoformat())
    names = [c.get("summary") for c in calendars._google_service().calendarList().list().execute().get("items", [])]
    print(f"Google connected. Calendars: {', '.join(names)}")


def icloud() -> None:
    import caldav

    username = input("Apple ID email: ").strip()
    password = getpass.getpass("App-specific password (not your Apple ID password): ").strip()
    client = caldav.DAVClient(url=calendars.ICLOUD_URL, username=username, password=password)
    names = [c.get_display_name() for c in client.principal().calendars()]  # fails here if the password is wrong
    print(f"iCloud calendars found: {', '.join(names)}")
    chosen = input("Calendars to use, comma-separated (Enter = all): ").strip()
    secret = {"username": username, "password": password,
              "calendars": [n.strip() for n in chosen.split(",") if n.strip()]}
    _write_secret(calendars.ICLOUD_SECRET, json.dumps(secret))
    print("iCloud connected.")


def status() -> None:
    sources = calendars.configured_sources()
    print("Connected:", ", ".join(sources) if sources else "none")
    for path in (calendars.GOOGLE_CLIENT, calendars.GOOGLE_TOKEN, calendars.ICLOUD_SECRET):
        if path.exists():
            print(f"  {path.name}: mode {oct(path.stat().st_mode & 0o777)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("target", choices=["google", "icloud", "status"])
    parser.add_argument("--port", type=int, default=0, help="google: wait for Google's reply on this port "
                        "(for a server, through an SSH tunnel) and print the sign-in link instead of opening a browser")
    args = parser.parse_args()
    if args.target == "google":
        google(args.port)
    else:
        {"icloud": icloud, "status": status}[args.target]()


if __name__ == "__main__":
    main()
