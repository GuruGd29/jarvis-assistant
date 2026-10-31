"""Long-term memory: lasting facts about the user, and short summaries of past chats.

The Hermes plugin appends each user message to a queue file (cheap, never slows a reply); this
module turns queued messages into short facts and a dated summary of each chat with a local model, embeds them, and finds the
relevant ones again before each reply. "remember ...", "forget ..." and "what do you know about
me" are handled straight away, without waiting for the queue.

Usage: jarvis-learn            process the queue (Hermes cron, nightly at 02:30; prints nothing)
       jarvis-memory-review    weekly: suggest facts to archive; nothing changes until the user replies
                               "clean up" (or "clean up 3 7"); "restore 12" brings one back
"""
import json
import re
from datetime import datetime

import httpx
import numpy as np
import psycopg
from pgvector.psycopg import register_vector

from . import config
from .embed import embed

QUEUE = config.SYSTEM_DIR / "state" / "learn-queue.jsonl"
# Jarvis's own chat model, run at night: loading any other model makes Ollama unload the chat
# model, and the extraction wipes its prompt cache, so the next reply would take about a minute.
EXTRACT_MODEL = "qwen3-4b-instruct-64k"
# Cosine distances between bge-m3 vectors of short facts.
SAME_FACT = 0.17      # a restatement: refresh the existing fact instead of adding a copy
RELEVANT = 0.45       # recalled before a reply
FORGET_MATCH = 0.40   # removed by "forget ..."
MAX_RECALL = 5
MAX_EPISODES = 2      # past-chat summaries recalled per reply

# Never store secrets or identifiers, even if the user typed them.
_SENSITIVE = re.compile(r"\b(passwords?|passcode|otp|pin|cvv|api[ -]?key|token)\b|\d{9,}", re.I)
# "remember to ..." is a reminder for the task tools, not a fact.
_REMEMBER = re.compile(r"^\s*(?:please\s+)?(?:remember|note)\s+(?!to\b|me\b)(?:that\s+)?(.{4,})$", re.I | re.S)
_FORGET = re.compile(r"^\s*(?:please\s+)?forget\s+(?!it\b)(?:that\s+|about\s+)?(.{3,})$", re.I | re.S)
_ONE_DAY = re.compile(r"\b(today|tonight|tomorrow|yesterday|this (morning|afternoon|evening))\b", re.I)
_ASK_ALL = re.compile(r"\bwhat (?:do|did) you (?:know|remember) about me\b|\bwhat have you (?:learned|learnt)\b", re.I)

_EXTRACT_PROMPT = """You maintain a personal assistant's long-term memory about its user.
Below is part of a chat: USER lines are the user's messages, JARVIS lines the assistant's replies.

1. "facts": LASTING facts about the user, taken only from USER lines, that will still be true next
   month: people in their life, preferences, routines, health conditions or allergies, vehicles,
   home, work, goals, accounts or providers they use. One short sentence each, starting with "User"
   (e.g. "User's GP is Dr. Rao."). Ignore questions, greetings and anything about today only.
2. "summary": one or two sentences on what the user wanted and what was found, decided or left
   open, useful context for a later chat (e.g. "User compared two health insurance plans and chose
   Star Health; still has to upload the ID proof."). Use "" for greetings or small talk only.

The chat took place on {day}. Keep relative dates ("next Friday") exactly as the user wrote them
and add "(said on {day})"; never calculate dates yourself.
Never include passwords, PINs, OTPs or long numbers.
Reply as JSON: {{"facts": ["..."], "summary": "..."}}

Chat:
"""



def _connect() -> psycopg.Connection:
    conn = psycopg.connect(config.DB_DSN)
    register_vector(conn)
    return conn


def remember(fact: str, source: str = "chat", kind: str = "fact") -> str:
    """Store a fact (or chat summary), or refresh an existing one that says the same thing. Returns what happened."""
    fact = " ".join(fact.split()).rstrip(".") + "."
    if _SENSITIVE.search(fact):
        return "not stored (looks like a secret or an account number)"
    vector = np.array(embed([fact])[0])
    with _connect() as conn:
        row = conn.execute("SELECT id, embedding <=> %s FROM facts WHERE embedding IS NOT NULL AND kind = %s "
                           "ORDER BY 2 LIMIT 1", (vector, kind)).fetchone()
        if row and row[1] < SAME_FACT:
            conn.execute("UPDATE facts SET fact = %s, embedding = %s, source = %s, updated_at = now() WHERE id = %s",
                         (fact, vector, source, row[0]))
            return f"updated #{row[0]}: {fact}"
        new_id = conn.execute("INSERT INTO facts (fact, source, embedding, kind) VALUES (%s, %s, %s, %s) RETURNING id",
                              (fact, source, vector, kind)).fetchone()[0]
    return f"saved #{new_id}: {fact}"


def forget(text: str) -> list[str]:
    """Delete the facts that match text; returns the deleted facts."""
    vector = np.array(embed([text])[0])
    with _connect() as conn:
        rows = conn.execute("DELETE FROM facts WHERE embedding <=> %s < %s RETURNING fact",
                            (vector, FORGET_MATCH)).fetchall()
    return [r[0] for r in rows]


def recall(query: str, limit: int = MAX_RECALL) -> list[str]:
    """Facts and past-chat summaries related to query, closest first."""
    vector = np.array(embed([query])[0])
    found = []
    with _connect() as conn:
        for kind, label, most in (("fact", "", limit), ("episode", "earlier chat: ", MAX_EPISODES)):
            rows = conn.execute("SELECT fact, updated_at FROM facts WHERE kind = %s AND embedding <=> %s < %s "
                                "ORDER BY embedding <=> %s LIMIT %s", (kind, vector, RELEVANT, vector, most)).fetchall()
            found += [f"({r[1]:%d %b %Y}) {label}{r[0]}" for r in rows]
    return found


def all_facts() -> list[str]:
    with _connect() as conn:
        rows = conn.execute("SELECT id, fact, updated_at FROM facts WHERE kind = 'fact' "
                            "ORDER BY updated_at DESC LIMIT 60").fetchall()
    return [f"#{r[0]} ({r[2]:%d %b %Y}) {r[1]}" for r in rows]


def memory_command(message: str) -> str | None:
    """Handle "remember ...", "forget ..." and "what do you know about me" from the user's own text."""
    if m := _REMEMBER.match(message or ""):
        return f"[Jarvis memory: {remember('User said: ' + m[1].strip(), 'told directly')} Confirm briefly.]"
    if m := _FORGET.match(message or ""):
        gone = forget(m[1].strip())
        if not gone:
            return "[Jarvis memory: nothing stored matched that, so nothing was deleted. Say so.]"
        return "[Jarvis memory: deleted these facts; confirm them to the user:]\n" + "\n".join(f"- {f}" for f in gone)
    if _ASK_ALL.search(message or ""):
        facts = all_facts()
        return ("[Jarvis memory: everything Jarvis has learned about the user, newest first. Summarise it; "
                "the user can say \"forget ...\" to remove any of it.]\n"
                + ("\n".join(f"- {f}" for f in facts) or "- nothing yet"))
    return None


def _extract(entries: list[dict], day) -> tuple[list[str], str]:
    text = "\n".join(f"USER: {e['text']}" + (f"\nJARVIS: {e['reply']}" if e.get("reply") else "") for e in entries)
    response = httpx.post(f"{config.OLLAMA_URL}/api/generate", timeout=300, json={
        "model": EXTRACT_MODEL, "prompt": _EXTRACT_PROMPT.format(day=f"{day:%A %d %B %Y}") + text, "format": "json", "stream": False,
        "keep_alive": "2h", "options": {"temperature": 0},  # the model's own num_ctx, so it is not reloaded
    })
    response.raise_for_status()
    found = json.loads(response.json()["response"])
    # "User has a dental appointment tomorrow" is about one day, not a lasting fact, and turns false
    # by the next one; the calendar and tasks hold such things.
    facts = [f for f in found.get("facts", []) if isinstance(f, str) and 8 <= len(f) <= 200
             and not _ONE_DAY.search(f)]
    summary = found.get("summary") if isinstance(found.get("summary"), str) else ""
    return facts, summary.strip()[:400]


def learn_from_queue() -> None:
    if not QUEUE.exists() or not QUEUE.stat().st_size:
        return
    batch = QUEUE.with_suffix(".processing")
    if not batch.exists():  # a batch left by a failed run is retried before new messages
        QUEUE.rename(batch)
    entries = [json.loads(line) for line in batch.read_text().splitlines() if line.strip()]
    chats: dict[tuple, list[dict]] = {}  # one summary per chat per day
    for e in entries:
        if not _SENSITIVE.search(e["text"]):
            chats.setdefault((e.get("session"), datetime.fromtimestamp(e.get("at", 0)).date()), []).append(e)
    for (_, day), chat in chats.items():
        for start in range(0, len(chat), 20):
            part = chat[start:start + 20]
            facts, summary = _extract(part, day)
            for fact in facts:
                remember(fact, f"learned {day}")
            # Greetings and one-line lookups are not worth a summary of their own.
            substantial = sum(len(e["text"]) >= 30 for e in part) >= 1 and len(part) >= 2
            if summary and substantial and not _SENSITIVE.search(summary):
                remember(summary, f"chat {day}", kind="episode")
    batch.unlink()


# --- Weekly clean-up: suggested by the model, applied only after the user agrees -----------------
REVIEW_FILE = config.SYSTEM_DIR / "state" / "memory-review.json"
REVIEW_VALID_DAYS = 7
MAX_SHARE_REMOVED = 0.4   # never suggest removing more than this share of all facts at once

_REVIEW_PROMPT = """Below are facts a personal assistant remembers about its user, oldest first, as
"#id (date) fact". Choose the ones to REMOVE:
- duplicates or near-duplicates (keep the newer or more complete one, remove the other);
- facts contradicted by a newer fact;
- vague facts that say nothing concrete about the user (e.g. "User asked about X",
  "User is concerned about someone");
- one-time things that are over (e.g. an appointment on a past day).
KEEP everything concrete and lasting: people, preferences, health, accounts, vehicles, routines.
Give each reason in 2-5 words. Reply as JSON: {{"remove": [{{"id": 12, "reason": "duplicate of #15"}}]}},
or {{"remove": []}}.

Facts:
{facts}
"""


def review_memory() -> list[dict]:
    """Ask the model which facts to archive; saves the suggestion for the user's "clean up" reply."""
    with _connect() as conn:
        rows = conn.execute("SELECT id, fact, updated_at FROM facts WHERE kind = 'fact' ORDER BY updated_at").fetchall()
    if len(rows) < 5:
        return []
    by_id = {r[0]: r[1] for r in rows}
    listing = "\n".join(f"#{r[0]} ({r[2]:%d %b %Y}) {r[1]}" for r in rows)
    response = httpx.post(f"{config.OLLAMA_URL}/api/generate", timeout=600, json={
        "model": EXTRACT_MODEL, "prompt": _REVIEW_PROMPT.format(facts=listing), "format": "json",
        "stream": False, "keep_alive": "2h", "options": {"temperature": 0}})
    response.raise_for_status()
    picked = json.loads(response.json()["response"]).get("remove", [])
    suggestions, seen = [], set()
    for item in picked if isinstance(picked, list) else []:
        fact_id = item.get("id") if isinstance(item, dict) else None
        if isinstance(fact_id, int) and fact_id in by_id and fact_id not in seen:
            seen.add(fact_id)
            suggestions.append({"id": fact_id, "fact": by_id[fact_id], "reason": str(item.get("reason", ""))[:80]})
    for fact_id, fact in by_id.items():  # one-day facts are always suggested
        if fact_id not in seen and _ONE_DAY.search(fact):
            suggestions.append({"id": fact_id, "fact": fact, "reason": "about one day only"})
    suggestions = suggestions[:max(1, int(len(rows) * MAX_SHARE_REMOVED))]
    REVIEW_FILE.write_text(json.dumps({"made": datetime.now().isoformat(), "suggestions": suggestions}))
    return suggestions


def weekly_review() -> None:
    """Hermes cron: the suggestion as a Telegram message; prints nothing when memory is tidy."""
    suggestions = review_memory()
    if not suggestions:
        return
    lines = [f"🧹 Memory clean-up: {len(suggestions)} fact{'s' if len(suggestions) != 1 else ''} look outdated or duplicated"]
    lines += [f"  #{s['id']} {s['fact']} ({s['reason']})" for s in suggestions]
    lines.append('\nReply "clean up" to archive all of them, "clean up 12 15" for only some, or ignore this to keep '
                 'everything. Archived facts can come back with "restore 12".')
    print("\n".join(lines))


def apply_review(ids: list[int] | None = None) -> str:
    """Archive the suggested facts (all, or only `ids`); only facts in this week's suggestion qualify."""
    if not REVIEW_FILE.exists():
        return "There is no memory clean-up waiting."
    review = json.loads(REVIEW_FILE.read_text())
    if (datetime.now() - datetime.fromisoformat(review["made"])).days > REVIEW_VALID_DAYS:
        return "That memory clean-up suggestion has expired; a new one comes on Sunday."
    allowed = {s["id"]: s["reason"] for s in review["suggestions"]}
    chosen = [i for i in (ids or list(allowed)) if i in allowed]
    if not chosen:
        return "None of those numbers were in this week's clean-up list."
    with _connect() as conn:
        for fact_id in chosen:
            conn.execute("""INSERT INTO facts_archive (id, fact, source, kind, embedding, created_at, updated_at, reason)
                            SELECT id, fact, source, kind, embedding, created_at, updated_at, %s FROM facts WHERE id = %s
                            ON CONFLICT (id) DO NOTHING""", (allowed[fact_id], fact_id))
            conn.execute("DELETE FROM facts WHERE id = %s", (fact_id,))
    remaining = [s for s in review["suggestions"] if s["id"] not in chosen]
    if remaining:
        REVIEW_FILE.write_text(json.dumps({**review, "suggestions": remaining}))
    else:
        REVIEW_FILE.unlink()
    return f"Archived {len(chosen)} fact{'s' if len(chosen) != 1 else ''}: " + ", ".join(f"#{i}" for i in chosen) \
        + '. Say "restore <number>" to bring one back.'


def restore_fact(fact_id: int) -> str:
    with _connect() as conn:
        row = conn.execute("SELECT fact FROM facts_archive WHERE id = %s", (fact_id,)).fetchone()
        if not row:
            return f"No archived fact #{fact_id}."
        conn.execute("""INSERT INTO facts (id, fact, source, kind, embedding, created_at, updated_at)
                        SELECT id, fact, source, kind, embedding, created_at, updated_at FROM facts_archive WHERE id = %s
                        ON CONFLICT (id) DO NOTHING""", (fact_id,))
        conn.execute("DELETE FROM facts_archive WHERE id = %s", (fact_id,))
    return f"Restored #{fact_id}: {row[0]}"


def main() -> None:
    learn_from_queue()


if __name__ == "__main__":
    main()
