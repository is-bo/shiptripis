"""Fix plan P2: cards show cities; detail pages show the catalogue place.

The owner's rule of 2026-11-24. The world is the canonical CDG → ALG → Jijel
one with catalogue-shaped names and parents (`give_catalogue_names`): ALG
serves the commune "Alger Centre" under the wilaya "Alger", Paris sits under
its department "Paris". Before P2 the cards read "Alger Centre · Alger" and
"Paris · Paris"; now every card and list row reads "Alger" and "Paris", in
every name-like field. Detail pages (journey and request detail, the
negotiation screen's proposal), the place picker, the owner's screens and the
staff views keep the full catalogue label.
"""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.admin_panel.ops_serializers import AdminRequestSerializer
from apps.locations.models import Location
from apps.matching.discovery import explain_candidate
from apps.trips.models import Journey, JourneyLeg, JourneyLegProof

from .support import DiscoveryWorld, client_for, give_catalogue_names

CITIES = {"Alger", "Paris", "Jijel"}

#: Catalogue and preferred-point naming no card or list row may carry, in any
#: field: the commune behind the wilaya, the airports' own names, a parent
#: department, the catalogue label's separator, and the preferred points'
#: own labels attached in `_attach_preferred_points`.
CARD_FORBIDDEN = (
    "Alger Centre",
    "Houari Boumediene",
    "Charles de Gaulle",
    "Val-d'Oise",
    " · ",
    "Quinconces Point",
    "Roissy Point",
)


def _labels(value, found: list[str]) -> list[str]:
    """Every place name in a payload, at any depth.

    A place block is a dict with `place_id` (a public stop: `label`) or
    `place_type` (a place summary: `display_label`). Other `label` keys, such
    as a distance band's, are not place names.
    """

    if isinstance(value, dict):
        if "place_id" in value and isinstance(value.get("label"), str):
            found.append(value["label"])
        if "place_type" in value and isinstance(value.get("display_label"), str):
            found.append(value["display_label"])
        for inner in value.values():
            _labels(inner, found)
    elif isinstance(value, list):
        for inner in value:
            _labels(inner, found)
    return found


class PublicCityNameTests(DiscoveryWorld, TestCase):
    def setUp(self):
        self.build_discovery_world()
        give_catalogue_names(self)
        self.opt_in(self.sender, (self.paris, self.jijel))
        self.opt_in(self.traveler, (self.alg, self.cdg))
        self.home_bound = self._alg_to_cdg_journey()

    def _alg_to_cdg_journey(self) -> Journey:
        """The demo shape Ismail saw: one flight from ALG to CDG."""

        traveler = self.new_traveler("p2-home-bound@example.com", name="Nadia Test")
        depart = self.now + timedelta(days=3)
        journey = Journey.objects.create(
            traveler=traveler,
            schema_version=2,
            start_place=self.alg,
            destination_place=self.cdg,
            status=Journey.Status.ACTIVE,
            published_at=self.now,
        )
        leg = JourneyLeg.objects.create(
            journey=journey,
            position=0,
            mode=JourneyLeg.Mode.FLIGHT,
            origin_place=self.alg,
            destination_place=self.cdg,
            depart_at=depart,
            arrive_at=depart + timedelta(hours=2, minutes=30),
            capacity_kg=Decimal("12.00"),
            flight_number="AH1006",
        )
        JourneyLegProof.objects.create(
            leg=leg,
            bucket="private",
            object_key=f"p2/{journey.pk}-ticket.jpg",
            status=JourneyLegProof.Status.APPROVED,
            reviewer=self.sender,
            reviewed_at=self.now,
        )
        return journey

    def _get(self, viewer, name, *args, **query):
        """`viewer` `None` reads as a guest, without an account."""

        client = APIClient() if viewer is None else client_for(viewer)
        response = client.get(reverse(name, args=args), query)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def readers(self):
        return ((self.other, "member"), (None, "guest"))

    def assertCitiesOnly(self, payload, *, expect: set[str]):
        labels = _labels(payload, [])
        self.assertTrue(expect <= set(labels), labels)
        self.assertLessEqual(set(labels), CITIES, labels)
        text = json.dumps(payload, default=str, ensure_ascii=False)
        for forbidden in CARD_FORBIDDEN:
            self.assertNotIn(forbidden, text)

    def _point(self, owner, label: str, place, latitude: str, longitude: str):
        return Location.objects.create(
            owner=owner,
            created_by=owner,
            kind=Location.Kind.EXACT_ADDRESS,
            normalized_label=f"1 Rue {label}",
            public_label=label,
            private_label=f"1 Rue {label}",
            city=label,
            country_code=place.country_id,
            canonical_place=place,
            latitude=latitude,
            longitude=longitude,
            coarse_latitude=latitude,
            coarse_longitude=longitude,
            source="manual",
            precision=Location.Precision.ROOFTOP,
        )

    def _attach_preferred_points(self):
        """Preferred map points on the request and the journey (Blocker 1)."""

        self.request.pickup_location = self._point(
            self.sender, "Quinconces Point", self.paris, "48.871234", "2.318765"
        )
        self.request.save(update_fields=["pickup_location"])
        self.journey.start_location = self._point(
            self.traveler, "Roissy Point", self.paris, "49.009700", "2.547900"
        )
        self.journey.save(update_fields=["start_location"])

    # -- guest and member surfaces -----------------------------------------

    def test_trip_cards_read_alger_to_paris(self):
        for viewer, label in self.readers():
            with self.subTest(viewer=label):
                payload = self._get(viewer, "discovery-trips")
                cards = {row["journey_id"]: row for row in payload["results"]}
                self.assertEqual(
                    [stop["label"] for stop in cards[self.home_bound.pk]["stops"]],
                    ["Alger", "Paris"],
                )
                self.assertEqual(
                    [stop["label"] for stop in cards[self.journey.pk]["stops"]],
                    ["Paris", "Alger", "Jijel"],
                )
                # Identity is still the commune behind the name.
                self.assertEqual(
                    cards[self.home_bound.pk]["stops"][0]["place_id"], self.algiers.pk
                )
                self.assertCitiesOnly(payload, expect={"Alger", "Paris", "Jijel"})

    def test_request_cards(self):
        self._request(self.alg, self.paris, title="Home-bound gift")
        for viewer, label in self.readers():
            with self.subTest(viewer=label):
                payload = self._get(viewer, "discovery-requests")
                routes = sorted(
                    (row["pickup"]["label"], row["delivery"]["label"])
                    for row in payload["results"]
                )
                self.assertEqual(routes, [("Alger", "Paris"), ("Paris", "Jijel")])
                self.assertCitiesOnly(payload, expect={"Alger", "Paris", "Jijel"})

    def test_people_and_person_pages(self):
        for viewer, label in self.readers():
            with self.subTest(viewer=label):
                travelers = self._get(viewer, "discovery-people", role="sender")
                senders = self._get(viewer, "discovery-people", role="traveler")
                self.assertCitiesOnly(travelers, expect={"Alger", "Paris"})
                self.assertCitiesOnly(senders, expect={"Paris", "Jijel"})
                for user in (self.traveler, self.sender):
                    page = self._get(
                        viewer, "discovery-person", user.public_profile.public_id
                    )
                    self.assertCitiesOnly(page, expect={"Paris"})
        page = self._get(None, "discovery-person", self.traveler.public_profile.public_id)
        self.assertEqual(
            page["profile"]["usual_routes"][0]["origin"],
            {"place_id": self.algiers.pk, "label": "Alger", "country_code": "DZ"},
        )

    def test_the_own_profile_preview(self):
        self.assertCitiesOnly(
            self._get(self.traveler, "discovery-profile-me"), expect={"Alger", "Paris"}
        )

    def test_route_alerts(self):
        created = client_for(self.sender).post(
            reverse("discovery-alerts"),
            {
                "watches": "trips",
                "origin_place_id": self.alg.pk,
                "destination_place_id": self.cdg.pk,
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data["origin"]["label"], "Alger")
        self.assertEqual(created.data["destination"]["label"], "Paris")
        self.assertCitiesOnly(
            self._get(self.sender, "discovery-alerts"), expect={"Alger", "Paris"}
        )

    def test_matches_for_you(self):
        for user, role in ((self.sender, "sender"), (self.traveler, "traveler")):
            with self.subTest(role=role):
                payload = self._get(user, "discovery-matches", role=role)
                self.assertTrue(payload["groups"])
                self.assertCitiesOnly(payload, expect={"Paris", "Jijel"})

    # -- signed-in, before funding ------------------------------------------

    def test_find_travelers_stops_name_the_city_beside_the_iata(self):
        payload = self._get(
            self.sender, "matches-find-travelers-v1", parcel_id=self.request.pk
        )
        [row] = [r for r in payload["results"] if r["journey_id"] == self.journey.pk]
        self.assertEqual(
            [(stop["label"], stop["airport_iata"]) for stop in row["route"]["stops"]],
            [("Paris", "CDG"), ("Alger", "ALG"), ("Jijel", None)],
        )
        self.assertCitiesOnly(payload, expect={"Paris", "Alger", "Jijel"})

    def test_compatible_request_rows_name_cities_even_with_preferred_points(self):
        # The rows of the traveler's journey screen and of "Matches for you".
        self._attach_preferred_points()
        payload = self._get(
            self.traveler, "matches-compatible-requests-v1", journey_id=self.journey.pk
        )
        [row] = payload["results"]
        request = row["delivery_request"]
        # The endpoint the app renders first is the catalogue place, not the
        # preferred point, and every name field reads the city.
        self.assertEqual(
            request["pickup"],
            {
                "id": self.paris.pk,
                "name": "Paris",
                "display_label": "Paris",
                "place_type": "locality",
                "country_code": "FR",
                "iata_code": None,
                "matching_locality_id": self.paris.pk,
            },
        )
        self.assertEqual(request["delivery_place"]["name"], "Jijel")
        self.assertEqual(row["journey"]["start_location"]["name"], "Paris")
        covered = row["compatibility"]["covered_legs"]
        self.assertEqual(
            [(leg["origin_place"]["name"], leg["destination_place"]["name"]) for leg in covered],
            [("Paris", "Alger"), ("Alger", "Jijel")],
        )
        self.assertCitiesOnly(payload, expect={"Paris", "Alger", "Jijel"})
        matches = self._get(self.traveler, "discovery-matches", role="traveler")
        self.assertCitiesOnly(matches, expect={"Paris", "Alger", "Jijel"})

    # -- detail pages keep the catalogue place (owner's rule) -----------------

    def test_the_negotiation_detail_keeps_the_catalogue_place(self):
        offer = self.propose()
        for user in (self.traveler, self.sender):
            with self.subTest(user=user.email):
                detail = self._get(user, "matches-detail", offer.match_id)
                self.assertEqual(
                    detail["parcel"]["origin"]["display_label"], "Paris · Paris"
                )
                self.assertEqual(
                    detail["parcel"]["destination"]["display_label"], "Jijel · Jijel"
                )
                self.assertIn("Alger Centre · Alger", _labels(detail, []))

    def test_a_members_journey_detail_keeps_the_catalogue_place(self):
        detail = self._get(self.other, "journeys-detail", self.home_bound.pk)
        self.assertEqual(
            detail["start_place"]["display_label"], "Houari Boumediene Airport · Alger"
        )

    def test_the_staff_explain_keeps_the_catalogue_place(self):
        explained = explain_candidate(
            delivery_request_id=self.request.pk, journey_id=self.journey.pk
        ).as_dict()
        self.assertEqual(
            explained["delivery_request"]["pickup_place"]["display_label"], "Paris · Paris"
        )
        self.assertIn("Alger Centre · Alger", _labels(explained, []))

    # -- precision stays where it is the point --------------------------------

    def test_owner_picker_and_staff_keep_the_catalogue_label(self):
        owned = self._get(self.traveler, "journeys-detail", self.journey.pk)
        self.assertEqual(owned["destination_place"]["display_label"], "Jijel · Jijel")
        self.assertIn("Alger Centre · Alger", _labels(owned, []))

        picker = self._get(self.sender, "geography-places", country="DZ", q="Alger Centre")
        self.assertIn("Alger Centre · Alger", _labels(picker, []))

        staff = AdminRequestSerializer(self.request).data
        self.assertEqual(staff["pickup_place_name"], "Paris · Paris")
