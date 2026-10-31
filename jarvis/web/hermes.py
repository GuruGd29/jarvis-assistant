"""Chats from the app, kept by Hermes through its Sessions API (the same agent Telegram uses)."""
import json
import os
from collections.abc import AsyncIterator
from pathlib import Path

import httpx

HERMES = os.environ.get("JARVIS_HERMES_URL", "http://127.0.0.1:8642")

# Shown above a reply as "✓ <label>"; anything not listed gets a generic label.
TOOL_LABELS = {
    "calendar_agenda": "Checked your calendars", "propose_calendar_event": "Prepared a calendar event",
    "confirm_calendar_event": "Added the event", "search_personal_docs": "Searched your files",
    "list_personal_docs": "Listed your files", "spending_summary": "Read your bank alerts",
    "spending_insights": "Read your bank alerts", "upcoming_renewals": "Checked bills & renewals",
    "email_inbox": "Checked your email", "email_read": "Read an email", "list_tasks": "Checked your tasks",
    "add_task": "Added a task", "update_task": "Updated a task", "snooze_reminder": "Snoozed a reminder",
    "iphone_reminders": "Read your iPhone Reminders", "add_medicine": "Added a medicine",
    "stop_medicine": "Stopped a medicine", "lab_results": "Checked your lab results",
    "add_lab_result": "Saved a lab result", "web_search": "Searched the web", "web_extract": "Read a web page",
    "memory": "Updated memory", "session_search": "Searched past chats",
    "skill_view": "Used a saved skill", "skills_list": "Looked at saved skills", "skill_manage": "Saved a skill",
}


def tool_label(name: str) -> str:
    short = name.rsplit("__", 1)[-1]
    return TOOL_LABELS.get(short, "Used a tool")


def _key() -> str:
    env = Path.home() / ".hermes" / ".env"
    for line in env.read_text().splitlines():
        if line.startswith("API_SERVER_KEY="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError("API_SERVER_KEY is not set in ~/.hermes/.env")


def _headers() -> dict:
    return {"Authorization": f"Bearer {_key()}", "Content-Type": "application/json"}


async def create_session() -> str:
    # No title: Hermes requires titles to be unique, so the app keeps chat titles itself.
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(f"{HERMES}/api/sessions", headers=_headers(), json={})
        response.raise_for_status()
        return response.json()["session"]["id"]


async def delete_session(session_id: str) -> None:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.delete(f"{HERMES}/api/sessions/{session_id}", headers=_headers())
        if response.status_code not in (200, 204, 404):
            response.raise_for_status()


async def messages(session_id: str) -> list[dict]:
    """The chat as the app shows it: user and assistant text, with the tools used for each reply."""
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(f"{HERMES}/api/sessions/{session_id}/messages", headers=_headers(),
                                    params={"inline_images": "false", "limit": 500})
        response.raise_for_status()
        raw = response.json().get("data", [])
    out, tools = [], []
    for m in raw:
        if m.get("role") == "user" and m.get("content"):
            out.append({"role": "user", "text": m["content"]})
            tools = []
        elif m.get("role") == "tool" and m.get("tool_name"):
            label = tool_label(m["tool_name"])
            if label not in tools:
                tools.append(label)
        elif m.get("role") == "assistant" and m.get("content"):
            out.append({"role": "assistant", "text": m["content"], "tools": tools})
            tools = []
    return out


async def stream_turn(session_id: str, text: str) -> AsyncIterator[dict]:
    """One turn, as app events: {"t": "tool", "label"}, {"t": "delta", "text"}, then {"t": "done", "text"} or
    {"t": "error", "message"}."""
    full, event = [], None
    timeout = httpx.Timeout(connect=10, read=600, write=30, pool=10)  # a cold first reply can take minutes
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", f"{HERMES}/api/sessions/{session_id}/chat/stream", headers=_headers(),
                                 json={"input": text}) as response:
            if response.status_code != 200:
                body = (await response.aread()).decode(errors="replace")[:300]
                yield {"t": "error", "message": f"Jarvis is not available right now ({response.status_code}). {body}"}
                return
            async for line in response.aiter_lines():
                if not line or line.startswith(":"):
                    continue
                if line.startswith("event:"):
                    event = line[6:].strip()
                    continue
                if not line.startswith("data:"):
                    continue
                try:
                    data = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue
                if event == "assistant.delta" and data.get("delta"):
                    full.append(data["delta"])
                    yield {"t": "delta", "text": data["delta"]}
                elif event == "tool.started" and data.get("tool_name"):
                    yield {"t": "tool", "label": tool_label(data["tool_name"])}
                elif event == "run.completed":
                    yield {"t": "done", "text": "".join(full)}
                    return
                elif event in ("run.failed", "run.cancelled"):
                    yield {"t": "error", "message": data.get("error") or "Jarvis could not finish that reply."}
                    return
    yield {"t": "done", "text": "".join(full)}
