"""Long-term memory: lasting facts about the user, and short summaries of past chats.

The Hermes plugin appends each user message to a queue file (cheap, never slows a reply); this
module turns queued messages into short facts and a dated summary of each chat with a local model, embeds them, and finds the
relevant ones again before each reply. "remember ...", "forget ..." and "what do you know about
me" are handled straight away, without waiting for the queue.

Usage: jarvis-learn    process the queue (Hermes cron, nightly at 02:30; prints nothing)
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


def main() -> None:
    learn_from_queue()


if __name__ == "__main__":
    main()
