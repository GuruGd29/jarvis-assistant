# Jarvis on your own server

Jarvis can run on a small Ubuntu 24.04 server instead of your Mac, so it works around the clock without the Mac.
These steps are for Oracle Cloud's free ARM server; any Ubuntu 24.04 server (ARM64 or x86-64) works the same way.
Everything is free and open source; on Oracle it costs nothing within the Always Free limits.

| | Oracle's free server | Any other server |
|---|---|---|
| Processor | 2 cores (ARM) | 2 cores or more; more cores make replies start sooner |
| Memory | 12 GB | 12 GB or more |
| Disk | 100 GB (200 GB is free in total) | 40 GB or more |
| Graphics card | none | none |
| Replies | about 50 s typical, up to 4 min (measured weekly) | |

Oracle's free ARM allowance is 2 cores and 12 GB in total (1,500 core-hours and 9,000 GB-hours a month): a bigger
server is charged for the rest. On a Pay As You Go account, set a **budget alert of ₹1** (Billing → Budgets) to hear
about any charge at once. Oracle may take back a free server that sits idle for a week (under 20% processor, network
and memory use); Jarvis keeps its models in memory, well above that.

## What the scripts do

- `deploy/server/prepare.sh`: security updates, a swap file, SSH with keys only, a firewall that lets in only
  WireGuard, the WireGuard VPN with one profile for your phone and one for your Mac, and HTTPS for the app at
  `https://10.8.0.1`, on the VPN only. With your Mac's certificate authority, so your phone trusts it already.
  When another program already has port 443 (Coolify's proxy, for one), the app is at **`https://10.8.0.1:8443`**
  instead; the script says so. Use that address wherever this guide says `https://10.8.0.1`.
- `install.sh`: Jarvis itself (the same installer the weekly test runs on this kind of server), with voice (the
  small whisper.cpp model, quick without a graphics card) and text recognition.
- `bin/server.sh`, on the Mac: runs the above for you, then moves your data and switches over.

Nothing of Jarvis is reachable from the internet: the app, Ollama, Postgres and Hermes listen on the server itself or
on the VPN address. On top of that, on the server the app answers only to its own address and refuses changes sent
from other websites (`JARVIS_HOSTS`).

## Setting it up

1. **SSH key, on the Mac:** `bin/server.sh key`. It prints a public key to paste in the next step.
2. **The server, in the Oracle Console:** Compute → Instances → Create instance:
   - Image: **Canonical Ubuntu 24.04** (not "Minimal"), aarch64. Shape: **VM.Standard.A1.Flex**, **2 OCPU, 12 GB**
     (the free allowance; more is charged).
   - Networking: a public IPv4 address. SSH keys: **Paste public keys**, the key from step 1.
   - Boot volume: 100 GB. Create, and note the **public IP**.
   - If it says "Out of host capacity", try again later or pick another availability domain.
3. **Open the VPN port:** the instance's subnet → Security lists → Default → Add ingress rule: source `0.0.0.0/0`,
   **UDP**, destination port **51820**.
4. **Prepare and install, on the Mac:** `bin/server.sh setup PUBLIC_IP`. About 30 minutes. Your Mac keeps running
   Jarvis meanwhile; the server gets your settings from the Mac's `.env`.
5. **VPN on the Mac:** install **WireGuard** from the Mac App Store, *Import tunnel(s) from file* →
   `secrets/wireguard-jarvis.conf`, *Activate*. Then `bin/server.sh vpn`, and delete the **TCP 22** rule from the
   security list: from now on SSH works only through the VPN.
6. **VPN on the phone:** install **WireGuard**, then `bin/server.sh phone` shows a QR code on the Mac's screen: in
   the app, **+ → Create from QR code**, scan, and switch it on. It sends only Jarvis's traffic through the VPN, so it
   can stay on all the time.
7. **The switch:** `bin/server.sh move`. It stops Jarvis and its Telegram bot on the Mac, copies the database, your
   files (`~/Jarvis`), the sign-ins (`secrets/`) and Hermes's chats and memory, and starts Jarvis on the server with
   the same scheduled jobs. A few minutes.
8. **The app on the phone:** with the VPN on, open **https://10.8.0.1** in Safari → Share → **Add to Home Screen**.
   It is a new app because the address changed: turn notifications on in **More → Notifications**, then remove the
   old one.
9. **Backups:** the Mac's backups went to a folder on the Mac. For the server, make an Object Storage bucket and a
   Customer Secret Key in Oracle and follow [backups.md](backups.md).

`bin/server.sh status` shows what runs on the server; `bin/server.sh back` undoes the switch (Jarvis starts on the
Mac again; anything new on the server stays there).

### With Coolify (or other Docker apps) on the same server

They work side by side: Jarvis takes port 8443 on the VPN address, and only its own two firewall rules are saved.
Docker's published ports go around the server's firewall, so Oracle's security list is what decides who reaches
them: don't open Coolify's dashboard (8000) to the internet, use `http://10.8.0.1:8000` with the VPN on. Coolify
needs about 2 GB; building big apps on the same 12 GB server can slow Jarvis down.

## Changing Jarvis after the move

The Mac is where Jarvis is changed and tested, with test data; the server only runs it.

1. Change and test on the Mac (Claude Code), then push to GitHub (`main`).
2. `bin/server.sh update`, through the VPN. On the server, `bin/update.sh` takes the new version, installs new
   packages when there are any, applies database changes, restarts only what changed and checks that Jarvis is
   healthy. If it isn't, it goes back to the version before by itself and says so.
3. The phone app updates itself the next time it opens.

## What is different on the server

- **Address:** the app is `https://10.8.0.1`, with the VPN on.
- **iPhone Reminders:** reading the Reminders app needs a Mac, so that part of Today is off. Tasks still go to your
  iPhone's calendar through iCloud.
- **Voice:** the small model: quick, a little weaker on names than the Mac's. Your names list (`JARVIS_VOICE_WORDS`)
  still helps.
- **Speed:** replies come from the server's processor rather than a graphics chip, so they take longer.
- **Telegram voice notes** aren't turned into text (Hermes's own speech-to-text is off on the server); typed messages
  work as before.
