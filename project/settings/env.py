"""Strict, secret-safe environment parsing for production settings."""

import os
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured


__all__ = (
    "required",
    "secret",
    "boolean",
    "integer",
    "csv",
    "https_origin",
)

_SENTINELS = {
    "changeme",
    "example",
    "replace-me",
    "replace_me",
    "tbd",
    "todo",
}
_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def _invalid(name):
    raise ImproperlyConfigured(f"Invalid production configuration: {name}")


def required(name):
    value = os.environ.get(name)
    if value is None:
        _invalid(name)
    value = value.strip()
    if not value or value.lower() in _SENTINELS:
        _invalid(name)
    return value


def secret(name, minimum=32):
    value = required(name)
    if len(value) < minimum:
        _invalid(name)
    return value


def boolean(name, default=None):
    value = os.environ.get(name)
    if value is None or not value.strip():
        if default is None:
            _invalid(name)
        return default
    normalized = value.strip().lower()
    if normalized in _TRUE:
        return True
    if normalized in _FALSE:
        return False
    _invalid(name)


def integer(name, minimum, maximum, default=None):
    raw_value = os.environ.get(name)
    if raw_value is None or not raw_value.strip():
        if default is None:
            _invalid(name)
        value = default
    else:
        try:
            value = int(raw_value.strip())
        except (TypeError, ValueError):
            _invalid(name)
    if isinstance(value, bool) or not minimum <= value <= maximum:
        _invalid(name)
    return value


def csv(name, required=False):
    raw_value = os.environ.get(name)
    if raw_value is None or not raw_value.strip():
        if required:
            _invalid(name)
        return []
    values = [value.strip() for value in raw_value.split(",")]
    if any(not value for value in values):
        _invalid(name)
    return values


def https_origin(name):
    value = required(name)
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except (TypeError, ValueError):
        _invalid(name)
    hostname = parsed.hostname
    if (
        parsed.scheme.lower() != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
        or "*" in hostname
    ):
        _invalid(name)
    host = hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    if port is not None:
        host = f"{host}:{port}"
    return f"https://{host}"
