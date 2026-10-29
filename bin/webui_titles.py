"""Give untitled Open WebUI chats a short title, at night.

Runs inside the open-webui container (it owns the database): see ~/.hermes/scripts/jarvis-webui-titles.sh.
Open WebUI's own instant titles load another model, which unloads Jarvis's and slows the next reply,
so they are off and this names chats once they have been quiet for 30 minutes. Prints nothing on success.
"""
import json
import sqlite3
import time
import urllib.request

DB = "/app/backend/data/webui.db"
OLLAMA = "http://host.docker.internal:11434/api/generate"
MODEL = "qwen3-4b-instruct-64k"  # Jarvis's own model, so nothing else is loaded
QUIET_SECONDS = 30 * 60


def first_messages(chat: dict) -> list[tuple[str, str]]:
    messages = chat.get("messages") or list((chat.get("history") or {}).get("messages", {}).values())
    return [(m.get("role", ""), str(m.get("content", ""))[:500]) for m in messages[:4]]


def needs_title(title: str, messages: list[tuple[str, str]]) -> bool:
    first_user = next((text for role, text in messages if role == "user"), "")
    return title in ("", "New Chat") or (bool(first_user) and first_user.strip().startswith(title.strip()))


def make_title(messages: list[tuple[str, str]]) -> str:
    chat = "\n".join(f"{role.upper()}: {text}" for role, text in messages)
    body = json.dumps({"model": MODEL, "stream": False, "keep_alive": "2h", "options": {"temperature": 0},
                       "prompt": "Write a 2-5 word title for this chat. Reply with the title only, no quotes.\n\n" + chat})
    request = urllib.request.Request(OLLAMA, body.encode(), {"Content-Type": "application/json"})
    title = json.load(urllib.request.urlopen(request, timeout=300))["response"].strip().strip('"').splitlines()[0]
    return title[:60]


def main() -> None:
    db = sqlite3.connect(DB)
    cutoff = int(time.time()) - QUIET_SECONDS
    rows = db.execute("SELECT id, title, chat FROM chat WHERE updated_at < ? AND archived = 0 "
                      "ORDER BY updated_at DESC LIMIT 50", (cutoff,)).fetchall()
    for chat_id, title, chat in rows:
        data = json.loads(chat or "{}")
        messages = first_messages(data)
        if messages and needs_title(title or "", messages):
            data["title"] = make_title(messages)
            # Leave updated_at alone so the chat keeps its place in the sidebar.
            db.execute("UPDATE chat SET title = ?, chat = ? WHERE id = ?", (data["title"], json.dumps(data), chat_id))
            db.commit()


if __name__ == "__main__":
    main()
