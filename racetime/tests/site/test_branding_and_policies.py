from pathlib import Path

from django.conf import settings
from django.test import TestCase
from django.urls import reverse
from django.utils.html import strip_tags

from racetime.models import Category


SOURCE_URL = "https://github.com/BogieSmalls/racetime-app"
LICENSE_URL = SOURCE_URL + "/blob/z1rr-production/LICENSE"
UPSTREAM_URL = "https://github.com/racetimeGG/racetime-app"


class BrandingTests(TestCase):
    def test_settings_define_z1rr_identity_and_attribution(self):
        site_info = settings.RT_SITE_INFO

        self.assertEqual(site_info["title"], "Z1RR Raceroom")
        self.assertEqual(
            site_info["header_text"],
            'Z1RR <span class="dot">.</span> Raceroom',
        )
        self.assertEqual(site_info["meta_site_name"], "Z1RR Raceroom")
        self.assertEqual(site_info["theme_color"], "#e05000")
        self.assertEqual(site_info["operator_text"], "Operated by Z1Rracing")
        self.assertEqual(
            site_info["upstream_text"],
            "Powered by the open-source racetime.gg project",
        )
        self.assertEqual(site_info["source_url"], SOURCE_URL)
        self.assertEqual(site_info["license_url"], LICENSE_URL)
        self.assertEqual(site_info["upstream_url"], UPSTREAM_URL)
        self.assertEqual(
            site_info["header_logo"],
            "racetime/image/icon-192.png",
        )

    def test_public_page_shows_identity_policies_and_source_attribution(self):
        Category.objects.create(
            name="Zelda 1 Randomizer Racing",
            short_name="Z1RR",
            slug="z1rr",
        )
        response = self.client.get(
            reverse("category", kwargs={"category": "z1rr"})
        )
        body = response.content.decode()

        self.assertEqual(response.status_code, 200)
        for visible_text in (
            "Z1RR Raceroom",
            "Privacy",
            "Acceptable use",
            "Account deletion",
            "Contact",
            "Source code",
            "GPL-3.0 license",
        ):
            self.assertIn(visible_text, body)
        for link in (
            reverse("privacy_policy"),
            reverse("acceptable_use_policy"),
            reverse("account_deletion_policy"),
            reverse("contact_policy"),
            SOURCE_URL,
            LICENSE_URL,
            UPSTREAM_URL,
        ):
            self.assertIn(f'href="{link}"', body)
        self.assertIn(
            'href="/static/racetime/image/favicon-32.png"',
            body,
        )
        self.assertIn('href="/static/racetime/image/favicon-16.png"', body)
        self.assertIn(
            'href="/static/racetime/image/apple-touch-icon.png"', body
        )
        self.assertIn(
            'src="/static/racetime/image/icon-192.png"', body
        )
        self.assertIn('alt="Z1RR Raceroom"', body)
        self.assertIn(
            "Z1RR Raceroom is operated by Z1Rracing, powered by the "
            "open-source racetime.gg project",
            " ".join(strip_tags(body).split()),
        )
        self.assertNotIn("Operated by racetime.gg", body)
        self.assertNotIn("Official racetime.gg", body)

    def test_dodongo_icon_assets_have_expected_formats_and_dimensions(self):
        image_root = (
            Path(settings.BASE_DIR)
            / "racetime"
            / "static"
            / "racetime"
            / "image"
        )
        expected_png_sizes = {
            "favicon-16.png": (16, 16),
            "favicon-32.png": (32, 32),
            "favicon-48.png": (48, 48),
            "apple-touch-icon.png": (180, 180),
            "icon-192.png": (192, 192),
            "dodongo_5horns_256x256.png": (256, 256),
        }
        for name, expected_size in expected_png_sizes.items():
            with self.subTest(name=name):
                raw = (image_root / name).read_bytes()
                self.assertEqual(raw[:8], b"\x89PNG\r\n\x1a\n")
                self.assertEqual(
                    (int.from_bytes(raw[16:20], "big"),
                     int.from_bytes(raw[20:24], "big")),
                    expected_size,
                )
        favicon = (image_root / "favicon.ico").read_bytes()
        self.assertEqual(favicon[:4], b"\x00\x00\x01\x00")
        self.assertEqual(int.from_bytes(favicon[4:6], "little"), 3)


class PolicyPageTests(TestCase):
    POLICY_CASES = (
        (
            "privacy_policy",
            "privacy.md",
            (
                "Discord user ID",
                "Twitch",
                "IP address and user-agent",
                "encrypted backups",
                "14 days",
                "three months",
                "one year",
                "not sold",
            ),
        ),
        (
            "acceptable_use_policy",
            "acceptable-use.md",
            (
                "race integrity",
                "cheating",
                "harassment",
                "automated access",
                "moderators may",
            ),
        ),
        (
            "account_deletion_policy",
            "account-deletion.md",
            (
                "active race",
                "historical race results",
                "encrypted backups",
                "one year",
            ),
        ),
        (
            "contact_policy",
            "contact.md",
            (
                "Z1Rracing Discord",
                "Discord Moderation",
                "not endorsed by or jointly administered with racetime.gg",
            ),
        ),
    )

    def test_policy_routes_and_markdown_copies_share_required_substance(self):
        policy_root = Path(settings.BASE_DIR) / "docs" / "policies"

        for route_name, document_name, required_phrases in self.POLICY_CASES:
            with self.subTest(route_name=route_name):
                response = self.client.get(reverse(route_name))
                rendered = response.content.decode()
                markdown = (policy_root / document_name).read_text(
                    encoding="utf-8"
                )
                visible_text = " ".join(strip_tags(rendered).split())
                markdown_text = " ".join(markdown.split())
                self.assertEqual(response.status_code, 200)
                self.assertIn("Z1RR Raceroom", visible_text)
                for phrase in required_phrases:
                    self.assertIn(phrase, visible_text)
                    self.assertIn(phrase, markdown_text)

    def test_delete_confirmation_discloses_backup_retention(self):
        template_path = (
            Path(settings.BASE_DIR)
            / "racetime"
            / "templates"
            / "racetime"
            / "user"
            / "delete_account.html"
        )
        contents = template_path.read_text(encoding="utf-8")

        self.assertIn("live account", contents)
        self.assertIn("encrypted backups", contents)
        self.assertIn("retention", contents)
