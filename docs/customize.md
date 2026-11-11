# Customize Jarvis

Everything in Jarvis can be changed: the AI model, where the model runs, which cloud or computer hosts it, its
personality, its schedule and its look. This page shows how, from the simplest change to the deepest.

## The AI model

Out of the box Jarvis uses **Qwen3.5 4B**. It fits a free 12 GB server, calls tools reliably, and handles Tamil and
English; the weekly tests check it. You can swap it for any of these:

| Option | Privacy | Cost | Speed |
|---|---|---|---|
| [Another local model](#another-local-model) | everything stays on your machine | free | depends on the model and the machine |
| [A model on another machine of yours](#a-model-on-another-machine-a-graphics-card) (e.g. one with a graphics card) | stays on your machines | that machine | much faster with a graphics card |
| [A cloud AI service](#a-cloud-ai-service) (OpenAI, Anthropic, Google, OpenRouter, Groq, DeepSeek…) | your chats, and the facts Jarvis adds to them, go to that company | pay per use | fast, and smarter |

### Another local model

Any model in [Ollama's library](https://ollama.com/library) that supports **tools** works. Ollama labels them
"tools". It also needs a 64k context, which Jarvis sets up for you. One command switches to it:

```bash
cd ~/jarvis-system
bin/use-model.sh qwen3.5:9b                         # or gemma3:12b, llama3.1:8b, mistral-small…
sudo systemctl restart jarvis-hermes jarvis-web     # on a Mac it prints its own restart command
```

[`bin/use-model.sh`](../bin/use-model.sh) does the rest:

- downloads the model into Ollama;
- builds Jarvis's version of it, with a 64k context and the settings in
  [deploy/ollama/Modelfile](../deploy/ollama/Modelfile);
- points Jarvis and Hermes at it;
- keeps your previous settings in `~/jarvis-backups/`.

To go back: `bin/use-model.sh qwen3.5:4b-q4_K_M`. To choose the model before the first install:
`JARVIS_CHAT_BASE=qwen3.5:9b ./install.sh`.

**Will it fit?** As a rough guide, with 4-bit models as Ollama ships them, and about 5 GB for the rest of Jarvis
(search, voice, the agent, the database):

| Model size | Download | Memory for all of Jarvis | Fits on |
|---|---|---|---|
| 4B (the default) | ~3 GB | ~10 GB | 12 GB, e.g. Oracle's free server |
| 8–9B | ~5–6 GB | ~13 GB | 16 GB |
| 12–14B | ~8–9 GB | ~16 GB | 24 GB |
| 27–32B | ~17–20 GB | ~28 GB | 32 GB or more, or a graphics card |

On a processor without a graphics card, a model twice as big answers about half as fast.

**Good to know**

- **Tuning:** the sampling settings in `deploy/ollama/Modelfile` are tuned for Qwen3.5. For another family, set the
  temperature and the other values its model card recommends there before running `use-model.sh`. Hermes also
  sends a temperature: see `extra_body` in `~/.hermes/config.yaml`.
- **Thinking models:** Jarvis switches thinking off for speed.
- **Testing:** small models differ a lot in how well they call tools. Try the checks in
  [testing.md](testing.md#3-checks-on-your-own-install), or run the full weekly test on your fork.
- **Disk space:** remove a model you no longer use with `ollama rm NAME` (`ollama list` shows them).

### A model on another machine: a graphics card

Ollama uses a graphics card by itself when the machine has one: NVIDIA or AMD on Linux, and Apple silicon on a Mac.
Replies then take seconds. To keep Jarvis on a small server but run the model on a bigger machine of yours (a
gaming PC, or a GPU server in the cloud):

1. Connect the two machines privately, for example by adding the GPU machine as a WireGuard peer
   ([remote-access.md](remote-access.md)). `deploy/server/prepare.sh` rewrites the server's WireGuard settings each
   time it runs, so add the peer again after running it.
2. Install [Ollama](https://ollama.com/download) on that machine, and let it listen on its private address only,
   e.g. `OLLAMA_HOST=10.8.0.5:11434` in its service settings. **Never use `0.0.0.0` on a machine with a public
   address, and never open port 11434 to the internet**: Ollama has no password.
3. On the Jarvis server, put the machine's private address in `.env`:
   `JARVIS_OLLAMA_URL=http://10.8.0.5:11434`
4. Set it up and restart:

   ```bash
   OLLAMA_HOST=http://10.8.0.5:11434 ollama pull bge-m3    # the search model, on that machine
   bin/use-model.sh qwen3.5:27b                             # downloads and builds there, points Hermes at it
   sudo systemctl restart jarvis-hermes jarvis-web
   ```

When that machine is off, Jarvis can't answer chats; reminders and briefings still go out. With
`JARVIS_OLLAMA_URL` pointing elsewhere, `./install.sh` and updates download no models onto the small server.

### A cloud AI service

Hermes Agent, which runs Jarvis's conversations, works with
[many AI services](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/integrations/providers.md):
OpenAI, Anthropic, Google Gemini, OpenRouter (hundreds of models with one key), Groq, DeepSeek, and any service with
an OpenAI-style API, such as vLLM, LM Studio, LiteLLM or llama.cpp's server.

**Know the trade-off first.** Your messages then go to that company, together with what Jarvis adds to answer them:
money totals, calendar events, passages from your files, and remembered facts. It costs money per message. In
return, replies are fast and smarter.

1. Put the service's API key into Hermes's settings. This command asks for it without showing it; never paste a key
   into a chat:

   ```bash
   read -rsp "API key: " key && echo "OPENROUTER_API_KEY=$key" >> ~/.hermes/.env && unset key; echo
   ```

   Use the name your service expects: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `GROQ_API_KEY`,
   `DEEPSEEK_API_KEY` or `OPENROUTER_API_KEY`.

2. Choose the service and the model:

   ```bash
   ~/.local/bin/hermes model
   ```

3. Stop the warm-up chat. It keeps a local model ready every 20 minutes; with a cloud service, it would be a paid
   request every time. Add `JARVIS_WARM_CHAT=off` to `~/jarvis-system/.env`.

4. Restart Jarvis: `sudo systemctl restart jarvis-hermes jarvis-web`.

**What stays on your machine** even then:

- search: the search model and reranker;
- voice;
- the nightly AI jobs: learning from your chats, the AI bank reader, and filling in watches. They use the local
  model through Ollama, so keep it installed.

**To go back:** `bin/use-model.sh qwen3.5:4b-q4_K_M`, remove `JARVIS_WARM_CHAT=off`, and restart.

## Where it runs

Jarvis needs a 64-bit Linux machine with Ubuntu 24.04 or newer (or a Mac) and about 12 GB of memory. Anything that
gives you that works:

| Where | Cost | Notes |
|---|---|---|
| Oracle Cloud Always Free | free | 2 ARM cores, 12 GB: [oracle-cloud.md](oracle-cloud.md) |
| Any VPS: Hetzner, DigitalOcean, Linode, Vultr, AWS (EC2, Lightsail), Google Cloud, Azure… | monthly | pick 12 GB or more; more cores answer faster: [install-server.md](install-server.md) |
| A cloud server with a graphics card | hourly, often expensive | fastest; or use one only for the model ([above](#a-model-on-another-machine-a-graphics-card)) |
| A PC or mini PC at home | electricity | `./install.sh` on Ubuntu; reach it from outside with the VPN or a public name |
| A Mac with Apple silicon | electricity | fast replies: [install-mac.md](install-mac.md) |

**Other pieces you can swap:**

- **The database:** any Postgres with the pgvector extension, e.g. a managed one. Set `JARVIS_DB_HOST`, `JARVIS_DB_PORT`,
  `JARVIS_DB_NAME`, `JARVIS_DB_USER` and `JARVIS_DB_PASSWORD`, then run `.venv/bin/jarvis-migrate`.
- **Backups:** restic works with almost any storage: Amazon S3, Backblaze B2, Cloudflare R2, Wasabi, MinIO, SFTP or a
  USB disk. Set `RESTIC_REPOSITORY` in `secrets/backup.env` ([backups.md](backups.md), and
  [restic's list](https://restic.readthedocs.io/en/stable/030_preparing_a_new_repo.html)).
- **The name:** any DNS provider, or your own domain, with an `A` record for the server
  ([public-address.md](public-address.md)).
- **The VPN:** WireGuard by default. Tailscale, Headscale or your own VPN also work: the app just needs HTTPS on an
  address the phone can reach.

## Personality, languages and schedule

| To change | Where | Then |
|---|---|---|
| How Jarvis talks and behaves | `hermes/SOUL.md` | `bin/apply-settings.sh`, restart Hermes |
| Languages, country style, currency, time zone | `.env` ([configuration.md](configuration.md)) | `bin/apply-settings.sh`, restart |
| When briefings, reminders and other jobs run | `hermes cron list`, then `hermes cron edit ID` | restart Hermes |
| What the morning brief and weekly report say | `jarvis/briefing.py` | restart |
| Money categories (food, travel, bills…) | `CATEGORIES` in `jarvis/money.py` | restart |
| A reader for your bank's emails | [money.md](money.md#add-a-built-in-reader-for-your-bank) | restart |
| Where your files are | `JARVIS_DATA_ROOT` in `.env` | restart |
| What the model may do: its tools | `jarvis/mcp_server.py`, and the toolsets in `deploy/hermes/config.yaml` | restart |
| The app's look | `web/app/` (HTML, CSS, JavaScript) | reload the app |

Every instruction and tool description goes into every message, so a longer `SOUL.md` or more tools make each
reply slower on a small machine.

## Keeping your own version

Fork the repository on GitHub and keep your changes there. To bring in new versions of Jarvis:

```bash
git remote add upstream https://github.com/GuruGd29/jarvis-assistant.git   # once
git pull upstream main && ./install.sh
```

Settings in `.env` and files in `secrets/` are never part of git, so updates keep them. With your own changes,
update this way rather than with `bin/update.sh`, which only updates an unchanged copy. If you change something
others could use, a pull request is welcome ([CONTRIBUTING.md](../CONTRIBUTING.md)).
