# Instructions for AI agents

This file is for AI agents that help someone install, run or change Jarvis: Claude Code (through
[CLAUDE.md](CLAUDE.md)), Codex, Gemini CLI, Cursor, or any agent that can run terminal commands. If you're a person,
start with [README.md](README.md) and [docs/setup-with-ai.md](docs/setup-with-ai.md).

Jarvis is a private personal assistant. **Hermes Agent** runs the conversations and the scheduled jobs; **Ollama**
runs the Qwen3.5 4B model on the machine itself; **Postgres with pgvector** stores the data; a **Starlette app
server** (`jarvis/web`) serves the phone app behind **Caddy**; **WireGuard** or a public name with a sign-in lets
the phone reach it. Everything runs on the user's own Mac or Linux server, and every part is free and open source.

## Ground rules

Follow these on every task:

1. **Secrets never go through the chat.** That means passwords, tokens, API keys, client secrets, private keys,
   backup keys and VPN profiles.
   - Never ask the user to paste one into the conversation.
   - Never print one (`cat` of `secrets/*`, `.env`'s database password, `~/jarvis-vpn/*.conf`, QR codes of VPN
     profiles).
   - Give the user a command to run in **their own terminal** instead: `jarvis-auth password`, `jarvis-auth google`,
     `jarvis-auth icloud`, `./install.sh` for Telegram, `read -s` for anything else. For files, use `scp`.
   - If a secret shows up in the chat anyway, tell the user to replace it.
2. **Ask before each change to a machine:** installing, editing settings, opening ports, restarting services,
   rebooting, deleting. Say what will change and how to undo it. Read-only checks need no permission.
3. **Back up a file before you edit it:** `mkdir -p ~/jarvis-backups/$(date +%Y%m%d-%H%M%S)` and copy it there.
4. **Use the scripts** (`install.sh`, `deploy/server/prepare.sh`, `bin/*.sh`, `jarvis-auth`) rather than editing by
   hand what they manage. They are safe to run again.
5. **No public address without a sign-in.** Set the password before giving the app a public name. The app refuses
   public addresses until then anyway.
6. **Open only the ports the guides name:**
   - UDP 51820 for the VPN.
   - TCP 80 and 443, only for a public name.
   - TCP 22 for SSH, closed again once the VPN works.

   Ollama, Postgres, Hermes and the app server must keep listening on `127.0.0.1` only.
7. **Nothing personal in the repository.** Never commit `.env`, `secrets/`, `logs/`, `state/`, `models/` or real
   names, emails, amounts or addresses. Tests and examples use made-up data.
8. **Jarvis never acts outside itself without a yes.** Don't send email, change calendars, or touch bank or account
   settings for the user.
9. **Some steps are slow, so don't call them failed early:**
   - `install.sh` takes 15–30 minutes.
   - The first reply after a restart takes up to 10 minutes on a 2-core server.
   - The weekly test run takes 1.5–2 hours.

   Run long commands in the background or with a long timeout.
10. **Check every step** with the commands below, and report what you actually saw.

## What only the user can do

Ask the user for these and wait. Don't try to do them yourself.

- **Accounts:** create the cloud account and the server (it needs their identity and card), the free DNS name, the
  Google Cloud project and its OAuth clients, and the Telegram bot.
- **Cloud consoles:** open firewall ports there, unless they've given you a command-line tool with access.
- **Sign-ins in a browser:** Google, Apple, Telegram.
- **Typing secrets:** see rule 1.
- **The phone:** scan the VPN QR code, trust a certificate, Add to Home Screen, turn on notifications.

## Before you start, ask

1. **Where will Jarvis run?**
   - A Linux server: Oracle's free server, another VPS, or a home PC. Recommended.
   - A Mac with Apple silicon.
   - Moving an existing Mac install to a server.
2. **Where are you running?** On the user's computer with SSH to the server (recommended), or on the server itself.
3. **How will the phone reach it?** A free public name with a sign-in (easiest: no VPN app, Google sign-in works), or
   the VPN only (most private).
4. **Which model?** The default Qwen3.5 4B (free, private, fits 12 GB), a bigger local model, or a cloud AI service
   ([docs/customize.md](docs/customize.md)).
5. **Their settings:** first name, `JARVIS_LOCALE` (e.g. `en_IN`), currency, time zone, the languages they write in,
   an optional contact email for notifications, and whether they want Telegram.
6. **What to connect now:** Google (Calendar, Gmail, Drive), iCloud calendar, bank alert emails, backups.

## Path A: a Linux server

Follow [docs/install-server.md](docs/install-server.md); the steps below are the same with checks. `SERVER` is an SSH
alias or `user@ip` for a normal user with `sudo` (not root).

| # | Who | Step | Check |
|---|---|---|---|
| 1 | user | Create the server: Ubuntu 24.04+, 12 GB memory, a public IPv4 address, their SSH key ([docs/oracle-cloud.md](docs/oracle-cloud.md) for Oracle's free one). Allow TCP 22 in the provider's firewall. | `ssh -o BatchMode=yes SERVER true` |
| 2 | agent | `git clone https://github.com/GuruGd29/jarvis-assistant.git ~/jarvis-system` | `ls ~/jarvis-system/install.sh` |
| 3 | agent | `cd ~/jarvis-system && deploy/server/prepare.sh PUBLIC_IP` (use `ssh -t` if `sudo` asks for a password) | `systemctl is-active wg-quick@wg0 caddy` |
| 4 | agent | First `ssh SERVER sudo -n true`. If that fails, `sudo` needs a password, so the user runs `ssh -t SERVER 'cd jarvis-system && ./install.sh'` themselves. Otherwise: `mkdir -p logs && JARVIS_INSTALL_YES=1 JARVIS_OWNER_NAME=… JARVIS_LOCALE=… JARVIS_CURRENCY=… JARVIS_TIMEZONE=… "JARVIS_LANGUAGES=…" JARVIS_CONTACT_EMAIL=… ./install.sh > logs/install.log 2>&1` (15–30 min, in the background) | `curl -s http://127.0.0.1:8791/api/health` shows `"ok": true` |
| 5 | agent | Check that the installer set the app's addresses (it does after `prepare.sh`). If not, add `JARVIS_HOSTS=10.8.0.1` to `.env` and `sudo systemctl restart jarvis-web` | `grep JARVIS_HOSTS .env` |
| 6 | user | In their terminal: `ssh -t SERVER jarvis-system/.venv/bin/jarvis-auth password` | `.venv/bin/jarvis-auth status` says "App sign-in: password" |
| 7a | user, then agent | **Public name:** the user creates a free name (e.g. dynv6.net) pointing at the public IP, and allows TCP 80 and 443. Then the agent runs `JARVIS_DOMAIN=NAME deploy/server/prepare.sh PUBLIC_IP` ([docs/public-address.md](docs/public-address.md)) | `dig +short NAME` shows the IP; from outside the server, `curl -sI https://NAME` answers `303`, location `/login` |
| 7b | user | **VPN:** allow UDP 51820. In their own terminal: `ssh -t SERVER 'qrencode -t ansiutf8 < jarvis-vpn/phone.conf'`, then scan it in the WireGuard app and trust Caddy's certificate ([docs/remote-access.md](docs/remote-access.md#4-trust-caddys-certificate-on-the-phone-once)) | `sudo wg show` lists a recent handshake |
| 8 | user | On the phone: open the address, sign in, Add to Home Screen, **More → Notifications** | |
| 9 | both | Connect accounts: Google ([docs/google.md](docs/google.md): the user makes the client, `scp`s the JSON, and runs the SSH tunnel and `jarvis-auth google --port 8085`), money ([docs/money.md](docs/money.md): bank sender addresses aren't secret, so you may write `secrets/money.json`), backups ([docs/backups.md](docs/backups.md): the user writes `secrets/backup.env` with the key; then you run `bin/backup.sh init && bin/backup.sh && bin/add-jobs.sh`, and the user saves `secrets/restic-password` in their password manager), Telegram ([docs/telegram.md](docs/telegram.md): to replace a token, delete the old `TELEGRAM_` lines in `~/.hermes/.env` first; then the user runs `./install.sh` and types it) | `jarvis-auth status`; `bin/backup.sh` ends without an error; `hermes cron list` shows `jarvis-backup` |
| 10 | both | Optional: close SSH to the internet ([docs/install-server.md](docs/install-server.md#7-close-ssh-to-the-internet-recommended)) | `ssh` works through `10.8.0.1` |

## Path B: a Mac

Follow [docs/install-mac.md](docs/install-mac.md) step by step: Homebrew (with Postgres), the Ollama app,
Hermes, then a login item for the app server. Reaching it from the phone on home Wi-Fi is covered in
[docs/remote-access.md](docs/remote-access.md#mac-or-pc-on-home-wi-fi).

## Path C: moving a Mac install to a server

From the Mac, in `~/jarvis-system`, follow [docs/server.md](docs/server.md):

1. `bin/server.sh key`, then the user creates the server with that key.
2. `bin/server.sh setup IP`.
3. `bin/server.sh phone`. The QR code holds a private key, so the user runs it in their own terminal.
4. `bin/server.sh vpn`.
5. `bin/server.sh move`. It asks before switching.

## Changing the model or the host

Follow [docs/customize.md](docs/customize.md).

- **Another local model:** `bin/use-model.sh MODEL`, then restart. It must support tools; check the memory with the
  table there first.
- **A model on another machine:** set `JARVIS_OLLAMA_URL` to that machine's private address. Reach it only over a VPN
  or a private network; Ollama has no password.
- **A cloud AI service:** before switching, tell the user plainly that their chats and the facts Jarvis adds go to
  that company. The user types the API key into their own terminal; then run `hermes model`, set
  `JARVIS_WARM_CHAT=off`, and restart.
- **Going back:** `bin/use-model.sh qwen3.5:4b-q4_K_M`.

## Checks

```bash
curl -s http://127.0.0.1:8791/api/health                   # database, hermes, ollama: all "ok"
~/jarvis-system/.venv/bin/jarvis-auth status                # calendars connected; how the app signs in
systemctl is-active jarvis-hermes jarvis-web ollama caddy   # server: all "active"
journalctl -u jarvis-web -u jarvis-hermes -u ollama -n 50   # server: recent errors
free -h; ollama ps                                          # memory; both models loaded after the first chat
```

## Known pitfalls

These come from real installs:

**Oracle**
- WireGuard needs **UDP** 51820 in the security list. TCP is a common mistake.
- The free allowance is 2 OCPU and 12 GB in total. A bigger server costs money.
- A server can't reach its own public IP: Oracle doesn't route it back. Test a public name from outside, or on the
  server with `curl --resolve NAME:443:PRIVATE_IP`.

**The free name**
- Some internet providers block some free name services: BSNL in India blocks `duckdns.org`. Check with `dig` on
  the user's network.
- deSEC's `dedyn.io` stopped taking new names in November 2026. `dynv6.net` works.

**Backups (Oracle Object Storage)**
- The URL needs the **namespace**, which isn't the bucket's name.
- A new Customer Secret Key takes about 2 minutes before it works.

**Ubuntu**
- On Ubuntu 26.04, `sudo -v` can ask for a password even when none is needed. Test with `sudo -n true`, and run
  interactive steps with `ssh -t`.

**Networks**
- Some home and mobile networks use `10.8.0.1` themselves. With the VPN off, that address reaches another device.

**The model**
- After a restart, start `.venv/bin/jarvis-warm-chat` so the first reply doesn't wait.
- Don't restart Ollama without a reason: it loses the cached instructions, and reading them again takes about 10
  minutes. `bin/update.sh` re-runs the installer, which restarts Ollama, when `install.sh` or `deploy/` changed.
- Ollama's OpenAI-style API ignores the Modelfile's temperature and top_p, so `deploy/hermes/config.yaml` sends them
  (`extra_body`). Keep it.
- Keep `presence_penalty 1.5` in `deploy/ollama/Modelfile`: at 0 the model can repeat itself endlessly.

## Changing the code

Read [CONTRIBUTING.md](CONTRIBUTING.md). In short:

- **Layout:** `jarvis/` is the Python package, `web/app/` the phone app, `hermes/` the plugin, persona and job scripts,
  `deploy/` the services and settings, `sql/` the database changes, `tests/` the tests.
- **Edit here, never in `~/.hermes`.** `bin/apply-settings.sh` copies Jarvis's parts into Hermes. Then restart:
  `sudo systemctl restart jarvis-hermes jarvis-web` on a server.
- **Database changes** go in a new numbered `sql/` file that only adds, so `jarvis-migrate` can run on every update.
- **No country or person in the code:** anything that depends on where someone lives goes through `jarvis/config.py`
  settings.
- **Money is computed in code or SQL,** never by the model.
- **Run the unit tests before you finish:** `.venv/bin/python -m unittest discover tests`. For changes to prompts,
  the model or Hermes, also run the weekly test (GitHub Actions → Weekly tests → Run workflow).
  See [docs/testing.md](docs/testing.md).
