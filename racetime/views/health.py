"""Minimal liveness and concealed dependency-readiness endpoints."""

import secrets
import uuid

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.http import Http404, JsonResponse
from django.views.decorators.http import require_GET


def _compact_json(payload, *, status=200):
    return JsonResponse(
        payload,
        status=status,
        json_dumps_params={"separators": (",", ":")},
    )


def _database_ready():
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            return cursor.fetchone() == (1,)
    except Exception:
        return False


def _cache_ready():
    marker = uuid.uuid4().hex
    cache_key = f"racetime:readyz:{marker}"
    try:
        cache.set(cache_key, marker, timeout=5)
        return cache.get(cache_key) == marker
    except Exception:
        return False
    finally:
        try:
            cache.delete(cache_key)
        except Exception:
            pass


def _readiness_token_matches(request):
    configured_token = getattr(settings, "INTERNAL_HEALTH_TOKEN", "")
    if not configured_token:
        return False
    supplied = request.headers.get("Authorization", "")
    expected = f"Bearer {configured_token}"
    try:
        return secrets.compare_digest(supplied, expected)
    except TypeError:
        return False


@require_GET
def healthz(request):
    return _compact_json({"status": "ok"})


@require_GET
def internal_readyz(request):
    if not _readiness_token_matches(request):
        raise Http404

    database_ready = _database_ready()
    cache_ready = _cache_ready()
    status = 200 if database_ready and cache_ready else 503
    return _compact_json(
        {
            "database": database_ready,
            "cache": cache_ready,
        },
        status=status,
    )
