# Install Jarvis on a Mac

A Mac with Apple silicon runs Jarvis much faster than a CPU server: replies take a few seconds once the model is
warm. These are the same pieces `install.sh` sets up on Linux, installed by hand. Allow about 45 minutes. You need
[Homebrew](https://brew.sh).

Requirements: Apple silicon (M1 or newer), 16 GB memory or more, 25 GB free disk.

## 1. Tools, Postgres and Ollama

```bash
brew install git python@3.12 postgresql@17 pgvector caddy
brew services start postgresql@17
```

Install the **Ollama** app from [ollama.com/download](https://ollama.com/download) and open it once.

## 2. Jarvis and its settings

```bash
git clone https://github.com/GuruGd29/jarvis-assistant.git ~/jarvis-system
cd ~/jarvis-system
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.lock && .venv/bin/pip install --no-deps -e .
cp .env.example .env && chmod 600 .env
mkdir -p secrets logs state ~/Jarvis/{documents,finance,health,notes} && chmod 700 secrets
```

Edit `.env`: set `JARVIS_DB_PASSWORD` to a long random value (`openssl rand -hex 16` makes one), keep
`JARVIS_DB_PORT=5432`, and fill in your name, `JARVIS_LOCALE`, time zone and languages. On a Mac you can also set
`JARVIS_APPLE_REMINDERS=on` to let Jarvis read your iPhone Reminders.

## 3. The database

```bash
createuser jarvis && createdb -O jarvis jarvis
psql -d jarvis -c "ALTER ROLE jarvis PASSWORD '$(grep ^JARVIS_DB_PASSWORD= .env | cut -d= -f2-)'"
psql -d jarvis -c "CREATE EXTENSION IF NOT EXISTS vector"
.venv/bin/jarvis-migrate
```

(Prefer Docker? `docker compose up -d` starts Postgres with pgvector on port 5433 instead; set `JARVIS_DB_PORT=5433`.)

## 4. The models

Ollama's settings for Jarvis are applied at login by `bin/startup.sh` (step 7). Download the models now:

```bash
ollama pull qwen3:4b-instruct-2507-q4_K_M
ollama pull bge-m3
ollama create qwen3-4b-instruct-64k -f deploy/ollama/Modelfile
```

## 5. Hermes Agent

```bash
git clone https://github.com/NousResearch/hermes-agent.git ~/.hermes/hermes-agent
git -C ~/.hermes/hermes-agent checkout "$(grep -o '[0-9a-f]\{40\}' install.sh | head -1)"   # the tested version
(cd ~/.hermes/hermes-agent && bash setup-hermes.sh)
sed "s#__VENV__#$HOME/jarvis-system/.venv#" deploy/hermes/config.yaml > ~/.hermes/config.yaml
printf 'API_SERVER_ENABLED=true\nAPI_SERVER_KEY=%s\n' "$(openssl rand -hex 24)" >> ~/.hermes/.env
chmod 600 ~/.hermes/.env
bin/apply-settings.sh
hermes gateway install --start-now --start-on-login
```

For Telegram, add `TELEGRAM_BOT_TOKEN=` and `TELEGRAM_ALLOWED_USERS=` (your user id) to `~/.hermes/.env`, then
`hermes gateway restart`.

## 6. Scheduled jobs

```bash
bin/add-jobs.sh
```

## 7. Start at login

The app server and Ollama's settings each have a login item. Install both (the commands are also at the top of
each file):

```bash
for item in com.jarvis.startup com.jarvis.web; do
  sed "s|/Users/YOU|$HOME|g" deploy/launchd/$item.plist > ~/Library/LaunchAgents/$item.plist
  launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/$item.plist
done
```

Open `http://127.0.0.1:8791` in a browser on the Mac to check it's working.

## 8. Your phone

On home Wi-Fi, with HTTPS from Caddy: see [remote-access.md](remote-access.md#mac-or-pc-on-home-wi-fi). Then
[connect Google](google.md), set up [money](money.md) and [backups](backups.md).

## Updating

```bash
cd ~/jarvis-system && git pull
.venv/bin/pip install -r requirements.lock && .venv/bin/pip install --no-deps -e .
.venv/bin/jarvis-migrate && bin/apply-settings.sh && bin/add-jobs.sh
hermes gateway restart && launchctl kickstart -k gui/$(id -u)/com.jarvis.web
```
