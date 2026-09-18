"""Phase 6C financial and guest transactional-email obligations."""

from __future__ import annotations

import json

from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.deals.tests.phase4_factories import enable_mock_rail
from apps.notifications.models import OutboundMessage

from ..models import PaymentAttempt, PaymentRefund
from ..services import (
    create_guest_link,
    mark_refund_succeeded,
    reconcile_attempt,
    request_refund,
    start_checkout,
)
from .factories import build_scenario, open_mock_checkout, pay_order_with_mock


class PaymentFailureEmailTests(TestCase):
    def setUp(self):
        enable_mock_rail()
        self.scenario = build_scenario(prefix="p6c-pay-failed")
        self.scenario.sender.preferred_language = "fr"
        self.scenario.sender.save(update_fields=("preferred_language",))
        self.scenario.accept()
        self.order = self.scenario.balance_order()

    def test_only_authoritative_failed_state_queues_email_and_replay_is_safe(self):
        attempt = open_mock_checkout(self.order)

        self.assertEqual(
            reconcile_attempt(attempt_id=attempt.pk, outcome="processing"),
            "attempt_processing",
        )
        self.assertFalse(
            OutboundMessage.objects.filter(
                kind=OutboundMessage.Kind.PAYMENT_FAILED
            ).exists()
        )

        self.assertEqual(
            reconcile_attempt(
                attempt_id=attempt.pk,
                outcome="failed",
                failure_code="provider_declined",
            ),
            "attempt_failed",
        )
        self.assertEqual(
            reconcile_attempt(
                attempt_id=attempt.pk,
                outcome="failed",
                failure_code="duplicate_event",
            ),
            "already_terminal",
        )

        message = OutboundMessage.objects.get(
            key=f"payment_failed:attempt:{attempt.pk}:owner"
        )
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, PaymentAttempt.Status.FAILED)
        self.assertEqual(message.language, "fr")
        self.assertEqual(message.context["status"], "failed")
        self.assertEqual(message.context["amount_eur_cents"], attempt.amount_eur_cents)

    def test_expiry_is_not_described_as_provider_failure(self):
        attempt = open_mock_checkout(self.order)

        reconcile_attempt(attempt_id=attempt.pk, outcome="expired")

        attempt.refresh_from_db()
        self.assertEqual(attempt.status, PaymentAttempt.Status.EXPIRED)
        self.assertFalse(
            OutboundMessage.objects.filter(
                kind=OutboundMessage.Kind.PAYMENT_FAILED
            ).exists()
        )

    def test_late_authoritative_success_cancels_pending_failure_notice(self):
        attempt = open_mock_checkout(self.order)
        reconcile_attempt(attempt_id=attempt.pk, outcome="failed")

        result = reconcile_attempt(
            attempt_id=attempt.pk,
            outcome="succeeded",
            provider_payment_id="late-success",
            provider_amount_minor=attempt.provider_amount_minor,
            provider_currency=attempt.payment_currency,
        )

        self.assertEqual(result, "applied")
        message = OutboundMessage.objects.get(
            key=f"payment_failed:attempt:{attempt.pk}:owner"
        )
        self.assertEqual(message.status, OutboundMessage.Status.CANCELLED)


class RefundStatusEmailTests(TestCase):
    def setUp(self):
        enable_mock_rail()
        self.scenario = build_scenario(prefix="p6c-refund")
        self.scenario.sender.preferred_language = "ar"
        self.scenario.sender.save(update_fields=("preferred_language",))
        self.scenario.accept()
        self.order = self.scenario.balance_order()
        self.attempt = pay_order_with_mock(self.client, self.order)

    def test_pending_and_completed_refund_are_authoritative_and_idempotent(self):
        key = f"phase6c-refund:{self.attempt.pk}"
        refund = request_refund(
            order_id=self.order.pk,
            attempt_id=self.attempt.pk,
            amount_eur_cents=500,
            reason=PaymentRefund.Reason.ADMIN,
            requested_by_id=self.scenario.admin.pk,
            idempotency_key=key,
        )
        same = request_refund(
            order_id=self.order.pk,
            attempt_id=self.attempt.pk,
            amount_eur_cents=500,
            reason=PaymentRefund.Reason.ADMIN,
            requested_by_id=self.scenario.admin.pk,
            idempotency_key=key,
        )
        self.assertEqual(refund.pk, same.pk)

        mark_refund_succeeded(refund_id=refund.pk, provider_refund_id="refund-p6c")
        mark_refund_succeeded(refund_id=refund.pk, provider_refund_id="duplicate")

        messages = OutboundMessage.objects.filter(
            kind=OutboundMessage.Kind.REFUND_STATUS,
            recipient_user=self.scenario.sender,
        ).order_by("created_at")
        self.assertEqual(messages.count(), 2)
        self.assertEqual(
            {row.context["status"] for row in messages}, {"pending", "succeeded"}
        )
        self.assertTrue(all(row.language == "ar" for row in messages))
        self.assertTrue(
            all(row.context["amount_eur_cents"] == 500 for row in messages)
        )


class GuestPaymentEmailTests(TestCase):
    def setUp(self):
        enable_mock_rail()
        self.scenario = build_scenario(prefix="p6c-guest-email")
        self.scenario.accept()
        self.order = self.scenario.balance_order()
        self.issued = create_guest_link(
            order_id=self.order.pk,
            actor_id=self.scenario.sender.pk,
            communication_language="fr",
        )

    def test_guest_link_api_validates_and_returns_resolved_language(self):
        client = APIClient()
        client.force_authenticate(self.scenario.sender)
        endpoint = reverse(
            "finance-order-guest-link", args=[str(self.order.public_reference)]
        )

        response = client.post(
            endpoint, {"communication_language": "ar"}, format="json"
        )
        # J7C: the live link is re-shared rather than replaced, and the explicit
        # receipt language still lands on it.
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["reused"])
        self.assertEqual(response.data["token"], self.issued.token)
        self.assertEqual(response.data["communication_language"], "ar")
        self.issued.link.refresh_from_db()
        self.assertEqual(self.issued.link.communication_language, "ar")

        invalid = client.post(
            endpoint, {"communication_language": "de"}, format="json"
        )
        self.assertEqual(invalid.status_code, 400)

    def test_success_receipt_is_localized_and_contains_only_payment_facts(self):
        attempt = start_checkout(
            order_id=self.order.pk,
            provider="mock",
            actor_id=None,
            guest_link=self.issued.link,
            guest_email="guest-payer@example.test",
        ).attempt

        reconcile_attempt(
            attempt_id=attempt.pk,
            outcome="succeeded",
            provider_payment_id="p6c-guest-payment",
            provider_amount_minor=attempt.provider_amount_minor,
            provider_currency=attempt.payment_currency,
        )

        message = OutboundMessage.objects.get(
            key=f"guest_payment:attempt:{attempt.pk}:succeeded"
        )
        self.assertEqual(message.to_email, "guest-payer@example.test")
        self.assertEqual(message.language, "fr")
        self.assertIsNone(message.deal_id)
        self.assertEqual(
            set(message.context),
            {"payment_reference", "amount_eur_cents", "currency", "status"},
        )
        serialized = json.dumps(message.context)
        for private_value in (
            self.scenario.sender.email,
            self.scenario.traveler.email,
            self.scenario.delivery_request.pickup_location.private_label,
            self.scenario.delivery_request.delivery_location.private_label,
            self.issued.token,
        ):
            self.assertNotIn(str(private_value), serialized)

    def test_guest_does_not_reuse_an_account_holders_open_attempt(self):
        owner_attempt = open_mock_checkout(self.order)

        guest_attempt = start_checkout(
            order_id=self.order.pk,
            provider="mock",
            actor_id=None,
            guest_link=self.issued.link,
            guest_email="guest-payer@example.test",
        ).attempt

        owner_attempt.refresh_from_db()
        self.assertNotEqual(guest_attempt.pk, owner_attempt.pk)
        self.assertEqual(owner_attempt.status, PaymentAttempt.Status.CANCELLED)
        self.assertEqual(guest_attempt.guest_link_id, self.issued.link.pk)
        self.assertEqual(guest_attempt.guest_email, "guest-payer@example.test")

    def test_failed_guest_payment_gets_one_minimal_status_message(self):
        attempt = start_checkout(
            order_id=self.order.pk,
            provider="mock",
            actor_id=None,
            guest_link=self.issued.link,
            guest_email="guest-payer@example.test",
        ).attempt

        reconcile_attempt(attempt_id=attempt.pk, outcome="failed")
        reconcile_attempt(attempt_id=attempt.pk, outcome="failed")

        message = OutboundMessage.objects.get(
            key=f"guest_payment:attempt:{attempt.pk}:failed"
        )
        self.assertEqual(message.language, "fr")
        self.assertEqual(message.context["status"], "failed")
        self.assertIsNone(message.recipient_user_id)
        self.assertIsNone(message.deal_id)

    def test_late_guest_success_cancels_failure_and_queues_receipt(self):
        attempt = start_checkout(
            order_id=self.order.pk,
            provider="mock",
            actor_id=None,
            guest_link=self.issued.link,
            guest_email="guest-payer@example.test",
        ).attempt
        reconcile_attempt(attempt_id=attempt.pk, outcome="failed")

        reconcile_attempt(
            attempt_id=attempt.pk,
            outcome="succeeded",
            provider_payment_id="late-guest-success",
            provider_amount_minor=attempt.provider_amount_minor,
            provider_currency=attempt.payment_currency,
        )

        failed = OutboundMessage.objects.get(
            key=f"guest_payment:attempt:{attempt.pk}:failed"
        )
        receipt = OutboundMessage.objects.get(
            key=f"guest_payment:attempt:{attempt.pk}:succeeded"
        )
        self.assertEqual(failed.status, OutboundMessage.Status.CANCELLED)
        self.assertEqual(receipt.status, OutboundMessage.Status.PENDING)

    @override_settings(TRANSACTIONAL_EMAIL_ENABLED=True)
    def test_enabled_guest_checkout_requires_receipt_email(self):
        response = APIClient().post(
            reverse("finance-guest-checkout", args=[self.issued.token]),
            {"provider": "mock"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("email", response.data)
        self.assertFalse(PaymentAttempt.objects.filter(order=self.order).exists())

    @override_settings(TRANSACTIONAL_EMAIL_ENABLED=True)
    def test_enabled_guest_checkout_validates_and_keeps_email_private(self):
        endpoint = reverse("finance-guest-checkout", args=[self.issued.token])

        invalid = APIClient().post(
            endpoint,
            {"provider": "mock", "email": "not-an-email"},
            format="json",
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertIn("email", invalid.data)
        self.assertFalse(PaymentAttempt.objects.filter(order=self.order).exists())

        response = APIClient().post(
            endpoint,
            {"provider": "mock", "email": "guest-payer@example.test"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertNotIn("email", response.data)
        self.assertEqual(
            PaymentAttempt.objects.get(order=self.order).guest_email,
            "guest-payer@example.test",
        )
