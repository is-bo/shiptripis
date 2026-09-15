"""The retired paid Boost package: what still has to work, and what is gone.

J2 replaced the paid visibility package with the sender's own reward Boost
(`test_j2_boost.py`). Nothing sells a package any more. But rows sold under the
old product are settled payments, and three things about them still have to be
true:

**A payment already in flight still lands.** A purchase that was `pending_payment`
when J2 shipped reconciles, activates and arms its expiry exactly as before.

**A paid-but-unusable purchase is still refunded, never stranded.** If the
request stopped being boostable while the money was travelling, every captured
cent goes back.

**History is never rewritten or deleted.** The row keeps the amount, the split,
the package, the duration and the settings version it was sold with, and its
ranking effect keeps running until it expires on its own.

And one thing is gone: the catalogue, the preview and the purchase call all
answer 410, in those words, rather than 404.

Purchases are built here by writing the row the retired service used to write.
That is deliberate and it is the honest shape of the test: this suite is about
rows that already exist in a database, not about a code path anyone can reach.
"""

from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.boosts.models import BoostPurchase
from apps.boosts.services import (
    BoostPurchaseRetired,
    activate_paid_boost,
    expire_boost,
    purchase_boost,
)
from apps.core.phase4_policy import phase4_policy
from apps.deals.cancellation import cancel_funded_deal
from apps.deals.tests.phase4_factories import enable_mock_rail
from apps.finance import ledger
from apps.finance.models import (
    LedgerAccount,
    LedgerTransaction,
    PaymentOrder,
    PaymentRefund,
    Payout,
    ScheduledJob,
)
from apps.finance.settlement import assert_deal_reconciles, read_deal_money
from apps.finance.tests.factories import (
    build_scenario,
    deliver_mock_webhook,
    open_mock_checkout,
    pay_order_with_mock,
    succeed_attempt,
)
from apps.matching.compatibility import CompatibilityResult
from apps.matching.policy import Phase2Policy
from apps.matching.ranking import rank_compatible_candidate
from apps.parcels.models import DeliveryRequest, ParcelRequest


def client_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def legacy_purchase(
    *,
    delivery_request,
    buyer,
    amount_eur_cents: int = 500,
    package_code: str = "boost_24h",
) -> BoostPurchase:
    """Write the row the retired `purchase_boost` used to write.

    Split economics, a separate BOOST payment order, a package snapshot and a
    duration -- all exactly as they were sold. This is a fixture for rows that
    predate J2, not a way back to a product that is no longer offered.
    """

    policy = phase4_policy()
    package = policy.boost.package(package_code)
    share_bps = policy.boost.traveler_share_bps
    traveler = (amount_eur_cents * share_bps) // 10_000
    purchase = BoostPurchase.objects.create(
        delivery_request=delivery_request,
        buyer=buyer,
        package_code=package.code,
        package_snapshot=package.snapshot(),
        duration_seconds=package.duration_seconds,
        amount_eur_cents=amount_eur_cents,
        ranking_weight=package.ranking_weight,
        economics_version=BoostPurchase.EconomicsVersion.TRAVELER_SPLIT_V1,
        traveler_share_bps=share_bps,
        traveler_boost_eur_cents=traveler,
        platform_boost_eur_cents=amount_eur_cents - traveler,
        business_settings_version=policy.settings_version,
    )
    order = PaymentOrder.objects.create(
        owner=buyer,
        purpose=PaymentOrder.Purpose.BOOST,
        amount_eur_cents=amount_eur_cents,
        delivery_request_id=delivery_request.pk,
        boost_reference=str(purchase.public_reference),
        business_settings_version=policy.settings_version,
        terms_snapshot={"boost_package": package.snapshot()},
    )
    purchase.payment_order = order
    purchase.save(update_fields=["payment_order", "updated_at"])
    return purchase


# --- retirement ---------------------------------------------------------------


class BoostPackageRetirementTests(TestCase):
    def test_every_package_surface_answers_gone_and_names_the_replacement(self):
        scenario = build_scenario(prefix="brt1")
        sender = client_for(scenario.sender)

        for name in ("boosts-packages", "boosts-preview"):
            res = sender.get(reverse(name))
            assert res.status_code == 410, (name, res.status_code)
            assert res.data["code"] == "boost_package_retired"
            assert "/boost" in res.data["detail"]

        res = sender.post(
            reverse("boosts-purchase", args=[scenario.delivery_request.pk]),
            {"package_code": "boost_24h", "amount_eur_cents": 777},
            format="json",
        )
        assert res.status_code == 410, res.data
        assert res.data["code"] == "boost_package_retired"

        # The service refuses by name rather than disappearing, so a caller
        # that still reaches for it gets an answer instead of an AttributeError.
        with self.assertRaises(BoostPurchaseRetired):
            purchase_boost(delivery_request_id=1, actor_id=1, package_code="x")

    def test_historical_purchases_remain_readable_by_their_owner(self):
        scenario = build_scenario(prefix="brt2")
        purchase = legacy_purchase(
            delivery_request=scenario.delivery_request,
            buyer=scenario.sender,
            amount_eur_cents=777,
        )
        res = client_for(scenario.sender).get(
            reverse("boosts-list", args=[scenario.delivery_request.pk])
        )
        assert res.status_code == 200, res.data
        assert len(res.data["purchases"]) == 1
        row = res.data["purchases"][0]
        assert row["amount_eur_cents"] == 777
        assert row["economics_version"] == "traveler_split_v1"
        assert row["traveler_boost_eur_cents"] == 582
        assert row["platform_boost_eur_cents"] == 195
        assert str(purchase.public_reference) == row["public_reference"]

        # And nobody else's business.
        other = client_for(scenario.outsider).get(
            reverse("boosts-list", args=[scenario.delivery_request.pk])
        )
        assert other.status_code in (403, 404)


# --- activation ---------------------------------------------------------------


class BoostActivationTests(TestCase):
    def test_activation_only_by_authoritative_payment_and_idempotent_webhooks(
        self,
    ):
        enable_mock_rail()
        scenario = build_scenario(prefix="ba1")
        req = scenario.delivery_request

        purchase = legacy_purchase(
            delivery_request=req, buyer=scenario.sender, amount_eur_cents=500
        )
        order = purchase.payment_order

        attempt = pay_order_with_mock(self.client, order)
        purchase.refresh_from_db()
        assert purchase.status == BoostPurchase.Status.ACTIVE
        assert purchase.is_active() is True
        assert purchase.activated_at is not None
        assert purchase.expires_at == purchase.activated_at + timedelta(
            seconds=purchase.duration_seconds
        )

        req.refresh_from_db()
        assert req.ranking_boost_weight == purchase.ranking_weight == 2
        assert req.ranking_boost_expires_at == purchase.expires_at

        # A replayed webhook returns cleanly and does not re-activate or extend.
        res = deliver_mock_webhook(self.client, succeed_attempt(attempt))
        assert res.status_code == 200

        again = activate_paid_boost(order_id=order.pk)
        assert again is False

        purchase.refresh_from_db()
        assert purchase.status == BoostPurchase.Status.ACTIVE
        assert req.ranking_boost_expires_at == purchase.expires_at


# --- expiry -------------------------------------------------------------------


class BoostExpiryTests(TestCase):
    def test_boost_expiry_retires_ranking_and_preserves_purchase_history(self):
        enable_mock_rail()
        scenario = build_scenario(prefix="be1")
        req = scenario.delivery_request

        purchase = legacy_purchase(
            delivery_request=req, buyer=scenario.sender, amount_eur_cents=500
        )
        pay_order_with_mock(self.client, purchase.payment_order)
        purchase.refresh_from_db()

        # The durable scheduled job is armed at activation.
        job = ScheduledJob.objects.get(
            kind=ScheduledJob.Kind.BOOST_EXPIRY,
            key=f"boost_expiry:{purchase.pk}",
        )
        assert job.run_at == purchase.expires_at

        # Attempting to expire before expires_at changes nothing.
        assert (
            expire_boost(
                purchase_id=purchase.pk,
                at=purchase.expires_at - timedelta(seconds=10),
            )
            == "not_due"
        )
        purchase.refresh_from_db()
        assert purchase.status == BoostPurchase.Status.ACTIVE

        # Expiring at or after expires_at retires the boost.
        assert (
            expire_boost(
                purchase_id=purchase.pk,
                at=purchase.expires_at + timedelta(seconds=1),
            )
            == "expired"
        )
        purchase.refresh_from_db()
        assert purchase.status == BoostPurchase.Status.EXPIRED

        req.refresh_from_db()
        assert req.ranking_boost_weight == 0
        assert req.ranking_boost_expires_at is None

        # Purchase row still exists (history is never deleted).
        assert BoostPurchase.objects.filter(pk=purchase.pk).exists()


class BoostDeliveryEconomicsTests(TestCase):
    def test_paid_boost_is_bound_to_deal_and_added_to_traveler_payout(self):
        enable_mock_rail()
        scenario = build_scenario(prefix="bec1")
        purchase = legacy_purchase(
            delivery_request=scenario.delivery_request,
            buyer=scenario.sender,
            amount_eur_cents=777,
        )
        pay_order_with_mock(self.client, purchase.payment_order)

        deal = scenario.accept(reward_eur_cents=2_000)
        purchase.refresh_from_db()
        assert purchase.deal_id == deal.pk
        assert purchase.payment_order.deal_id == deal.pk
        # A bound historical purchase keeps its split, and the Deal records
        # which model produced these numbers rather than assuming the new one.
        assert deal.terms.boost_economics_version == "traveler_split_v1"
        assert deal.terms.boost_amount_minor == 777
        assert deal.terms.boost_traveler_bonus_minor == 582
        assert deal.terms.boost_platform_fee_minor == 195
        assert deal.terms.traveler_total_minor == 2_582
        # Its cash was collected before the Deal existed, so the balance the
        # sender still owes is the base sender total and nothing more.
        assert scenario.balance_order().amount_eur_cents == 2_500

        pay_order_with_mock(self.client, scenario.balance_order())
        payout = Payout.objects.get(deal=deal)
        assert payout.amount_eur_cents == 2_582
        allocation = LedgerTransaction.objects.get(
            kind=LedgerTransaction.Kind.BOOST_ALLOCATION
        )
        binding = LedgerTransaction.objects.get(
            kind=LedgerTransaction.Kind.BOOST_BINDING
        )
        assert binding.entries.count() == 4
        assert allocation.entries.count() == 3
        assert sum(entry.amount_eur_cents for entry in allocation.entries.all()) == 0
        assert (
            binding.entries.get(
                account=LedgerAccount.DEAL_FUNDS,
                deal__isnull=True,
            ).amount_eur_cents
            == 777
        )
        assert ledger.deal_balance(deal.pk, LedgerAccount.DEAL_FUNDS) == 0

    def test_pre_funding_deal_cancellation_refunds_bound_boost(self):
        from apps.deals.services import cancel_pending_deal

        enable_mock_rail()
        scenario = build_scenario(prefix="bec2")
        purchase = legacy_purchase(
            delivery_request=scenario.delivery_request,
            buyer=scenario.sender,
            amount_eur_cents=500,
        )
        pay_order_with_mock(self.client, purchase.payment_order)
        deal = scenario.accept(reward_eur_cents=2_000)

        cancel_pending_deal(deal_id=deal.pk, actor_id=scenario.sender.pk)
        purchase.refresh_from_db()
        assert purchase.status == BoostPurchase.Status.REFUNDED
        assert purchase.disposition_reason == "deal_cancelled"
        refund = PaymentRefund.objects.get(order=purchase.payment_order)
        assert refund.amount_eur_cents == purchase.amount_eur_cents
        assert read_deal_money(deal).boost_cash_eur_cents == 0
        scenario.delivery_request.refresh_from_db()
        assert scenario.delivery_request.ranking_boost_weight == 0
        assert scenario.delivery_request.ranking_boost_expires_at is None

    def test_funded_deal_cancellation_refunds_boost_and_balances_subledger(self):
        enable_mock_rail()
        scenario = build_scenario(prefix="bec3")
        purchase = legacy_purchase(
            delivery_request=scenario.delivery_request,
            buyer=scenario.sender,
            amount_eur_cents=777,
        )
        pay_order_with_mock(self.client, purchase.payment_order)
        deal = scenario.accept(reward_eur_cents=2_000)
        pay_order_with_mock(self.client, scenario.balance_order())
        money = read_deal_money(deal)

        quote = cancel_funded_deal(deal_id=deal.pk, actor_id=scenario.traveler.pk)

        refunded = sum(
            PaymentRefund.objects.filter(order__deal_id=deal.pk)
            .exclude(status=PaymentRefund.Status.FAILED)
            .values_list("amount_eur_cents", flat=True)
        )
        assert money.boost_cash_eur_cents == 777
        assert quote.sender_refund_eur_cents == money.collected_eur_cents
        assert refunded == money.collected_eur_cents
        assert read_deal_money(deal).boost_cash_eur_cents == 0
        assert assert_deal_reconciles(deal.pk)["net"] == 0
        assert Payout.objects.get(deal=deal).status == Payout.Status.CANCELLED


# --- paid but unusable --------------------------------------------------------


class BoostUnusableRefundTests(TestCase):
    def test_paid_but_unusable_boost_is_refunded_in_full_with_no_ranking_write(
        self,
    ):
        """A request that stops being boostable mid-payment refunds in full.

        The purchase is marked unusable and then refunded, a full PaymentRefund
        is raised, and the ranking columns are never written.
        """

        enable_mock_rail()
        scenario = build_scenario(prefix="bur1")
        req = scenario.delivery_request

        purchase = legacy_purchase(
            delivery_request=req, buyer=scenario.sender, amount_eur_cents=500
        )
        order = purchase.payment_order
        attempt = open_mock_checkout(order)

        # Cancel the request while payment is in flight.
        DeliveryRequest.objects.filter(pk=req.pk).update(
            status=ParcelRequest.Status.CANCELLED
        )

        # Payment webhook arrives from provider.
        response = deliver_mock_webhook(self.client, succeed_attempt(attempt))
        assert response.status_code == 200

        purchase.refresh_from_db()
        assert purchase.status == BoostPurchase.Status.REFUNDED
        assert purchase.disposition_reason == "request_cancelled"

        # A real refund is created for the full amount.
        refund = PaymentRefund.objects.get(order=order)
        assert refund.amount_eur_cents == order.amount_eur_cents == 500
        assert refund.reason == PaymentRefund.Reason.BOOST_UNUSABLE

        # Ranking columns were never written.
        req.refresh_from_db()
        assert req.ranking_boost_weight == 0
        assert req.ranking_boost_expires_at is None


# --- hard invariant: boost never creates compatibility ------------------------


class BoostCompatibilityInvariantTests(TestCase):
    def test_ranking_raises_on_incompatible_candidate_regardless_of_boost(self):
        """Compatibility must pass before ranking; no boost can bypass it."""

        scenario = build_scenario(prefix="bci1")
        policy = Phase2Policy.from_settings(scenario.policy.settings_version)

        incompatible = CompatibilityResult(
            compatible=False,
            rejection_codes=("route_detour_exceeded",),
            checks=(),
            covered_legs=(),
            pickup_position=None,
            delivery_position=None,
            pickup_at=None,
            delivery_at=None,
            pickup_added_duration_seconds=None,
            pickup_detour_meters=0,
            delivery_detour_meters=0,
            added_distance_meters=0,
            added_duration_seconds=None,
            matched_distance_meters=None,
            matched_distance_method="unavailable",
            distance_components=(),
            capacity_remaining_by_leg=(),
            limitations=(),
            route_provider=None,
        )

        with self.assertRaises(ValueError) as caught:
            rank_compatible_candidate(
                compatibility=incompatible,
                delivery_request=scenario.delivery_request,
                policy=policy,
            )
        assert "Hard compatibility must pass before ranking." in str(caught.exception)

    def test_an_active_historical_purchase_still_ranks_until_it_expires(self):
        enable_mock_rail()
        scenario = build_scenario(prefix="bci2")

        purchase = legacy_purchase(
            delivery_request=scenario.delivery_request,
            buyer=scenario.sender,
            amount_eur_cents=500,
        )
        pay_order_with_mock(self.client, purchase.payment_order)
        scenario.delivery_request.refresh_from_db()
        assert scenario.delivery_request.ranking_boost_weight == 2
        assert scenario.delivery_request.is_ranking_boost_active() is True
        assert scenario.delivery_request.ranking_boost_expires_at > timezone.now()
