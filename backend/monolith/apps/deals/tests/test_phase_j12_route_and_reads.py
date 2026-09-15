"""Phase J1.2 — the funded route over canonical geography, and the cost of a read.

I1A proved the sender's funded route over the **legacy** shape, where a journey
leg carries `origin`/`destination` `Location` rows. Every V1 journey is
canonical: its legs carry `origin_place`/`destination_place` and leave those two
columns NULL. That is the shape the deployed app actually creates, and it is the
shape the owner was looking at when they reported an empty route — so it needs
its own evidence that the server side is sound, separate from the client fix.

The second half is a cost bound. J1.2 measured every screen's endpoint against
the deployed TEST runtime and found none of them slow; what it found instead was
the app asking for the same things three times. A query-count bound is the guard
that keeps the server half of that true — it measures the code, where a
wall-clock assertion would measure the machine.
"""

from __future__ import annotations

from django.db import connection
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework.test import APIClient

from apps.deals.models import Deal, DealLegAllocation
from apps.deals.route import funded_route
from apps.matching.v1_services import accept_offer
from apps.matching.tests.test_phase8dr_offer_locks import CanonicalOfferFixture

from apps.finance.tests.factories import pay_order_with_mock
from apps.deals.tests.phase4_factories import enable_mock_rail


def client_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


class CanonicalFundedRouteTests(CanonicalOfferFixture, TestCase):
    """What a Sender sees of a canonical CDG → ALG → Jijel carrying route."""

    def setUp(self):
        enable_mock_rail()
        self.build_world()
        offer = self.propose()
        self.deal = accept_offer(pending_offer=offer, actor=self.traveler).deal
        from apps.finance.models import PaymentOrder

        order = PaymentOrder.objects.get(
            deal=self.deal, purpose=PaymentOrder.Purpose.DEAL_BALANCE
        )
        pay_order_with_mock(Client(), order)
        self.deal.refresh_from_db()
        assert self.deal.status == Deal.Status.FUNDED, self.deal.status

    def test_the_legs_under_test_really_carry_no_location_rows(self):
        # If this stops holding, the rest of this class stops covering the
        # shape it was written for.
        assert (
            self.journey.legs.filter(
                origin__isnull=True, destination__isnull=True
            ).count()
            == 2
        )

    def test_funding_freezes_a_canonical_route_rather_than_an_empty_one(self):
        frozen = self.deal.arrival_snapshot["route"]
        assert len(frozen) == 2
        assert [row["position"] for row in frozen] == [0, 1]
        # Identities, not labels: a place's id is immutable and its name is not.
        assert all(row["origin_place_id"] is not None for row in frozen)
        assert all(row["origin_location_id"] is None for row in frozen)

    def test_the_sender_sees_every_stop_named_in_order(self):
        route = client_for(self.sender).get(
            reverse("deals-detail", args=[self.deal.pk])
        ).json()["route"]

        assert route["basis"] == "funded_snapshot"
        legs = route["legs"]
        assert [leg["position"] for leg in legs] == [0, 1]
        assert [leg["mode"] for leg in legs] == ["FLIGHT", "DRIVE"]

        # The whole point: a canonical endpoint resolves to a real label. An
        # endpoint that resolved to `None` here is exactly what would render as
        # a route line of unlabelled dots.
        stops = [legs[0]["origin"], *[leg["destination"] for leg in legs]]
        assert all(stop is not None for stop in stops)
        assert [stop["display_label"] for stop in stops] == [
            "Paris Charles de Gaulle",
            "Houari Boumediene",
            "Jijel",
        ]
        assert stops[0]["kind"] == "place"
        assert stops[0]["iata_code"] == "CDG"
        assert stops[2]["iata_code"] is None

        # Scheduled times come through on both ends of both legs.
        assert all(leg["depart_at"] and leg["arrive_at"] for leg in legs)

        # The contract seam. `DealRouteEndpoint.fromJson` on the client reads
        # exactly these keys; a field renamed on this side and not the other is
        # how a route silently becomes a column of unlabelled dots, which is the
        # defect this phase fixed on the discovery contract.
        assert set(stops[0]) == {
            "kind",
            "id",
            "name",
            "display_label",
            "place_type",
            "iata_code",
            "country_code",
            "parent_name",
        }

    def test_the_canonical_route_still_withholds_private_traveler_detail(self):
        route = client_for(self.sender).get(
            reverse("deals-detail", args=[self.deal.pk])
        ).json()["route"]
        forbidden = {
            "route_polyline",
            "route_metadata",
            "distance_meters",
            "route_duration_seconds",
            "capacity_kg",
            "proofs",
            "flight_number",
        }
        for leg in route["legs"]:
            assert forbidden.isdisjoint(leg)
            for endpoint in (leg["origin"], leg["destination"]):
                assert "latitude" not in endpoint
                assert "longitude" not in endpoint

    def test_a_historical_deal_with_no_frozen_route_says_so_rather_than_guessing(self):
        # The backfill left these as `route: []`. Live Journey rows are not
        # historical evidence, so the honest answer is that there is none.
        Deal.objects.filter(pk=self.deal.pk).update(
            arrival_snapshot={**self.deal.arrival_snapshot, "route": []}
        )
        self.deal.refresh_from_db()
        assert funded_route(deal=self.deal, viewer_id=self.deal.sender_id) is None
        # And the allocations still exist, so nothing reconstructed one from them.
        assert DealLegAllocation.objects.filter(deal=self.deal).exists()

    def test_a_non_party_gets_no_canonical_route_either(self):
        assert funded_route(deal=self.deal, viewer_id=self.other.pk) is None
        body = client_for(self.other).get(
            reverse("deals-detail", args=[self.deal.pk])
        )
        # A non-party cannot even read the Deal.
        assert body.status_code == 404

    def test_the_traveler_sees_their_own_carrying_route(self):
        route = funded_route(deal=self.deal, viewer_id=self.deal.traveler_id)
        assert route is not None and len(route["legs"]) == 2


class ReadCostTests(CanonicalOfferFixture, TestCase):
    """Bounds on the reads every screen makes, as a regression guard."""

    def setUp(self):
        enable_mock_rail()
        self.build_world()
        offer = self.propose()
        self.deal = accept_offer(pending_offer=offer, actor=self.traveler).deal
        from apps.finance.models import PaymentOrder

        pay_order_with_mock(
            Client(),
            PaymentOrder.objects.get(
                deal=self.deal, purpose=PaymentOrder.Purpose.DEAL_BALANCE
            ),
        )
        self.deal.refresh_from_db()

    def measure(self, client, path):
        client.get(path)  # warm any first-request caches
        with CaptureQueriesContext(connection) as captured:
            response = client.get(path)
        assert response.status_code == 200, (path, response.status_code)
        return len(captured.captured_queries)

    def test_the_screens_a_user_opens_read_a_bounded_number_of_times(self):
        """Every bound here is generous and every one of them is flat.

        These are the endpoints the app fires on Home, Deliveries and a
        delivery detail. Measured against the deployed TEST runtime they answer
        in tens of milliseconds; what must not happen is one of them quietly
        growing a per-row query and turning that into seconds.
        """

        sender = client_for(self.sender)
        assert self.measure(sender, "/api/deals") <= 8
        assert self.measure(sender, "/api/deals?activity=active") <= 8
        assert self.measure(sender, f"/api/deals/{self.deal.pk}") <= 16
        assert self.measure(sender, "/api/parcels") <= 8

    def test_a_deal_list_does_not_cost_a_query_per_deal(self):
        sender = client_for(self.sender)
        one = self.measure(sender, "/api/deals")

        # Four more Deals for the same sender, each with its own journey.
        for index in range(4):
            journey, flight, drive = self._journey(
                self.traveler, origin=self.cdg
            )
            request = self._request(self.paris, self.jijel, title=f"Extra {index}")
            offer = self.propose(
                delivery_request=request,
                journey=journey,
                start_leg_id=flight.pk,
                end_leg_id=drive.pk,
            )
            accept_offer(pending_offer=offer, actor=self.traveler)

        assert Deal.objects.filter(sender=self.sender).count() == 5
        assert self.measure(sender, "/api/deals") == one

    def test_discovery_does_not_cost_a_query_per_candidate(self):
        """Candidate discovery scores every journey it scans.

        Scoring is in-memory over rows the two prefetches already loaded, so
        the query count is a property of the code and not of how many Travelers
        happen to be publishing. This is the guard on that.
        """

        from apps.core.models import BusinessSettingsVersion
        from apps.matching.discovery import compatible_journeys_for_request
        from apps.matching.policy import Phase2Policy

        policy = Phase2Policy.from_settings(
            BusinessSettingsVersion.objects.get(
                status=BusinessSettingsVersion.Status.ACTIVE
            )
        )
        fresh = self._request(self.paris, self.jijel, title="Discovery")

        def scan():
            with CaptureQueriesContext(connection) as captured:
                results = compatible_journeys_for_request(
                    delivery_request=fresh, policy=policy
                )
            return len(captured.captured_queries), len(results)

        one_queries, one_results = scan()
        for _ in range(9):
            self._journey(self.traveler, origin=self.cdg)
        many_queries, many_results = scan()

        assert one_results >= 1
        assert many_results > one_results
        assert many_queries == one_queries
        assert one_queries <= 10, one_queries

    def test_discovery_is_bounded_by_the_policy_result_limit(self):
        from apps.core.models import BusinessSettingsVersion
        from apps.matching.discovery import compatible_journeys_for_request
        from apps.matching.policy import Phase2Policy

        policy = Phase2Policy.from_settings(
            BusinessSettingsVersion.objects.get(
                status=BusinessSettingsVersion.Status.ACTIVE
            )
        )
        fresh = self._request(self.paris, self.jijel, title="Bounded")
        for _ in range(policy.result_limit + 3):
            self._journey(self.traveler, origin=self.cdg)

        results = compatible_journeys_for_request(
            delivery_request=fresh, policy=policy
        )
        assert len(results) <= policy.result_limit
