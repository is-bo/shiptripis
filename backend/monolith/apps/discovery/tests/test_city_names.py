"""Fix plan P2: public and pre-funding route lines name cities only.

The world is the canonical CDG → ALG → Jijel one with catalogue-shaped names
and parents (`give_catalogue_names`): ALG serves the commune "Alger Centre"
under the wilaya "Alger", Paris sits under its department "Paris". Before P2
the cards read "Alger Centre · Alger" and "Paris · Paris"; now every reader who
is not a party reads "Alger" and "Paris". The owner, the place picker and the
staff console keep the full catalogue label.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.admin_panel.ops_serializers import AdminRequestSerializer
from apps.trips.models import Journey, JourneyLeg, JourneyLegProof

from .support import DiscoveryWorld, client_for, give_catalogue_names

CITIES = {"Alger", "Paris", "Jijel"}


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

    def test_compatible_requests_show_the_city(self):
        payload = self._get(
            self.traveler, "matches-compatible-requests-v1", journey_id=self.journey.pk
        )
        [row] = payload["results"]
        request = row["delivery_request"]
        self.assertEqual(request["pickup_place"]["display_label"], "Paris")
        self.assertEqual(request["delivery_place"]["display_label"], "Jijel")
        self.assertCitiesOnly(payload, expect={"Paris", "Alger", "Jijel"})

    def test_a_proposal_shows_the_city(self):
        offer = self.propose()
        for user in (self.traveler, self.sender):
            with self.subTest(user=user.email):
                detail = self._get(user, "matches-detail", offer.match_id)
                self.assertEqual(detail["parcel"]["origin"]["display_label"], "Paris")
                self.assertEqual(detail["parcel"]["destination"]["display_label"], "Jijel")
                self.assertCitiesOnly(detail, expect={"Paris", "Alger", "Jijel"})
                listed = self._get(user, "matches-list")
                self.assertCitiesOnly(listed, expect={"Paris", "Jijel"})

    # -- precision stays where it is the point --------------------------------

    def test_owner_picker_and_staff_keep_the_catalogue_label(self):
        owned = self._get(self.traveler, "journeys-detail", self.journey.pk)
        self.assertEqual(owned["destination_place"]["display_label"], "Jijel · Jijel")
        self.assertIn("Alger Centre · Alger", _labels(owned, []))

        picker = self._get(self.sender, "geography-places", country="DZ", q="Alger Centre")
        self.assertIn("Alger Centre · Alger", _labels(picker, []))

        staff = AdminRequestSerializer(self.request).data
        self.assertEqual(staff["pickup_place_name"], "Paris · Paris")
