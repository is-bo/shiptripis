"""Phase 8D operations-console contract tests.

These tests exercise the visible route boundary and the operator actions. The
existing REST/admin-service tests remain the authority for the domain rules;
this suite proves the HTML console does not bypass them or leak role-scoped
surfaces.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.admin_panel.console_forms import (
    FxSettingsForm,
    ManualPayoutForm,
    PricingSettingsForm,
)
from apps.admin_panel.console_views import _proof_summary
from apps.admin_panel.models import AdminAuditLog, AdminInvitation
from apps.admin_panel.permissions import AdminRole, assign_admin_roles, user_admin_roles
from apps.core.models import BusinessSettingsVersion
from apps.deals.tests.phase4_factories import delivered_scenario
from apps.disputes.models import Dispute
from apps.disputes.services import open_dispute
from apps.finance.models import LedgerTransaction, PaymentRefund, ScheduledJob
from apps.kyc.models import KycSubmission
from apps.locations.models import Country, GeographyCatalogueImport, Place
from apps.notifications.models import OutboundMessage
from apps.trips.models import Journey, JourneyLeg, JourneyLegProof


def _reachable_store(*, readable: bool = True) -> Mock:
    """A stand-in for one `apps.core.storage` class.

    `readable` is the fact that matters and the one the deployed failure turned
    on: presigning is local and always succeeds, so whether an object can be
    fetched is a separate question that has to be asked separately.
    """

    store = Mock()
    store.name = "kyc"
    store.bucket = "private-evidence"
    store.credential_source = "KYC_S3_*"
    store.readable.return_value = readable
    store.presigned_get.return_value = "https://private.example.test/signed"
    return store

User = get_user_model()

UNHASHED_STATIC = override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        },
    }
)


class ConsoleHttpMixin:
    def dispatch(self, path, method="get", data=None, user=None):
        self.client.force_login(user or self.owner)
        return getattr(self.client, method)(path, data or {})

    def staff_user(self, role, prefix="operator"):
        user = User.objects.create_user(
            username=f"{prefix}-{role}@example.com",
            email=f"{prefix}-{role}@example.com",
        )
        assign_admin_roles(user, (role,))
        return user


@UNHASHED_STATIC
class ConsoleAccessTests(ConsoleHttpMixin, TestCase):
    def setUp(self):
        self.owner = User.objects.create_superuser(
            username="owner-console@example.com",
            email="owner-console@example.com",
            password="Sup3rStrong!",
        )
        self.client.force_login(self.owner)

    def test_owner_lands_on_actionable_overview_and_can_reach_core_areas(self):
        response = self.dispatch("/admin/")
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn("What needs attention", body)
        self.assertIn("Action queues", body)
        self.assertIn("Business settings", body)
        self.assertIn("System", body)
        self.assertIn("Technical records", body)

    def test_support_navigation_does_not_expose_private_verification_or_finance(self):
        support = User.objects.create_user(
            username="support-console@example.com",
            email="support-console@example.com",
            password="Sup3rStrong!",
        )
        assign_admin_roles(support, (AdminRole.SUPPORT,))
        self.client.force_login(support)
        body = self.dispatch("/admin/", user=support).content.decode()
        self.assertIn("Users", body)
        self.assertIn("Disputes", body)
        self.assertNotIn("KYC review", body)
        self.assertNotIn("Flight proofs", body)
        self.assertNotIn("Business settings", body)
        self.assertNotIn("Payments", body)
        self.assertEqual(
            self.dispatch("/admin/verification/kyc/", user=support).status_code, 403
        )

    def test_authentication_and_csrf_are_enforced_by_middleware(self):
        self.client.logout()
        self.assertEqual(self.client.get("/admin/").status_code, 302)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        self.assertEqual(
            client.post("/admin/staff/", {"email": "no-csrf@example.com"}).status_code,
            403,
        )
        self.assertFalse(
            AdminInvitation.objects.filter(email="no-csrf@example.com").exists()
        )

    def test_support_cannot_mutate_staff_settings_finance_or_open_technical(self):
        support = self.staff_user(AdminRole.SUPPORT)
        for path in (
            "/admin/staff/",
            "/admin/settings/",
            "/admin/finance/payments/",
            "/admin/finance/refunds/",
            "/admin/finance/payouts/",
            "/admin/technical/",
        ):
            with self.subTest(path=path):
                self.assertEqual(
                    self.dispatch(path, method="post", user=support).status_code, 403
                )


@UNHASHED_STATIC
class ConsoleVerificationTests(ConsoleHttpMixin, TestCase):
    def setUp(self):
        self.owner = User.objects.create_superuser(
            username="trust-console@example.com",
            email="trust-console@example.com",
            password="Sup3rStrong!",
        )
        self.applicant = User.objects.create_user(
            username="applicant-console@example.com",
            email="applicant-console@example.com",
            password="Sup3rStrong!",
            full_name="Amina Applicant",
        )
        self.submission = KycSubmission.objects.create(
            user=self.applicant,
            document_type=KycSubmission.DocumentType.PASSPORT,
            idempotency_key="phase8d-console-kyc-00000000001",
            front_image_key="kyc/private/front.jpg",
            selfie_image_key="kyc/private/selfie.jpg",
            status=KycSubmission.Status.PENDING,
        )
        self.client.force_login(self.owner)

    @patch("apps.admin_panel.console_views.storage_for")
    def test_kyc_detail_has_evidence_action_and_reject_requires_reason(
        self, storage_for
    ):
        # The reachable case, stated explicitly since Phase 8F-C: with a store
        # that answers, the reviewer gets the evidence. The unreachable case is
        # its own test, because the two used to be indistinguishable.
        storage_for.return_value = _reachable_store()
        response = self.dispatch(f"/admin/verification/kyc/{self.submission.pk}/")
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn("View evidence, full size", body)
        self.assertNotIn("Evidence is temporarily unavailable", body)
        self.assertIn("Approve", body)
        self.assertIn("Reject", body)

        response = self.dispatch(
            f"/admin/verification/kyc/{self.submission.pk}/",
            method="post",
            data={"decision": "rejected", "confirm": "on"},
        )
        self.assertEqual(response.status_code, 200)
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.status, KycSubmission.Status.PENDING)

    def test_kyc_rejection_uses_audited_service(self):
        response = self.dispatch(
            f"/admin/verification/kyc/{self.submission.pk}/",
            method="post",
            data={
                "decision": "rejected",
                "reason": "The document image is unreadable.",
                "confirm": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.status, KycSubmission.Status.REJECTED)
        self.assertTrue(
            AdminAuditLog.objects.filter(
                action="kyc.rejected", target_id=str(self.submission.pk)
            ).exists()
        )

    def test_kyc_approve_is_confirmed_and_audited(self):
        trust = self.staff_user(AdminRole.TRUST)
        path = f"/admin/verification/kyc/{self.submission.pk}/"
        self.assertEqual(
            self.dispatch(path, "post", {"decision": "approved"}, trust).status_code,
            200,
        )
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.status, "pending")
        self.assertEqual(
            self.dispatch(
                path, "post", {"decision": "approved", "confirm": "on"}, trust
            ).status_code,
            302,
        )
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.status, "approved")
        self.assertTrue(
            AdminAuditLog.objects.filter(action="kyc.approved", actor=trust).exists()
        )

    @patch("apps.admin_panel.console_views.storage_for")
    def test_private_kyc_evidence_is_signed_audited_and_authorized(self, storage_for):
        store = _reachable_store()
        storage_for.return_value = store
        trust = self.staff_user(AdminRole.TRUST)
        path = f"/admin/verification/kyc/{self.submission.pk}/evidence/front/"
        response = self.dispatch(path, user=trust)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(response["Referrer-Policy"], "no-referrer")
        # Phase 8F-C: the KYC bucket is not Django's own, so the evidence path
        # must ask for the KYC storage class by name. Signing with the generic
        # credential produces a URL that is well-formed and then denied.
        self.assertEqual(storage_for.call_args.args[0], "kyc")
        self.assertEqual(
            store.presigned_get.call_args.args[0], self.submission.front_image_key
        )
        self.assertTrue(
            AdminAuditLog.objects.filter(
                action="kyc.evidence_viewed", actor=trust
            ).exists()
        )
        self.assertEqual(
            self.dispatch(path, user=self.staff_user(AdminRole.SUPPORT)).status_code,
            403,
        )
        self.assertEqual(store.presigned_get.call_count, 1)

    @patch("apps.admin_panel.console_views.storage_for")
    def test_storage_failure_is_actionable_without_exposing_raw_error(
        self, storage_for
    ):
        store = _reachable_store()
        store.presigned_get.side_effect = RuntimeError("storage-secret-sentinel")
        storage_for.return_value = store
        response = self.dispatch(
            f"/admin/verification/kyc/{self.submission.pk}/evidence/front/"
        )
        self.assertEqual(response.status_code, 302)
        body = self.dispatch(
            f"/admin/verification/kyc/{self.submission.pk}/"
        ).content.decode()
        self.assertIn("Private evidence access could not be completed", body)
        self.assertIn("Reference:", body)
        self.assertNotIn("storage-secret-sentinel", body)

    @patch("apps.admin_panel.console_views.storage_for")
    def test_unreadable_evidence_says_so_instead_of_rendering_a_dead_image(
        self, storage_for
    ):
        """Phase 8F-C: the failure the reviewer actually saw.

        Django presigned the KYC bucket with a credential that has no grant on
        it. Signing succeeded — it is local HMAC — so the page rendered an
        `<img>` whose fetch was then refused, and the reviewer got a broken
        image indistinguishable from a submission with no document at all.
        """

        store = _reachable_store(readable=False)
        storage_for.return_value = store
        trust = self.staff_user(AdminRole.TRUST)

        body = self.dispatch(
            f"/admin/verification/kyc/{self.submission.pk}/", user=trust
        ).content.decode()

        self.assertIn("Evidence is temporarily unavailable", body)
        # Never a URL the browser is about to be denied.
        self.assertEqual(store.presigned_get.call_count, 0)
        # And none of the things a storage error would otherwise leak.
        self.assertNotIn(self.submission.front_image_key, body)
        self.assertNotIn("AccessDenied", body)
        self.assertNotIn("shiptrip-kyc", body)

        # Following the link is refused with the same sentence, not a 500.
        response = self.dispatch(
            f"/admin/verification/kyc/{self.submission.pk}/evidence/front/",
            user=trust,
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(store.presigned_get.call_count, 0)

    def test_a_submission_with_no_document_is_not_a_storage_failure(self):
        """"Nothing was submitted" and "we cannot fetch it" are different."""

        self.submission.front_image_key = ""
        self.submission.back_image_key = ""
        self.submission.selfie_image_key = ""
        self.submission.save()

        body = self.dispatch(
            f"/admin/verification/kyc/{self.submission.pk}/",
            user=self.staff_user(AdminRole.TRUST),
        ).content.decode()

        self.assertIn("No evidence file was attached", body)
        self.assertNotIn("Evidence is temporarily unavailable", body)

    def test_trust_can_open_flight_proof_queue_and_support_is_blocked(self):
        trust = User.objects.create_user(
            username="trust-proof-console@example.com",
            email="trust-proof-console@example.com",
            password="Sup3rStrong!",
        )
        assign_admin_roles(trust, (AdminRole.TRUST,))
        response = self.dispatch(
            "/admin/verification/flight-proofs/?status=pending", user=trust
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Flight-proof review", response.content.decode())
        self.assertIn("No flight proofs waiting", response.content.decode())

        support = User.objects.create_user(
            username="support-proof-console@example.com",
            email="support-proof-console@example.com",
            password="Sup3rStrong!",
        )
        assign_admin_roles(support, (AdminRole.SUPPORT,))
        self.assertEqual(
            self.dispatch(
                "/admin/verification/flight-proofs/?status=pending", user=support
            ).status_code,
            403,
        )

    def proof(self, *, journey=None, position=0):
        journey = journey or Journey.objects.create(traveler=self.applicant)
        leg = JourneyLeg.objects.create(
            journey=journey,
            position=position,
            mode="FLIGHT",
            depart_at=timezone.now() + timedelta(days=2),
            capacity_kg="5.00",
            flight_number="AH1006",
        )
        return JourneyLegProof.objects.create(
            leg=leg, bucket="private-proof", object_key=f"journeys/{leg.pk}/proof.jpg"
        )

    @patch("apps.admin_panel.console_views.store_for_bucket")
    def test_flight_proof_evidence_and_both_decisions_are_authorized_and_audited(
        self, store_for_bucket
    ):
        store_for_bucket.return_value = _reachable_store()
        trust = self.staff_user(AdminRole.TRUST)
        support = self.staff_user(AdminRole.SUPPORT)
        for decision in ("approved", "rejected"):
            proof = self.proof()
            path = f"/admin/verification/flight-proofs/{proof.pk}/"
            body = self.dispatch(path, user=trust).content.decode()
            self.assertIn("AH1006", body)
            self.assertIn(f"{path}evidence/", body)
            self.assertNotIn(proof.object_key, body)
            self.assertEqual(
                self.dispatch(path + "evidence/", user=trust).status_code, 302
            )
            self.assertEqual(
                self.dispatch(path + "evidence/", user=support).status_code, 403
            )
            self.assertEqual(
                self.dispatch(
                    path,
                    "post",
                    {
                        "decision": decision,
                        "confirm": "on",
                        "reason": "Unclear flight details",
                    },
                    trust,
                ).status_code,
                302,
            )
            proof.refresh_from_db()
            self.assertEqual(proof.status, decision)
            self.assertTrue(
                AdminAuditLog.objects.filter(
                    action=f"flight_proof.{decision}", target_id=str(proof.pk)
                ).exists()
            )

    def test_proof_summary_requires_approval_for_every_flight_leg(self):
        proof = self.proof()
        JourneyLegProof.objects.filter(pk=proof.pk).update(
            status="approved", reviewer=self.owner, reviewed_at=timezone.now()
        )
        journey = proof.leg.journey
        self.assertEqual(_proof_summary(journey), ("Approved", "ok"))
        JourneyLeg.objects.create(
            journey=journey,
            position=1,
            mode="FLIGHT",
            depart_at=timezone.now(),
            capacity_kg="5.00",
        )
        self.assertEqual(_proof_summary(journey), ("Missing", "bad"))


@UNHASHED_STATIC
class ConsoleOwnerWorkflowTests(ConsoleHttpMixin, TestCase):
    def setUp(self):
        self.owner = User.objects.create_superuser(
            username="owner-workflow@example.com",
            email="owner-workflow@example.com",
            password="Sup3rStrong!",
        )
        self.client.force_login(self.owner)

    def test_owner_can_reach_operational_queues_and_safe_system_view(self):
        surfaces = (
            ("/admin/disputes/", "Disputes"),
            ("/admin/finance/payments/", "Payments"),
            ("/admin/finance/refunds/", "Refunds"),
            ("/admin/finance/payouts/", "Payouts"),
            ("/admin/finance/ledger/", "Ledger"),
            ("/admin/staff/", "Staff"),
            ("/admin/settings/", "Business settings"),
            # Escaped, because the console now emits a well-formed entity for
            # the ampersand instead of a raw one.
            ("/admin/system/", "System &amp; operations"),
        )
        with override_settings(REDIS_URL="redis://127.0.0.1:6399/0"):
            for path, heading in surfaces:
                with self.subTest(path=path):
                    response = self.dispatch(path)
                    self.assertEqual(response.status_code, 200)
                    body = response.content.decode()
                    self.assertIn(heading, body)
                    if path == "/admin/system/":
                        self.assertNotIn("STRIPE_SECRET_KEY", body)
                        self.assertNotIn("SMTP_PASSWORD", body)

    @patch("apps.notifications.outbox.enqueue_secret_message")
    def test_staff_invite_is_pending_and_audited(self, enqueue_secret):
        response = self.dispatch(
            "/admin/staff/",
            method="post",
            data={
                "email": "new-ops-console@example.com",
                "role": AdminRole.OPS,
                "expires_in_hours": "24",
            },
        )
        self.assertEqual(response.status_code, 302)
        invitation = AdminInvitation.objects.get(email="new-ops-console@example.com")
        self.assertTrue(invitation.is_active)
        self.assertEqual(invitation.role, AdminRole.OPS)
        self.assertTrue(enqueue_secret.called)
        self.assertTrue(
            AdminAuditLog.objects.filter(
                action="admin_invitation.created", target_id=str(invitation.pk)
            ).exists()
        )

    def test_settings_use_human_units_and_validate_before_save(self):
        response = self.dispatch("/admin/settings/")
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn("ShipTrip commission", body)
        self.assertIn("DZD for €1", body)
        self.assertIn("Payout protection window", body)
        for secret_name in ("STRIPE_SECRET_KEY", "CHARGILY_API_KEY", "SMTP_PASSWORD"):
            self.assertNotIn(secret_name, body)

        invalid = PricingSettingsForm(
            data={
                "commission_percent": "25",
                "deposit_percent": "10",
                "deposit_min_eur": "8",
                "deposit_max_eur": "3",
                "global_floor_eur": "20",
                "weight_rate_eur": "2",
                "recommendation_multiplier_percent": "100",
                "reason": "test",
                "confirm": "on",
            }
        )
        self.assertFalse(invalid.is_valid())
        self.assertIn("deposit_max_eur", invalid.errors)

        fx = FxSettingsForm(
            data={
                "eur_dzd_rate": "145.250000",
                "reason": "Treasury quote",
                "confirm": "on",
            }
        )
        self.assertTrue(fx.is_valid())
        self.assertEqual(fx.rate_micros(), 145_250_000)

    def test_manual_payout_respects_currency_units_and_rejects_fractional_dinars(self):
        data = {
            "payout_currency": "DZD",
            "payout_amount": "1500",
            "fx_rate": "150",
            "reference": "bank-123",
            "confirm": "on",
        }
        form = ManualPayoutForm(data)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.service_values()["payout_amount_minor"], 1500)
        invalid = ManualPayoutForm({**data, "payout_amount": "1500.50"})
        self.assertFalse(invalid.is_valid())
        euro = ManualPayoutForm(
            {**data, "payout_currency": "EUR", "payout_amount": "10.25"}
        )
        self.assertTrue(euro.is_valid(), euro.errors)
        self.assertEqual(euro.service_values()["payout_amount_minor"], 1025)

    def test_fx_update_creates_audited_immutable_revision(self):
        before = BusinessSettingsVersion.objects.count()
        response = self.dispatch(
            "/admin/settings/",
            method="post",
            data={
                "action": "fx",
                "eur_dzd_rate": "145.250000",
                "reason": "Treasury quote",
                "confirm": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(BusinessSettingsVersion.objects.count(), before + 1)
        active = BusinessSettingsVersion.objects.get(status="active")
        self.assertEqual(
            active.policy["payments"]["chargily"]["eur_dzd_rate_micros"],
            145_250_000,
        )
        self.assertTrue(
            AdminAuditLog.objects.filter(action="settings.version_created").exists()
        )

    def test_commission_update_preserves_old_revision_and_audits_human_input(self):
        active = BusinessSettingsVersion.objects.get(status="active")
        before_rate = active.commission_rate_bps
        response = self.dispatch("/admin/settings/")
        initial = response.context["pricing_form"].initial
        response = self.dispatch(
            "/admin/settings/",
            "post",
            {
                **initial,
                "action": "pricing",
                "commission_percent": "27.50",
                "reason": "Reviewed commercial pricing",
                "confirm": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        active.refresh_from_db()
        self.assertEqual(active.commission_rate_bps, before_rate)
        self.assertEqual(
            BusinessSettingsVersion.objects.get(status="active").commission_rate_bps,
            2750,
        )
        audit = AdminAuditLog.objects.get(action="settings.version_created")
        self.assertEqual(audit.before["commission_rate_bps"], before_rate)
        self.assertEqual(audit.after["commission_rate_bps"], 2750)

    @patch("apps.notifications.outbox.enqueue_secret_message")
    def test_staff_pending_role_access_and_revocation_require_confirmation(
        self, enqueue_secret
    ):
        self.dispatch(
            "/admin/staff/",
            "post",
            {
                "email": "invite-task@example.com",
                "role": AdminRole.SUPPORT,
                "expires_in_hours": 24,
            },
        )
        invitation = AdminInvitation.objects.get(email="invite-task@example.com")
        body = self.dispatch("/admin/staff/").content.decode()
        self.assertIn("Pending acceptance", body)
        self.assertNotIn(invitation.token_hash, body)
        path = f"/admin/staff/invitations/{invitation.pk}/revoke/"
        self.dispatch(path, "post")
        invitation.refresh_from_db()
        self.assertTrue(invitation.is_active)
        self.dispatch(path, "post", {"confirm": "yes"})
        invitation.refresh_from_db()
        self.assertFalse(invitation.is_active)
        self.assertTrue(
            AdminAuditLog.objects.filter(
                action="admin_invitation.revoked", target_id=str(invitation.pk)
            ).exists()
        )

        member = self.staff_user(AdminRole.SUPPORT)
        self.dispatch(
            f"/admin/staff/{member.pk}/role/",
            "post",
            {"role": AdminRole.FINANCE, "confirm": "on"},
        )
        member.refresh_from_db()
        self.assertEqual(user_admin_roles(member), (AdminRole.FINANCE,))
        access_path = f"/admin/staff/{member.pk}/access/"
        self.dispatch(access_path, "post", {"enabled": "False"})
        member.refresh_from_db()
        self.assertTrue(member.is_active)
        self.dispatch(access_path, "post", {"enabled": "False", "confirm": "on"})
        member.refresh_from_db()
        self.assertFalse(member.is_active)
        self.assertTrue(
            AdminAuditLog.objects.filter(
                action="admin.access_disabled", target_id=str(member.pk)
            ).exists()
        )

    def test_overview_links_to_filtered_failed_work_without_exposing_payloads(self):
        ScheduledJob.objects.create(
            key="console-failed",
            kind=ScheduledJob.Kind.PROVIDER_RECONCILE,
            status="failed",
            run_at=timezone.now(),
            payload={"secret": "never-render-job-secret"},
        )
        OutboundMessage.objects.create(
            key="console-failed-mail",
            kind=OutboundMessage.Kind.KYC_STATUS,
            to_email="person@example.com",
            status="failed",
            secret_ref="never-render-mail-secret",
            context={"token": "never-render-context"},
        )
        body = self.dispatch("/admin/").content.decode()
        self.assertIn("2 queues with work waiting", body)
        for path in (
            "/admin/system/jobs/?status=failed",
            "/admin/system/email/?status=failed",
        ):
            self.assertIn(path, body)
            response = self.dispatch(path)
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("never-render", response.content.decode())
            self.assertEqual(response.context["page_obj"].paginator.count, 1)


@UNHASHED_STATIC
class ConsoleDisputeFinanceTests(ConsoleHttpMixin, TestCase):
    def setUp(self):
        self.owner = User.objects.create_superuser(
            username="finance-console@example.com",
            email="finance-console@example.com",
            password="Sup3rStrong!",
        )
        self.scenario = delivered_scenario(self.client, prefix="console-finance")
        self.dispute = open_dispute(
            deal_id=self.scenario.deal.pk,
            actor_id=self.scenario.sender.pk,
            category=Dispute.Category.DAMAGED,
            reason_text="Parcel damaged during transport.",
        )
        self.path = f"/admin/disputes/{self.dispute.pk}/"

    def test_dispute_detail_has_money_handover_and_role_safe_resolution(self):
        body = self.dispatch(self.path).content.decode()
        for label in (
            "Sender total",
            "Traveler reward",
            "ShipTrip fee",
            "Pickup confirmed",
            "Delivery confirmed",
            "Preview consequence",
        ):
            self.assertIn(label, body)
        support = self.staff_user(AdminRole.SUPPORT)
        body = self.dispatch(self.path, user=support).content.decode()
        self.assertNotIn("Preview consequence", body)
        self.assertNotIn(self.dispute.reason_text, body)
        self.assertEqual(
            self.dispatch(
                self.path,
                "post",
                {"action": "preview-resolution", "resolution": "full_sender_refund"},
                support,
            ).status_code,
            403,
        )

    def test_resolution_preview_writes_nothing_and_confirmation_is_audited(self):
        data = {
            "action": "preview-resolution",
            "resolution": "full_sender_refund",
            "note": "Evidence supports refund",
        }
        refunds_before = PaymentRefund.objects.count()
        ledger_before = LedgerTransaction.objects.count()
        response = self.dispatch(self.path, "post", data)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Server-validated consequence", response.content.decode())
        self.assertEqual(PaymentRefund.objects.count(), refunds_before)
        self.assertEqual(LedgerTransaction.objects.count(), ledger_before)
        self.dispute.refresh_from_db()
        self.assertTrue(self.dispute.is_active)
        self.dispatch(self.path, "post", {**data, "action": "confirm-resolution"})
        self.dispute.refresh_from_db()
        self.assertTrue(self.dispute.is_active)
        response = self.dispatch(
            self.path,
            "post",
            {**data, "action": "confirm-resolution", "confirm_resolution": "yes"},
        )
        self.assertEqual(response.status_code, 302)
        self.dispute.refresh_from_db()
        self.assertEqual(self.dispute.status, "resolved")
        self.assertTrue(
            AdminAuditLog.objects.filter(
                action="dispute.resolved", target_id=str(self.dispute.pk)
            ).exists()
        )
        count = PaymentRefund.objects.count()
        self.dispatch(
            self.path,
            "post",
            {**data, "action": "confirm-resolution", "confirm_resolution": "yes"},
        )
        self.assertEqual(PaymentRefund.objects.count(), count)

    def test_finance_lists_show_formatted_money_and_refund_form_needs_confirmation(
        self,
    ):
        finance = self.staff_user(AdminRole.FINANCE)
        response = self.dispatch("/admin/finance/payments/", user=finance)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Canonical EUR", response.content.decode())
        self.assertIn("€", response.content.decode())
        payout = self.scenario.deal.payout
        response = self.dispatch(f"/admin/finance/payouts/{payout.pk}/", user=finance)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Frozen", response.content.decode())
        attempt = self.scenario.base.balance_order().attempts.get(status="succeeded")
        before = PaymentRefund.objects.count()
        response = self.dispatch(
            f"/admin/finance/refunds/new/{attempt.pk}/",
            "post",
            {"amount_eur": "1.00", "reason": PaymentRefund.Reason.DISPUTE_RESOLUTION},
            finance,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(PaymentRefund.objects.count(), before)

    def test_finance_refund_request_creates_an_audited_obligation(self):
        finance = self.staff_user(AdminRole.FINANCE)
        attempt = self.scenario.base.balance_order().attempts.get(status="succeeded")
        response = self.dispatch(
            f"/admin/finance/refunds/new/{attempt.pk}/",
            "post",
            {
                "amount_eur": "1.00",
                "reason": PaymentRefund.Reason.DISPUTE_RESOLUTION,
                "confirm": "on",
            },
            finance,
        )
        self.assertEqual(response.status_code, 302)
        refund = PaymentRefund.objects.get(attempt=attempt)
        self.assertEqual(refund.amount_eur_cents, 100)
        self.assertTrue(
            AdminAuditLog.objects.filter(
                action="refund.requested", target_id=str(refund.pk), actor=finance
            ).exists()
        )
        self.assertEqual(
            self.dispatch(
                f"/admin/finance/refunds/{refund.pk}/", user=finance
            ).status_code,
            200,
        )


@UNHASHED_STATIC
class GeographyConsoleTests(ConsoleHttpMixin, TestCase):
    """The catalogue page has to answer "did the reviewed data land?".

    Row counts cannot distinguish a complete catalogue from a superseded or a
    half-applied one, and this is the page an operator opens after a deploy to
    decide whether the release is usable at all — canonical place selection
    gates every request and journey.
    """

    def setUp(self):
        self.owner = User.objects.create_superuser(
            username="owner-geography@example.com",
            email="owner-geography@example.com",
            password="Sup3rStrong!",
        )

    def test_an_empty_catalogue_says_so_rather_than_showing_a_tidy_zero(self):
        response = self.dispatch(reverse("admin_console:geography"))

        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        assert "No catalogue import is recorded" in body
        assert "geography catalogue import FAILED" in body

    def test_an_applied_catalogue_names_the_manifest_it_came_from(self):
        GeographyCatalogueImport.objects.create(
            content_sha256="b4aad209f4ae7ecb264fc9ae4b5d9b4b61b7ff9d918ca470729db93d1abb7692",
            counts={"places": 56134},
            applied_by_release="v1.0.0-rc.2+abcdef1",
        )
        country = Country.objects.create(
            code="DZ", name="Algeria", source="test", source_id="DZ"
        )
        Place.objects.create(
            country=country,
            place_type=Place.PlaceType.ADMIN_REGION,
            source="test-region",
            source_id="DZ-18",
            source_version="test",
            name="Jijel",
            admin_level="wilaya",
        )

        response = self.dispatch(reverse("admin_console:geography"))

        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        # The digest is truncated for reading, not hidden.
        assert "b4aad209f4ae7ecb" in body
        assert "v1.0.0-rc.2+abcdef1" in body
        assert "No catalogue import is recorded" not in body

