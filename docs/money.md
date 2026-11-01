# Money from bank alert emails

Most banks email you after every payment ("Rs. 450 debited from your account ending 1234 at ZOMATO"). Jarvis reads
those alerts from Gmail, every 30 minutes, into a table of transactions. Totals are then **added up by the database,
not by the AI**, so "How much did I spend this week?" gets an exact answer, and the app's **Money** screen shows
spending by day, week, month and category.

You need [Google connected](google.md) first. All of this stays on your machine.

## 1. Tell Jarvis about your banks

Create `~/jarvis-system/secrets/money.json`:

```json
{
  "alert_senders": ["alerts@yourbank.example", "creditcards@yourbank.example"],
  "own_names": ["priya sharma"],
  "own_account_suffixes": ["1234", "5678"]
}
```

| Key | What to put |
|---|---|
| `alert_senders` | The **From** address of each kind of alert email from your bank(s). Open one alert in Gmail and copy the sender's address exactly. Banks often use different addresses for accounts and cards. |
| `own_names` | Your name as it appears in transfers, in lower case. Money you move between your own accounts isn't counted as spending. |
| `own_account_suffixes` | The last 4 digits of your own accounts, for the same reason. |

Then read the last 90 days once (later runs read only new emails):

```bash
~/jarvis-system/.venv/bin/jarvis-money-sync --days 90 --verbose
```

## 2. Which banks are understood

**Built-in readers (exact, instant):** HDFC Bank, ICICI Bank and IDFC FIRST Bank (India). These cover account
debits and credits (UPI, IMPS, deposits), debit and credit card purchases, refunds, card bill payments, and the
credit card statement emails with bill amount and due date (ICICI and IDFC; HDFC sends statements only as a
password-protected PDF).

**Every other bank: read by the local AI.** An email from one of your `alert_senders` that no built-in reader
understands goes to the chat model with a fixed form to fill in: is it a payment, how much, which currency, debit or
credit, which card or account, the merchant, the date. Jarvis then checks the answer before saving anything:

- the amount must appear in the email **exactly as the AI copied it**, so a made-up number is never stored;
- the currency must be yours (`JARVIS_CURRENCY`); foreign-currency charges aren't counted;
- offers, OTPs, login alerts and declined payments are dropped;
- a date far from the email's own date is replaced by the email's date.

Each email is read once and the outcome is remembered, so nothing is read twice. In the weekly tests the AI reader
handles 8 made-up emails from SBI, Kotak, Axis and Chase correctly (see the *Money AI* cases).

**When the AI reads them** is the `JARVIS_MONEY_AI` setting in `.env`:

| Value | Effect |
|---|---|
| `nightly` (default) | Read at 2:15 am. While the AI reads, your current chat drops out of the model's memory, which costs minutes on a CPU server, so night is best. Totals for these banks can be up to a day behind. |
| `always` | Read on every 30-minute sync. Fine on a fast Mac; on a slow server the next chat reply can be slower. |
| `off` | Only the built-in readers are used. |

Run it by hand any time: `~/jarvis-system/.venv/bin/jarvis-money-sync --ai --days 7 --verbose`.

## 3. How totals are counted

- **Spending** = money out of your accounts and cards, minus refunds, without transfers between your own accounts.
- **Credit cards count when you pay the bill**, not per purchase, so nothing is counted twice. Card purchases are
  shown separately, and on the **Cards** screen: each card's latest bill, the part payments you've made towards it,
  what's left, the due date, and the purchases since the statement (they go on the next bill).
- **Categories** (food, groceries, travel, bills, health…) are guessed from the merchant's name. "Unusually large"
  means among your largest 5% of payments and at least 10 times your usual payment, so it works in any currency.

Cash, and payments your bank doesn't email you about, aren't included. Jarvis says so when you ask.

## Add a built-in reader for your bank

A built-in reader is faster than the AI and works at any hour. If you know a little Python, add a branch to
`parse_alert()` in `jarvis/money.py` with a regular expression for your bank's alert text, plus a test in
`tests/test_parsing.py` with a real-looking (made-up) email. See [CONTRIBUTING.md](../CONTRIBUTING.md); pull
requests for more banks are very welcome.
