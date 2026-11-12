"""L2A Listings tier: `GET /api/discovery/trips` and `GET /api/discovery/requests`."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.kyc.models import KycSubmission
from apps.matching.v1_services import accept_offer
from apps.parcels.models import ParcelRequest
from apps.trips.models import Journey, JourneyLeg

from .support import DiscoveryWorld, activate_marketplace, client_for

TRIPS = "discovery-trips"
REQUESTS = "discovery-requests"


class TripsListingTests(DiscoveryWorld, TestCase):
    def setUp(self):
        self.build_discovery_world()

    def trips(self, viewer=None, **query):
        response = client_for(viewer or self.sender).get(reverse(TRIPS), query)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def ids(self, viewer=None, **query):
        return [row["journey_id"] for row in self.trips(viewer, **query)["results"]]

    def test_a_published_proven_journey_is_listed_with_its_card(self):
        payload = self.trips()

        self.assertEqual(payload["state"], "results")
        self.assertIsNone(payload["next_offset"])
        card = payload["results"][0]
        self.assertEqual(card["journey_id"], self.journey.pk)
        self.assertEqual(card["traveler"]["display_name"], "Yacine")
        self.assertTrue(card["traveler"]["identity_verified"])
        self.assertEqual(
            [stop["label"] for stop in card["stops"]], ["Paris", "Algiers", "Jijel"]
        )
        self.assertEqual([leg["mode"] for leg in card["legs"]], ["FLIGHT", "DRIVE"])
        self.assertEqual(card["capacity_band"], "5_to_10kg")
        self.assertEqual(card["departs_at"], self.flight_leg.depart_at.isoformat())

    def test_the_caller_never_sees_their_own_journey(self):
        self.assertEqual(self.ids(self.traveler), [])

    def test_an_unproven_flight_keeps_a_journey_off_the_list(self):
        other = self.new_traveler("l2a-unproven@example.com")
        self.unproven_flight_journey(other)

        self.assertEqual(self.ids(), [self.journey.pk])

    def test_expired_identity_check_unlists_the_journey(self):
        KycSubmission.objects.filter(user=self.traveler).update(
            status=KycSubmission.Status.EXPIRED
        )
        self.assertEqual(self.trips()["state"], "empty")

    def test_a_banned_or_deactivated_traveler_is_not_listed(self):
        self.traveler.is_banned = True
        self.traveler.save(update_fields=["is_banned"])
        self.assertEqual(self.ids(), [])
        self.traveler.is_banned = False
        self.traveler.is_active = False
        self.traveler.save(update_fields=["is_banned", "is_active"])
        self.assertEqual(self.ids(), [])

    def test_a_cancelled_or_draft_journey_is_not_listed(self):
        Journey.objects.filter(pk=self.journey.pk).update(status=Journey.Status.CANCELLED)
        self.assertEqual(self.ids(), [])
        Journey.objects.filter(pk=self.journey.pk).update(status=Journey.Status.DRAFT)
        self.assertEqual(self.ids(), [])

    def test_a_journey_with_a_full_leg_ahead_is_not_listed(self):
        accept_offer(pending_offer=self.propose(), actor=self.traveler)
        self.assertEqual(self.trips()["results"][0]["capacity_band"], "5_to_10kg")

        # The accepted deal reserves 2 kg on the drive leg; shrink it to that.
        JourneyLeg.objects.filter(pk=self.drive_leg.pk).update(capacity_kg=Decimal("2.00"))
        self.assertEqual(self.ids(), [])

    def test_the_capacity_band_is_the_smallest_free_weight_ahead(self):
        own = self.new_traveler("l2a-band@example.com")
        self.drive_journey(own, capacity="30.00")
        cards = {row["journey_id"]: row for row in self.trips()["results"]}
        bands = sorted(card["capacity_band"] for card in cards.values())
        self.assertEqual(bands, ["20kg_plus", "5_to_10kg"])

    def test_soonest_departure_first_and_server_paging(self):
        later = self.drive_journey(self.new_traveler("l2a-later@example.com"), days=6)
        sooner = self.drive_journey(self.new_traveler("l2a-sooner@example.com"), days=1)

        first = self.trips(limit=2)
        self.assertEqual(
            [row["journey_id"] for row in first["results"]], [sooner.pk, self.journey.pk]
        )
        self.assertEqual(first["next_offset"], 2)
        second = self.trips(limit=2, offset=2)
        self.assertEqual([row["journey_id"] for row in second["results"]], [later.pk])
        self.assertIsNone(second["next_offset"])

    def test_place_filters_match_the_city_behind_an_airport_and_respect_direction(self):
        # Paris → Jijel, given by the Paris airport, matches the CDG start.
        self.assertEqual(
            self.ids(origin_place_id=self.cdg.pk, destination_place_id=self.jijel.pk),
            [self.journey.pk],
        )
        # A stop in the middle is a pickup too.
        self.assertEqual(
            self.ids(origin_place_id=self.algiers.pk, destination_place_id=self.jijel.pk),
            [self.journey.pk],
        )
        # The journey never goes Jijel → Paris.
        self.assertEqual(
            self.ids(origin_place_id=self.jijel.pk, destination_place_id=self.paris.pk), []
        )
        # A distinct canonical Paris a few metres away is a different city.
        self.assertEqual(self.ids(origin_place_id=self.paris_twin.pk), [])

    def test_country_filters(self):
        self.assertEqual(
            self.ids(origin_country="FR", destination_country="DZ"), [self.journey.pk]
        )
        self.assertEqual(self.ids(origin_country="DZ", destination_country="FR"), [])

    def test_an_unknown_place_is_refused(self):
        response = client_for(self.sender).get(reverse(TRIPS), {"origin_place_id": 999_999})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "place_not_found")

    def test_departing_after_skips_trips_leaving_earlier(self):
        after = (self.depart + timedelta(days=1)).isoformat()
        self.assertEqual(self.ids(departing_after=after), [])
        later = self.drive_journey(self.new_traveler("l2a-after@example.com"), days=5)
        self.assertEqual(self.ids(departing_after=after), [later.pk])

    def test_switching_listings_off_answers_disabled(self):
        activate_marketplace({"discovery": {"listings_enabled": False}})
        self.assertEqual(
            self.trips(), {"state": "disabled", "results": [], "next_offset": None}
        )

    def test_anonymous_callers_are_refused(self):
        from rest_framework.test import APIClient

        self.assertIn(APIClient().get(reverse(TRIPS)).status_code, (401, 403))


class RequestsListingTests(DiscoveryWorld, TestCase):
    def setUp(self):
        self.build_discovery_world()

    def requests(self, viewer=None, **query):
        response = client_for(viewer or self.traveler).get(reverse(REQUESTS), query)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def ids(self, viewer=None, **query):
        return [row["request_id"] for row in self.requests(viewer, **query)["results"]]

    def test_an_open_request_is_listed_with_its_card(self):
        card = self.requests()["results"][0]

        self.assertEqual(card["request_id"], self.request.pk)
        self.assertEqual(card["sender"], {"display_name": "Samira"})
        self.assertEqual(card["pickup"]["label"], "Paris")
        self.assertEqual(card["delivery"]["label"], "Jijel")
        self.assertEqual(card["weight_kg"], "2.00")
        self.assertEqual(card["title"], "Canonical request")
        self.assertEqual(card["category"], ParcelRequest.ItemType.DOCUMENTS)
        self.assertFalse(card["fragile"])
        self.assertEqual(card["total_offered_reward_eur_cents"], 3_000)
        self.assertEqual(card["currency"], "EUR")

    def test_the_sender_never_sees_their_own_request(self):
        self.assertEqual(self.ids(self.sender), [])

    def test_unpublished_targeted_closed_and_expired_requests_are_not_listed(self):
        for change in (
            {"status": ParcelRequest.Status.AWAITING_DEPOSIT},
            {"status": ParcelRequest.Status.MATCHED},
            {"status": ParcelRequest.Status.CANCELLED},
            {"deadline_at": self.now - timedelta(hours=1)},
            {"target_traveler": self.other},
        ):
            with self.subTest(change):
                saved = {key: getattr(self.request, key) for key in change}
                type(self.request).objects.filter(pk=self.request.pk).update(**change)
                self.assertEqual(self.ids(), [])
                type(self.request).objects.filter(pk=self.request.pk).update(**saved)
        self.assertEqual(self.ids(), [self.request.pk])

    def test_a_banned_sender_is_not_listed(self):
        self.sender.is_banned = True
        self.sender.save(update_fields=["is_banned"])
        self.assertEqual(self.ids(), [])

    def test_place_and_country_filters(self):
        self.assertEqual(
            self.ids(origin_place_id=self.cdg.pk, destination_place_id=self.jijel.pk),
            [self.request.pk],
        )
        self.assertEqual(self.ids(origin_place_id=self.jijel.pk), [])
        self.assertEqual(self.ids(origin_country="FR"), [self.request.pk])
        self.assertEqual(self.ids(destination_country="FR"), [])

    def test_newest_first(self):
        newer = self._request(self.algiers, self.jijel, title="Newer")
        self.assertEqual(self.ids(), [newer.pk, self.request.pk])

    def test_switching_listings_off_answers_disabled(self):
        activate_marketplace({"discovery": {"listings_enabled": False}})
        self.assertEqual(self.requests()["state"], "disabled")
