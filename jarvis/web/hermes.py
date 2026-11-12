"""Chats from the app, kept by Hermes through its Sessions API (the same agent Telegram uses)."""
import asyncio
import fcntl
import json
import os
import time
from collections.abc import AsyncIterator
from pathlib import Path

import httpx

from .. import config
from . import files, instant

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
            attached, own = files.split_message(m["content"])  # a file attached to the chat shows as a chip
            own = instant.NOTE.sub("", own)  # earlier instant answers passed along for the model
            out.append({"role": "user", "text": own, "at": m.get("timestamp"),
                        **({"file": attached} if attached else {})})
            tools = []
        elif m.get("role") == "tool" and m.get("tool_name"):
            label = tool_label(m["tool_name"])
            if label not in tools:
                tools.append(label)
        elif m.get("role") == "assistant" and m.get("content"):
            out.append({"role": "assistant", "text": m["content"], "tools": tools, "at": m.get("timestamp")})
            tools = []
    return out


async def stream_turn(session_id: str, text: str, read_timeout: float = 600) -> AsyncIterator[dict]:
    """One turn, as app events: {"t": "tool", "label"}, {"t": "delta", "text"}, then {"t": "done", "text"} or
    {"t": "error", "message"}."""
    full, event = [], None
    timeout = httpx.Timeout(connect=10, read=read_timeout, write=30, pool=10)  # a cold first reply can take minutes
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


def warm_chat() -> None:
    """jarvis-warm-chat: one throwaway chat through Hermes, deleted afterwards, so the model has Jarvis's long prompt
    cached before the user's next message. Reading that prompt from scratch takes minutes on a 2-core server: after
    a restart, after the nightly AI jobs and after midnight (the prompt holds the date). Once cached, this takes
    seconds. The keep-warm job runs it in the background; two never run at once. JARVIS_WARM_CHAT=off skips it."""
    if not config.WARM_CHAT:
        return
    lock_file = config.SYSTEM_DIR / "state" / "warm-chat.lock"
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    with lock_file.open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return  # the previous warm-up is still reading

        async def run() -> dict:
            session_id = await create_session()
            try:
                async for event in stream_turn(session_id, "Hi", read_timeout=3600):
                    if event["t"] in ("done", "error"):
                        return event
                return {"t": "error", "message": "no reply"}
            finally:
                await delete_session(session_id)

        started = time.monotonic()
        event = asyncio.run(run())
        # A chat that ends without a reply (Hermes still starting, say) warmed nothing.
        result = "ok" if event["t"] == "done" and event.get("text") else f"failed: {event.get('message') or 'no reply'}"
        print(f"{time.strftime('%Y-%m-%d %H:%M')} warm chat {result} in {time.monotonic() - started:.0f} s", flush=True)
        if result == "ok":
            started = time.monotonic()
            try:
                result = mark_question_start()
            except (OSError, ValueError, KeyError, httpx.HTTPError) as error:
                result = f"failed: {type(error).__name__}: {error}"
            print(f"{time.strftime('%Y-%m-%d %H:%M')} question start {result} in {time.monotonic() - started:.0f} s",
                  flush=True)


def mark_question_start() -> str:
    """Send Hermes's fixed instructions alone, so the model saves its place where every new chat's question begins.

    Qwen3.5 can only be resumed from places llama-server saved, 4 tokens before the end of each request among them.
    The Hermes plugin keeps the system message and tools of a new chat's first request (state/chat-prompt.json);
    sent alone with thinking on, the request ends "<|im_start|>assistant\\n<think>\\n", so the place 4 tokens before
    its end is right after the "<|im_start|>" that every new chat's "user" turn also starts with. A new chat then
    reads only its own question instead of the last ~1,100 tokens of the instructions as well."""
    prompt = json.loads((config.SYSTEM_DIR / "state" / "chat-prompt.json").read_text())
    response = httpx.post(f"{config.OLLAMA_URL}/api/chat", timeout=3600, json={
        "model": prompt["model"], "messages": [prompt["system"]], "tools": prompt["tools"], "think": True,
        "stream": False, "options": {"num_predict": 1}})
    response.raise_for_status()
    return f"ok ({len(prompt['tools'])} tools)"
