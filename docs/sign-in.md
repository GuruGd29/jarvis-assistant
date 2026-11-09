# Sign in to the app

The Jarvis app can ask for a sign-in: a **password**, **Sign in with Google**, or both. You need it as soon as the app
can be reached from the internet, for example on your own domain. Without it, anyone who finds the address could read
your money, calendar and files.

Sign-in is off until you set one of them up, so the app on a Mac at home works as before. While it's off, Jarvis
refuses to answer on a public address (a domain name or a public IP). It still answers on `127.0.0.1`, your home
Wi-Fi and the WireGuard VPN.

## Password

On the machine running Jarvis:

```bash
~/jarvis-system/.venv/bin/jarvis-auth password
```

- Use at least 12 characters. Four random words are easy to type and hard to guess.
- Only a scrypt hash is saved, in `secrets/web-password`. The password itself is stored nowhere.
- Setting a new password signs every device out.
- Wrong guesses slow down. After 5 wrong tries from one address, that address waits 1 minute, then 2, 4 and so on,
  up to an hour. After 20 wrong tries in an hour from anywhere, the password pauses for 15 minutes for everyone.
  Google sign-in still works during the pause.

A sign-in lasts 30 days and renews while you use the app, so a phone you use every day stays signed in.

## Sign in with Google (optional)

This uses the Google Cloud project from [google.md](google.md), with a second client of a different type. Google
sends you back to the app's web address, which a "Desktop app" client can't do. It asks Google only for your email
address and can't read anything else.

Google only sends you back to an `https://` domain name, not to an IP address such as `10.8.0.1`. So Google sign-in
needs the app on a domain. The password works anywhere.

1. [console.cloud.google.com](https://console.cloud.google.com) → your Jarvis project → **APIs & Services →
   Credentials → Create credentials → OAuth client ID**.
2. Application type **Web application**, name "Jarvis sign-in".
3. **Authorised redirect URIs** → **Add URI**: `https://YOUR-DOMAIN/auth/google/callback`.
4. **Create**, then **Download JSON**. Save it on the machine running Jarvis as
   `~/jarvis-system/secrets/google-login.json`:

   ```bash
   scp ~/Downloads/client_secret_*.json ubuntu@SERVER:~/jarvis-system/secrets/google-login.json
   ssh ubuntu@SERVER chmod 600 jarvis-system/secrets/google-login.json
   ```

5. In `~/jarvis-system/.env`, list the Google accounts allowed to sign in (only these can):

   ```
   JARVIS_LOGIN_EMAILS=you@gmail.com
   ```

6. Restart the app: `sudo systemctl restart jarvis-web` on a server, or
   `launchctl kickstart -k gui/$(id -u)/com.jarvis.web` on a Mac.

The sign-in page then shows **Sign in with Google**. Any other Google account gets "That Google account isn't
allowed to sign in to Jarvis."

## Check and sign out

- `~/jarvis-system/.venv/bin/jarvis-auth status` shows how the app signs in.
- **More → Sign out** signs out that device and removes the screens' saved copies from it.
- To sign out every device, set a new password.

What answers without signing in: the sign-in pages, `/api/health` (only "ok" or "down" for each part), and the app's
own code and icons, which are open source anyway.
