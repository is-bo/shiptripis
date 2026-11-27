"""Rule G-D: every reported payment is accounted for before the order collects again.

Three facts are kept apart: whether a checkout can still collect (finality),
whether its provider reported a payment (evidence), and what became of that
money (disposition). A payment whose report cannot be verified is held: the
order takes no new payment until the hold ends in one of the five ways the
plan names (G1-A).
"""

from __future__ import annotations

import ast
from contextlib import nullcontext
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.admin_panel.models import AdminAuditLog
from apps.admin_panel.permissions import AdminRole, assign_admin_roles
from apps.admin_panel.tests.two_step_helpers import staff_login
from apps.core.business_settings import get_active_business_settings
from apps.core.models import BusinessSettingsVersion
from apps.finance import jobs
from apps.finance.models import (
    HELD_PAYMENT,
    PAID_AFTER_DISPOSITION,
    LedgerTransaction,
    PaymentAttempt,
    PaymentOrder,
    PaymentProviderEvent,
    PaymentRefund,
    ScheduledJob,
)
from apps.finance.operations import (
    FinanceOperationsError,
    payment_attention_queryset,
    resolve_payment_attention,
)
from apps.finance.providers import (
    CHECKOUT_CLOSED,
    CHECKOUT_COLLECTED,
    AttemptSnapshot,
    ProviderCheckoutRejected,
    ProviderError,
    ProviderUnavailable,
)
from apps.finance.providers.mock import MockGateway
from apps.finance.services import (
    FinanceError,
    cancel_order,
    create_guest_link,
    expire_checkout_attempt,
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
                resolution=PaymentAttempt.OperationalResolution.NO_DEBIT,
                reason="No money was taken at the provider.",
                failure_code=own.failure_code,
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
        # Held again for staff, the disposition cleared (its audit row keeps it).
        assert own.failure_code == "paid_after_disposition"
        assert own.operational_resolution == ""

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


# --- The table: every attempt state against every event that can reach it ----

#: The facts each row checks, in this order.
FIELDS = ("status", "code", "final", "disposition", "queue")

#: What each state looks like before its event: status, failure code, whether
#: the checkout is final, staff's disposition, and whether it is in the
#: finance queue.
STATES = {
    "opening": ("created", "", False, "", False),
    "never_opened": ("failed", "provider_checkout_failed", False, "", False),
    "open": ("checkout_pending", "", False, "", False),
    "closing": ("checkout_pending", "", False, "", False),
    "settling": ("processing", "", False, "", False),
    "ended_unconfirmed": ("cancelled", "deal_cancelled", False, "", False),
    "paid": ("succeeded", "", True, "", False),
    "ended_confirmed": ("expired", "expired", True, "", False),
    "held": ("failed", "amount_mismatch", True, "", True),
    "no_debit": ("failed", "amount_mismatch", True, "no_debit", False),
    "returned": ("failed", "amount_mismatch", True, "returned", False),
    "held_again": ("failed", "paid_after_disposition", True, "", True),
}
#: States a provider can report on: their checkout was stored.
WITH_CHECKOUT = [s for s in STATES if s not in ("opening", "never_opened")]
#: States the settle read leaves alone: nothing in them can collect or is held.
SETTLED = ("opening", "never_opened", "paid", "ended_confirmed", "no_debit", "returned")

APPLIED = {"status": "succeeded", "final": True, "queue": False}
UNAPPLIED = {"status": "succeeded", "final": True, "queue": True}
SUPERSEDED = {"status": "cancelled", "code": "superseded", "final": True}
EXPIRED = {"status": "expired", "code": "expired", "final": True}
FAILED = {"status": "failed", "code": "failed", "final": True}
SETTLING = {"status": "processing"}
STOPPED = {"status": "cancelled", "code": "deal_cancelled"}
HELD_AGAIN = {"code": PAID_AFTER_DISPOSITION, "disposition": "", "queue": True}


def _held_as(code):
    return {"status": "failed", "code": code, "final": True, "queue": True}


def _unverified_report(code):
    """A success the attempt cannot verify, reported by webhook."""

    return {
        "open": (code, _held_as(code)),
        "closing": (code, _held_as(code)),
        "settling": (code, _held_as(code)),
        "ended_unconfirmed": (code, _held_as(code)),
        "paid": "already_succeeded",
        "ended_confirmed": (code, _held_as(code)),
        # Already held: the hold it has is kept, nothing changes.
        "held": "amount_mismatch",
        "no_debit": (PAID_AFTER_DISPOSITION, HELD_AGAIN),
        "returned": "payment_already_returned",
        "held_again": "payment_held",
    }


def _read(**cells):
    """A settle read: states it never reads answer "checkout_final"."""

    return {**{state: "checkout_final" for state in SETTLED}, **cells}


#: event -> state -> the answer, or (the answer, the facts it changes).
TABLE = {
    "owner_tap": {
        "opening": "checkout_in_progress",
        "never_opened": "opened",
        "open": "handed_back",
        "closing": ("opened", SUPERSEDED),
        "settling": "checkout_in_progress",
        "ended_unconfirmed": "order_not_collectable",
        "paid": "order_not_collectable",
        "ended_confirmed": "opened",
        "held": "payment_under_review",
        "no_debit": "opened",
        "returned": "opened",
        "held_again": "payment_under_review",
    },
    "guest_tap": {
        "opening": "checkout_in_progress",
        "never_opened": "opened",
        "open": ("opened", SUPERSEDED),
        "closing": ("opened", SUPERSEDED),
        "settling": "checkout_in_progress",
        "ended_unconfirmed": "guest_link_invalid",
        "paid": "guest_link_invalid",
        "ended_confirmed": "opened",
        "held": "payment_under_review",
        "no_debit": "opened",
        "returned": "opened",
        "held_again": "payment_under_review",
    },
    "webhook_paid": {
        "open": ("applied", APPLIED),
        "closing": ("applied", APPLIED),
        "settling": ("applied", APPLIED),
        "ended_unconfirmed": ("unapplied_payment_refunded", UNAPPLIED),
        "paid": "already_succeeded",
        "ended_confirmed": ("applied", APPLIED),
        "held": ("applied", APPLIED),
        "no_debit": (PAID_AFTER_DISPOSITION, HELD_AGAIN),
        "returned": "payment_already_returned",
        "held_again": "payment_held",
    },
    "webhook_no_amount": _unverified_report("amount_unverifiable"),
    "webhook_no_currency": _unverified_report("currency_mismatch"),
    "webhook_fractional": _unverified_report("amount_unverifiable"),
    "webhook_mismatch": _unverified_report("amount_mismatch"),
    "webhook_failed": {
        "open": ("attempt_failed", FAILED),
        "closing": ("attempt_failed", FAILED),
        "settling": ("attempt_failed", FAILED),
        "ended_unconfirmed": ("already_terminal", {"final": True}),
        "paid": "already_succeeded",
        "ended_confirmed": "already_terminal",
        # A failure report never ends a hold: only the settle read does.
        "held": "already_terminal",
        "no_debit": "already_terminal",
        "returned": "already_terminal",
        "held_again": "already_terminal",
    },
    "read_final": _read(
        open=("attempt_expired", EXPIRED),
        closing=("attempt_expired", EXPIRED),
        settling=("attempt_expired", EXPIRED),
        ended_unconfirmed=("checkout_final", {"final": True}),
        held=("payment_released", {"code": "expired", "queue": False}),
        held_again="payment_held",
    ),
    "read_paid": _read(
        open=("applied", APPLIED),
        closing=("applied", APPLIED),
        settling=("applied", APPLIED),
        ended_unconfirmed=("unapplied_payment_refunded", UNAPPLIED),
        held=("applied", APPLIED),
        held_again="payment_held",
    ),
    "read_unverified": _read(
        open=("payment_held", _held_as("amount_mismatch")),
        closing=("payment_held", _held_as("amount_mismatch")),
        settling=("payment_held", _held_as("amount_mismatch")),
        ended_unconfirmed=("payment_held", _held_as("amount_mismatch")),
        held="payment_held",
        held_again="payment_held",
    ),
    "read_open": _read(
        open="checkout_open",
        closing=("attempt_cancelled", SUPERSEDED),
        settling=("attempt_cancelled", {**SUPERSEDED, "code": "cancelled"}),
        ended_unconfirmed=("checkout_final", {"final": True}),
        held="payment_held",
        held_again="payment_held",
    ),
    "read_processing": _read(
        open=("checkout_settling", SETTLING),
        closing=("checkout_settling", SETTLING),
        settling="checkout_settling",
        ended_unconfirmed="checkout_settling",
        held="payment_held",
        held_again="payment_held",
    ),
    "read_unreadable": _read(
        open="provider_unavailable",
        closing="provider_unavailable",
        settling="provider_unavailable",
        ended_unconfirmed="provider_unavailable",
        held="provider_unavailable",
        held_again="provider_unavailable",
    ),
    "close_unpaid": _read(
        open="checkout_open",
        closing=("attempt_cancelled", SUPERSEDED),
        settling=("attempt_cancelled", {**SUPERSEDED, "code": "cancelled"}),
        ended_unconfirmed=("checkout_final", {"final": True}),
        held="payment_held",
        held_again="payment_held",
    ),
    "close_collecting": _read(
        open="checkout_open",
        closing=("checkout_collecting", SETTLING),
        settling="checkout_collecting",
        ended_unconfirmed="checkout_collecting",
        held="payment_held",
        held_again="payment_held",
    ),
    "close_failed": _read(
        open="checkout_open",
        closing=("attempt_failed", FAILED),
        settling=("attempt_failed", FAILED),
        ended_unconfirmed=("checkout_final", {"final": True}),
        held="payment_held",
        held_again="payment_held",
    ),
    "expiry": {
        **{state: "attempt_already_terminal" for state in STATES},
        "opening": "attempt_opening",
        "open": ("attempt_expired", EXPIRED),
        "closing": ("attempt_expired", EXPIRED),
        "settling": "attempt_settling",
    },
    "staff_no_debit": {
        **{state: "payment_not_held" for state in STATES},
        "held": ("no_debit", {"disposition": "no_debit", "queue": False}),
        "held_again": "invalid_payment_resolution",
    },
    "staff_returned": {
        **{state: "payment_not_held" for state in STATES},
        "held": ("returned", {"disposition": "returned", "queue": False}),
        "held_again": ("returned", {"disposition": "returned", "queue": False}),
    },
    "order_stops": {
        **{state: "stopped" for state in STATES},
        "opening": ("stopped", STOPPED),
        "open": ("stopped", STOPPED),
        "closing": ("stopped", STOPPED),
        # Money it holds was credited, so the order keeps collecting it.
        "paid": "kept",
    },
    # Reachable only where the order can open another checkout.
    "paid_by_other": {
        state: "applied"
        for state in ("never_opened", "ended_confirmed", "no_debit", "returned")
    },
}
for _event in (
    "webhook_paid",
    "webhook_no_amount",
    "webhook_no_currency",
    "webhook_fractional",
    "webhook_mismatch",
    "webhook_failed",
):
    # A provider reports only on a checkout this server stored.
    assert set(TABLE[_event]) == set(WITH_CHECKOUT), _event


class _Interrupted(Exception):
    """The opening request is still out at the provider."""


class StatesAndEvents(HeldPaymentTestCase):
    """The table's states, each reached the way the product reaches it, and its events."""

    def state_opening(self):
        with mock.patch.object(
            MockGateway, "create_checkout", side_effect=_Interrupted
        ), self.assertRaises(_Interrupted):
            self.owner_taps()
        return PaymentAttempt.objects.get(order=self.order)

    def state_never_opened(self):
        with mock.patch.object(
            MockGateway, "create_checkout", side_effect=ProviderCheckoutRejected("no")
        ), self.assertRaises(ProviderCheckoutRejected):
            self.owner_taps()
        return PaymentAttempt.objects.get(order=self.order)

    def state_open(self):
        return self.owner_taps().attempt

    def state_closing(self):
        own = self.state_open()
        MockGateway.fail_close(own.provider_session_id, ProviderUnavailable("down"))
        with self.assertRaises(FinanceError):
            self.guest_taps()
        MockGateway.fail_close(own.provider_session_id, None)
        return own

    def state_settling(self):
        own = self.state_open()
        reconcile_attempt(attempt_id=own.pk, outcome="processing")
        return own

    def state_ended_unconfirmed(self):
        own = self.state_open()
        cancel_order(order_id=self.order.pk, reason="deal_cancelled")
        return own

    def state_paid(self):
        own = self.state_open()
        self.report(own, event_id=f"evt_paid_{own.pk}")
        return own

    def state_ended_confirmed(self):
        own = self.state_open()
        self.time_up(own)
        expire_checkout_attempt(attempt_id=own.pk)
        return own

    def state_held(self):
        return self.held(amount_delta=1)

    def state_no_debit(self):
        own = self.state_held()
        self.staff(own, PaymentAttempt.OperationalResolution.NO_DEBIT)
        return own

    def state_returned(self):
        own = self.state_held()
        self.staff(own, PaymentAttempt.OperationalResolution.RETURNED)
        return own

    def state_held_again(self):
        own = self.state_no_debit()
        self.report(own, event_id=f"evt_again_{own.pk}")
        return own

    # Events. Each answers its note, or the stable code it was refused with.

    def time_up(self, attempt):
        PaymentAttempt.objects.filter(pk=attempt.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )

    def staff(self, attempt, resolution):
        attempt.refresh_from_db()
        try:
            resolve_payment_attention(
                attempt_id=attempt.pk,
                actor_id=self.scenario.admin.pk,
                resolution=resolution,
                reason="Checked at the provider.",
                failure_code=attempt.failure_code,
                provider_reference=f"{attempt.provider_session_id}_pi",
            )
        except FinanceOperationsError as exc:
            return exc.code
        return resolution

    def tap(self, how):
        try:
            session = how()
        except FinanceError as exc:
            return exc.code
        return "opened" if session.created else "handed_back"

    def webhook(self, attempt, **data):
        event_id = f"evt_table_{attempt.pk}"
        self.report(attempt, event_id=event_id, **data)
        return PaymentProviderEvent.objects.get(
            provider="mock", provider_event_id=event_id
        ).processing_note

    def read(self, attempt, outcome, *, amount_delta=0, error=None, closed=None):
        """`settle_checkout`, its provider reading `outcome` (and closing as `closed`)."""

        def answer(gateway, **kwargs):
            if error is not None:
                raise error
            return AttemptSnapshot(
                outcome=outcome,
                provider_payment_id=f"{attempt.provider_session_id}_pi",
                amount_minor=int(attempt.provider_amount_minor) + amount_delta,
                currency=attempt.payment_currency,
            )

        close = (
            mock.patch.object(MockGateway, "close_checkout", return_value=closed)
            if closed is not None
            else nullcontext()
        )
        with mock.patch.object(MockGateway, "fetch_attempt", new=answer), close:
            try:
                return settle_checkout(attempt_id=attempt.pk)
            except ProviderError as exc:
                return exc.code

    def event_owner_tap(self, attempt):
        return self.tap(self.owner_taps)

    def event_guest_tap(self, attempt):
        return self.tap(self.guest_taps)

    def event_webhook_paid(self, attempt):
        return self.webhook(attempt)

    def event_webhook_no_amount(self, attempt):
        return self.webhook(attempt, amount=None)

    def event_webhook_no_currency(self, attempt):
        return self.webhook(attempt, currency="")

    def event_webhook_fractional(self, attempt):
        return self.webhook(attempt, amount=int(attempt.provider_amount_minor) + 0.5)

    def event_webhook_mismatch(self, attempt):
        return self.webhook(attempt, amount=int(attempt.provider_amount_minor) + 1)

    def event_webhook_failed(self, attempt):
        return self.webhook(attempt, outcome="failed")

    def event_read_final(self, attempt):
        return self.read(attempt, "expired")

    def event_read_paid(self, attempt):
        return self.read(attempt, "succeeded")

    def event_read_unverified(self, attempt):
        return self.read(attempt, "succeeded", amount_delta=1)

    def event_read_open(self, attempt):
        return self.read(attempt, "ignored")

    def event_read_processing(self, attempt):
        return self.read(attempt, "processing")

    def event_read_unreadable(self, attempt):
        return self.read(attempt, "ignored", error=ProviderUnavailable("down"))

    def event_close_unpaid(self, attempt):
        return self.read(attempt, "ignored", closed=CHECKOUT_CLOSED)

    def event_close_collecting(self, attempt):
        return self.read(attempt, "ignored", closed=CHECKOUT_COLLECTED)

    def event_close_failed(self, attempt):
        return self.read(attempt, "ignored", closed="failed")

    def event_expiry(self, attempt):
        self.time_up(attempt)
        try:
            return expire_checkout_attempt(attempt_id=attempt.pk)
        except ProviderError as exc:
            return exc.code

    def event_staff_no_debit(self, attempt):
        return self.staff(attempt, PaymentAttempt.OperationalResolution.NO_DEBIT)

    def event_staff_returned(self, attempt):
        return self.staff(attempt, PaymentAttempt.OperationalResolution.RETURNED)

    def event_order_stops(self, attempt):
        order = cancel_order(order_id=self.order.pk, reason="deal_cancelled")
        return "stopped" if order.cancelled_at else "kept"

    def event_paid_by_other(self, attempt):
        return self.webhook(self.owner_taps().attempt)

    def facts(self, attempt) -> dict:
        attempt.refresh_from_db()
        return {
            "status": attempt.status,
            "code": attempt.failure_code,
            "final": attempt.checkout_final_at is not None,
            "disposition": attempt.operational_resolution,
            "queue": payment_attention_queryset().filter(pk=attempt.pk).exists(),
        }


class AttemptTableTests(StatesAndEvents):
    """G1-A's table: generated from `TABLE`, one test per state and event."""

    def check(self, state, event, answer, changes):
        attempt = getattr(self, f"state_{state}")()
        before = dict(zip(FIELDS, STATES[state]))
        assert self.facts(attempt) == before, "the state was not built as listed"
        attempts = PaymentAttempt.objects.filter(order=self.order).count()

        got = getattr(self, f"event_{event}")(attempt)

        assert (got, self.facts(attempt)) == (answer, {**before, **changes})
        # Ledger: credited once exactly when it succeeded, and money the order
        # could not take is refunded.
        assert self.payments(attempt) == int(attempt.status == "succeeded")
        assert PaymentRefund.objects.filter(attempt=attempt).count() == int(
            attempt.is_unapplied
        )
        # A new checkout only when the event opened one.
        opened = got == "opened" or event == "paid_by_other"
        assert PaymentAttempt.objects.filter(order=self.order).count() == (
            attempts + opened
        )
        if PaymentAttempt.objects.filter(HELD_PAYMENT, pk=attempt.pk).exists():
            # A hold never tells anyone the payment failed.
            assert not OutboundMessage.objects.filter(
                key=f"payment_failed:attempt:{attempt.pk}:owner",
                status=OutboundMessage.Status.PENDING,
            ).exists()


def _table_test(state, event, answer, changes):
    def test(self):
        self.check(state, event, answer, changes)

    return test


for _event, _cells in TABLE.items():
    for _state, _cell in _cells.items():
        _answer, _changes = _cell if isinstance(_cell, tuple) else (_cell, {})
        setattr(
            AttemptTableTests,
            f"test_{_state}__{_event}",
            _table_test(_state, _event, _answer, _changes),
        )


class EitherOrderTests(StatesAndEvents):
    """Both orders of the events that can race: each sees what the other did."""

    def during_read(self, attempt, resolution, outcome, *, payment_id=None):
        """Staff record `resolution` while the settle read of `outcome` is out."""

        attempt.refresh_from_db()
        snapshot = AttemptSnapshot(
            outcome=outcome,
            provider_payment_id=payment_id or attempt.provider_payment_id,
            amount_minor=int(attempt.provider_amount_minor),
            currency=attempt.payment_currency,
        )

        def staff_decide_during_the_read(gateway, **kwargs):
            assert self.staff(attempt, resolution) == resolution
            return snapshot

        with mock.patch.object(
            MockGateway, "fetch_attempt", new=staff_decide_during_the_read
        ):
            return settle_checkout(attempt_id=attempt.pk)

    def test_a_disposition_then_a_verified_webhook_holds_it_again(self):
        own = self.state_no_debit()
        assert self.webhook(own) == PAID_AFTER_DISPOSITION
        assert self.facts(own)["queue"] and self.payments(own) == 0

    def test_a_verified_webhook_then_a_disposition_is_refused(self):
        own = self.state_held()
        assert self.webhook(own) == "applied"
        for resolution in PaymentAttempt.HELD_DISPOSITIONS:
            assert self.staff(own, resolution) == "payment_not_held"
        assert self.payments(own) == 1

    def test_money_returned_then_its_own_webhook_changes_nothing(self):
        own = self.state_returned()
        before = self.facts(own)
        assert self.webhook(own) == "payment_already_returned"
        assert self.facts(own) == before and self.payments(own) == 0

    def test_a_read_then_a_disposition_is_refused(self):
        own = self.state_held()
        assert self.event_read_final(own) == "payment_released"
        assert self.staff(own, "no_debit") == "payment_not_held"

    def test_a_disposition_then_a_read_reads_nothing(self):
        own = self.state_no_debit()
        with mock.patch.object(MockGateway, "fetch_attempt") as fetch:
            assert settle_checkout(attempt_id=own.pk) == "checkout_final"
        fetch.assert_not_called()

    def test_no_money_taken_during_a_read_of_no_payment_stands(self):
        own = self.state_held()
        assert self.during_read(own, "no_debit", "expired") == "checkout_final"
        assert self.facts(own)["disposition"] == "no_debit"

    def test_money_returned_during_a_read_of_that_payment_stands(self):
        own = self.state_held()
        assert (
            self.during_read(own, "returned", "succeeded")
            == "payment_already_returned"
        )
        assert self.facts(own)["disposition"] == "returned"
        assert self.payments(own) == 0

    def test_money_returned_during_a_read_of_another_payment_holds_it_again(self):
        own = self.state_held()
        answer = self.during_read(
            own, "returned", "succeeded", payment_id="pi_a_second_payment"
        )
        assert answer == "payment_held"
        assert self.facts(own) == dict(zip(FIELDS, STATES["held_again"]))
        assert own.provider_payment_id == "pi_a_second_payment"
        assert self.payments(own) == 0

    def test_a_webhook_holding_a_payment_then_a_tap_is_refused(self):
        own = self.state_open()
        self.webhook(own, amount=None)
        assert self.tap(self.guest_taps) == "payment_under_review"

    def test_a_tap_whose_read_finds_an_unverified_payment_is_refused(self):
        own = self.state_open()
        MockGateway.mark(own.provider_session_id, "succeeded")
        real_fetch = MockGateway.fetch_attempt

        def unverifiable(gateway, **kwargs):
            return replace(real_fetch(gateway, **kwargs), currency="")

        with mock.patch.object(MockGateway, "fetch_attempt", new=unverifiable):
            assert self.tap(self.guest_taps) == "payment_under_review"
        assert self.facts(own) == {
            **dict(zip(FIELDS, STATES["held"])),
            "code": "currency_mismatch",
        }
        assert PaymentAttempt.objects.filter(order=self.order).count() == 1

    def test_a_tap_handed_its_checkout_then_a_held_webhook_stops_the_next(self):
        own = self.state_open()
        assert self.tap(self.owner_taps) == "handed_back"
        self.webhook(own, amount=int(own.provider_amount_minor) + 0.5)
        assert self.tap(self.owner_taps) == "payment_under_review"


class LateEvidenceTests(StatesAndEvents):
    def test_the_same_event_twice_is_one_effect(self):
        own = self.state_held()
        before = self.facts(own)
        held_report = mock_event_body(
            event_id=f"evt_held_{own.pk}",
            outcome="succeeded",
            session_id=own.provider_session_id,
            payment_id=f"{own.provider_session_id}_pi",
            amount=int(own.provider_amount_minor) + 1,
            currency=own.payment_currency,
        )
        assert deliver_mock_webhook(self.client, held_report).status_code == 200
        assert self.facts(own) == before

    def test_the_same_unverified_report_as_a_new_event_keeps_the_hold(self):
        own = self.state_held()
        before = self.facts(own)
        settle_run_at = self.settle_job(own).run_at
        assert self.event_webhook_mismatch(own) == "amount_mismatch"
        assert self.facts(own) == before
        # Not armed again: the job's own reads keep their backoff.
        assert self.settle_job(own).run_at == settle_run_at

    def test_the_same_verified_payment_twice_is_credited_once(self):
        own = self.state_open()
        assert self.webhook(own) == "applied"
        self.report(own, event_id=f"evt_again_{own.pk}")
        assert self.payments(own) == 1

    def test_money_returned_needs_the_reference_the_provider_reported(self):
        own = self.state_held()
        for reference, code in (
            ("", "provider_reference_required"),
            ("pi_not_this_payment", "provider_reference_mismatch"),
        ):
            with self.subTest(reference or "none"):
                with self.assertRaises(FinanceOperationsError) as caught:
                    resolve_payment_attention(
                        attempt_id=own.pk,
                        actor_id=self.scenario.admin.pk,
                        resolution="returned",
                        reason="Refunded at the provider.",
                        failure_code=own.failure_code,
                        provider_reference=reference,
                    )
                assert caught.exception.code == code
        assert self.facts(own)["disposition"] == ""

    def test_money_returned_never_names_another_payment(self):
        paid = self.state_paid()
        paid.refresh_from_db()
        second = build_scenario(prefix="held-second")
        second.accept(reward_eur_cents=3_200)
        self.order = second.balance_order()
        self.owner = second.sender
        own = self.owner_taps().attempt
        # Reported with no payment id: none is stored for staff to match.
        self.report(own, event_id=f"evt_held_{own.pk}", amount=None, payment_id="")
        own.refresh_from_db()
        assert own.provider_payment_id == ""
        with self.assertRaises(FinanceOperationsError) as caught:
            resolve_payment_attention(
                attempt_id=own.pk,
                actor_id=self.scenario.admin.pk,
                resolution="returned",
                reason="Refunded at the provider.",
                failure_code=own.failure_code,
                provider_reference=paid.provider_payment_id,
            )
        assert caught.exception.code == "provider_reference_mismatch"


class MechanicalChecks(HeldPaymentTestCase):
    SOURCE = Path(__file__).resolve().parents[2]

    def sources(self):
        for path in sorted(self.SOURCE.rglob("*.py")):
            parts = path.relative_to(self.SOURCE).parts
            if "tests" not in parts and "migrations" not in parts:
                yield path

    def test_a_final_checkout_has_a_terminal_status(self):
        own = self.owner_taps().attempt
        with self.assertRaises(IntegrityError), transaction.atomic():
            PaymentAttempt.objects.filter(pk=own.pk).update(
                checkout_final_at=timezone.now()
            )

    def test_one_function_writes_the_final_time(self):
        writers = set()
        for path in self.sources():
            tree = ast.parse(path.read_text())
            for function in ast.walk(tree):
                if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for node in ast.walk(function):
                    targets = []
                    if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
                        targets = getattr(node, "targets", None) or [node.target]
                    written = any(
                        isinstance(t, ast.Attribute) and t.attr == "checkout_final_at"
                        for t in targets
                    ) or (
                        isinstance(node, ast.Call)
                        and any(k.arg == "checkout_final_at" for k in node.keywords)
                    )
                    if written:
                        writers.add((path.relative_to(self.SOURCE).as_posix(), function.name))
        assert writers == {("finance/services.py", "reconcile_attempt")}

    def test_the_three_predicates_are_stated_once(self):
        # The Python restatements in `next_checkout` and `_hands_back` are
        # G1-C's to remove (one gate function).
        for token in ("checkout_final_at__isnull", "HELD_PAYMENT_CODES", "UNVERIFIED_"):
            with self.subTest(token):
                found = {
                    path.relative_to(self.SOURCE).as_posix()
                    for path in self.sources()
                    if token in path.read_text()
                }
                assert found <= {"finance/models.py"}, found

    def test_the_test_gateway_refuses_a_call_inside_a_transaction(self):
        gateway = MockGateway()
        calls = {
            "create_checkout": lambda: gateway.create_checkout(None),
            "close_checkout": lambda: gateway.close_checkout(provider_session_id="x"),
            "fetch_attempt": lambda: gateway.fetch_attempt(
                provider_session_id="x", provider_payment_id=""
            ),
            "refund": lambda: gateway.refund(None),
        }
        for name, call in calls.items():
            with self.subTest(name), self.assertRaises(AssertionError), transaction.atomic():
                call()


LOCAL_STATIC = override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        },
    }
)


@LOCAL_STATIC
class HeldPaymentConsoleTests(StatesAndEvents):
    """Finance closes a held payment from the console: one audited transaction."""

    def setUp(self):
        super().setUp()
        assign_admin_roles(self.scenario.admin, (AdminRole.FINANCE,))
        staff_login(self.client, self.scenario.admin)

    def path(self, attempt):
        return reverse("admin_console:payment-resolve", args=(attempt.pk,))

    def post(self, attempt, **data):
        attempt.refresh_from_db()
        return self.client.post(
            self.path(attempt),
            {
                "reason": "Seen at the provider: no charge.",
                "failure_code": attempt.failure_code,
                "confirm": "on",
                **data,
            },
        )

    def test_a_held_payment_offers_the_two_dispositions_only(self):
        page = self.client.get(self.path(self.state_held())).content.decode()
        assert "Close held payment" in page
        for value in ("no_debit", "returned"):
            assert f'value="{value}"' in page
        for value in ("resolved", "dismissed", "superseded"):
            assert f'value="{value}"' not in page

    def test_no_money_taken_is_recorded_and_audited(self):
        own = self.state_held()
        response = self.post(own, resolution="no_debit")
        assert response.status_code == 302
        assert self.facts(own)["disposition"] == "no_debit"
        log = AdminAuditLog.objects.get(action="payment.hold_closed")
        assert (log.actor_id, log.target_id, log.reason) == (
            self.scenario.admin.pk,
            str(own.pk),
            "Seen at the provider: no charge.",
        )
        assert log.before["failure"] == "amount_mismatch"
        assert log.after["operational_resolution"] == "no_debit"

    def test_a_payment_that_changed_since_it_was_reviewed_is_not_closed(self):
        own = self.state_held()
        page = self.post(own, resolution="no_debit", failure_code="amount_unverifiable")
        assert page.status_code == 200
        assert "(payment_changed)" in page.content.decode()
        assert self.facts(own)["disposition"] == ""
        assert not AdminAuditLog.objects.filter(action="payment.hold_closed").exists()

    def test_money_returned_without_its_reference_is_refused(self):
        own = self.state_held()
        page = self.post(own, resolution="returned", provider_reference="")
        assert page.status_code == 200
        assert "(provider_reference_required)" in page.content.decode()
        assert self.facts(own)["disposition"] == ""

    def test_a_payment_held_again_ends_only_as_money_returned(self):
        own = self.state_held_again()
        page = self.client.get(self.path(own)).content.decode()
        assert 'value="returned"' in page and 'value="no_debit"' not in page
        assert self.post(own, resolution="no_debit").status_code == 200
        response = self.post(
            own,
            resolution="returned",
            provider_reference=f"{own.provider_session_id}_pi",
        )
        assert response.status_code == 302
        assert self.facts(own)["disposition"] == "returned"
