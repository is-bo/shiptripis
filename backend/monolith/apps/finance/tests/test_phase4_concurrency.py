"""PostgreSQL concurrency tests for the Phase 4 lifecycle.

Real threads, real connections, real row locks. SQLite cannot express any of
this, so the module skips there rather than passing vacuously.

Four races are tested, and they are the four that can lose money:

* **A dispute against the protection timer.** The one the whole lock ordering
  was designed around. There must be no interleaving in which an active dispute
  coexists with a payout the database considers releasable.
* **Two administrators resolving one dispute.** Exactly one economic
  resolution may exist, no matter how the two arrive.
* **A cancellation against a pickup confirmation.** Exactly one wins outright;
  the loser must be refused against committed state, not half-applied.
* **A code redeemed twice at once.** One transition, one set of side effects.

Every future is joined and every worker exception is re-raised in the main
thread. A race test that silently swallowed a thread's exception would be a
test that passes because nothing happened.
"""

from __future__ import annotations

import unittest
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from importlib import import_module
from threading import Barrier
from unittest.mock import patch

from django.db import connection, connections
from django.db.models import Sum
from django.utils import timezone

from django.test import TransactionTestCase

from apps.core.business_settings import get_active_business_settings
from apps.core.models import BusinessSettingsVersion
from apps.deals.cancellation import CancellationError, cancel_funded_deal
from apps.deals.models import Deal, DealEvent
from apps.deals.recipient import set_recipient
from apps.disputes.models import Dispute
from apps.disputes.services import DisputeError, open_dispute, resolve_dispute
from apps.finance.models import PaymentRefund, Payout
from apps.finance.payout_release import evaluate_payout_release
from apps.finance.providers.mock import MockGateway
from apps.finance.settlement import assert_deal_reconciles, read_deal_money
from apps.handover.models import DealHandoverCode
from apps.handover.services import HandoverError, reveal_code, submit_code
from apps.notifications.models import OutboundMessage

from .factories import build_scenario, pay_order_with_mock

POSTGRES_ONLY = unittest.skipUnless(
    connection.vendor == "postgresql",
    "Phase 4 lifecycle guarantees are PostgreSQL row-lock behaviour.",
)

RELEASABLE_PAYOUT_STATUSES = (
    Payout.Status.ELIGIBLE,
    Payout.Status.SCHEDULED,
    Payout.Status.PROCESSING,
    Payout.Status.PAID,
)


def _seed_phase4_settings() -> BusinessSettingsVersion:
    """`TransactionTestCase` truncates tables; re-seed the active revision.

    The Phase 4 revision, not the Phase 3 one: these tests are about buffers,
    protection windows and cancellation policy, and every one of those numbers
    comes from the revision a Deal was funded under.
    """

    active = BusinessSettingsVersion.objects.filter(status="active").first()
    if active is not None and "handover" in (active.policy or {}):
        return active
    document = import_module(
        "apps.core.migrations.0006_seed_phase4_business_settings"
    ).PHASE4_POLICY
    BusinessSettingsVersion.objects.filter(status="active").update(status="retired")
    row, _ = BusinessSettingsVersion.objects.get_or_create(
        version=4,
        defaults={
            "canonical_currency": "EUR",
            "commission_rate_bps": 2_500,
            "pricing_version": "v1-lifecycle-1",
            "policy": deepcopy(document),
        },
    )
    BusinessSettingsVersion.objects.filter(pk=row.pk).update(
        status="active", activated_at=timezone.now()
    )
    return BusinessSettingsVersion.objects.get(pk=row.pk)


def _enable_mock_rail() -> None:
    settings_version = get_active_business_settings()
    policy = deepcopy(settings_version.policy)
    policy["payments"]["providers"]["mock_enabled"] = True
    BusinessSettingsVersion.objects.filter(pk=settings_version.pk).update(policy=policy)


def _refunded(deal_id: int) -> int:
    return int(
        PaymentRefund.objects.filter(order__deal_id=deal_id)
        .exclude(status=PaymentRefund.Status.FAILED)
        .aggregate(total=Sum("amount_eur_cents"))["total"]
        or 0
    )


@POSTGRES_ONLY
class Phase4ConcurrencyTestCase(TransactionTestCase):
    reset_sequences = True
    prefix = "p4conc"

    def setUp(self):
        publisher = patch("apps.core.redis_bus.publish_after_commit")
        publisher.start()
        self.addCleanup(publisher.stop)
        MockGateway.reset()
        _seed_phase4_settings()
        _enable_mock_rail()

    # -- scenario construction ------------------------------------------------

    def build_funded(self, suffix: str, *, reward: int = 20_000):
        scenario = build_scenario(prefix=f"{self.prefix}-{suffix}")
        scenario.accept(reward_eur_cents=reward)
        pay_order_with_mock(self.client, scenario.balance_order())
        scenario.deal.refresh_from_db()
        assert scenario.deal.status == Deal.Status.FUNDED
        set_recipient(
            deal_id=scenario.deal.pk,
            actor_id=scenario.sender.pk,
            full_name="Recipient Example",
            email=f"recipient-{suffix}@example.invalid",
        )
        scenario.deal.refresh_from_db()
        return scenario

    def build_delivered(self, suffix: str, *, reward: int = 20_000):
        scenario = self.build_funded(suffix, reward=reward)
        deal = scenario.deal
        pickup = reveal_code(
            deal_id=deal.pk,
            kind=DealHandoverCode.Kind.PICKUP,
            actor_id=scenario.sender.pk,
        ).code
        submit_code(
            deal_id=deal.pk,
            kind=DealHandoverCode.Kind.PICKUP,
            actor_id=scenario.traveler.pk,
            submitted_code=pickup,
        )
        deal.refresh_from_db()
        # Move the stored buffer instants into the past instead of faking the
        # clock: these tests run in threads, and a patched global clock would
        # not be honest about what each connection sees.
        #
        # Both of them. The buffer is recorded twice on purpose -- on the Deal
        # and on the code row -- and the reveal path checks the code's copy
        # while the release path checks the Deal's. Moving only one produces an
        # active code that still refuses to open, which is the gate working.
        past = timezone.now() - timedelta(seconds=1)
        Deal.objects.filter(pk=deal.pk).update(delivery_code_available_at=past)
        DealHandoverCode.objects.filter(
            deal_id=deal.pk, kind=DealHandoverCode.Kind.DELIVERY
        ).update(available_at=past)
        from apps.handover.services import release_delivery_code

        release_delivery_code(deal_id=deal.pk)
        delivery = reveal_code(
            deal_id=deal.pk,
            kind=DealHandoverCode.Kind.DELIVERY,
            actor_id=scenario.sender.pk,
        ).code
        submit_code(
            deal_id=deal.pk,
            kind=DealHandoverCode.Kind.DELIVERY,
            actor_id=scenario.traveler.pk,
            submitted_code=delivery,
        )
        deal.refresh_from_db()
        assert deal.status == Deal.Status.PROTECTION_WINDOW
        # I1A: this delivers at the wall clock, hours before the journey's own
        # scheduled arrival, so the arrival floor would hold the payout for
        # reasons none of these race tests are about. Move the floor into the
        # past, exactly as the stored buffer instants above were moved.
        Deal.objects.filter(pk=deal.pk).update(
            funded_scheduled_arrival_floor_at=timezone.now() - timedelta(seconds=1)
        )
        deal.refresh_from_db()
        return scenario

    # -- thread plumbing ------------------------------------------------------

    def race(self, first, second):
        """Run two callables at the same instant, on their own connections.

        Returns `(result_or_exception, result_or_exception)`. Both futures are
        always joined, and an exception is returned rather than swallowed so the
        caller can assert which side lost and why.
        """

        barrier = Barrier(2, timeout=30)

        def wrap(fn):
            def run():
                connections.close_all()
                try:
                    barrier.wait()
                    return fn()
                except Exception as exc:  # noqa: BLE001 - returned, not hidden
                    return exc
                finally:
                    connections.close_all()

            return run

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(wrap(first)), pool.submit(wrap(second))]
            return [future.result(timeout=60) for future in futures]


# --- the race the lock order exists for ---------------------------------------


@POSTGRES_ONLY
class DisputeVersusProtectionExpiryRaceTests(Phase4ConcurrencyTestCase):
    prefix = "p4conc-race"

    def test_a_dispute_and_the_expiry_timer_never_both_win(self):
        """Twelve rounds, both orderings, one invariant.

        An active dispute must never coexist with a payout in a releasable
        state. Which side wins is allowed to vary run to run — that is what a
        race is — but the outcome must always be one of the two coherent ones.
        """

        for round_index in range(12):
            scenario = self.build_delivered(f"r{round_index}")
            deal = scenario.deal
            # Put the deadline exactly on the instant both threads will act.
            Deal.objects.filter(pk=deal.pk).update(
                protection_ends_at=timezone.now() + timedelta(milliseconds=50)
            )
            deal.refresh_from_db()

            def open_it(deal_id=deal.pk, sender_id=scenario.sender.pk):
                return open_dispute(
                    deal_id=deal_id,
                    actor_id=sender_id,
                    category=Dispute.Category.NOT_DELIVERED,
                    reason_text="It never arrived.",
                )

            def expire_it(deal_id=deal.pk):
                return evaluate_payout_release(deal_id=deal_id)

            outcomes = self.race(open_it, expire_it)
            for outcome in outcomes:
                if isinstance(outcome, Exception) and not isinstance(
                    outcome, DisputeError
                ):
                    raise outcome

            payout = Payout.objects.get(deal_id=deal.pk)
            active = Dispute.objects.filter(
                deal_id=deal.pk, status__in=Dispute.ACTIVE_STATUSES
            ).exists()

            if active:
                assert payout.status not in RELEASABLE_PAYOUT_STATUSES, (
                    round_index,
                    payout.status,
                )
            else:
                # The timer won and no dispute exists. Either it released the
                # payout or it found the window still open; both are coherent.
                assert payout.status in (
                    Payout.Status.ELIGIBLE,
                    Payout.Status.NOT_ELIGIBLE,
                ), (round_index, payout.status)

    def test_a_dispute_arriving_after_release_pulls_the_payout_back(self):
        scenario = self.build_delivered("after")
        deal = scenario.deal
        Deal.objects.filter(pk=deal.pk).update(
            protection_ends_at=timezone.now() - timedelta(seconds=1)
        )
        assert evaluate_payout_release(deal_id=deal.pk) == "released"

        open_dispute(
            deal_id=deal.pk,
            actor_id=scenario.admin.pk,
            category=Dispute.Category.DAMAGED,
            reason_text="Reported to support.",
            as_admin=True,
        )
        assert Payout.objects.get(deal_id=deal.pk).status == Payout.Status.FROZEN


# --- two administrators -------------------------------------------------------


@POSTGRES_ONLY
class ConcurrentResolutionTests(Phase4ConcurrencyTestCase):
    prefix = "p4conc-res"

    def test_two_administrators_resolving_at_once_produce_one_settlement(self):
        for round_index in range(6):
            scenario = self.build_delivered(f"res{round_index}")
            deal = scenario.deal
            money = read_deal_money(deal)
            dispute = open_dispute(
                deal_id=deal.pk,
                actor_id=scenario.sender.pk,
                category=Dispute.Category.DAMAGED,
                reason_text="Damaged.",
            )

            def refund_all(dispute_id=dispute.pk, admin_id=scenario.admin.pk):
                return resolve_dispute(
                    dispute_id=dispute_id,
                    admin_actor_id=admin_id,
                    resolution=Dispute.Resolution.FULL_SENDER_REFUND,
                )

            def pay_traveler(dispute_id=dispute.pk, admin_id=scenario.sender.pk):
                return resolve_dispute(
                    dispute_id=dispute_id,
                    admin_actor_id=admin_id,
                    resolution=Dispute.Resolution.FULL_TRAVELER_PAYOUT,
                )

            outcomes = self.race(refund_all, pay_traveler)
            for outcome in outcomes:
                if isinstance(outcome, Exception):
                    raise outcome

            row = Dispute.objects.get(pk=dispute.pk)
            assert row.status == Dispute.Status.RESOLVED
            assert row.resolution in Dispute.Resolution.values

            # Exactly one economic resolution: the refunds on this Deal match
            # the single stored decision, and the ledger balances.
            assert _refunded(deal.pk) == row.sender_refund_eur_cents, round_index
            assert (
                row.sender_refund_eur_cents
                + row.traveler_payout_eur_cents
                + row.platform_fee_eur_cents
                == money.collected_eur_cents
            )
            assert assert_deal_reconciles(deal.pk)["net"] == 0
            assert (
                DealEvent.objects.filter(
                    deal_id=deal.pk, kind=DealEvent.Kind.DISPUTE_RESOLVED
                ).count()
                == 1
            )


# --- cancellation against pickup ----------------------------------------------


@POSTGRES_ONLY
class CancellationVersusPickupRaceTests(Phase4ConcurrencyTestCase):
    prefix = "p4conc-cnl"

    def test_exactly_one_of_cancellation_and_pickup_takes_effect(self):
        for round_index in range(10):
            scenario = self.build_funded(f"c{round_index}")
            deal = scenario.deal
            # Well outside the 24-hour cutoff, so a sender cancellation is
            # free and "cancellation won" has exactly one expected refund.
            # The late-cancellation arithmetic has its own tests.
            Deal.objects.filter(pk=deal.pk).update(
                agreed_pickup_at=timezone.now() + timedelta(hours=72)
            )
            code = reveal_code(
                deal_id=deal.pk,
                kind=DealHandoverCode.Kind.PICKUP,
                actor_id=scenario.sender.pk,
            ).code
            money = read_deal_money(deal)

            def cancel(deal_id=deal.pk, sender_id=scenario.sender.pk):
                return cancel_funded_deal(deal_id=deal_id, actor_id=sender_id)

            def pickup(
                deal_id=deal.pk,
                traveler_id=scenario.traveler.pk,
                submitted=code,
            ):
                return submit_code(
                    deal_id=deal_id,
                    kind=DealHandoverCode.Kind.PICKUP,
                    actor_id=traveler_id,
                    submitted_code=submitted,
                )

            outcomes = self.race(cancel, pickup)
            for outcome in outcomes:
                if isinstance(outcome, Exception) and not isinstance(
                    outcome, (CancellationError, HandoverError)
                ):
                    raise outcome

            deal.refresh_from_db()
            cancelled = deal.status in (
                Deal.Status.CANCELLED,
                Deal.Status.REFUNDED,
                Deal.Status.PARTIALLY_REFUNDED,
            )
            picked_up = deal.pickup_confirmed_at is not None

            # Never both, never neither.
            assert cancelled != picked_up, (round_index, deal.status, picked_up)

            if cancelled:
                # The sender was made whole and nothing is stranded.
                assert _refunded(deal.pk) == money.collected_eur_cents, round_index
            else:
                assert _refunded(deal.pk) == 0, round_index
            assert assert_deal_reconciles(deal.pk)["net"] == 0


# --- a code redeemed twice at once --------------------------------------------


@POSTGRES_ONLY
class ConcurrentCodeSubmissionTests(Phase4ConcurrencyTestCase):
    prefix = "p4conc-code"

    def test_the_same_pickup_code_submitted_twice_at_once_confirms_once(self):
        for round_index in range(8):
            scenario = self.build_funded(f"p{round_index}")
            deal = scenario.deal
            code = reveal_code(
                deal_id=deal.pk,
                kind=DealHandoverCode.Kind.PICKUP,
                actor_id=scenario.sender.pk,
            ).code

            def submit(
                deal_id=deal.pk,
                traveler_id=scenario.traveler.pk,
                submitted=code,
            ):
                return submit_code(
                    deal_id=deal_id,
                    kind=DealHandoverCode.Kind.PICKUP,
                    actor_id=traveler_id,
                    submitted_code=submitted,
                )

            outcomes = self.race(submit, submit)
            succeeded = [o for o in outcomes if not isinstance(o, Exception)]
            failed = [o for o in outcomes if isinstance(o, Exception)]
            assert len(succeeded) == 1, (round_index, outcomes)
            assert all(isinstance(o, HandoverError) for o in failed), outcomes

            deal.refresh_from_db()
            assert deal.status == Deal.Status.IN_TRANSIT
            assert (
                DealEvent.objects.filter(
                    deal_id=deal.pk, kind=DealEvent.Kind.PICKUP_CONFIRMED
                ).count()
                == 1
            )
            assert (
                DealHandoverCode.objects.filter(
                    deal_id=deal.pk,
                    kind=DealHandoverCode.Kind.DELIVERY,
                ).count()
                == 1
            )

    def test_two_delivery_code_releases_at_once_notify_the_recipient_once(self):
        from apps.handover.services import release_delivery_code

        for round_index in range(6):
            scenario = self.build_funded(f"d{round_index}")
            deal = scenario.deal
            code = reveal_code(
                deal_id=deal.pk,
                kind=DealHandoverCode.Kind.PICKUP,
                actor_id=scenario.sender.pk,
            ).code
            submit_code(
                deal_id=deal.pk,
                kind=DealHandoverCode.Kind.PICKUP,
                actor_id=scenario.traveler.pk,
                submitted_code=code,
            )
            past = timezone.now() - timedelta(seconds=1)
            Deal.objects.filter(pk=deal.pk).update(delivery_code_available_at=past)
            DealHandoverCode.objects.filter(
                deal_id=deal.pk, kind=DealHandoverCode.Kind.DELIVERY
            ).update(available_at=past)

            def release(deal_id=deal.pk):
                return release_delivery_code(deal_id=deal_id)

            outcomes = self.race(release, release)
            for outcome in outcomes:
                if isinstance(outcome, Exception):
                    raise outcome
            assert sorted(outcomes) == ["already_released", "released"], (
                round_index,
                outcomes,
            )

            deal.refresh_from_db()
            assert deal.status == Deal.Status.DELIVERY_READY
            assert (
                OutboundMessage.objects.filter(
                    deal_id=deal.pk,
                    kind=OutboundMessage.Kind.RECIPIENT_DELIVERY_CODE,
                ).count()
                == 1
            )
            assert (
                DealEvent.objects.filter(
                    deal_id=deal.pk, kind=DealEvent.Kind.DELIVERY_CODE_RELEASED
                ).count()
                == 1
            )
