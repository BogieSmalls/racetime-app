"""Deterministic, service-free settings for fast tests."""

from .base import *  # noqa: F403


DEBUG = False
SECRET_KEY = "z1rr-test-only-secret-key-not-for-production"
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]

INSTALLED_APPS = [
    application for application in INSTALLED_APPS  # noqa: F405
    if application != "debug_toolbar"
]
MIDDLEWARE = [
    middleware for middleware in MIDDLEWARE  # noqa: F405
    if middleware != "debug_toolbar.middleware.DebugToolbarMiddleware"
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    }
}
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "z1rr-racetime-tests",
    }
}
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

RT_SITE_URI = "https://testserver"
RT_PUBLIC_PASSWORD_AUTH = False
RT_PUBLIC_CATEGORY_REQUESTS = False
RT_PATREON_ENABLED = False
RT_DISCORD_AUTH_ENABLED = True
RT_ENABLE_LEGACY_LIVESPLIT_PKCE_BYPASS = False
RT_THROTTLING_ENABLED = True
RT_THROTTLING_REQUIRE_REDIS = False
RACETIME_THROTTLE_HMAC_KEY = "test-only-dedicated-throttle-key-0123456789abcdef"
RACETIME_TRUSTED_PROXY_CIDR = "172.30.0.2/32"

RT_SERVICE_BACKED_CI = False

DISCORD_CLIENT_ID = "test-discord-client"
DISCORD_CLIENT_SECRET = "test-discord-secret"
TWITCH_CLIENT_ID = "test-twitch-client"
TWITCH_CLIENT_SECRET = "test-twitch-secret"
PATREON_CLIENT_ID = "test-patreon-client"
PATREON_CLIENT_SECRET = "test-patreon-secret"
PATREON_ACCESS_TOKEN = "test-patreon-token"
PATREON_CAMPAIGN_ID = 1
