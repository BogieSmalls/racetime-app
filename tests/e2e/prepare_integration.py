"""Create deterministic fixture state inside the isolated integration stack."""

import os


if os.environ.get("DJANGO_SETTINGS_MODULE") != "project.settings.integration":
    raise SystemExit("Refusing to prepare fixtures outside integration settings.")
if os.environ.get("RACETIME_INTEGRATION_ORIGIN") != (
    "https://integration.racetime.test:8443"
):
    raise SystemExit("Refusing to prepare fixtures for a non-integration origin.")

import django  # noqa: E402

django.setup()

from django.core.management import call_command  # noqa: E402
from oauth2_provider.models import get_application_model  # noqa: E402

from racetime.models import Category, ExternalIdentity, Goal, User  # noqa: E402


OWNER_SUBJECT = "1001"
OWNER_EMAIL = f"{OWNER_SUBJECT}@discord.invalid"
PUBLIC_CLIENT_ID = "z1rr-livesplit-integration-public"
REDIRECT_URI = "http://127.0.0.1:4888/"

owner, created = User.objects.get_or_create(
    email=OWNER_EMAIL,
    defaults={"name": "Racer One"},
)
if created:
    owner.set_unusable_password()
    owner.save(update_fields=("password",))
ExternalIdentity.objects.get_or_create(
    user=owner,
    provider="discord",
    subject=OWNER_SUBJECT,
)

call_command(
    "bootstrap_z1rr",
    site_domain="integration.racetime.test",
    site_name="Z1RR RaceTime Integration",
    exclusive_public_category=True,
    owner_discord_id=[OWNER_SUBJECT],
    reconcile_managed_fields=True,
)

# Browser fixtures cannot contact Twitch and must still exercise the race
# lifecycle. This relaxation exists only in the integration database.
Category.objects.filter(slug="z1rr").update(
    streaming_required=False,
    allow_stream_override=True,
)
Goal.objects.filter(category__slug="z1rr").update(
    streaming_required=False,
    allow_stream_override=True,
)

application_model = get_application_model()
application_model.objects.update_or_create(
    client_id=PUBLIC_CLIENT_ID,
    defaults={
        "user": owner,
        "name": "LiveSplit.Racetime.Z1RR Integration",
        "client_type": application_model.CLIENT_PUBLIC,
        "authorization_grant_type": application_model.GRANT_AUTHORIZATION_CODE,
        "redirect_uris": REDIRECT_URI,
    },
)

print("Integration fixtures prepared: owner=1001 category=z1rr oauth=public")
