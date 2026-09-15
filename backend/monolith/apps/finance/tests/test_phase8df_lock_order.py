"""Phase 8D-F: the finance lock-order contract and the races it protects.

The defect this module exists for was not an application ordering mistake. Every
service already approached the aggregate in the order
`apps.core.financial_locks` documents. The inverted order was the *database's*:
Django emits foreign keys as `DEFERRABLE INITIALLY DEFERRED`, so an `INSERT`
checks its parents at `COMMIT` by taking one `FOR KEY SHARE` row lock per
foreign key, in constraint-creation order. `finance_provider_event` references
`PaymentAttempt` before `PaymentOrder`, which is the exact inverse of the
canonical order, and no application statement chooses that.

`FOR KEY SHARE` conflicts with exactly one mode, `FOR UPDATE`. So the repair is
lock *strength*, not lock order: the aggregate is taken `FOR NO KEY UPDATE`,
which still excludes every other writer and no longer excludes a foreign-key
reference. The first class below asserts that contract structurally; the rest
run the real races on real threads.
"""

from __future__ import annotations

import ast
import pathlib
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

from django.db import connection, connections, transaction
from django.db.models import Sum
from django.test import SimpleTestCase
from django.test.client import Client
from django.test.utils import CaptureQueriesContext

from apps.finance.models import (
    LedgerEntry,
    LedgerTransaction,
    PaymentAttempt,
    PaymentOrder,
    PaymentProviderEvent,
    PaymentRefund,
)
from apps.finance.providers.mock import MockGateway
from apps.finance.services import (
    RefundExceedsCapture,
    reconcile_attempt,
    request_refund,
)

from .factories import (
    deliver_mock_webhook,
    open_mock_checkout,
    pay_order_with_mock,
    succeed_attempt,
)
from .test_concurrency import FinanceConcurrencyTestCase

POSTGRES_ONLY = unittest.skipUnless(
    connection.vendor == "postgresql",
    "Row-lock strength is PostgreSQL behaviour.",
)

#: Every module that locks a row named in the canonical finance/deal lock order.
#: Legacy rails that V1 refuses -- `apps.verification`, `apps.wallet`,
#: `apps.payments` and the unrouted legacy views in `apps.matching.views` -- are
#: deliberately absent: they cannot execute against a V1 Deal, and Phase 8D-R
#: already recorded them as removal candidates rather than repair targets.
CANONICAL_LOCK_MODULES = (
    "apps/core/financial_locks.py",
    "apps/core/business_settings.py",
    "apps/finance/services.py",
    "apps/finance/jobs.py",
    "apps/finance/operations.py",
    "apps/finance/payout_release.py",
    "apps/finance/settlement.py",
    "apps/finance/payout_domain.py",
    "apps/finance/payout_profiles.py",
    "apps/finance/payout_snapshots.py",
    "apps/finance/payout_operations.py",
    # H3 execution. These are the modules that actually move money, so a bare
    # `select_for_update()` here would reintroduce the deferred-FK lock cycle
    # this gate exists to keep closed. `payout_provider_events` and
    # `payout_sweeper` are deliberately absent: they take no lock at all, and
    # this gate asserts that a listed module still locks something.
    "apps/finance/payout_execution.py",
    "apps/finance/payout_manual.py",
    "apps/finance/payout_manual_profiles.py",
    "apps/finance/payout_reconciliation.py",
    "apps/parcels/services.py",
    # J2. `apps.boosts` reaches a PaymentOrder from the request graph in three
    # places -- binding a historical purchase, unwinding one, and checking that
    # a Boost cut does not strand a committed deposit -- so it is a canonical
    # lock site and is held to the same mode as the rest of the graph.
    "apps/boosts/services.py",
    "apps/deals/services.py",
    "apps/disputes/services.py",
    "apps/trips/services.py",
    "apps/matching/v1_services.py",
)

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


def _select_for_update_calls(source: str) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "select_for_update"
    ]


class FinanceLockContractTests(SimpleTestCase):
    """The contract itself, asserted where it is written rather than inferred."""

    def test_every_canonical_lock_site_asks_for_no_key_update(self):
        offenders: list[str] = []
        for relative in CANONICAL_LOCK_MODULES:
            path = _REPO_ROOT / relative
            source = path.read_text(encoding="utf-8")
            calls = _select_for_update_calls(source)
            assert calls, f"{relative} no longer locks anything; update this list."
            for call in calls:
                no_key = [kw for kw in call.keywords if kw.arg == "no_key"]
                ok = (
                    len(no_key) == 1
                    and isinstance(no_key[0].value, ast.Constant)
                    and no_key[0].value.value is True
                )
                if not ok:
                    offenders.append(f"{relative}:{call.lineno}")
        assert not offenders, (
            "A canonical-graph row was locked FOR UPDATE. That mode conflicts "
            "with the FOR KEY SHARE locks PostgreSQL takes for deferred "
            "foreign-key checks at COMMIT, which is the deadlock Phase 8D-F "
            "repaired. Use select_for_update(no_key=True). Offenders: "
            + ", ".join(offenders)
        )

    def test_the_canonical_order_is_documented_beside_the_helper(self):
        """Item 11: one place to read, not one assumption per service."""

        text = (_REPO_ROOT / "apps/core/financial_locks.py").read_text(encoding="utf-8")
        for marker in (
            "FOR NO KEY UPDATE",
            "DEFERRABLE INITIALLY DEFERRED",
            "FOR KEY SHARE",
            "PaymentOrder",
            "PaymentAttempt",
        ):
            assert marker in text, f"The lock-order contract no longer states {marker}."


@POSTGRES_ONLY
class EmittedLockModeTests(FinanceConcurrencyTestCase):
    """What the helpers actually send to PostgreSQL, not what they intend to."""

    prefix = "p8df-sql"

    def test_the_payment_aggregate_never_emits_a_bare_for_update(self):
        from apps.core.financial_locks import lock_payment_order_aggregate

        with transaction.atomic():
            with CaptureQueriesContext(connection) as captured:
                lock_payment_order_aggregate(self.order.pk)

        self._assert_only_no_key_locks(captured)

    def test_the_deal_lifecycle_never_emits_a_bare_for_update(self):
        from apps.core.financial_locks import lock_deal_lifecycle

        with transaction.atomic():
            with CaptureQueriesContext(connection) as captured:
                lock_deal_lifecycle(self.scenario.deal.pk)

        self._assert_only_no_key_locks(captured)

    def _assert_only_no_key_locks(self, captured) -> None:
        locking = [
            entry["sql"]
            for entry in captured.captured_queries
            if "FOR NO KEY UPDATE" in entry["sql"] or "FOR UPDATE" in entry["sql"]
        ]
        assert locking, "The aggregate acquired no row locks at all."
        for sql in locking:
            assert "FOR NO KEY UPDATE" in sql, sql
            assert "FOR UPDATE" not in sql.replace("FOR NO KEY UPDATE", ""), sql


@POSTGRES_ONLY
class RefundReconciliationRaceTests(FinanceConcurrencyTestCase):
    """A. The reproduced deadlock, and the invariant it was hiding."""

    prefix = "p8df-refund"

    def _round(self, *, attempt, index: int, slice_eur_cents: int) -> dict:
        """One refund racing one provider event on the same order and attempt.

        The provider event is what makes this the reproduction: persisting it
        inserts a `finance_provider_event` row whose deferred foreign keys are
        checked at COMMIT, attempt first and order second.
        """

        barrier = Barrier(2)
        outcome: dict = {}

        def refund():
            connections.close_all()
            try:
                barrier.wait(timeout=30)
                request_refund(
                    order_id=self.order.pk,
                    attempt_id=attempt.pk,
                    amount_eur_cents=slice_eur_cents,
                    reason=PaymentRefund.Reason.ADMIN,
                    requested_by_id=self.scenario.admin.pk,
                    idempotency_key=f"p8df-slice-{index}",
                )
                outcome["refund"] = "refunded"
            except RefundExceedsCapture:
                outcome["refund"] = "refused"
            finally:
                connections.close_all()

        def replay():
            connections.close_all()
            try:
                barrier.wait(timeout=30)
                response = deliver_mock_webhook(
                    Client(), succeed_attempt(attempt, event_id=f"evt_p8df_{index}")
                )
                outcome["webhook"] = response.status_code
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(refund), executor.submit(replay)]
            for future in futures:
                future.result(timeout=60)

        # A deadlock is not a test failure by itself -- the webhook view
        # converts every exception into a 500 so the provider retries -- so the
        # status code is the assertion that catches it.
        assert outcome["webhook"] == 200, (
            f"Round {index} lost the provider event: the webhook answered "
            f"{outcome['webhook']}, which is what a DeadlockDetected looks like "
            "from outside."
        )
        return outcome

    def test_a_refund_racing_a_reconciliation_never_deadlocks_or_over_refunds(self):
        attempt = pay_order_with_mock(Client(), self.order)
        captured = int(attempt.amount_eur_cents)

        self._round(attempt=attempt, index=0, slice_eur_cents=captured // 4)

        self.order.refresh_from_db()
        assert self.order.paid_eur_cents == captured
        assert self.order.refunded_eur_cents <= self.order.paid_eur_cents
        assert LedgerTransaction.objects.filter(kind="customer_payment").count() == 1
        assert PaymentProviderEvent.objects.count() >= 2
        self._assert_books_balance()

    def test_the_race_survives_repeated_rounds(self):
        """Item 10: one clean run proved nothing when the failure was 1 in 3."""

        attempt = pay_order_with_mock(Client(), self.order)
        captured = int(attempt.amount_eur_cents)
        rounds = 30
        slice_eur_cents = max(1, captured // (rounds * 2))

        refunded_rounds = 0
        for index in range(rounds):
            outcome = self._round(
                attempt=attempt, index=index, slice_eur_cents=slice_eur_cents
            )
            refunded_rounds += outcome["refund"] == "refunded"

        assert refunded_rounds == rounds, refunded_rounds
        self.order.refresh_from_db()
        assert self.order.paid_eur_cents == captured
        assert self.order.refunded_eur_cents <= self.order.paid_eur_cents
        assert self.order.refunded_eur_cents == rounds * slice_eur_cents
        assert LedgerTransaction.objects.filter(kind="customer_payment").count() == 1
        assert (
            PaymentRefund.objects.filter(
                attempt=attempt, status=PaymentRefund.Status.SUCCEEDED
            ).count()
            == rounds
        )
        self._assert_books_balance()

    def test_a_refund_can_never_exceed_the_capture_under_contention(self):
        attempt = pay_order_with_mock(Client(), self.order)
        captured = int(attempt.amount_eur_cents)

        self._round(attempt=attempt, index=100, slice_eur_cents=captured)
        refused = self._round(attempt=attempt, index=101, slice_eur_cents=1)

        assert refused["refund"] == "refused"
        self.order.refresh_from_db()
        assert self.order.refunded_eur_cents == captured
        assert self.order.refunded_eur_cents <= self.order.paid_eur_cents
        self._assert_books_balance()

    def _assert_books_balance(self) -> None:
        """Every ledger fact this order touched still nets to zero."""

        transactions = LedgerTransaction.objects.filter(
            entries__order_id=self.order.pk
        ).distinct()
        assert transactions.exists(), "The order left no ledger fact at all."
        for row in transactions:
            total = int(
                LedgerEntry.objects.filter(transaction=row).aggregate(
                    total=Sum("amount_eur_cents")
                )["total"]
                or 0
            )
            assert total == 0, f"{row.key} nets {total}."


@POSTGRES_ONLY
class WebhookRefundRaceTests(FinanceConcurrencyTestCase):
    """B. A first-time capture landing while a refund of another one runs."""

    prefix = "p8df-webhook"

    def test_a_second_capture_and_a_refund_never_deadlock(self):
        # Both attempts have to exist before either succeeds: a covered order
        # refuses a new checkout, which is exactly why switching rail cancels
        # the open attempt first.
        first = open_mock_checkout(self.order)
        PaymentAttempt.objects.filter(pk=first.pk).update(
            status=PaymentAttempt.Status.CANCELLED
        )
        second = open_mock_checkout(self.order)
        MockGateway.mark(second.provider_session_id, "succeeded")
        response = deliver_mock_webhook(
            Client(), succeed_attempt(first, event_id="evt_p8df_first")
        )
        assert response.status_code == 200, response.content
        first.refresh_from_db()
        assert first.status == PaymentAttempt.Status.SUCCEEDED
        barrier = Barrier(2)
        outcome: dict = {}

        def capture():
            connections.close_all()
            try:
                barrier.wait(timeout=30)
                outcome["webhook"] = deliver_mock_webhook(
                    Client(), succeed_attempt(second, event_id="evt_p8df_second")
                ).status_code
            finally:
                connections.close_all()

        def refund():
            connections.close_all()
            try:
                barrier.wait(timeout=30)
                request_refund(
                    order_id=self.order.pk,
                    attempt_id=first.pk,
                    amount_eur_cents=int(first.amount_eur_cents),
                    reason=PaymentRefund.Reason.ADMIN,
                    requested_by_id=self.scenario.admin.pk,
                    idempotency_key="p8df-webhook-refund",
                )
                outcome["refund"] = "refunded"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            for future in [executor.submit(capture), executor.submit(refund)]:
                future.result(timeout=60)

        assert outcome["webhook"] == 200
        assert outcome["refund"] == "refunded"

        self.order.refresh_from_db()
        second.refresh_from_db()
        assert second.status == PaymentAttempt.Status.SUCCEEDED
        assert self.order.refunded_eur_cents <= self.order.paid_eur_cents
        # The second capture is real money whichever way the race went: either
        # it was applied to the obligation, or it was carried as unapplied and
        # refunded. It is never silently absent.
        for attempt in (first, second):
            attempt.refresh_from_db()
            obligated = int(
                PaymentRefund.objects.filter(
                    attempt=attempt,
                    status__in=(
                        PaymentRefund.Status.PENDING,
                        PaymentRefund.Status.PROCESSING,
                        PaymentRefund.Status.SUCCEEDED,
                    ),
                ).aggregate(total=Sum("amount_eur_cents"))["total"]
                or 0
            )
            assert obligated <= int(attempt.amount_eur_cents), attempt.pk
            if attempt.is_unapplied:
                assert obligated == int(attempt.amount_eur_cents), attempt.pk


@POSTGRES_ONLY
class DuplicateRefundRequestTests(FinanceConcurrencyTestCase):
    """C. Two refund requests, and the operator who clicks twice."""

    prefix = "p8df-dupe"

    def test_two_partial_refunds_that_both_fit_never_deadlock(self):
        attempt = pay_order_with_mock(Client(), self.order)
        half = int(attempt.amount_eur_cents) // 2
        barrier = Barrier(2)

        def refund(index):
            connections.close_all()
            try:
                barrier.wait(timeout=30)
                request_refund(
                    order_id=self.order.pk,
                    attempt_id=attempt.pk,
                    amount_eur_cents=half,
                    reason=PaymentRefund.Reason.ADMIN,
                    requested_by_id=self.scenario.admin.pk,
                    idempotency_key=f"p8df-half-{index}",
                )
                return "refunded"
            except RefundExceedsCapture:
                return "refused"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = sorted(executor.map(refund, range(2)))

        assert results == ["refunded", "refunded"], results
        self.order.refresh_from_db()
        assert self.order.refunded_eur_cents == 2 * half
        assert self.order.refunded_eur_cents <= self.order.paid_eur_cents

    def test_a_repeated_operator_refund_request_creates_one_obligation(self):
        """Item 7: the same operator action twice is one refund, not two."""

        attempt = pay_order_with_mock(Client(), self.order)
        amount = int(attempt.amount_eur_cents)
        barrier = Barrier(3)

        def refund(_index):
            connections.close_all()
            try:
                barrier.wait(timeout=30)
                return request_refund(
                    order_id=self.order.pk,
                    attempt_id=attempt.pk,
                    amount_eur_cents=amount,
                    reason=PaymentRefund.Reason.ADMIN,
                    requested_by_id=self.scenario.admin.pk,
                    idempotency_key="p8df-operator-click",
                ).pk
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=3) as executor:
            ids = set(executor.map(refund, range(3)))

        # All three callers are handed the same obligation. The unlocked
        # idempotency lookup at the top of `request_refund` answers the
        # sequential retry; the re-read under the order lock answers this one.
        assert len(ids) == 1, ids
        assert PaymentRefund.objects.filter(attempt=attempt).count() == 1
        self.order.refresh_from_db()
        assert self.order.refunded_eur_cents == amount
        assert self.order.refunded_eur_cents <= self.order.paid_eur_cents


@POSTGRES_ONLY
class ReconciliationConcurrencyTests(FinanceConcurrencyTestCase):
    """D. Reconciliation against reconciliation, and the ordering around it."""

    prefix = "p8df-reconcile"

    def test_three_events_for_one_attempt_capture_once(self):
        attempt = open_mock_checkout(self.order)
        MockGateway.mark(attempt.provider_session_id, "succeeded")
        barrier = Barrier(3)

        def deliver(index):
            connections.close_all()
            try:
                barrier.wait(timeout=30)
                return deliver_mock_webhook(
                    Client(), succeed_attempt(attempt, event_id=f"evt_p8df_r{index}")
                ).status_code
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=3) as executor:
            statuses = list(executor.map(deliver, range(3)))

        assert statuses == [200, 200, 200], statuses
        self.order.refresh_from_db()
        assert self.order.paid_eur_cents == int(attempt.amount_eur_cents)
        assert self.order.outstanding_eur_cents == 0
        assert LedgerTransaction.objects.filter(kind="customer_payment").count() == 1
        assert LedgerTransaction.objects.filter(kind="deal_funding").count() == 1

    def test_reconciliation_after_a_webhook_moves_no_further_money(self):
        """Item 7: webhook first, then a poll for the same attempt."""

        attempt = pay_order_with_mock(Client(), self.order)
        before = int(self.order.__class__.objects.get(pk=self.order.pk).paid_eur_cents)

        result = reconcile_attempt(
            attempt_id=attempt.pk,
            outcome="succeeded",
            provider_amount_minor=int(attempt.provider_amount_minor),
            provider_currency=attempt.payment_currency,
        )

        assert result == "already_succeeded", result
        self.order.refresh_from_db()
        assert int(self.order.paid_eur_cents) == before
        assert LedgerTransaction.objects.filter(kind="customer_payment").count() == 1

    def test_a_webhook_after_a_reconciliation_moves_no_further_money(self):
        """Item 7: the same pair in the other order."""

        attempt = open_mock_checkout(self.order)
        MockGateway.mark(attempt.provider_session_id, "succeeded")
        reconcile_attempt(
            attempt_id=attempt.pk,
            outcome="succeeded",
            provider_amount_minor=int(attempt.provider_amount_minor),
            provider_currency=attempt.payment_currency,
        )

        response = deliver_mock_webhook(
            Client(), succeed_attempt(attempt, event_id="evt_p8df_late")
        )

        assert response.status_code == 200, response.content
        self.order.refresh_from_db()
        assert self.order.paid_eur_cents == int(attempt.amount_eur_cents)
        assert LedgerTransaction.objects.filter(kind="customer_payment").count() == 1


@POSTGRES_ONLY
class RefundRollbackTests(FinanceConcurrencyTestCase):
    """E. A transaction that dies mid-way leaves no half-refund behind."""

    prefix = "p8df-rollback"

    def test_a_failed_refund_transaction_leaves_no_partial_money_state(self):
        attempt = pay_order_with_mock(Client(), self.order)
        self.order.refresh_from_db()
        before = {
            "paid": int(self.order.paid_eur_cents),
            "refunded": int(self.order.refunded_eur_cents),
            "status": self.order.status,
            "ledger": LedgerTransaction.objects.count(),
        }

        with patch(
            "apps.finance.services._enqueue_refund_status_email",
            side_effect=RuntimeError("email adapter exploded"),
        ):
            with self.assertRaises(RuntimeError):
                request_refund(
                    order_id=self.order.pk,
                    attempt_id=attempt.pk,
                    amount_eur_cents=int(attempt.amount_eur_cents),
                    reason=PaymentRefund.Reason.ADMIN,
                    requested_by_id=self.scenario.admin.pk,
                    idempotency_key="p8df-doomed",
                )

        assert not PaymentRefund.objects.filter(idempotency_key="p8df-doomed").exists()
        self.order.refresh_from_db()
        assert int(self.order.paid_eur_cents) == before["paid"]
        assert int(self.order.refunded_eur_cents) == before["refunded"]
        assert self.order.status == before["status"]
        assert LedgerTransaction.objects.count() == before["ledger"]

        # And the obligation is still refundable afterwards: the failure cost
        # the attempt nothing.
        refund = request_refund(
            order_id=self.order.pk,
            attempt_id=attempt.pk,
            amount_eur_cents=int(attempt.amount_eur_cents),
            reason=PaymentRefund.Reason.ADMIN,
            requested_by_id=self.scenario.admin.pk,
            idempotency_key="p8df-recovered",
        )
        assert refund.pk is not None
        self.order.refresh_from_db()
        assert self.order.refunded_eur_cents <= self.order.paid_eur_cents
        assert int(
            PaymentOrder.objects.filter(pk=self.order.pk).aggregate(
                total=Sum("refunded_eur_cents")
            )["total"]
        ) == int(attempt.amount_eur_cents)
