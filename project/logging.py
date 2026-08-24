"""Structured JSON logging with recursive security redaction."""

from collections.abc import Mapping
from datetime import datetime, timezone
import json
import logging
import re


REDACTED = "[REDACTED]"
_SENSITIVE_KEY = re.compile(
    r"authorization|token|code|secret|cookie|password|webhook",
    re.IGNORECASE,
)
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_SYNTHETIC_EMAIL = re.compile(r"(?i)\b[0-9]+@discord\.invalid\b")
_KEY_VALUE = re.compile(
    r"(?i)\b(authorization|access_token|refresh_token|client_secret|code|"
    r"secret|cookie|password|webhook)\s*[:=]\s*[^\s,;]+"
)
_OAUTH_QUERY = re.compile(
    r"(?i)(https?://[^\s'\"]*(?:/o/|/account/discord/)[^?\s'\"]*)"
    r"\?[^\s'\"]+"
)


def _redact_string(value):
    value = _OAUTH_QUERY.sub(r"\1?" + REDACTED, value)
    value = _BEARER.sub("Bearer " + REDACTED, value)
    value = _SYNTHETIC_EMAIL.sub(REDACTED, value)
    return _KEY_VALUE.sub(lambda match: match.group(1) + "=" + REDACTED, value)


def redact(value, key=None):
    if key is not None and _SENSITIVE_KEY.search(str(key)):
        return REDACTED
    if isinstance(value, Mapping):
        return {
            item_key: redact(item_value, item_key)
            for item_key, item_value in value.items()
        }
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, set):
        return sorted(redact(item) for item in value)
    if isinstance(value, str):
        return _redact_string(value)
    return value


class RedactionFilter(logging.Filter):
    def filter(self, record):
        record.msg = redact(record.msg)
        record.args = redact(record.args)
        for field in ("request_id", "correlation_id"):
            if hasattr(record, field):
                setattr(record, field, redact(getattr(record, field)))
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record):
        exception_class = None
        if isinstance(record.exc_info, BaseException):
            exception_class = type(record.exc_info).__name__
        elif record.exc_info and record.exc_info[0]:
            exception_class = record.exc_info[0].__name__

        request_id = getattr(record, "request_id", None)
        correlation_id = getattr(record, "correlation_id", None)
        payload = {
            "timestamp": datetime.fromtimestamp(
                record.created,
                tz=timezone.utc,
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
            "request_id": redact(request_id or correlation_id),
            "exception_class": exception_class,
        }
        return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
