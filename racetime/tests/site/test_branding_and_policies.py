from pathlib import Path
from xml.etree import ElementTree

from django.conf import settings
from django.test import TestCase
from django.urls import reverse
from django.utils.html import strip_tags


SOURCE_URL = "https://github.com/BogieSmalls/racetime-app"
LICENSE_URL = SOURCE_URL + "/blob/z1rr-production/LICENSE"
UPSTREAM_URL = "https://github.com/racetimeGG/racetime-app"


class BrandingTests(TestCase):
    def test_settings_define_z1rr_identity_and_attribution(self):
        site_info = settings.RT_SITE_INFO

        self.assertEqual(site_info["title"], "Z1RR RaceTime")
        self.assertEqual(site_info["meta_site_name"], "Z1RR RaceTime")
        self.assertEqual(site_info["operator_text"], "Operated by Z1Rracing")
        self.assertEqual(
            site_info["upstream_text"],
            "Powered by the open-source Racetime project",
        )
        self.assertEqual(site_info["source_url"], SOURCE_URL)
        self.assertEqual(site_info["license_url"], LICENSE_URL)
        self.assertEqual(site_info["upstream_url"], UPSTREAM_URL)
        self.assertEqual(
            site_info["header_logo"],
            "racetime/image/favicon.svg",
        )

    def test_public_page_shows_identity_policies_and_source_attribution(self):
        response = self.client.get(reverse("home"))
        body = response.content.decode()

        self.assertEqual(response.status_code, 200)
        for visible_text in (
            "Z1RR RaceTime",
            "Operated by Z1Rracing",
            "Powered by the open-source Racetime project",
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
            'href="/static/racetime/image/favicon.svg"',
            body,
        )
        self.assertIn('alt="Z1RR RaceTime"', body)
        self.assertNotIn("Operated by racetime.gg", body)
        self.assertNotIn("Official racetime.gg", body)

    def test_favicon_is_valid_accessible_original_svg(self):
        favicon_path = (
            Path(settings.BASE_DIR)
            / "racetime"
            / "static"
            / "racetime"
            / "image"
            / "favicon.svg"
        )
        raw_svg = favicon_path.read_text(encoding="utf-8")
        root = ElementTree.fromstring(raw_svg)

        self.assertTrue(root.tag.endswith("svg"))
        self.assertIn("Z1RR", raw_svg)
        self.assertIn("<title", raw_svg)
        self.assertIn("aria-labelledby", raw_svg)
        self.assertNotIn("racetime.gg", raw_svg.lower())


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
                self.assertIn("Z1RR RaceTime", visible_text)
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
