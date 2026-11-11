# Set up Jarvis with an AI agent

You don't have to type every command yourself. An AI coding agent can read Jarvis's guides, run the commands for
you over SSH, check each step, and tell you when it needs you. It works with Claude Code, Codex, Gemini CLI, Cursor
and others.

Jarvis comes with instructions written for these agents: [AGENTS.md](../AGENTS.md), and [CLAUDE.md](../CLAUDE.md),
which Claude Code loads by itself. They hold the steps, the checks, the known problems and the safety rules. So you
only need to say what you want in plain words.

This is optional: every step is also in the normal guides ([install-server.md](install-server.md),
[install-mac.md](install-mac.md)). Jarvis stays free either way. Some agents are paid; others have a free tier.

## 1. Pick an agent

Any agent that can run terminal commands will do, for example:

- **[Claude Code](https://claude.com/claude-code):** in a terminal, or in the Claude desktop app's **Code** tab.
- **[Codex CLI](https://github.com/openai/codex)**
- **[Gemini CLI](https://github.com/google-gemini/gemini-cli)**
- **[Cursor](https://cursor.com)**

## 2. Get Jarvis on your computer and start the agent there

Run the agent on **your own computer**. It reaches the server with SSH, and your passwords stay with you.

```bash
git clone https://github.com/GuruGd29/jarvis-assistant.git ~/jarvis-system
cd ~/jarvis-system
claude        # or codex, gemini, or open the folder in Cursor
```

Running the agent on the server itself also works: clone there the same way and start it in `~/jarvis-system`.

## 3. Tell it what you want

Copy one of these and fill in the parts in CAPITALS. Every prompt starts with "Read AGENTS.md", so every agent finds
the instructions.

**I don't have a server yet**
> Read AGENTS.md. I want to run Jarvis on Oracle Cloud's free server, but I don't have one yet. Walk me through
> creating it, then install Jarvis on it. I want to open it from my phone with a free public name and a password.

**Install on my server**
> Read AGENTS.md and install Jarvis on my server. Its IP is SERVER_IP; I log in as ubuntu with the key
> ~/.ssh/KEY_FILE. I want to open it [from anywhere with a free public name | only through a VPN]. Ask me for my
> settings first, tell me each step before you do it, and tell me which steps I must do myself.

**Install on this Mac**
> Read AGENTS.md and install Jarvis on this Mac, following docs/install-mac.md. Ask before each step.

**Move Jarvis from this Mac to a server**
> Read AGENTS.md and move my Jarvis from this Mac to my server at SERVER_IP, following docs/server.md.

**Open it from anywhere** (no VPN on the phone)
> Read AGENTS.md and docs/public-address.md. Give my Jarvis server a free public name, with the sign-in set first.

**Connect something**
> Read AGENTS.md and help me connect [Google Calendar and Gmail | my bank's alert emails | encrypted backups |
> Telegram | Sign in with Google].

**Something's wrong**
> Read AGENTS.md and docs/troubleshooting.md. PROBLEM, e.g. "the app says Jarvis is restarting". Check my server
> over SSH and tell me what's wrong before changing anything.

**Update**
> Read AGENTS.md and update Jarvis on my server to the newest version, then check it's healthy.

## 4. What you'll do yourself

The agent pauses and asks you to:

- create accounts: the cloud server, the free name, the Google Cloud project, the Telegram bot;
- click in web consoles, e.g. to open a firewall port in Oracle's security list;
- sign in to Google or Apple in your browser;
- type passwords and tokens into **your terminal**, never into the chat. The agent gives you the exact command, e.g.
  `ssh -t SERVER jarvis-system/.venv/bin/jarvis-auth password`;
- use your phone: scan the VPN QR code, add the app to the Home Screen, allow notifications.

## 5. Stay safe

- **Approve each change.** Jarvis's instructions tell the agent to ask before installing, editing settings, opening
  ports or restarting anything, and to back up a settings file before changing it. Read what it plans, then approve.
  Most agents also ask before every command, unless you switch that off.
- **Never paste a password, token, API key or private key into the chat.** A good agent won't ask. If one gets into
  the chat by mistake, replace it: set a new password, make a new token in that service, or make a new Google
  client.
- **Keep it to your own machines.** Give the agent SSH access to your Jarvis server only.

When it's done, try the checks in [testing.md](testing.md#3-checks-on-your-own-install). Or ask the agent to run them.
