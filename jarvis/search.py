"""Hybrid search: vector + keyword candidates, merged by reciprocal rank fusion, then reranked.

Usage: jarvis-search "when does my car insurance expire" [--domain finance] [--limit 5]
       jarvis-search --serve   JSON lines on stdin/stdout, models stay loaded (used by the Hermes plugin)
"""
import argparse
import json
import re
import sys
from pathlib import Path
from functools import lru_cache

import numpy as np
import psycopg
from pgvector.psycopg import register_vector

from . import config
from .embed import embed

CANDIDATES = 30   # per retriever
RERANK_POOL = 20  # fused candidates sent to the reranker
RRF_K = 60

_SELECT = """
  SELECT c.id, d.path, d.domain, d.title, c.heading, c.page, c.content
  FROM chunks c JOIN documents d ON d.id = c.document_id
  WHERE (%(domain)s::text IS NULL OR d.domain = %(domain)s)
"""


# Tanglish (Tamil in English letters): the reranker reads its filler words as noise and scored
# "naan enna subscriptions ku pay panren?" far below "what subscriptions do I pay for". So question
# words become English and fillers are dropped, for ranking only.
_TANGLISH_QUESTION = {"eppo": "when", "eppadi": "how", "evlo": "how much", "evvalavu": "how much",
                      "enna": "what", "ena": "what", "yaar": "who", "yaaru": "who", "enga": "where"}
_TANGLISH_FILLER = set("""naan nan na en enaku enakku ennoda ennudaiya unga ungal la le ku kku ki kitta kitte
irundhu irunthu pathi patthi oda ah va iruka irukka irukku irukkaa irukaa iruku irundha irundhuchu
panren pannren panniruken pannen panninen pannanum pannunga panna pannu etha ethu edhu entha endha
intha indha antha andha sollu solu sollunga kaattu kaatu paaru paru venum vendum aagum aaguthu
varudhu varuthu ethavathu edhavadhu ellam ellaam konjam romba""".split())


def _ranking_query(query: str) -> str:
    words = query.split()
    out = []
    for word in words:
        bare = re.sub(r"\W", "", word.lower())
        if bare in _TANGLISH_QUESTION:
            out.append(_TANGLISH_QUESTION[bare])
        elif bare not in _TANGLISH_FILLER:
            out.append(word)
    return " ".join(out) or query


@lru_cache(maxsize=1)
def _reranker():
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    return TextCrossEncoder(config.RERANK_MODEL, cache_dir=str(config.MODELS_DIR))


def search(query: str, domain: str | None = None, limit: int = 5) -> list[dict]:
    query_vector = np.array(embed([query])[0])
    params = {"domain": domain, "vec": query_vector, "q": query, "n": CANDIDATES}
    with psycopg.connect(config.DB_DSN) as conn:
        register_vector(conn)
        vector_rows = conn.execute(_SELECT + " ORDER BY c.embedding <=> %(vec)s LIMIT %(n)s", params).fetchall()
        # OR the query words together; plainto_tsquery alone ANDs them, which misses on natural questions.
        keyword_rows = conn.execute(
            _SELECT + """ AND c.tsv @@ replace(plainto_tsquery('simple', %(q)s)::text, '&', '|')::tsquery
              ORDER BY ts_rank(c.tsv, replace(plainto_tsquery('simple', %(q)s)::text, '&', '|')::tsquery) DESC
              LIMIT %(n)s""",
            params,
        ).fetchall()

    fused: dict[int, float] = {}
    rows: dict[int, tuple] = {}
    for ranked in (vector_rows, keyword_rows):
        for rank, row in enumerate(ranked):
            fused[row[0]] = fused.get(row[0], 0.0) + 1.0 / (RRF_K + rank + 1)
            rows[row[0]] = row
    pool = [rows[i] for i in sorted(fused, key=fused.get, reverse=True)[:RERANK_POOL]]
    if not pool:
        return []

    scores = list(_reranker().rerank(_ranking_query(query), [f"{r[3]}\n{r[4] or ''}\n{r[6]}" for r in pool]))
    ranked = sorted(zip(pool, scores), key=lambda pair: pair[1], reverse=True)[:limit]
    return [
        {
            "source": row[1],
            "domain": row[2],
            "title": row[3],
            "heading": row[4],
            "page": row[5],
            "score": round(float(score), 3),
            "text": row[6],
        }
        for row, score in ranked
    ]


def list_documents(domain: str | None = None) -> list[dict]:
    with psycopg.connect(config.DB_DSN) as conn:
        rows = conn.execute(
            """SELECT d.path, d.domain, d.modified_at, count(c.id)
               FROM documents d LEFT JOIN chunks c ON c.document_id = d.id
               WHERE (%(domain)s::text IS NULL OR d.domain = %(domain)s)
               GROUP BY d.id ORDER BY d.domain, d.path""",
            {"domain": domain},
        ).fetchall()
    return [
        {"source": r[0], "domain": r[1], "modified": r[2].date().isoformat() if r[2] else None, "chunks": r[3]}
        for r in rows
    ]


def _quick_reply(message: str) -> str | None:
    """Record a short reply to a reminder directly, so it never depends on the model calling a tool."""
    from . import health, tasks

    if m := re.fullmatch(r"\s*clean\s*up((?:[\s,#]+\d+)*)\s*[.!]?\s*", message or "", re.I):
        from . import learn  # the weekly memory clean-up, approved by the user's own reply

        return learn.apply_review([int(n) for n in re.findall(r"\d+", m[1])] or None)
    if re.fullmatch(r"\s*(sync|refresh|update)\s+(my\s+)?(google\s+)?drive(\s+folder)?\s*[.!]?\s*", message or "", re.I):
        return _start_drive_sync()
    if m := re.fullmatch(r"\s*restore\s*#?(\d+)\s*[.!]?\s*", message or "", re.I):
        from . import learn

        return learn.restore_fact(int(m[1]))
    m = re.fullmatch(r"\s*(taken|took|skip|skipped|done)\s*#?(\d+)\s*[.!]?\s*", message or "", re.I)
    if not m:
        return None
    word, number = m[1].lower(), int(m[2])
    try:
        if word == "done":
            task = tasks.update_task(number, status="done")
            return f"Task #{number} \"{task['title']}\" marked done."
        dose = health.mark_dose(number, "taken" if word in ("taken", "took") else "skipped")
        return f"Dose #{number} ({dose['name']} {dose['dose'] or ''}, due {dose['due']}) marked {dose['status']}."
    except ValueError as error:
        return f"Could not record that: {error}"


def _start_drive_sync() -> str:
    """Copy the Drive folder in the background (it can take minutes); the result arrives in Activity."""
    import subprocess

    bin_dir = Path(sys.executable).parent
    subprocess.Popen(f'"{bin_dir}/jarvis-drive-sync" | "{bin_dir}/jarvis-notify" reports --one', shell=True,
                     start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return ("Started syncing the Google Drive folder \"Jarvis\". New and changed files become searchable in a minute "
            "or two; the result will appear in Activity.")


def serve() -> None:
    """One request per line: {"id", "query", "domain", "limit"} -> {"id", "results": [...]} or {"id", "error"}.
    The id is echoed so a client that timed out can discard the late reply."""
    for line in sys.stdin:
        request: dict = {}
        try:
            request = json.loads(line)
            if request.get("op") == "email":  # read-only Gmail lookup for the plugin's prefetch
                from .mail import list_messages

                reply = {"id": request.get("id"), "results": list_messages(request["query"], int(request.get("limit", 5)))}
                sys.stdout.write(json.dumps(reply) + "\n")
                sys.stdout.flush()
                continue
            if request.get("op") == "reply":  # "taken 12" / "skip 12" / "done 5" answered to a reminder
                reply = {"id": request.get("id"), "results": _quick_reply(request.get("message", ""))}
                sys.stdout.write(json.dumps(reply, default=str) + "\n")
                sys.stdout.flush()
                continue
            if request.get("op") == "medicines":  # medicine list for a medicine question, for the plugin's prefetch
                from . import health

                asks = re.search(r"\b(medicines?|medications?|tablets?|pills?|doses?|supplements?|vitamins?|meds)\b"
                                 # Tamil and Tanglish ("mathirai", "marunthu"); no \b inside Tamil script
                                 r"|\b(maa?th?irai|marun[dt]h?u)|மாத்திரை|மருந்து|டேப்லெட்|வைட்டமின்",
                                 request.get("message", ""), re.I)
                reply = {"id": request.get("id"), "results": {
                    "medicines": [f"#{m['id']} {m['name']} {m['dose'] or ''} at {', '.join(m['times'])} "
                                  f"({'daily' if m['weekdays'] is None else 'days ' + ','.join('MTWTFSS'[d] for d in m['weekdays'])})"
                                  for m in health.list_medications()],
                    "today": health.doses_today(), "last_7_days": health.adherence(7)} if asks else None}
                sys.stdout.write(json.dumps(reply, default=str) + "\n")
                sys.stdout.flush()
                continue
            if request.get("op") == "attachments":  # files sent on Telegram: save into ~/Jarvis and index
                from .ingest import save_attachments

                reply = {"id": request.get("id"), "results": save_attachments(request.get("message", ""))}
                sys.stdout.write(json.dumps(reply, default=str) + "\n")
                sys.stdout.flush()
                continue
            if request.get("op") == "calendar":  # the agenda for a calendar question, for the plugin's prefetch
                from .calendars import agenda_for_text

                reply = {"id": request.get("id"), "results": agenda_for_text(request.get("message", ""))}
                sys.stdout.write(json.dumps(reply, default=str) + "\n")
                sys.stdout.flush()
                continue
            if request.get("op") == "money":  # exact totals for a money question, for the plugin's prefetch
                from .money import insights, period_from_text, summary

                period = period_from_text(request.get("message", ""))
                result = summary(*period) if period else None
                if result and period[0] != period[1]:
                    # "How much on food this month?": the plugin prints the note line, so categories ride on it.
                    cats = insights(*period)["by_category"]
                    result["note"] += "\nBy category (guessed from merchant names): " + "; ".join(
                        f"{c['category']} ₹{c['total']:,.2f} ({c['payments']} payments)" for c in cats)
                reply = {"id": request.get("id"), "results": result}
                sys.stdout.write(json.dumps(reply, default=str) + "\n")
                sys.stdout.flush()
                continue
            if request.get("op") in ("memory", "recall"):  # long-term facts, for the plugin's turn start and prefetch
                from . import learn

                message = request.get("message", "")
                results = learn.memory_command(message) if request["op"] == "memory" else learn.recall(message)
                sys.stdout.write(json.dumps({"id": request.get("id"), "results": results}) + "\n")
                sys.stdout.flush()
                continue
            if request.get("op") == "approve":  # the user's raw message, sent by the Hermes plugin
                from .pending import approve_from_user_message

                reply = {"id": request.get("id"), "approved": approve_from_user_message(request.get("message", ""))}
                sys.stdout.write(json.dumps(reply) + "\n")
                sys.stdout.flush()
                continue
            domain = request.get("domain") if request.get("domain") in config.DOMAINS else None
            reply = {"id": request.get("id"), "results": search(request["query"], domain, int(request.get("limit", 5)))}
        except Exception as error:  # report and keep serving
            reply = {"id": request.get("id"), "error": f"{type(error).__name__}: {error}"}
        sys.stdout.write(json.dumps(reply) + "\n")
        sys.stdout.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("query", nargs="?")
    parser.add_argument("--domain", choices=config.DOMAINS)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--serve", action="store_true")
    args = parser.parse_args()
    if args.serve:
        serve()
        return
    if not args.query:
        parser.error("a query is required unless --serve is given")
    for hit in search(args.query, args.domain, args.limit):
        location = f" p.{hit['page']}" if hit["page"] else ""
        print(f"[{hit['score']:>7}] {hit['source']}{location} :: {hit['heading'] or ''}")
        print("          " + hit["text"][:200].replace("\n", " "))


if __name__ == "__main__":
    main()
