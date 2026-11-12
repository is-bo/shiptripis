"""L3A: matching over routes for everyone.

The package's "done when", proved end to end: a traveler creates Lille → Paris
→ Lyon → Marseille by road, Marseille → Algiers by ferry and Algiers → Sétif →
Constantine by road, publishes it with an approved ferry ticket, and the
journey matches leg by leg — through the scan and through Find Travelers —
while a parcel that never boards the ferry takes nothing from it.

Around that, every new gate is held to its contract: the switch and the
crossing close a whole journey to new offers, a stop only serves what it
accepts, the traveler's item rules hold, volume and parcel slots are real
capacity (including under concurrent acceptance), a pause hides a journey from
every discovery surface, and the handover note reaches the sender only once
the deal is funded.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier

from django.core.cache import cache
from django.db import close_old_connections, connection, connections
from django.test import Client, TestCase, TransactionTestCase, override_settings, skipUnlessDBFeature
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import User
from apps.admin_panel.permissions import AdminRole, assign_admin_roles
from apps.admin_panel.services import review_flight_proof
from apps.deals.models import Deal, DealLegAllocation
from apps.deals.tests.phase4_factories import enable_mock_rail
from apps.discovery.listings import listable_journeys
from apps.finance.tests.factories import pay_order_with_mock
from apps.matching.compatibility import evaluate_compatibility
from apps.matching.discovery import compatible_journeys_for_request, phase2_policy
from apps.matching.models import Offer
from apps.matching.v1_services import (
    CapacityExceeded,
    IncompatibleCandidate,
    JourneyPaused,
    accept_offer,
    create_sender_offer,
)
from apps.parcels.models import ParcelRequest
from apps.trips.models import Journey, JourneyLegProof
from apps.trips.services import pause_own_journey, resume_own_journey
from apps.trips.tests.sea_world import DRIVE, MARSEILLE_ALGIERS_METERS, SEA, SeaWorld

REWARD = 3_000

DETERMINISTIC_ROUTES = override_settings(
    ROUTE_PROVIDER_CLASS="apps.routing.testing.DeterministicFixtureRouteProvider",
    ROUTE_PROVIDER_OPTIONS={"road_distance_multiplier": "1.20", "speed_kph": 60},
)


def client_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


class MatchingWorld(SeaWorld):
    def build_matching_world(self) -> None:
        self.build_sea_world()
        self.traveler = self.person("l3a-traveler@example.com")
        self.sender = self.person("l3a-sender@example.com")
        self.policy = phase2_policy()

    def scan(self, delivery_request):
        return compatible_journeys_for_request(delivery_request=delivery_request, policy=self.policy)

    def candidate(self, delivery_request, journey):
        return next(
            (row for row in self.scan(delivery_request) if row.journey.pk == journey.pk),
            None,
        )

    def evaluate(self, delivery_request, journey):
        return evaluate_compatibility(
            delivery_request=delivery_request,
            journey=Journey.objects.get(pk=journey.pk),
            policy=self.policy,
        )

    def propose(self, delivery_request, journey, *, first: int, last: int) -> Offer:
        legs = list(journey.legs.order_by("position"))
        return create_sender_offer(
            sender=self.sender,
            delivery_request=delivery_request,
            journey=journey,
            start_leg_id=legs[first].pk,
            end_leg_id=legs[last].pk,
            traveler_reward_eur_cents=REWARD,
        )

    def accept(self, offer: Offer):
        return accept_offer(pending_offer=offer, actor=self.traveler)


# ---------------------------------------------------------------------------
# Done when: one journey across road, sea and road
# ---------------------------------------------------------------------------


@DETERMINISTIC_ROUTES
class RouteForEveryoneTests(MatchingWorld, APITestCase):
    """The package's acceptance route, created and published through the API."""

    def setUp(self):
        cache.clear()
        self.build_matching_world()
        self.set_sea_switch(True)
        self.depart = self.now + timedelta(days=4)
        stops = [
            (DRIVE, self.lille, self.paris),
            (DRIVE, self.paris, self.lyon),
            (DRIVE, self.lyon, self.marseille),
            (SEA, self.marseille, self.algiers),
            (DRIVE, self.algiers, self.setif),
            (DRIVE, self.setif, self.constantine),
        ]
        legs = []
        for position, (mode, origin, destination) in enumerate(stops):
            depart = self.depart + timedelta(hours=6 * position)
            legs.append(
                {
                    "position": position,
                    "mode": mode,
                    "origin_place_id": origin.pk,
                    "destination_place_id": destination.pk,
                    "depart_at": depart.isoformat(),
                    "arrive_at": (depart + timedelta(hours=4)).isoformat(),
                    "capacity_kg": "12.00",
                }
            )
        traveler_client = client_for(self.traveler)
        response = traveler_client.post(
            reverse("journeys-list-create"),
            {
                "start_place_id": self.lille.pk,
                "destination_place_id": self.constantine.pk,
                "notes": "",
                "legs": legs,
            },
            format="json",
        )
        assert response.status_code == 201, response.data
        self.journey = Journey.objects.get(pk=response.data["id"])
        self.legs = list(self.journey.legs.order_by("position"))
        self.sea_leg = self.legs[3]

        # The ferry ticket goes through the real review, and only then may
        # the journey publish.
        refused = traveler_client.post(reverse("journeys-publish", args=(self.journey.pk,)))
        assert refused.status_code == 409 and refused.data["code"] == "sea_proof_not_approved"
        proof = self.ticket(self.sea_leg, JourneyLegProof.Status.PENDING)
        reviewer = self.person("l3a-trust@example.com", verified=False)
        assign_admin_roles(reviewer, (AdminRole.TRUST,))
        review_flight_proof(actor=reviewer, proof_id=proof.pk, decision=JourneyLegProof.Status.APPROVED)
        published = traveler_client.post(reverse("journeys-publish", args=(self.journey.pk,)))
        assert published.status_code == 200, published.data
        self.journey.refresh_from_db()

    def test_the_route_stores_what_each_mode_can_honestly_measure(self):
        distances = [leg.distance_meters for leg in self.legs]

        # French cities have no catalogue coordinates, so nothing was routed.
        assert distances[:3] == [None, None, None]
        assert distances[3] == MARSEILLE_ALGIERS_METERS
        assert all(distance and distance > 0 for distance in distances[4:])
        assert self.sea_leg.route_metadata == {"sea_crossing_id": self.marseille_algiers.pk}

    def test_every_leg_and_every_span_matches(self):
        for first, last in ((0, 0), (0, 2), (1, 3), (2, 4), (3, 3), (3, 5), (5, 5), (0, 5)):
            with self.subTest(first=first, last=last):
                delivery_request = self.request_over(self.sender, self.journey, first, last)
                evaluation = self.candidate(delivery_request, self.journey)
                assert evaluation is not None
                result = evaluation.compatibility
                assert result.compatible, result.rejection_codes
                assert [leg.position for leg in result.covered_legs] == list(range(first, last + 1))
                checks = {row["code"]: row for row in result.checks}
                assert checks["sea_legs_available"]["passed"]
                assert checks["sea_proofs_approved"]["passed"]
                assert checks["sea_proofs_approved"]["details"]["sea_leg_ids"] == [self.sea_leg.pk]

    def test_distance_follows_each_mode(self):
        crossing = self.candidate(
            self.request_over(self.sender, self.journey, 3, 3), self.journey
        ).compatibility
        assert crossing.matched_distance_meters == MARSEILLE_ALGIERS_METERS
        assert crossing.matched_distance_method == "great_circle_sea_crossing"

        french = self.candidate(
            self.request_over(self.sender, self.journey, 0, 1), self.journey
        ).compatibility
        # Uncoordinated catalogue cities price at the distance floor; the
        # scan neither fails nor invents a distance.
        assert french.matched_distance_meters == 0
        assert french.matched_distance_method == "canonical_place_floor"
        assert french.limitations == ()

        algerian = self.candidate(
            self.request_over(self.sender, self.journey, 4, 5), self.journey
        ).compatibility
        assert algerian.matched_distance_method == "stored_routed_road_distance"
        assert algerian.matched_distance_meters == self.legs[4].distance_meters + self.legs[5].distance_meters

    def find_travelers(self, delivery_request) -> dict:
        response = client_for(self.sender).get(
            reverse("matches-find-travelers-v1"), {"parcel_id": delivery_request.pk}
        )
        assert response.status_code == 200, response.data
        rows = [row for row in response.data["results"] if row["journey_id"] == self.journey.pk]
        assert len(rows) == 1, response.data
        return rows[0]

    def test_find_travelers_names_the_ferry_only_to_a_parcel_that_sails(self):
        sailing = self.find_travelers(self.request_over(self.sender, self.journey, 1, 4))

        assert sailing["primary_mode"] == SEA
        assert [segment["mode"] for segment in sailing["route"]["segments"]] == [
            DRIVE,
            DRIVE,
            SEA,
            DRIVE,
        ]
        reasons = [reason["code"] for reason in sailing["match_reasons"]]
        assert "sea_proof_approved" in reasons
        assert "flight_proof_approved" not in reasons

        road_only = self.find_travelers(self.request_over(self.sender, self.journey, 0, 0))

        assert road_only["primary_mode"] == DRIVE
        assert "sea_proof_approved" not in [reason["code"] for reason in road_only["match_reasons"]]

    def test_a_parcel_that_never_sails_takes_nothing_from_the_ferry(self):
        delivery_request = self.request_over(self.sender, self.journey, 0, 0)
        proposal = self.find_travelers(delivery_request)["proposal"]

        response = client_for(self.sender).post(
            reverse("matches-propose-v1"),
            {"parcel_id": delivery_request.pk, **proposal, "traveler_reward_eur_cents": REWARD},
            format="json",
        )
        assert response.status_code == 201, response.data
        deal = self.accept(Offer.objects.get(pk=response.data["id"])).deal

        allocations = list(DealLegAllocation.objects.filter(deal=deal))
        assert [row.journey_leg_id for row in allocations] == [self.legs[0].pk]
        assert allocations[0].allocated_volume_l == Decimal("3.000")
        assert not DealLegAllocation.objects.filter(journey_leg=self.sea_leg).exists()


# ---------------------------------------------------------------------------
# The switch and the crossing close the whole journey
# ---------------------------------------------------------------------------


class SeaAvailabilityTests(MatchingWorld, APITestCase):
    def setUp(self):
        self.build_matching_world()
        self.set_sea_switch(True)
        self.journey = self.make_journey(
            self.traveler,
            [
                (DRIVE, self.lyon, self.marseille),
                (SEA, self.marseille, self.algiers),
                (DRIVE, self.algiers, self.setif),
            ],
        )
        self.sea_leg = self.journey.legs.get(mode=SEA)
        self.road_parcel = self.request_over(self.sender, self.journey, 0, 0)
        self.sailing_parcel = self.request_over(self.sender, self.journey, 0, 2)

    def listed(self, *, sea_legs_enabled: bool = True) -> bool:
        return listable_journeys(at=timezone.now(), sea_legs_enabled=sea_legs_enabled).filter(
            pk=self.journey.pk
        ).exists()

    def listed_through_the_api(self) -> bool:
        response = client_for(self.sender).get(reverse("discovery-trips"))
        assert response.status_code == 200, response.data
        return self.journey.pk in [card["journey_id"] for card in response.data["results"]]

    def assert_closed(self, *, sea_legs_enabled: bool) -> None:
        for delivery_request in (self.road_parcel, self.sailing_parcel):
            with self.subTest(parcel=delivery_request.pk):
                assert self.candidate(delivery_request, self.journey) is None
                result = self.evaluate(delivery_request, self.journey)
                assert "sea_legs_available" in result.rejection_codes
                with self.assertRaises(IncompatibleCandidate) as caught:
                    self.propose(delivery_request, self.journey, first=0, last=0)
                assert "sea_legs_available" in caught.exception.rejection_codes
        assert not self.listed(sea_legs_enabled=sea_legs_enabled)
        assert not self.listed_through_the_api()
        assert self.detail_status(self.sender) == 404
        assert self.detail_status(self.traveler) == 200

    def detail_status(self, user) -> int:
        return client_for(user).get(reverse("journeys-detail", args=(self.journey.pk,))).status_code

    def test_an_open_ferry_journey_is_matched_and_listed(self):
        for delivery_request in (self.road_parcel, self.sailing_parcel):
            assert self.candidate(delivery_request, self.journey).compatibility.compatible
        assert self.listed()
        assert self.listed_through_the_api()
        assert self.detail_status(self.sender) == 200
        card = next(
            card
            for card in client_for(self.sender).get(reverse("discovery-trips")).data["results"]
            if card["journey_id"] == self.journey.pk
        )
        assert [leg["mode"] for leg in card["legs"]] == [DRIVE, SEA, DRIVE]

    def test_turning_the_switch_off_closes_even_the_road_part(self):
        self.set_sea_switch(False)

        self.assert_closed(sea_legs_enabled=False)

    def test_deactivating_the_crossing_closes_the_journey(self):
        from apps.locations.models import SeaCrossing

        SeaCrossing.objects.filter(pk=self.marseille_algiers.pk).update(is_active=False)

        self.assert_closed(sea_legs_enabled=True)

    def test_a_retired_port_closes_the_journey(self):
        self.algiers.active = False
        self.algiers.save(update_fields=["active"])

        assert not self.listed()

    def test_a_ferry_ticket_that_is_not_approved_closes_the_journey(self):
        JourneyLegProof.objects.filter(leg=self.sea_leg).update(
            status=JourneyLegProof.Status.REJECTED, rejection_reason="Wrong date"
        )

        result = self.evaluate(self.road_parcel, self.journey)
        assert "sea_proofs_approved" in result.rejection_codes
        assert "flight_proofs_approved" not in result.rejection_codes
        assert self.candidate(self.road_parcel, self.journey) is None
        assert not self.listed()

    def test_a_ferry_journey_costs_the_scan_no_query_of_its_own(self):
        def measure() -> int:
            with CaptureQueriesContext(connection) as captured:
                assert self.scan(self.road_parcel)
            return len(captured)

        one = measure()
        for _ in range(2):
            self.make_journey(
                self.traveler,
                [
                    (DRIVE, self.lyon, self.marseille),
                    (SEA, self.marseille, self.algiers),
                    (DRIVE, self.algiers, self.setif),
                ],
            )
        assert len(self.scan(self.road_parcel)) == 3
        assert measure() == one

    def test_find_travelers_costs_no_query_per_ferry_candidate(self):
        def measure() -> tuple[int, int]:
            with CaptureQueriesContext(connection) as captured:
                response = client_for(self.sender).get(
                    reverse("matches-find-travelers-v1"), {"parcel_id": self.sailing_parcel.pk}
                )
            assert response.status_code == 200
            return len(captured), len(response.data["results"])

        one, found = measure()
        assert found == 1
        for index in range(2):
            self.make_journey(
                self.person(f"l3a-other-traveler-{index}@example.com"),
                [
                    (DRIVE, self.lyon, self.marseille),
                    (SEA, self.marseille, self.algiers),
                    (DRIVE, self.algiers, self.setif),
                ],
            )
        three, found = measure()
        assert found == 3
        assert three == one

    def test_compatible_requests_costs_no_query_per_request_on_a_ferry_journey(self):
        def measure() -> tuple[int, int]:
            with CaptureQueriesContext(connection) as captured:
                response = client_for(self.traveler).get(
                    reverse("matches-compatible-requests-v1"), {"journey_id": self.journey.pk}
                )
            assert response.status_code == 200, response.data
            return len(captured), len(response.data["results"])

        one, found = measure()
        assert found == 2  # the road parcel and the sailing parcel
        for first, last in ((1, 1), (1, 2)):
            self.request_over(self.person(f"l3a-sender-{first}{last}@example.com"), self.journey, first, last)
        four, found = measure()
        assert found == 4
        assert four == one


# ---------------------------------------------------------------------------
# Stops and the traveler's item rules
# ---------------------------------------------------------------------------


class StopAndItemRuleTests(MatchingWorld, TestCase):
    def setUp(self):
        self.build_matching_world()
        self.journey = self.make_journey(
            self.traveler,
            [(DRIVE, self.algiers, self.setif), (DRIVE, self.setif, self.constantine)],
        )

    def assert_refused(self, delivery_request, code: str) -> dict:
        assert self.candidate(delivery_request, self.journey) is None
        result = self.evaluate(delivery_request, self.journey)
        assert code in result.rejection_codes, result.rejection_codes
        return next(row for row in result.checks if row["code"] == code)

    def assert_matches(self, delivery_request) -> None:
        assert self.candidate(delivery_request, self.journey).compatibility.compatible
        assert self.evaluate(delivery_request, self.journey).compatible

    def test_a_stop_that_takes_no_pickup_boards_no_parcel(self):
        self.stop(self.journey, 1, accepts_pickup=False)

        check = self.assert_refused(
            self.request_over(self.sender, self.journey, 1, 1), "stop_services_allow_handover"
        )
        assert check["details"] == {"pickup_stop": 1, "dropoff_stop": 2}
        # Passing through, or getting off there, is still fine.
        self.assert_matches(self.request_over(self.sender, self.journey, 0, 1))
        self.assert_matches(self.request_over(self.sender, self.journey, 0, 0))

    def test_a_stop_that_takes_no_dropoff_leaves_no_parcel(self):
        self.stop(self.journey, 1, accepts_dropoff=False)

        self.assert_refused(
            self.request_over(self.sender, self.journey, 0, 0), "stop_services_allow_handover"
        )
        self.assert_matches(self.request_over(self.sender, self.journey, 1, 1))

    def test_a_refused_category_is_refused(self):
        Journey.objects.filter(pk=self.journey.pk).update(refused_categories=["electronics"])

        check = self.assert_refused(
            self.request_over(
                self.sender, self.journey, 0, 1, category=ParcelRequest.ItemType.ELECTRONICS
            ),
            "item_accepted_by_traveler",
        )
        assert check["details"] == {"category_accepted": False, "fragile_accepted": True}
        self.assert_matches(self.request_over(self.sender, self.journey, 0, 1))

    def test_a_fragile_parcel_needs_a_traveler_who_takes_one(self):
        fragile = self.request_over(self.sender, self.journey, 0, 1, fragile=True)
        self.assert_matches(fragile)

        Journey.objects.filter(pk=self.journey.pk).update(accepts_fragile=False)

        check = self.assert_refused(fragile, "item_accepted_by_traveler")
        assert check["details"] == {"category_accepted": True, "fragile_accepted": False}
        self.assert_matches(self.request_over(self.sender, self.journey, 0, 1))


# ---------------------------------------------------------------------------
# Volume and parcel slots
# ---------------------------------------------------------------------------


class SecondaryCapacityTests(MatchingWorld, TestCase):
    def setUp(self):
        self.build_matching_world()
        self.journey = self.make_journey(
            self.traveler,
            [(DRIVE, self.algiers, self.setif)],
            capacity_volume_l=5,
            capacity_parcels=2,
        )

    def test_a_leg_without_limits_reports_capacity_exactly_as_before(self):
        plain = self.make_journey(self.traveler, [(DRIVE, self.algiers, self.setif)])

        result = self.evaluate(self.request_over(self.sender, plain, 0, 0), plain)

        assert set(result.capacity_remaining_by_leg[0]) == {
            "journey_leg_id",
            "capacity_kg",
            "reserved_kg",
            "remaining_kg",
        }
        # Unchanged byte for byte: a direct evaluation with nothing reserved
        # has always said "0".
        assert result.capacity_remaining_by_leg[0]["reserved_kg"] == "0"

    def test_a_parcel_without_dimensions_is_matched_with_a_caveat(self):
        result = self.evaluate(
            self.request_over(self.sender, self.journey, 0, 0, dimensions=None), self.journey
        )

        assert result.compatible, result.rejection_codes
        assert "volume_unverified" in result.limitations
        row = result.capacity_remaining_by_leg[0]
        assert (row["capacity_volume_l"], row["capacity_parcels"], row["reserved_parcels"]) == (5, 2, 0)

    def test_a_parcel_too_big_for_the_space_left_is_refused(self):
        too_big = self.request_over(
            self.sender, self.journey, 0, 0, dimensions=("30.00", "20.00", "10.00")
        )

        result = self.evaluate(too_big, self.journey)
        assert "volume_available_on_every_leg" in result.rejection_codes
        with self.assertRaises(CapacityExceeded):
            self.propose(too_big, self.journey, first=0, last=0)

    def test_acceptance_reserves_volume_and_a_slot(self):
        first = self.request_over(self.sender, self.journey, 0, 0)
        deal = self.accept(self.propose(first, self.journey, first=0, last=0)).deal

        allocation = DealLegAllocation.objects.get(deal=deal)
        assert allocation.allocated_volume_l == Decimal("3.000")
        second = self.request_over(self.sender, self.journey, 0, 0)
        row = self.evaluate(second, self.journey).capacity_remaining_by_leg[0]
        assert (row["reserved_volume_l"], row["reserved_parcels"]) == ("3.000", 1)
        # Two litres are left: a three-litre parcel no longer fits.
        assert "volume_available_on_every_leg" in self.evaluate(second, self.journey).rejection_codes

        small = self.request_over(
            self.sender, self.journey, 0, 0, dimensions=("10.00", "10.00", "10.00")
        )
        self.accept(self.propose(small, self.journey, first=0, last=0))
        last = self.request_over(
            self.sender, self.journey, 0, 0, dimensions=("5.00", "5.00", "5.00")
        )
        assert "parcel_slots_available_on_every_leg" in self.evaluate(last, self.journey).rejection_codes
        assert not listable_journeys(at=timezone.now(), sea_legs_enabled=False).filter(
            pk=self.journey.pk
        ).exists()


# ---------------------------------------------------------------------------
# Pause
# ---------------------------------------------------------------------------


class PausedJourneyTests(MatchingWorld, APITestCase):
    def setUp(self):
        self.build_matching_world()
        self.journey = self.make_journey(self.traveler, [(DRIVE, self.algiers, self.setif)])
        self.parcel = self.request_over(self.sender, self.journey, 0, 0)

    def matches_tier(self, user, role: str) -> dict:
        response = client_for(user).get(reverse("discovery-matches"), {"role": role})
        assert response.status_code == 200, response.data
        return response.data

    def test_a_paused_journey_leaves_every_discovery_surface(self):
        pending = self.propose(self.parcel, self.journey, first=0, last=0)
        other = self.request_over(self.sender, self.journey, 0, 0)
        traveler_groups = self.matches_tier(self.traveler, "traveler")["groups"]
        assert [group["journey"]["id"] for group in traveler_groups] == [self.journey.pk]
        sender_before = json.dumps(self.matches_tier(self.sender, "sender"), default=str)
        assert f'"journey_id": {self.journey.pk}' in sender_before

        pause_own_journey(journey=self.journey, actor=self.traveler)

        # Matches, on both sides of the marketplace.
        assert self.matches_tier(self.traveler, "traveler")["groups"] == []
        sender_after = json.dumps(self.matches_tier(self.sender, "sender"), default=str)
        assert f'"journey_id": {self.journey.pk}' not in sender_after

        assert self.candidate(self.parcel, self.journey) is None
        assert "journey_not_paused" in self.evaluate(self.parcel, self.journey).rejection_codes
        assert not listable_journeys(at=timezone.now(), sea_legs_enabled=False).filter(
            pk=self.journey.pk
        ).exists()
        found = client_for(self.sender).get(
            reverse("matches-find-travelers-v1"), {"parcel_id": self.parcel.pk}
        )
        assert found.data["results"] == []

        with self.assertRaises(JourneyPaused) as caught:
            self.propose(other, self.journey, first=0, last=0)
        assert caught.exception.code == "journey_paused"
        # An offer made before the pause stays pending and cannot be accepted.
        with self.assertRaises(JourneyPaused):
            self.accept(pending)
        pending.refresh_from_db()
        assert pending.status == Offer.Status.PENDING
        assert not Deal.objects.exists()

        resume_own_journey(journey=self.journey, actor=self.traveler)

        assert self.accept(pending).deal.status
        assert self.candidate(other, self.journey) is not None


# ---------------------------------------------------------------------------
# The handover note
# ---------------------------------------------------------------------------


class HandoverNotePrivacyTests(MatchingWorld, APITestCase):
    NOTE = "Ask for Karim at the café by the station"

    def setUp(self):
        enable_mock_rail()
        self.build_matching_world()
        self.journey = self.make_journey(
            self.traveler,
            [(DRIVE, self.algiers, self.setif), (DRIVE, self.setif, self.constantine)],
        )
        legs = list(self.journey.legs.order_by("position"))
        self.window = (legs[0].arrive_at, legs[1].depart_at)
        self.stop(
            self.journey,
            1,
            handover_note=self.NOTE,
            window_start=self.window[0],
            window_end=self.window[1],
        )
        self.parcel = self.request_over(self.sender, self.journey, 1, 1)

    def test_the_note_reaches_the_sender_only_with_the_funded_route(self):
        sender = client_for(self.sender)
        surfaces = [
            sender.get(reverse("matches-find-travelers-v1"), {"parcel_id": self.parcel.pk}),
            sender.get(reverse("journeys-detail", args=(self.journey.pk,))),
        ]
        offer = self.propose(self.parcel, self.journey, first=1, last=1)
        deal = self.accept(offer).deal
        surfaces.append(sender.get(reverse("deals-detail", args=(deal.pk,))))
        surfaces.append(sender.get(reverse("matches-detail", args=(offer.match_id,))))
        for response in surfaces:
            assert response.status_code == 200, response.data
            assert "Karim" not in json.dumps(response.data, default=str)

        from apps.finance.models import PaymentOrder

        order = PaymentOrder.objects.get(deal=deal, purpose=PaymentOrder.Purpose.DEAL_BALANCE)
        pay_order_with_mock(Client(), order)
        deal.refresh_from_db()
        assert deal.status == Deal.Status.FUNDED

        route = sender.get(reverse("deals-detail", args=(deal.pk,))).json()["route"]
        pickup, dropoff = route["handover_stops"]
        assert (pickup["role"], pickup["position"], pickup["handover_note"]) == ("pickup", 1, self.NOTE)
        assert pickup["window_start"] and pickup["window_end"]
        assert (dropoff["role"], dropoff["position"], dropoff["handover_note"]) == ("dropoff", 2, "")
        assert dropoff["window_start"] is None
        frozen = deal.arrival_snapshot["handover_stops"]
        assert frozen[0]["window_start"] == self.window[0].isoformat()


# ---------------------------------------------------------------------------
# The last slot and the last litres, under concurrent acceptance
# ---------------------------------------------------------------------------


@skipUnlessDBFeature("has_select_for_update")
class SecondaryCapacityConcurrencyTests(MatchingWorld, TransactionTestCase):
    def build(self, **limits) -> list[int]:
        self.build_matching_world()
        journey = self.make_journey(self.traveler, [(DRIVE, self.algiers, self.setif)], **limits)
        return [
            self.propose(
                self.request_over(self.sender, journey, 0, 0), journey, first=0, last=0
            ).pk
            for _ in range(2)
        ]

    def race(self, offer_ids: list[int]) -> list[str]:
        barrier = Barrier(2)

        def accept(offer_id: int) -> str:
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                accept_offer(
                    pending_offer=Offer.objects.get(pk=offer_id),
                    actor=User.objects.get(pk=self.traveler.pk),
                )
                return "accepted"
            except CapacityExceeded:
                return "capacity_exceeded"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            return sorted(executor.map(accept, offer_ids))

    def test_two_acceptances_cannot_share_the_last_parcel_slot(self):
        offer_ids = self.build(capacity_parcels=1)

        assert self.race(offer_ids) == ["accepted", "capacity_exceeded"]
        assert DealLegAllocation.objects.count() == 1

    def test_two_acceptances_cannot_share_the_last_litres(self):
        # Two three-litre parcels, four litres of space.
        offer_ids = self.build(capacity_volume_l=4)

        assert self.race(offer_ids) == ["accepted", "capacity_exceeded"]
        assert DealLegAllocation.objects.count() == 1
        assert DealLegAllocation.objects.get().allocated_volume_l == Decimal("3.000")
