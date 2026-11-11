# Open Jarvis without the VPN

On a server set up with [server.md](server.md), Jarvis is reachable only through WireGuard. With a public name such
as `yourname.dynv6.net`, you open the app from any phone or computer instead and sign in. The VPN stays for SSH.

What the internet can reach then: Caddy on ports 80 and 443, for that name only. It serves only the app, which asks
for a sign-in. The database, Hermes and Ollama still listen on the server itself only, and the server's bare IP
address doesn't serve the app.

Everything here is free.

## 1. Set a sign-in first

```bash
~/jarvis-system/.venv/bin/jarvis-auth password
```

See [sign-in.md](sign-in.md). Until a sign-in is set, the app refuses to answer on a public name.

## 2. A free name

[dynv6](https://dynv6.com) gives free names under `dynv6.net`:

1. Sign up and confirm the email.
2. Create a zone: your name, under `dynv6.net`.
3. **Edit Zone** → **IPv4 address**: the server's public IP. Leave IPv6 empty.

Other free names work too, if their ending is on the [public suffix list](https://publicsuffix.org/list/) (Let's
Encrypt and Google then treat your name as a domain of its own). Before you choose one, check two things:

- **Your own internet provider must find it.** Some providers block `duckdns.org`: BSNL in India did in November
  2026. Check with `dig duckdns.org` on your home network; `NXDOMAIN` means blocked.
- **The service must still give out names.** deSEC's `dedyn.io` stopped taking new names in November 2026.

A domain you own works the same way, with an `A` record for the server's IP.

Keep the service's update token to yourself. Anyone who has it can point your name at another server.

## 3. Open the web ports in Oracle

The instance's subnet → **Security lists** → Default → **Add ingress rules**, two rules with source `0.0.0.0/0`,
protocol **TCP**: destination port **80**, and destination port **443**. Port 80 only answers Let's Encrypt and sends
browsers to `https://`.

## 4. Set it up on the server

```bash
cd ~/jarvis-system && JARVIS_DOMAIN=yourname.dynv6.net deploy/server/prepare.sh SERVER_PUBLIC_IP
```

This runs the server preparation again, which is safe and takes a few minutes. With the name, it also:

- opens TCP 80 and 443 in the server's own firewall;
- adds the name to Caddy, which gets a free Let's Encrypt certificate and renews it by itself;
- adds the name to `JARVIS_HOSTS` in `.env` and restarts the app.

Later runs keep the name. To check it, `curl -sI https://yourname.dynv6.net` from your computer should answer
`303` with `location: /login`.

## 5. The phone

1. Turn the VPN off and open `https://yourname.dynv6.net` in Safari. Sign in.
2. **Share → Add to Home Screen.** It's a new app because the address changed.
3. Turn notifications on in **More → Notifications**, then delete the old icon.

Every 20 minutes the keep-warm job checks that the public address answers, and tells you if it stops.

**Sign in with Google** needs a name like this, because Google only sends you back to an `https://` domain:
[sign-in.md](sign-in.md#sign-in-with-google-optional).
