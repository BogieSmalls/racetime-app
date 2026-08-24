from datetime import timedelta

from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from racetime.models import ExternalIdentity, User


class ExternalIdentityModelTests(TestCase):
    def create_user(self, identity):
        return User.objects.create_user(
            f"{identity}@discord.invalid",
            name=f"Racer {identity}",
        )

    def test_provider_subject_and_provider_user_are_unique(self):
        user = self.create_user("1")
        ExternalIdentity.objects.create(
            user=user, provider="discord", subject="1"
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ExternalIdentity.objects.create(
                    user=user, provider="discord", subject="2"
                )

    def test_provider_subject_is_unique_across_users(self):
        ExternalIdentity.objects.create(
            user=self.create_user("1"), provider="discord", subject="1"
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ExternalIdentity.objects.create(
                    user=self.create_user("2"), provider="discord", subject="1"
                )

    def test_identity_is_deleted_with_user(self):
        user = self.create_user("1")
        identity = ExternalIdentity.objects.create(
            user=user, provider="discord", subject="1"
        )
        identity_id = identity.id
        user.delete()
        self.assertFalse(ExternalIdentity.objects.filter(id=identity_id).exists())

    def test_manager_canonicalizes_provider_and_subject(self):
        identity = ExternalIdentity.objects.create(
            user=self.create_user("123"),
            provider=" Discord ",
            subject=" 123 ",
        )
        self.assertEqual(identity.provider, "discord")
        self.assertEqual(identity.subject, "123")

    def test_full_clean_uses_manager_normalization_from_an_instance(self):
        identity = ExternalIdentity(
            user=self.create_user("full-clean"),
            provider=" Discord ",
            subject=" 123 ",
        )

        identity.full_clean()

        self.assertEqual(identity.provider, "discord")
        self.assertEqual(identity.subject, "123")

    def test_discord_subject_must_be_nonempty_ascii_numeric(self):
        for subject in ("", " ", "abc", "１２３", "1.0", "-1"):
            with self.subTest(subject=subject), self.assertRaises(ValidationError):
                ExternalIdentity.objects.create(
                    user=self.create_user(f"invalid-{len(subject)}-{ord(subject[0]) if subject else 0}"),
                    provider="discord",
                    subject=subject,
                )

    def test_provider_must_be_nonempty_and_canonical(self):
        for provider in ("", " ", "not valid", "-discord"):
            with self.subTest(provider=provider), self.assertRaises(ValidationError):
                ExternalIdentity.objects.create(
                    user=self.create_user(f"provider-{len(provider)}"),
                    provider=provider,
                    subject="123",
                )

    def test_last_authenticated_at_is_optional_and_persisted(self):
        authenticated_at = timezone.now() - timedelta(minutes=1)
        identity = ExternalIdentity.objects.create(
            user=self.create_user("1"),
            provider="discord",
            subject="1",
            last_authenticated_at=authenticated_at,
        )
        identity.refresh_from_db()
        self.assertEqual(identity.last_authenticated_at, authenticated_at)
        self.assertIsNotNone(identity.created_at)

    def test_identity_table_contains_no_provider_profile_or_token_fields(self):
        field_names = {field.name for field in ExternalIdentity._meta.get_fields()}
        self.assertTrue({"user", "provider", "subject"}.issubset(field_names))
        self.assertTrue(
            field_names.isdisjoint(
                {"username", "email", "avatar", "access_token", "refresh_token"}
            )
        )

    def test_admin_is_read_only_oriented_and_searchable(self):
        model_admin = admin.site._registry[ExternalIdentity]
        self.assertFalse(model_admin.has_add_permission(None))
        self.assertFalse(model_admin.has_delete_permission(None))
        self.assertTrue(
            {"user", "provider", "subject", "created_at", "last_authenticated_at"}
            .issubset(set(model_admin.readonly_fields))
        )
        self.assertTrue(
            {"user__name", "provider", "subject"}.issubset(
                set(model_admin.search_fields)
            )
        )


class ExternalIdentityMigrationTests(TransactionTestCase):
    reset_sequences = True

    def test_migrates_from_0081_to_0082_and_reverses(self):
        executor = MigrationExecutor(connection)
        migrate_from = [("racetime", "0081_alter_race_bot_meta")]
        migrate_to = [("racetime", "0082_externalidentity")]
        try:
            executor.migrate(migrate_from)
            self.assertNotIn("racetime_externalidentity", connection.introspection.table_names())

            executor = MigrationExecutor(connection)
            executor.migrate(migrate_to)
            apps = executor.loader.project_state(migrate_to).apps
            HistoricalUser = apps.get_model("racetime", "User")
            HistoricalIdentity = apps.get_model("racetime", "ExternalIdentity")
            user = HistoricalUser.objects.create(
                email="migration@discord.invalid",
                name="Migration Racer",
                discriminator="0000",
            )
            HistoricalIdentity.objects.create(
                user=user, provider="discord", subject="123"
            )
            self.assertEqual(HistoricalIdentity.objects.count(), 1)

            executor = MigrationExecutor(connection)
            executor.migrate(migrate_from)
            self.assertNotIn("racetime_externalidentity", connection.introspection.table_names())
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())
