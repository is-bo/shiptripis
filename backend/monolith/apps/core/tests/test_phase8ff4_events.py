"""Live refresh contracts exercised through real V1 transitions."""

from datetime import timedelta
from unittest.mock import patch

from django.db import transaction
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.deals.services import cancel_pending_deal, release_pending_deal_reservation
from apps.deals.tests.phase4_factories import (
    confirm_delivery,
    confirm_pickup,
    delivered_scenario,
    enable_mock_rail,
    freeze_at,
    fund_scenario,
    record_recipient,
    release_delivery_code,
)
from apps.disputes.models import Dispute
from apps.disputes.services import open_dispute, resolve_dispute
from apps.finance.models import PaymentRefund, Payout
from apps.finance.payout_release import evaluate_payout_release
from apps.finance.services import (
    complete_manual_payout,
    mark_refund_succeeded,
    reconcile_attempt,
    request_refund,
)
from apps.finance.tests.factories import (
    build_scenario,
    open_mock_checkout,
    pay_order_with_mock,
)
from apps.matching.v1_services import accept_offer, counter_offer, create_sender_offer
from apps.notifications.models import Notification
from apps.parcels.services import cancel_delivery_request


class LivePublicationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        # TransactionTestCase runs can deplete a reused database's seeds.
        from importlib import import_module
        from django.apps import apps
        from apps.finance.tests.test_phase4_concurrency import _seed_phase4_settings
        _seed_phase4_settings()
        import_module("apps.core.migrations.0009_seed_boost_economics").seed_boost_economics(apps, None)

    def setUp(self):
        enable_mock_rail()
        self.redis = patch("apps.core.redis_bus.get_client").start()
        self.addCleanup(patch.stopall)

    def _rows(self, channel):
        return list(Notification.objects.filter(channel=channel).order_by("pk"))

    def _assert_parties(self, rows, scenario):
        assert {row.recipient_id for row in rows} == {
            scenario.sender.pk, scenario.traveler.pk,
        }
        assert len({row.event_id for row in rows}) == 1

    def _assert_deal_ids(self, payload, deal):
        assert payload["deal_id"] == deal.pk
        assert payload["match_id"] == deal.match_id
        assert payload["parcel_id"] == deal.delivery_request_id
        assert payload["journey_id"] == deal.journey_id

    def test_proposal_counter_accept_publish_only_after_commit_and_replay_is_quiet(self):
        scenario = build_scenario(prefix="f4-offer")
        with self.captureOnCommitCallbacks(execute=True):
            offer = scenario.propose()
            self._assert_parties(self._rows("offer.created"), scenario)
            self.redis.return_value.publish.assert_not_called()
        self.redis.return_value.publish.assert_called_once()
        rows = self._rows("offer.created")
        self._assert_parties(rows, scenario)
        assert rows[0].payload["match_id"] == offer.match_id
        assert rows[0].payload["parcel_id"] == scenario.delivery_request.pk
        assert rows[0].payload["journey_id"] == scenario.journey.pk

        with self.captureOnCommitCallbacks(execute=True):
            child = counter_offer(
                pending_offer=offer, actor=scenario.traveler,
                traveler_reward_eur_cents=2_100,
            )
        rows = self._rows("offer.updated")
        self._assert_parties(rows, scenario)
        assert rows[0].payload["offer_id"] == child.pk

        with self.captureOnCommitCallbacks(execute=True):
            deal = accept_offer(pending_offer=child, actor=scenario.sender).deal
            accept_offer(pending_offer=child, actor=scenario.sender)
        rows = self._rows("offer.accepted")
        assert len(rows) == 2
        self._assert_parties(rows, scenario)
        self._assert_deal_ids(rows[0].payload, deal)

    def test_rolled_back_proposal_never_publishes(self):
        scenario = build_scenario(prefix="f4-rollback")
        with self.captureOnCommitCallbacks(execute=True):
            with transaction.atomic():
                scenario.propose()
                transaction.set_rollback(True)
        assert not Notification.objects.exists()
        self.redis.return_value.publish.assert_not_called()

    def test_losing_negotiation_gets_its_own_ids_only(self):
        winner = build_scenario(prefix="f4-winner")
        loser = build_scenario(prefix="f4-loser")
        winner.propose()
        losing_offer = create_sender_offer(
            sender=winner.sender, delivery_request=winner.delivery_request,
            journey=loser.journey, start_leg_id=loser.leg.pk, end_leg_id=loser.leg.pk,
            traveler_reward_eur_cents=2_000,
        )
        with self.captureOnCommitCallbacks(execute=True):
            winner.accept()
        updates = self._rows("offer.updated")
        assert {row.recipient_id for row in updates} == {winner.sender.pk, loser.traveler.pk}
        assert all(row.payload["match_id"] == losing_offer.match_id for row in updates)
        assert all(row.payload["journey_id"] == loser.journey.pk for row in updates)
        assert all("deal_id" not in row.payload for row in updates)
        assert all(row.recipient_id != loser.traveler.pk for row in self._rows("offer.accepted"))

    def test_grace_expiry_emits_neutral_refresh_once(self):
        scenario = build_scenario(prefix="f4-expiry")
        deal = scenario.accept()
        with self.captureOnCommitCallbacks(execute=True):
            for _ in range(2):
                release_pending_deal_reservation(deal_id=deal.pk, reason="payment_grace_expired")
        rows = self._rows("deal.updated")
        assert len(rows) == 2
        self._assert_parties(rows, scenario)
        self._assert_deal_ids(rows[0].payload, deal)
        assert self._rows("deal.cancelled") == []

    def test_pending_deal_cancellation_notifies_both_parties_once(self):
        scenario = build_scenario(prefix="f4-cancel")
        deal = scenario.accept()
        with self.captureOnCommitCallbacks(execute=True):
            cancel_pending_deal(deal_id=deal.pk, actor_id=scenario.sender.pk)
            cancel_pending_deal(deal_id=deal.pk, actor_id=scenario.sender.pk)
        rows = self._rows("deal.cancelled")
        assert len(rows) == 2
        self._assert_parties(rows, scenario)
        self._assert_deal_ids(rows[0].payload, deal)

    def test_request_cancellation_invalidates_counterparty_negotiation(self):
        scenario = build_scenario(prefix="f4-request")
        offer = scenario.propose()
        with self.captureOnCommitCallbacks(execute=True):
            cancel_delivery_request(
                request_id=scenario.delivery_request.pk, actor_id=scenario.sender.pk,
            )
        rows = self._rows("offer.updated")
        assert any(row.recipient_id == scenario.traveler.pk for row in rows)
        assert all(row.payload["match_id"] == offer.match_id for row in rows)
        client = APIClient()
        client.force_authenticate(scenario.traveler)
        response = client.get(reverse("matches-detail", args=[offer.match_id]))
        assert response.status_code == 200
        assert response.data["status"] == "cancelled"

    def test_payment_failure_and_refund_carry_authoritative_resource_ids(self):
        scenario = build_scenario(prefix="f4-payment")
        deal = scenario.accept()
        order = scenario.balance_order()
        attempt = open_mock_checkout(order)
        with self.captureOnCommitCallbacks(execute=True):
            reconcile_attempt(attempt_id=attempt.pk, outcome="failed")
        failed = self._rows("payment.failed")[0].payload
        assert failed["deal_id"] == deal.pk
        assert failed["request_id"] == scenario.delivery_request.pk
        assert failed["payment_order_id"] == order.pk

        attempt = pay_order_with_mock(self.client, order)
        refund = request_refund(
            order_id=order.pk, attempt_id=attempt.pk, amount_eur_cents=500,
            reason=PaymentRefund.Reason.ADMIN, requested_by_id=scenario.admin.pk,
            idempotency_key="f4-refund",
        )
        with self.captureOnCommitCallbacks(execute=True):
            mark_refund_succeeded(refund_id=refund.pk)
        refunded = self._rows("payment.refunded")[0].payload
        assert refunded["deal_id"] == deal.pk
        assert refunded["request_id"] == scenario.delivery_request.pk
        assert refunded["payment_order_id"] == order.pk

    def test_handover_completion_and_manual_payout_are_live_without_secrets(self):
        scenario = fund_scenario(self.client, prefix="f4-handover")
        with self.captureOnCommitCallbacks(execute=True):
            record_recipient(scenario)
        self._assert_parties(self._rows("deal.updated"), scenario)
        with self.captureOnCommitCallbacks(execute=True):
            confirm_pickup(scenario)
        self._assert_parties(self._rows("match.in_transit"), scenario)
        with self.captureOnCommitCallbacks(execute=True):
            release_delivery_code(scenario)
            confirm_delivery(scenario)
        self._assert_parties(self._rows("handover.delivery_confirmed"), scenario)

        with freeze_at(scenario.deal.protection_ends_at + timedelta(seconds=1)):
            with self.captureOnCommitCallbacks(execute=True):
                evaluate_payout_release(deal_id=scenario.deal.pk)
                evaluate_payout_release(deal_id=scenario.deal.pk)
        rows = self._rows("match.completed")
        assert len(rows) == 2
        self._assert_parties(rows, scenario)
        payout = Payout.objects.get(deal_id=scenario.deal.pk)
        with self.captureOnCommitCallbacks(execute=True):
            for _ in range(2):
                complete_manual_payout(
                    payout_id=payout.pk, admin_actor_id=scenario.admin.pk,
                    payout_currency="EUR", payout_amount_minor=payout.amount_eur_cents,
                    reference="private bank reference",
                )
        paid = [r for r in self._rows("payout.status_changed") if r.payload["status"] == "paid"]
        assert len(paid) == 1
        assert paid[0].recipient_id == scenario.traveler.pk
        for row in Notification.objects.all():
            if "deal_id" not in row.payload:
                continue
            serialized = str(row.payload)
            assert "private bank reference" not in serialized
            assert "recipient@example.invalid" not in serialized
            assert scenario.pickup_code not in serialized
            assert scenario.delivery_code not in serialized
            if row.channel == "payment.captured" and "attempt_id" in row.payload:
                # Funding's inbox row now exists before its on_commit callback.
                # Payments identify the order/request; Deal lifecycle events
                # identify the match/parcel/journey. Both refetch contracts stay
                # authoritative without expanding payment payloads for a test.
                assert row.payload["deal_id"] == scenario.deal.pk
                assert row.payload["request_id"] == scenario.delivery_request.pk
                assert row.payload["payment_order_id"] == scenario.base.balance_order().pk
                assert row.recipient_id == scenario.sender.pk
            else:
                self._assert_deal_ids(row.payload, scenario.deal)

    def test_dispute_open_and_resolve_publish_the_same_safe_aggregate_ids(self):
        scenario = delivered_scenario(self.client, prefix="f4-dispute")
        with self.captureOnCommitCallbacks(execute=True):
            dispute = open_dispute(
                deal_id=scenario.deal.pk, actor_id=scenario.sender.pk,
                category=Dispute.Category.DAMAGED, reason_text="Private dispute evidence.",
            )
        with self.captureOnCommitCallbacks(execute=True):
            for _ in range(2):
                resolve_dispute(
                    dispute_id=dispute.pk, admin_actor_id=scenario.admin.pk,
                    resolution=Dispute.Resolution.FULL_TRAVELER_PAYOUT,
                )
        for channel in ("dispute.opened", "dispute.resolved"):
            rows = self._rows(channel)
            assert len(rows) == 2
            self._assert_parties(rows, scenario)
            self._assert_deal_ids(rows[0].payload, scenario.deal)
            assert rows[0].payload["dispute_id"] == dispute.pk
            assert "Private dispute evidence" not in str(rows[0].payload)
