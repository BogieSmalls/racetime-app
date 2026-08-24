#!/usr/bin/env python3
"""Validate production settings without emitting configuration values."""

import base64
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# This command validates production, regardless of the caller's ambient shell.
os.environ["DJANGO_SETTINGS_MODULE"] = "project.settings.production"


def main():
    try:
        import django
        from django.conf import settings
        from django.core.exceptions import ImproperlyConfigured

        django.setup()
        decoded_throttle_key = base64.b64decode(
            settings.RACETIME_THROTTLE_HMAC_KEY,
            validate=True,
        )
        checks = {
            "DJANGO_SECRET_KEY": (
                len(settings.SECRET_KEY) >= 32
                and settings.SECRET_KEY
                != settings.RACETIME_THROTTLE_HMAC_KEY
            ),
            "RACETIME_THROTTLE_HMAC_KEY": len(decoded_throttle_key) >= 32,
            "RACETIME_TRUSTED_PROXY_CIDRS": (
                settings.RACETIME_TRUSTED_PROXY_CIDRS
                == ["172.30.0.2/32"]
                and settings.RACETIME_TRUSTED_PROXY_CIDR
                == "172.30.0.2/32"
            ),
            "RACETIME_ACCESS_PHASE": (
                settings.RACETIME_ACCESS_PHASE in {"restricted", "public"}
            ),
            "RT_SITE_URI": settings.RT_SITE_URI.startswith("https://"),
            "DISCORD_REDIRECT_URI": (
                settings.DISCORD_REDIRECT_URI
                == settings.RT_SITE_URI + "/account/discord/callback"
            ),
            "SECURITY_SETTINGS": (
                not settings.DEBUG
                and settings.SECURE_SSL_REDIRECT
                and settings.SESSION_COOKIE_SECURE
                and settings.CSRF_COOKIE_SECURE
                and not settings.SECURE_HSTS_PRELOAD
            ),
        }
    except ImproperlyConfigured as error:
        print(f"CONFIG=FAIL {error}")
        return 1
    except Exception:
        print("CONFIG=FAIL INTERNAL")
        return 1

    failed = False
    for name, passed in checks.items():
        print(f"{name}={'PASS' if passed else 'FAIL'}")
        failed = failed or not passed
    print(f"CONFIG={'FAIL' if failed else 'PASS'}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
