"""L2A privacy contract: the five public payloads carry public facts only.

Each test builds members with a distinctive surname, email, phone, street
address, exact coordinates, a deal recipient and a KYC row, then walks the
whole JSON answer: none of those strings and none of the forbidden keys may
appear anywhere in it, at any depth. The four public reads are walked twice:
as a member and as a guest without an account (plan EGS, decision 10).

The places carry catalogue-shaped names and parents (fix plan P2), so the
walk also proves a public stop names a city only: never the catalogue's
`"<name> · <parent>"` label, a department, the Algerian commune behind its
wilaya, or an airport's own name.
"""

from __future__ import annotations

import json

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.deals.models import DealRecipient
from apps.kyc.models import KycSubmission
from apps.locations.models import Location
from apps.matching.v1_services import accept_offer
from apps.parcels.models import DeliveryRequest

from .support import DiscoveryWorld, client_for, give_catalogue_names

SECRETS = (
    "Zekkouriqa",  # sender surname
    "Bouqtafrin",  # traveler surname
    "zekk.private@example.com",
    "bouq.private@example.com",
    "+213555019283",
    "+33655019284",
    "Rue des Quinconces Zekk",  # street address
    "48.871234",  # exact latitude
    "2.318765",  # exact longitude
    "Nadjibouline",  # recipient name
    "recipient.hidden@example.com",
    "+213777000111",
    "kyc/privacy-secret",  # KYC object key
    "WSL-",  # any tracking number (L11A)
)

#: Catalogue naming a public stop never carries (P2): the departments, the
#: commune behind the wilaya "Alger", and the airports' own names.
CATALOGUE_ONLY = (
    "Seine-Quinconces",
    "Val-d'Oise",
    "Alger Centre",
    "Houari Boumediene",
    "Charles de Gaulle",
)

FORBIDDEN_KEYS = {
    "email",
    "phone",
    "full_name",
    "last_name",
    "first_name",
    "username",
    "user_id",
    "sender_id",
    "traveler_id",
    "address",
    "street",
    "private_label",
    "normalized_label",
    "latitude",
    "longitude",
    "lat",
    "lng",
    "coordinates",
    "pickup_location",
    "delivery_location",
    "location",
    "recipient",
    "kyc",
    "document_type",
    "front_image_key",
    "hidden_reason",
    "hidden_by",
    "consented_at",
    "flight_number",
    "description",
    "declared_value_eur_cents",
    "tracking_number",
}


def _place_labels(value, found: list[str]) -> list[str]:
    """Every public stop label (`label` beside a `place_id`), at any depth."""

    if isinstance(value, dict):
        if "place_id" in value and isinstance(value.get("label"), str):
            found.append(value["label"])
        for inner in value.values():
            _place_labels(inner, found)
    elif isinstance(value, list):
        for inner in value:
            _place_labels(inner, found)
    return found


def _keys(value, found: set[str]) -> set[str]:
    if isinstance(value, dict):
        for key, inner in value.items():
            found.add(key)
            _keys(inner, found)
    elif isinstance(value, list):
        for inner in value:
            _keys(inner, found)
    return found


class PublicPayloadPrivacyTests(DiscoveryWorld, TestCase):
    def setUp(self):
        self.build_discovery_world()
        give_catalogue_names(self, paris_department="Seine-Quinconces")
        self._make_people_distinctive()
        self.opt_in(self.sender, (self.paris, self.jijel))
        self.opt_in(self.traveler, (self.algiers, self.jijel))

    def _make_people_distinctive(self):
        self.sender.full_name = "Samira Zekkouriqa"
        self.sender.email = "zekk.private@example.com"
        self.sender.phone = "+213555019283"
        self.sender.save(update_fields=["full_name", "email", "phone"])
        self.traveler.full_name = "Yacine Bouqtafrin"
        self.traveler.email = "bouq.private@example.com"
        self.traveler.phone = "+33655019284"
        self.traveler.save(update_fields=["full_name", "email", "phone"])
        KycSubmission.objects.filter(user=self.traveler).update(
            front_image_key="kyc/privacy-secret/front.jpg"
        )

        # The first request is booked: its deal has a named recipient.
        accepted = accept_offer(pending_offer=self.propose(), actor=self.traveler)
        DealRecipient.objects.create(
            deal=accepted.deal,
            full_name="Karima Nadjibouline",
            email="recipient.hidden@example.com",
            phone="+213777000111",
            created_by=self.sender,
        )
        # The second request is open and carries an exact street address.
        street = Location.objects.create(
            owner=self.sender,
            created_by=self.sender,
            kind=Location.Kind.EXACT_ADDRESS,
            normalized_label="5 Rue des Quinconces Zekk, Paris",
            public_label="Paris",
            private_label="Flat 2, 5 Rue des Quinconces Zekk, Paris",
            city="Paris",
            country_code="FR",
            latitude="48.871234",
            longitude="2.318765",
            coarse_latitude="48.870000",
            coarse_longitude="2.320000",
            source="manual",
            precision=Location.Precision.ROOFTOP,
        )
        self.open_request = self._request(self.paris, self.jijel, title="Gift box")
        DeliveryRequest.objects.filter(pk=self.open_request.pk).update(
            pickup_location=street
        )

    def assertPublic(self, payload, *, expect: str):
        text = json.dumps(payload, default=str)
        self.assertIn(expect, text, "the payload under test is empty")
        for secret in SECRETS:
            self.assertNotIn(secret, text)
        self.assertEqual(_keys(payload, set()) & FORBIDDEN_KEYS, set())
        for name in CATALOGUE_ONLY:
            self.assertNotIn(name, text)
        labels = _place_labels(payload, [])
        self.assertTrue(labels, "the payload under test names no place")
        self.assertLessEqual(set(labels), {"Paris", "Alger", "Jijel"}, labels)
        for label in labels:
            self.assertNotIn(" · ", label)

    def _get(self, viewer, name, *args, **query):
        """`viewer` `None` reads as a guest, without an account."""

        client = APIClient() if viewer is None else client_for(viewer)
        response = client.get(reverse(name, args=args), query)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def readers(self):
        """A member who owns nothing, then a guest."""

        return ((self.other, "member"), (None, "guest"))

    def test_the_trip_listing_is_public_only(self):
        for viewer, label in self.readers():
            with self.subTest(viewer=label):
                payload = self._get(viewer, "discovery-trips")
                self.assertPublic(payload, expect="Yacine")

    def test_the_request_listing_is_public_only(self):
        for viewer, label in self.readers():
            with self.subTest(viewer=label):
                payload = self._get(viewer, "discovery-requests")
                self.assertEqual(
                    [row["request_id"] for row in payload["results"]], [self.open_request.pk]
                )
                self.assertPublic(payload, expect="Samira")

    def test_the_people_list_is_public_only(self):
        for viewer, label in self.readers():
            with self.subTest(viewer=label):
                travelers = self._get(viewer, "discovery-people", role="sender")
                senders = self._get(viewer, "discovery-people", role="traveler")
                self.assertPublic(travelers, expect="Yacine")
                self.assertPublic(senders, expect="Samira")

    def test_the_person_page_is_public_only(self):
        for viewer, label in self.readers():
            for user, name in ((self.traveler, "Yacine"), (self.sender, "Samira")):
                with self.subTest(viewer=label, person=name):
                    public_id = user.public_profile.public_id
                    payload = self._get(viewer, "discovery-person", public_id)
                    self.assertTrue(payload["trips"] or payload["requests"])
                    self.assertPublic(payload, expect=name)

    def test_the_own_profile_preview_is_public_only(self):
        for user, name in ((self.traveler, "Yacine"), (self.sender, "Samira")):
            with self.subTest(name):
                self.assertPublic(self._get(user, "discovery-profile-me"), expect=name)
