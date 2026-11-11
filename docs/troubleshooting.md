# Troubleshooting

Find what you see below. If it isn't here, the logs usually say why:

```bash
curl -s http://127.0.0.1:8791/api/health                 # which part is down
journalctl -u jarvis-web -u jarvis-hermes -u ollama -n 100 # on a server; add -f to follow
ls ~/jarvis-system/logs/                                 # the scheduled jobs' logs
```

On a Mac, Hermes's logs are in `~/.hermes/logs/` and the app server's in `~/jarvis-system/logs/`.

Still stuck? [Open an issue](https://github.com/GuruGd29/jarvis-assistant/issues/new/choose) with what you did, what
you expected and what happened. Remove any personal data first.

## Replies

### The first reply takes minutes

After a restart, the model has to read Jarvis's instructions once (about 6,000 tokens). On a 2-core server that
takes up to 10 minutes; on a Mac, seconds. The keep-warm job does it within 20 minutes of a restart. To start it at
once:

```bash
~/jarvis-system/.venv/bin/jarvis-warm-chat
```

The instructions include today's date, so just after midnight the first reply is a little slower too.

### Replies are always slow

A small model on a processor without a graphics card is slow. On Oracle's free server, measured:

- a short reply takes 15–40 seconds once warm;
- a question that needs a tool (calendar, money, search) takes 1–3 minutes.

On a Mac with Apple silicon, it's a few seconds. Long answers take longer, because the model writes about 4 words a
second on 2 cores. Scheduled reminders and briefings don't wait for the model.

### "Jarvis is restarting. Try again in a minute."

The app can't reach Hermes. On a server, check `systemctl status jarvis-hermes`, then
`journalctl -u jarvis-hermes -n 50`. On a Mac, run `hermes gateway restart` and look in `~/.hermes/logs/`.

### "Jarvis's database isn't answering"

Postgres is down. On a server: `sudo systemctl status postgresql`. On a Mac: `brew services list` should show
`postgresql@17` started (or, with the Docker option, `docker ps` shows `jarvis-db`).

## Opening the app

### "Unknown address for Jarvis."

The app answers only to the addresses in `JARVIS_HOSTS` in `.env`. Add the one you opened, comma-separated, then run
`sudo systemctl restart jarvis-web`.

### "Jarvis has no sign-in yet, so it doesn't answer on a public address"

Set a password first: `~/jarvis-system/.venv/bin/jarvis-auth password` ([sign-in.md](sign-in.md)).

### "Please sign in again", or the sign-in page keeps coming back

The sign-in ran out (30 days without using the app), or a new password signed every device out. Sign in again. If it
happens right after signing in, check the browser allows cookies for the site.

### "Too many wrong tries"

Wrong passwords slow down on purpose. Wait the time shown, or use Sign in with Google. To change a forgotten
password: `jarvis-auth password` on the server.

### Sign in with Google

| What you see | Fix |
|---|---|
| No "Sign in with Google" button | it needs `secrets/google-login.json` **and** your address in `JARVIS_LOGIN_EMAILS`, then `sudo systemctl restart jarvis-web` |
| "That Google account isn't allowed" | add that address to `JARVIS_LOGIN_EMAILS` |
| Google says `redirect_uri_mismatch` | the client's **Authorised redirect URI** must be exactly `https://YOUR-NAME/auth/google/callback` |
| "Google hasn't verified this app" | expected for a personal app: **Advanced → Go to Jarvis** |
| "Google sign-in didn't finish" | try again. If it keeps failing, see `journalctl -u jarvis-web` for the reason |

### The browser warns about the certificate on https://10.8.0.1

The phone or computer doesn't trust Caddy's own certificate yet. Do step 4 of
[remote-access.md](remote-access.md#4-trust-caddys-certificate-on-the-phone-once) once. A public name
([public-address.md](public-address.md)) gets a normal certificate instead.

### The phone can't reach https://10.8.0.1

- Is the WireGuard app switched on? Its *latest handshake* should be recent.
- On Oracle, the security list rule must be **UDP** 51820. TCP is a common mistake.
- On the server: `sudo wg show` lists the phone with a recent handshake when the VPN works.
- Some home and mobile networks use `10.8.0.1` themselves. With the VPN off you then reach some other device and get
  a certificate warning. Switch the VPN on.

### The public name doesn't open

1. Does the name point at the server? `dig +short yourname.dynv6.net` should print the server's public IP.
2. Are TCP 80 and 443 allowed in the provider's firewall (Oracle: the security list)?
3. Did Caddy get its certificate? `journalctl -u caddy -n 50` names any problem.
4. Some internet providers block some free name services. BSNL in India blocks `duckdns.org`, for example. Check
   with `dig duckdns.org` on that network: `NXDOMAIN` means blocked.

### Notifications don't arrive

- **iPhone:** they only work from the Home Screen app, on iOS 16.4 or newer.
- Turn them on in **More → Notifications**, and send a test notification from there.
- After the app's address changes, it's a new app: turn them on again in the new one.
- Check the phone's own settings: **Settings → Notifications → Jarvis**.

## Accounts and data

### Calendar or Gmail stopped working

The Google sign-in ran out. If your Google Cloud app is still in *Testing*, Google ends sign-ins after 7 days: publish
it ([google.md](google.md#2-the-consent-screen)). Then sign in again with `jarvis-auth google`. A daily job tells you
when this happens.

### Spending is missing or wrong

- The **From** addresses in `secrets/money.json` must match the bank's alert emails exactly.
- Read the emails again and see what happened to each one:

  ```bash
  ~/jarvis-system/.venv/bin/jarvis-money-sync --days 30 --verbose
  ```

- Payments without an alert email (cash, some wallets) can't be counted. See [money.md](money.md).

### Jarvis doesn't find a document

- New files are read every 15 minutes. **More → Your files** adds one at once and shows whether each file can be
  searched.
- The supported types are PDF, Word, text, Markdown, CSV and HTML, plus photos and scans with text recognition
  ([files.md](files.md)).
- A scanned PDF without text needs text recognition installed.

## Installing and servers

### Oracle says "Out of host capacity"

Free ARM servers are busy in that area. Try another availability domain, or try again later; it usually works within
a day.

### The installer stops at a password prompt

Your user needs `sudo` rights. Run `sudo -v` once and type your password, then run `./install.sh` again.

### Backups fail with "Access Denied" or "bucket not found"

- **Access Denied right after you made the key:** a new Oracle Customer Secret Key takes about 2 minutes to start
  working. Try again.
- **Bucket not found:** the URL needs the Object Storage **namespace**, which isn't the bucket's name. Find it in the
  bucket's details. See [backups.md](backups.md).

### The server is short of memory

Run `free -h` and `ollama ps`. Jarvis needs about 9–10 GB with every model loaded. Other big programs on the same
12 GB server, such as Docker apps or a second model, make it swap and slow down.

### Updating broke something

`bin/update.sh` goes back to the version before by itself when Jarvis isn't healthy afterwards. To go back by hand:

```bash
cd ~/jarvis-system && git log --oneline -5      # find the last good version
git checkout <version> && ./install.sh
```

When a fixed version is out: `git checkout main && ./install.sh` (or `bin/update.sh`).
