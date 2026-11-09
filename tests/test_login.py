"""The app's sign-in (jarvis/web/login.py): password, Google, the cookie, the guard and the guess throttle."""
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from jarvis import config
from jarvis.web import login

PASSWORD = "correct horse battery staple"
LOCAL, PUBLIC = "http://127.0.0.1", "https://jarvis.example.org"


def _app() -> Starlette:
    async def home(request):
        return PlainTextResponse("home")

    async def data(request):
        return JSONResponse({"ok": True})

    return Starlette(routes=[
        Route("/", home), Route("/api/data", data), Route("/static/app.js", home), Route("/api/health", data),
        Route("/login", login.page), Route("/login", login.submit, methods=["POST"]),
        Route("/logout", login.logout, methods=["POST"]),
        Route("/auth/google", login.google_start), Route("/auth/google/callback", login.google_back),
    ], middleware=[Middleware(login.SignInGuard)])


class SignInTest(unittest.TestCase):
    def setUp(self):
        folder = Path(tempfile.mkdtemp())
        patches = [
            mock.patch.object(config, "SECRETS_DIR", folder),
            mock.patch.object(login, "PASSWORD_FILE", folder / "web-password"),
            mock.patch.object(login, "KEY_FILE", folder / "web-session.key"),
            mock.patch.object(login, "GOOGLE_FILE", folder / "google-login.json"),
            mock.patch.object(login, "_throttle", login.Throttle()),
            mock.patch.object(config, "LOGIN_EMAILS", set()),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.folder = folder

    def client(self, base=PUBLIC) -> TestClient:
        return TestClient(_app(), base_url=base, follow_redirects=False)

    def signed_in(self, base=PUBLIC) -> TestClient:
        login.set_password(PASSWORD)
        client = self.client(base)
        self.assertEqual(client.post("/login", data={"password": PASSWORD}).status_code, 303)
        return client

    @staticmethod
    def use_cookie(client, value):
        """Replaces the browser's sign-in cookie, as an attacker or an old phone would send it."""
        client.cookies.clear()
        client.cookies.set(login.COOKIE, value, domain=urlsplit(str(client.base_url)).hostname)

    def google_ready(self, emails=("me@gmail.com",)):
        (self.folder / "google-login.json").write_text(json.dumps(
            {"web": {"client_id": "id-123.apps.googleusercontent.com", "client_secret": "s3cret"}}))
        config.LOGIN_EMAILS = set(emails)

    # --- the password itself

    def test_password_hash(self):
        stored = login.hash_password(PASSWORD)
        self.assertNotIn(PASSWORD, stored)
        self.assertTrue(login.check_password(PASSWORD, stored))
        self.assertFalse(login.check_password(PASSWORD + "!", stored))
        self.assertFalse(login.check_password(PASSWORD, "not a hash"))
        self.assertNotEqual(stored, login.hash_password(PASSWORD))  # a new salt each time

    def test_secret_files_are_private(self):
        login.set_password(PASSWORD)
        for name in ("web-password", "web-session.key"):
            self.assertEqual((self.folder / name).stat().st_mode & 0o777, 0o600)

    # --- sign-in off

    def test_off_works_as_before_at_home_and_on_the_vpn(self):
        for base in (LOCAL, "http://10.8.0.1", "http://localhost:8791"):
            self.assertEqual(self.client(base).get("/").text, "home")

    def test_off_refuses_a_public_address(self):
        for base in (PUBLIC, "https://1.1.1.1"):
            client = self.client(base)
            self.assertEqual(client.get("/").status_code, 403)
            self.assertIn("jarvis-auth password", client.get("/api/data").json()["error"])
        self.assertEqual(self.client().get("/static/app.js").status_code, 200)  # the app's code is open source

    def test_public_addresses(self):
        for host in ("jarvis.dedyn.io", "1.1.1.1", "8.8.8.8"):
            self.assertTrue(login.public(host), host)
        for host in ("", "localhost", "127.0.0.1", "10.8.0.1", "192.168.1.20", "::1", "[::1]", "mac.local"):
            self.assertFalse(login.public(host), host)

    # --- password sign-in

    def test_signed_out_goes_to_sign_in(self):
        login.set_password(PASSWORD)
        client = self.client()
        self.assertEqual(client.get("/").headers["location"], "/login")
        self.assertEqual(client.get("/api/data").status_code, 401)
        self.assertEqual(client.get("/api/health").status_code, 200)
        page = client.get("/login")
        self.assertEqual(page.status_code, 200)
        self.assertIn('type="password"', page.text)
        self.assertNotIn("Sign in with Google", page.text)
        self.assertEqual(page.headers["cache-control"], "no-store")

    def test_sign_in_and_out(self):
        login.set_password(PASSWORD)
        client = self.client()
        wrong = client.post("/login", data={"password": "nope"})
        self.assertEqual(wrong.status_code, 401)
        self.assertIn("isn&#x27;t right", wrong.text)
        right = client.post("/login", data={"password": PASSWORD})
        self.assertEqual((right.status_code, right.headers["location"]), (303, "/"))
        cookie = right.headers["set-cookie"].lower()
        for flag in ("httponly", "secure", "samesite=lax", "max-age=2592000"):
            self.assertIn(flag, cookie)
        self.assertEqual(client.get("/").text, "home")
        self.assertEqual(client.get("/login").headers["location"], "/")  # already signed in
        self.assertEqual(client.post("/logout").status_code, 204)
        self.assertEqual(client.get("/").status_code, 303)

    def test_no_secure_flag_over_plain_http(self):
        login.set_password(PASSWORD)
        right = self.client(LOCAL).post("/login", data={"password": PASSWORD})
        self.assertNotIn("secure", right.headers["set-cookie"].lower())

    def test_changed_or_old_cookies_dont_work(self):
        client = self.signed_in()
        good = client.cookies.get(login.COOKIE)
        self.use_cookie(client, good)
        self.assertEqual(client.get("/api/data").status_code, 200)  # the helper itself works
        self.use_cookie(client, good[:-2] + ("AA" if not good.endswith("AA") else "BB"))
        self.assertEqual(client.get("/api/data").status_code, 401)
        expired = login._sign(f"s.{int(time.time()) - 5}")
        self.use_cookie(client, expired)
        self.assertEqual(client.get("/api/data").status_code, 401)

    def test_new_password_signs_everyone_out(self):
        client = self.signed_in()
        self.assertEqual(client.get("/api/data").status_code, 200)
        login.set_password("another long password")
        self.assertEqual(client.get("/api/data").status_code, 401)

    def test_sign_in_renews_when_half_used(self):
        client = self.signed_in()
        self.assertNotIn("set-cookie", client.get("/api/data").headers)  # fresh: nothing to renew
        self.use_cookie(client, login._sign(f"s.{int(time.time()) + 3 * 86400}"))
        renewed = client.get("/api/data")
        self.assertIn("max-age=2592000", renewed.headers["set-cookie"].lower())

    def test_sign_in_from_another_website_is_refused(self):
        login.set_password(PASSWORD)
        answer = self.client().post("/login", data={"password": PASSWORD}, headers={"sec-fetch-site": "cross-site"})
        self.assertEqual(answer.status_code, 403)

    def test_guessing_slows_down(self):
        login.set_password(PASSWORD)
        client = self.client()
        for _ in range(5):
            self.assertEqual(client.post("/login", data={"password": "guess"}).status_code, 401)
        blocked = client.post("/login", data={"password": PASSWORD})  # even the right one waits now
        self.assertEqual(blocked.status_code, 429)
        self.assertIn("Try again in a minute", blocked.text)

    def test_throttle(self):
        throttle, now = login.Throttle(), 1_000_000.0
        for _ in range(4):
            throttle.failed("a", now)
        self.assertEqual(throttle.wait("a", now), 0)
        throttle.failed("a", now)
        self.assertEqual(throttle.wait("a", now), 61)
        throttle.failed("a", now)
        self.assertEqual(throttle.wait("a", now), 121)  # doubles
        self.assertEqual(throttle.wait("a", now + 200), 0)
        throttle.passed("a")
        self.assertEqual(throttle.wait("a", now), 0)
        for i in range(20):  # many addresses, a few tries each: everyone pauses for 15 minutes
            throttle.failed(f"b{i}", now)
        self.assertEqual(throttle.wait("c", now), 901)
        self.assertEqual(throttle.wait("c", now + 901), 0)

    # --- Google

    def test_google_needs_the_client_and_the_allowed_accounts(self):
        self.assertIsNone(login.google_client())
        self.google_ready(emails=())
        self.assertIsNone(login.google_client())  # no allowed accounts: off, never "any Google account"
        self.google_ready()
        self.assertEqual(login.google_client()["client_id"], "id-123.apps.googleusercontent.com")
        page = self.client().get("/login")
        self.assertIn("Sign in with Google", page.text)
        self.assertNotIn('type="password"', page.text)

    def _start(self, client):
        start = client.get("/auth/google")
        self.assertEqual(start.status_code, 303)
        where = urlsplit(start.headers["location"])
        self.assertEqual(f"{where.scheme}://{where.netloc}{where.path}", login.GOOGLE_AUTH)
        query = {k: v[0] for k, v in parse_qs(where.query).items()}
        self.assertEqual(query["redirect_uri"], f"{PUBLIC}/auth/google/callback")
        self.assertEqual((query["scope"], query["code_challenge_method"]), ("openid email", "S256"))
        return query

    def _back(self, client, query, claims, state=None):
        async def exchange(client_info, code, redirect_uri, verifier):
            self.assertEqual((code, redirect_uri), ("one-time-code", f"{PUBLIC}/auth/google/callback"))
            self.assertTrue(verifier)
            return claims
        with mock.patch.object(login, "exchange", exchange):
            return client.get("/auth/google/callback", params={"code": "one-time-code", "state": state or query["state"]})

    def _claims(self, query, **change):
        claims = {"iss": "https://accounts.google.com", "aud": "id-123.apps.googleusercontent.com",
                  "exp": time.time() + 3600, "nonce": query["nonce"], "email": "Me@Gmail.com", "email_verified": True}
        return {**claims, **change}

    def test_google_sign_in(self):
        self.google_ready()
        client = self.client()
        query = self._start(client)
        back = self._back(client, query, self._claims(query))
        self.assertEqual((back.status_code, back.headers["location"]), (303, "/"))
        self.assertEqual(client.get("/api/data").status_code, 200)

    def test_google_refuses_other_accounts_and_bad_answers(self):
        self.google_ready()
        cases = [({"email": "someone@gmail.com"}, "account"), ({"email_verified": False}, "account"),
                 ({"aud": "another-app"}, "google"), ({"iss": "https://evil.example"}, "google"),
                 ({"exp": time.time() - 10}, "google"), ({"nonce": "replayed"}, "google")]
        for change, shown in cases:
            client = self.client()
            query = self._start(client)
            back = self._back(client, query, self._claims(query, **change))
            self.assertEqual(back.headers["location"], f"/login?e={shown}", change)
            self.assertEqual(client.get("/api/data").status_code, 401, change)

    def test_google_needs_a_matching_start(self):
        self.google_ready()
        client = self.client()
        query = self._start(client)
        self.assertEqual(self._back(client, query, self._claims(query), state="forged").headers["location"],
                         "/login?e=google")
        stranger = self.client()  # came back without starting here
        self.assertEqual(self._back(stranger, query, self._claims(query)).headers["location"], "/login?e=google")


class AppWiringTest(unittest.TestCase):
    """The real app has the sign-in routes and guard (no database needed for these)."""

    def test_app_asks_for_sign_in(self):
        from jarvis.web import server

        folder = Path(tempfile.mkdtemp())
        with mock.patch.object(config, "SECRETS_DIR", folder), \
                mock.patch.object(login, "PASSWORD_FILE", folder / "web-password"), \
                mock.patch.object(login, "KEY_FILE", folder / "web-session.key"):
            login.set_password(PASSWORD)
            client = TestClient(server.app, base_url="http://127.0.0.1", follow_redirects=False)
            self.assertEqual(client.get("/").headers["location"], "/login")
            self.assertEqual(client.get("/api/chats").status_code, 401)
            self.assertIn('type="password"', client.get("/login").text)
            self.assertEqual(client.get("/manifest.webmanifest").status_code, 200)
            client.post("/login", data={"password": PASSWORD})
            home = client.get("/")
            self.assertEqual(home.status_code, 200)
            self.assertIn("&quot;signin&quot;: true", home.text)


if __name__ == "__main__":
    unittest.main()
