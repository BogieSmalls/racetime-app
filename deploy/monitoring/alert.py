#!/usr/bin/env python3
"""Authenticate, redact, deduplicate, and deliver a normalized alert."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


SCHEMA_VERSION = 1
MAX_PAYLOAD_BYTES = 65536
SECRET_KEY = re.compile(r"(?:authorization|cookie|credential|password|secret|token|webhook)", re.I)
TOKEN_VALUE = re.compile(r"(?i)(token|secret|password|code)=([^&\s;]+)")
WEBHOOK_VALUE = re.compile(r"https://(?:discord(?:app)?\.com)/api/webhooks/[^\s\"']+", re.I)
SEVERITIES = frozenset({"P0", "P1", "P2", "P3"})
STATUSES = frozenset({"firing", "resolved"})


def redact(value, key=""):
    if SECRET_KEY.search(str(key)):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(item_key): redact(item_value, str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        result = WEBHOOK_VALUE.sub("[REDACTED]", value)
        return TOKEN_VALUE.sub(lambda match: f"{match.group(1)}=[REDACTED]", result)
    return value


def _validate_config(config, environ):
    if config.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported alert configuration schema")
    parsed = urlsplit(str(config.get("webhook_url", "")))
    allowlist = config.get("webhook_host_allowlist")
    if not isinstance(allowlist, list) or not allowlist or any(not isinstance(item, str) for item in allowlist):
        raise ValueError("webhook_host_allowlist must contain exact hostnames")
    if (
        parsed.scheme != "https"
        or parsed.hostname not in allowlist
        or parsed.port not in (None, 443)
        or parsed.username
        or parsed.password
        or not parsed.path.startswith("/api/webhooks/")
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("webhook URL is outside the HTTPS host allowlist")
    attempts = config.get("max_attempts")
    if not isinstance(attempts, int) or not 1 <= attempts <= 5:
        raise ValueError("max_attempts must be between one and five")
    retry = config.get("retry_seconds")
    if not isinstance(retry, (int, float)) or not 0 <= retry <= 30:
        raise ValueError("retry_seconds must be between zero and 30")
    dedupe = config.get("dedupe_seconds")
    if not isinstance(dedupe, (int, float)) or not 60 <= dedupe <= 86400:
        raise ValueError("dedupe_seconds must be between 60 and 86400")
    state_path = Path(str(config.get("state_path", "")))
    if not state_path.is_absolute():
        raise ValueError("state_path must be absolute")
    env_name = str(config.get("signing_secret_env", ""))
    secret = environ.get(env_name, "")
    if len(secret) < 16:
        raise ValueError("alert signing secret is missing or too short")
    validated = dict(config)
    validated["secret"] = secret.encode("utf-8")
    validated["state_path"] = state_path
    return validated


def _parse_payload(raw):
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_PAYLOAD_BYTES:
        raise ValueError("alert payload size is invalid")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("alert payload is not valid UTF-8 JSON") from exc
    required = {
        "schema_version", "event_id", "status", "code", "severity",
        "component", "summary", "observed_at", "runbook", "details",
    }
    if not isinstance(payload, dict) or set(payload) != required:
        raise ValueError("alert payload fields are invalid")
    if payload["schema_version"] != SCHEMA_VERSION:
        raise ValueError("unsupported alert payload schema")
    for key in ("event_id", "code", "component", "summary", "observed_at", "runbook"):
        if not isinstance(payload[key], str) or not payload[key].strip() or len(payload[key]) > 500:
            raise ValueError(f"alert {key} is invalid")
    if payload["severity"] not in SEVERITIES or payload["status"] not in STATUSES:
        raise ValueError("alert status or severity is invalid")
    if not isinstance(payload["details"], dict):
        raise ValueError("alert details must be an object")
    if not payload["runbook"].startswith("docs/runbooks/") or ".." in payload["runbook"]:
        raise ValueError("alert runbook path is invalid")
    return payload


def _load_state(path):
    if not path.exists():
        return {"schema_version": SCHEMA_VERSION, "events": {}}
    if path.is_symlink() or path.stat().st_size > 1024 * 1024:
        raise ValueError("alert state file is unsafe")
    with path.open("r", encoding="utf-8") as handle:
        state = json.load(handle)
    if state.get("schema_version") != SCHEMA_VERSION or not isinstance(state.get("events"), dict):
        raise ValueError("alert state schema is invalid")
    return state


def _write_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix(path.suffix + ".tmp")
    data = json.dumps(state, sort_keys=True, separators=(",", ":")) + "\n"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _default_sender(url, body, timeout):
    request = Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "z1rr-racetime-alert/1"},
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:
        return int(response.status)


class AlertDispatcher:
    def __init__(self, config, *, environ=None, sender=None, sleeper=None, clock=None):
        environ = dict(os.environ if environ is None else environ)
        self.config = _validate_config(config, environ)
        self.sender = sender or _default_sender
        self.sleeper = sleeper or time.sleep
        self.clock = clock or time.time

    def dispatch(self, raw, signature):
        expected = "sha256=" + hmac.new(self.config["secret"], raw, hashlib.sha256).hexdigest()
        if not isinstance(signature, str) or not hmac.compare_digest(signature, expected):
            raise ValueError("alert signature is invalid")
        payload = _parse_payload(raw)
        safe = redact(payload)
        fingerprint = hashlib.sha256(
            f"{payload['component']}\0{payload['code']}\0{payload['event_id']}".encode("utf-8")
        ).hexdigest()
        state = _load_state(self.config["state_path"])
        prior = state["events"].get(fingerprint)
        current_time = float(self.clock())
        if (
            prior
            and prior.get("status") == payload["status"]
            and current_time - float(prior.get("last_sent", 0)) < self.config["dedupe_seconds"]
        ):
            return "deduped"
        if payload["status"] == "resolved" and (not prior or prior.get("status") != "firing"):
            return "deduped"

        prefix = "RESOLVED" if payload["status"] == "resolved" else "ALERT"
        content = (
            f"{prefix} [{safe['severity']}] {safe['component']} {safe['code']}: "
            f"{safe['summary']} — {safe['runbook']}"
        )
        message = {
            "content": content[:1900],
            "allowed_mentions": {"parse": []},
            "embeds": [{"description": json.dumps(safe["details"], sort_keys=True)[:3900]}],
        }
        body = json.dumps(message, sort_keys=True, separators=(",", ":")).encode("utf-8")
        delivered = False
        for attempt in range(self.config["max_attempts"]):
            try:
                status = self.sender(self.config["webhook_url"], body, 10)
                delivered = 200 <= int(status) < 300
            except Exception:
                delivered = False
            if delivered:
                break
            if attempt + 1 < self.config["max_attempts"]:
                self.sleeper(self.config["retry_seconds"] * (attempt + 1))
        if not delivered:
            raise RuntimeError("alert delivery failed after bounded retries")
        state["events"][fingerprint] = {
            "status": payload["status"],
            "last_sent": current_time,
            "event_id_hash": hashlib.sha256(payload["event_id"].encode("utf-8")).hexdigest(),
        }
        _write_state(self.config["state_path"], state)
        return "delivered"


def _load_config(path):
    with Path(path).open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if isinstance(value, dict) and "alert" in value:
        value = value["alert"]
    if not isinstance(value, dict):
        raise ValueError("alert config must be an object")
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--payload", help="payload path; defaults to stdin")
    parser.add_argument("--signature-env", default="RACETIME_ALERT_SIGNATURE")
    args = parser.parse_args(argv)
    raw = Path(args.payload).read_bytes() if args.payload else sys.stdin.buffer.read(MAX_PAYLOAD_BYTES + 1)
    signature = os.environ.get(args.signature_env, "")
    result = AlertDispatcher(_load_config(args.config)).dispatch(raw, signature)
    sys.stdout.write(json.dumps({"result": result}) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
