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
