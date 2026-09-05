"""Paid sender boosts: catalogue, checkout, authoritative activation and expiry.

Four things are being defended here:

**Boost never creates compatibility.** It is a ranking-only signal that operates
strictly on compatible candidates. Handing an incompatible candidate to the
ranking calculator raises, and the boost payload explicitly declares
`compatibility_override=False`.

**Money activates a boost; a client never does.** A purchase creates a pending
obligation and leaves the request's ranking columns untouched. Activation is
driven exclusively by an authoritative provider payment event.

**Stacking takes the maximum weight and the latest expiry.** Multiple active
boosts extend duration and redundancy without unbounded score inflation.

**Paid but unusable boosts are refunded, never stranded.** When a request is
matched, expired or cancelled before the payment lands, every captured cent is
refunded in full.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.boosts.models import BoostPurchase
from apps.boosts.services import (
    BoostError,
    NotAuthorized,
    activate_paid_boost,
    expire_boost,
    list_packages,
    preview_boost,
    purchase_boost as purchase_boost_service,
)
from apps.core.business_settings import (
    activate_business_settings,
    get_active_business_settings,
)
from apps.core.models import BusinessSettingsVersion
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
from apps.matching.compatibility import CompatibilityResult, evaluate_compatibility
from apps.matching.policy import Phase2Policy
from apps.matching.ranking import rank_compatible_candidate
from apps.parcels.models import DeliveryRequest, ParcelRequest
from apps.routing.providers import UnavailableRouteProvider


def client_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def purchase_boost(**kwargs):
    """Tests that are not about pricing buy the policy minimum."""

    policy = phase4_policy()
    return purchase_boost_service(
        **kwargs,
        amount_eur_cents=policy.boost.minimum_amount_eur_cents,
        preview_settings_version=policy.settings_version.version,
    )


# --- catalogue ----------------------------------------------------------------


class BoostCatalogueTests(TestCase):
    def test_list_packages_returns_visibility_packages(self):
        packages = list_packages()
        policy = phase4_policy()
        assert len(packages) == len(policy.boost.packages)

        for package in packages:
            assert package["currency"] == "EUR"
            assert "price_eur_cents" not in package
            assert package["duration_seconds"] > 0
            assert package["ranking_weight"] > 0

        codes = [p["code"] for p in packages]
        assert "boost_24h" in codes
        assert "boost_72h" in codes
        assert "boost_7d" in codes

    def test_preview_enforces_only_the_minimum_and_rounds_in_integer_cents(self):
        policy = phase4_policy()
        with self.assertRaises(BoostError) as caught:
            preview_boost(package_code="boost_24h", amount_eur_cents=499)
        assert caught.exception.code == "boost_amount_below_minimum"

        preview = preview_boost(
            package_code="boost_24h", amount_eur_cents=10_000_000_001
        )
        assert preview["amount_eur_cents"] == 10_000_000_001
        expected_traveler = (10_000_000_001 * policy.boost.traveler_share_bps) // 10_000
        assert preview["traveler_boost_eur_cents"] == expected_traveler
        assert preview["platform_boost_eur_cents"] == 10_000_000_001 - expected_traveler
        assert preview["rounding_rule"] == "traveler_floor_platform_remainder"


# --- purchase -----------------------------------------------------------------


class BoostPurchaseTests(TestCase):
    def test_stale_preview_is_refused_before_creating_money(self):
        scenario = build_scenario(prefix="bp0")
        policy = phase4_policy()
        with self.assertRaises(BoostError) as caught:
            purchase_boost_service(
                delivery_request_id=scenario.delivery_request.pk,
                actor_id=scenario.sender.pk,
                package_code="boost_24h",
                amount_eur_cents=500,
                preview_settings_version=policy.settings_version.version - 1,
            )
        assert caught.exception.code == "boost_preview_stale"
        assert (
            PaymentOrder.objects.filter(purpose=PaymentOrder.Purpose.BOOST).count() == 0
        )

    def test_owner_purchasing_boost_creates_pending_obligation_and_leaves_ranking_untouched(
        self,
    ):
        scenario = build_scenario(prefix="bp1")
        req = scenario.delivery_request

        purchase = purchase_boost(
            delivery_request_id=req.pk,
            actor_id=scenario.sender.pk,
            package_code="boost_24h",
        )

        assert purchase.status == BoostPurchase.Status.PENDING_PAYMENT
        assert purchase.is_active() is False
        assert purchase.activated_at is None
        assert purchase.expires_at is None

        order = purchase.payment_order
        assert order is not None
        assert order.purpose == PaymentOrder.Purpose.BOOST
        assert order.amount_eur_cents == purchase.amount_eur_cents == 500
        assert purchase.traveler_boost_eur_cents == 375
        assert purchase.platform_boost_eur_cents == 125
        assert order.boost_reference == str(purchase.public_reference)

        req.refresh_from_db()
        assert req.ranking_boost_weight == 0
        assert req.ranking_boost_expires_at is None

    def test_non_owner_purchasing_is_refused(self):
        scenario = build_scenario(prefix="bp2")
        with self.assertRaises(NotAuthorized):
            purchase_boost(
                delivery_request_id=scenario.delivery_request.pk,
                actor_id=scenario.outsider.pk,
                package_code="boost_24h",
            )

    def test_unknown_package_code_is_refused(self):
        scenario = build_scenario(prefix="bp3")
        with self.assertRaises(BoostError) as caught:
            purchase_boost(
                delivery_request_id=scenario.delivery_request.pk,
                actor_id=scenario.sender.pk,
                package_code="unknown_turbo_package",
            )
        assert caught.exception.code == "boost_package_unknown"

    def test_inactive_or_expired_request_cannot_be_boosted(self):
        scenario = build_scenario(prefix="bp4")
        req = scenario.delivery_request

        DeliveryRequest.objects.filter(pk=req.pk).update(
            status=ParcelRequest.Status.CANCELLED
        )
        with self.assertRaises(BoostError) as caught:
            purchase_boost(
                delivery_request_id=req.pk,
                actor_id=scenario.sender.pk,
                package_code="boost_24h",
            )
        assert caught.exception.code == "boost_request_not_active"

        DeliveryRequest.objects.filter(pk=req.pk).update(
            status=ParcelRequest.Status.OPEN,
            deadline_at=timezone.now() - timedelta(minutes=1),
        )
        with self.assertRaises(BoostError) as caught:
            purchase_boost(
                delivery_request_id=req.pk,
                actor_id=scenario.sender.pk,
                package_code="boost_24h",
            )
        assert caught.exception.code == "boost_request_expired"

    def test_per_request_active_boost_limit_is_enforced(self):
        scenario = build_scenario(prefix="bp5")
        max_active = phase4_policy().boost.max_active_per_request

        for _ in range(max_active):
            purchase_boost(
                delivery_request_id=scenario.delivery_request.pk,
                actor_id=scenario.sender.pk,
                package_code="boost_24h",
            )

        with self.assertRaises(BoostError) as caught:
            purchase_boost(
                delivery_request_id=scenario.delivery_request.pk,
                actor_id=scenario.sender.pk,
                package_code="boost_24h",
            )
        assert caught.exception.code == "boost_limit_reached"

    def test_amount_does_not_scale_ranking_weight(self):
        scenario = build_scenario(prefix="bp6")
        policy = phase4_policy()
        low = purchase_boost_service(
            delivery_request_id=scenario.delivery_request.pk,
            actor_id=scenario.sender.pk,
            package_code="boost_24h",
            amount_eur_cents=500,
            preview_settings_version=policy.settings_version.version,
        )
        high = purchase_boost_service(
            delivery_request_id=scenario.delivery_request.pk,
            actor_id=scenario.sender.pk,
            package_code="boost_24h",
            amount_eur_cents=50_000,
            preview_settings_version=policy.settings_version.version,
        )
        assert low.ranking_weight == high.ranking_weight == 2

    def test_new_settings_do_not_reprice_an_existing_purchase(self):
        scenario = build_scenario(prefix="bp7")
        purchase = purchase_boost(
            delivery_request_id=scenario.delivery_request.pk,
            actor_id=scenario.sender.pk,
            package_code="boost_24h",
        )
        committed_settings_id = purchase.business_settings_version_id

        active = get_active_business_settings()
        changed_policy = deepcopy(active.policy)
        changed_policy["boost"]["traveler_share_bps"] = 8_235
        changed = BusinessSettingsVersion.objects.create(
            version=active.version + 1,
            commission_rate_bps=active.commission_rate_bps,
            pricing_version="v1-boost-economics-test",
            policy=changed_policy,
        )
        activate_business_settings(changed)

        updated_preview = preview_boost(package_code="boost_24h", amount_eur_cents=500)
        purchase.refresh_from_db()
        assert updated_preview["traveler_boost_eur_cents"] == 411
        assert updated_preview["platform_boost_eur_cents"] == 89
        assert purchase.business_settings_version_id == committed_settings_id
        assert purchase.traveler_share_bps == 7_500
        assert purchase.traveler_boost_eur_cents == 375
        assert purchase.platform_boost_eur_cents == 125


# --- activation ---------------------------------------------------------------


class BoostActivationTests(TestCase):
    def test_activation_only_by_authoritative_payment_and_idempotent_webhooks(
        self,
    ):
        enable_mock_rail()
        scenario = build_scenario(prefix="ba1")
        req = scenario.delivery_request

        purchase = purchase_boost(
            delivery_request_id=req.pk,
            actor_id=scenario.sender.pk,
            package_code="boost_24h",
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


# --- stacking -----------------------------------------------------------------


class BoostStackingTests(TestCase):
    def test_stacking_multiple_boosts_takes_maximum_weight_and_latest_expiry(
        self,
    ):
        """Stacking two active purchases of different weights leaves
        ranking_boost_weight at the maximum across them (never the sum),
        and ranking_boost_expires_at at the latest expiry.
        """
        enable_mock_rail()
        scenario = build_scenario(prefix="bs1")
        req = scenario.delivery_request

        p1 = purchase_boost(
            delivery_request_id=req.pk,
            actor_id=scenario.sender.pk,
            package_code="boost_24h",
        )
        pay_order_with_mock(self.client, p1.payment_order)

        p2 = purchase_boost(
            delivery_request_id=req.pk,
            actor_id=scenario.sender.pk,
            package_code="boost_72h",
        )
        pay_order_with_mock(self.client, p2.payment_order)

        p1.refresh_from_db()
        p2.refresh_from_db()
        req.refresh_from_db()

        assert p1.ranking_weight == 2
        assert p2.ranking_weight == 4
        # Ranking boost weight is the MAXIMUM, never the sum 2+4=6.
        assert req.ranking_boost_weight == 4
        assert req.ranking_boost_expires_at == max(p1.expires_at, p2.expires_at)


# --- expiry -------------------------------------------------------------------


class BoostExpiryTests(TestCase):
    def test_boost_expiry_retires_ranking_and_preserves_purchase_history(self):
        enable_mock_rail()
        scenario = build_scenario(prefix="be1")
        req = scenario.delivery_request

        purchase = purchase_boost(
            delivery_request_id=req.pk,
            actor_id=scenario.sender.pk,
            package_code="boost_24h",
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
        purchase = purchase_boost_service(
            delivery_request_id=scenario.delivery_request.pk,
            actor_id=scenario.sender.pk,
            package_code="boost_24h",
            amount_eur_cents=777,
            preview_settings_version=phase4_policy().settings_version.version,
        )
        pay_order_with_mock(self.client, purchase.payment_order)

        deal = scenario.accept(reward_eur_cents=2_000)
        purchase.refresh_from_db()
        assert purchase.deal_id == deal.pk
        assert purchase.payment_order.deal_id == deal.pk
        assert deal.terms.boost_amount_minor == 777
        assert deal.terms.boost_traveler_bonus_minor == 582
        assert deal.terms.boost_platform_fee_minor == 195
        assert deal.terms.traveler_total_minor == 2_582

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
        purchase = purchase_boost(
            delivery_request_id=scenario.delivery_request.pk,
            actor_id=scenario.sender.pk,
            package_code="boost_24h",
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
        purchase = purchase_boost_service(
            delivery_request_id=scenario.delivery_request.pk,
            actor_id=scenario.sender.pk,
            package_code="boost_24h",
            amount_eur_cents=777,
            preview_settings_version=phase4_policy().settings_version.version,
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
        """When a request becomes unboostable (e.g. cancelled) between checkout creation
        and payment arrival, the purchase is marked unusable then refunded, a full
        PaymentRefund is raised, and ranking columns are never modified.
        """
        enable_mock_rail()
        scenario = build_scenario(prefix="bur1")
        req = scenario.delivery_request

        purchase = purchase_boost(
            delivery_request_id=req.pk,
            actor_id=scenario.sender.pk,
            package_code="boost_24h",
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
        """Hard compatibility must pass before ranking is evaluated; boost cannot bypass it."""
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

    def test_boost_only_adds_ranking_points_and_never_creates_compatibility(self):
        enable_mock_rail()
        scenario = build_scenario(prefix="bci2")

        purchase = purchase_boost(
            delivery_request_id=scenario.delivery_request.pk,
            actor_id=scenario.sender.pk,
            package_code="boost_24h",
        )
        pay_order_with_mock(self.client, purchase.payment_order)
        scenario.delivery_request.refresh_from_db()
        assert scenario.delivery_request.ranking_boost_weight == 2
        assert scenario.delivery_request.is_ranking_boost_active() is True

        policy = Phase2Policy.from_settings(scenario.policy.settings_version)
        compat = evaluate_compatibility(
            delivery_request=scenario.delivery_request,
            journey=scenario.journey,
            policy=policy,
            route_provider=UnavailableRouteProvider(),
        )
        assert compat.compatible is True

        ranked = rank_compatible_candidate(
            compatibility=compat,
            delivery_request=scenario.delivery_request,
            policy=policy,
        )
        assert ranked["boost"]["compatibility_override"] is False
        assert ranked["boost"]["active"] is True
        assert (
            ranked["boost"]["weight"] == scenario.delivery_request.ranking_boost_weight
        )
        boost_points = min(
            policy.max_boost_points,
            scenario.delivery_request.ranking_boost_weight
            * policy.boost_points_per_weight,
        )
        assert ranked["boost"]["points"] == boost_points
        assert ranked["score"] == ranked["base_score"] + boost_points


# --- API surface --------------------------------------------------------------


class BoostApiTests(TestCase):
    def test_boost_api_endpoints_catalogue_purchase_and_list(self):
        scenario = build_scenario(prefix="bapi1")
        sender = client_for(scenario.sender)
        outsider = client_for(scenario.outsider)
        anon = APIClient()

        # Unauthenticated catalogue read is rejected.
        assert anon.get(reverse("boosts-packages")).status_code == 401

        # Authenticated catalogue read returns visibility packages and economics.
        res = sender.get(reverse("boosts-packages"))
        assert res.status_code == 200, res.data
        assert res.data["enabled"] is True
        assert res.data["currency"] == "EUR"
        assert res.data["minimum_amount_eur_cents"] == 500
        assert res.data["traveler_share_bps"] > 5_000
        assert len(res.data["packages"]) > 0

        preview = sender.post(
            reverse("boosts-preview"),
            {"package_code": "boost_24h", "amount_eur_cents": 777},
            format="json",
        )
        assert preview.status_code == 200, preview.data
        assert preview.data["traveler_boost_eur_cents"] == 582
        assert preview.data["platform_boost_eur_cents"] == 195
        purchase_body = {
            "package_code": "boost_24h",
            "amount_eur_cents": 777,
            "preview_settings_version": preview.data["settings_version"],
        }

        # Outsider purchase is forbidden.
        res = outsider.post(
            reverse("boosts-purchase", args=[scenario.delivery_request.pk]),
            purchase_body,
            format="json",
        )
        assert res.status_code in (403, 404)

        # Owner purchase creates pending payment obligation.
        res = sender.post(
            reverse("boosts-purchase", args=[scenario.delivery_request.pk]),
            purchase_body,
            format="json",
        )
        assert res.status_code == 201, res.data
        assert res.data["status"] == "pending_payment"
        assert res.data["payment_order_reference"] is not None
        assert res.data["amount_eur_cents"] == 777
        assert res.data["traveler_boost_eur_cents"] == 582
        assert res.data["platform_boost_eur_cents"] == 195

        # Outsider cannot read request boost state.
        res = outsider.get(reverse("boosts-list", args=[scenario.delivery_request.pk]))
        assert res.status_code in (403, 404)

        # Owner can read request boost state.
        res = sender.get(reverse("boosts-list", args=[scenario.delivery_request.pk]))
        assert res.status_code == 200, res.data
        assert res.data["is_owner"] is True
        assert res.data["affects_compatibility"] is False
        assert len(res.data["purchases"]) == 1
