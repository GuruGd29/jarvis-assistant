"""The Jarvis web app server (Starlette). Listens on 127.0.0.1 only; Caddy serves it over HTTPS.

  jarvis-web                 run on 127.0.0.1:8791 (JARVIS_WEB_PORT to change)
"""
import asyncio
import contextlib
import json
import os
from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .. import config
from . import data, hermes, notify

APP_DIR = config.SYSTEM_DIR / "web" / "app"
PORT = int(os.environ.get("JARVIS_WEB_PORT", "8791"))
# A reply keeps running after the phone leaves the app; these keep the background tasks alive until done.
_RUNNING: set[asyncio.Task] = set()


def _json(payload, status: int = 200) -> JSONResponse:
    return JSONResponse(payload, status_code=status)


def _error(message: str, status: int = 400) -> JSONResponse:
    return _json({"error": message}, status)


async def _body(request: Request) -> dict:
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return body if isinstance(body, dict) else {}


# --- chats ----------------------------------------------------------------------------------------

def _chat_rows() -> list[dict]:
    with notify.connect() as conn:
        rows = conn.execute("SELECT session_id, title, preview, created_at, updated_at FROM web_chats "
                            "ORDER BY updated_at DESC LIMIT 200").fetchall()
    return [{"id": r["session_id"], "title": r["title"], "preview": r["preview"],
             "updated_at": r["updated_at"].isoformat()} for r in rows]


def _known_chat(session_id: str) -> bool:
    with notify.connect() as conn:
        return conn.execute("SELECT 1 FROM web_chats WHERE session_id = %s", (session_id,)).fetchone() is not None


def _touch_chat(session_id: str, user_text: str, reply: str) -> None:
    title = " ".join(user_text.split())[:60]
    with notify.connect() as conn:
        conn.execute("""UPDATE web_chats SET updated_at = now(), preview = %s,
                        title = CASE WHEN title = 'New chat' THEN %s ELSE title END WHERE session_id = %s""",
                     (" ".join(reply.split())[:140], title or "New chat", session_id))


async def list_chats(request: Request) -> Response:
    return _json(await run_in_threadpool(_chat_rows))


async def new_chat(request: Request) -> Response:
    session_id = await hermes.create_session()

    def insert():
        with notify.connect() as conn:
            conn.execute("INSERT INTO web_chats (session_id) VALUES (%s)", (session_id,))
    await run_in_threadpool(insert)
    return _json({"id": session_id, "title": "New chat", "preview": ""}, 201)


async def get_chat(request: Request) -> Response:
    session_id = request.path_params["sid"]
    if not await run_in_threadpool(_known_chat, session_id):
        return _error("no such chat", 404)
    return _json({"id": session_id, "messages": await hermes.messages(session_id)})


async def delete_chat(request: Request) -> Response:
    session_id = request.path_params["sid"]
    if not await run_in_threadpool(_known_chat, session_id):
        return _error("no such chat", 404)
    await hermes.delete_session(session_id)

    def remove():
        with notify.connect() as conn:
            conn.execute("DELETE FROM web_chats WHERE session_id = %s", (session_id,))
    await run_in_threadpool(remove)
    return _json({"ok": True})


async def _run_turn(session_id: str, text: str, queue: asyncio.Queue, client: dict) -> None:
    """Runs the whole reply even if the phone disconnects; the reply is saved by Hermes either way."""
    final = {"t": "error", "message": "Jarvis could not finish that reply."}
    try:
        async for event in hermes.stream_turn(session_id, text):
            await queue.put(event)
            if event["t"] in ("done", "error"):
                final = event
                break
    except Exception as error:  # report to the phone instead of hanging the chat
        final = {"t": "error", "message": f"Jarvis is not reachable ({type(error).__name__})."}
        await queue.put(final)
    if final["t"] == "done":
        await run_in_threadpool(_touch_chat, session_id, text, final["text"])
        # Wait until the response stream has either handed the reply to the phone or closed without it.
        try:
            await asyncio.wait_for(client["settled"].wait(), timeout=15)
        except asyncio.TimeoutError:
            pass
        if not client["delivered"]:
            await run_in_threadpool(notify.notify, "replies", "Jarvis replied",
                                    final["text"][:300] or "Your answer is ready.", {"url": f"/#chat/{session_id}"})


async def send_message(request: Request) -> Response:
    session_id = request.path_params["sid"]
    text = str((await _body(request)).get("text", "")).strip()
    if not text:
        return _error("message is empty")
    if len(text) > 8000:
        return _error("message is too long")
    if not await run_in_threadpool(_known_chat, session_id):
        return _error("no such chat", 404)
    queue: asyncio.Queue = asyncio.Queue()
    # delivered: the final event reached the phone; settled: the stream finished one way or the other.
    client = {"delivered": False, "settled": asyncio.Event()}
    task = asyncio.create_task(_run_turn(session_id, text, queue, client))
    _RUNNING.add(task)
    task.add_done_callback(_RUNNING.discard)

    async def events():
        try:
            while True:
                event = await queue.get()
                yield json.dumps(event, ensure_ascii=False) + "\n"
                if event["t"] in ("done", "error"):
                    client["delivered"] = True
                    return
        finally:  # also runs when the phone disconnects and Starlette cancels the stream
            client["settled"].set()

    return StreamingResponse(events(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


# --- screens and actions --------------------------------------------------------------------------

async def today(request: Request) -> Response:
    return _json(await run_in_threadpool(data.today))


async def iphone_reminders(request: Request) -> Response:
    return _json(await run_in_threadpool(data.iphone_reminders))


async def task_done(request: Request) -> Response:
    done = bool((await _body(request)).get("done", True))
    try:
        return _json(await run_in_threadpool(data.complete_task, int(request.path_params["tid"]), done))
    except ValueError as error:
        return _error(str(error), 404)


async def medicine(request: Request) -> Response:
    body = await _body(request)
    try:
        return _json(await run_in_threadpool(data.mark_medicine, int(body.get("medication_id", 0)),
                                             str(body.get("time", "")), str(body.get("status", ""))))
    except ValueError as error:
        return _error(str(error))


async def money_view(request: Request) -> Response:
    period = request.query_params.get("period", "week")
    if period not in data.PERIODS:
        return _error("unknown period")
    return _json(await run_in_threadpool(data.money_view, period))


async def more(request: Request) -> Response:
    return _json(await run_in_threadpool(data.more))


# --- settings, activity, push ---------------------------------------------------------------------

async def settings(request: Request) -> Response:
    if request.method == "PUT":
        try:
            await run_in_threadpool(notify.save_settings, await _body(request))
        except ValueError:
            return _error("times must look like 23:00")
    current = await run_in_threadpool(notify.get_settings)
    kinds = [{"kind": k, "title": t, "detail": d, "push": current["push"][k]} for k, (t, d, _) in notify.KINDS.items()]
    return _json({"kinds": kinds, "quiet": current["quiet"], "telegram": notify.telegram_copy_on(current),
                  "telegram_until": current["telegram_until"]})


async def activity(request: Request) -> Response:
    if request.method == "POST":
        await run_in_threadpool(notify.mark_read)
    return _json(await run_in_threadpool(notify.activity, 60))


async def push_key(request: Request) -> Response:
    return _json({"key": await run_in_threadpool(notify.public_key)})


async def push_subscribe(request: Request) -> Response:
    try:
        await run_in_threadpool(notify.subscribe, await _body(request), request.headers.get("user-agent"))
    except ValueError as error:
        return _error(str(error))
    return _json({"ok": True})


async def push_unsubscribe(request: Request) -> Response:
    await run_in_threadpool(notify.unsubscribe, str((await _body(request)).get("endpoint", "")))
    return _json({"ok": True})


async def push_test(request: Request) -> Response:
    sent = await run_in_threadpool(notify.push_all, {"title": "Jarvis", "body": "Notifications are working.",
                                                     "kind": "test", "url": "/#more"})
    return _json({"sent": sent})


# --- static files ---------------------------------------------------------------------------------

async def index(request: Request) -> Response:
    return FileResponse(APP_DIR / "index.html", headers={"Cache-Control": "no-cache"})


async def service_worker(request: Request) -> Response:
    # Served from the root so it controls the whole app; never cached, so updates arrive.
    return FileResponse(APP_DIR / "sw.js", media_type="text/javascript",
                        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})


async def manifest(request: Request) -> Response:
    return FileResponse(APP_DIR / "manifest.webmanifest", media_type="application/manifest+json")


class SecurityHeaders(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; connect-src 'self'; "
            "media-src 'self' blob:; frame-ancestors 'none'; base-uri 'none'")
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        elif request.url.path.startswith("/static/"):
            # Revalidate every time (cheap with ETags), so a new version of the app shows on the next open.
            response.headers.setdefault("Cache-Control", "no-cache")
        return response


routes = [
    Route("/", index), Route("/sw.js", service_worker), Route("/manifest.webmanifest", manifest),
    Route("/api/chats", list_chats, methods=["GET"]), Route("/api/chats", new_chat, methods=["POST"]),
    Route("/api/chats/{sid}", get_chat, methods=["GET"]), Route("/api/chats/{sid}", delete_chat, methods=["DELETE"]),
    Route("/api/chats/{sid}/send", send_message, methods=["POST"]),
    Route("/api/today", today), Route("/api/iphone-reminders", iphone_reminders),
    Route("/api/tasks/{tid:int}/done", task_done, methods=["POST"]),
    Route("/api/medicine", medicine, methods=["POST"]),
    Route("/api/money", money_view), Route("/api/more", more),
    Route("/api/settings", settings, methods=["GET", "PUT"]),
    Route("/api/activity", activity, methods=["GET", "POST"]),
    Route("/api/push/key", push_key), Route("/api/push/subscribe", push_subscribe, methods=["POST"]),
    Route("/api/push/unsubscribe", push_unsubscribe, methods=["POST"]),
    Route("/api/push/test", push_test, methods=["POST"]),
    Mount("/static", StaticFiles(directory=str(APP_DIR)), name="static"),
]
async def _keep_reminders_fresh() -> None:
    """Read iPhone Reminders at start-up and every few minutes, so Today never waits on the Reminders app."""
    while True:
        await run_in_threadpool(data.iphone_reminders, False)
        await asyncio.sleep(data.REMINDERS_STALE)


@contextlib.asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(_keep_reminders_fresh())
    yield
    task.cancel()


app = Starlette(routes=routes, middleware=[Middleware(SecurityHeaders)], lifespan=lifespan)


def main() -> None:
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning", proxy_headers=True)


if __name__ == "__main__":
    main()
