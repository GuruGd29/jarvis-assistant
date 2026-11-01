# Use Jarvis from your phone

The app server listens only on the machine itself (`127.0.0.1:8791`) and **has no login of its own**, so it must
never be opened to the internet. Your phone reaches it in one of two private ways:

- **Server (Oracle or any VPS):** a **WireGuard** VPN. Your phone joins a private network with the server, and the
  app is served over HTTPS on that network only. Below.
- **Mac or PC at home:** your home Wi-Fi, with HTTPS from Caddy. [Jump there](#mac-or-pc-on-home-wi-fi).

HTTPS is needed either way: phones allow Home Screen apps, notifications and the microphone only on secure pages.
Caddy makes its own small certificate authority for this, and your phone trusts it once.

Everything here is free and open source (WireGuard, Caddy).

## Server: WireGuard and HTTPS

The commands run on the server. Replace `YOUR_SERVER_IP` with its public IP.

### 1. Open the WireGuard port

- **Oracle Console** → Networking → Virtual cloud networks → your network → Security lists → Default → **Add ingress
  rule**: source `0.0.0.0/0`, protocol **UDP**, destination port **51820**.
- **The server's firewall.** Oracle's Ubuntu images reject everything not allowed explicitly:

  ```bash
  sudo iptables -I INPUT -p udp --dport 51820 -j ACCEPT
  sudo iptables -I INPUT -i wg0 -j ACCEPT
  sudo netfilter-persistent save
  ```

### 2. WireGuard, with a QR code for your phone

```bash
sudo apt-get install -y wireguard qrencode
cd "$(mktemp -d)" && umask 077
wg genkey | tee server.key | wg pubkey > server.pub
wg genkey | tee phone.key | wg pubkey > phone.pub
sudo tee /etc/wireguard/wg0.conf > /dev/null <<EOF
[Interface]
Address = 10.8.0.1/24
ListenPort = 51820
PrivateKey = $(cat server.key)

[Peer]
# phone
PublicKey = $(cat phone.pub)
AllowedIPs = 10.8.0.2/32
EOF
sudo systemctl enable --now wg-quick@wg0
cat > phone.conf <<EOF
[Interface]
Address = 10.8.0.2/32
PrivateKey = $(cat phone.key)

[Peer]
PublicKey = $(cat server.pub)
Endpoint = YOUR_SERVER_IP:51820
AllowedIPs = 10.8.0.1/32
PersistentKeepalive = 25
EOF
qrencode -t ansiutf8 < phone.conf
```

On the phone, install the **WireGuard** app (free, from the App Store or Play Store), tap **+ → Create from QR
code**, scan it, and switch the tunnel on. Then delete the keys from the server: `rm phone.key phone.conf server.key`.

`AllowedIPs = 10.8.0.1/32` sends only Jarvis's traffic through the tunnel, so the rest of your phone's internet is
unaffected and you can leave the VPN on all the time.

### 3. HTTPS on the private address

```bash
sudo apt-get install -y caddy    # if apt can't find it: caddyserver.com/docs/install#debian-ubuntu-raspbian
sudo tee /etc/caddy/Caddyfile > /dev/null <<'EOF'
{
	local_certs
	skip_install_trust
}

https://10.8.0.1 {
	bind 10.8.0.1
	tls internal
	reverse_proxy 127.0.0.1:8791 {
		flush_interval -1
	}
}
EOF
# Caddy listens on the VPN address, so it must start after WireGuard.
sudo mkdir -p /etc/systemd/system/caddy.service.d
printf '[Unit]\nAfter=wg-quick@wg0.service\nRequires=wg-quick@wg0.service\n' \
  | sudo tee /etc/systemd/system/caddy.service.d/wireguard.conf > /dev/null
sudo systemctl daemon-reload && sudo systemctl restart caddy
```

### 4. Trust Caddy's certificate on the phone (once)

Hand the phone Caddy's public root certificate (it isn't secret), over the VPN:

```bash
sudo cp /var/lib/caddy/.local/share/caddy/pki/authorities/local/root.crt ~/jarvis-ca.crt
cd ~ && python3 -m http.server 8080 --bind 10.8.0.1    # Ctrl+C when the phone has it
```

- **iPhone:** with the VPN on, open `http://10.8.0.1:8080/jarvis-ca.crt` in Safari → *Allow*. Then **Settings →
  Profile Downloaded → Install**. Then **Settings → General → About → Certificate Trust Settings** and switch on
  the Caddy Local Authority.
- **Android:** download the same file, then **Settings → Security → Encryption & credentials → Install a
  certificate → CA certificate**.

Delete `~/jarvis-ca.crt` afterwards.

### 5. Add Jarvis to the Home Screen

Open **https://10.8.0.1** on the phone.

- **iPhone:** in Safari, Share → **Add to Home Screen**.
- **Android:** in Chrome, menu → **Install app**.

Open Jarvis from the Home Screen, then turn on notifications in **More → Notifications**. On an iPhone this needs
iOS 16.4 or newer, and only works from the Home Screen app.

### 6. Close SSH to the internet (recommended)

Add your computer as a second WireGuard peer: repeat step 2's key and `[Peer]` part with address `10.8.0.3`, use
the WireGuard app for Mac, Windows or Linux, and restart with `sudo systemctl restart wg-quick@wg0`. Check that
`ssh ubuntu@10.8.0.1` works through the VPN, then delete the port 22 rule from Oracle's security list. After that
only WireGuard answers from the internet.

## Mac or PC on home Wi-Fi

On a Mac, install Caddy (`brew install caddy`) and adapt
[deploy/caddy/Caddyfile.example](../deploy/caddy/Caddyfile.example): put in your Mac's `.local` name and home IP
address. The file explains how the phone gets Caddy's certificate (step 4 above, from `http://your-mac.local:3080`).
Then open `https://your-mac.local:3444` on the phone and add it to the Home Screen.

Anyone on the same Wi-Fi can reach that address, and the app has no login, so use this only on a network you trust.
On shared networks use WireGuard instead (it runs on a Mac too).
