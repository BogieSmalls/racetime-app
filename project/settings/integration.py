"""Container-backed settings for the isolated G0 integration stack only."""

import os

from .ci import *  # noqa: F403


_EXPECTED_ORIGIN = "https://integration.racetime.test:8443"
if os.environ.get("RACETIME_INTEGRATION_ORIGIN") != _EXPECTED_ORIGIN:
    raise RuntimeError("The integration profile requires its fixed local origin.")

DEBUG = False
RT_SITE_URI = _EXPECTED_ORIGIN
ALLOWED_HOSTS = ["integration.racetime.test"]
CSRF_TRUSTED_ORIGINS = [_EXPECTED_ORIGIN]
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SAMESITE = "Lax"

CORS_ORIGIN_ALLOW_ALL = False
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = [_EXPECTED_ORIGIN]
CORS_ALLOW_CREDENTIALS = False

RACETIME_TRUSTED_PROXY_CIDR = "172.30.0.2/32"
REAL_IP_HEADER = "HTTP_X_FORWARDED_FOR"
RT_THROTTLING_ENABLED = True
RT_THROTTLING_REQUIRE_REDIS = True

RT_PUBLIC_PASSWORD_AUTH = False
RT_PUBLIC_CATEGORY_REQUESTS = False
RT_PATREON_ENABLED = False
RT_DISCORD_AUTH_ENABLED = True
RT_ENABLE_LEGACY_LIVESPLIT_PKCE_BYPASS = False

DISCORD_CLIENT_ID = os.environ["DISCORD_CLIENT_ID"]
DISCORD_CLIENT_SECRET = os.environ["DISCORD_CLIENT_SECRET"]
DISCORD_REDIRECT_URI = _EXPECTED_ORIGIN + "/account/discord/callback"
DISCORD_AUTHORIZE_URL = _EXPECTED_ORIGIN + "/fixture-discord/authorize"
DISCORD_TOKEN_URL = "http://fixture-provider:8090/fixture-discord/token"
DISCORD_USER_URL = "http://fixture-provider:8090/fixture-discord/user"
DISCORD_HTTP_TIMEOUT = (1.0, 3.0)

STATIC_ROOT = "/srv/racetime/static"
MEDIA_ROOT = "/srv/racetime/media"

CHANNEL_LAYERS["default"]["CONFIG"]["prefix"] = (  # noqa: F405
    "z1rr-racetime-integration-channels"
)
CACHES["default"]["KEY_PREFIX"] = "z1rr-racetime-integration"  # noqa: F405

