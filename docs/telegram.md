# Telegram (optional)

Chat with Jarvis from Telegram as well as the phone app, and get the morning brief, reminders and weekly reports as
Telegram messages. Telegram is free. Jarvis works fine without it.

**Privacy:** the AI still runs on your own machine, but messages to a Telegram bot travel through Telegram's servers
and aren't end-to-end encrypted. If that matters to you, use the phone app only.

## 1. Make a bot

1. In Telegram, open **@BotFather** and send `/newbot`.
2. Give it a name (e.g. "My Jarvis") and a username that ends in `bot` (e.g. `priya_jarvis_bot`).
3. BotFather replies with a **token** like `123456789:AA…`. It's a password for the bot, so keep it private.

## 2. Find your user ID

Open **@userinfobot** in Telegram and send it any message. It replies with your numeric **Id**, e.g. `123456789`.
Only this ID will be able to use your bot; everyone else is ignored.

## 3. Give them to Jarvis

On the machine running Jarvis, type them into the terminal yourself (never into a chat):

```bash
cd ~/jarvis-system && ./install.sh
```

The installer keeps all your earlier answers and asks for the **Telegram bot token** and **your Telegram user id**.
It saves both in `~/.hermes/.env` (as `TELEGRAM_BOT_TOKEN` and `TELEGRAM_ALLOWED_USERS`), restarts Jarvis, and
points the scheduled jobs at your Telegram.

It keeps values it already has, too. So **to replace a token or an ID** (after a typo, or if a token leaked), first
delete the two `TELEGRAM_` lines from `~/.hermes/.env`, then run `./install.sh` again.

On a Mac set up by hand ([install-mac.md](install-mac.md)), add the two lines to `~/.hermes/.env` yourself, then run
`hermes gateway restart` and `bin/add-jobs.sh`.

## 4. Try it

Send your bot "Hi". The first reply after a restart can take a few minutes on a small server (see
[troubleshooting.md](troubleshooting.md#the-first-reply-takes-minutes)).

## What works in Telegram

- **Chat:** everything the app's chat does: questions, files, money, tasks, memory.
- **Files:** files you send the bot are saved to `~/Jarvis` and become searchable ([files.md](files.md)).
- **Messages from Jarvis:** the morning brief, reminders, renewal alerts, and the weekly and monthly reports. They
  also appear in the app under **More → Activity**.
- **Voice notes:** turned into text on a Mac, but not on a server. Use the app's mic button there
  ([voice.md](voice.md)).

## Turn it off

Delete the two `TELEGRAM_` lines from `~/.hermes/.env`, then:

```bash
sudo systemctl restart jarvis-hermes && ~/jarvis-system/bin/add-jobs.sh   # on a Mac: hermes gateway restart
```

The scheduled jobs go back to the app's notifications only. You can also delete the bot in @BotFather (`/deletebot`).
