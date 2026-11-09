"""Signing in to the web app, with a password, with Google, or both (docs/sign-in.md).

Sign-in is off until one of them is set up, so the app on a Mac at home works as before. Until then a public address
(a domain name or a public IP) is refused, so Jarvis is never on the internet without a sign-in.

  jarvis-auth password          sets the password, and signs every device out
  secrets/google-login.json     a Google "Web application" OAuth client; JARVIS_LOGIN_EMAILS says who may use it
"""
import asyncio
import base64
import hashlib
import hmac
import html
import ipaddress
import json
import logging
import os
import secrets
import time
from urllib.parse import urlencode

import httpx
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from .. import config

PASSWORD_FILE = config.SECRETS_DIR / "web-password"
KEY_FILE = config.SECRETS_DIR / "web-session.key"  # signs the sign-in cookies; a new one signs everyone out
GOOGLE_FILE = config.SECRETS_DIR / "google-login.json"
COOKIE, GOOGLE_COOKIE = "jarvis_session", "jarvis_google"
SESSION_DAYS = 30  # renewed while the app is in use, so a phone in daily use stays signed in
GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
# Open without signing in: the sign-in itself, the health check, and the app's code and icons (open source anyway).
OPEN = {"/login", "/logout", "/auth/google", "/auth/google/callback", "/api/health", "/sw.js", "/manifest.webmanifest"}
log = logging.getLogger("jarvis.web.login")


# --- the password and the signing key ---------------------------------------------------------------

_SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1}


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, dklen=32, maxmem=64 * 2 ** 20, **_SCRYPT)
    return "$".join(["scrypt", *(str(_SCRYPT[k]) for k in "nrp"), _b64(salt), _b64(digest)])


def check_password(password: str, stored: str) -> bool:
    try:
        kind, n, r, p, salt, digest = stored.strip().split("$")
        if kind != "scrypt":
            return False
        got = hashlib.scrypt(password.encode(), salt=_unb64(salt), dklen=32, n=int(n), r=int(r), p=int(p),
                             maxmem=64 * 2 ** 20)
        return hmac.compare_digest(got, _unb64(digest))
    except (ValueError, TypeError):
        return False


def _write_secret(path, text: str, replace: bool = True) -> None:
    config.SECRETS_DIR.mkdir(mode=0o700, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | (os.O_TRUNC if replace else os.O_EXCL), 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(text)


def set_password(password: str) -> None:
    """Saves the password's hash and a new signing key, which signs every device out."""
    _write_secret(PASSWORD_FILE, hash_password(password) + "\n")
    _write_secret(KEY_FILE, secrets.token_hex(32) + "\n")


def _key() -> bytes:
    try:
        _write_secret(KEY_FILE, secrets.token_hex(32) + "\n", replace=False)  # only the first time
    except FileExistsError:
        pass
    return KEY_FILE.read_text().strip().encode()


def _sign(payload: str) -> str:
    return f"{payload}.{_b64(hmac.new(_key(), payload.encode(), hashlib.sha256).digest())}"


def _unsign(value: str) -> str:
    """The signed text, or "" when the signature is missing or wrong."""
    payload, _, signature = (value or "").rpartition(".")
    good = payload and _b64(hmac.new(_key(), payload.encode(), hashlib.sha256).digest())
    return payload if good and hmac.compare_digest(signature, good) else ""


# --- what is set up -----------------------------------------------------------------------------------

def password_set() -> bool:
    return PASSWORD_FILE.exists()


def google_client() -> dict | None:
    """The Google OAuth client for signing in, when it and the allowed accounts (JARVIS_LOGIN_EMAILS) are set."""
    if not config.LOGIN_EMAILS or not GOOGLE_FILE.exists():
        return None
    try:
        data = json.loads(GOOGLE_FILE.read_text())
    except (OSError, ValueError):
        log.warning("%s isn't a Google client file; Google sign-in is off", GOOGLE_FILE)
        return None
    client = data.get("web", data) if isinstance(data, dict) else {}
    return client if client.get("client_id") and client.get("client_secret") else None


def enabled() -> bool:
    return password_set() or google_client() is not None


def public(host: str) -> bool:
    """A domain name or a public IP, which the internet can reach. Local names and private (VPN, home) addresses aren't."""
    if not host or host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        return False
    try:
        return ipaddress.ip_address(host.strip("[]")).is_global
    except ValueError:
        return True


# --- the sign-in cookie -------------------------------------------------------------------------------

def session_left(request: Request) -> float:
    """Seconds left on this browser's sign-in; 0 when it isn't signed in."""
    payload = _unsign(request.cookies.get(COOKIE, ""))
    if not payload.startswith("s."):
        return 0
    try:
        return max(int(payload[2:]) - time.time(), 0)
    except ValueError:
        return 0


def _secure(request: Request) -> bool:
    return request.url.scheme == "https"


def _set_session(response: Response, request: Request) -> None:
    seconds = SESSION_DAYS * 86400
    response.set_cookie(COOKIE, _sign(f"s.{int(time.time()) + seconds}"), max_age=seconds, path="/",
                        httponly=True, secure=_secure(request), samesite="lax")


class SignInGuard(BaseHTTPMiddleware):
    """Sends anyone not signed in to the sign-in page (the app's data calls get 401, and the app goes there)."""

    async def dispatch(self, request, call_next):
        path = request.url.path
        if path in OPEN or path.startswith("/static/"):
            return await call_next(request)
        if not enabled():
            if public((request.url.hostname or "").lower()):
                return _refuse(path, "Jarvis has no sign-in yet, so it doesn't answer on a public address. "
                                     "Set a password on the server first: jarvis-auth password")
            return await call_next(request)
        left = session_left(request)
        if not left:
            if path.startswith("/api/"):
                return JSONResponse({"error": "Please sign in again."}, 401)
            return RedirectResponse("/login", 303)
        response = await call_next(request)
        if left < SESSION_DAYS * 86400 / 2:
            _set_session(response, request)
        return response


def _refuse(path: str, message: str) -> Response:
    if path.startswith("/api/"):
        return JSONResponse({"error": message}, 403)
    return _html(f'<p class="msg">{html.escape(message)}</p>', 403)


# --- slowing down password guesses --------------------------------------------------------------------

class Throttle:
    """After 5 wrong passwords from one address it waits 1 minute, then 2, 4 and so on up to an hour. After 20 wrong
    ones in an hour from anywhere, the password pauses for 15 minutes for everyone (Google sign-in still works)."""
    PER_ADDRESS, EVERYONE = 5, 20

    def __init__(self):
        self.fails: dict[str, tuple[int, float]] = {}  # address -> (wrong tries in a row, wait until)
        self.recent: list[float] = []  # times of the wrong tries in the last hour

    def wait(self, address: str, now: float | None = None) -> int:
        """Seconds to wait before this address may try again; 0 = it may try now."""
        now = time.time() if now is None else now
        self.recent = [t for t in self.recent if now - t < 3600]
        until = self.fails.get(address, (0, 0.0))[1]
        if len(self.recent) >= self.EVERYONE:
            until = max(until, self.recent[-1] + 900)
        return int(until - now) + 1 if until > now else 0

    def failed(self, address: str, now: float | None = None) -> None:
        now = time.time() if now is None else now
        self.recent.append(now)
        count = self.fails.get(address, (0, 0.0))[0] + 1
        until = now + min(60 * 2 ** (count - self.PER_ADDRESS), 3600) if count >= self.PER_ADDRESS else 0.0
        if len(self.fails) > 10_000:  # keep memory bounded if many addresses try
            self.fails.clear()
        self.fails[address] = (count, until)

    def passed(self, address: str) -> None:
        self.fails.pop(address, None)


_throttle = Throttle()
_checking = asyncio.Lock()  # one password check at a time, so parallel guesses can't slip past the throttle


def _wait_text(seconds: int) -> str:
    minutes = -(-seconds // 60)
    return "a minute" if minutes <= 1 else f"{minutes} minutes"


# --- the pages ----------------------------------------------------------------------------------------

_MESSAGES = {
    "google": "Google sign-in didn't finish. Try again.",
    "account": "That Google account isn't allowed to sign in to Jarvis.",
}

_STYLE = """
:root{color-scheme:light dark;--bg:#f9f8f6;--card:#fff;--ink:#1f1e1d;--soft:#6b6a67;--line:#e4e2dd;--accent:#c96442}
@media (prefers-color-scheme:dark){:root{--bg:#1a1a19;--card:#262624;--ink:#ecebe8;--soft:#a3a29e;--line:#3a3936}}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px 16px;
  background:var(--bg);color:var(--ink);font:16px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
main{width:100%;max-width:360px}
h1{font-size:28px;margin:0 0 4px}
.sub{color:var(--soft);margin:0 0 24px}
form,.google{display:block}
input{width:100%;font:inherit;padding:13px 14px;border:1px solid var(--line);border-radius:12px;background:var(--card);
  color:var(--ink);margin-bottom:12px}
button,.google{width:100%;font:inherit;font-weight:600;padding:13px 14px;border-radius:12px;text-align:center;
  text-decoration:none;cursor:pointer}
button{border:0;background:var(--accent);color:#fff}
.google{border:1px solid var(--line);background:var(--card);color:var(--ink)}
.or{display:flex;align-items:center;gap:12px;color:var(--soft);font-size:14px;margin:18px 0}
.or::before,.or::after{content:"";flex:1;height:1px;background:var(--line)}
.msg{background:var(--card);border:1px solid var(--line);border-left:3px solid var(--accent);border-radius:10px;
  padding:10px 12px;margin:0 0 16px}
"""


def _html(body: str, status: int = 200) -> HTMLResponse:
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Sign in · Jarvis</title>
<meta name="theme-color" content="#f9f8f6" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#1a1a19" media="(prefers-color-scheme: dark)">
<link rel="manifest" href="/manifest.webmanifest">
<link rel="apple-touch-icon" href="/static/icons/apple-touch-icon.png">
<link rel="icon" href="/static/icons/icon-192.png">
<style>{_STYLE}</style></head>
<body><main><h1>Jarvis</h1><p class="sub">Sign in to continue</p>{body}</main></body></html>"""
    return HTMLResponse(page, status, headers={"Cache-Control": "no-store"})


def _page(message: str = "", status: int = 200) -> HTMLResponse:
    parts = [f'<p class="msg" role="alert">{html.escape(message)}</p>'] if message else []
    if password_set():
        parts.append('<form method="post" action="/login">'
                     '<input type="password" name="password" placeholder="Password" aria-label="Password" '
                     'autocomplete="current-password" required autofocus>'
                     '<button type="submit">Sign in</button></form>')
    if google_client():
        if password_set():
            parts.append('<div class="or">or</div>')
        parts.append('<a class="google" href="/auth/google">Sign in with Google</a>')
    return _html("".join(parts), status)


async def page(request: Request) -> Response:
    if not enabled() or session_left(request):
        return RedirectResponse("/", 303)
    return _page(_MESSAGES.get(request.query_params.get("e", ""), ""))


async def submit(request: Request) -> Response:
    if not password_set():
        return RedirectResponse("/login", 303)
    if request.headers.get("sec-fetch-site") not in (None, "same-origin", "none"):
        return _page("That sign-in came from another website.", 403)
    address = request.client.host if request.client else "unknown"
    async with _checking:
        wait = _throttle.wait(address)
        if wait:
            return _page(f"Too many wrong tries. Try again in {_wait_text(wait)}.", 429)
        form = await request.form()
        password = str(form.get("password") or "")[:1024]
        right = await run_in_threadpool(check_password, password, PASSWORD_FILE.read_text())
        if not right:
            _throttle.failed(address)
            log.warning("wrong password from %s", address)
            return _page("That password isn't right.", 401)
        _throttle.passed(address)
    log.info("signed in with the password from %s", address)
    response = RedirectResponse("/", 303)
    _set_session(response, request)
    return response


async def logout(request: Request) -> Response:
    response = Response(status_code=204)
    response.delete_cookie(COOKIE, path="/", httponly=True, secure=_secure(request), samesite="lax")
    return response


# --- Google -------------------------------------------------------------------------------------------

def _callback(request: Request) -> str:
    return f"{request.url.scheme}://{request.url.netloc}/auth/google/callback"


async def google_start(request: Request) -> Response:
    client = google_client()
    if not client:
        return RedirectResponse("/login", 303)
    state, nonce, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    query = urlencode({
        "client_id": client["client_id"], "redirect_uri": _callback(request), "response_type": "code",
        "scope": "openid email", "state": state, "nonce": nonce, "prompt": "select_account",
        "code_challenge": _b64(hashlib.sha256(verifier.encode()).digest()), "code_challenge_method": "S256"})
    saved = {"state": state, "nonce": nonce, "verifier": verifier, "until": int(time.time()) + 600}
    response = RedirectResponse(f"{GOOGLE_AUTH}?{query}", 303)
    response.set_cookie(GOOGLE_COOKIE, _sign("g." + _b64(json.dumps(saved).encode())), max_age=600,
                        path="/auth/google", httponly=True, secure=_secure(request), samesite="lax")
    return response


async def exchange(client: dict, code: str, redirect_uri: str, verifier: str) -> dict:
    """Trades Google's one-time code for who signed in. The answer comes straight from Google over HTTPS, so it needs
    no signature check (OpenID Connect Core, section 3.1.3.7)."""
    async with httpx.AsyncClient(timeout=15) as http:
        reply = await http.post(GOOGLE_TOKEN, data={
            "code": code, "client_id": client["client_id"], "client_secret": client["client_secret"],
            "redirect_uri": redirect_uri, "grant_type": "authorization_code", "code_verifier": verifier})
    reply.raise_for_status()
    return json.loads(_unb64(reply.json()["id_token"].split(".")[1]))


def check_claims(claims: dict, client_id: str, nonce: str) -> str:
    """"" when Google's answer is good and the account may sign in; otherwise what is wrong."""
    audience = claims.get("aud")
    if claims.get("iss") not in ("accounts.google.com", "https://accounts.google.com"):
        return "issuer"
    if audience != client_id and not (isinstance(audience, list) and client_id in audience):
        return "audience"
    if float(claims.get("exp") or 0) < time.time():
        return "expired"
    if not hmac.compare_digest(str(claims.get("nonce", "")), nonce):
        return "nonce"
    if claims.get("email_verified") not in (True, "true"):
        return "account"
    if str(claims.get("email", "")).lower() not in config.LOGIN_EMAILS:
        return "account"
    return ""


def _saved_google(request: Request) -> dict | None:
    payload = _unsign(request.cookies.get(GOOGLE_COOKIE, ""))
    if not payload.startswith("g."):
        return None
    try:
        saved = json.loads(_unb64(payload[2:]))
    except ValueError:
        return None
    return saved if saved.get("until", 0) > time.time() else None


def _google_failed(problem: str) -> Response:
    response = RedirectResponse(f"/login?e={'account' if problem == 'account' else 'google'}", 303)
    response.delete_cookie(GOOGLE_COOKIE, path="/auth/google")
    return response


async def google_back(request: Request) -> Response:
    client, saved, query = google_client(), _saved_google(request), request.query_params
    if not client or not saved or not query.get("code") \
            or not hmac.compare_digest(query.get("state", ""), saved["state"]):
        log.warning("Google sign-in came back without a matching start (%s)",
                    query.get("error") or "no code, or the state didn't match")
        return _google_failed("start")
    try:
        claims = await exchange(client, query["code"], _callback(request), saved["verifier"])
    except (httpx.HTTPError, ValueError, KeyError, IndexError) as error:
        log.warning("Google sign-in failed: %s", error)
        return _google_failed("exchange")
    problem = check_claims(claims, client["client_id"], saved["nonce"])
    if problem:
        log.warning("Google sign-in refused (%s) for %s", problem, claims.get("email") or "an unknown account")
        return _google_failed(problem)
    log.info("signed in with Google as %s", claims.get("email"))
    response = RedirectResponse("/", 303)
    response.delete_cookie(GOOGLE_COOKIE, path="/auth/google")
    _set_session(response, request)
    return response
