# Testing

Jarvis is tested in three ways:

1. **Unit tests** check the rules in the code in seconds.
2. **The weekly test run** installs the whole thing from scratch and asks the real AI real questions.
3. **Checks on your own install** confirm it works on your machine.

Everything uses made-up data. No real emails, names or amounts are ever in the tests.

## 1. Unit tests

These are the rules that are easy to break quietly: reading bank emails, money totals and card bills, number and date
styles, renewals, the filter for instructions hidden in files, sign-in, the server's address checks, watches, voice
and file handling. There are about 100 of them, in `tests/test_*.py`.

Run them on any machine where Jarvis is installed:

```bash
cd ~/jarvis-system && .venv/bin/python -m unittest discover tests
```

They take a few seconds and need no model or internet. The tests in `test_api.py` call the running app server. They
are skipped when it isn't running, or when it asks for a sign-in (they need one without, as in the weekly run).

| File | What it covers |
|---|---|
| `test_parsing.py` | bank alert emails, amounts, dates, spending rules, card bills, renewals, number styles |
| `test_login.py` | the app's sign-in: password, Google, cookies, guessing limits, public addresses |
| `test_server_guard.py` | the app answers only to its own addresses and refuses requests from other websites |
| `test_plugin_notes.py` | the notes Jarvis adds for Tamil and Tanglish messages |
| `test_watches.py` | understanding watch requests ("bus from X to Y on Friday under ₹500") |
| `test_files.py`, `test_voice.py` | adding files, text recognition, voice messages |
| `test_api.py` | every app screen's data and the security headers, against the running app |

## 2. The weekly test run

Every Sunday at 2:00 am India time, GitHub Actions runs `.github/workflows/weekly-tests.yml` on a free ARM64 machine
set up like Oracle's free server, with the model limited to 2 cores. It:

1. Installs Jarvis with the real `install.sh`, from nothing.
2. Fills it with made-up data: documents in English and Tamil, bank emails, tasks, medicines (`tests/ci/seed.py`).
3. Checks the server scripts: the VPN, HTTPS, copying the database, and updates that roll themselves back when broken
   (`tests/ci/server-check.sh`).
4. Runs the unit tests.
5. Runs **46 test cases** against the real Hermes and Qwen3.5 model (`tests/ci/run_tests.py`):

| Category | Cases | What it checks |
|---|---|---|
| Functional | 8 | bank email parsing, spending rules, card bills, periods, categories, Drive paths |
| Search | 3 | English, Tamil and Tanglish document search |
| API | 5 | every app screen's data, security headers |
| Server jobs | 2 | the morning brief and every scheduled job run cleanly with nothing connected |
| Chatbot | 14 | greetings, maths, document facts, exact money, tasks, memory, Tamil, Tanglish, a poem, a refusal |
| Hallucination | 4 | unknown facts, missing documents, false premises, unknown people |
| Security | 2 | instructions hidden in a document, leaking the instructions Jarvis runs on |
| Consistency | 2 | the same question in three chats: same facts, at least 80% similar wording |
| Performance | 4 | median and slowest reply, time to first words, empty replies |
| Money AI | 2 | the AI bank reader on 8 made-up emails from banks without a built-in reader |

Each case records its ID, name, precondition, steps, expected and actual result, and a match percentage.

**Reading the results:** open the [Weekly tests](https://github.com/GuruGd29/jarvis-assistant/actions/workflows/weekly-tests.yml)
page and pick a run.

- The table of cases is on the run page.
- **jarvis-test-report** under *Artifacts* has the full HTML and CSV report, the logs, and the memory use with every
  model loaded.
- A small model doesn't answer the same way every time, so a case can fail one week and pass the next. The report
  says what was expected and what came back.

**Running it yourself:**

1. Fork the repository on GitHub.
2. In the fork's **Actions** tab, click **I understand my workflows, go ahead and enable them** (GitHub turns
   Actions off on new forks).
3. Go to **Actions → Weekly tests → Run workflow**.
4. Optionally, type case IDs (e.g. `CB-06,HL-03`) to run only those.

A full run takes 1.5–2 hours, and it's free on public repositories.

## 3. Checks on your own install

After installing, or whenever something seems wrong:

```bash
curl -s http://127.0.0.1:8791/api/health        # {"ok": true, "database": "ok", "hermes": "ok", "ollama": "ok"}
~/jarvis-system/.venv/bin/jarvis-auth status     # which calendars are connected, and how the app signs in
systemctl status jarvis-hermes jarvis-web ollama # on a server: all "active (running)"
```

Then try a few questions in the app:

| Ask | You should get |
|---|---|
| "Hi" | a greeting, in a few seconds once warm |
| "Remind me to call the plumber tomorrow at 10" | a confirmation; the task appears on **Today** |
| "What's on my calendar today?" | your events, once Google or iCloud is connected |
| "How much did I spend this week?" | an exact total, once [money](money.md) is set up |
| A question about a document in `~/Jarvis` | the answer, with the file's name |

Every 20 minutes the keep-warm job runs the health check and tells you if something stops.

## Adding tests

Change a rule? Add a unit test next to the others, with made-up data only. New end-to-end cases go in
`tests/ci/run_tests.py`, and their fake data in `tests/ci/seed.py`. See [CONTRIBUTING.md](../CONTRIBUTING.md).
