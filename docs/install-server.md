# Install Jarvis on a server

This guide installs Jarvis on a fresh Ubuntu server so it runs around the clock. It works on:

- **Oracle Cloud's free ARM server**, which costs nothing; [oracle-cloud.md](oracle-cloud.md) shows how to create it.
- **Any other Ubuntu server:** a VPS from Hetzner, DigitalOcean, AWS Lightsail and so on, or a Linux PC at home.

Plan on about an hour, mostly waiting for downloads. You need SSH access and `sudo` on the server.

> **Already running Jarvis on a Mac?** Use [server.md](server.md) instead. It does these steps from the Mac and moves
> your data and sign-ins across.

**There is no separate installer to download: the repository is the installer.** You clone it onto the machine
that will run Jarvis, and `install.sh` sets everything up from there. Updates come with `git pull`.

## What you need

| | Minimum | Tested |
|---|---|---|
| System | Ubuntu 24.04 or newer | 24.04 (weekly tests) and 26.04 (the author's Oracle server) |
| Processor | ARM64 or x86-64, 2 cores | Ampere A1, 2 cores |
| Memory | 12 GB (8 GB works, but slowly, with swapping) | 12 GB |
| Disk | 40 GB (the installer needs 20 GB free) | 50–100 GB |
| Network | a public IPv4 address | |
| Graphics card | not needed | none |

Jarvis uses about 9–10 GB of memory with every model loaded.

## 1. Get a server

- **Oracle (free):** follow steps 1 and 2 of [oracle-cloud.md](oracle-cloud.md), then come back here.
- **Another provider:**
  - Create an Ubuntu 24.04 (or newer) machine with at least 12 GB of memory, and add your SSH public key when
    asked.
  - Note its public IP address.
  - In the provider's firewall (often called a *security group* or *firewall rules*), allow **TCP 22** for now.
  - **No firewall at your provider?** Then turn on the server's own after step 3, keeping SSH open:
    `sudo ufw allow 22/tcp && sudo ufw allow 51820/udp && sudo ufw enable`. Add `sudo ufw allow 80/tcp` and
    `sudo ufw allow 443/tcp` for a public name. Wherever this guide says "the provider's firewall", use `ufw` instead.

## 2. Connect and get the code

```bash
ssh ubuntu@SERVER_IP
```

The user name depends on the provider: `ubuntu` on Oracle and AWS, often `root` elsewhere. Jarvis's scripts must run
as a normal user with `sudo`, not as root. If you can only log in as root, make a user once and log in as that:

```bash
adduser jarvis && usermod -aG sudo jarvis && rsync -a ~/.ssh /home/jarvis/ && chown -R jarvis: /home/jarvis/.ssh
```

Then get Jarvis:

```bash
git clone https://github.com/GuruGd29/jarvis-assistant.git ~/jarvis-system
cd ~/jarvis-system
```

## 3. Prepare the server: security, VPN and HTTPS

```bash
deploy/server/prepare.sh SERVER_IP
```

It takes a few minutes and is safe to run again. It sets up:

- **Updates:** installs all updates now, and security updates from then on by themselves.
- **Swap:** a 4 GB swap file as a safety margin for memory.
- **SSH:** keys only, with no passwords and no root login, plus fail2ban against password guessers.
- **Firewall:** opens the WireGuard port (UDP 51820) in the server's own firewall, plus ports 80 and 443 with a
  public name (step 6A). Oracle's images already block everything else on the server itself. On other providers
  the server's firewall is usually off, so the provider's firewall decides: allow only the ports this guide names.
  Jarvis's own services listen on the server itself or on the VPN either way.
- **WireGuard VPN:** a private network where the server is `10.8.0.1`. It makes two profiles in `~/jarvis-vpn/`, one
  for your phone and one for your computer.
- **HTTPS:** Caddy serves the app at `https://10.8.0.1`, on the VPN only.

If it ends with "The updates need a restart", run `sudo reboot` and connect again.

## 4. Install Jarvis

```bash
./install.sh
```

The installer asks a few questions. Press Enter to take the suggestion in brackets.

| Question | What to answer |
|---|---|
| Your first name | used in greetings; Enter for none |
| Language_COUNTRY | how numbers and dates look: `en_IN` India, `en_US` USA, `en_GB` UK, `de_DE` Germany… |
| Currency code | `INR`, `USD`, `EUR`…; Enter uses your country's |
| Time zone | e.g. `Asia/Kolkata`, `Europe/London`. The server's clock is set to it |
| Languages | the languages you write in, e.g. `Tamil and English` |
| An email for notifications | only Apple's and Google's push services see it; Enter to skip |
| Bank emails without a built-in reader | `nightly` (default), `always` or `off` ([money.md](money.md)) |
| Telegram bot token | Enter to skip; you can add it later ([telegram.md](telegram.md)) |

Then it installs everything in order:

1. Postgres with pgvector.
2. The Python environment.
3. Ollama and the models (about 4 GB).
4. Hermes Agent.
5. The services `ollama`, `jarvis-hermes` and `jarvis-web`, which start again after a reboot.
6. The scheduled jobs.

It takes 15–30 minutes. Every answer is saved in `~/jarvis-system/.env`, and you can change any of them later
([configuration.md](configuration.md)).

After `prepare.sh`, the installer also tells the app which addresses it's opened by (`JARVIS_HOSTS` in `.env`). The
app refuses any other address, which stops some web attacks. `grep JARVIS_HOSTS .env` shows them.

Check that it's running:

```bash
curl -s http://127.0.0.1:8791/api/health          # {"ok": true, "database": "ok", "hermes": "ok", "ollama": "ok"}
systemctl status jarvis-hermes jarvis-web ollama   # all "active (running)"
```

## 5. Set a sign-in

```bash
.venv/bin/jarvis-auth password
```

Use at least 12 characters. You need a sign-in before the app can be on the internet (step 6A), and it's a good
idea on the VPN too. Google sign-in can be added later: see [sign-in.md](sign-in.md).

## 6. Reach it from your phone

Choose one, or use both:

| | A. Public name: easiest | B. VPN only: most private |
|---|---|---|
| You open | `https://yourname.dynv6.net`, from anywhere | `https://10.8.0.1`, with the VPN switched on |
| What the internet can reach | the app, behind its sign-in (ports 80, 443), and the VPN port | only the VPN port |
| Phone setup | nothing to install | the WireGuard app, and trusting a certificate once |
| Sign in with Google | works | not possible: Google needs a domain name |

**A. Public name.** Follow [public-address.md](public-address.md):

1. Get a free name, e.g. from dynv6.
2. Allow TCP 80 and 443 in the provider's firewall.
3. Run:

   ```bash
   JARVIS_DOMAIN=yourname.dynv6.net deploy/server/prepare.sh SERVER_IP
   ```

Caddy then gets a free Let's Encrypt certificate by itself.

**B. VPN only.**

1. Allow **UDP 51820** in the provider's firewall.
2. Show the phone's VPN profile as a QR code. Install **WireGuard** on the phone, tap **+ → Create from QR code**,
   scan it, and switch it on:

   ```bash
   qrencode -t ansiutf8 < ~/jarvis-vpn/phone.conf
   ```

   The profile sends only Jarvis's traffic through the VPN, so it can stay on all the time.
3. Trust Caddy's certificate on the phone once: step 4 of [remote-access.md](remote-access.md#4-trust-caddys-certificate-on-the-phone-once).

**Then, either way:**

1. Open the address in the phone's browser and sign in.
2. Tap **Share → Add to Home Screen**.
3. Turn notifications on in **More → Notifications**. On an iPhone this needs iOS 16.4 or newer, and only works from
   the Home Screen app.

## 7. Close SSH to the internet (recommended)

Once the VPN works, SSH doesn't need to be open to everyone:

1. Copy the computer's VPN profile to your computer:

   ```bash
   scp ubuntu@SERVER_IP:jarvis-vpn/computer.conf .
   ```

2. Import it in the WireGuard app (**Import tunnel(s) from file**), switch it on, and delete the copied file; it
   holds a private key.
3. Check that `ssh ubuntu@10.8.0.1` works.
4. Delete the **TCP 22** rule in the provider's firewall.

Leave the server's own firewall rule for SSH in place. If the VPN ever breaks, adding the provider's TCP 22 rule again
is then your way back in. Without a provider firewall, close it on the server instead with
`sudo ufw delete allow 22/tcp`; your way back in is then the provider's web console.

## A Linux PC at home

The same steps work on a PC at home, with three differences:

- **Router:** for the phone to reach it from outside, forward the ports from your router to the PC: UDP 51820 for
  the VPN, or TCP 80 and 443 for a public name.
- **Address:** `SERVER_IP` is your home's public address (`curl -4 ifconfig.me`). Many home connections change it from
  time to time, so a public name that you update (dynv6 has an update address; see [public-address.md](public-address.md))
  is the steadier choice. Some providers don't give homes a public address at all; then use the VPN through another
  server, or only home Wi-Fi.
- **SSH:** `prepare.sh` turns off SSH password logins. Set up an SSH key first if you log in to the PC from another
  computer.

To use it only on your home Wi-Fi instead, skip `prepare.sh` and follow
[remote-access.md](remote-access.md#mac-or-pc-on-home-wi-fi).

## 8. Connect your accounts and add your data

| What | Guide |
|---|---|
| Your documents: copy them into `~/Jarvis/documents`, `finance`, `health` or `notes`, or use **More → Your files** in the app | [files.md](files.md) |
| Google Calendar, Gmail and Drive (on a server, the sign-in goes through an SSH tunnel) | [google.md](google.md#4-sign-in) |
| iCloud calendar | [google.md](google.md#icloud-calendar-optional) |
| Spending from your bank's alert emails | [money.md](money.md) |
| Telegram | [telegram.md](telegram.md) |
| Encrypted backups | [backups.md](backups.md) |
| Voice messages: set up by `install.sh` on a server | [voice.md](voice.md) |

To copy files from your computer to the server:

```bash
scp -r ~/Documents/insurance ubuntu@SERVER:Jarvis/documents/
```

They're searchable within 15 minutes. Every setting, secret file and email address is explained in
[configuration.md](configuration.md).

## 9. Keep it running

- **Updates:** run `bin/update.sh`. It gets the new version from GitHub, updates only what changed, and goes back to
  the previous version by itself if Jarvis isn't healthy afterwards. Running `git pull && ./install.sh` also works.
- **After a restart:** everything starts by itself. The model then re-reads its instructions, so the first reply can
  take up to 10 minutes on a 2-core server. Start it straight away with `.venv/bin/jarvis-warm-chat`, or let the
  keep-warm job do it within 20 minutes.
- **Watching:** every 20 minutes the keep-warm job checks the database, the agent, the model and the HTTPS address.
  It tells you in the app (and on Telegram, if you use it) when something stops.
- **Logs:** `journalctl -u jarvis-web -u jarvis-hermes -u ollama -f`, and `~/jarvis-system/logs/`.
- **Something wrong?** See [troubleshooting.md](troubleshooting.md).
