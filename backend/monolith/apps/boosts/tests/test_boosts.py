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
    purchase_boost,
)
from apps.core.phase4_policy import phase4_policy
from apps.deals.tests.phase4_factories import enable_mock_rail
from apps.finance.models import PaymentOrder, PaymentRefund, ScheduledJob
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


# --- catalogue ----------------------------------------------------------------


class BoostCatalogueTests(TestCase):
    def test_list_packages_returns_server_priced_packages(self):
        packages = list_packages()
        policy = phase4_policy()
        assert len(packages) == len(policy.boost.packages)

        for package in packages:
            assert package["currency"] == "EUR"
            assert package["price_eur_cents"] > 0
            assert package["duration_seconds"] > 0
            assert package["ranking_weight"] > 0

        codes = [p["code"] for p in packages]
        assert "boost_24h" in codes
        assert "boost_72h" in codes
        assert "boost_7d" in codes


# --- purchase -----------------------------------------------------------------


class BoostPurchaseTests(TestCase):
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
        assert order.amount_eur_cents == purchase.price_eur_cents == 199
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
        assert refund.amount_eur_cents == order.amount_eur_cents == 199
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
        assert ranked["boost"]["weight"] == scenario.delivery_request.ranking_boost_weight
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

        # Authenticated catalogue read returns server-priced packages.
        res = sender.get(reverse("boosts-packages"))
        assert res.status_code == 200, res.data
        assert res.data["enabled"] is True
        assert res.data["currency"] == "EUR"
        assert len(res.data["packages"]) > 0

        # Outsider purchase is forbidden.
        res = outsider.post(
            reverse("boosts-purchase", args=[scenario.delivery_request.pk]),
            {"package_code": "boost_24h"},
            format="json",
        )
        assert res.status_code in (403, 404)

        # Owner purchase creates pending payment obligation.
        res = sender.post(
            reverse("boosts-purchase", args=[scenario.delivery_request.pk]),
            {"package_code": "boost_24h"},
            format="json",
        )
        assert res.status_code == 201, res.data
        assert res.data["status"] == "pending_payment"
        assert res.data["payment_order_reference"] is not None
        assert res.data["price_eur_cents"] == 199

        # Outsider cannot read request boost state.
        res = outsider.get(
            reverse("boosts-list", args=[scenario.delivery_request.pk])
        )
        assert res.status_code in (403, 404)

        # Owner can read request boost state.
        res = sender.get(
            reverse("boosts-list", args=[scenario.delivery_request.pk])
        )
        assert res.status_code == 200, res.data
        assert res.data["is_owner"] is True
        assert res.data["affects_compatibility"] is False
        assert len(res.data["purchases"]) == 1
