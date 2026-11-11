# Run Jarvis free on Oracle Cloud

Oracle Cloud's **Always Free** tier includes an ARM server (Ampere A1) that's big enough for Jarvis and costs
nothing. Jarvis's weekly tests run on a machine set up the same way (ARM64 Ubuntu, the model on 2 cores), so this
is a tested path.

| | Used by Jarvis | Always Free limit |
|---|---|---|
| Server | `VM.Standard.A1.Flex`, 2 OCPU, 12 GB memory, running all month | 2 OCPU and 12 GB running all month (1,500 OCPU-hours and 9,000 GB-hours a month) |
| Disk | one boot volume, 50–100 GB | 200 GB of block storage in total |
| Backups | Object Storage bucket | 20 GB |

Stay at or under these numbers and nothing is charged. These are from Oracle's
[Always Free resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm)
page, checked in November 2026; older pages and blog posts mention 4 cores and 24 GB, which was the earlier allowance.
Check the page before you create the server.

## 1. Create the account

Sign up at [oracle.com/cloud/free](https://www.oracle.com/cloud/free/). Oracle asks for a card to check who you
are. **Pick your home region carefully**: Always Free resources live only in that region, and it can't be changed
later. Choose one close to you.

## 2. Create the server

Console → **Compute → Instances → Create instance**:

1. **Image**: Canonical **Ubuntu 24.04** (or newer), the **aarch64** (ARM) build.
2. **Shape**: Ampere → `VM.Standard.A1.Flex` with **2 OCPUs** and **12 GB** memory.
3. **Networking**: keep the new virtual cloud network, and **assign a public IPv4 address**.
4. **SSH keys**: upload your public key (`~/.ssh/id_ed25519.pub`; make one with `ssh-keygen -t ed25519` if you
   have none). Never upload the private key.
5. **Boot volume**: 50–100 GB.

Create it and note the public IP. If Oracle says **"Out of host capacity"**, free ARM servers are busy in that
area. Try another availability domain, or try again later; it usually works within a day.

## 3. Install Jarvis

Continue with [install-server.md](install-server.md) from step 2. In short:

```bash
ssh ubuntu@YOUR_SERVER_IP
git clone https://github.com/GuruGd29/jarvis-assistant.git ~/jarvis-system
cd ~/jarvis-system
deploy/server/prepare.sh YOUR_SERVER_IP    # security, firewall, VPN, HTTPS
./install.sh                               # Jarvis; answer a few questions
.venv/bin/jarvis-auth password             # the app's sign-in
```

The installer sets the server's clock to your time zone, so the morning brief comes at your 7:30.

## 4. Reach it from your phone

Oracle's network lets nothing in until you add a rule: **Networking → Virtual cloud networks →** your network →
**Security Lists → Default → Add Ingress Rules**, with source `0.0.0.0/0`:

- **Free public name, no VPN app on the phone:** TCP **80** and TCP **443**, then
  [public-address.md](public-address.md).
- **VPN only:** **UDP** 51820, not TCP, then step 6B of [install-server.md](install-server.md#6-reach-it-from-your-phone).

## 5. Then

[Connect Google](google.md), set up [money](money.md) and [backups](backups.md) (Oracle Object Storage is free up
to 20 GB). Every setting and account is in [configuration.md](configuration.md).

## Good to know

- **Idle servers.** Oracle may reclaim an Always Free server that stays almost idle for a week. Jarvis's regular jobs
  usually keep it busy enough. If Oracle warns you, upgrading the account to *Pay As You Go* stops this and still
  charges nothing within the free limits. With backups set up ([backups.md](backups.md)) nothing is lost; without them, a reclaimed server takes everything with it.
- **Memory.** Jarvis uses about 9–10 GB of the 12 GB with every model loaded (measured in the weekly test run), which leaves room, but not for a second large model.
- **Speed.** Replies are slower than on a Mac, because there's no GPU. Scheduled reminders and briefings don't
  depend on the model's speed.
- **Updates.** `cd ~/jarvis-system && git pull && ./install.sh`. Ubuntu security updates install themselves when
  `unattended-upgrades` is on (it is on Oracle's Ubuntu images by default).
