# Contributing

Thanks for helping. Bug reports, ideas, new bank readers, translations of the docs and fixes are all welcome.

## Reporting a bug

Open an issue with what you did, what you expected and what happened, plus your machine (Mac or Linux, memory) and
the output of `systemctl status jarvis-hermes jarvis-web` or the relevant log in `~/jarvis-system/logs`.
**Remove personal data** (names, amounts, account numbers, email text) before posting. Security problems go
privately: see [SECURITY.md](SECURITY.md).

## Working on the code

```bash
git clone https://github.com/GuruGd29/jarvis-assistant.git ~/jarvis-system && cd ~/jarvis-system
./install.sh                                   # or docs/install-mac.md
.venv/bin/python -m unittest discover tests   # fast checks; no database, network or model needed
```

- `jarvis/` is the Python package, `web/app/` the phone app, `hermes/` the plugin, persona and job scripts that
  `bin/apply-settings.sh` copies into Hermes. Edit them here, never in `~/.hermes`.
- After changing Python code, restart: `sudo systemctl restart jarvis-hermes jarvis-web` (Linux), or
  `hermes gateway restart` and `launchctl kickstart -k gui/$(id -u)/com.jarvis.web` (Mac).
- Database changes go in a new numbered file in `sql/` that only adds (`CREATE ... IF NOT EXISTS`, `ADD COLUMN IF
  NOT EXISTS`), so `jarvis-migrate` can run on every update.
- Anything that depends on where a person lives (money, dates, names, languages) goes through `jarvis/config.py`
  settings, never hard-coded.

### Style

Match the code around you: short functions, plain names, and a comment only where the *why* isn't obvious.
Money is always computed in code or SQL, never by the model. Anything that changes something outside Jarvis (a
calendar, an email) needs the user's explicit yes.

### Tests

- Add a unit test in `tests/test_parsing.py` for every rule you add or fix. Use **made-up data only**: no real
  emails, names or amounts.
- The end-to-end cases are in `tests/ci/run_tests.py`, with fake data in `tests/ci/seed.py`. They run every week on
  GitHub; you can start a run from the Actions tab of your fork.

## Adding a bank

Banks without a built-in reader already work through the AI reader ([docs/money.md](docs/money.md)), but a built-in
reader is exact and instant.

1. Add the bank's sender to `BUILT_IN_SENDERS` in `jarvis/money.py` and a branch in `parse_alert()` with a regular
   expression per alert type (debit, credit, card purchase, refund...). Return the same fields as the existing
   branches: `bank`, `instrument` (`"BANK a/c 1234"`, `"BANK card 1234"` or `"BANK debit card 1234"`), `kind`,
   `direction`, `amount`, `counterparty`, `occurred_on`, `reference`.
2. If the bank emails card statements, extend `parse_statement()`.
3. Add tests with a made-up email for each alert type.

## Pull requests

- One change per pull request, with a clear description of what and why.
- `python -m unittest discover tests` passes.
- No secrets, personal data or real screenshots. The screenshots in `docs/screenshots/` use made-up data.
- By contributing you agree that your work is released under the [MIT licence](LICENSE).
