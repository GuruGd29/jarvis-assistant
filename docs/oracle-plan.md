# Jarvis on Oracle Cloud — build plan

Target: Oracle Always Free **Ampere A1, 2 OCPU / 12 GB RAM**, Ubuntu 24.04 (ARM64), no GPU.
Everything below is open source and free. Nothing here needs a payment.

**Expected speed** (estimates, measured in phase 8): short replies 20–60 s, email/calendar
questions 1–2 min, once after a restart a few minutes. Reminders, morning brief and money
sync run 24/7 without the Mac.

Who does what: **You** = steps that need your Oracle login, phone or passwords.
**Claude** = everything over SSH, after you approve each phase.

---

## Phase 0 — Prepare on the Mac first (Claude, testable now)

1. **Smaller instructions:** cut Jarvis's prompt from ~10K to ~4–5K tokens (shorter SOUL.md,
   fewer tool descriptions). The biggest speed win on a CPU server. Measure on the Mac.
2. **Fix the morning brief** (failing since 28 Oct: times out waiting for the model).
3. **Package the stack** as one `docker-compose.yml` (Postgres + Open WebUI + Caddy) plus
   install scripts, so the server build is repeatable.
4. **Export script:** one command that bundles the database, Hermes state, Open WebUI data,
   secrets and `~/Jarvis` into an encrypted archive for the move.

## Phase 1 — Create the server (You, ~20 min; Claude guides)

1. Oracle Console → Compute → Create instance: shape `VM.Standard.A1.Flex`, 2 OCPU, 12 GB,
   image Ubuntu 24.04 aarch64, boot volume 100 GB (the free allowance is 200 GB total).
2. Add your SSH public key (Claude can make one on the Mac; the private key never leaves it).
3. Networking (security list): allow only **TCP 22** (temporary) and **UDP 51820** (WireGuard).
4. Send Claude the public IP.

If Oracle says "Out of host capacity", retry later or in another availability domain. This
is common for free A1 servers.

## Phase 2 — Lock down the base system (Claude)

- System updates, plus automatic security updates (`unattended-upgrades`).
- A normal user for Jarvis; root login off; SSH keys only (passwords off); `fail2ban`.
- Firewall: allow only WireGuard from the internet. Docker skips the firewall, so every
  container is bound to `127.0.0.1` or the VPN address only, never `0.0.0.0`.
- 4 GB swap file (a safety margin for 12 GB), time zone Asia/Kolkata.

## Phase 3 — Private access with WireGuard (Claude + You)

- WireGuard on the server; one profile each for your phone and Mac (QR code for the phone).
- **You:** install the WireGuard app (free, open source) and scan the QR code.
- After it works: **close SSH to the internet** (SSH only through the VPN).
- Telegram needs no open ports. It keeps working even with the VPN off.

## Phase 4 — Install Jarvis (Claude)

| Part | Setting for 2 CPU / 12 GB | Approx. RAM |
|---|---|---|
| Ollama (system service) | qwen3 4B instruct q4, context 24K, KV cache q8, flash attention, 1 slot, models kept loaded (`OLLAMA_KEEP_ALIVE=-1` works on Linux) | 3.5–4.5 GB |
| bge-m3 (search) | via Ollama | 1.2 GB |
| Reranker | bge-reranker-v2-m3 int8 | 0.6 GB |
| Postgres + pgvector | Docker, 127.0.0.1 only | 0.3 GB |
| Hermes gateway + Jarvis plugin | systemd service | 0.6 GB |
| Whisper small (voice) + Piper | int8 on CPU | 0.5 GB |
| Open WebUI | Docker, behind Caddy HTTPS on the VPN address only | 1.0 GB |
| **Total** | | **~8–9 GB of 12** |

- HTTPS inside the VPN (needed for the browser mic): Caddy reuses **your Mac's local CA**, so
  your iPhone, which already trusts it, needs no new certificate.
- Hermes cron jobs move as they are (reminders, money sync, learn, titles, briefing).
- Telegram is the main way to talk to Jarvis. Open WebUI is for occasional use. Switching
  between them clears the one conversation cache, so the next reply is slow.

## Phase 5 — Move your data (Claude, with your OK at the switch-over)

1. **Stop Jarvis's Telegram on the Mac first.** Only one machine may run the bot at a time.
2. Copy the encrypted archive from Phase 0 and restore: database, `~/.hermes` (memory, chats,
   config, plugin, SOUL), Open WebUI data, `secrets/`, `~/Jarvis`.
3. Google: the saved sign-in keeps working on the server. When `jarvis-auth google` is due
   again, run it on the server through an SSH tunnel (Claude gives the command).
4. iCloud Calendar works from the server unchanged.

## Phase 6 — Adding files later (Claude + You)

- **Syncthing** (free, open source) keeps `~/Jarvis` in sync from your Mac and/or phone to the
  server; the server re-indexes changed files every 15 min.

## Phase 7 — Backups (Claude)

- Nightly encrypted backup (`restic`) of the database, Hermes state and `~/Jarvis` to Oracle
  Object Storage (20 GB free), keeping 7 daily + 4 weekly copies; restore tested once.
- Telegram message to you only if a backup fails.

## Phase 8 — Verify, then retire the Mac setup (Claude + You)

- Measure the real speed table (replies, tools, Tamil, voice, search) and send it to you.
- Test reminders, morning brief, money sync and memory for one week on the server.
- Then turn off the Mac's Jarvis services. Keep the Mac copy for 2 weeks as a rollback.

---

## Security on the server (built in during Phases 2–4)

On the Mac the app is only reachable on home Wi-Fi, so it runs without these. On a public server
every layer below is on from day one. Sign-in inside the app is decided at the move (VPN alone,
or VPN plus pairing each device once).

**1. Network: nothing to attack from the internet**
- Only WireGuard (UDP 51820) is open; SSH, the app, Open WebUI, Postgres, Ollama and Hermes listen on
  `127.0.0.1` or the VPN address only. Oracle's security list and the server firewall both enforce it.
- Docker publishes ports to `127.0.0.1` / the VPN address only (Docker bypasses the firewall otherwise).
- Telegram needs no open port (Jarvis calls out to Telegram).

**2. Server: hard to break into**
- SSH keys only, no passwords, no root login, SSH reachable only over the VPN; `fail2ban`.
- Automatic security updates; a non-admin user runs Jarvis; secrets readable by that user only.
- Nightly encrypted backups (restic) to Oracle Object Storage; restore tested.

**3. The web app: safe even if someone reaches it**
- Requests from other websites are refused (a required app header plus `Origin` / `Sec-Fetch-Site`
  checks), so a malicious page you open cannot use the app through your browser.
- Only the app's own host names are accepted (blocks DNS-rebinding tricks).
- Notification sign-ups accepted only for Apple / Google / Mozilla push services, so nobody can make
  the server call other addresses.
- Size limits on every request, a limit on replies running at once, and rate limits.
- Strict browser security headers (no framing, no outside scripts, HTTPS only).
- Optional sign-in: pair each phone once with a 6-digit code; a long-lived, HttpOnly cookie after that.

**4. Jarvis itself**
- Still read-only for email; calendar changes still need your "yes".
- Emails and files remain "data, not instructions" for the model (prompt-injection guard).
- Hermes API key replaced with a long random one; Telegram stays limited to your account.

**5. Checks before going live**
- `pip-audit` on all Python packages, image updates for Docker, and a port scan from outside to confirm
  only WireGuard answers.

---

## Risks to know

- **Idle reclaim:** Oracle can reclaim Always Free servers that stay almost idle (low CPU) for
  7 days. Jarvis's regular jobs may keep it above that line; if Oracle warns you, the free
  fix is upgrading the account to Pay-As-You-Go (it still charges nothing within free limits,
  but it needs a card on file — your call). Nightly backups mean nothing is lost either way.
- **Speed:** CPU-only replies are slower; that is the cost of not depending on the Mac.
- **Memory:** 12 GB fits with ~3 GB to spare; a second large model will not fit.

## What you need to do (in order)

1. Create the server (Phase 1) and send the IP.
2. Install the WireGuard app and scan the QR code (Phase 3).
3. Approve the switch-over moment (Phase 5).
4. Optional: install Syncthing to add files from your phone (Phase 6).
