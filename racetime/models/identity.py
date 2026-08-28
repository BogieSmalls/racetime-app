import re

from django.core.exceptions import ValidationError
from django.db import models


_PROVIDER_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
_DISCORD_SUBJECT_PATTERN = re.compile(r"^[0-9]+$")


class ExternalIdentityManager(models.Manager):
    @staticmethod
    def normalize(provider, subject):
        provider = str(provider).strip().lower()
        subject = str(subject).strip()
        errors = {}
        if not _PROVIDER_PATTERN.fullmatch(provider):
            errors["provider"] = (
                "Provider must start with a lowercase letter and contain only "
                "lowercase letters, numbers, underscores, or hyphens."
            )
        if not subject:
            errors["subject"] = "Provider subject cannot be empty."
        elif provider == "discord" and not _DISCORD_SUBJECT_PATTERN.fullmatch(subject):
            errors["subject"] = "Discord subject must contain ASCII digits only."
        if errors:
            raise ValidationError(errors)
        return provider, subject

    def create(self, **kwargs):
        if "provider" not in kwargs or "subject" not in kwargs:
            raise ValidationError("provider and subject are required")
        kwargs["provider"], kwargs["subject"] = self.normalize(
            kwargs["provider"], kwargs["subject"]
        )
        return super().create(**kwargs)


class ExternalIdentity(models.Model):
    user = models.ForeignKey(
        "User",
        on_delete=models.CASCADE,
        related_name="external_identities",
    )
    provider = models.CharField(max_length=32)
    subject = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)
    last_authenticated_at = models.DateTimeField(null=True, blank=True)

    objects = ExternalIdentityManager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("provider", "subject"),
                name="unique_external_provider_subject",
            ),
            models.UniqueConstraint(
                fields=("provider", "user"),
                name="unique_external_provider_user",
            ),
        ]
        ordering = ("provider", "subject")

    def clean(self):
        super().clean()
        self.provider, self.subject = type(self).objects.normalize(
            self.provider, self.subject
        )

    def __str__(self):
        return f"{self.provider}:{self.subject}"


class ProfileImportCandidateManager(models.Manager):
    def create(self, **kwargs):
        if "discord_subject" not in kwargs or "racetimegg_subject" not in kwargs:
            raise ValidationError(
                "discord_subject and racetimegg_subject are required"
            )
        _, kwargs["discord_subject"] = ExternalIdentity.objects.normalize(
            "discord", kwargs["discord_subject"]
        )
        _, kwargs["racetimegg_subject"] = ExternalIdentity.objects.normalize(
            "racetimegg", kwargs["racetimegg_subject"]
        )
        return super().create(**kwargs)


class ProfileImportCandidate(models.Model):
    """A private, unclaimed match offered only after Discord authentication."""

    discord_subject = models.CharField(max_length=128, unique=True)
    racetimegg_subject = models.CharField(max_length=128, unique=True)
    twitch_id = models.BigIntegerField(null=True, blank=True, unique=True)
    owned_categories = models.ManyToManyField(
        "Category",
        blank=True,
        related_name="+",
    )
    moderated_categories = models.ManyToManyField(
        "Category",
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ProfileImportCandidateManager()

    class Meta:
        ordering = ("discord_subject",)

    def clean(self):
        super().clean()
        _, self.discord_subject = ExternalIdentity.objects.normalize(
            "discord", self.discord_subject
        )
        _, self.racetimegg_subject = ExternalIdentity.objects.normalize(
            "racetimegg", self.racetimegg_subject
        )

    def apply_category_roles(self, user):
        user.owned_categories.add(*self.owned_categories.all())
        user.mod_categories.add(*self.moderated_categories.all())

    def __str__(self):
        return (
            f"discord:{self.discord_subject} -> racetimegg:{self.racetimegg_subject}"
        )
