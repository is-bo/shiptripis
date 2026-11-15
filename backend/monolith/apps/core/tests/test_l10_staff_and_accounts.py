"""L10 final acceptance: staff sign-in, finance exports and an account claimed back.

Plan L10 item 2:

- a staff sign-in with enrolment, a wrong code, a recovery code and a reset
  (spec 19.1), through the console pages with the password form, never the
  test helper that marks a session verified;
- the three exports reconciled with the finance dashboard (spec 19.2), after
  real deliveries: one paid out, one refunded after a no-show;
- an account opened with someone else's email and then claimed, once by Google
  sign-in and once by a password reset, with the first person signed out and
  their device silent (plan L18A item 5).
"""

from __future__ import annotations

import base64
import csv
import io
import json
import uuid
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import PasswordResetCode, User
from apps.admin_panel import two_step
from apps.admin_panel.console_exports import AUDIT_ACTION
from apps.admin_panel.models import AdminAuditLog
from apps.admin_panel.permissions import (
    ROLE_PERMISSIONS,
    AdminRole,
    assign_admin_roles,
    role_group,
)
from apps.admin_panel.tests.two_step_helpers import staff_login
from apps.core import channels
from apps.core.tests.business_settings_seed import seed_business_settings
from apps.deals.tests.phase4_factories import freeze_at
from apps.discovery.tests.support import STATIC_STORES
from apps.finance.control_plane.filters import Scope
from apps.finance.control_plane.snapshot import build_snapshot
from apps.finance.models import Payout
from apps.notifications.models import PushDevice
from apps.notifications.push import enqueue_fcm_for_event

from .l10_world import DRIVE, AcceptanceWorld, api

KEYRING = {
    "PAYOUT_DATA_KEYRING": json.dumps({"l10": base64.b64encode(b"l" * 32).decode()}),
    "PAYOUT_DATA_ACTIVE_KEY_ID": "l10",
    "PAYOUT_ACCOUNT_FINGERPRINT_KEY": base64.b64encode(b"m" * 32).decode(),
}
PASSWORD = "Strong-pass-123!"


def code_now(user, *, at=None) -> str:
    key = two_step._key_bytes(two_step.secret_text(two_step.pending_enrolment(user)))
    return two_step.totp(key, at or timezone.now())


@override_settings(STORAGES=STATIC_STORES, **KEYRING)
class StaffSignInTests(TestCase):
    def staff(self, email, role):
        user = User.objects.create_user(
            email=email,
            username=email,
            password=PASSWORD,
            full_name="Staff Member",
            is_staff=True,
            is_superuser=role == AdminRole.SUPER_ADMIN,
        )
        assign_admin_roles(
            user, (role,), elevate_super_admin=role == AdminRole.SUPER_ADMIN
        )
        return user

    def sign_in(self, client, user):
        response = client.post(
            reverse("admin:login") + "?next=/admin/marketplace/deals/",
            {
                "username": user.email,
                "password": PASSWORD,
                "next": "/admin/marketplace/deals/",
            },
        )
        assert response.status_code == 302, response.content[:400]
        return response

    def test_enrolment_a_wrong_code_a_recovery_code_and_a_reset(self):
        ops = self.staff("l10-ops@example.test", AdminRole.OPS)
        owner = self.staff("l10-owner@example.test", AdminRole.SUPER_ADMIN)
        client = Client()

        # The password alone opens nothing.
        self.sign_in(client, ops)
        gated = client.get("/admin/marketplace/deals/")
        assert gated.status_code == 302 and gated["Location"].startswith(
            "/admin/two-step/"
        )

        # First sign-in: enrol. A wrong code is refused; the right one shows ten codes once.
        enrol = reverse("admin_console:two-step-enrol")
        assert client.get(enrol).status_code == 200
        wrong = client.post(
            enrol, {"code": "000000", "next": "/admin/marketplace/deals/"}
        )
        assert wrong.status_code == 400
        start = timezone.now() - timedelta(minutes=3)
        with freeze_at(start):
            done = client.post(
                enrol,
                {"code": code_now(ops, at=start), "next": "/admin/marketplace/deals/"},
            )
        assert done.status_code == 302
        shown = client.get(reverse("admin_console:two-step-recovery-codes"))
        codes = shown.context["codes"]
        assert len(codes) == 10
        assert client.get("/admin/marketplace/deals/").status_code == 200
        assert AdminAuditLog.objects.filter(
            actor=ops, action__startswith="admin.two_step"
        ).exists()

        # Next sign-in: the verify page; a wrong code, then a recovery code.
        client.logout()
        self.sign_in(client, ops)
        assert client.get("/admin/marketplace/deals/")["Location"].startswith(
            "/admin/two-step/"
        )
        verify = reverse("admin_console:two-step-verify")
        assert client.post(verify, {"code": "000000"}).status_code == 400
        assert client.get("/admin/marketplace/deals/").status_code == 302
        used = client.post(
            reverse("admin_console:two-step-recovery"),
            {"code": codes[0], "next": "/admin/users/"},
            follow=True,
        )
        assert "9 of 10 left" in used.content.decode()
        assert client.get("/admin/marketplace/deals/").status_code == 200
        # A recovery code works once.
        again = Client()
        self.sign_in(again, ops)
        assert (
            again.post(
                reverse("admin_console:two-step-recovery"), {"code": codes[0]}
            ).status_code
            == 400
        )

        # The owner resets the lost second step: ops is signed out and enrols again.
        owners = Client()
        staff_login(owners, owner)
        reset = owners.post(
            reverse("admin_console:staff-two-step-reset", args=(ops.pk,)),
            {"reason": "Lost phone", "confirm": "on"},
        )
        assert reset.status_code == 302
        assert client.get("/admin/marketplace/deals/")["Location"].startswith(
            reverse("admin:login")
        )
        audit = AdminAuditLog.objects.get(action="admin.two_step_reset")
        assert (audit.actor, audit.reason) == (owner, "Lost phone")
        fresh = Client()
        self.sign_in(fresh, ops)
        back = fresh.get("/admin/marketplace/deals/", follow=True)
        assert back.redirect_chain[-1][0].startswith(enrol)


def seed_admin_roles() -> None:
    """The role groups and their capabilities, as the admin_panel migrations seed them."""

    holder, _ = ContentType.objects.get_or_create(
        app_label="admin_panel", model="adminauditlog"
    )
    for slug, codes in ROLE_PERMISSIONS.items():
        role_group(slug).permissions.add(
            *(
                Permission.objects.get_or_create(
                    content_type=holder,
                    codename=code,
                    defaults={"name": "Can " + code.replace("_", " ")},
                )[0]
                for code in codes
            )
        )


@override_settings(STORAGES=STATIC_STORES)
class ExportsReconcileTests(AcceptanceWorld, TransactionTestCase):
    """A transaction test: the dashboard reads its own standalone snapshot.

    TransactionTestCase empties every table between tests, so what the
    migrations seed and this test needs is seeded again here: the active
    settings revision (as the other transaction tests do) and the staff
    roles' capabilities.
    """

    def setUp(self):
        cache.clear()
        seed_business_settings()
        seed_admin_roles()
        self.build_acceptance_world()

    def download(self, client, kind: str, mode: str = "test") -> list[dict]:
        today = timezone.now().date()  # the frozen clock of the caller
        response = client.post(
            reverse("admin_console:finance-exports"),
            {
                "kind": kind,
                "mode": mode,
                "start": (today - timedelta(days=5)).isoformat(),
                "end": today.isoformat(),
            },
        )
        assert response.status_code == 200, response.content[:500]
        text = b"".join(response.streaming_content).decode("utf-8")
        return list(csv.DictReader(io.StringIO(text.lstrip("﻿"), newline="")))

    @staticmethod
    def cents(text: str) -> int:
        return int(Decimal(text) * 100)

    def test_the_three_exports_add_up_to_the_finance_dashboard(self):
        depart = self.now + timedelta(hours=3)
        journey = self.post_trip(
            [
                self.leg_payload(DRIVE, self.algiers, self.setif, depart, hours=3),
                self.leg_payload(
                    DRIVE,
                    self.setif,
                    self.constantine,
                    depart + timedelta(hours=4),
                    hours=2,
                ),
            ]
        )
        self.publish(journey)
        self.set_price(journey, 400, 1_000)
        journey.refresh_from_db()
        first, second = journey.legs.order_by("position")
        parcels = []
        for origin, destination, leg in (
            (self.algiers, self.setif, first),
            (self.setif, self.constantine, second),
        ):
            parcel = self.post_parcel(
                origin,
                destination,
                ready_from=leg.depart_at - timedelta(hours=1),
                ready_until=leg.depart_at + timedelta(minutes=30),
                deliver_by=leg.arrive_at + timedelta(hours=6),
            )
            self.pay_deposit(parcel)
            parcels.append((parcel, leg, self.tracking))
        # The second parcel is paid for, then the traveler does not come. It
        # goes first: carrying the other one runs every job due in the next
        # two days, the expiry of a parcel nobody accepted among them.
        parcel, leg, second_tracking = parcels[1]
        offer = self.propose(parcel, journey, leg, leg, 3_000)
        refunded = self.accept(offer)
        self.pay_balance(refunded)
        self.set_recipient(refunded)
        refunded.refresh_from_db()
        with freeze_at(refunded.agreed_pickup_at + timedelta(hours=1)):
            staff_login(self.client, self.trust)
            recorded = self.client.post(
                reverse("admin_console:deal-no-show", args=(refunded.pk,)),
                {"party": "traveler", "note": "Checked"},
            )
        assert recorded.status_code == 302
        delivered = self.carry(journey, parcels[0][0], first, first)

        # Read the day after: every money event of both deals is in the past.
        delivered.refresh_from_db()
        with (
            override_settings(**KEYRING),
            freeze_at(delivered.protection_ends_at + timedelta(days=1)),
        ):
            staff_login(self.client, self.finance)
            transactions = self.download(self.client, "transactions")
            commissions = self.download(self.client, "commissions")
            # Tests run without payout profiles, so this payout took the manual
            # path, which leaves its money mode unknown; production requires
            # profiles, whose snapshot records the mode (finance tests H1 to H7).
            payout_mode = Payout.objects.get(deal=delivered).provider_mode
            payouts = self.download(self.client, "payouts", payout_mode)
            board = build_snapshot(Scope.parse({"mode": "test"}))
            payout_board = build_snapshot(Scope.parse({"mode": payout_mode}))

        def total(key):
            return board["metrics"][key]["amount_eur_cents"]

        assert {row["Tracking number"] for row in commissions} == {
            delivered.delivery_request.tracking_number,
            second_tracking,
        }
        assert sum(self.cents(row["Fee kept"]) for row in commissions) == total(
            "recognized_revenue"
        )
        payments = [row for row in transactions if row["Type"] == "payment"]
        refunds = [row for row in transactions if row["Type"] == "refund"]
        assert sum(
            self.cents(r["Amount"]) for r in payments if r["Status"] == "succeeded"
        ) == total("gross_funded")
        assert sum(
            self.cents(r["Amount"]) for r in refunds if r["Status"] == "succeeded"
        ) == total("refunds_finalized")
        assert refunds, "the no-show refund is in the file"
        by_number = {row["Tracking number"]: row for row in payouts}
        assert set(by_number) == {
            delivered.delivery_request.tracking_number,
            second_tracking,
        }
        paid = by_number[delivered.delivery_request.tracking_number]
        assert paid["Status"] == "paid"
        assert (
            by_number[second_tracking]["Status"] != "paid"
        ), "a refunded deal pays no traveler"
        assert self.cents(paid["Amount"]) == delivered.terms.traveler_reward_minor
        # The paid payout is the dashboard's settled payout for its mode.
        settled = payout_board["metrics"]["payouts_settled"]["amount_eur_cents"]
        assert settled == self.cents(paid["Amount"]), settled
        assert (
            AdminAuditLog.objects.filter(
                action=AUDIT_ACTION, actor=self.finance
            ).count()
            == 3
        )
        # No email, phone or address reaches a cell.
        everything = json.dumps([transactions, commissions, payouts])
        for secret in (
            self.sender.email,
            self.traveler.email,
            "l10-recipient@example.invalid",
            "+213555000111",
        ):
            assert secret not in everything


class AccountClaimTests(TestCase):
    SIGN_UP = reverse("auth-sign-up")

    def squat(self, email: str):
        """Someone opens an account with an address that is not theirs, on their phone."""

        response = APIClient().post(
            self.SIGN_UP,
            {
                "email": email,
                "password": "Sup3rStrongPass!",
                "full_name": "Not The Owner",
                "phone": "+213555111444",
                "wilaya": "16",
                "preferred_language": "fr",
            },
            format="json",
        )
        assert response.status_code == 201, response.data
        user = User.objects.get(email=email)
        phone = api(user).post(
            reverse("notification-device-register"),
            {
                "token": f"fcm-token-{uuid.uuid4().hex}",
                "installation_id": str(uuid.uuid4()),
                "platform": "android",
            },
            format="json",
        )
        assert phone.status_code in (200, 201), phone.data
        return user, response.data["refresh"]

    @staticmethod
    def refresh_works(refresh: str) -> bool:
        return (
            APIClient()
            .post(reverse("auth-refresh"), {"refresh": refresh}, format="json")
            .status_code
            == 200
        )

    @staticmethod
    def pushes_reaching(user) -> int:
        with (
            override_settings(FCM_ENABLED=True),
            patch("apps.core.redis_bus.get_client"),
        ):
            return enqueue_fcm_for_event(
                channel=channels.PAYOUT_STATUS_CHANGED,
                event_id=str(uuid.uuid4()),
                payload={"status": "paid"},
                targets=[user.pk],
            )

    def test_the_owner_claims_the_account_with_google(self):
        user, refresh = self.squat("l10-google-owner@example.com")
        assert self.refresh_works(refresh) and self.pushes_reaching(user) == 1

        claim = {
            "sub": "sub-owner",
            "email": user.email,
            "email_verified": True,
            "name": "Real Owner",
        }
        with patch("apps.accounts.views.verify_id_token", return_value=claim):
            response = APIClient().post(
                reverse("auth-oauth-google"), {"id_token": "x"}, format="json"
            )
        assert response.status_code == 200, response.data

        assert not self.refresh_works(refresh), "the first person is signed out"
        assert self.pushes_reaching(user) == 0, "their phone is silent"
        assert not PushDevice.objects.filter(user=user, active=True).exists()
        account = User.objects.get(pk=user.pk)
        assert account.is_email_verified and not account.has_usable_password()
        assert account.full_name == "Real Owner"
        assert (
            APIClient()
            .post(
                reverse("auth-sign-in"),
                {"email": user.email, "password": "Sup3rStrongPass!"},
                format="json",
            )
            .status_code
            != 200
        )
        assert self.refresh_works(response.data["refresh"])

    def test_the_owner_claims_the_account_with_a_password_reset(self):
        user, refresh = self.squat("l10-reset-owner@example.com")
        asked = APIClient().post(
            reverse("auth-password-reset-request"), {"email": user.email}, format="json"
        )
        assert asked.status_code in (200, 202, 204), asked.data
        _, code = PasswordResetCode.issue(user)
        done = APIClient().post(
            reverse("auth-password-reset-confirm"),
            {"email": user.email, "code": code, "new_password": "OwnersOwnPass77!"},
            format="json",
        )
        assert done.status_code == 204, done.data

        assert not self.refresh_works(refresh)
        assert self.pushes_reaching(user) == 0
        assert User.objects.get(pk=user.pk).is_email_verified
        old = APIClient().post(
            reverse("auth-sign-in"),
            {"email": user.email, "password": "Sup3rStrongPass!"},
            format="json",
        )
        new = APIClient().post(
            reverse("auth-sign-in"),
            {"email": user.email, "password": "OwnersOwnPass77!"},
            format="json",
        )
        assert (old.status_code, new.status_code) == (400, 200), (old.data, new.data)
