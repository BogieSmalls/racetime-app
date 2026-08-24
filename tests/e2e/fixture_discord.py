"""A dependency-free Discord OAuth fixture used only by Compose integration."""

from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import secrets
import threading
from urllib.parse import parse_qs, urlencode, urlsplit


_LOCK = threading.Lock()
_CODES = {}
_TOKENS = {}


def _required(name):
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing fixture setting: {name}")
    return value


CLIENT_ID = _required("FIXTURE_DISCORD_CLIENT_ID")
CLIENT_SECRET = _required("FIXTURE_DISCORD_CLIENT_SECRET")
REDIRECT_URI = _required("FIXTURE_DISCORD_REDIRECT_URI")


class FixtureHandler(BaseHTTPRequestHandler):
    server_version = "Z1RRFixture/1"

    def log_message(self, format, *args):  # noqa: A003
        return

    def _json(self, status, payload):
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status=HTTPStatus.BAD_REQUEST):
        self._json(status, {"error": "invalid_request"})

    def do_GET(self):  # noqa: N802
        request = urlsplit(self.path)
        if request.path == "/healthz":
            self._json(HTTPStatus.OK, {"status": "ok"})
            return
        if request.path == "/fixture-discord/authorize":
            self._authorize(parse_qs(request.query, keep_blank_values=True))
            return
        if request.path == "/fixture-discord/user":
            self._user()
            return
        self._error(HTTPStatus.NOT_FOUND)

    def do_POST(self):  # noqa: N802
        if urlsplit(self.path).path != "/fixture-discord/token":
            self._error(HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._error()
            return
        if length < 1 or length > 8192:
            self._error()
            return
        form = parse_qs(self.rfile.read(length).decode("utf-8"), keep_blank_values=True)
        self._token(form)

    def _authorize(self, query):
        required = {
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "scope": "identify",
        }
        if any(query.get(key) != [value] for key, value in required.items()):
            self._error()
            return
        state = query.get("state", [""])[0]
        if not state:
            self._error()
            return
        cookies = SimpleCookie(self.headers.get("Cookie", ""))
        subject_cookie = cookies.get("fixture_discord_subject")
        subject = subject_cookie.value if subject_cookie else ""
        if not subject.isascii() or not subject.isdecimal():
            self._error()
            return
        code = secrets.token_urlsafe(24)
        with _LOCK:
            _CODES[code] = subject
        location = REDIRECT_URI + "?" + urlencode({"code": code, "state": state})
        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def _token(self, form):
        expected = {
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT_URI,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        }
        if any(form.get(key) != [value] for key, value in expected.items()):
            self._error(HTTPStatus.UNAUTHORIZED)
            return
        code = form.get("code", [""])[0]
        with _LOCK:
            subject = _CODES.pop(code, None)
            if subject is not None:
                token = secrets.token_urlsafe(32)
                _TOKENS[token] = subject
            else:
                token = None
        if token is None:
            self._error(HTTPStatus.UNAUTHORIZED)
            return
        self._json(
            HTTPStatus.OK,
            {"access_token": token, "token_type": "Bearer", "expires_in": 300},
        )

    def _user(self):
        authorization = self.headers.get("Authorization", "")
        token = authorization[7:] if authorization.startswith("Bearer ") else ""
        with _LOCK:
            subject = _TOKENS.get(token)
        if subject is None:
            self._error(HTTPStatus.UNAUTHORIZED)
            return
        self._json(HTTPStatus.OK, {"id": subject})


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8090), FixtureHandler).serve_forever()

