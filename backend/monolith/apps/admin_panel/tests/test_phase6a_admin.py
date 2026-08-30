import os
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.locations.models import Location
from apps.trips.models import Journey, JourneyLeg, JourneyLegProof

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
    def test_role_matrix_is_enforced_at_representative_endpoints(self):
        samples = {
            AdminRole.OPS: {
                "/api/admin/requests": 200,
                "/api/admin/users": 403,
                "/api/admin/payment-orders": 403,
                "/api/admin/kyc": 403,
                "/api/admin/settings": 403,
            },
            AdminRole.SUPPORT: {
                "/api/admin/users": 200,
                "/api/admin/requests": 200,
                "/api/admin/payment-orders": 403,
                "/api/admin/kyc": 403,
                "/api/admin/settings": 403,
            },
            AdminRole.FINANCE: {
                "/api/admin/payment-orders": 200,
                "/api/admin/disputes": 200,
                "/api/admin/users": 403,
                "/api/admin/kyc": 403,
                "/api/admin/settings": 403,
            },
            AdminRole.TRUST: {
                "/api/admin/users": 200,
                "/api/admin/kyc": 200,
                "/api/admin/flight-proofs": 200,
                "/api/admin/payment-orders": 403,
                "/api/admin/settings": 403,
            },
            AdminRole.SUPER_ADMIN: {
                "/api/admin/users": 200,
                "/api/admin/kyc": 200,
                "/api/admin/payment-orders": 200,
                "/api/admin/settings": 200,
                "/api/admin/roles": 200,
            },
        }

        for role, endpoints in samples.items():
            with self.subTest(role=role):
                user = make_user(f"{role}@matrix.example.test", staff=True)
                assign_admin_roles(
                    user,
                    (role,),
                    elevate_super_admin=role == AdminRole.SUPER_ADMIN,
                )
                self.client.force_authenticate(user)
                for endpoint, expected in endpoints.items():
                    with self.subTest(role=role, endpoint=endpoint):
                        response = self.client.get(endpoint)
                        assert response.status_code == expected, response.data

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


class AdminJourneyContractTests(APITestCase):
    def test_leg_proof_counts_are_present_and_server_calculated(self):
        operator = make_user("ops-journey@example.test", staff=True)
        assign_admin_roles(operator, (AdminRole.OPS,))
        traveler = make_user("traveler-journey@example.test")
        paris = Location.objects.create(
            kind=Location.Kind.CITY,
            normalized_label="paris",
            public_label="Paris",
            city="Paris",
            country_code="FR",
            latitude=Decimal("48.856600"),
            longitude=Decimal("2.352200"),
        )
        algiers = Location.objects.create(
            kind=Location.Kind.CITY,
            normalized_label="algiers",
            public_label="Algiers",
            city="Algiers",
            country_code="DZ",
            latitude=Decimal("36.753800"),
            longitude=Decimal("3.058800"),
        )
        journey = Journey.objects.create(
            traveler=traveler,
            start_location=paris,
            destination_location=algiers,
        )
        departure = timezone.now() + timedelta(days=2)
        leg = JourneyLeg.objects.create(
            journey=journey,
            position=0,
            mode=JourneyLeg.Mode.FLIGHT,
            origin=paris,
            destination=algiers,
            depart_at=departure,
            arrive_at=departure + timedelta(hours=2),
            capacity_kg=Decimal("10.00"),
            flight_number="AH1007",
        )
        JourneyLegProof.objects.create(
            leg=leg,
            bucket="private-proof",
            object_key="journeys/contract/pending.jpg",
        )
        JourneyLegProof.objects.create(
            leg=leg,
            bucket="private-proof",
            object_key="journeys/contract/approved.jpg",
            status=JourneyLegProof.Status.APPROVED,
            reviewer=operator,
            reviewed_at=timezone.now(),
        )

        self.client.force_authenticate(operator)
        response = self.client.get("/api/admin/journeys")

        assert response.status_code == 200
        serialized_leg = response.data["results"][0]["legs"][0]
        assert serialized_leg["proof_count"] == 2
        assert serialized_leg["pending_proof_count"] == 1
