"""Dry-run-first, audited external identity recovery."""

import logging

from django.core.exceptions import ValidationError
from django.core.management import BaseCommand, CommandError
from django.db import IntegrityError, transaction

from ...models import ExternalIdentity, User, UserAction


logger = logging.getLogger(__name__)
MAX_EVIDENCE_LENGTH = 128


def _resolve_user(reference, label):
    reference = str(reference).strip()
    if not reference:
        raise CommandError(f"{label} is required.")
    try:
        return User.objects.get_by_hashid(reference)
    except User.DoesNotExist:
        try:
            return User.objects.get(email=reference)
        except User.DoesNotExist:
            raise CommandError(f"{label} was not found.") from None


def _normalize_identity(provider, subject):
    try:
        return ExternalIdentity.objects.normalize(provider, subject)
    except ValidationError as error:
        raise CommandError(" ".join(error.messages)) from None


def _redact_subject(subject):
    if len(subject) <= 4:
        return "..." + ("*" * len(subject))
    return "..." + subject[-4:]


def _audit_action(*, role, provider, old_subject, new_subject, actor, target, evidence):
    fields = [
        "identity_transfer",
        f"role={role}",
        f"provider={provider}",
        f"old={_redact_subject(old_subject)}",
        f"new={_redact_subject(new_subject)}",
    ]
    if role == "target":
        fields.append(f"actor={actor.hashid}")
    else:
        fields.append(f"target={target.hashid}")
    fields.append(f"evidence={evidence}")
    action = " ".join(fields)
    if len(action) > UserAction._meta.get_field("action").max_length:
        raise CommandError("Evidence reference is too long for the audit record.")
    return action


class Command(BaseCommand):
    help = "Transfer an external identity with explicit confirmation and audit records."

    def add_arguments(self, parser):
        parser.add_argument("--provider", required=True)
        parser.add_argument("--current-subject", required=True)
        parser.add_argument("--new-subject", required=True)
        parser.add_argument(
            "--target-user",
            required=True,
            help="Target user hashid or exact email address.",
        )
        parser.add_argument(
            "--actor-user",
            required=True,
            help="Active superuser hashid or exact email address.",
        )
        parser.add_argument("--evidence", required=True)
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Apply the transfer; the default is a non-mutating dry run.",
        )
        parser.add_argument(
            "--confirm",
            help="Exact target user hashid required together with --apply.",
        )

    def handle(self, *args, **options):
        provider, current_subject = _normalize_identity(
            options["provider"],
            options["current_subject"],
        )
        new_provider, new_subject = _normalize_identity(
            options["provider"],
            options["new_subject"],
        )
        if provider != new_provider:
            raise CommandError("Provider normalization mismatch.")
        if current_subject == new_subject:
            raise CommandError("The new provider subject must be different.")

        evidence = str(options["evidence"]).strip()
        if not evidence:
            raise CommandError("Evidence reference is required.")
        if len(evidence) > MAX_EVIDENCE_LENGTH:
            raise CommandError(
                f"Evidence reference must be at most {MAX_EVIDENCE_LENGTH} characters."
            )
        if any(character in evidence for character in "\r\n\x00"):
            raise CommandError("Evidence reference contains invalid control characters.")

        target = _resolve_user(options["target_user"], "Target user")
        actor = _resolve_user(options["actor_user"], "Actor user")
        if not actor.is_staff or not actor.is_superuser or not actor.is_active:
            raise CommandError("Actor user must be an active superuser.")

        apply_change = options["apply"]
        if apply_change and options.get("confirm") != target.hashid:
            raise CommandError(
                "--apply requires --confirm with the exact target user hashid."
            )

        target_action = _audit_action(
            role="target",
            provider=provider,
            old_subject=current_subject,
            new_subject=new_subject,
            actor=actor,
            target=target,
            evidence=evidence,
        )
        actor_action = _audit_action(
            role="actor",
            provider=provider,
            old_subject=current_subject,
            new_subject=new_subject,
            actor=actor,
            target=target,
            evidence=evidence,
        )

        with transaction.atomic():
            target = User.objects.select_for_update().get(pk=target.pk)
            actor = User.objects.select_for_update().get(pk=actor.pk)
            if not actor.is_staff or not actor.is_superuser or not actor.is_active:
                raise CommandError("Actor user must be an active superuser.")
            try:
                identity = ExternalIdentity.objects.select_for_update().get(
                    user=target,
                    provider=provider,
                )
            except ExternalIdentity.DoesNotExist:
                raise CommandError(
                    "Current provider subject does not match the target identity."
                ) from None
            if identity.subject != current_subject:
                raise CommandError(
                    "Current provider subject does not match the target identity."
                )
            collision = (
                ExternalIdentity.objects.select_for_update()
                .filter(provider=provider, subject=new_subject)
                .exclude(pk=identity.pk)
                .exists()
            )
            if collision:
                raise CommandError("New provider subject is already linked.")

            if not target.is_active:
                self.stderr.write(
                    self.style.WARNING(
                        f"WARNING: target user {target.hashid} is inactive."
                    )
                )

            if not apply_change:
                self.stdout.write(
                    self.style.WARNING(
                        "DRY RUN: would transfer "
                        f"{provider}:{_redact_subject(current_subject)} to "
                        f"{_redact_subject(new_subject)} for target {target.hashid}."
                    )
                )
                return

            identity.subject = new_subject
            identity.full_clean()
            try:
                identity.save(update_fields=("subject",))
            except IntegrityError:
                raise CommandError("New provider subject is already linked.") from None
            UserAction.objects.bulk_create(
                (
                    UserAction(user=target, action=target_action),
                    UserAction(user=actor, action=actor_action),
                )
            )

        logger.info(
            "External identity transfer applied",
            extra={
                "provider": provider,
                "current_subject": _redact_subject(current_subject),
                "new_subject": _redact_subject(new_subject),
                "target_hashid": target.hashid,
                "actor_hashid": actor.hashid,
                "evidence_reference": evidence,
            },
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"APPLIED: transferred {provider} identity for target {target.hashid}."
            )
        )
