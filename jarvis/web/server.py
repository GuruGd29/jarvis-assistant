"""The Jarvis web app server (Starlette). Listens on 127.0.0.1 only; Caddy serves it over HTTPS.

  jarvis-web                 run on 127.0.0.1:8791 (JARVIS_WEB_PORT to change)
"""
import asyncio
import contextlib
import html
import json
import logging
import os
import sys
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urlsplit

import httpx
import psycopg
import uvicorn
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .. import config, money, watches
from . import data, files, hermes, login, notify, voice

APP_DIR = config.SYSTEM_DIR / "web" / "app"
PORT = int(os.environ.get("JARVIS_WEB_PORT", "8791"))
# A reply keeps running after the phone leaves the app; these keep the background tasks alive until done.
_RUNNING: set[asyncio.Task] = set()
_MONEY_SYNC = asyncio.Lock()  # one tap's check at a time; a second tap waits for it
log = logging.getLogger("jarvis.web")


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


async def _run_turn(session_id: str, text: str, queue: asyncio.Queue, client: dict, shown: str | None = None) -> None:
    """Runs the whole reply even if the phone disconnects; the reply is saved by Hermes either way. `shown` is what the
    chat list shows of the user's message when `text` carries an attached file."""
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
        await run_in_threadpool(_touch_chat, session_id, shown or text, final["text"])
        # Wait until the response stream has either handed the reply to the phone or closed without it.
        try:
            await asyncio.wait_for(client["settled"].wait(), timeout=15)
        except asyncio.TimeoutError:
            pass
        if not client["delivered"]:
            await run_in_threadpool(notify.notify, "replies", "Jarvis replied",
                                    final["text"][:300] or "Your answer is ready.", {"url": f"/#chat/{session_id}"})


# --- files: attached to one chat, or added to the user's files ----------------------------------------------------

async def _upload(request: Request) -> tuple[str, bytes]:
    """The file the app sends as the request body, its name in X-File-Name."""
    if int(request.headers.get("content-length") or 0) > files.MAX_BYTES:
        raise ValueError("That file is over 20 MB.")
    name, data = unquote(request.headers.get("x-file-name", "")).strip(), await request.body()
    if not name or not data:
        raise ValueError("No file came through. Try again.")
    return name, data


async def attach_to_chat(request: Request) -> Response:
    try:
        name, data = await _upload(request)
        return _json(await run_in_threadpool(files.attach, name, data), 201)
    except ValueError as error:
        return _error(str(error))


async def my_files(request: Request) -> Response:
    return _json(await run_in_threadpool(files.my_files))


async def add_my_file(request: Request) -> Response:
    try:
        name, data = await _upload(request)
        return _json(await run_in_threadpool(files.add_file, request.query_params.get("folder", "documents"), name, data), 201)
    except ValueError as error:
        return _error(str(error))


async def view_my_file(request: Request) -> Response:
    try:
        return _json(await run_in_threadpool(files.view, request.query_params.get("path", "")))
    except LookupError:
        return _error("That file is no longer in your files.", 404)


async def my_file_itself(request: Request) -> Response:
    """The file as it is, shown in the browser where it can be (PDFs, photos, text), else downloaded."""
    try:
        path = await run_in_threadpool(files.raw, request.query_params.get("path", ""))
    except LookupError:
        return _error("That file is no longer in your files.", 404)
    headers = {"Cache-Control": "private, no-cache", "X-Content-Type-Options": "nosniff"}
    if path.suffix.lower() != ".pdf":  # a saved web page can't run its scripts here (Chrome shows no PDF when sandboxed)
        headers["Content-Security-Policy"] = "sandbox"
    return FileResponse(path, filename=path.name, content_disposition_type="inline", headers=headers)


async def my_file_picture(request: Request) -> Response:
    try:
        page = int(request.query_params.get("page") or 1)
        jpeg = await run_in_threadpool(files.picture, request.query_params.get("path", ""), page)
    except (LookupError, ValueError):
        return _error("no such page", 404)
    return Response(jpeg, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})


async def remove_my_file(request: Request) -> Response:
    try:
        await run_in_threadpool(files.remove_file, request.query_params.get("path", ""))
    except LookupError:
        return _error("no such file", 404)
    return _json({"ok": True})


async def voice_to_text(request: Request) -> Response:
    """A voice message (16 kHz WAV from the app) as text, to check in the message box before sending."""
    if not voice.available():
        return _error("Voice messages aren't set up on this computer (docs/voice.md).", 503)
    audio = await request.body()
    if not audio:
        return _error("no audio")
    if len(audio) > voice.MAX_BYTES:
        return _error("That voice message is too long; keep it under 2 minutes.", 413)
    try:
        return _json({"text": await voice.transcribe(audio)})
    except (RuntimeError, httpx.HTTPError) as error:
        log.warning("voice message failed: %s", error)
        return _error("Couldn't turn that into text. Try again in a moment.", 503)


async def send_message(request: Request) -> Response:
    session_id = request.path_params["sid"]
    body = await _body(request)
    text, attachment = str(body.get("text", "")).strip(), body.get("attachment")
    if not text and attachment:
        text = "What's in this file? Give me a short summary."
    if not text:
        return _error("message is empty")
    if len(text) > 8000:
        return _error("message is too long")
    if not await run_in_threadpool(_known_chat, session_id):
        return _error("no such chat", 404)
    shown = None
    if attachment:
        try:
            message, name = await run_in_threadpool(files.message_with, str(attachment), text)
        except ValueError as error:
            return _error(str(error))
        text, shown = message, f"{name}: {text}"
    queue: asyncio.Queue = asyncio.Queue()
    # delivered: the final event reached the phone; settled: the stream finished one way or the other.
    client = {"delivered": False, "settled": asyncio.Event()}
    task = asyncio.create_task(_run_turn(session_id, text, queue, client, shown))
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
    on = request.query_params.get("on") or None
    try:
        date.fromisoformat(on) if on else None
    except ValueError:
        return _error("bad date")
    return _json(await run_in_threadpool(data.money_view, period, on))


async def money_sync(request: Request) -> Response:
    """Read new bank alert emails now (the refresh button), on top of the sync every 30 minutes."""
    async with _MONEY_SYNC:
        try:
            counts = await run_in_threadpool(money.sync, 2, ai=False)
        except Exception as error:  # Gmail, the Google sign-in or the database
            log.warning("money sync failed: %s", error)
            return _error("Couldn't check your bank emails. Try again in a moment.", 503)
    if "skipped" in counts:
        return _error(f"Couldn't check: {counts['skipped']}", 503)
    return _json({"added": counts["added"]})


# --- watches ------------------------------------------------------------------------------------------

def _watch_id(request: Request) -> int:
    return int(request.path_params["wid"])


def _every(body: dict) -> int | None:
    try:
        return int(body.get("every"))
    except (TypeError, ValueError):
        return None


async def watch_list(request: Request) -> Response:
    return _json(await run_in_threadpool(watches.listing))


async def watch_places(request: Request) -> Response:
    return _json(await run_in_threadpool(watches.bus_places))


async def watch_create(request: Request) -> Response:
    body = await _body(request)
    try:
        return _json(await run_in_threadpool(watches.create, body.get("kind"), body.get("params") or {}, body.get("day"),
                                             _every(body), body.get("resolved")), 201)
    except ValueError as error:
        return _error(str(error))


async def watch_get(request: Request) -> Response:
    try:
        return _json(await run_in_threadpool(watches.detail, _watch_id(request)))
    except LookupError:
        return _error("no such watch", 404)


async def watch_change(request: Request) -> Response:
    body = await _body(request)
    paused = body.get("paused") if isinstance(body.get("paused"), bool) else None
    try:
        return _json(await run_in_threadpool(watches.change, _watch_id(request), body.get("params"), _every(body), paused,
                                             body.get("day")))
    except LookupError:
        return _error("no such watch", 404)
    except ValueError as error:
        return _error(str(error))


async def watch_delete(request: Request) -> Response:
    await run_in_threadpool(watches.delete, _watch_id(request))
    return _json({"ok": True})


async def watch_start(request: Request) -> Response:
    body = await _body(request)
    try:
        return _json(await run_in_threadpool(watches.start, _watch_id(request), body.get("day"), _every(body)))
    except LookupError:
        return _error("no such watch", 404)
    except ValueError as error:
        return _error(str(error))


async def watch_seen(request: Request) -> Response:
    await run_in_threadpool(watches.seen, _watch_id(request))
    return _json({"ok": True})


async def watch_fill(request: Request) -> Response:
    text = str((await _body(request)).get("text") or "").strip()
    if not text:
        return _error("Say or type what to watch.")
    try:
        return _json(await watches.fill(text))
    except (httpx.HTTPError, ValueError, KeyError) as error:
        log.warning("watch fill failed: %r", error)
        return _error("Jarvis's AI couldn't read that just now. Pick a type below and fill it in.", 503)


async def watch_test(request: Request) -> Response:
    """One real check of a watch that is not saved yet, so the user sees what it reads (10-60 s)."""
    body = await _body(request)
    try:
        params, day = watches.clean(body.get("kind"), body.get("params") or {}, body.get("day"))
    except ValueError as error:
        return _error(str(error))
    return _json(await watches.check(body["kind"], params, day))


async def watch_read(request: Request) -> Response:
    url = str((await _body(request)).get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        return _error("Paste the page's link (starting with https://).")
    try:
        return _json(await watches.options(url))
    except ValueError as error:
        return _error(str(error), 503)


async def cards_view(request: Request) -> Response:
    return _json(await run_in_threadpool(data.cards_view))


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

async def health(request: Request) -> Response:
    """For monitoring: the database, Hermes and the model server. 200 when all answer, 503 otherwise."""
    checks = {}

    def database():
        with notify.connect() as conn:
            conn.execute("SELECT 1")
    try:
        await run_in_threadpool(database)
        checks["database"] = "ok"
    except Exception as error:
        checks["database"] = f"down ({type(error).__name__})"
    async with httpx.AsyncClient(timeout=5) as client:
        for name, url in (("hermes", f"{hermes.HERMES}/health"), ("ollama", f"{config.OLLAMA_URL}/api/version")):
            try:
                checks[name] = "ok" if (await client.get(url)).status_code == 200 else "error"
            except httpx.HTTPError as error:
                checks[name] = f"down ({type(error).__name__})"
    ok = all(v == "ok" for v in checks.values())
    return _json({"ok": ok, **checks}, 200 if ok else 503)


def _profile() -> str:
    """The user's name, number/date style and currency for the app, as a <meta> tag (no inline script needed)."""
    profile = {"name": config.OWNER_NAME, "locale": config.LOCALE.replace("_", "-"), "currency": config.CURRENCY,
               "host": "mac" if sys.platform == "darwin" else "other", "voice": voice.available(),
               "photos": bool(config.IMAGE_SUFFIXES), "signin": login.enabled()}
    return f'<meta name="jarvis-profile" content="{html.escape(json.dumps(profile))}">'


async def index(request: Request) -> Response:
    page = (APP_DIR / "index.html").read_text().replace("<!-- jarvis-profile -->", _profile(), 1)
    return HTMLResponse(page, headers={"Cache-Control": "no-cache"})


async def service_worker(request: Request) -> Response:
    # Served from the root so it controls the whole app; never cached, so updates arrive.
    return FileResponse(APP_DIR / "sw.js", media_type="text/javascript",
                        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})


async def manifest(request: Request) -> Response:
    return FileResponse(APP_DIR / "manifest.webmanifest", media_type="application/manifest+json")


def _host_name(netloc: str) -> str:
    """"10.8.0.1:443" -> "10.8.0.1", "[::1]:8791" -> "::1"."""
    try:
        return (urlsplit(f"//{netloc}").hostname or "").lower()
    except ValueError:
        return ""


class ServerGuard(BaseHTTPMiddleware):
    """On a server (JARVIS_HOSTS set): answer only to Jarvis's own host names, which stops DNS-rebinding tricks, and
    refuse changes sent from other websites, so a page open in the same browser can't use the app."""
    LOCAL = {"127.0.0.1", "localhost", "::1"}  # the scheduled jobs and health checks on the server itself
    MAX_BODY = 25_000_000  # a 20 MB file plus room

    async def dispatch(self, request, call_next):
        allowed = set(config.HOSTS) | self.LOCAL
        if _host_name(request.headers.get("host", "")) not in allowed:
            return _error("Unknown address for Jarvis.", 421)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            site, origin = request.headers.get("sec-fetch-site"), request.headers.get("origin")
            elsewhere = origin and _host_name(urlsplit(origin).netloc) not in allowed
            if (site and site not in ("same-origin", "none")) or elsewhere:
                return _error("Refused: that request came from another website.", 403)
        if int(request.headers.get("content-length") or 0) > self.MAX_BODY:
            return _error("That is too large to send.", 413)
        return await call_next(request)


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
    Route("/login", login.page), Route("/login", login.submit, methods=["POST"]),
    Route("/logout", login.logout, methods=["POST"]),
    Route("/auth/google", login.google_start), Route("/auth/google/callback", login.google_back),
    Route("/api/chats", list_chats, methods=["GET"]), Route("/api/chats", new_chat, methods=["POST"]),
    Route("/api/chats/{sid}", get_chat, methods=["GET"]), Route("/api/chats/{sid}", delete_chat, methods=["DELETE"]),
    Route("/api/chats/{sid}/send", send_message, methods=["POST"]),
    Route("/api/voice", voice_to_text, methods=["POST"]), Route("/api/attach", attach_to_chat, methods=["POST"]),
    Route("/api/files", my_files), Route("/api/files", add_my_file, methods=["POST"]),
    Route("/api/files", remove_my_file, methods=["DELETE"]), Route("/api/files/view", view_my_file),
    Route("/api/files/raw", my_file_itself), Route("/api/files/picture", my_file_picture),
    Route("/api/today", today), Route("/api/iphone-reminders", iphone_reminders),
    Route("/api/tasks/{tid:int}/done", task_done, methods=["POST"]),
    Route("/api/medicine", medicine, methods=["POST"]),
    Route("/api/money", money_view), Route("/api/money/sync", money_sync, methods=["POST"]),
    Route("/api/cards", cards_view), Route("/api/more", more),
    Route("/api/watches", watch_list), Route("/api/watches", watch_create, methods=["POST"]),
    Route("/api/watches/fill", watch_fill, methods=["POST"]), Route("/api/watches/test", watch_test, methods=["POST"]),
    Route("/api/watches/read", watch_read, methods=["POST"]), Route("/api/watches/places", watch_places),
    Route("/api/watches/{wid:int}", watch_get), Route("/api/watches/{wid:int}", watch_change, methods=["PUT"]),
    Route("/api/watches/{wid:int}", watch_delete, methods=["DELETE"]),
    Route("/api/watches/{wid:int}/start", watch_start, methods=["POST"]),
    Route("/api/watches/{wid:int}/seen", watch_seen, methods=["POST"]),
    Route("/api/settings", settings, methods=["GET", "PUT"]),
    Route("/api/activity", activity, methods=["GET", "POST"]),
    Route("/api/push/key", push_key), Route("/api/push/subscribe", push_subscribe, methods=["POST"]),
    Route("/api/push/unsubscribe", push_unsubscribe, methods=["POST"]),
    Route("/api/push/test", push_test, methods=["POST"]),
    Route("/api/health", health),
    Mount("/static", StaticFiles(directory=str(APP_DIR)), name="static"),
]
async def _keep_today_fresh() -> None:
    """Read iPhone Reminders and the calendars at start-up and every couple of minutes, so Today never waits on them."""
    while True:
        await run_in_threadpool(data.iphone_reminders, False)
        await run_in_threadpool(data.agenda, data.tasks.today(), False)
        await asyncio.sleep(data.AGENDA_STALE)


@contextlib.asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(_keep_today_fresh())
    asyncio.create_task(voice.start())  # load the voice model now, so the first voice message is quick
    checks = asyncio.create_task(watches.runner())  # the watches' checks, one at a time
    yield
    task.cancel()
    checks.cancel()


async def server_error(request: Request, error: Exception) -> Response:
    """Every unexpected failure becomes a short, clear message for the app, with the details in the log."""
    if isinstance(error, psycopg.OperationalError):
        log.warning("database unavailable on %s: %s", request.url.path, error)
        return _error("Jarvis's database isn't answering. It usually comes back within a minute.", 503)
    if isinstance(error, (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout)):
        log.warning("Hermes unavailable on %s: %s", request.url.path, error)
        return _error("Jarvis is restarting. Try again in a minute.", 503)
    log.exception("unexpected error on %s %s", request.method, request.url.path)
    where = "the Mac" if sys.platform == "darwin" else "the server"
    return _error(f"Something went wrong on {where}. The details were logged.", 500)


app = Starlette(routes=routes, lifespan=lifespan, exception_handlers={Exception: server_error},
                middleware=[Middleware(SecurityHeaders)] + ([Middleware(ServerGuard)] if config.HOSTS else [])
                + [Middleware(login.SignInGuard)])


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per Hermes/Ollama request would grow the log forever
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning", proxy_headers=True)


if __name__ == "__main__":
    main()
