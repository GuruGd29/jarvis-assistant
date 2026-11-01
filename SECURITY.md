# Security

## Reporting a problem

Please report security problems **privately**, not in a public issue: on GitHub, open the repository's
**Security** tab and choose **Report a vulnerability**. Include what you found, how to reproduce it, and what an
attacker could do with it. You'll get a reply within a week. Fixes go to `main`; please don't publish details until
a fix is out.

Only the latest `main` is supported. Update with `git pull && ./install.sh`.

## How Jarvis is meant to be run

Jarvis holds very personal data (mail, money, health), and it's built for **one person on their own machine**. Its
safety depends on these assumptions; please keep them in mind when reporting or changing things:

- **Nothing is exposed to the internet.** Ollama, Postgres, Hermes and the app server listen on `127.0.0.1`. The
  phone reaches the app over WireGuard or a trusted home network ([docs/remote-access.md](docs/remote-access.md)).
- **The app has no login of its own.** Anyone who can reach the app's address can use it. A report showing a way
  to reach it from outside a correctly set-up VPN is very welcome; "the app has no password when exposed to the
  internet" is the documented design, not a vulnerability.
- **Read-only access to outside accounts.** Gmail, Drive and iPhone Reminders are read-only. A calendar event is
  added only after the user's own "yes" (checked in code, not left to the model).
- **Untrusted text.** Files and emails are treated as data: sentences that try to instruct the assistant are removed
  before the model sees them (`jarvis/safety.py`), and the weekly tests check a planted injection. Ways around this
  are in scope.
- **Secrets** are in `.env` (mode 600) and `secrets/` (mode 700): Google and iCloud sign-ins, bank settings, the
  backup password. They are never committed and never sent anywhere except to the service they belong to.
- **Backups** are encrypted by restic on the machine before upload.
- **No telemetry.** Hermes's telemetry and update checks and Ollama's cloud features are switched off in the
  installed configuration.

## Hardening a server further

On a public server, also consider: SSH reachable only through the VPN, `fail2ban`, automatic security updates
(`unattended-upgrades`), and a port scan from outside to confirm that only WireGuard answers.
