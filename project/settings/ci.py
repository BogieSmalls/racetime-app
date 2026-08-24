"""Service-backed settings used only by the MariaDB/Redis CI job."""

import os

from .test import *  # noqa: F403


_REQUIRED_ENVIRONMENT = (
    "RACETIME_CI_DB_NAME",
    "RACETIME_CI_DB_USER",
    "RACETIME_CI_DB_PASSWORD",
    "RACETIME_CI_DB_HOST",
    "RACETIME_CI_DB_PORT",
    "RACETIME_CI_REDIS_URL",
    "RACETIME_CI_THROTTLE_HMAC_KEY",
)
_missing = [name for name in _REQUIRED_ENVIRONMENT if not os.environ.get(name)]
if _missing:
    raise RuntimeError(
        "Missing required RaceTime CI environment variables: " + ", ".join(_missing)
    )

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": os.environ["RACETIME_CI_DB_NAME"],
        "USER": os.environ["RACETIME_CI_DB_USER"],
        "PASSWORD": os.environ["RACETIME_CI_DB_PASSWORD"],
        "HOST": os.environ["RACETIME_CI_DB_HOST"],
        "PORT": os.environ["RACETIME_CI_DB_PORT"],
        "OPTIONS": {"charset": "utf8mb4"},
    }
}

_redis_url = os.environ["RACETIME_CI_REDIS_URL"]
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": _redis_url,
        "KEY_PREFIX": "z1rr-racetime-ci",
    }
}
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "racetime.utils.RedisChannelLayer",
        "CONFIG": {
            "hosts": [_redis_url],
            "prefix": "z1rr-racetime-ci-channels",
            "capacity": 100,
            "expiry": 10,
        },
    }
}

RT_SERVICE_BACKED_CI = True
RT_THROTTLING_ENABLED = True
RT_THROTTLING_REQUIRE_REDIS = True
RACETIME_THROTTLE_HMAC_KEY = os.environ["RACETIME_CI_THROTTLE_HMAC_KEY"]
RACETIME_TRUSTED_PROXY_CIDR = "172.30.0.2/32"
