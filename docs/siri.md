# Ask Jarvis with Siri

Say **"Hey Siri, Ask Jarvis"**, then your question. Siri sends it to your Jarvis and reads the answer out. It works
from the lock screen, with AirPods and in the car. Every question is also saved as a chat in the app.

It uses a **Shortcut** on your iPhone and a **Siri key**: a long password that only lets the Shortcut ask questions.
Setting it up takes about five minutes, once.

**Before you start:** Siri can reach Jarvis only if your phone can. With a public name
([public-address.md](public-address.md)) that works anywhere. With the VPN only, it works while the VPN is on.

## 1. Make a Siri key

In the Jarvis app: **More → Siri & Shortcuts → Make a Siri key**, then **Copy the key**.

The key is shown only this once. Paste it straight into the Shortcut in the next step, not into notes or chats.

## 2. Make the Shortcut

On the same iPhone, open the **Shortcuts** app and tap **+**. Name it **Ask Jarvis**: that name is what you say to Siri.
Then add these actions, in this order:

1. **Dictate Text**: Siri listens for your question.
2. **Get Contents of URL**:
   - **URL:** your Jarvis address followed by `/api/ask`, e.g. `https://yourname.dynv6.net/api/ask`. The app shows
     yours, with a **Copy the address** button.
   - Tap the arrow to show more options.
   - **Method:** POST.
   - **Headers:** add one, with the key `Authorization`; as its value, paste your Siri key. It starts with `Bearer `.
   - **Request Body:** JSON. Add a **Text** field, with the key `text` and the value **Dictated Text** (pick it from
     the variables above the keyboard).
3. **Get Dictionary Value**: get **Value** for `reply` in **Contents of URL**.
4. **Show Result**, with **Dictionary Value**. When you use Siri, it reads this out.

## 3. Try it

Say "Hey Siri, Ask Jarvis", wait for Siri, then ask, e.g. "What's on my calendar today?" or "How much did I spend this
week?".

**Slow answers:** Siri waits up to 40 seconds. If Jarvis takes longer (a cold start, or a question that needs
several tools on a small server), Siri says the answer will come as a notification. It then arrives as **Siri
answers**, which you can switch off in **More → Notifications**. To change the wait, set `JARVIS_SIRI_WAIT` (in
seconds) in `.env` and restart the app.

## Safety

- **The key only asks questions.** It opens nothing else in Jarvis: not your screens, files or settings.
- **Only a hash of the key is kept** on the server (`secrets/siri-key`), and wrong keys slow down like wrong
  passwords.
- **To replace it** (a new phone, or if it leaked): **Make a new key** in the app and paste it into the Shortcut. The
  old one stops working at once. **Turn off the Siri key** stops all Siri questions.
- **The lock screen:** Siri runs shortcuts while the phone is locked, and it can mistake another voice for yours.
  If you'd rather nobody could ask Jarvis from your locked phone, turn off **Settings → Siri → Allow Siri When
  Locked**. The Shortcut then works once you've unlocked.

## Other apps

Any app that can send a web request can ask Jarvis the same way, e.g. *HTTP Shortcuts* or *Tasker* on Android, or a
computer. Send a POST to `/api/ask` with the header `Authorization: Bearer YOUR-KEY` and the JSON body
`{"text": "your question"}`. The answer comes back as `{"reply": "…"}`.

From a terminal, without the key showing on screen or in your history:

```bash
read -rsp "Siri key: " k; echo
curl -s https://yourname.dynv6.net/api/ask -H "Authorization: Bearer $k" -H "Content-Type: application/json" \
  -d '{"text": "What is on my calendar today?"}'
unset k
```

## When it doesn't work

| Siri says | Fix |
|---|---|
| "That Siri key isn't right" | make a new key in the app and paste it into the Shortcut again |
| "Too many wrong Siri keys" | wait the time it says; check the header value starts with `Bearer ` |
| "There was a problem with the shortcut", or nothing | check the address ends in `/api/ask`, the method is POST, and the phone can open Jarvis in Safari |
| "Jarvis is still working on that" every time | the server is slow to answer; see [troubleshooting.md](troubleshooting.md#the-first-reply-takes-minutes) |
