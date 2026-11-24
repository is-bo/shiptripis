"""Phase K7-E — discovery reads cost the same at N and 2N candidates.

K7 package B measured two bounded N+1s against the real catalogue, where every
locality and airport has an administrative-region parent:

* Find Travelers lazily loaded ``place.parent`` for each leg's origin and
  destination (``Place.display_label``), up to ~210 extra queries at the scan
  cap;
* ``compatible-requests`` lazily loaded each candidate request's
  ``pickup_place``/``delivery_place`` and their parents, 165 queries in the
  seeded world and 515 at +10k open requests.

The fixture places in the older cost tests have no parent, so they could not
see either. This world gives every place a region parent, and every grown
candidate its own airport (so a per-airport read cannot hide behind a shared
prefetch cache). It then pins the property that matters: the query count does
not move when the number of candidates doubles. The payloads are asserted to
still carry the parent-derived labels and the served locality, so the fix
cannot "pass" by dropping them. Since fix plan P2 a card or list row (Find
Travelers stops, compatible-request rows) names the city
(`apps.locations.city_names`), which reads the parent for Algeria: the region
here stands in for the wilaya, so the Algerian stops read "Region DZ" and the
parent join is still exercised on every stop. The compatible-journeys payload
is not a list surface and keeps the catalogue label.
"""

from __future__ import annotations

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.core.models import BusinessSettingsVersion
from apps.locations.models import Place
from apps.matching.discovery import (
    compatible_journeys_for_request,
    compatible_requests_for_journey,
)
from apps.matching.find_travelers import find_travelers
from apps.matching.policy import Phase2Policy
from apps.matching.tests.test_phase8dr_offer_locks import CanonicalOfferFixture
from apps.matching.tests.test_v1_matching import _approve_kyc, _user


class RegionalCanonicalFixture(CanonicalOfferFixture):
    """The 8D-R canonical world, with every place under a region parent."""

    def build_world(self) -> None:
        self._regions: dict[str, Place] = {}
        self._grown = 0
        super().build_world()

    def _region(self, country_code: str) -> Place:
        if country_code not in self._regions:
            self._regions[country_code] = Place.objects.create(
                country=self.countries[country_code],
                place_type=Place.PlaceType.ADMIN_REGION,
                source="phase-k7e-test",
                source_id=f"region-{country_code}",
                source_version="phase-k7e",
                name=f"Region {country_code}",
                # The Algerian region stands in for a wilaya, the tier a card
                # reads for an Algerian place (P2).
                admin_level="wilaya" if country_code == "DZ" else "department",
            )
        return self._regions[country_code]

    def _locality(self, country_code, name, latitude, longitude, *, suffix="main"):
        place = super()._locality(
            country_code, name, latitude, longitude, suffix=suffix
        )
        place.parent = self._region(country_code)
        place.save(update_fields=["parent"])
        return place

    def _airport(self, country_code, name, iata, locality):
        airport = super()._airport(country_code, name, iata, locality)
        airport.parent = self._region(country_code)
        airport.save(update_fields=["parent"])
        return airport

    def _paris_airport(self) -> Place:
        """A further airport serving Paris, distinct from every other one."""

        self._grown += 1
        return self._airport(
            "FR", f"Paris Field {self._grown}", f"Q{self._grown:02d}", self.paris
        )

    def setUp(self):
        self.build_world()
        self.policy = Phase2Policy.from_settings(
            BusinessSettingsVersion.objects.get(
                status=BusinessSettingsVersion.Status.ACTIVE
            )
        )
        self.journeys = 1
        self.requests = 1

    # -- growth -----------------------------------------------------------

    def grow_journeys_to(self, total: int) -> None:
        for index in range(self.journeys, total):
            traveler = _user(f"k7e-traveler-{index}@example.com")
            _approve_kyc(traveler, f"k7etrav{index}x")
            self._journey(traveler, origin=self._paris_airport())
        self.journeys = max(self.journeys, total)

    def grow_split_header_journeys_to(self, total: int) -> None:
        """Journeys whose header names one Paris airport and whose first leg
        leaves from another (ORY in the header, CDG on the leg), so no leg can
        lend the header its served mapping."""

        for index in range(self.journeys, total):
            traveler = _user(f"k7e-split-{index}@example.com")
            _approve_kyc(traveler, f"k7esplit{index}x")
            journey, _, _ = self._journey(traveler, origin=self._paris_airport())
            journey.start_place = self._paris_airport()
            journey.save(update_fields=["start_place"])
        self.journeys = max(self.journeys, total)

    def grow_requests_to(self, total: int) -> None:
        for index in range(self.requests, total):
            # Alternate a locality and an airport pickup so both the parent
            # join and the airport-to-locality mapping are exercised per row.
            origin = self.paris if index % 2 else self._paris_airport()
            self._request(origin, self.jijel, title=f"K7-E request {index}")
        self.requests = max(self.requests, total)

    # -- reads ------------------------------------------------------------

    def find_travelers_page(self) -> dict:
        candidates = compatible_journeys_for_request(
            delivery_request=self.request, policy=self.policy
        )
        page, block = find_travelers(
            delivery_request=self.request, candidates=candidates, limit=50
        )
        return page.as_dict(request_block=block)

    def compatible_journeys_payload(self) -> list[dict]:
        return [
            row.as_public_dict(include_recommendation=True)
            for row in compatible_journeys_for_request(
                delivery_request=self.request, policy=self.policy
            )
        ]

    def compatible_requests_payload(self) -> list[dict]:
        # The rows `GET /api/matches/compatible-requests` serves (P2: card rows).
        return [
            row.as_card_row()
            for row in compatible_requests_for_journey(
                journey=self.journey, policy=self.policy
            )
        ]

    @staticmethod
    def measure(read) -> tuple[int, object]:
        # Warm first-read caches so the measurement is of the read itself.
        read()
        with CaptureQueriesContext(connection) as captured:
            payload = read()
        return len(captured.captured_queries), payload


class DiscoveryQueryCountTests(RegionalCanonicalFixture, TestCase):
    def test_the_world_really_has_region_parents(self):
        # If this stops holding, the flat-count tests below stop covering the
        # lazy parent load they were written for.
        self.grow_journeys_to(3)
        self.assertFalse(
            Place.objects.exclude(place_type=Place.PlaceType.ADMIN_REGION)
            .filter(parent__isnull=True)
            .exists()
        )

    def test_find_travelers_cost_is_flat_from_n_to_2n_journeys(self):
        self.grow_journeys_to(4)
        n_queries, n_payload = self.measure(self.find_travelers_page)
        self.assertEqual(n_payload["page"]["total"], 4)

        self.grow_journeys_to(8)
        two_n_queries, two_n_payload = self.measure(self.find_travelers_page)
        self.assertEqual(two_n_payload["page"]["total"], 8)

        self.assertEqual(n_queries, two_n_queries)
        # Every stop still carries its public city name, including the city
        # each distinct airport resolves to; the Algerian ones are the parent.
        for row in two_n_payload["results"]:
            self.assertEqual(
                [stop["label"] for stop in row["route"]["stops"]],
                ["Paris", "Region DZ", "Region DZ"],
            )

    def test_compatible_journeys_cost_is_flat_from_n_to_2n_journeys(self):
        self.grow_journeys_to(4)
        n_queries, n_payload = self.measure(self.compatible_journeys_payload)
        self.assertEqual(len(n_payload), 4)

        self.grow_journeys_to(8)
        two_n_queries, two_n_payload = self.measure(self.compatible_journeys_payload)
        self.assertEqual(len(two_n_payload), 8)

        self.assertEqual(n_queries, two_n_queries)
        for row in two_n_payload:
            start = row["journey"]["start_place"]
            origin = row["journey"]["covered_legs"][0]["origin_place"]
            self.assertEqual(start, origin)
            self.assertEqual(start["display_label"], f"{start['name']} · Region FR")
            self.assertEqual(start["matching_locality_id"], self.paris.pk)

    def test_compatible_journeys_cost_is_flat_with_a_header_airport_no_leg_uses(self):
        # P2 second pass: a header airport that is not a leg place used to
        # cost one mapping query per candidate; it is now loaded in one batch.
        self.grow_split_header_journeys_to(4)
        n_queries, n_payload = self.measure(self.compatible_journeys_payload)
        self.assertEqual(len(n_payload), 4)

        self.grow_split_header_journeys_to(8)
        two_n_queries, two_n_payload = self.measure(self.compatible_journeys_payload)
        self.assertEqual(len(two_n_payload), 8)

        self.assertEqual(n_queries, two_n_queries)
        split = [row for row in two_n_payload if row["journey"]["id"] != self.journey.pk]
        self.assertEqual(len(split), 7)
        for row in split:
            start = row["journey"]["start_place"]
            self.assertEqual(start["matching_locality_id"], self.paris.pk)
            self.assertNotEqual(
                start["id"], row["journey"]["covered_legs"][0]["origin_place"]["id"]
            )

    def test_compatible_requests_cost_is_flat_from_n_to_2n_requests(self):
        self.grow_requests_to(4)
        n_queries, n_payload = self.measure(self.compatible_requests_payload)
        self.assertEqual(len(n_payload), 4)

        self.grow_requests_to(8)
        two_n_queries, two_n_payload = self.measure(self.compatible_requests_payload)
        self.assertEqual(len(two_n_payload), 8)

        self.assertEqual(n_queries, two_n_queries)
        airport_pickups = 0
        for row in two_n_payload:
            pickup = row["delivery_request"]["pickup_place"]
            delivery = row["delivery_request"]["delivery_place"]
            self.assertEqual(pickup["display_label"], "Paris")
            # An airport pickup still resolves to its served locality.
            self.assertEqual(pickup["matching_locality_id"], self.paris.pk)
            airport_pickups += pickup["place_type"] == Place.PlaceType.AIRPORT
            self.assertEqual(delivery["display_label"], "Region DZ")
        self.assertEqual(airport_pickups, 3)
