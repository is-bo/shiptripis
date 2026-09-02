from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import User
from apps.kyc.models import KycSubmission
from apps.locations.models import AirportLocalityMapping, Country, Location, Place
from apps.trips.models import Journey, JourneyLeg, JourneyLegProof
from apps.trips.services import JourneyDomainError, publish_journey


def _user(email: str) -> User:
    return User.objects.create_user(
        username=email,
        email=email,
        password="Sup3rStrongPass!",
        full_name="Journey Tester",
        role=User.Role.BOTH,
    )


def _client(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _location(label: str, *, owner: User | None = None) -> Location:
    return Location.objects.create(
        kind=Location.Kind.CITY,
        normalized_label=label.lower(),
        public_label=label,
        private_label=f"Exact {label}",
        city=label,
        country_code="FR" if label == "Paris" else "DZ",
        latitude=Decimal("36.752500"),
        longitude=Decimal("3.041970"),
        owner=owner,
    )


def _approve_kyc(user: User, *, expired: bool = False) -> KycSubmission:
    expiry = timezone.now() - timedelta(minutes=1) if expired else None
    return KycSubmission.objects.create(
        user=user,
        document_type=KycSubmission.DocumentType.PASSPORT,
        idempotency_key=f"{user.pk:032d}",
        front_image_key=f"kyc/{user.pk}/front.jpg",
        status=KycSubmission.Status.APPROVED,
        expires_at=expiry,
    )


class JourneyServiceTests(APITestCase):
    def setUp(self):
        self.owner = _user("journey-owner@example.com")
        self.other = _user("journey-other@example.com")
        self.paris = _location("Paris")
        self.algiers = _location("Algiers")
        self.jijel = _location("Jijel")
        self.depart = timezone.now() + timedelta(days=5)

    def _journey(self) -> Journey:
        return Journey.objects.create(
            traveler=self.owner,
            start_location=self.paris,
            destination_location=self.jijel,
        )

    def _leg(
        self,
        journey: Journey,
        *,
        position: int,
        mode: str,
        origin: Location,
        destination: Location,
        hours: int,
    ) -> JourneyLeg:
        depart_at = self.depart + timedelta(hours=hours)
        return JourneyLeg.objects.create(
            journey=journey,
            position=position,
            mode=mode,
            origin=origin,
            destination=destination,
            depart_at=depart_at,
            arrive_at=depart_at + timedelta(hours=2),
            capacity_kg=Decimal("12.50"),
            flight_number="AH1006" if mode == JourneyLeg.Mode.FLIGHT else "",
        )

    def test_legs_are_returned_in_position_order(self):
        journey = self._journey()
        second = self._leg(
            journey,
            position=1,
            mode=JourneyLeg.Mode.DRIVE,
            origin=self.algiers,
            destination=self.jijel,
            hours=4,
        )
        first = self._leg(
            journey,
            position=0,
            mode=JourneyLeg.Mode.FLIGHT,
            origin=self.paris,
            destination=self.algiers,
            hours=0,
        )
        assert list(journey.legs.all()) == [first, second]

    def test_publish_requires_current_kyc_approval(self):
        journey = self._journey()
        self._leg(
            journey,
            position=0,
            mode=JourneyLeg.Mode.DRIVE,
            origin=self.paris,
            destination=self.jijel,
            hours=0,
        )

        with self.assertRaises(JourneyDomainError) as raised:
            publish_journey(journey=journey, actor=self.owner)

        assert raised.exception.code == "traveler_kyc_not_approved"
        journey.refresh_from_db()
        assert journey.status == Journey.Status.DRAFT

    def test_expired_kyc_is_not_current(self):
        _approve_kyc(self.owner, expired=True)
        journey = self._journey()
        self._leg(
            journey,
            position=0,
            mode=JourneyLeg.Mode.DRIVE,
            origin=self.paris,
            destination=self.jijel,
            hours=0,
        )

        with self.assertRaises(JourneyDomainError) as raised:
            publish_journey(journey=journey, actor=self.owner)

        assert raised.exception.code == "traveler_kyc_not_approved"

    def test_drive_journey_publishes_without_transport_proof(self):
        _approve_kyc(self.owner)
        journey = self._journey()
        self._leg(
            journey,
            position=0,
            mode=JourneyLeg.Mode.DRIVE,
            origin=self.paris,
            destination=self.jijel,
            hours=0,
        )

        published = publish_journey(journey=journey, actor=self.owner)

        assert published.status == Journey.Status.ACTIVE
        assert published.published_at is not None

    def test_flight_requires_approved_proof(self):
        _approve_kyc(self.owner)
        journey = self._journey()
        leg = self._leg(
            journey,
            position=0,
            mode=JourneyLeg.Mode.FLIGHT,
            origin=self.paris,
            destination=self.jijel,
            hours=0,
        )
        proof = JourneyLegProof.objects.create(
            leg=leg,
            bucket="private-proof",
            object_key="journeys/1/ticket.jpg",
        )

        with self.assertRaises(JourneyDomainError) as raised:
            publish_journey(journey=journey, actor=self.owner)
        assert raised.exception.code == "flight_proof_not_approved"

        proof.status = JourneyLegProof.Status.APPROVED
        proof.reviewer = self.other
        proof.reviewed_at = timezone.now()
        proof.save(update_fields=["status", "reviewer", "reviewed_at", "updated_at"])
        published = publish_journey(journey=journey, actor=self.owner)
        assert published.status == Journey.Status.ACTIVE

    def test_non_owner_cannot_publish(self):
        _approve_kyc(self.owner)
        journey = self._journey()
        self._leg(
            journey,
            position=0,
            mode=JourneyLeg.Mode.DRIVE,
            origin=self.paris,
            destination=self.jijel,
            hours=0,
        )

        with self.assertRaises(JourneyDomainError) as raised:
            publish_journey(journey=journey, actor=self.other)

        assert raised.exception.code == "journey_not_owned"

    def test_publish_rejects_non_contiguous_leg_positions(self):
        _approve_kyc(self.owner)
        journey = self._journey()
        self._leg(
            journey,
            position=1,
            mode=JourneyLeg.Mode.DRIVE,
            origin=self.paris,
            destination=self.jijel,
            hours=0,
        )

        with self.assertRaises(JourneyDomainError) as raised:
            publish_journey(journey=journey, actor=self.owner)

        assert raised.exception.code == "journey_leg_positions_invalid"


class JourneyApiTests(APITestCase):
    def setUp(self):
        self.owner = _user("journey-api-owner@example.com")
        self.other = _user("journey-api-other@example.com")
        self.paris = _location("Paris", owner=self.owner)
        self.algiers = _location("Algiers")
        self.jijel = _location("Jijel")
        self.depart = timezone.now() + timedelta(days=7)
        self.client = _client(self.owner)

        france = Country.objects.create(
            code="FR",
            name="France",
            source="phase8c-test",
            source_id="country-fr",
            source_version="phase8c",
        )
        algeria = Country.objects.create(
            code="DZ",
            name="Algeria",
            source="phase8c-test",
            source_id="country-dz",
            source_version="phase8c",
        )

        def locality(country, name, source_id, latitude, longitude):
            return Place.objects.create(
                country=country,
                place_type=Place.PlaceType.LOCALITY,
                source="phase8c-test",
                source_id=source_id,
                source_version="phase8c",
                name=name,
                latitude=latitude,
                longitude=longitude,
            )

        self.paris_place = locality(
            france, "Paris", "locality-paris", "48.856600", "2.352200"
        )
        self.algiers_place = locality(
            algeria, "Algiers", "locality-algiers", "36.753800", "3.058800"
        )
        self.jijel_place = locality(
            algeria, "Jijel", "locality-jijel", "36.820600", "5.766700"
        )

        def airport(country, locality_place, name, iata, latitude, longitude):
            place = Place.objects.create(
                country=country,
                place_type=Place.PlaceType.AIRPORT,
                source="phase8c-test",
                source_id=f"airport-{iata}",
                source_version="phase8c",
                name=name,
                iata_code=iata,
                latitude=latitude,
                longitude=longitude,
                passenger_use=True,
            )
            AirportLocalityMapping.objects.create(
                airport=place,
                locality=locality_place,
                relationship_type=AirportLocalityMapping.RelationshipType.SERVED,
                is_primary=True,
                source="phase8c-test",
                source_id=f"mapping-{iata}",
                source_version="phase8c",
            )
            return place

        self.cdg_place = airport(
            france,
            self.paris_place,
            "Paris Charles de Gaulle",
            "CDG",
            "49.009700",
            "2.547900",
        )
        self.alg_place = airport(
            algeria,
            self.algiers_place,
            "Houari Boumediene",
            "ALG",
            "36.691000",
            "3.215400",
        )

    def _payload(self) -> dict:
        return {
            "start_location": self.paris.pk,
            "destination_location": self.jijel.pk,
            "notes": "One flight and one road segment",
            "legs": [
                {
                    "position": 1,
                    "mode": JourneyLeg.Mode.DRIVE,
                    "origin": self.algiers.pk,
                    "destination": self.jijel.pk,
                    "depart_at": (self.depart + timedelta(hours=5)).isoformat(),
                    "arrive_at": (self.depart + timedelta(hours=8)).isoformat(),
                    "capacity_kg": "8.50",
                },
                {
                    "position": 0,
                    "mode": JourneyLeg.Mode.FLIGHT,
                    "origin": self.paris.pk,
                    "destination": self.algiers.pk,
                    "depart_at": self.depart.isoformat(),
                    "arrive_at": (self.depart + timedelta(hours=3)).isoformat(),
                    "capacity_kg": "10.00",
                    "flight_number": "AH1006",
                },
            ],
        }

    def _canonical_payload(self) -> dict:
        return {
            "start_place_id": self.cdg_place.pk,
            "destination_place_id": self.jijel_place.pk,
            "notes": "Paris airport to Jijel via Algiers",
            "legs": [
                {
                    "position": 0,
                    "mode": JourneyLeg.Mode.FLIGHT,
                    "origin_place_id": self.cdg_place.pk,
                    "destination_place_id": self.alg_place.pk,
                    "depart_at": self.depart.isoformat(),
                    "arrive_at": (self.depart + timedelta(hours=3)).isoformat(),
                    "capacity_kg": "10.00",
                    "flight_number": "AH1006",
                },
                {
                    "position": 1,
                    "mode": JourneyLeg.Mode.DRIVE,
                    "origin_place_id": self.algiers_place.pk,
                    "destination_place_id": self.jijel_place.pk,
                    "depart_at": (self.depart + timedelta(hours=5)).isoformat(),
                    "arrive_at": (self.depart + timedelta(hours=8)).isoformat(),
                    "capacity_kg": "8.50",
                },
            ],
        }

    def test_location_only_creation_is_rejected(self):
        response = self.client.post(
            reverse("journeys-list-create"),
            self._payload(),
            format="json",
        )

        assert response.status_code == 400
        assert "start_place_id" in response.data
        assert "destination_place_id" in response.data
        assert Journey.objects.count() == 0

    def test_create_uses_canonical_places_and_locality_continuity(self):
        response = self.client.post(
            reverse("journeys-list-create"),
            self._canonical_payload(),
            format="json",
        )

        assert response.status_code == 201, response.data
        journey = Journey.objects.get(pk=response.data["id"])
        assert journey.schema_version == 2
        assert journey.start_place == self.cdg_place
        assert journey.start_location is None
        assert response.data["status"] == Journey.Status.DRAFT
        assert [leg["position"] for leg in response.data["legs"]] == [0, 1]
        assert (
            response.data["start_place"]["matching_locality_id"] == self.paris_place.pk
        )
        assert response.data["legs"][1]["origin_place"]["id"] == self.algiers_place.pk

    def test_canonical_flight_leg_requires_airport_endpoints(self):
        payload = self._canonical_payload()
        payload["legs"][0]["origin_place_id"] = self.paris_place.pk

        response = self.client.post(
            reverse("journeys-list-create"), payload, format="json"
        )

        assert response.status_code == 400
        assert "origin_place_id" in str(response.data)
        assert Journey.objects.count() == 0

    def test_list_contains_only_callers_journeys(self):
        own = Journey.objects.create(
            traveler=self.owner,
            start_location=self.paris,
            destination_location=self.jijel,
        )
        Journey.objects.create(
            traveler=self.other,
            start_location=self.algiers,
            destination_location=self.jijel,
        )

        response = self.client.get(reverse("journeys-list-create"))

        assert response.status_code == 200
        assert [row["id"] for row in response.data] == [own.pk]

    def test_non_owner_cannot_publish_or_add_proof(self):
        create_response = self.client.post(
            reverse("journeys-list-create"),
            self._canonical_payload(),
            format="json",
        )
        journey_id = create_response.data["id"]
        flight_leg_id = create_response.data["legs"][0]["id"]
        other_client = _client(self.other)

        publish_response = other_client.post(
            reverse("journeys-publish", kwargs={"pk": journey_id})
        )
        proof_response = other_client.post(
            reverse(
                "journey-leg-proof-create",
                kwargs={"journey_pk": journey_id, "leg_pk": flight_leg_id},
            )
        )

        assert publish_response.status_code == 403
        assert publish_response.data["code"] == "journey_not_owned"
        assert proof_response.status_code == 403
        assert proof_response.data["code"] == "journey_not_owned"

    @patch("apps.trips.views.image_bytes_match_extension", return_value=True)
    @patch("apps.trips.views.put_object")
    def test_proof_storage_fields_are_visible_only_to_owner(
        self, _put_object, _valid_image
    ):
        create_response = self.client.post(
            reverse("journeys-list-create"),
            self._canonical_payload(),
            format="json",
        )
        journey_id = create_response.data["id"]
        flight_leg_id = create_response.data["legs"][0]["id"]
        upload = SimpleUploadedFile(
            "ticket.jpg",
            b"test-jpeg-content",
            content_type="image/jpeg",
        )

        proof_response = self.client.post(
            reverse(
                "journey-leg-proof-create",
                kwargs={"journey_pk": journey_id, "leg_pk": flight_leg_id},
            ),
            {"photo": upload, "kind": "ticket"},
            format="multipart",
        )

        assert proof_response.status_code == 201, proof_response.data
        assert "bucket" in proof_response.data
        assert "object_key" in proof_response.data

        proof = JourneyLegProof.objects.get(pk=proof_response.data["id"])
        proof.status = JourneyLegProof.Status.APPROVED
        proof.reviewer = self.other
        proof.reviewed_at = timezone.now()
        proof.save(update_fields=["status", "reviewer", "reviewed_at", "updated_at"])
        _approve_kyc(self.owner)
        publish_response = self.client.post(
            reverse("journeys-publish", kwargs={"pk": journey_id})
        )
        assert publish_response.status_code == 200, publish_response.data

        public_response = _client(self.other).get(
            reverse("journeys-detail", kwargs={"pk": journey_id})
        )
        assert "route_polyline" not in public_response.data["legs"][0]
        assert "route_metadata" not in public_response.data["legs"][0]
        assert "proofs" not in public_response.data["legs"][0]
        assert public_response.data["legs"][0]["has_approved_proof"] is True

    def test_drive_leg_rejects_transport_proof(self):
        journey = Journey.objects.create(
            traveler=self.owner,
            start_location=self.paris,
            destination_location=self.jijel,
        )
        drive_leg = JourneyLeg.objects.create(
            journey=journey,
            position=0,
            mode=JourneyLeg.Mode.DRIVE,
            origin=self.paris,
            destination=self.jijel,
            depart_at=self.depart,
            capacity_kg=Decimal("5.00"),
        )

        response = self.client.post(
            reverse(
                "journey-leg-proof-create",
                kwargs={"journey_pk": journey.pk, "leg_pk": drive_leg.pk},
            )
        )

        assert response.status_code == 400
        assert response.data["code"] == "proof_only_for_flight"


class JourneySearchTests(APITestCase):
    def setUp(self):
        self.searcher = _user("journey-searcher@example.com")
        self.flight_owner = _user("journey-flight-owner@example.com")
        self.drive_owner = _user("journey-drive-owner@example.com")
        self.paris = _location("Paris")
        self.algiers = _location("Algiers")
        self.jijel = _location("Jijel")
        self.depart = timezone.now() + timedelta(days=5)
        self.client = _client(self.searcher)
        self.flight_kyc = _approve_kyc(self.flight_owner)
        _approve_kyc(self.drive_owner)

        self.mixed = Journey.objects.create(
            traveler=self.flight_owner,
            start_location=self.paris,
            destination_location=self.jijel,
            status=Journey.Status.ACTIVE,
            published_at=timezone.now(),
        )
        flight = JourneyLeg.objects.create(
            journey=self.mixed,
            position=0,
            mode=JourneyLeg.Mode.FLIGHT,
            origin=self.paris,
            destination=self.algiers,
            depart_at=self.depart,
            arrive_at=self.depart + timedelta(hours=3),
            capacity_kg=Decimal("10.00"),
            flight_number="AH1006",
            route_polyline="private-flight-waypoints",
            route_metadata={"provider_response": "private"},
        )
        JourneyLeg.objects.create(
            journey=self.mixed,
            position=1,
            mode=JourneyLeg.Mode.DRIVE,
            origin=self.algiers,
            destination=self.jijel,
            depart_at=self.depart + timedelta(hours=5),
            capacity_kg=Decimal("4.00"),
        )
        JourneyLegProof.objects.create(
            leg=flight,
            bucket="private-proof",
            object_key="journeys/search/private-ticket.jpg",
            status=JourneyLegProof.Status.APPROVED,
            reviewer=self.searcher,
            reviewed_at=timezone.now(),
        )

        self.drive = Journey.objects.create(
            traveler=self.drive_owner,
            start_location=self.paris,
            destination_location=self.jijel,
            status=Journey.Status.ACTIVE,
            published_at=timezone.now(),
        )
        JourneyLeg.objects.create(
            journey=self.drive,
            position=0,
            mode=JourneyLeg.Mode.DRIVE,
            origin=self.paris,
            destination=self.jijel,
            depart_at=self.depart + timedelta(days=2),
            capacity_kg=Decimal("20.00"),
        )

        own = Journey.objects.create(
            traveler=self.searcher,
            start_location=self.paris,
            destination_location=self.jijel,
            status=Journey.Status.ACTIVE,
            published_at=timezone.now(),
        )
        JourneyLeg.objects.create(
            journey=own,
            position=0,
            mode=JourneyLeg.Mode.DRIVE,
            origin=self.paris,
            destination=self.jijel,
            depart_at=self.depart + timedelta(days=1),
            capacity_kg=Decimal("30.00"),
        )

    def _search(self, **params):
        return self.client.get(reverse("journeys-search"), params)

    def test_search_returns_active_non_owned_journeys_in_departure_order(self):
        response = self._search()

        assert response.status_code == 200
        assert [row["id"] for row in response.data] == [
            self.mixed.pk,
            self.drive.pk,
        ]

    def test_search_filters_endpoints_and_mode(self):
        response = self._search(
            start_location_id=self.paris.pk,
            destination_location_id=self.jijel.pk,
            mode=JourneyLeg.Mode.FLIGHT,
        )

        assert response.status_code == 200
        assert [row["id"] for row in response.data] == [self.mixed.pk]

    def test_min_capacity_must_be_available_on_every_leg(self):
        response = self._search(min_capacity_kg="5.00")

        assert response.status_code == 200
        assert [row["id"] for row in response.data] == [self.drive.pk]

    def test_departure_after_uses_first_leg_departure(self):
        response = self._search(
            departure_after=(self.depart + timedelta(days=1)).isoformat()
        )

        assert response.status_code == 200
        assert [row["id"] for row in response.data] == [self.drive.pk]

    def test_search_rejects_unknown_mode(self):
        response = self._search(mode="TRAIN")

        assert response.status_code == 400
        assert "mode" in response.data

    def test_search_requires_authentication(self):
        response = APIClient().get(reverse("journeys-search"))

        assert response.status_code in {401, 403}

    def test_search_redacts_exact_route_and_proof_storage(self):
        response = self._search(mode=JourneyLeg.Mode.FLIGHT)

        leg = response.data[0]["legs"][0]
        assert "route_polyline" not in leg
        assert "route_metadata" not in leg
        assert "proofs" not in leg
        assert leg["has_approved_proof"] is True

    def test_expired_kyc_removes_active_journey_from_search(self):
        self.flight_kyc.status = KycSubmission.Status.EXPIRED
        self.flight_kyc.save(update_fields=["status", "updated_at"])

        response = self._search(mode=JourneyLeg.Mode.FLIGHT)

        assert response.status_code == 200
        assert response.data == []
        detail = self.client.get(
            reverse("journeys-detail", kwargs={"pk": self.mixed.pk})
        )
        assert detail.status_code == 404
