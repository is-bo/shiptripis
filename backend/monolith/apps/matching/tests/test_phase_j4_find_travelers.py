"""Phase J4 — the frozen Find Travelers contract.

What these tests are guarding is a **projection**, so almost every assertion is
of the form "the browse payload says exactly what the matching verdict said".
The three that are not are the three J4 actually decides: how route fit is
classified, what a Traveler's card may say about them, and what a page is.

The geography is the canonical CDG → ALG → Jijel world from Phase 8D-R, because
that is the shape every deployed V1 journey has: legs described by
`origin_place`/`destination_place` with the legacy `Location` columns null.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import BusinessSettingsVersion
from apps.deals.models import Deal
from apps.locations.models import Location
from apps.matching.discovery import compatible_journeys_for_request
from apps.matching.find_travelers import (
    ROUTE_FIT_COMPATIBLE,
    ROUTE_FIT_EXCELLENT,
    ROUTE_FIT_GOOD,
    SORT_SOONEST_DEPARTURE,
    STATE_NO_CANDIDATES,
    STATE_REQUEST_INELIGIBLE,
    STATE_RESULTS,
    TIMING_FIT_COMFORTABLE,
    TIMING_FIT_FITS,
    classify_route_fit,
    classify_timing_fit,
    find_travelers,
    first_name,
    project_route,
)
from apps.matching.policy import Phase2Policy
from apps.matching.tests.test_phase8dr_offer_locks import CanonicalOfferFixture
from apps.matching.v1_services import accept_offer
from apps.parcels.models import ParcelRequest
from apps.ratings.models import Rating
from apps.trips.models import Journey, JourneyLeg, JourneyLegProof


FIND = "matches-find-travelers-v1"


def client_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


class FindTravelersFixture(CanonicalOfferFixture):
    """The canonical world, plus whatever J4 needs to look at it."""

    def setUp(self):
        self.build_world()
        self.policy = Phase2Policy.from_settings(
            BusinessSettingsVersion.objects.get(
                status=BusinessSettingsVersion.Status.ACTIVE
            )
        )
        self.traveler.full_name = "Yacine Bensalah"
        self.traveler.save(update_fields=["full_name"])

    def candidates(self, delivery_request=None):
        return compatible_journeys_for_request(
            delivery_request=delivery_request or self.request,
            policy=self.policy,
        )

    def page(self, delivery_request=None, **kwargs):
        page, block = find_travelers(
            delivery_request=delivery_request or self.request,
            candidates=self.candidates(delivery_request),
            **kwargs,
        )
        return page.as_dict(request_block=block)

    def get(self, **query):
        query.setdefault("parcel_id", self.request.pk)
        return client_for(self.sender).get(reverse(FIND), query)

    # -- extra geography ---------------------------------------------------

    def three_leg_journey(self, traveler):
        """Jijel → Algiers (drive) → Paris (flight) → Lyon (drive).

        An Algeria domestic DRIVE, the mandatory FLIGHT for the international
        crossing, and a continental-Europe DRIVE. A request for Algiers → Paris
        rides only the middle leg of it.
        """

        lyon = self._locality("FR", "Lyon", "45.7640", "4.8357")
        journey = Journey.objects.create(
            traveler=traveler,
            schema_version=2,
            start_place=self.jijel,
            destination_place=lyon,
            status=Journey.Status.ACTIVE,
            published_at=self.now,
        )
        first = JourneyLeg.objects.create(
            journey=journey,
            position=0,
            mode=JourneyLeg.Mode.DRIVE,
            origin_place=self.jijel,
            destination_place=self.algiers,
            depart_at=self.depart - timedelta(hours=8),
            arrive_at=self.depart - timedelta(hours=3),
            capacity_kg=Decimal("8.00"),
            distance_meters=320_000,
            route_provider="catalogue_snapshot",
        )
        flight = JourneyLeg.objects.create(
            journey=journey,
            position=1,
            mode=JourneyLeg.Mode.FLIGHT,
            origin_place=self.alg,
            destination_place=self.cdg,
            depart_at=self.depart,
            arrive_at=self.depart + timedelta(hours=3),
            capacity_kg=Decimal("8.00"),
            flight_number="AH1008",
        )
        last = JourneyLeg.objects.create(
            journey=journey,
            position=2,
            mode=JourneyLeg.Mode.DRIVE,
            origin_place=self.cdg,
            destination_place=lyon,
            depart_at=self.depart + timedelta(hours=5),
            arrive_at=self.depart + timedelta(hours=10),
            capacity_kg=Decimal("8.00"),
            distance_meters=465_000,
            route_provider="catalogue_snapshot",
        )
        JourneyLegProof.objects.create(
            leg=flight,
            bucket="private",
            object_key=f"j4/{journey.pk}-ticket.jpg",
            status=JourneyLegProof.Status.APPROVED,
            reviewer=self.sender,
            reviewed_at=self.now,
        )
        return journey, (first, flight, last)


# ---------------------------------------------------------------------------
# Compatibility authority
# ---------------------------------------------------------------------------


class CompatibilityAuthorityTests(FindTravelersFixture, TestCase):
    def test_a_compatible_traveler_is_returned(self):
        payload = self.page()
        self.assertEqual(payload["state"], STATE_RESULTS)
        self.assertEqual(len(payload["results"]), 1)
        self.assertEqual(payload["results"][0]["journey_id"], self.journey.pk)

    def test_an_incompatible_traveler_is_never_returned(self):
        # The same Traveler's other journey goes nowhere near Jijel.
        oran = self._locality("DZ", "Oran", "35.6976", "-0.6337")
        elsewhere = Journey.objects.create(
            traveler=self.other,
            schema_version=2,
            start_place=self.algiers,
            destination_place=oran,
            status=Journey.Status.ACTIVE,
            published_at=self.now,
        )
        JourneyLeg.objects.create(
            journey=elsewhere,
            position=0,
            mode=JourneyLeg.Mode.DRIVE,
            origin_place=self.algiers,
            destination_place=oran,
            depart_at=self.depart,
            arrive_at=self.depart + timedelta(hours=4),
            capacity_kg=Decimal("8.00"),
            distance_meters=430_000,
            route_provider="catalogue_snapshot",
        )

        returned = {row["journey_id"] for row in self.page()["results"]}
        self.assertNotIn(elsewhere.pk, returned)
        self.assertEqual(returned, {self.journey.pk})

    def test_boost_never_makes_an_incompatible_request_compatible(self):
        """Money buys position among compatible candidates and nothing else.

        The request here has no compatible Traveler at all: nobody travels
        Oran → Jijel. A Boost of a thousand euros must leave the list empty,
        not merely shorter.
        """

        oran = self._locality("DZ", "Oran", "35.6976", "-0.6337")
        unmatched = self._request(oran, self.jijel, title="Boosted but unroutable")
        unmatched.boost_eur_cents = 100_000
        unmatched.ranking_boost_weight = 20
        unmatched.ranking_boost_expires_at = unmatched.deadline_at
        unmatched.save(
            update_fields=[
                "boost_eur_cents",
                "ranking_boost_weight",
                "ranking_boost_expires_at",
            ]
        )

        payload = self.page(unmatched)
        self.assertEqual(payload["state"], STATE_NO_CANDIDATES)
        self.assertEqual(payload["results"], [])
        self.assertEqual(payload["page"]["total"], 0)

    def test_boost_on_the_senders_own_request_does_not_reorder_travelers(self):
        """A Boost is one number on one request, shared by every candidate.

        `rank_compatible_candidate` adds the same bonus to every row of a
        `compatible-journeys` scan, so on the Find Travelers screen a Boost
        cannot move a Traveler up or down. It is a traveller-facing signal, and
        J4 must not imply otherwise.
        """

        for index in range(3):
            traveler = self._kyc_traveler(f"j4-order-{index}")
            self._journey(traveler, origin=self.cdg)

        before = [row["journey_id"] for row in self.page()["results"]]

        self.request.boost_eur_cents = 5_000
        self.request.ranking_boost_weight = 10
        self.request.ranking_boost_expires_at = self.request.deadline_at
        self.request.save(
            update_fields=[
                "boost_eur_cents",
                "ranking_boost_weight",
                "ranking_boost_expires_at",
            ]
        )

        after = [row["journey_id"] for row in self.page()["results"]]
        self.assertEqual(before, after)

    def _kyc_traveler(self, suffix: str):
        from apps.matching.tests.test_v1_matching import _approve_kyc, _user

        traveler = _user(f"{suffix}@example.com")
        traveler.full_name = f"Amina {suffix}"
        traveler.save(update_fields=["full_name"])
        _approve_kyc(traveler, f"{suffix}x")
        return traveler


# ---------------------------------------------------------------------------
# Route projection
# ---------------------------------------------------------------------------


class RouteProjectionTests(FindTravelersFixture, TestCase):
    def test_a_multi_leg_route_is_ordered_named_and_moded(self):
        route = self.page()["results"][0]["route"]

        self.assertEqual(
            [stop["label"] for stop in route["stops"]],
            ["Paris", "Algiers", "Jijel"],
        )
        self.assertEqual(
            [segment["mode"] for segment in route["segments"]],
            [JourneyLeg.Mode.FLIGHT, JourneyLeg.Mode.DRIVE],
        )
        self.assertEqual(
            [segment["journey_leg_id"] for segment in route["segments"]],
            [self.flight_leg.pk, self.drive_leg.pk],
        )
        # N segments make N+1 stops, which is exactly what a route line draws.
        self.assertEqual(len(route["stops"]), len(route["segments"]) + 1)

    def test_a_stop_carries_catalogue_identity_and_no_geometry(self):
        for stop in self.page()["results"][0]["route"]["stops"]:
            self.assertEqual(
                set(stop),
                {
                    "place_id",
                    "label",
                    "country_code",
                    "airport_iata",
                    "arrive_at",
                    "depart_at",
                },
            )
            self.assertTrue(stop["label"])
            self.assertIsNotNone(stop["place_id"])

    def test_the_schedule_on_a_stop_is_the_published_leg_schedule(self):
        stops = self.page()["results"][0]["route"]["stops"]
        self.assertEqual(stops[0]["depart_at"], self.flight_leg.depart_at.isoformat())
        self.assertIsNone(stops[0]["arrive_at"])
        self.assertEqual(stops[1]["arrive_at"], self.flight_leg.arrive_at.isoformat())
        self.assertEqual(stops[1]["depart_at"], self.drive_leg.depart_at.isoformat())
        self.assertEqual(stops[2]["arrive_at"], self.drive_leg.arrive_at.isoformat())
        self.assertIsNone(stops[2]["depart_at"])

    def test_a_direct_single_leg_route_reports_no_transfers(self):
        traveler = self._direct_traveler()
        direct = Journey.objects.create(
            traveler=traveler,
            schema_version=2,
            start_place=self.algiers,
            destination_place=self.jijel,
            status=Journey.Status.ACTIVE,
            published_at=self.now,
        )
        JourneyLeg.objects.create(
            journey=direct,
            position=0,
            mode=JourneyLeg.Mode.DRIVE,
            origin_place=self.algiers,
            destination_place=self.jijel,
            depart_at=self.depart,
            arrive_at=self.depart + timedelta(hours=5),
            capacity_kg=Decimal("8.00"),
            distance_meters=320_000,
            route_provider="catalogue_snapshot",
        )
        domestic = self._request(self.algiers, self.jijel, title="Algiers to Jijel")

        row = next(
            candidate
            for candidate in self.page(domestic)["results"]
            if candidate["journey_id"] == direct.pk
        )
        self.assertEqual(row["transfers"], 0)
        self.assertEqual(row["primary_mode"], JourneyLeg.Mode.DRIVE)
        self.assertEqual(len(row["route"]["segments"]), 1)
        self.assertFalse(row["route"]["continues_before"])
        self.assertFalse(row["route"]["continues_after"])

    def test_the_carrying_route_says_the_trip_continues_without_saying_where(self):
        traveler = self._direct_traveler()
        journey, legs = self.three_leg_journey(traveler)
        crossing = self._request(self.algiers, self.paris, title="Algiers to Paris")
        crossing.ready_window_start = legs[1].depart_at - timedelta(hours=1)
        crossing.ready_window_end = legs[1].depart_at + timedelta(hours=1)
        crossing.deadline_at = legs[1].arrive_at + timedelta(hours=6)
        crossing.save(
            update_fields=["ready_window_start", "ready_window_end", "deadline_at"]
        )

        row = next(
            candidate
            for candidate in self.page(crossing)["results"]
            if candidate["journey_id"] == journey.pk
        )
        route = row["route"]
        self.assertEqual(
            [stop["label"] for stop in route["stops"]],
            ["Algiers", "Paris"],
        )
        self.assertTrue(route["continues_before"])
        self.assertTrue(route["continues_after"])
        # Jijel and Lyon are on the Traveler's trip and not on the parcel's.
        self.assertNotIn("Jijel", [stop["label"] for stop in route["stops"]])
        self.assertNotIn("Lyon", [stop["label"] for stop in route["stops"]])

    def test_primary_mode_is_flight_whenever_the_parcel_flies(self):
        self.assertEqual(
            self.page()["results"][0]["primary_mode"], JourneyLeg.Mode.FLIGHT
        )

    def _direct_traveler(self):
        from apps.matching.tests.test_v1_matching import _approve_kyc, _user

        traveler = _user("j4-direct@example.com")
        traveler.full_name = "Sofiane Kaci"
        traveler.save(update_fields=["full_name"])
        _approve_kyc(traveler, "j4direct")
        return traveler


# ---------------------------------------------------------------------------
# Fit
# ---------------------------------------------------------------------------


class RouteFitTests(FindTravelersFixture, TestCase):
    def test_classification_is_a_pure_function_of_the_covered_span(self):
        self.assertEqual(
            classify_route_fit(covered_leg_positions=[0, 1], journey_leg_count=2),
            ROUTE_FIT_EXCELLENT,
        )
        self.assertEqual(
            classify_route_fit(covered_leg_positions=[0], journey_leg_count=2),
            ROUTE_FIT_GOOD,
        )
        self.assertEqual(
            classify_route_fit(covered_leg_positions=[1], journey_leg_count=2),
            ROUTE_FIT_GOOD,
        )
        self.assertEqual(
            classify_route_fit(covered_leg_positions=[1], journey_leg_count=3),
            ROUTE_FIT_COMPATIBLE,
        )
        # Never raises on a shape it has no answer for.
        self.assertEqual(
            classify_route_fit(covered_leg_positions=[], journey_leg_count=0),
            ROUTE_FIT_COMPATIBLE,
        )

    def test_riding_the_whole_journey_is_excellent(self):
        row = self.page()["results"][0]
        self.assertEqual(row["route_fit"], ROUTE_FIT_EXCELLENT)
        self.assertIn(
            {"code": "whole_trip_matches", "params": {}}, row["match_reasons"]
        )

    def test_sharing_one_end_of_the_journey_is_good(self):
        partial = self._request(self.paris, self.algiers, title="Paris to Algiers")
        row = next(
            candidate
            for candidate in self.page(partial)["results"]
            if candidate["journey_id"] == self.journey.pk
        )
        self.assertEqual(row["route_fit"], ROUTE_FIT_GOOD)
        self.assertNotIn(
            {"code": "whole_trip_matches", "params": {}}, row["match_reasons"]
        )

    def test_passing_through_is_compatible(self):
        from apps.matching.tests.test_v1_matching import _approve_kyc, _user

        traveler = _user("j4-through@example.com")
        traveler.full_name = "Nadia Haddad"
        traveler.save(update_fields=["full_name"])
        _approve_kyc(traveler, "j4through")
        journey, legs = self.three_leg_journey(traveler)

        crossing = self._request(self.algiers, self.paris, title="Through traffic")
        crossing.ready_window_start = legs[1].depart_at - timedelta(hours=1)
        crossing.ready_window_end = legs[1].depart_at + timedelta(hours=1)
        crossing.deadline_at = legs[1].arrive_at + timedelta(hours=6)
        crossing.save(
            update_fields=["ready_window_start", "ready_window_end", "deadline_at"]
        )

        row = next(
            candidate
            for candidate in self.page(crossing)["results"]
            if candidate["journey_id"] == journey.pk
        )
        self.assertEqual(row["route_fit"], ROUTE_FIT_COMPATIBLE)

    def test_classification_is_deterministic(self):
        first = self.page()["results"][0]["route_fit"]
        second = self.page()["results"][0]["route_fit"]
        self.assertEqual(first, second)
        self.assertEqual(first, ROUTE_FIT_EXCELLENT)

    def test_no_radius_pin_detour_or_distance_vocabulary_survives(self):
        """Section 3 of the J4 brief, enforced on the payload rather than trusted.

        On a canonical candidate every detour is a hard zero, so the bands the
        old endpoint publishes are constants dressed as measurements. Nothing
        shaped like proximity may appear in this contract.
        """

        import json

        blob = json.dumps(self.page()).lower()
        for forbidden in (
            "detour",
            "radius",
            "distance",
            "_km",
            "km_",
            "proximity",
            "nearby",
            "latitude",
            "longitude",
            "coordinate",
            "polyline",
            "corridor",
        ):
            self.assertNotIn(forbidden, blob, forbidden)


class TimingFitTests(FindTravelersFixture, TestCase):
    def test_a_full_day_of_margin_is_comfortable(self):
        arrives = timezone.now()
        self.assertEqual(
            classify_timing_fit(
                arrives_at=arrives, deadline_at=arrives + timedelta(hours=25)
            ),
            TIMING_FIT_COMFORTABLE,
        )
        self.assertEqual(
            classify_timing_fit(
                arrives_at=arrives, deadline_at=arrives + timedelta(hours=2)
            ),
            TIMING_FIT_FITS,
        )
        self.assertIsNone(classify_timing_fit(arrives_at=None, deadline_at=arrives))
        self.assertIsNone(classify_timing_fit(arrives_at=arrives, deadline_at=None))

    def test_a_tight_deadline_still_fits_because_the_gate_already_said_so(self):
        # depart + 9h arrival against a depart + 16h deadline: seven hours.
        row = self.page()["results"][0]
        self.assertEqual(row["timing_fit"], TIMING_FIT_FITS)
        self.assertEqual(row["arrives_at"], self.drive_leg.arrive_at.isoformat())
        self.assertEqual(row["departs_at"], self.flight_leg.depart_at.isoformat())

    def test_a_generous_deadline_reads_comfortable(self):
        self.request.deadline_at = self.drive_leg.arrive_at + timedelta(days=3)
        self.request.save(update_fields=["deadline_at"])
        self.assertEqual(
            self.page()["results"][0]["timing_fit"], TIMING_FIT_COMFORTABLE
        )


# ---------------------------------------------------------------------------
# Traveler identity
# ---------------------------------------------------------------------------


class TravelerIdentityTests(FindTravelersFixture, TestCase):
    def test_only_a_first_name_crosses_the_wire(self):
        traveler = self.page()["results"][0]["traveler"]
        self.assertEqual(traveler["display_name"], "Yacine")
        self.assertNotIn("Bensalah", str(self.page()))

    def test_a_missing_name_never_becomes_an_email_local_part(self):
        self.assertEqual(first_name(""), "")
        self.assertEqual(first_name("   "), "")
        self.assertEqual(first_name("Yacine Bensalah"), "Yacine")
        self.assertEqual(first_name("Yacine"), "Yacine")

    def test_an_unrated_traveler_is_new_and_never_five_point_zero(self):
        rating = self.page()["results"][0]["traveler"]["rating"]
        self.assertEqual(rating, {"state": "new", "average": None, "count": 0})

    def test_a_revealed_rating_is_counted_and_averaged(self):
        self._rate(5, revealed=True)
        self._rate(4, revealed=True)
        rating = self.page()["results"][0]["traveler"]["rating"]
        self.assertEqual(rating["state"], "rated")
        self.assertEqual(rating["count"], 2)
        self.assertEqual(rating["average"], 4.5)

    def test_a_single_rating_reads_as_one_rating(self):
        self._rate(3, revealed=True)
        rating = self.page()["results"][0]["traveler"]["rating"]
        self.assertEqual(rating, {"state": "rated", "average": 3.0, "count": 1})

    def test_a_blind_rating_is_not_counted_until_it_reveals(self):
        """The blind window is the whole point of the rating product.

        A rating written inside an open window, with no counterpart rating on
        the Deal, is invisible to everybody. Discovery must not be the surface
        that leaks it in aggregate.
        """

        self._rate(1, revealed=False)
        self.assertEqual(
            self.page()["results"][0]["traveler"]["rating"],
            {"state": "new", "average": None, "count": 0},
        )

    def test_a_blind_rating_reveals_once_both_sides_have_spoken(self):
        deal = self._completed_deal()
        Rating.objects.create(
            deal=deal,
            rater=self.sender,
            ratee=self.traveler,
            rater_role=Rating.RaterRole.SENDER,
            score=5,
            review_window_ends_at=timezone.now() + timedelta(days=7),
        )
        self.assertEqual(
            self.page()["results"][0]["traveler"]["rating"]["state"], "new"
        )

        Rating.objects.create(
            deal=deal,
            rater=self.traveler,
            ratee=self.sender,
            rater_role=Rating.RaterRole.TRAVELER,
            score=4,
            review_window_ends_at=timezone.now() + timedelta(days=7),
        )
        self.assertEqual(
            self.page()["results"][0]["traveler"]["rating"],
            {"state": "rated", "average": 5.0, "count": 1},
        )

    def test_completed_deliveries_come_from_completed_deals_only(self):
        self.assertEqual(
            self.page()["results"][0]["traveler"]["completed_deliveries"], 0
        )
        deal = self._completed_deal()
        self.assertEqual(
            self.page()["results"][0]["traveler"]["completed_deliveries"], 1
        )
        # A Deal that has not completed is not a delivery.
        Deal.objects.filter(pk=deal.pk).update(status=Deal.Status.IN_TRANSIT)
        self.assertEqual(
            self.page()["results"][0]["traveler"]["completed_deliveries"], 0
        )

    def test_a_published_journey_is_not_a_completed_delivery(self):
        for _ in range(4):
            self._journey(self.traveler, origin=self.cdg)
        self.assertEqual(
            self.page()["results"][0]["traveler"]["completed_deliveries"], 0
        )

    def test_the_traveler_block_carries_nothing_private(self):
        traveler = self.page()["results"][0]["traveler"]
        self.assertEqual(
            set(traveler),
            {
                "id",
                "display_name",
                "avatar_url",
                "identity_verified",
                "rating",
                "completed_deliveries",
            },
        )
        self.assertTrue(traveler["identity_verified"])
        self.assertIsNone(traveler["avatar_url"])

    def _rate(self, score: int, *, revealed: bool) -> Rating:
        deal = self._completed_deal()
        window = timezone.now() + (
            timedelta(days=-1) if revealed else timedelta(days=7)
        )
        return Rating.objects.create(
            deal=deal,
            rater=self.sender,
            ratee=self.traveler,
            rater_role=Rating.RaterRole.SENDER,
            score=score,
            review_window_ends_at=window,
        )

    def _completed_deal(self) -> Deal:
        journey, flight, drive = self._journey(self.traveler, origin=self.cdg)
        parcel = self._request(self.paris, self.jijel, title="History")
        offer = self.propose(
            delivery_request=parcel,
            journey=journey,
            start_leg_id=flight.pk,
            end_leg_id=drive.pk,
        )
        deal = accept_offer(pending_offer=offer, actor=self.traveler).deal
        # The lifecycle that produces a COMPLETED Deal is Phase 4's and has its
        # own suite; what is under test here is the counting.
        Deal.objects.filter(pk=deal.pk).update(status=Deal.Status.COMPLETED)
        deal.refresh_from_db()
        return deal


# ---------------------------------------------------------------------------
# Lifecycle and staleness
# ---------------------------------------------------------------------------


class LifecycleTests(FindTravelersFixture, TestCase):
    def test_a_cancelled_journey_leaves_the_list(self):
        self.assertEqual(len(self.page()["results"]), 1)
        self.journey.status = Journey.Status.CANCELLED
        self.journey.save(update_fields=["status"])
        payload = self.page()
        self.assertEqual(payload["state"], STATE_NO_CANDIDATES)
        self.assertEqual(payload["results"], [])

    def test_an_expired_journey_leaves_the_list(self):
        JourneyLeg.objects.filter(journey=self.journey).update(
            depart_at=self.now - timedelta(days=5),
            arrive_at=self.now - timedelta(days=4),
        )
        self.assertEqual(self.page()["state"], STATE_NO_CANDIDATES)

    def test_a_request_that_is_not_open_is_its_own_state(self):
        """"Nobody matches" and "this request is closed" are different screens.

        Before J4 both arrived as an empty list, because a closed request
        simply failed `request_active` on every candidate in turn.
        """

        self.request.status = ParcelRequest.Status.CANCELLED
        self.request.save(update_fields=["status"])
        payload = self.page()
        self.assertEqual(payload["state"], STATE_REQUEST_INELIGIBLE)
        self.assertEqual(payload["reason"], "closed")
        self.assertEqual(payload["request_status"], ParcelRequest.Status.CANCELLED)
        self.assertEqual(payload["results"], [])

    def test_an_unpaid_posting_deposit_says_so(self):
        self.request.status = ParcelRequest.Status.AWAITING_DEPOSIT
        self.request.save(update_fields=["status"])
        payload = self.page()
        self.assertEqual(payload["state"], STATE_REQUEST_INELIGIBLE)
        self.assertEqual(payload["reason"], "awaiting_deposit")

    def test_an_already_matched_request_says_so(self):
        self.request.status = ParcelRequest.Status.MATCHED
        self.request.save(update_fields=["status"])
        self.assertEqual(self.page()["reason"], "already_matched")

    def test_an_ineligible_request_never_runs_a_candidate_scan(self):
        self.request.status = ParcelRequest.Status.CANCELLED
        self.request.save(update_fields=["status"])
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["state"], STATE_REQUEST_INELIGIBLE)
        self.assertNotIn("request", response.data)

    def test_a_stale_candidate_cannot_authorise_an_offer(self):
        """A browse row is a snapshot, never a reservation.

        The world moves between the read and the tap, and the propose path is
        what has to notice. It re-locks, re-evaluates and refuses; the card the
        Sender is looking at has no authority at all.
        """

        row = self.page()["results"][0]
        target = row["proposal"]
        self.journey.status = Journey.Status.CANCELLED
        self.journey.save(update_fields=["status"])

        response = client_for(self.sender).post(
            reverse("matches-propose-v1"),
            {
                "parcel_id": self.request.pk,
                "journey_id": target["journey_id"],
                "start_leg_id": target["start_leg_id"],
                "end_leg_id": target["end_leg_id"],
                "traveler_reward_eur_cents": row["economics"][
                    "recommended_reward_eur_cents"
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "journey_not_active")

    def test_a_stale_candidate_cannot_be_quoted_either(self):
        row = self.page()["results"][0]
        self.request.status = ParcelRequest.Status.CANCELLED
        self.request.save(update_fields=["status"])

        response = client_for(self.sender).post(
            reverse("matches-quote-v1"),
            {"parcel_id": self.request.pk, "journey_id": row["journey_id"]},
            format="json",
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "incompatible_candidate")


# ---------------------------------------------------------------------------
# Paging, sorting and the envelope
# ---------------------------------------------------------------------------


class PageTests(FindTravelersFixture, TestCase):
    def _extra(self, count: int) -> None:
        from apps.matching.tests.test_v1_matching import _approve_kyc, _user

        for index in range(count):
            traveler = _user(f"j4-page-{index}@example.com")
            traveler.full_name = f"Page {index}"
            traveler.save(update_fields=["full_name"])
            _approve_kyc(traveler, f"j4page{index}x")
            self._journey(traveler, origin=self.cdg)

    def test_the_first_page_is_bounded(self):
        self._extra(14)
        payload = self.page()
        self.assertEqual(payload["page"]["limit"], 10)
        self.assertEqual(len(payload["results"]), 10)
        self.assertEqual(payload["page"]["total"], 15)
        self.assertTrue(payload["page"]["has_more"])
        self.assertEqual(payload["page"]["next_offset"], 10)

    def test_paging_covers_the_set_exactly_once(self):
        self._extra(14)
        first = self.page(limit=6, offset=0)
        second = self.page(limit=6, offset=6)
        third = self.page(limit=6, offset=12)

        ids = [row["journey_id"] for page in (first, second, third) for row in page["results"]]
        self.assertEqual(len(ids), 15)
        self.assertEqual(len(set(ids)), 15)
        self.assertFalse(third["page"]["has_more"])
        self.assertIsNone(third["page"]["next_offset"])

    def test_the_order_is_stable_across_identical_reads(self):
        self._extra(9)
        self.assertEqual(
            [row["journey_id"] for row in self.page(limit=10)["results"]],
            [row["journey_id"] for row in self.page(limit=10)["results"]],
        )

    def test_an_offset_past_the_end_is_an_empty_page_not_an_error(self):
        payload = self.page(limit=10, offset=500)
        self.assertEqual(payload["results"], [])
        self.assertEqual(payload["page"]["total"], 1)
        self.assertFalse(payload["page"]["has_more"])

    def test_the_view_caps_the_page_at_the_policy_result_limit(self):
        response = self.get(limit=100)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["page"]["limit"], self.policy.result_limit)

    def test_soonest_departure_is_a_server_side_order(self):
        from apps.matching.tests.test_v1_matching import _approve_kyc, _user

        later = _user("j4-later@example.com")
        later.full_name = "Later Traveler"
        later.save(update_fields=["full_name"])
        _approve_kyc(later, "j4later")
        journey, flight, drive = self._journey(later, origin=self.cdg)
        JourneyLeg.objects.filter(pk=flight.pk).update(
            depart_at=self.depart + timedelta(minutes=30),
            arrive_at=self.depart + timedelta(hours=3, minutes=30),
        )

        ordered = [
            row["journey_id"]
            for row in self.page(sort=SORT_SOONEST_DEPARTURE)["results"]
        ]
        self.assertEqual(ordered, [self.journey.pk, journey.pk])
        self.assertEqual(
            self.page(sort=SORT_SOONEST_DEPARTURE)["sort"], SORT_SOONEST_DEPARTURE
        )

    def test_an_unknown_sort_is_refused_rather_than_guessed(self):
        self.assertEqual(self.get(sort="cheapest").status_code, 400)

    def test_the_request_block_is_sent_once_not_once_per_row(self):
        self._extra(3)
        payload = self.page()
        self.assertEqual(payload["request"]["id"], self.request.pk)
        self.assertEqual(
            payload["request"]["total_offered_reward_eur_cents"],
            self.request.traveler_reward_eur_cents,
        )
        for row in payload["results"]:
            self.assertNotIn("delivery_request", row)
            self.assertNotIn("request", row)

    def test_a_row_carries_the_propose_target_and_its_authorised_actions(self):
        row = self.page()["results"][0]
        self.assertEqual(
            row["proposal"],
            {
                "journey_id": self.journey.pk,
                "start_leg_id": self.flight_leg.pk,
                "end_leg_id": self.drive_leg.pk,
            },
        )
        self.assertEqual(
            {action["code"]: action["available"] for action in row["actions"]},
            {"view_journey": True, "propose_offer": True},
        )

    def test_a_row_carries_the_four_numbers_the_propose_sheet_renders(self):
        economics = self.page()["results"][0]["economics"]
        self.assertEqual(economics["currency"], "EUR")
        self.assertIsNotNone(economics["minimum_reward_eur_cents"])
        self.assertIsNotNone(economics["recommended_reward_eur_cents"])
        self.assertEqual(
            set(economics),
            {
                "currency",
                "minimum_reward_eur_cents",
                "minimum_economics",
                "recommended_reward_eur_cents",
                "recommended_economics",
            },
        )


# ---------------------------------------------------------------------------
# Match explanation
# ---------------------------------------------------------------------------


class MatchExplanationTests(FindTravelersFixture, TestCase):
    def test_every_claim_is_a_code_the_client_localises(self):
        reasons = self.page()["results"][0]["match_reasons"]
        codes = [reason["code"] for reason in reasons]
        self.assertEqual(
            codes,
            [
                "picks_up_in",
                "arrives_in",
                "transfers",
                "whole_trip_matches",
                "arrives_before_deadline",
                "has_room_for",
                "identity_verified",
                "flight_proof_approved",
            ],
        )
        for reason in reasons:
            self.assertEqual(set(reason), {"code", "params"})
            self.assertIsInstance(reason["params"], dict)

    def test_the_named_places_are_the_carrying_routes_own_endpoints(self):
        reasons = {
            reason["code"]: reason["params"]
            for reason in self.page()["results"][0]["match_reasons"]
        }
        self.assertEqual(reasons["picks_up_in"]["place"], "Paris")
        self.assertEqual(reasons["arrives_in"]["place"], "Jijel")
        self.assertEqual(reasons["transfers"]["count"], 1)
        self.assertEqual(reasons["has_room_for"]["weight_kg"], "2.00")

    def test_a_road_only_route_makes_no_flight_claim(self):
        from apps.matching.tests.test_v1_matching import _approve_kyc, _user

        traveler = _user("j4-road@example.com")
        traveler.full_name = "Road Traveler"
        traveler.save(update_fields=["full_name"])
        _approve_kyc(traveler, "j4road")
        direct = Journey.objects.create(
            traveler=traveler,
            schema_version=2,
            start_place=self.algiers,
            destination_place=self.jijel,
            status=Journey.Status.ACTIVE,
            published_at=self.now,
        )
        JourneyLeg.objects.create(
            journey=direct,
            position=0,
            mode=JourneyLeg.Mode.DRIVE,
            origin_place=self.algiers,
            destination_place=self.jijel,
            depart_at=self.depart,
            arrive_at=self.depart + timedelta(hours=5),
            capacity_kg=Decimal("8.00"),
            distance_meters=320_000,
            route_provider="catalogue_snapshot",
        )
        domestic = self._request(self.algiers, self.jijel, title="Road only")

        row = next(
            candidate
            for candidate in self.page(domestic)["results"]
            if candidate["journey_id"] == direct.pk
        )
        codes = [reason["code"] for reason in row["match_reasons"]]
        self.assertNotIn("flight_proof_approved", codes)
        self.assertIn("direct_leg", codes)
        self.assertNotIn("transfers", codes)


# ---------------------------------------------------------------------------
# Authorization and privacy
# ---------------------------------------------------------------------------


class AuthorizationTests(FindTravelersFixture, TestCase):
    def test_the_owner_may_read_their_own_discovery(self):
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["state"], STATE_RESULTS)

    def test_a_stranger_may_not_read_somebody_elses_discovery(self):
        response = client_for(self.other).get(
            reverse(FIND), {"parcel_id": self.request.pk}
        )
        self.assertEqual(response.status_code, 403)

    def test_the_traveler_on_the_list_may_not_read_the_list(self):
        response = client_for(self.traveler).get(
            reverse(FIND), {"parcel_id": self.request.pk}
        )
        self.assertEqual(response.status_code, 403)

    def test_an_anonymous_caller_is_refused(self):
        self.assertIn(
            APIClient().get(reverse(FIND), {"parcel_id": self.request.pk}).status_code,
            (401, 403),
        )

    def test_the_payload_carries_no_private_field_of_any_party(self):
        """The allowlist, asserted against real values rather than key names.

        A key name can be renamed; an email address in the blob is an email
        address in the blob.
        """

        import json

        blob = json.dumps(self.page())
        for forbidden in (
            self.traveler.email,
            self.sender.email,
            "Bensalah",
            "kyc",
            "payout",
            "delivery_code",
            "pickup_code",
            "private_label",
            "normalized_label",
            "ranking",
            "score",
            "checks",
            "capacity_remaining",
            "rejection_codes",
        ):
            self.assertNotIn(forbidden, blob, forbidden)

    def test_the_exact_pickup_and_delivery_points_stay_hidden(self):
        """Pre-funding disclosure is catalogue identity and nothing else.

        The request's own endpoints are the Sender's to know, so the envelope
        carries their windows and weight — but no candidate row publishes a
        coordinate, an address or a preferred meeting point for either party.
        """

        import json

        payload = self.page()
        for row in payload["results"]:
            blob = json.dumps(row)
            self.assertNotIn("latitude", blob)
            self.assertNotIn("longitude", blob)
            self.assertNotIn("private", blob)
            self.assertNotIn("address", blob)
        self.assertEqual(
            set(payload["request"]),
            {
                "id",
                "actual_weight_kg",
                "volumetric_weight_kg",
                "chargeable_weight_kg",
                "ready_window_start",
                "ready_window_end",
                "deadline_at",
                "chosen_reward_eur_cents",
                "boost_eur_cents",
                "total_offered_reward_eur_cents",
            },
        )

    def test_a_row_carries_exactly_the_frozen_keys(self):
        self.assertEqual(
            set(self.page()["results"][0]),
            {
                "journey_id",
                "traveler",
                "route",
                "route_fit",
                "timing_fit",
                "departs_at",
                "arrives_at",
                "transfers",
                "primary_mode",
                "match_reasons",
                "caveats",
                "economics",
                "proposal",
                "actions",
            },
        )


# ---------------------------------------------------------------------------
# Cost
# ---------------------------------------------------------------------------


class ReadCostTests(FindTravelersFixture, TestCase):
    """The query count is a property of the code, not of the candidate volume.

    J1.2 measured candidate discovery at five queries at 1, 10 and 40
    candidates. J4 adds the two grouped trust aggregates and nothing else, so
    the number moves once and then stays flat — which is the property that
    matters. A per-candidate read would show up here immediately.
    """

    def _grow_to(self, total: int) -> None:
        from apps.matching.tests.test_v1_matching import _approve_kyc, _user

        existing = Journey.objects.filter(status=Journey.Status.ACTIVE).count()
        for index in range(existing, total):
            traveler = _user(f"j4-cost-{index}@example.com")
            traveler.full_name = f"Cost {index}"
            traveler.save(update_fields=["full_name"])
            _approve_kyc(traveler, f"j4cost{index}x")
            self._journey(traveler, origin=self.cdg)

    def _measure(self) -> tuple[int, int]:
        # Warm any first-read caches so the measurement is of the page itself.
        self.page()
        with CaptureQueriesContext(connection) as captured:
            payload = self.page(limit=50)
        return len(captured.captured_queries), payload["page"]["total"]

    def test_the_cost_is_flat_at_one_ten_and_forty_candidates(self):
        one_queries, one_total = self._measure()
        self.assertEqual(one_total, 1)

        self._grow_to(10)
        ten_queries, ten_total = self._measure()
        self.assertEqual(ten_total, 10)

        self._grow_to(40)
        forty_queries, forty_total = self._measure()
        self.assertEqual(forty_total, 40)

        self.assertEqual(one_queries, ten_queries)
        self.assertEqual(ten_queries, forty_queries)
        self.assertLessEqual(forty_queries, 10, forty_queries)

        # J1.2 measured the scan itself at five queries. J4 is that plus the
        # two grouped trust aggregates, and the sum is pinned so a future field
        # cannot quietly add a third read.
        with CaptureQueriesContext(connection) as scan:
            self.candidates()
        self.assertEqual(forty_queries - len(scan.captured_queries), 2)

    def test_the_two_trust_aggregates_are_the_only_addition(self):
        from apps.matching.find_travelers import traveler_trust_signals

        self._grow_to(12)
        candidates = self.candidates()
        traveler_ids = [row.journey.traveler_id for row in candidates]
        self.assertGreater(len(traveler_ids), 1)

        with CaptureQueriesContext(connection) as captured:
            traveler_trust_signals(traveler_ids, at=timezone.now())
        self.assertEqual(len(captured.captured_queries), 2)

    def test_the_response_is_smaller_than_the_endpoint_it_supersedes(self):
        """Density over the wire, not just on screen.

        `compatible-journeys` repeats the Sender's own request and a full
        pricing diagnostic on every row. Ten candidates of that is ten copies
        of two blocks that never vary.
        """

        import json

        self._grow_to(10)
        new = len(json.dumps(self.page(limit=10), default=str))
        legacy = len(
            json.dumps(
                {
                    "count": 10,
                    "results": [
                        row.as_public_dict(include_recommendation=True)
                        for row in self.candidates()
                    ],
                },
                default=str,
            )
        )
        self.assertLess(new, legacy)


class LegacyJourneyRouteTests(FindTravelersFixture, TestCase):
    """A pre-8C journey must still name its stops.

    Every V1 journey is canonical, but a legacy journey that is still active
    carries `Location` rows and no `Place` at all. A route of unlabelled dots is
    the exact defect J1.2 spent a phase fixing, so the projection falls back to
    the coarse public label rather than rendering an empty stop.
    """

    def _location(self, label: str) -> Location:
        return Location.objects.create(
            kind=Location.Kind.MAP_POINT,
            normalized_label=f"Exact {label}",
            public_label=label,
            private_label=f"Private {label}",
            city=label,
            country_code="DZ",
            latitude=Decimal("36.000000"),
            longitude=Decimal("3.000000"),
            coarse_latitude=Decimal("36.0"),
            coarse_longitude=Decimal("3.0"),
        )

    def test_a_legacy_leg_falls_back_to_its_coarse_public_label(self):
        origin = self._location("Setif")
        destination = self._location("Bejaia")
        legacy = Journey.objects.create(
            traveler=self.traveler,
            schema_version=1,
            start_location=origin,
            destination_location=destination,
            status=Journey.Status.ACTIVE,
            published_at=self.now,
        )
        leg = JourneyLeg.objects.create(
            journey=legacy,
            position=0,
            mode=JourneyLeg.Mode.DRIVE,
            origin=origin,
            destination=destination,
            depart_at=self.depart,
            arrive_at=self.depart + timedelta(hours=3),
            capacity_kg=Decimal("8.00"),
            distance_meters=120_000,
            route_provider="catalogue_snapshot",
        )

        route = project_route(
            [leg],
            journey_leg_count=1,
            first_covered_position=0,
            last_covered_position=0,
        )
        self.assertEqual(
            [stop["label"] for stop in route["stops"]], ["Setif", "Bejaia"]
        )
        # No canonical identity to publish, and no airport facet either.
        for stop in route["stops"]:
            self.assertIsNone(stop["place_id"])
            self.assertIsNone(stop["airport_iata"])
            self.assertEqual(stop["country_code"], "DZ")

    def test_the_fallback_uses_the_coarse_label_and_never_the_private_one(self):
        origin = self._location("Setif")
        destination = self._location("Bejaia")
        legacy = Journey.objects.create(
            traveler=self.traveler,
            schema_version=1,
            start_location=origin,
            destination_location=destination,
            status=Journey.Status.ACTIVE,
            published_at=self.now,
        )
        leg = JourneyLeg.objects.create(
            journey=legacy,
            position=0,
            mode=JourneyLeg.Mode.DRIVE,
            origin=origin,
            destination=destination,
            depart_at=self.depart,
            arrive_at=self.depart + timedelta(hours=3),
            capacity_kg=Decimal("8.00"),
            distance_meters=120_000,
            route_provider="catalogue_snapshot",
        )

        import json

        blob = json.dumps(
            project_route(
                [leg],
                journey_leg_count=1,
                first_covered_position=0,
                last_covered_position=0,
            )
        )
        self.assertNotIn("Private", blob)
        self.assertNotIn("Exact", blob)


class PlaceTypeSanityTests(FindTravelersFixture, TestCase):
    def test_an_airport_rides_the_stop_as_a_facet_of_the_city(self):
        """The locked route UX: `Algiers · ALG`, never `Houari Boumediene`.

        An airport and the city it serves are one stop, so the label is the
        city and the airport is a code beside it. Jijel is reached by road and
        carries none.
        """

        stops = self.page()["results"][0]["route"]["stops"]
        self.assertEqual([stop["label"] for stop in stops], ["Paris", "Algiers", "Jijel"])
        self.assertEqual(stops[0]["airport_iata"], "CDG")
        self.assertEqual(stops[1]["airport_iata"], "ALG")
        self.assertIsNone(stops[2]["airport_iata"])
        self.assertEqual(stops[0]["place_id"], self.paris.pk)
        self.assertEqual(stops[1]["place_id"], self.algiers.pk)
