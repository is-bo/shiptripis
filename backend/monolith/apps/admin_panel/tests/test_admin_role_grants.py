"""Every way a staff member gets a role today writes the current role group.

L4 removed the Phase 4 group names from `assign_admin_roles`. These tests pin,
for each grant path, that the account ends with exactly its role's group and
exactly that role's capabilities, so the removal cannot change a permission.
"""

import os
from unittest.mock import patch

from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase

from apps.accounts.models import User

from ..permissions import (
    ADMIN_PERMISSION_CODES,
    ROLE_GROUP_NAMES,
    ROLE_PERMISSIONS,
    AdminRole,
    has_admin_permission,
    user_admin_roles,
)
from ..services import accept_admin_invitation, change_admin_role, create_admin_invitation

PHASE4_GROUP_NAMES = (
    "Operations Admin",
    "Support Agent",
    "Finance Admin",
    "Trust & Verification Admin",
)


def make_user(email: str, *, staff: bool = False, superuser: bool = False) -> User:
    return User.objects.create_user(
        email=email,
        username=email,
        password="Strong-pass-123!",
        full_name="Role Grant Test",
        is_staff=staff,
        is_superuser=superuser,
    )


class RoleGrantPathTests(TestCase):
    def setUp(self):
        self.root = make_user("root@example.test", staff=True, superuser=True)

    def assert_holds_exactly(self, user, role):
        user = User.objects.get(pk=user.pk)
        assert user_admin_roles(user) == (role,)
        assert set(user.groups.values_list("name", flat=True)) == {ROLE_GROUP_NAMES[role]}
        assert user.is_staff and user.role == "admin"
        held = {code for code in ADMIN_PERMISSION_CODES if has_admin_permission(user, code)}
        assert held == set(ROLE_PERMISSIONS[role])

    def test_migrations_leave_no_phase4_group(self):
        assert not Group.objects.filter(name__in=PHASE4_GROUP_NAMES).exists()

    def test_accepting_an_invitation_as_a_new_account(self):
        for role in (AdminRole.OPS, AdminRole.SUPPORT, AdminRole.FINANCE, AdminRole.TRUST):
            with self.subTest(role=role):
                _, token = create_admin_invitation(
                    actor=self.root, email=f"new-{role}@example.test", role=role
                )
                user = accept_admin_invitation(
                    plaintext_token=token, password="Strong-pass-123!", full_name="New"
                )
                self.assert_holds_exactly(user, role)

    def test_accepting_an_invitation_as_an_existing_account(self):
        existing = make_user("existing@example.test")
        _, token = create_admin_invitation(
            actor=self.root, email=existing.email, role=AdminRole.FINANCE
        )
        user = accept_admin_invitation(plaintext_token=token, authenticated_user=existing)
        self.assert_holds_exactly(user, AdminRole.FINANCE)

    def test_changing_a_role_replaces_the_previous_one(self):
        _, token = create_admin_invitation(
            actor=self.root, email="moved@example.test", role=AdminRole.FINANCE
        )
        user = accept_admin_invitation(plaintext_token=token, password="Strong-pass-123!")
        change_admin_role(actor=self.root, user_id=user.pk, role=AdminRole.SUPPORT)
        self.assert_holds_exactly(user, AdminRole.SUPPORT)
        assert not has_admin_permission(User.objects.get(pk=user.pk), "resolve_disputes")

    def test_the_bootstrap_command_grants_super_admin(self):
        env = {
            "SHIPTRIP_SUPER_ADMIN_EMAIL": "boot@example.test",
            "SHIPTRIP_SUPER_ADMIN_PASSWORD": "Strong-pass-123!",
        }
        with patch.dict(os.environ, env):
            call_command("bootstrap_super_admin")
        user = User.objects.get(email="boot@example.test")
        assert user.is_superuser
        self.assert_holds_exactly(user, AdminRole.SUPER_ADMIN)
