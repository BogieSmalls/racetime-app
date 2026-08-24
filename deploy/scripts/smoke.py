#!/usr/bin/env python3
"""Bounded public HTTP/WSS and optional internal readiness smoke checks."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import socket
import ssl
import sys
from typing import Sequence
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.error import HTTPError, URLError


class SmokeError(RuntimeError):
    """A bounded post-deployment smoke check failed."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def _origin(value: str) -> tuple[str, int]:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise SmokeError("public origin must be an absolute HTTPS origin")
    return parsed.hostname, parsed.port or 443


def _internal_url(value: str) -> None:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname not in {"127.0.0.1", "localhost", "web"}
        or parsed.username
        or parsed.password
        or parsed.path != "/internal/readyz"
        or parsed.query
        or parsed.fragment
        or (parsed.hostname == "web" and parsed.scheme != "http")
    ):
        raise SmokeError(
            "internal readiness URL must be a loopback/web "
            "/internal/readyz endpoint"
        )


def _get_json(
    url: str,
    *,
    timeout: float,
    authorization: str | None = None,
) -> tuple[int, dict]:
    headers = {
        "Accept": "application/json",
        "User-Agent": "z1rr-racetime-deploy-smoke/1",
    }
    if authorization:
        headers["Authorization"] = authorization
    request = Request(url, headers=headers, method="GET")
    try:
        with build_opener().open(request, timeout=timeout) as response:
            body = response.read(4096)
            status = response.status
    except HTTPError as error:
        raise SmokeError(f"HTTP endpoint returned {error.code}") from None
    except (OSError, URLError):
        raise SmokeError("HTTP endpoint unavailable") from None
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise SmokeError("HTTP endpoint returned invalid JSON") from None
    if not isinstance(payload, dict):
        raise SmokeError("HTTP endpoint returned an invalid payload")
    return status, payload


def _login_surface(origin: str, *, timeout: float) -> None:
    request = Request(
        origin.rstrip("/") + "/account/discord",
        headers={"User-Agent": "z1rr-racetime-deploy-smoke/1"},
        method="GET",
    )
    try:
        with build_opener(_NoRedirect()).open(request, timeout=timeout) as response:
            status = response.status
    except HTTPError as error:
        status = error.code
    except (OSError, URLError):
        raise SmokeError("login surface unavailable") from None
    if status not in {200, 302, 303}:
        raise SmokeError("login surface returned an unexpected status")


def _websocket(origin: str, path: str, *, timeout: float) -> None:
    host, port = _origin(origin)
    if (
        not path.startswith("/ws/")
        or "?" in path
        or "#" in path
        or any(ord(character) < 32 for character in path)
    ):
        raise SmokeError("WebSocket smoke path invalid")
    key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
    expected = base64.b64encode(
        hashlib.sha1(
            (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")
        ).digest()
    ).decode("ascii")
    context = ssl.create_default_context()
    try:
        with socket.create_connection((host, port), timeout=timeout) as raw:
            with context.wrap_socket(raw, server_hostname=host) as connection:
                connection.settimeout(timeout)
                request = (
                    f"GET {path} HTTP/1.1\r\n"
                    f"Host: {host}\r\n"
                    "Upgrade: websocket\r\n"
                    "Connection: Upgrade\r\n"
                    f"Sec-WebSocket-Key: {key}\r\n"
                    "Sec-WebSocket-Version: 13\r\n"
                    "User-Agent: z1rr-racetime-deploy-smoke/1\r\n\r\n"
                )
                connection.sendall(request.encode("ascii"))
                response = bytearray()
                while b"\r\n\r\n" not in response and len(response) < 16384:
                    chunk = connection.recv(2048)
                    if not chunk:
                        break
                    response.extend(chunk)
    except (OSError, ssl.SSLError):
        raise SmokeError("WSS handshake unavailable") from None
    header = bytes(response).split(b"\r\n\r\n", 1)[0]
    lines = header.decode("iso-8859-1").split("\r\n")
    if not lines or " 101 " not in f" {lines[0]} ":
        raise SmokeError("WSS handshake did not return 101")
    fields = {}
    for line in lines[1:]:
        if ":" in line:
            name, value = line.split(":", 1)
            fields[name.strip().lower()] = value.strip()
    if fields.get("sec-websocket-accept") != expected:
        raise SmokeError("WSS Sec-WebSocket-Accept mismatch")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", required=True)
    parser.add_argument("--websocket-path", required=True)
    parser.add_argument("--internal-url")
    parser.add_argument("--internal-token-env", default="INTERNAL_HEALTH_TOKEN")
    parser.add_argument("--timeout", type=float, default=5.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        _origin(args.origin)
        status, payload = _get_json(
            args.origin.rstrip("/") + "/healthz", timeout=args.timeout
        )
        if status != 200 or payload != {"status": "ok"}:
            raise SmokeError("public health check failed")
        _login_surface(args.origin, timeout=args.timeout)
        _websocket(args.origin, args.websocket_path, timeout=args.timeout)
        if args.internal_url:
            _internal_url(args.internal_url)
            token = os.environ.get(args.internal_token_env, "")
            if not token:
                raise SmokeError("internal readiness token unavailable")
            status, payload = _get_json(
                args.internal_url,
                timeout=args.timeout,
                authorization=f"Bearer {token}",
            )
            if (
                status != 200
                or payload.get("database") is not True
                or payload.get("cache") is not True
            ):
                raise SmokeError("internal database/cache readiness failed")
    except SmokeError as error:
        print(f"SMOKE=FAIL {error}", file=sys.stderr)
        return 1
    print("SMOKE=PASS HTTP WSS login database cache")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
