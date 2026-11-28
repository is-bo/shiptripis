"""PostgreSQL concurrency tests for the financial state machine.

These run real threads against a real database. SQLite cannot express what is
being tested — row-level locking, partial unique indexes and `SELECT ... FOR
UPDATE SKIP LOCKED` are PostgreSQL behaviours — so the whole module skips
elsewhere rather than passing vacuously.

The defence under test is deliberately *not* a process-local mutex. Every
guarantee here comes from the database: a row lock, a unique index, or a check
constraint. Two web workers on different machines get the same answer as two
threads in one process.
"""

from __future__ import annotations

import unittest
from concurrent.futures import ThreadPoolExecutor, wait
from copy import deepcopy
from datetime import timedelta
from threading import Barrier, Event
from unittest.mock import patch

from django.db import IntegrityError, connection, connections, transaction
from django.db.utils import OperationalError
from django.test import TransactionTestCase
from django.test.client import Client
from django.utils import timezone

from apps.core.business_settings import get_active_business_settings
from apps.core.models import BusinessSettingsVersion
from apps.core.tests.business_settings_seed import seed_business_settings
from apps.deals.models import Deal
from apps.finance import jobs, ledger
from apps.finance.models import (
    LedgerTransaction,
    PaymentAttempt,
    PaymentOrder,
    PaymentProviderEvent,
    PaymentRefund,
    Payout,
    ScheduledJob,
)
from apps.finance.providers.mock import MockGateway
from apps.finance.services import (
    CheckoutInProgress,
    RefundExceedsCapture,
    cancel_order,
    create_guest_link,
    ensure_posting_deposit_order,
    request_refund,
    revoke_guest_link,
)

from .factories import (
    build_scenario,
    deliver_mock_webhook,
    open_mock_checkout,
    pay_order_with_mock,
    succeed_attempt,
)
from .assertions import (
    assert_provider_funds_are_locally_accounted,
)

POSTGRES_ONLY = unittest.skipUnless(
    connection.vendor == "postgresql",
    "Financial concurrency guarantees are PostgreSQL row-lock behaviour.",
)


def _seed_settings() -> BusinessSettingsVersion:
    """TransactionTestCase truncates tables; re-seed the active revision."""

    return seed_business_settings()


def _enable_mock_rail() -> None:
    settings_version = get_active_business_settings()
    policy = deepcopy(settings_version.policy)
    policy["payments"]["providers"]["mock_enabled"] = True
    BusinessSettingsVersion.objects.filter(pk=settings_version.pk).update(
        policy=policy
    )


@POSTGRES_ONLY
class FinanceConcurrencyTestCase(TransactionTestCase):
    reset_sequences = True
    prefix = "conc"

    def setUp(self):
        publisher = patch("apps.core.redis_bus.publish_after_commit")
        publisher.start()
        self.addCleanup(publisher.stop)
        MockGateway.reset()
        _seed_settings()
        _enable_mock_rail()
        self.scenario = build_scenario(prefix=self.prefix)
        self.scenario.accept(reward_eur_cents=3_200)
        self.order = self.scenario.balance_order()

    def _in_thread(self, fn):
        """Run a callable on its own database connection."""

        def wrapped(*args, **kwargs):
            connections.close_all()
            try:
                return fn(*args, **kwargs)
            finally:
                connections.close_all()

        return wrapped


class DuplicateWebhookRaceTests(FinanceConcurrencyTestCase):
    prefix = "conc-webhook"

    def test_the_same_event_delivered_twice_at_once_funds_once(self):
        attempt = open_mock_checkout(self.order)
        MockGateway.mark(attempt.provider_session_id, "succeeded")
        body = succeed_attempt(attempt, event_id="evt_race")
        barrier = Barrier(2)

        def deliver(_index):
            connections.close_all()
            try:
                barrier.wait(timeout=10)
                return deliver_mock_webhook(Client(), body).status_code
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            statuses = list(executor.map(deliver, range(2)))

        assert all(status == 200 for status in statuses), statuses
        self.order.refresh_from_db()
        assert self.order.paid_eur_cents == int(attempt.amount_eur_cents)
        # The unique index on (provider, provider_event_id) is what makes the
        # loser a no-op, not a lock the application happened to take.
        assert (
            PaymentProviderEvent.objects.filter(provider_event_id="evt_race").count()
            == 1
        )
        assert LedgerTransaction.objects.filter(kind="customer_payment").count() == 1
        assert LedgerTransaction.objects.filter(kind="deal_funding").count() == 1
        assert Deal.objects.get(pk=self.scenario.deal.pk).status == Deal.Status.FUNDED

    def test_two_different_events_for_one_attempt_still_pay_once(self):
        attempt = open_mock_checkout(self.order)
        MockGateway.mark(attempt.provider_session_id, "succeeded")
        barrier = Barrier(2)
        bodies = [
            succeed_attempt(attempt, event_id="evt_a"),
            succeed_attempt(attempt, event_id="evt_b"),
        ]

        def deliver(body):
            connections.close_all()
            try:
                barrier.wait(timeout=10)
                return deliver_mock_webhook(Client(), body).status_code
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            list(executor.map(deliver, bodies))

        self.order.refresh_from_db()
        assert self.order.paid_eur_cents == int(attempt.amount_eur_cents)
        assert self.order.outstanding_eur_cents == 0
        assert LedgerTransaction.objects.filter(kind="customer_payment").count() == 1

    def test_scheduled_reconciliation_and_webhook_converge_once(self):
        attempt = open_mock_checkout(self.order)
        # Captured before the race: provider-side truth must not be
        # re-derived from rows the race could have rolled back.
        session_id = attempt.provider_session_id
        MockGateway.mark(attempt.provider_session_id, "succeeded")
        barrier = Barrier(2)

        def webhook():
            connections.close_all()
            try:
                barrier.wait(timeout=10)
                response = deliver_mock_webhook(
                    Client(), succeed_attempt(attempt, event_id="evt_poll_webhook")
                )
                assert response.status_code == 200, response.content
                return "webhook"
            finally:
                connections.close_all()

        def poll():
            connections.close_all()
            try:
                barrier.wait(timeout=10)
                jobs.handle_provider_reconcile({"attempt_id": attempt.pk})
                return "poll"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            webhook_future = executor.submit(webhook)
            poll_future = executor.submit(poll)
            assert {webhook_future.result(), poll_future.result()} == {
                "webhook",
                "poll",
            }

        assert LedgerTransaction.objects.filter(kind="customer_payment").count() == 1
        assert LedgerTransaction.objects.filter(kind="deal_funding").count() == 1
        assert_provider_funds_are_locally_accounted(
            order_ids=[self.order.pk], session_ids=[session_id]
        )


class CheckoutRaceTests(FinanceConcurrencyTestCase):
    prefix = "conc-checkout"

    def test_two_simultaneous_checkouts_leave_exactly_one_open_attempt(self):
        """The order lock and the partial unique index are the arbiters, not
        application timing. The later request reuses the first checkout or is
        told it is still opening; the provider opens one session (G1)."""

        barrier = Barrier(2)

        def start(_index):
            connections.close_all()
            try:
                barrier.wait(timeout=10)
                return open_mock_checkout(self.order).pk
            except IntegrityError:
                return "conflict"
            except CheckoutInProgress:
                return "opening"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(start, range(2)))

        rows = list(PaymentAttempt.objects.values_list("pk", "status"))
        live = PaymentAttempt.objects.get(
            order=self.order, status__in=PaymentAttempt.OPEN_STATUSES
        )
        assert len(rows) == 1, rows
        assert live.pk in results, results
        assert set(results) <= {live.pk, "opening", "conflict"}, results
        assert MockGateway.checkout_session_ids() == [live.provider_session_id]

    def test_two_attempts_that_both_succeed_fund_the_deal_once(self):
        """The residual double-pay race, run for real."""

        first = open_mock_checkout(self.order)
        # Take the first attempt out of the open state so a second may exist,
        # exactly as switching provider would.
        PaymentAttempt.objects.filter(pk=first.pk).update(
            status=PaymentAttempt.Status.CANCELLED
        )
        second = open_mock_checkout(self.order)
        first.refresh_from_db()
        barrier = Barrier(2)

        def deliver(attempt_and_id):
            attempt, event_id = attempt_and_id
            connections.close_all()
            try:
                barrier.wait(timeout=10)
                return deliver_mock_webhook(
                    Client(), succeed_attempt(attempt, event_id=event_id)
                ).status_code
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            list(
                executor.map(
                    deliver, [(first, "evt_first"), (second, "evt_second")]
                )
            )

        self.order.refresh_from_db()
        first.refresh_from_db()
        second.refresh_from_db()
        applied = [
            attempt
            for attempt in (first, second)
            if attempt.status == PaymentAttempt.Status.SUCCEEDED
            and not attempt.is_unapplied
        ]
        unapplied = [
            attempt
            for attempt in (first, second)
            if attempt.status == PaymentAttempt.Status.SUCCEEDED
            and attempt.is_unapplied
        ]

        assert len(applied) == 1
        assert len(unapplied) == 1
        assert self.order.paid_eur_cents == int(applied[0].amount_eur_cents)
        assert Deal.objects.get(pk=self.scenario.deal.pk).status == Deal.Status.FUNDED
        assert LedgerTransaction.objects.filter(kind="deal_funding").count() == 1
        # The money that could not be applied is real, and is refunded.
        assert PaymentRefund.objects.filter(
            attempt=unapplied[0], reason=PaymentRefund.Reason.UNAPPLIED_PAYMENT
        ).exists()


class GuestPageRaceTests(FinanceConcurrencyTestCase):
    """G1: the guest page, submitted as the browser submits it, under contention."""

    prefix = "conc-guest"

    def setUp(self):
        super().setUp()
        self.issued = create_guest_link(
            order_id=self.order.pk, actor_id=self.scenario.sender.pk
        )
        self.page = f"/pay/guest/{self.issued.token}"

    def _tap(self):
        connections.close_all()
        try:
            return Client(enforce_csrf_checks=True).post(
                self.page,
                {"provider": "mock", "lang": "en"},
                secure=True,
                HTTP_ORIGIN="null",
            )
        finally:
            connections.close_all()

    def test_a_revocation_committing_while_the_payer_taps_stops_the_payment(self):
        """The page read the link before the revocation committed; checkout
        waits on the order row the revocation holds, then reads it again."""

        from apps.finance import guest_web

        revoked = Event()
        allow_commit = Event()
        checkout_entered = Event()
        real_start = guest_web.start_checkout

        def entering_checkout(**kwargs):
            checkout_entered.set()
            return real_start(**kwargs)

        def revoke():
            connections.close_all()
            try:
                with transaction.atomic():
                    count = revoke_guest_link(
                        order_id=self.order.pk, actor_id=self.scenario.sender.pk
                    )
                    revoked.set()
                    assert allow_commit.wait(timeout=10)
                return count
            finally:
                connections.close_all()

        with (
            patch.object(guest_web, "start_checkout", side_effect=entering_checkout),
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            revocation = executor.submit(revoke)
            assert revoked.wait(timeout=10)
            payment = executor.submit(self._tap)
            try:
                assert checkout_entered.wait(timeout=10)
                done, _ = wait([payment], timeout=0.5)
                assert not done, "Checkout did not wait for the revocation's lock."
            finally:
                allow_commit.set()
            assert revocation.result(timeout=10) == 1
            response = payment.result(timeout=10)

        assert response.status_code == 409
        assert "This link is no longer active" in response.content.decode()
        assert not PaymentAttempt.objects.filter(order=self.order).exists()

    def assert_only_payable(self, live):
        """`live` is the order's one open attempt and the one checkout anyone can pay."""

        assert list(
            PaymentAttempt.objects.filter(
                order=self.order, status__in=PaymentAttempt.OPEN_STATUSES
            )
        ) == [live]
        payable = [
            session
            for session in MockGateway.checkout_session_ids()
            if MockGateway.is_payable(session)
        ]
        assert payable == [live.provider_session_id]

    def test_two_taps_at_once_leave_one_payable_checkout_and_fund_once(self):
        due = self.order.outstanding_eur_cents
        barrier = Barrier(2)

        def tap(_index):
            barrier.wait(timeout=10)
            return self._tap()

        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(tap, range(2)))

        # The later tap waited on the order lock, then either found the first
        # checkout still opening and was asked to wait, or closed it at the
        # provider before opening its own. Either way one checkout can collect.
        live = PaymentAttempt.objects.get(
            order=self.order, status__in=PaymentAttempt.OPEN_STATUSES
        )
        assert live.provider_session_id and live.checkout_url
        self.assert_only_payable(live)
        attempts = list(PaymentAttempt.objects.filter(order=self.order))
        redirects = [res["Location"] for res in responses if res.status_code == 302]
        # Each redirect is a checkout of its own, opened by one of these taps:
        # no two taps are ever sent to the same one.
        assert len(redirects) == len(set(redirects)) == len(attempts) >= 1
        assert set(redirects) == {attempt.checkout_url for attempt in attempts}
        assert live.checkout_url in redirects
        # And each checkout the later tap replaced was closed at its provider.
        for replaced in (attempt for attempt in attempts if attempt.pk != live.pk):
            assert replaced.status == PaymentAttempt.Status.CANCELLED
            assert replaced.failure_code == "superseded"
            assert not MockGateway.is_payable(replaced.provider_session_id)
        for waiting in (res for res in responses if res.status_code != 302):
            assert waiting.status_code == 409
            assert "A payment is already under way" in waiting.content.decode()

        MockGateway.mark(live.provider_session_id, "succeeded")
        assert deliver_mock_webhook(Client(), succeed_attempt(live)).status_code == 200
        self.order.refresh_from_db()
        assert self.order.paid_eur_cents == due > 0
        assert LedgerTransaction.objects.filter(kind="deal_funding").count() == 1

    def test_a_tap_while_the_first_is_at_the_provider_keeps_its_key(self):
        """The first tap's provider call is held open. A second tap, on its own
        connection, finds the attempt with no URL yet: it is asked to wait and
        opens nothing. Released, the first tap stores its URL; a retry closes
        that checkout before opening its own."""

        at_provider = Event()
        release = Event()
        real_create = MockGateway.create_checkout

        def held(gateway, request):
            if not at_provider.is_set():
                at_provider.set()
                assert release.wait(timeout=10)
            return real_create(gateway, request)

        with (
            patch.object(MockGateway, "create_checkout", new=held),
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            first = executor.submit(self._tap)
            try:
                assert at_provider.wait(timeout=10)
                second = executor.submit(self._tap).result(timeout=10)
                opening = PaymentAttempt.objects.get(order=self.order)
            finally:
                release.set()
            first = first.result(timeout=10)

        assert second.status_code == 409
        assert "A payment is already under way" in second.content.decode()
        assert opening.status == PaymentAttempt.Status.CREATED
        assert opening.checkout_url == ""

        stored = PaymentAttempt.objects.get(order=self.order)
        assert stored.pk == opening.pk
        assert stored.idempotency_key == opening.idempotency_key
        assert first.status_code == 302 and first["Location"] == stored.checkout_url
        assert MockGateway.checkout_session_ids() == [stored.provider_session_id]
        retry = self._tap()
        assert retry.status_code == 302 and retry["Location"] != stored.checkout_url
        live = PaymentAttempt.objects.get(
            order=self.order, status__in=PaymentAttempt.OPEN_STATUSES
        )
        assert retry["Location"] == live.checkout_url
        self.assert_only_payable(live)

    def test_no_lock_is_held_while_a_provider_closes_a_checkout(self):
        """A tap that must close the open checkout first holds that provider
        call open. The order row stays free meanwhile, and the tap opens its
        own checkout only after the close returned."""

        first = self._tap()
        assert first.status_code == 302
        at_provider = Event()
        release = Event()
        real_close = MockGateway.close_checkout

        def held(gateway, *, provider_session_id):
            at_provider.set()
            assert release.wait(timeout=10)
            return real_close(gateway, provider_session_id=provider_session_id)

        def order_row_is_free():
            connections.close_all()
            try:
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute("SET LOCAL lock_timeout = '2s'")
                    PaymentOrder.objects.select_for_update().get(pk=self.order.pk)
                return True
            finally:
                connections.close_all()

        with (
            patch.object(MockGateway, "close_checkout", new=held),
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            second = executor.submit(self._tap)
            try:
                assert at_provider.wait(timeout=10)
                assert executor.submit(order_row_is_free).result(timeout=10)
                assert PaymentAttempt.objects.filter(order=self.order).count() == 1
            finally:
                release.set()
            second = second.result(timeout=10)

        assert second.status_code == 302
        assert second["Location"] != first["Location"]
        live = PaymentAttempt.objects.get(
            order=self.order, status__in=PaymentAttempt.OPEN_STATUSES
        )
        assert second["Location"] == live.checkout_url
        self.assert_only_payable(live)


class RefundRaceTests(FinanceConcurrencyTestCase):
    prefix = "conc-refund"

    def test_two_simultaneous_full_refunds_return_the_money_once(self):
        attempt = pay_order_with_mock(Client(), self.order)
        barrier = Barrier(2)

        def refund(index):
            connections.close_all()
            try:
                barrier.wait(timeout=10)
                request_refund(
                    order_id=self.order.pk,
                    attempt_id=attempt.pk,
                    amount_eur_cents=int(attempt.amount_eur_cents),
                    reason=PaymentRefund.Reason.ADMIN,
                    requested_by_id=self.scenario.admin.pk,
                    idempotency_key=f"race-refund-{index}",
                )
                return "refunded"
            except RefundExceedsCapture:
                return "refused"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = sorted(executor.map(refund, range(2)))

        assert results == ["refunded", "refused"], results
        self.order.refresh_from_db()
        assert self.order.refunded_eur_cents == int(attempt.amount_eur_cents)
        assert self.order.refunded_eur_cents <= self.order.paid_eur_cents

    def test_a_refund_racing_a_reconciliation_never_exceeds_the_capture(self):
        attempt = pay_order_with_mock(Client(), self.order)
        barrier = Barrier(2)

        def refund():
            connections.close_all()
            try:
                barrier.wait(timeout=10)
                request_refund(
                    order_id=self.order.pk,
                    attempt_id=attempt.pk,
                    amount_eur_cents=int(attempt.amount_eur_cents),
                    reason=PaymentRefund.Reason.ADMIN,
                    requested_by_id=self.scenario.admin.pk,
                )
                return "refunded"
            finally:
                connections.close_all()

        def replay_success():
            connections.close_all()
            try:
                barrier.wait(timeout=10)
                deliver_mock_webhook(
                    Client(), succeed_attempt(attempt, event_id="evt_replay")
                )
                return "replayed"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            refund_future = executor.submit(refund)
            replay_future = executor.submit(replay_success)
            assert {refund_future.result(), replay_future.result()} == {
                "refunded",
                "replayed",
            }

        self.order.refresh_from_db()
        assert self.order.paid_eur_cents == int(attempt.amount_eur_cents)
        assert self.order.refunded_eur_cents <= self.order.paid_eur_cents
        assert LedgerTransaction.objects.filter(kind="customer_payment").count() == 1


class GraceExpiryRaceTests(FinanceConcurrencyTestCase):
    prefix = "conc-grace"

    def test_original_inverse_lock_interleaving_is_deadlock_free(self):
        """The payment owns the domain graph before it can own finance rows."""

        from apps.deals.services import release_pending_deal_reservation
        from apps.finance import services as finance_services

        attempt = open_mock_checkout(self.order)
        MockGateway.mark(attempt.provider_session_id, "succeeded")
        payment_holds_aggregate = Event()
        allow_payment = Event()
        expiry_started = Event()
        expiry_reached_finance = Event()
        original_lock = finance_services.lock_payment_order_aggregate
        original_cancel = finance_services.cancel_deal_balance_orders

        def pause_after_complete_lock(order_id):
            aggregate = original_lock(order_id)
            payment_holds_aggregate.set()
            assert allow_payment.wait(timeout=10)
            return aggregate

        def observe_cancel(*, deal_id, reason):
            expiry_reached_finance.set()
            return original_cancel(deal_id=deal_id, reason=reason)

        def pay():
            connections.close_all()
            try:
                response = deliver_mock_webhook(
                    Client(), succeed_attempt(attempt, event_id="evt_forced_grace")
                )
                assert response.status_code == 200, response.content
                return "paid"
            finally:
                connections.close_all()

        def expire():
            connections.close_all()
            try:
                expiry_started.set()
                release_pending_deal_reservation(
                    deal_id=self.scenario.deal.pk,
                    reason="payment_grace_expired",
                )
                return "expired"
            finally:
                connections.close_all()

        with (
            patch.object(
                finance_services,
                "lock_payment_order_aggregate",
                side_effect=pause_after_complete_lock,
            ),
            patch.object(
                finance_services,
                "cancel_deal_balance_orders",
                side_effect=observe_cancel,
            ),
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            payment = executor.submit(pay)
            assert payment_holds_aggregate.wait(timeout=10)
            expiry = executor.submit(expire)
            assert expiry_started.wait(timeout=10)
            try:
                assert not expiry_reached_finance.wait(timeout=0.5), (
                    "Expiry passed the domain locks while payment held the "
                    "same aggregate; the inverse lock edge returned."
                )
            finally:
                allow_payment.set()
            assert {payment.result(timeout=10), expiry.result(timeout=10)} == {
                "paid",
                "expired",
            }

    def test_a_payment_landing_as_the_grace_expires_never_half_funds_a_deal(self):
        """Whichever side wins, the outcome is coherent."""

        from apps.deals.services import release_pending_deal_reservation

        attempt = open_mock_checkout(self.order)
        # Captured before the race: provider-side truth must not be
        # re-derived from rows the race could have rolled back.
        session_id = attempt.provider_session_id
        MockGateway.mark(attempt.provider_session_id, "succeeded")
        barrier = Barrier(2)

        def pay():
            connections.close_all()
            try:
                barrier.wait(timeout=10)
                response = deliver_mock_webhook(
                    Client(), succeed_attempt(attempt, event_id="evt_grace")
                )
                assert response.status_code == 200, response.content
                return "paid"
            finally:
                connections.close_all()

        def expire():
            connections.close_all()
            try:
                barrier.wait(timeout=10)
                release_pending_deal_reservation(
                    deal_id=self.scenario.deal.pk, reason="payment_grace_expired"
                )
                return "expired"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            payment = executor.submit(pay)
            expiry = executor.submit(expire)
            assert {payment.result(), expiry.result()} == {"paid", "expired"}

        deal = Deal.objects.get(pk=self.scenario.deal.pk)
        self.order.refresh_from_db()
        attempt.refresh_from_db()

        # Exactly one of the two coherent outcomes, never a mixture.
        if deal.status == Deal.Status.FUNDED:
            assert self.order.status == PaymentOrder.Status.PAID
            assert attempt.is_unapplied is False
        else:
            assert deal.status == Deal.Status.EXPIRED
            assert self.order.status == PaymentOrder.Status.CANCELLED
            # Unconditional on purpose. The provider captured the money before
            # either thread started, so the attempt is succeeded whichever side
            # won; an `if` here would let a lost payment pass silently.
            assert attempt.status == PaymentAttempt.Status.SUCCEEDED
            assert attempt.is_unapplied is True
            assert PaymentRefund.objects.filter(attempt=attempt).exists()
        assert_provider_funds_are_locally_accounted(
            order_ids=[self.order.pk], session_ids=[session_id]
        )

    def test_a_cancellation_racing_a_payment_never_leaves_money_unaccounted(self):
        attempt = open_mock_checkout(self.order)
        # Captured before the race: provider-side truth must not be
        # re-derived from rows the race could have rolled back.
        session_id = attempt.provider_session_id
        MockGateway.mark(attempt.provider_session_id, "succeeded")
        barrier = Barrier(2)

        def pay():
            connections.close_all()
            try:
                barrier.wait(timeout=10)
                response = deliver_mock_webhook(
                    Client(), succeed_attempt(attempt, event_id="evt_cancel_race")
                )
                assert response.status_code == 200, response.content
                return "paid"
            finally:
                connections.close_all()

        def cancel():
            connections.close_all()
            try:
                barrier.wait(timeout=10)
                cancel_order(order_id=self.order.pk, reason="race")
                return "cancelled"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            payment = executor.submit(pay)
            cancellation = executor.submit(cancel)
            assert {payment.result(), cancellation.result()} == {"paid", "cancelled"}

        attempt.refresh_from_db()
        assert attempt.status == PaymentAttempt.Status.SUCCEEDED
        assert_provider_funds_are_locally_accounted(
            order_ids=[self.order.pk], session_ids=[session_id]
        )


@POSTGRES_ONLY
class DealCancellationPaymentStressTests(TransactionTestCase):
    """Repeatedly exercise the former PaymentOrder/Deal inverse edge."""

    reset_sequences = True

    def setUp(self):
        publisher = patch("apps.core.redis_bus.publish_after_commit")
        publisher.start()
        self.addCleanup(publisher.stop)
        MockGateway.reset()
        _seed_settings()
        _enable_mock_rail()

    def test_payment_vs_grace_and_deal_cancellation_repeated_stress(self):
        from apps.deals.services import release_pending_deal_reservation

        for index in range(12):
            scenario = build_scenario(prefix=f"deal-stress-{index}")
            scenario.accept(reward_eur_cents=3_200)
            order = scenario.balance_order()
            attempt = open_mock_checkout(order)
            # Captured before the race: provider-side truth must not be
            # re-derived from rows the race could have rolled back.
            session_id = attempt.provider_session_id
            MockGateway.mark(attempt.provider_session_id, "succeeded")
            reason = (
                "payment_grace_expired" if index % 2 == 0 else "deal_cancelled"
            )
            barrier = Barrier(2)

            def pay():
                connections.close_all()
                try:
                    barrier.wait(timeout=10)
                    response = deliver_mock_webhook(
                        Client(),
                        succeed_attempt(attempt, event_id=f"evt_deal_stress_{index}"),
                    )
                    assert response.status_code == 200, response.content
                    return "paid"
                finally:
                    connections.close_all()

            def release():
                connections.close_all()
                try:
                    barrier.wait(timeout=10)
                    release_pending_deal_reservation(
                        deal_id=scenario.deal.pk,
                        reason=reason,
                    )
                    return "released"
                finally:
                    connections.close_all()

            with ThreadPoolExecutor(max_workers=2) as executor:
                payment = executor.submit(pay)
                cancellation = executor.submit(release)
                assert {payment.result(), cancellation.result()} == {
                    "paid",
                    "released",
                }

            deal = Deal.objects.get(pk=scenario.deal.pk)
            order.refresh_from_db()
            attempt.refresh_from_db()
            assert attempt.status == PaymentAttempt.Status.SUCCEEDED
            if deal.status == Deal.Status.FUNDED:
                assert order.status == PaymentOrder.Status.PAID
                assert attempt.is_unapplied is False
            else:
                assert deal.status in (Deal.Status.EXPIRED, Deal.Status.CANCELLED)
                assert order.status == PaymentOrder.Status.CANCELLED
                assert attempt.is_unapplied is True
                assert PaymentRefund.objects.filter(attempt=attempt).exists()
            assert_provider_funds_are_locally_accounted(
                order_ids=[order.pk], session_ids=[session_id]
            )


@POSTGRES_ONLY
class ParcelCancellationPaymentRaceTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        publisher = patch("apps.core.redis_bus.publish_after_commit")
        publisher.start()
        self.addCleanup(publisher.stop)
        MockGateway.reset()
        _seed_settings()
        _enable_mock_rail()

    def _scenario(self, suffix: str):
        scenario = build_scenario(prefix=f"parcel-race-{suffix}", open_request=False)
        order = ensure_posting_deposit_order(
            delivery_request=scenario.delivery_request,
            policy=scenario.policy,
        )
        attempt = open_mock_checkout(order)
        # Captured before the race: provider-side truth must not be
        # re-derived from rows the race could have rolled back.
        session_id = attempt.provider_session_id
        MockGateway.mark(session_id, "succeeded")
        return scenario, order, attempt, session_id

    def _assert_cancelled_money(self, scenario, order, attempt, session_id) -> None:
        scenario.delivery_request.refresh_from_db()
        order.refresh_from_db()
        attempt.refresh_from_db()
        assert scenario.delivery_request.status == "cancelled"
        assert order.status == PaymentOrder.Status.CANCELLED
        assert attempt.status == PaymentAttempt.Status.SUCCEEDED
        assert PaymentRefund.objects.filter(attempt=attempt).exists()
        assert_provider_funds_are_locally_accounted(
            order_ids=[order.pk], session_ids=[session_id]
        )

    def test_payment_then_request_cancellation_refunds_applied_money(self):
        from apps.parcels.services import cancel_delivery_request

        scenario, order, attempt, session_id = self._scenario("payment-first")
        assert deliver_mock_webhook(
            Client(), succeed_attempt(attempt, event_id="evt_parcel_payment_first")
        ).status_code == 200
        cancel_delivery_request(
            request_id=scenario.delivery_request.pk,
            actor_id=scenario.sender.pk,
        )
        self._assert_cancelled_money(scenario, order, attempt, session_id)
        attempt.refresh_from_db()
        assert attempt.is_unapplied is False

    def test_request_cancellation_then_payment_refunds_unapplied_money(self):
        from apps.parcels.services import cancel_delivery_request

        scenario, order, attempt, session_id = self._scenario("cancel-first")
        cancel_delivery_request(
            request_id=scenario.delivery_request.pk,
            actor_id=scenario.sender.pk,
        )
        assert deliver_mock_webhook(
            Client(), succeed_attempt(attempt, event_id="evt_parcel_cancel_first")
        ).status_code == 200
        self._assert_cancelled_money(scenario, order, attempt, session_id)
        attempt.refresh_from_db()
        assert attempt.is_unapplied is True

    @POSTGRES_ONLY
    def test_payment_and_request_cancellation_stress_conserves_money(self):
        """Threaded, so PostgreSQL only. The two ordering tests above are not:
        they drive each order deterministically and are worth running on both
        backends."""


        from apps.parcels.services import cancel_delivery_request

        for index in range(8):
            scenario, order, attempt, session_id = self._scenario(str(index))
            barrier = Barrier(2)

            def pay():
                connections.close_all()
                try:
                    barrier.wait(timeout=10)
                    response = deliver_mock_webhook(
                        Client(),
                        succeed_attempt(
                            attempt,
                            event_id=f"evt_parcel_stress_{index}",
                        ),
                    )
                    assert response.status_code == 200, response.content
                    return "paid"
                finally:
                    connections.close_all()

            def cancel():
                connections.close_all()
                try:
                    barrier.wait(timeout=10)
                    cancel_delivery_request(
                        request_id=scenario.delivery_request.pk,
                        actor_id=scenario.sender.pk,
                    )
                    return "cancelled"
                finally:
                    connections.close_all()

            with ThreadPoolExecutor(max_workers=2) as executor:
                payment = executor.submit(pay)
                cancellation = executor.submit(cancel)
                assert {payment.result(), cancellation.result()} == {
                    "paid",
                    "cancelled",
                }
            self._assert_cancelled_money(scenario, order, attempt, session_id)


class DepositCreditRaceTests(FinanceConcurrencyTestCase):
    prefix = "conc-deposit"

    def setUp(self):
        _seed_settings()
        _enable_mock_rail()
        self.scenario = build_scenario(prefix=self.prefix, open_request=False)
        self.deposit = ensure_posting_deposit_order(
            delivery_request=self.scenario.delivery_request,
            policy=self.scenario.policy,
        )
        pay_order_with_mock(Client(), self.deposit)
        self.deposit.refresh_from_db()
        self.scenario.delivery_request.refresh_from_db()

    def test_two_simultaneous_credit_attempts_spend_the_deposit_once(self):
        from apps.finance.services import apply_posting_deposit_credit

        self.scenario.accept(reward_eur_cents=3_200)
        deal = self.scenario.deal
        balance = self.scenario.balance_order()
        # Retire the credited order so a competing replacement may exist.
        PaymentOrder.objects.filter(pk=balance.pk).update(
            status=PaymentOrder.Status.CANCELLED, cancelled_at=timezone.now()
        )
        rival = PaymentOrder.objects.create(
            owner_id=self.scenario.sender.pk,
            purpose=PaymentOrder.Purpose.DEAL_BALANCE,
            amount_eur_cents=5_000,
            deal_id=deal.pk,
            delivery_request_id=self.scenario.delivery_request.pk,
        )

        connections.close_all()
        credited = apply_posting_deposit_credit(order=rival, deal=deal)

        assert credited == 0
        rival.refresh_from_db()
        assert rival.credit_source_id is None
        assert LedgerTransaction.objects.filter(kind="deposit_credit").count() == 1

    def test_the_partial_unique_index_allows_one_live_deposit_per_request(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PaymentOrder.objects.create(
                    owner_id=self.scenario.sender.pk,
                    purpose=PaymentOrder.Purpose.POSTING_DEPOSIT,
                    amount_eur_cents=500,
                    delivery_request_id=self.scenario.delivery_request.pk,
                )


class ScheduledJobRaceTests(FinanceConcurrencyTestCase):
    prefix = "conc-jobs"

    def test_two_workers_never_claim_the_same_job(self):
        """`SKIP LOCKED` is what makes a shared queue safe, not a global lock."""

        for index in range(8):
            ScheduledJob.objects.create(
                key=f"race-job-{index}",
                kind=ScheduledJob.Kind.ATTEMPT_EXPIRY,
                run_at=timezone.now() - timedelta(minutes=1),
                payload={"attempt_id": 10_000 + index},
            )
        barrier = Barrier(2)

        def claim(_index):
            connections.close_all()
            try:
                barrier.wait(timeout=10)
                return [job.pk for job in jobs.claim_due_jobs(limit=8)]
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            first, second = list(executor.map(claim, range(2)))

        assert not set(first).intersection(second), (first, second)

    def test_running_the_deposit_refund_from_two_workers_refunds_once(self):
        scenario = build_scenario(prefix="conc-jobs-refund", open_request=False)
        deposit = ensure_posting_deposit_order(
            delivery_request=scenario.delivery_request, policy=scenario.policy
        )
        pay_order_with_mock(Client(), deposit)
        scenario.delivery_request.refresh_from_db()
        from apps.parcels.models import DeliveryRequest

        DeliveryRequest.objects.filter(pk=scenario.delivery_request.pk).update(
            deadline_at=timezone.now() - timedelta(minutes=1)
        )
        ScheduledJob.objects.filter(
            kind=ScheduledJob.Kind.DEPOSIT_EXPIRY_REFUND
        ).update(run_at=timezone.now() - timedelta(minutes=1))
        barrier = Barrier(2)

        def sweep(_index):
            connections.close_all()
            try:
                barrier.wait(timeout=10)
                return jobs.run_due_jobs(limit=10).claimed
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            list(executor.map(sweep, range(2)))

        deposit.refresh_from_db()
        assert PaymentRefund.objects.filter(order=deposit).count() == 1
        assert deposit.refunded_eur_cents == deposit.paid_eur_cents


class ManualPayoutRaceTests(FinanceConcurrencyTestCase):
    prefix = "conc-payout"

    def setUp(self):
        super().setUp()
        pay_order_with_mock(Client(), self.order)
        self.payout = Payout.objects.get(deal=self.scenario.deal)
        # Stand in for the Phase 4 release service.
        Payout.objects.filter(pk=self.payout.pk).update(
            status=Payout.Status.ELIGIBLE, eligible_at=timezone.now()
        )

    def test_a_double_submitted_settlement_pays_once(self):
        from apps.finance.services import complete_manual_payout

        barrier = Barrier(2)

        def settle(_index):
            connections.close_all()
            try:
                barrier.wait(timeout=10)
                complete_manual_payout(
                    payout_id=self.payout.pk,
                    admin_actor_id=self.scenario.admin.pk,
                    payout_currency="EUR",
                    payout_amount_minor=3_200,
                    reference="RACE-REF",
                )
                return "settled"
            except OperationalError:
                return "blocked"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            list(executor.map(settle, range(2)))

        self.payout.refresh_from_db()
        assert self.payout.status == Payout.Status.PAID
        assert LedgerTransaction.objects.filter(kind="payout").count() == 1
        assert (
            ledger.account_balance(
                "traveler_payable", user_id=self.scenario.traveler.pk
            )
            == 0
        )


@POSTGRES_ONLY
class LedgerBalanceInvariantTests(FinanceConcurrencyTestCase):
    """After every race, the books must still balance."""

    prefix = "conc-ledger"

    def test_the_whole_ledger_nets_to_zero_after_a_contended_lifecycle(self):
        attempt = pay_order_with_mock(Client(), self.order)
        request_refund(
            order_id=self.order.pk,
            attempt_id=attempt.pk,
            amount_eur_cents=int(attempt.amount_eur_cents),
            reason=PaymentRefund.Reason.ADMIN,
            requested_by_id=self.scenario.admin.pk,
        )

        from django.db.models import Sum

        for ledger_transaction in LedgerTransaction.objects.all():
            total = ledger_transaction.entries.aggregate(
                total=Sum("amount_eur_cents")
            )["total"]
            assert total == 0, f"{ledger_transaction.key} nets {total}"
