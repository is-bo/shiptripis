"""Idempotent, environment-controlled Super Admin bootstrap."""

from __future__ import annotations

import os

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.admin_panel.models import AdminAuditLog
from apps.admin_panel.permissions import AdminRole, assign_admin_roles
from apps.admin_panel.services import record_admin_action


def _first_env(*names: str) -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


class Command(BaseCommand):
    help = "Create or reconcile the controlled, environment-configured Super Admin account."

    def add_arguments(self, parser):
        parser.add_argument(
            "--email",
            dest="email",
            help="Override the bootstrap email (prefer the environment in production).",
        )
        parser.add_argument(
            "--name", dest="full_name", help="Override the bootstrap display name."
        )

    def handle(self, *args, **options):
        email = (options.get("email") or _first_env(
            "SHIPTRIP_SUPER_ADMIN_EMAIL",
            "SHIPTRIP_SUPERADMIN_EMAIL",
            "ADMIN_BOOTSTRAP_EMAIL",
        )).strip().lower()
        password = _first_env(
            "SHIPTRIP_SUPER_ADMIN_PASSWORD",
            "SHIPTRIP_SUPERADMIN_PASSWORD",
            "ADMIN_BOOTSTRAP_PASSWORD",
        )
        full_name = options.get("full_name") or _first_env(
            "SHIPTRIP_SUPER_ADMIN_NAME", "ADMIN_BOOTSTRAP_NAME"
        ) or "ShipTrip Super Admin"

        if not email or not password:
            raise CommandError(
                "Set SHIPTRIP_SUPER_ADMIN_EMAIL and SHIPTRIP_SUPER_ADMIN_PASSWORD "
                "(or the ADMIN_BOOTSTRAP_* aliases) before bootstrapping."
            )

        User = get_user_model()
        with transaction.atomic():
            user = User.objects.select_for_update(no_key=True).filter(email__iexact=email).first()
            created = user is None
            before = {}
            if user is None:
                user = User(
                    username=email,
                    email=email,
                    full_name=full_name[:120],
                )
            else:
                before = {
                    "is_staff": user.is_staff,
                    "is_superuser": user.is_superuser,
                    "role": user.role,
                }

            # Validate only when creating or when an operator explicitly asks
            # for a password reset. Existing bootstrap runs never overwrite a
            # live administrator's password just because env was reloaded.
            if created:
                validate_password(password, user=user)
                user.set_password(password)
            user.email = email
            user.full_name = full_name[:120]
            user.is_active = True
            user.is_email_verified = True
            user.save()
            assign_admin_roles(
                user, (AdminRole.SUPER_ADMIN,), elevate_super_admin=True
            )

            after = {
                "is_staff": user.is_staff,
                "is_superuser": user.is_superuser,
                "role": user.role,
                "email": user.email,
            }
            # Keep bootstrap state idempotent: one canonical audit row records
            # provisioning; a no-op rerun does not create audit noise.
            already_audited = AdminAuditLog.objects.filter(
                action="super_admin.bootstrap",
                target_type="accounts.user",
                target_id=str(user.pk),
            ).exists()
            if not already_audited:
                record_admin_action(
                    actor=None,
                    action="super_admin.bootstrap",
                    target=user,
                    before=before,
                    after=after,
                    metadata={"source": "environment_bootstrap", "created": created},
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Super Admin {'created' if created else 'reconciled'} for {email}."
            )
        )
