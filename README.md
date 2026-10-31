# Jarvis

A private, self-hosted personal assistant that runs on your own hardware: documents, calendar,
tasks and reminders, email (read-only), money, health and long-term memory, in English and Tamil.
Built on [Hermes Agent](https://github.com/NousResearch/hermes-agent) with a local
[Ollama](https://ollama.com) model (Qwen3 4B instruct). Everything is open source and free.

You talk to Jarvis from its own **Home Screen web app** (chat, Today, Money, notifications),
from Telegram, or from Open WebUI.

## How it fits together

```
 iPhone app (web/app) ──HTTPS──▶ Caddy ──▶ app server (jarvis/web) ──▶ Hermes Agent ──▶ Ollama (Qwen3 4B)
 Telegram ─────────────────────────────────────────────────────────▶ Hermes Agent      │
                                                                     │  jarvis plugin   │
                                                                     ▼  + MCP tools     ▼
                                                      jarvis package (search, money, tasks, health, memory)
                                                                     │
                                                      Postgres + pgvector · Google / iCloud · ~/Jarvis files
```

- **Hermes Agent** runs every conversation. The **Jarvis plugin** (`hermes/plugins/jarvis`) adds exact
  data before each reply (money totals, medicines, calendar, email, file passages, remembered facts);
  the **MCP tools** (`jarvis/mcp_server.py`) let the model look things up and add tasks or events.
- **The app server** (`jarvis/web`) serves the Home Screen app, streams chats through the Hermes
  Sessions API, and sends web-push notifications. Each kind of notification has its own switch;
  everything else is kept in the app's Activity list.
- **Scheduled jobs** (Hermes cron, `hermes/scripts`) send reminders, the morning brief, weekly and
  monthly reports and renewal alerts through `jarvis-notify`, and keep the index and memory fresh.
- Search is hybrid (vector + keyword) with bge-m3 embeddings and a multilingual reranker; voice uses
  faster-whisper and Piper.

## Repository layout

```
jarvis/                 The core assistant (Python package `jarvis`)
  config.py               paths, database and model settings
  search.py ingest.py     file search and indexing of ~/Jarvis
  parse.py embed.py
  mcp_server.py           tools the model can call
  calendars.py mail.py    Google / iCloud calendars, iPhone Reminders, Gmail (read-only)
  money.py health.py      bank-alert totals and categories, medicines and lab results
  tasks.py pending.py     tasks and reminders, approvals for calendar changes
  renewals.py             bills, renewals and expiry dates found in your files
  learn.py                long-term memory and the weekly memory review
  briefing.py             morning brief, weekly and monthly reports
  auth.py                 sign-in for Google and iCloud
  web/                    The app server
    server.py               routes (Starlette), streaming chat, settings, push
    hermes.py               Hermes Sessions API client
    data.py                 data for the Today, Money and More screens
    notify.py               notifications: settings, Activity, web push, `jarvis-notify`
web/app/                The app front end (HTML, CSS, JS, service worker, icons)
hermes/                 Copies of what lives in ~/.hermes: plugin, SOUL.md, cron scripts
sql/                    Database schema, applied in order (001 … 009)
tests/                  Fast checks: python -m unittest discover tests
bin/                    Scripts the running system uses: startup.sh, backup.sh,
                        sync-hermes.sh, webui_titles.py
deploy/                 Templates to install by hand
  launchd/                start-up and app-server login items (macOS)
  caddy/                  HTTPS for the app (:3444) and Open WebUI (:3443)
docs/                   oracle-plan.md (moving to a server), design/ (approved mockups)
docker-compose.yml      Postgres + pgvector, bound to localhost
pyproject.toml          package and commands (jarvis-web, jarvis-notify, jarvis-search, …)
```

Not in git: `.env`, `secrets/`, `state/`, `logs/`, `models/`, `.venv/`, `deploy/caddy/Caddyfile`.

## Setup outline

1. `cp .env.example .env` and set `JARVIS_DB_PASSWORD`; `docker compose up -d`.
2. `python -m venv .venv && .venv/bin/pip install -e .`
3. Install Hermes Agent and Ollama; pull the chat model and `bge-m3`.
4. Copy `hermes/plugins/jarvis` to `~/.hermes/plugins/`, `hermes/SOUL.md` to `~/.hermes/`,
   and `hermes/scripts/*` to `~/.hermes/scripts/`; add the Hermes cron jobs.
5. `jarvis-auth google` (and optionally `jarvis-auth icloud`) for calendar and mail.
6. Install the login items from `deploy/launchd/` and the Caddy config from `deploy/caddy/`
   (instructions are at the top of each file).

## Working on it

- Run the checks: `.venv/bin/python -m unittest discover tests`
- After changing anything inside `~/.hermes`, run `bin/sync-hermes.sh` before committing.
- Restart the app server after Python changes: `launchctl kickstart -k gui/$(id -u)/com.jarvis.web`
