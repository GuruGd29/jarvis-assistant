# Settings, secrets and accounts

Everything you can set up in Jarvis, in one place: where things are kept, every setting, every secret file, every
email address and account it uses, and how to change them.

## Where things live

| Where | What's in it |
|---|---|
| `~/jarvis-system/` | Jarvis: the code from GitHub, plus your own files that are never committed (below) |
| `~/jarvis-system/.env` | your settings ([below](#settings-env)); private (mode 600) |
| `~/jarvis-system/secrets/` | sign-ins, keys and bank settings ([below](#secret-files)); private (mode 700) |
| `~/jarvis-system/logs/`, `state/`, `models/` | logs, small working files, and downloaded model files |
| `~/Jarvis/` | **your files**: `documents`, `finance`, `health`, `notes`. Jarvis reads and indexes them |
| Postgres database `jarvis` | the search index, tasks, medicines, money, memory, chats in the app, watches |
| `~/.hermes/` | Hermes Agent: its settings, persona (`SOUL.md`), conversations, scheduled jobs and Telegram token |

`.env`, `secrets/`, `logs/`, `state/` and `models/` are in `.gitignore`, so `git pull` never touches them and they
can never be committed by accident. Backups ([backups.md](backups.md)) cover the database, `~/Jarvis`, `secrets/`,
`.env` and Hermes's memory and conversations.

## Changing a setting

1. Edit `~/jarvis-system/.env`. Write values without quotes; a setting that isn't there uses its default.
2. Apply it:
   - **Server:** `bin/apply-settings.sh && sudo systemctl restart jarvis-hermes jarvis-web`
   - **Mac:** `bin/apply-settings.sh && hermes gateway restart && launchctl kickstart -k gui/$(id -u)/com.jarvis.web`

`./install.sh` asks the most common questions and writes `.env` for you. Running it again keeps your answers.

## Settings (.env)

[.env.example](../.env.example) has every setting with a comment. In short:

**You and where you live**

| Setting | Example | What it does |
|---|---|---|
| `JARVIS_OWNER_NAME` | `Priya` | your first name, for greetings |
| `JARVIS_LOCALE` | `en_IN`, `en_US`, `de_DE` | how numbers, money and dates are written, and whether 05/12 is 5 December or May 12 |
| `JARVIS_CURRENCY` | `INR`, `USD`, `EUR` | the currency of money totals; default: your country's |
| `JARVIS_TIMEZONE` | `Asia/Kolkata` | when reminders and briefings arrive, and what "today" means. The scheduled jobs follow the computer's clock, so after changing it on a server also run `sudo timedatectl set-timezone ZONE` (or `./install.sh`) |
| `JARVIS_LANGUAGES` | `Tamil and English` | the languages you write in; Jarvis replies in the language of each message |

**The app, sign-in and the internet**

| Setting | Example | What it does |
|---|---|---|
| `JARVIS_HOSTS` | `10.8.0.1,yourname.dynv6.net` | the addresses the app answers to; any other address is refused. Set on servers |
| `JARVIS_LOGIN_EMAILS` | `you@gmail.com` | the Google accounts allowed to **Sign in with Google** ([sign-in.md](sign-in.md)); empty: Google sign-in is off |
| `JARVIS_CONTACT_EMAIL` | `you@example.com` | given only to the push services (Apple, Google, Mozilla) in case they need to reach you about notifications |
| `JARVIS_SIRI_WAIT` | `40` | seconds a question from Siri waits for its answer; a slower one comes as a notification ([siri.md](siri.md)) |
| `JARVIS_WEB_PORT` | `8791` | the app server's port, on `127.0.0.1` only. Mac only: on a server, Caddy and the scripts expect 8791 |

**Money, voice and files**

| Setting | Example | What it does |
|---|---|---|
| `JARVIS_MONEY_AI` | `nightly`, `always`, `off` | when the AI reads alert emails from banks without a built-in reader ([money.md](money.md)) |
| `JARVIS_APPLE_REMINDERS` | `on` | Mac only: read the Reminders app (your iPhone Reminders through iCloud) |
| `JARVIS_WHISPER_MODEL` | `models/ggml-small-q8_0.bin` | the speech-to-text model; without it there's no mic button ([voice.md](voice.md)) |
| `JARVIS_VOICE_WORDS` | `Jarvis, HDFC, Zomato` | names voice messages should spell right |
| `JARVIS_VOICE_KEEP` | `10` | keep the last N voice messages in `logs/voice/` to check accuracy; default 0 |
| `JARVIS_OCR_LANGS` | `eng+tam` | text recognition languages for photos and scans ([files.md](files.md)) |
| `JARVIS_DATA_ROOT` | `~/Jarvis` | the folder of your files |
| `JARVIS_SECRETS_DIR` | `~/jarvis-system/secrets` | where the secret files are |

**Database and models** (`install.sh` sets these; [customize.md](customize.md) explains changing them)

| Setting | Default | What it does |
|---|---|---|
| `JARVIS_DB_PASSWORD` | made up by `install.sh` | the database password |
| `JARVIS_DB_HOST`, `JARVIS_DB_PORT`, `JARVIS_DB_NAME`, `JARVIS_DB_USER` | `127.0.0.1`, `5432` (written by `install.sh`; without the setting the code uses 5433, the Docker option), `jarvis`, `jarvis` | the database connection |
| `JARVIS_CHAT_BASE` | `qwen3.5:4b-q4_K_M` | the Ollama model the chat model is built from; change it with `bin/use-model.sh` ([customize.md](customize.md)) |
| `JARVIS_CHAT_MODEL` | `qwen3.5-4b-64k` | Jarvis's version of it in Ollama, with a 64k context |
| `JARVIS_WARM_CHAT` | `on` | `off`: no warm-up chat every 20 minutes; set it when the chat model is a cloud service |
| `JARVIS_EMBED_MODEL` | `bge-m3` | the search model in Ollama |
| `JARVIS_OLLAMA_URL` | `http://127.0.0.1:11434` | where Ollama answers; another machine's address runs the models there ([customize.md](customize.md#a-model-on-another-machine-a-graphics-card)) |

**Only for the installer and the server scripts** (given on the command line, not in `.env`)

| Setting | Example | What it does |
|---|---|---|
| `JARVIS_INSTALL_YES=1` | | `./install.sh` asks nothing and takes every answer from settings like those above: `JARVIS_INSTALL_YES=1 JARVIS_LOCALE=en_GB JARVIS_TIMEZONE=Europe/London ./install.sh` |
| `JARVIS_MODEL_THREADS` | `2` | how many processor cores the chat model may use; saved in `.env`, so updates and `bin/use-model.sh` keep it |
| `JARVIS_DOMAIN` | `yourname.dynv6.net` | `deploy/server/prepare.sh`: also serve the app on this public name ([public-address.md](public-address.md)) |
| `JARVIS_HTTPS_PORT` | `8443` | `prepare.sh`: the app's port on the VPN address when another program has 443 |

## Secret files

Everything in `~/jarvis-system/secrets/` is private. Never commit it, paste it into a chat, or send it to anyone.

| File | What it is | How it's made |
|---|---|---|
| `google-client.json` | your Google Cloud "Desktop app" client, for Calendar, Gmail and Drive | you download it ([google.md](google.md)) |
| `google-token.json`, `google-signed-in-at` | your Google sign-in for those | `jarvis-auth google` |
| `google-login.json` | your Google Cloud "Web application" client, for **Sign in with Google** to the app | you download it ([sign-in.md](sign-in.md)) |
| `icloud.json` | your Apple ID and an app-specific password, for iCloud calendars | `jarvis-auth icloud` ([google.md](google.md#icloud-calendar-optional)) |
| `money.json` | your banks' alert email addresses, and your own names and account endings | you write it ([money.md](money.md)) |
| `web-password` | the app's sign-in password, as a scrypt hash (the password itself isn't kept) | `jarvis-auth password` |
| `siri-key` | a hash of the Siri key, which only lets a Shortcut ask questions ([siri.md](siri.md)) | **More → Siri & Shortcuts** in the app |
| `web-session.key` | signs the app's sign-in cookies; a new one signs every device out | made by itself; `jarvis-auth password` makes a new one |
| `vapid-private.pem` | the key for phone notifications | made by itself |
| `backup.env` | where backups go, and the storage key | you write it ([backups.md](backups.md)) |
| `restic-password` | unlocks your backups. **Keep a copy in your password manager** | `bin/backup.sh init` |
| `wireguard-jarvis.conf` | Mac only: the Mac's VPN profile from `bin/server.sh` | `bin/server.sh setup` |

The Telegram bot token, and the API key of a cloud AI service if you use one ([customize.md](customize.md#a-cloud-ai-service)),
are kept by Hermes in `~/.hermes/.env` ([telegram.md](telegram.md)).

The commands are in `~/jarvis-system/.venv/bin/`. `jarvis-auth status` shows what's connected and how the app signs in.

## Email addresses and accounts

Jarvis uses several addresses and accounts, each for one thing:

| What | Where it goes | Used for |
|---|---|---|
| **The Google account Jarvis reads** | you sign in with it in `jarvis-auth google`. Add it as a **Test user** in your Google Cloud project | Calendar, Gmail (read-only: inbox summaries and bank alerts), one Drive folder |
| **Google accounts that may sign in to the app** | `JARVIS_LOGIN_EMAILS` in `.env`, comma-separated | Sign in with Google. Anyone else is refused |
| **Your banks' alert senders** | `alert_senders` in `secrets/money.json`, copied exactly from an alert email's **From** | money: only emails from these addresses are read for spending |
| **A contact email for notifications** | `JARVIS_CONTACT_EMAIL` in `.env` | only Apple's and Google's push services see it |
| **Your Apple ID** | `jarvis-auth icloud`, with an app-specific password from appleid.apple.com (never your real Apple ID password) | iCloud calendars |
| **Your Telegram user ID** | `TELEGRAM_ALLOWED_USERS` in `~/.hermes/.env` | only you can use the bot; briefings are sent to you |

## Passwords and keys you choose

| What | How to set it | If you lose it |
|---|---|---|
| The app's password | `jarvis-auth password` | set a new one the same way |
| The backup password (`secrets/restic-password`) | `bin/backup.sh init` makes it | the backups can't be read by anyone. Keep a copy |
| The database password | `install.sh` makes it | it's in `.env`; you never need to type it |
| Your Google, Apple and Telegram sign-ins | in their own apps | sign in again with `jarvis-auth google` or `jarvis-auth icloud`; for Telegram see [telegram.md](telegram.md) |

Secrets are always typed into the terminal, never into a chat with anyone, AI included. The commands above ask for them
without showing them on screen.
