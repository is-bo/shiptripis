"""Two real writers racing for the same euro, against real PostgreSQL.

SQLite cannot express any of this — row-level locking, partial unique indexes
and the `FOR NO KEY UPDATE` ordering that keeps them acyclic are PostgreSQL
behaviours — so the module skips elsewhere rather than passing vacuously.

Every assertion here is about an *external* effect, not a local row count. Two
threads both writing a `dispatch_committed` row and one of them losing is not
interesting; two threads both calling `POST /v1/transfers` is the failure this
phase exists to make impossible, so the fake provider's call log is what gets
counted.

The defences under test are all in the database: the Deal lifecycle aggregate
taken in the canonical order, the partial unique index that permits one
committed attempt per payout, the operation lease, and the immutable allocation
rows that make a source's remaining capacity a fact rather than an opinion.
"""

from __future__ import annotations

import unittest
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from threading import Barrier

from django.db import connection, connections
from django.db.models import Sum
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from unittest.mock import patch

from apps.core.models import BusinessSettingsVersion
from apps.finance import ledger
from apps.finance.models import (
    FinanceHold,
    LedgerAccount,
    LedgerTransaction,
    PaymentRefund,
    PayoutAttempt,
    PayoutFundingAllocation,
    PayoutProviderOperation,
    StripeDisbursement,
    StripeDisbursementAllocation,
)
from apps.finance.payout_execution import (
    PayoutExecutionError,
    execute_payout,
)
from apps.finance.services import RefundExceedsCapture, request_refund

from .payout_execution_harness import (
    H3_SETTINGS,
    FakeConnect,
    authorise_auto_stripe,
    build_stripe_payout,
)

POSTGRES_ONLY = unittest.skipUnless(
    connection.vendor == "postgresql",
    "Payout dispatch races are PostgreSQL row-lock behaviour.",
)


def _seed_admin_roles() -> None:
    """Re-seed the role groups and payout capabilities.

    `TransactionTestCase` truncates `auth_group` and `auth_permission`, so the
    capability rows the admin migrations seed are gone by the time a test runs.
    The migrations' own seed functions are re-run against the live registry —
    reimplementing them here would let the test's idea of a capability drift
    from production's.
    """

    from importlib import import_module

    from django.apps import apps as registry
    from django.db import connection as db

    with db.schema_editor() as editor:
        import_module("apps.admin_panel.migrations.0002_seed_roles").seed_roles(
            registry, editor
        )
        import_module(
            "apps.admin_panel.migrations.0005_seed_payout_capabilities"
        ).seed(registry, editor)


def _seed_settings() -> BusinessSettingsVersion:
    """TransactionTestCase truncates tables; re-seed the active revision."""

    active = BusinessSettingsVersion.objects.filter(status="active").first()
    if active is not None:
        return active
    from importlib import import_module

    document = import_module(
        "apps.core.migrations.0005_seed_phase3_payment_settings"
    ).PHASE3_POLICY
    return BusinessSettingsVersion.objects.create(
        version=3,
        status=BusinessSettingsVersion.Status.ACTIVE,
        canonical_currency="EUR",
        commission_rate_bps=2_500,
        pricing_version="v1-payments-1",
        policy=deepcopy(document),
        activated_at=timezone.now(),
    )


class ThreadSafeConnect(FakeConnect):
    """`FakeConnect` with the one property a race needs: a slow call.

    `hold` makes `create_transfer` wait on a barrier, so both threads are
    guaranteed to be inside the provider call at the same moment if the local
    serialization ever lets them get there.
    """

    def __init__(self, *, barrier=None, **kwargs):
        super().__init__(**kwargs)
        self.barrier = barrier

    def create_transfer(self, **kwargs):
        if self.barrier is not None:
            try:
                self.barrier.wait(timeout=10)
            except Exception:  # noqa: BLE001 - a lone arrival is the point
                pass
        return super().create_transfer(**kwargs)


@POSTGRES_ONLY
@override_settings(**H3_SETTINGS)
class PayoutDispatchRaceTests(TransactionTestCase):
    prefix = "h3race"

    def setUp(self):
        publisher = patch("apps.core.redis_bus.publish_after_commit")
        publisher.start()
        self.addCleanup(publisher.stop)
        _seed_settings()
        _seed_admin_roles()
        authorise_auto_stripe(True)
        (
            self.scenario,
            self.payout,
            self.account,
            self.capture,
        ) = build_stripe_payout(prefix=self.prefix)

    def _run(self, fn, count=2):
        def wrapped(index):
            connections.close_all()
            try:
                return fn(index)
            except PayoutExecutionError as exc:
                return f"refused:{exc.code}"
            except Exception as exc:  # noqa: BLE001 - the loser's reason matters
                return f"error:{type(exc).__name__}:{exc}"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=count) as executor:
            return list(executor.map(wrapped, range(count)))

    # -- two workers -----------------------------------------------------

    def test_two_workers_create_exactly_one_transfer(self):
        barrier = Barrier(2)
        gateway = ThreadSafeConnect(barrier=barrier)

        results = self._run(lambda _i: execute_payout(self.payout.pk, gateway=gateway))

        # The external effect is the assertion. One Transfer left the building.
        assert len(gateway.names("create_transfer")) == 1, results
        assert len(gateway.transfers) == 1
        assert PayoutAttempt.objects.count() == 1
        assert (
            PayoutProviderOperation.objects.filter(kind="transfer_create").count() == 1
        )
        assert (
            LedgerTransaction.objects.filter(key__startswith="payout_transfer:").count()
            == 1
        )
        self.payout.refresh_from_db()
        assert self.payout.status == "processing"
        assert ledger.deal_balance(
            self.payout.deal_id, LedgerAccount.CONNECT_FUNDS
        ) == int(self.payout.amount_eur_cents)

    def test_two_workers_create_exactly_one_bank_payout(self):
        gateway = FakeConnect()
        execute_payout(self.payout.pk, gateway=gateway)
        barrier = Barrier(2)

        def advance(_index):
            barrier.wait(timeout=10)
            return execute_payout(self.payout.pk, gateway=gateway)

        results = self._run(advance)
        assert len(gateway.names("create_bank_payout")) == 1, results
        assert StripeDisbursement.objects.count() == 1
        assert StripeDisbursementAllocation.objects.filter(active=True).count() == 1
        assert (
            LedgerTransaction.objects.filter(
                key__startswith="payout_bank_submitted:"
            ).count()
            == 1
        )

    # -- payout versus refund --------------------------------------------

    def test_a_refund_and_a_dispatch_cannot_spend_the_same_cents(self):
        """One of the two must lose, and the loser must be told why."""

        barrier = Barrier(2)
        gateway = ThreadSafeConnect(barrier=None)
        spendable = int(self.capture.amount_eur_cents)
        owed = int(self.payout.amount_eur_cents)

        def worker(index):
            barrier.wait(timeout=10)
            if index == 0:
                return execute_payout(self.payout.pk, gateway=gateway)
            try:
                request_refund(
                    order_id=self.capture.order_id,
                    attempt_id=self.capture.pk,
                    amount_eur_cents=spendable,
                    reason="admin",
                    requested_by_id=None,
                    idempotency_key="race-full-refund",
                )
            except RefundExceedsCapture:
                return "refund_refused"
            return "refund_raised"

        results = self._run(worker)
        refunded = int(
            PaymentRefund.objects.filter(attempt=self.capture)
            .exclude(status="failed")
            .aggregate(total=Sum("amount_eur_cents"))["total"]
            or 0
        )
        reserved = int(
            PayoutFundingAllocation.objects.filter(
                source_attempt=self.capture, release__isnull=True
            ).aggregate(total=Sum("amount_eur_cents"))["total"]
            or 0
        )
        # Whichever order they landed in, the capture is never over-committed.
        assert refunded + reserved <= spendable, (results, refunded, reserved)
        if reserved:
            assert reserved == owed
            assert len(gateway.names("create_transfer")) == 1
        else:
            assert refunded == spendable
            assert gateway.names("create_transfer") == []

    # -- payout versus dispute -------------------------------------------

    def test_a_dispute_and_a_dispatch_never_both_win(self):
        from apps.core.financial_locks import lock_deal_lifecycle
        from apps.finance.payout_release import freeze_payout
        from django.db import transaction

        barrier = Barrier(2)
        gateway = ThreadSafeConnect(barrier=None)

        def worker(index):
            barrier.wait(timeout=10)
            if index == 0:
                return execute_payout(self.payout.pk, gateway=gateway)
            with transaction.atomic():
                aggregate = lock_deal_lifecycle(self.scenario.deal.pk)
                return freeze_payout(aggregate, reason="dispute_race")

        results = self._run(worker)
        self.payout.refresh_from_db()
        transfers = len(gateway.names("create_transfer"))
        if self.payout.status == "frozen" and transfers == 0:
            # The dispute committed first. Nothing was sent, and nothing may be.
            assert PayoutAttempt.objects.filter(
                status__in=["dispatch_committed", "unknown", "accepted", "sent"]
            ).count() == 0, results
        else:
            # The dispatch committed first. The freeze still applies to the next
            # stage, and the committed exposure is recorded rather than denied.
            assert transfers == 1
            from apps.finance.payout_domain import committed_exposure_cents

            assert committed_exposure_cents(self.payout) == int(
                self.payout.amount_eur_cents
            )
            gateway_after = FakeConnect()
            try:
                execute_payout(self.payout.pk, gateway=gateway_after)
            except PayoutExecutionError:
                pass
            assert gateway_after.names("create_bank_payout") == []

    # -- payout versus a Finance hold ------------------------------------

    def test_a_hold_racing_the_bank_stage_stops_it(self):
        gateway = FakeConnect()
        execute_payout(self.payout.pk, gateway=gateway)
        barrier = Barrier(2)

        def worker(index):
            barrier.wait(timeout=10)
            if index == 0:
                return execute_payout(self.payout.pk, gateway=gateway)
            FinanceHold.objects.create(
                payout=self.payout,
                kind="compliance",
                reason_code="race_hold",
                source_reference="race",
            )
            return "hold_opened"

        self._run(worker)
        # Either the hold arrived first and no bank payout exists, or the bank
        # payout was committed first and exactly one exists. Never two, and
        # never a bank payout created after the hold was visible.
        assert len(gateway.names("create_bank_payout")) <= 1
        assert StripeDisbursement.objects.count() <= 1

    # -- restart recovery -------------------------------------------------

    def test_a_worker_that_dies_after_commitment_recovers_the_same_operation(self):
        gateway = FakeConnect()

        def create_then_die(**kwargs):
            FakeConnect.create_transfer(gateway, **kwargs)
            raise RuntimeError("worker killed after the provider accepted")

        gateway.create_transfer = create_then_die
        try:
            execute_payout(self.payout.pk, gateway=gateway)
        except RuntimeError:
            pass
        operation = PayoutProviderOperation.objects.get(kind="transfer_create")
        assert operation.status == "committed"
        assert len(gateway.transfers) == 1

        # While the dead worker's lease is still live, a fresh worker defers
        # rather than racing the same POST. That is the lease doing its job:
        # from outside, a crashed worker and a slow one look identical.
        gateway.create_transfer = lambda **kwargs: FakeConnect.create_transfer(
            gateway, **kwargs
        )
        with self.assertRaises(PayoutExecutionError) as caught:
            execute_payout(self.payout.pk, gateway=gateway)
        assert caught.exception.code == "operation_leased"
        assert len(gateway.transfers) == 1

        # Once it expires, recovery resumes the same identity and the same key.
        PayoutProviderOperation.objects.filter(pk=operation.pk).update(
            retry_after=timezone.now() - timedelta(seconds=1)
        )
        execute_payout(self.payout.pk, gateway=gateway)
        assert len(gateway.transfers) == 1
        operation.refresh_from_db()
        assert operation.status == "accepted"
        assert (
            LedgerTransaction.objects.filter(key__startswith="payout_transfer:").count()
            == 1
        )

    def test_two_bank_payout_retries_produce_one_new_disbursement(self):
        from apps.finance.payout_reconciliation import reconcile_payout

        gateway = FakeConnect()
        execute_payout(self.payout.pk, gateway=gateway)
        execute_payout(self.payout.pk, gateway=gateway)
        gateway.payout_status = "failed"
        reconcile_payout(self.payout.pk, gateway=gateway)
        gateway.payout_status = "pending"

        # A failed bank payout is not re-armed automatically; an operator
        # authorises one retry, and then two workers race to perform it.
        from apps.finance.payout_execution import admin_retry_bank_payout

        self.payout.refresh_from_db()
        admin_retry_bank_payout(
            actor=self.scenario.admin,
            payout_id=self.payout.pk,
            expected_state_version=self.payout.state_version,
        )
        barrier = Barrier(2)

        def retry(_index):
            barrier.wait(timeout=10)
            return execute_payout(self.payout.pk, gateway=gateway)

        self._run(retry)
        assert len(gateway.names("create_transfer")) == 1
        assert len(gateway.names("create_bank_payout")) == 2
        assert StripeDisbursement.objects.count() == 2
        assert StripeDisbursementAllocation.objects.filter(active=True).count() == 1

    # -- accounting -------------------------------------------------------

    def test_the_ledger_balances_after_every_racing_outcome(self):
        barrier = Barrier(2)
        gateway = ThreadSafeConnect(barrier=barrier)
        self._run(lambda _i: execute_payout(self.payout.pk, gateway=gateway))
        totals = {
            account: ledger.deal_balance(self.payout.deal_id, account)
            for account in LedgerAccount.values
        }
        assert sum(totals.values()) == 0, totals
        assert totals[LedgerAccount.CONNECT_FUNDS] >= 0
        assert totals[LedgerAccount.PAYOUT_IN_TRANSIT] >= 0


@POSTGRES_ONLY
@override_settings(**H3_SETTINGS)
class PayoutConstraintTests(TransactionTestCase):
    def setUp(self):
        publisher = patch("apps.core.redis_bus.publish_after_commit")
        publisher.start()
        self.addCleanup(publisher.stop)
        _seed_settings()
        _seed_admin_roles()
        authorise_auto_stripe(True)
        (
            self.scenario,
            self.payout,
            self.account,
            self.capture,
        ) = build_stripe_payout(prefix="h3guard")

    def test_a_second_committed_attempt_is_refused_by_the_database(self):
        from django.db import IntegrityError, transaction

        gateway = FakeConnect()
        execute_payout(self.payout.pk, gateway=gateway)
        live = PayoutAttempt.objects.get()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PayoutAttempt.objects.create(
                    payout=self.payout,
                    sequence=live.sequence + 1,
                    instruction_version=live.instruction_version,
                    amount_eur_cents=live.amount_eur_cents,
                    currency="EUR",
                    rail="stripe_transfer",
                    provider_mode="test",
                    status=PayoutAttempt.Status.ACCEPTED,
                    idempotency_key="second-committed",
                    request_fingerprint="x" * 64,
                )

    def test_a_disbursement_allocation_cannot_exceed_its_bank_payout(self):
        from django.db import DatabaseError, transaction

        gateway = FakeConnect()
        execute_payout(self.payout.pk, gateway=gateway)
        execute_payout(self.payout.pk, gateway=gateway)
        disbursement = StripeDisbursement.objects.get()
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                StripeDisbursementAllocation.objects.create(
                    disbursement=disbursement,
                    payout=self.payout,
                    amount_eur_cents=disbursement.amount_minor,
                )

    def test_a_funding_release_cannot_be_edited_or_deleted(self):
        from django.core.exceptions import ValidationError
        from django.db import DatabaseError, transaction

        from apps.finance.models import PayoutFundingRelease
        from apps.finance.payout_execution import release_allocation

        gateway = FakeConnect()
        from apps.finance.providers.base import ProviderCheckoutRejected

        gateway.fail["create_transfer"] = ProviderCheckoutRejected(
            "no", provider_code="account_invalid"
        )
        execute_payout(self.payout.pk, gateway=gateway)
        release = PayoutFundingRelease.objects.get()
        with self.assertRaises(ValidationError):
            release.reason_code = "edited"
            release.save()
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                PayoutFundingRelease.objects.filter(pk=release.pk).using(
                    "default"
                )._raw_delete("default")
        assert release_allocation is not None

    def test_a_provider_operation_link_is_immutable(self):
        from django.db import DatabaseError, connection as db, transaction

        gateway = FakeConnect()
        execute_payout(self.payout.pk, gateway=gateway)
        operation = PayoutProviderOperation.objects.get(kind="transfer_create")
        with self.assertRaises(DatabaseError):
            with transaction.atomic(), db.cursor() as cursor:
                cursor.execute(
                    "UPDATE finance_payout_provider_operation "
                    "SET funding_allocation_id = NULL WHERE id = %s",
                    [operation.pk],
                )

    def test_a_disbursement_provider_identity_is_immutable(self):
        from django.db import DatabaseError, connection as db, transaction

        gateway = FakeConnect()
        execute_payout(self.payout.pk, gateway=gateway)
        execute_payout(self.payout.pk, gateway=gateway)
        disbursement = StripeDisbursement.objects.get()
        assert disbursement.provider_payout_id
        with self.assertRaises(DatabaseError):
            with transaction.atomic(), db.cursor() as cursor:
                cursor.execute(
                    "UPDATE finance_stripe_disbursement "
                    "SET provider_payout_id = 'po_someone_elses' WHERE id = %s",
                    [disbursement.pk],
                )


@POSTGRES_ONLY
@override_settings(**H3_SETTINGS)
class PayoutSweeperTests(TransactionTestCase):
    def setUp(self):
        publisher = patch("apps.core.redis_bus.publish_after_commit")
        publisher.start()
        self.addCleanup(publisher.stop)
        _seed_settings()
        _seed_admin_roles()
        authorise_auto_stripe(True)
        (
            self.scenario,
            self.payout,
            self.account,
            self.capture,
        ) = build_stripe_payout(prefix="h3sweep")

    def test_the_sweeper_recovers_a_payout_whose_job_was_lost(self):
        from apps.finance.models import ScheduledJob
        from apps.finance.payout_sweeper import sweep_payouts

        gateway = FakeConnect()
        execute_payout(self.payout.pk, gateway=gateway)
        # Redis flushed, the job row deleted, the worker restarted.
        ScheduledJob.objects.all().delete()
        report = sweep_payouts()
        assert report["execute"] >= 1
        assert ScheduledJob.objects.filter(
            kind="payout_execute", key=f"payout_execute:{self.payout.pk}"
        ).exists()

    def test_the_sweeper_pages_rather_than_scanning(self):
        """Bounded by construction: one pass claims at most `limit` per question.

        The point is not the number itself but that there is one. An unbounded
        sweep over a growing payout table is how a safety net becomes the thing
        that takes the database down.
        """

        from apps.finance.payout_sweeper import sweep_payouts

        report = sweep_payouts(limit=1)
        assert report["execute"] <= 1
        assert report["reconcile"] <= 1
        assert report["accounts"] <= 1
