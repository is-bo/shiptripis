"""Rule G-D: every reported payment is accounted for before the order collects again.

Three facts are kept apart: whether a checkout can still collect (finality),
whether its provider reported a payment (evidence), and what became of that
money (disposition). A payment whose report cannot be verified is held: the
order takes no new payment until the hold ends in one of the five ways the
plan names (G1-A).
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from unittest import mock

from django.test import TestCase
from django.urls import reverse

from apps.core.business_settings import get_active_business_settings
from apps.core.models import BusinessSettingsVersion
from apps.finance import jobs
from apps.finance.models import (
    LedgerTransaction,
    PaymentAttempt,
    PaymentOrder,
    ScheduledJob,
)
from apps.finance.operations import resolve_payment_attention
from apps.finance.providers.mock import MockGateway
from apps.finance.services import (
    FinanceError,
    create_guest_link,
    reconcile_attempt,
    resolve_guest_link,
    settle_checkout,
    start_checkout,
)
from apps.notifications.models import OutboundMessage

from .factories import build_scenario, deliver_mock_webhook, mock_event_body


def _enable_mock():
    settings_version = get_active_business_settings()
    policy = deepcopy(settings_version.policy)
    policy["payments"]["providers"]["mock_enabled"] = True
    BusinessSettingsVersion.objects.filter(pk=settings_version.pk).update(
        policy=policy
    )


class HeldPaymentTestCase(TestCase):
    def setUp(self):
        _enable_mock()
        MockGateway.reset()
        self.scenario = build_scenario(prefix="held")
        self.scenario.accept(reward_eur_cents=3_200)
        self.order = self.scenario.balance_order()
        self.owner = self.scenario.sender
        self.token = create_guest_link(
            order_id=self.order.pk, actor_id=self.owner.pk
        ).token

    def owner_taps(self):
        return start_checkout(
            order_id=self.order.pk, provider="mock", actor_id=self.owner.pk
        )

    def guest_taps(self):
        return start_checkout(
            order_id=self.order.pk,
            provider="mock",
            actor_id=None,
            guest_link=resolve_guest_link(self.token),
        )

    def report(self, attempt, *, event_id, outcome="succeeded", **data):
        """A signed provider event about `attempt`'s checkout, through the webhook."""

        fields = {
            "amount": int(attempt.provider_amount_minor),
            "currency": attempt.payment_currency,
            "payment_id": f"{attempt.provider_session_id}_pi",
        }
        fields.update(data)
        body = mock_event_body(
            event_id=event_id,
            outcome=outcome,
            session_id=attempt.provider_session_id,
            event_type="checkout.updated",
            **fields,
        )
        assert deliver_mock_webhook(self.client, body).status_code == 200

    def held(self, *, amount_delta=None, **data):
        """The owner's checkout, its payment reported with `data` and held."""

        attempt = self.owner_taps().attempt
        if amount_delta is not None:
            data["amount"] = int(attempt.provider_amount_minor) + amount_delta
        self.report(attempt, event_id=f"evt_held_{attempt.pk}", **data)
        attempt.refresh_from_db()
        assert attempt.status == PaymentAttempt.Status.FAILED
        return attempt

    def payments(self, attempt) -> int:
        return LedgerTransaction.objects.filter(
            key=f"customer_payment:attempt:{attempt.pk}"
        ).count()

    def settle_job(self, attempt):
        return ScheduledJob.objects.get(key=f"provider_reconcile:{attempt.pk}")


class RoundSevenFindingTests(HeldPaymentTestCase):
    """The three round-7 findings G1-A closes, reproduced first."""

    def test_a_held_payment_stops_every_new_checkout(self):
        """Blocker 1: a payment whose amount cannot be accepted did not stop a
        new checkout, and the owner was told nothing was charged."""

        own = self.held(amount_delta=1)

        for tap in (self.owner_taps, self.guest_taps):
            with self.subTest(tap.__name__), self.assertRaises(FinanceError) as caught:
                tap()
            assert caught.exception.code == "payment_under_review"
        assert list(PaymentAttempt.objects.filter(order=self.order)) == [own]
        # Nothing says nothing was charged: no payment-failed email, and the
        # page the payer returns to does not say the payment failed.
        assert not OutboundMessage.objects.filter(
            kind=OutboundMessage.Kind.PAYMENT_FAILED
        ).exists()
        page = self.client.get(
            reverse("payment-return", args=[self.order.public_reference])
        )
        assert "nothing was charged" not in page.content.decode().lower()

    def test_staff_closing_a_hold_while_its_settle_job_reads_is_obeyed(self):
        """Blocker 3: staff close the held item while the settle job's read of
        the provider is out; the success that read then reports was applied."""

        own = self.held(amount=None)
        MockGateway.mark(own.provider_session_id, "succeeded")
        real_fetch = MockGateway.fetch_attempt

        def staff_close_during_the_read(gateway, **kwargs):
            snapshot = real_fetch(gateway, **kwargs)
            resolve_payment_attention(
                attempt_id=own.pk,
                actor_id=self.owner.pk,
                resolution=PaymentAttempt.OperationalResolution.RESOLVED,
                reason="No money was taken at the provider.",
            )
            return snapshot

        with mock.patch.object(
            MockGateway, "fetch_attempt", new=staff_close_during_the_read
        ):
            jobs.run_job(self.settle_job(own))

        own.refresh_from_db()
        assert own.status == PaymentAttempt.Status.FAILED
        assert self.payments(own) == 0
        self.order.refresh_from_db()
        assert self.order.status != PaymentOrder.Status.PAID

    def test_a_close_that_finds_the_payment_failed_ends_the_attempt(self):
        """Chargily should-fix: a close that learned the checkout's payment
        failed reported only "closed", so a settling attempt stayed final and
        `processing` forever."""

        own = self.owner_taps().attempt
        reconcile_attempt(attempt_id=own.pk, outcome="processing")
        MockGateway.mark(own.provider_session_id, "failed")
        real_fetch = MockGateway.fetch_attempt

        def still_open(gateway, **kwargs):
            return replace(real_fetch(gateway, **kwargs), outcome="ignored")

        with mock.patch.object(MockGateway, "fetch_attempt", new=still_open):
            settle_checkout(attempt_id=own.pk)

        own.refresh_from_db()
        assert own.status == PaymentAttempt.Status.FAILED
        assert own.checkout_final_at is not None
