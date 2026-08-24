from io import StringIO
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import TestCase

from racetime.models import (
    Category,
    Entrant,
    ExternalIdentity,
    Race,
    User,
    UserAction,
)


CURRENT_SUBJECT = "123456789012345678"
NEW_SUBJECT = "987654321098765432"
EVIDENCE = "INC-2026-0042"


class TransferExternalIdentityCommandTests(TestCase):
    def setUp(self):
        self.target = User.objects.create_user(
            "target@discord.invalid",
            name="Target Racer",
        )
        self.actor = User.objects.create_superuser(
            "operator@discord.invalid",
            password="not-used-by-command",
            name="Infrastructure Operator",
        )
        self.identity = ExternalIdentity.objects.create(
            user=self.target,
            provider="discord",
            subject=CURRENT_SUBJECT,
        )

    def command_options(self, **overrides):
        options = {
            "provider": "discord",
            "current_subject": CURRENT_SUBJECT,
            "new_subject": NEW_SUBJECT,
            "target_user": self.target.hashid,
            "actor_user": self.actor.hashid,
            "evidence": EVIDENCE,
        }
        options.update(overrides)
        return options

    def run_command(self, **overrides):
        stdout = StringIO()
        stderr = StringIO()
        call_command(
            "transfer_external_identity",
            stdout=stdout,
            stderr=stderr,
            **self.command_options(**overrides),
        )
        return stdout.getvalue(), stderr.getvalue()

    def test_all_identity_actor_target_and_evidence_options_are_required(self):
        option_names = (
            "provider",
            "current_subject",
            "new_subject",
            "target_user",
            "actor_user",
            "evidence",
        )
        for missing in option_names:
            options = self.command_options()
            del options[missing]
            with self.subTest(missing=missing), self.assertRaises(CommandError):
                call_command("transfer_external_identity", **options)

    def test_defaults_to_dry_run_and_accepts_target_email(self):
        stdout, _ = self.run_command(target_user=self.target.email)

        self.identity.refresh_from_db()
        self.assertEqual(self.identity.subject, CURRENT_SUBJECT)
        self.assertFalse(UserAction.objects.exists())
        self.assertIn("DRY RUN", stdout)
        self.assertIn(self.target.hashid, stdout)
        self.assertNotIn(self.target.email, stdout)
        self.assertNotIn(CURRENT_SUBJECT, stdout)
        self.assertNotIn(NEW_SUBJECT, stdout)

    def test_apply_requires_exact_target_hashid_confirmation(self):
        for confirmation in (None, self.actor.hashid, self.target.email):
            with self.subTest(confirm=confirmation), self.assertRaises(CommandError):
                self.run_command(apply=True, confirm=confirmation)
        self.identity.refresh_from_db()
        self.assertEqual(self.identity.subject, CURRENT_SUBJECT)
        self.assertFalse(UserAction.objects.exists())

    @mock.patch("racetime.management.commands.transfer_external_identity.logger.info")
    def test_confirmed_apply_transfers_and_audits_target_and_actor(self, log_info):
        stdout, _ = self.run_command(
            apply=True,
            confirm=self.target.hashid,
        )

        self.identity.refresh_from_db()
        self.assertEqual(self.identity.subject, NEW_SUBJECT)
        actions = list(UserAction.objects.order_by("id"))
        self.assertEqual([action.user for action in actions], [self.target, self.actor])
        for action in actions:
            self.assertIn("provider=discord", action.action)
            self.assertIn("old=...5678", action.action)
            self.assertIn("new=...5432", action.action)
            self.assertIn(f"evidence={EVIDENCE}", action.action)
            self.assertNotIn(CURRENT_SUBJECT, action.action)
            self.assertNotIn(NEW_SUBJECT, action.action)
        self.assertIn("APPLIED", stdout)
        self.assertNotIn(CURRENT_SUBJECT, stdout)
        self.assertNotIn(NEW_SUBJECT, stdout)
        log_info.assert_called_once()
        self.assertNotIn(CURRENT_SUBJECT, str(log_info.call_args))
        self.assertNotIn(NEW_SUBJECT, str(log_info.call_args))

    def test_new_subject_collision_is_rejected_without_mutation(self):
        other = User.objects.create_user(
            "other@discord.invalid",
            name="Other Racer",
        )
        ExternalIdentity.objects.create(
            user=other,
            provider="discord",
            subject=NEW_SUBJECT,
        )

        with self.assertRaisesMessage(CommandError, "already linked"):
            self.run_command(apply=True, confirm=self.target.hashid)

        self.identity.refresh_from_db()
        self.assertEqual(self.identity.subject, CURRENT_SUBJECT)
        self.assertFalse(UserAction.objects.exists())

    def test_actor_must_be_an_active_superuser(self):
        cases = (
            {"is_staff": False, "is_superuser": False, "active": True},
            {"is_staff": True, "is_superuser": False, "active": True},
            {"is_staff": True, "is_superuser": True, "active": False},
        )
        for fields in cases:
            for name, value in fields.items():
                setattr(self.actor, name, value)
            self.actor.save(update_fields=tuple(fields))
            with self.subTest(fields=fields), self.assertRaisesMessage(
                CommandError, "active superuser"
            ):
                self.run_command(apply=True, confirm=self.target.hashid)
            self.actor.is_staff = True
            self.actor.is_superuser = True
            self.actor.active = True
            self.actor.save(update_fields=("is_staff", "is_superuser", "active"))
        self.identity.refresh_from_db()
        self.assertEqual(self.identity.subject, CURRENT_SUBJECT)
        self.assertFalse(UserAction.objects.exists())

    def test_current_subject_must_match_target_identity(self):
        with self.assertRaisesMessage(CommandError, "does not match"):
            self.run_command(
                current_subject="111111111111111111",
                apply=True,
                confirm=self.target.hashid,
            )
        self.identity.refresh_from_db()
        self.assertEqual(self.identity.subject, CURRENT_SUBJECT)
        self.assertFalse(UserAction.objects.exists())

    def test_inactive_target_warns_without_mutating_active_race(self):
        self.target.active = False
        self.target.save(update_fields=("active",))
        category = Category.objects.create(
            name="Zelda 1 Randomizer",
            short_name="Z1R",
            slug="z1rr",
            streaming_required=False,
        )
        race = Race.objects.create(
            category=category,
            custom_goal="Beat the game",
            slug="active-race",
            opened_by=self.target,
            streaming_required=False,
        )
        entrant = Entrant.objects.create(user=self.target, race=race)
        entrant_snapshot = {
            field: getattr(entrant, field)
            for field in ("state", "ready", "dnf", "dq", "finish_time")
        }

        stdout, stderr = self.run_command(
            apply=True,
            confirm=self.target.hashid,
        )

        entrant.refresh_from_db()
        self.assertEqual(
            entrant_snapshot,
            {
                field: getattr(entrant, field)
                for field in entrant_snapshot
            },
        )
        self.assertIn("WARNING", stdout + stderr)
        self.assertIn("inactive", (stdout + stderr).lower())
        self.identity.refresh_from_db()
        self.assertEqual(self.identity.subject, NEW_SUBJECT)

    def test_invalid_identity_and_overlong_evidence_fail_before_mutation(self):
        cases = (
            {"new_subject": "not-a-discord-id"},
            {"provider": "invalid provider"},
            {"evidence": "x" * 256},
        )
        for overrides in cases:
            with self.subTest(overrides=overrides), self.assertRaises(CommandError):
                self.run_command(
                    apply=True,
                    confirm=self.target.hashid,
                    **overrides,
                )
        self.identity.refresh_from_db()
        self.assertEqual(self.identity.subject, CURRENT_SUBJECT)
        self.assertFalse(UserAction.objects.exists())
