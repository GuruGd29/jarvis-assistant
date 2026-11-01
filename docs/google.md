# Connect Google (Calendar, Gmail, Drive)

Jarvis reads your Google Calendar, Gmail and one Drive folder with **your own** Google sign-in. Google calls this an
"OAuth client", and you make it once in your own Google Cloud project. It's free and takes about 15 minutes. Jarvis
never sees your Google password.

What Jarvis can do with it:

| Google service | Access | Used for |
|---|---|---|
| Calendar | read, and add events | your schedule; an event is added only after you reply "yes" |
| Gmail | **read-only** | inbox summaries, bank alert emails for money |
| Drive | **read-only** | copying the folder named "Jarvis" when you say "sync drive" |

Jarvis cannot send, reply to or delete email, and cannot change or delete anything in Drive.

## 1. Create the project and turn on the APIs

1. Open [console.cloud.google.com](https://console.cloud.google.com) and sign in with the Google account Jarvis
   should read.
2. Create a project (top bar → project picker → **New project**), for example "Jarvis".
3. **APIs & Services → Library**: enable **Google Calendar API**, **Gmail API** and **Google Drive API**.

## 2. The consent screen

1. **APIs & Services → OAuth consent screen** (also called *Google Auth Platform*). Choose **External**.
2. App name "Jarvis"; your email as the support and developer contact. You can leave the logo and links empty.
3. **Audience → Test users**: add your own Google address.
4. **Publish the app** (Audience → *Publish app* → "In production"). Without this, Google signs you out every
   7 days. Because the app isn't verified, Google shows a "Google hasn't verified this app" screen when you sign in.
   That's expected for a personal app: choose **Advanced → Go to Jarvis**. Verification is only needed for apps with
   more than 100 users.

## 3. The client file

1. **APIs & Services → Credentials → Create credentials → OAuth client ID**, application type **Desktop app**.
2. **Download JSON** and save it as `~/jarvis-system/secrets/google-client.json` on the machine running Jarvis.
   From your own computer to a server:

   ```bash
   scp ~/Downloads/client_secret_*.json ubuntu@SERVER:~/jarvis-system/secrets/google-client.json
   ```

## 4. Sign in

**On a Mac (or a Linux PC with a browser):**

```bash
~/jarvis-system/.venv/bin/jarvis-auth google
```

A browser opens. Choose your account, allow access, and the terminal prints your calendars.

**On a server** (no browser there): Google sends you back to a local address, so forward it from your computer.

1. On your own computer, open an SSH connection with a tunnel and leave it open:

   ```bash
   ssh -L 8085:127.0.0.1:8085 ubuntu@SERVER
   ```

2. In that SSH session, on the server:

   ```bash
   ~/jarvis-system/.venv/bin/jarvis-auth google --port 8085
   ```

3. Open the link it prints in your computer's browser, allow access, and the server prints your calendars.

Check any time with `~/jarvis-system/.venv/bin/jarvis-auth status`. A daily job warns you (in the app, and on
Telegram if you use it) if the sign-in ever stops working; running `jarvis-auth google` again fixes it.

## iCloud calendar (optional)

```bash
~/jarvis-system/.venv/bin/jarvis-auth icloud
```

It asks for your Apple ID email and an **app-specific password**, which you create at
[appleid.apple.com](https://appleid.apple.com) → Sign-In and Security. Never use your real Apple ID password.

## Removing access

Remove Jarvis at [myaccount.google.com/permissions](https://myaccount.google.com/permissions), and delete
`~/jarvis-system/secrets/google-token.json`.
