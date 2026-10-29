# Jarvis

A private, self-hosted personal assistant that runs on your own hardware: documents, calendar,
tasks and reminders, email (read-only), money, health and long-term memory, in English and Tamil.
Built on [Hermes Agent](https://github.com/NousResearch/hermes-agent) with a local
[Ollama](https://ollama.com) model (Qwen3 4B instruct). Everything is open source and free.

## How it fits together

- **Hermes Agent** runs the chat (Telegram and the OpenAI-compatible API used by Open WebUI).
- **`hermes/plugins/jarvis`**: memory provider plugin. Before each reply it looks up exact data
  (money totals, medicines, email) or searches your files, recalls remembered facts, and queues
  messages for nightly learning.
- **`jarvis/`**: Python package with the search server, MCP tools (calendar, tasks, email,
  money, health), ingestion, reminders, briefing and memory learning.
- **Postgres + pgvector** stores documents, tasks, transactions, health data and facts.
- Search is hybrid (vector + keyword) with bge-m3 embeddings and a multilingual reranker
  (bge-reranker-v2-m3); Tanglish questions are normalised before ranking.
- Voice uses faster-whisper (small) for speech-to-text and Piper for replies.
- **Open WebUI** is the web chat, served over HTTPS by Caddy (`caddy/Caddyfile.example`).

## Layout

```
jarvis/            Python package (search, MCP server, tasks, money, health, learn, …)
sql/               Database schema, applied in order by Postgres on first start
bin/               Startup script, Open WebUI title job, sync-hermes.sh
hermes/            Copies of the Jarvis parts that live in ~/.hermes (plugin, SOUL.md, cron scripts)
caddy/             HTTPS reverse proxy example for Open WebUI
docs/              Plans (docs/oracle-plan.md: moving to an Oracle Cloud free server)
docker-compose.yml Postgres + pgvector, bound to localhost
```

## Setup outline

1. `cp .env.example .env` and set `JARVIS_DB_PASSWORD`; `docker compose up -d`.
2. `python -m venv .venv && .venv/bin/pip install -e .`
3. Install Hermes Agent and Ollama; pull the chat model and `bge-m3`.
4. Copy `hermes/plugins/jarvis` to `~/.hermes/plugins/`, `hermes/SOUL.md` to `~/.hermes/`,
   and `hermes/scripts/*` to `~/.hermes/scripts/`; add the Hermes cron jobs.
5. `jarvis-auth google` (and optionally `jarvis-auth icloud`) for calendar and mail.

Secrets (`.env`, `secrets/`), personal files, the database, models and logs are never committed.
After changing anything inside `~/.hermes`, run `bin/sync-hermes.sh` before committing.
