import os
from unittest.mock import patch

from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APITestCase

from apps.accounts.models import User

from ..models import AdminAuditLog, AdminInvitation, hash_invitation_token
from ..permissions import (
    AdminRole,
    assign_admin_roles,
    has_admin_permission,
    user_admin_roles,
)
from ..services import (
    accept_admin_invitation,
    create_admin_invitation,
    record_admin_action,
    revoke_admin_invitation,
)


def make_user(email: str, *, staff: bool = False, superuser: bool = False) -> User:
    user = User.objects.create_user(
        email=email,
        username=email,
        password="Strong-pass-123!",
        full_name="Admin Test",
        is_staff=staff,
        is_superuser=superuser,
    )
    return user


class AdminRoleBoundaryTests(TestCase):
    def test_roles_are_fixed_and_legacy_privileges_are_revoked_on_downgrade(self):
        user = make_user("finance@example.test", staff=True)
        Group.objects.create(name="Finance Admin")
        # Assign through the real migration-seeded role, then add the legacy
        # compatibility group as a regression fixture.
        assign_admin_roles(user, (AdminRole.FINANCE,))
        user.groups.add(Group.objects.get(name="Finance Admin"))
        assign_admin_roles(user, (AdminRole.SUPPORT,))
        user.refresh_from_db()
        assert user_admin_roles(user) == (AdminRole.SUPPORT,)
        assert not user.groups.filter(name="Finance Admin").exists()
        assert not has_admin_permission(user, "resolve_disputes")
        assert has_admin_permission(user, "view_users")

    def test_support_cannot_read_sensitive_user_fields(self):
        user = make_user("support@example.test", staff=True)
        assign_admin_roles(user, (AdminRole.SUPPORT,))
        assert not has_admin_permission(user, "view_user_sensitive")
        assert has_admin_permission(user, "view_users")

    def test_finance_can_resolve_but_cannot_read_evidence(self):
        user = make_user("finance2@example.test", staff=True)
        assign_admin_roles(user, (AdminRole.FINANCE,))
        assert has_admin_permission(user, "resolve_disputes")
        assert not has_admin_permission(user, "view_evidence")


class AdminInvitationSecurityTests(TestCase):
    def setUp(self):
        self.super_admin = make_user(
            "owner@example.test", staff=True, superuser=True
        )
        assign_admin_roles(
            self.super_admin,
            (AdminRole.SUPER_ADMIN,),
            elevate_super_admin=True,
        )

    @patch("apps.notifications.outbox.enqueue_secret_message")
    def test_invitation_is_hash_only_and_role_bound(self, enqueue):
        invitation, token = create_admin_invitation(
            actor=self.super_admin,
            email="ops@example.test",
            role=AdminRole.OPS,
        )
        invitation.refresh_from_db()
        assert invitation.token_hash == hash_invitation_token(token)
        assert token not in invitation.token_hash
        assert invitation.role == AdminRole.OPS
        assert enqueue.call_args.kwargs["kind"] == "admin_invitation"
        assert AdminAuditLog.objects.filter(
            action="admin_invitation.created", target_id=str(invitation.pk)
        ).exists()

    def test_existing_account_requires_authenticated_same_email_acceptance(self):
        existing = make_user("existing@example.test")
        invitation, token = AdminInvitation.issue(
            email=existing.email,
            role=AdminRole.SUPPORT,
            invited_by=self.super_admin,
        )
        with self.assertRaises(PermissionDenied):
            accept_admin_invitation(plaintext_token=token, password="New-pass-123!")
        existing.refresh_from_db()
        assert not existing.is_staff
        assert invitation.used_at is None

    @patch("apps.notifications.outbox.enqueue_secret_message")
    def test_new_account_acceptance_is_one_use(self, enqueue):
        invitation, token = create_admin_invitation(
            actor=self.super_admin,
            email="new-admin@example.test",
            role=AdminRole.OPS,
        )
        user = accept_admin_invitation(
            plaintext_token=token,
            password="New-admin-pass-123!",
            full_name="New Admin",
        )
        assert user.is_staff
        assert user_admin_roles(user) == (AdminRole.OPS,)
        invitation.refresh_from_db()
        assert invitation.used_at is not None
        with self.assertRaises(Exception):
            accept_admin_invitation(
                plaintext_token=token,
                password="Another-pass-123!",
            )

    @patch("apps.notifications.outbox.enqueue_secret_message")
    def test_revocation_invalidates_the_capability_and_is_audited(self, enqueue):
        invitation, token = create_admin_invitation(
            actor=self.super_admin,
            email="revoked@example.test",
            role=AdminRole.TRUST,
        )
        revoke_admin_invitation(
            actor=self.super_admin,
            invitation_id=invitation.pk,
        )
        with self.assertRaises(ValidationError):
            accept_admin_invitation(
                plaintext_token=token,
                password="Revoked-pass-123!",
            )
        assert AdminAuditLog.objects.filter(
            action="admin_invitation.revoked",
            target_id=str(invitation.pk),
        ).exists()


class AdminAuditSecurityTests(TestCase):
    def test_secret_shaped_metadata_is_redacted_recursively(self):
        row = record_admin_action(
            action="security.redaction_test",
            metadata={"token": "plaintext", "nested": {"delivery_code": "123456"}},
        )
        assert row.metadata == {
            "token": "[REDACTED]",
            "nested": {"delivery_code": "[REDACTED]"},
        }


class SuperAdminBootstrapTests(TestCase):
    @patch.dict(
        os.environ,
        {
            "SHIPTRIP_SUPER_ADMIN_EMAIL": "bootstrap@example.test",
            "SHIPTRIP_SUPER_ADMIN_PASSWORD": "Bootstrap-pass-123!",
            "SHIPTRIP_SUPER_ADMIN_NAME": "Bootstrap Admin",
        },
        clear=False,
    )
    def test_bootstrap_is_idempotent_and_audited_once(self):
        call_command("bootstrap_super_admin", verbosity=0)
        user = User.objects.get(email="bootstrap@example.test")
        password_hash = user.password

        call_command("bootstrap_super_admin", verbosity=0)
        user.refresh_from_db()
        assert user.password == password_hash
        assert user.is_superuser and user.is_staff
        assert user_admin_roles(user) == (AdminRole.SUPER_ADMIN,)
        assert AdminAuditLog.objects.filter(
            action="super_admin.bootstrap",
            target_id=str(user.pk),
        ).count() == 1


class AdminEndpointAuthorizationTests(APITestCase):
    def test_dashboard_requires_named_admin_permission(self):
        user = make_user("ops-endpoint@example.test", staff=True)
        assign_admin_roles(user, (AdminRole.OPS,))
        self.client.force_authenticate(user)
        response = self.client.get("/api/admin/dashboard")
        assert response.status_code == 200
        assert "users" in response.data

        ordinary = make_user("ordinary@example.test")
        self.client.force_authenticate(ordinary)
        assert self.client.get("/api/admin/dashboard").status_code == 403

    def test_user_detail_exposes_reliability_but_not_sensitive_contact_to_support(self):
        support = make_user("support-endpoint@example.test", staff=True)
        assign_admin_roles(support, (AdminRole.SUPPORT,))
        target = make_user("target@example.test")
        self.client.force_authenticate(support)

        response = self.client.get(f"/api/admin/users/{target.pk}")
        assert response.status_code == 200
        assert "average_rating" in response.data
        assert "no_show_count" in response.data
        assert "phone" not in response.data
