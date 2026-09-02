from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.core.models import BusinessSettingsVersion
from apps.kyc.models import KycSubmission
from apps.locations.models import AirportLocalityMapping, Country, Location, Place
from apps.matching.compatibility import evaluate_compatibility
from apps.matching.policy import Phase2Policy
from apps.parcels.models import DeliveryRequest, ParcelRequest
from apps.parcels.serializers import ParcelRequestSerializer
from apps.trips.models import Journey, JourneyLeg, JourneyLegProof


class CanonicalLocalityMatchingTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.sender = self._user("phase8c-sender@example.com")
        self.traveler = self._user("phase8c-traveler@example.com")
        KycSubmission.objects.create(
            user=self.traveler,
            document_type=KycSubmission.DocumentType.PASSPORT,
            idempotency_key="phase8c-traveler-kyc-000000001",
            front_image_key="kyc/phase8c/front.jpg",
            status=KycSubmission.Status.APPROVED,
            reviewed_at=self.now,
        )
        self.policy = Phase2Policy.from_settings(
            BusinessSettingsVersion.objects.get(
                status=BusinessSettingsVersion.Status.ACTIVE
            )
        )

        self.countries = {
            code: Country.objects.create(
                code=code,
                name=name,
                source="phase8c-test",
                source_id=f"country-{code}",
                source_version="phase8c",
            )
            for code, name in (
                ("DZ", "Algeria"),
                ("FR", "France"),
                ("ES", "Spain"),
                ("DE", "Germany"),
            )
        }
        self.paris = self._locality("FR", "Paris", 48.8566, 2.3522)
        self.paris_same_name = self._locality(
            "FR", "Paris", 48.8567, 2.3523, suffix="other-id"
        )
        self.algiers = self._locality("DZ", "Algiers", 36.7538, 3.0588)
        self.jijel = self._locality("DZ", "Jijel", 36.8206, 5.7667)
        self.madrid = self._locality("ES", "Madrid", 40.4168, -3.7038)
        self.frankfurt = self._locality("DE", "Frankfurt", 50.1109, 8.6821)

        self.cdg = self._airport(
            "FR", "Paris Charles de Gaulle", "CDG", 49.0097, 2.5479, self.paris
        )
        self.alg = self._airport(
            "DZ", "Houari Boumediene", "ALG", 36.6910, 3.2154, self.algiers
        )
        self.mad = self._airport(
            "ES", "Adolfo Suárez Madrid-Barajas", "MAD", 40.4983, -3.5676, self.madrid
        )
        self.fra = self._airport(
            "DE", "Frankfurt Airport", "FRA", 50.0379, 8.5622, self.frankfurt
        )

    @staticmethod
    def _user(email: str) -> User:
        return User.objects.create_user(
            username=email,
            email=email,
            password="Sup3rStrongPass!",
            full_name=email.split("@")[0],
        )

    def _locality(
        self,
        country_code: str,
        name: str,
        latitude: float,
        longitude: float,
        *,
        suffix: str = "main",
    ) -> Place:
        return Place.objects.create(
            country=self.countries[country_code],
            place_type=Place.PlaceType.LOCALITY,
            source="phase8c-test",
            source_id=f"locality-{country_code}-{name}-{suffix}",
            source_version="phase8c",
            name=name,
            latitude=Decimal(str(latitude)),
            longitude=Decimal(str(longitude)),
        )

    def _airport(
        self,
        country_code: str,
        name: str,
        iata: str,
        latitude: float,
        longitude: float,
        locality: Place,
    ) -> Place:
        airport = Place.objects.create(
            country=self.countries[country_code],
            place_type=Place.PlaceType.AIRPORT,
            source="phase8c-test",
            source_id=f"airport-{iata}",
            source_version="phase8c",
            name=name,
            latitude=Decimal(str(latitude)),
            longitude=Decimal(str(longitude)),
            iata_code=iata,
            passenger_use=True,
        )
        AirportLocalityMapping.objects.create(
            airport=airport,
            locality=locality,
            relationship_type=AirportLocalityMapping.RelationshipType.SERVED,
            is_primary=True,
            source="phase8c-test",
            source_id=f"mapping-{iata}",
            source_version="phase8c",
        )
        return airport

    def _preferred(
        self, place: Place, label: str, latitude: str, longitude: str
    ) -> Location:
        return Location.objects.create(
            kind=Location.Kind.MAP_POINT,
            normalized_label=label,
            public_label=f"{place.name}, {place.country_id}",
            private_label=label,
            city=place.name,
            country_code=place.country_id,
            latitude=Decimal(latitude),
            longitude=Decimal(longitude),
            coarse_latitude=Decimal(latitude).quantize(Decimal("0.1")),
            coarse_longitude=Decimal(longitude).quantize(Decimal("0.1")),
            canonical_place=place,
            owner=self.sender,
            created_by=self.sender,
        )

    def _request(
        self,
        origin: Place,
        destination: Place,
        *,
        pickup_point: Location | None = None,
        delivery_point: Location | None = None,
    ) -> DeliveryRequest:
        depart = self.now + timedelta(days=2)
        return DeliveryRequest.objects.create(
            sender=self.sender,
            kind=ParcelRequest.Kind.DELIVERY,
            schema_version=3,
            pickup_place=origin,
            delivery_place=destination,
            pickup_location=pickup_point,
            delivery_location=delivery_point,
            ready_window_start=depart - timedelta(hours=1),
            ready_window_end=depart + timedelta(hours=1),
            deadline_at=depart + timedelta(hours=16),
            actual_weight_kg=Decimal("2.00"),
            length_cm=Decimal("20.00"),
            width_cm=Decimal("15.00"),
            height_cm=Decimal("10.00"),
            declared_value_eur_cents=10_000,
            traveler_reward_eur_cents=2_000,
            title="Canonical request",
            description="Sealed documents",
            category=ParcelRequest.ItemType.DOCUMENTS,
            item_type=ParcelRequest.ItemType.DOCUMENTS,
            description_is_accurate=True,
            item_is_legal=True,
            no_prohibited_goods=True,
            declared_value_is_accurate=True,
            customs_responsibilities_understood=True,
            base_amount_dzd=None,
        )

    def _drive_journey(self, origin: Place, destination: Place) -> Journey:
        depart = self.now + timedelta(days=2)
        journey = Journey.objects.create(
            traveler=self.traveler,
            schema_version=2,
            start_place=origin,
            destination_place=destination,
            status=Journey.Status.ACTIVE,
            published_at=self.now,
        )
        JourneyLeg.objects.create(
            journey=journey,
            position=0,
            mode=JourneyLeg.Mode.DRIVE,
            origin_place=origin,
            destination_place=destination,
            depart_at=depart,
            arrive_at=depart + timedelta(hours=7),
            capacity_kg=Decimal("8.00"),
            distance_meters=500_000,
            route_provider="catalogue_snapshot",
        )
        return journey

    def _evaluate(self, delivery: DeliveryRequest, journey: Journey):
        return evaluate_compatibility(
            delivery_request=delivery,
            journey=journey,
            policy=self.policy,
            at=self.now,
        )

    def test_canonical_locality_identity_matches_and_different_ids_do_not(self):
        journey = self._drive_journey(self.paris, self.jijel)

        same = self._evaluate(self._request(self.paris, self.jijel), journey)
        close_but_different = self._evaluate(
            self._request(self.paris_same_name, self.jijel), journey
        )

        self.assertTrue(same.compatible, same.rejection_codes)
        self.assertFalse(close_but_different.compatible)
        self.assertIn("pickup_before_delivery", close_but_different.rejection_codes)

    def test_preferred_coordinates_do_not_change_compatibility(self):
        first = self._preferred(self.paris, "University gate", "48.856600", "2.352200")
        second = self._preferred(
            self.paris, "Station entrance", "48.996600", "2.492200"
        )
        delivery_point = self._preferred(
            self.jijel, "Town centre", "36.820600", "5.766700"
        )
        request = self._request(
            self.paris,
            self.jijel,
            pickup_point=first,
            delivery_point=delivery_point,
        )
        journey = self._drive_journey(self.paris, self.jijel)

        before = self._evaluate(request, journey)
        request.pickup_location = second
        request.save(update_fields=["pickup_location", "updated_at"])
        after = self._evaluate(request, journey)

        self.assertTrue(before.compatible, before.rejection_codes)
        self.assertTrue(after.compatible, after.rejection_codes)
        self.assertEqual(before.pickup_position, after.pickup_position)
        self.assertEqual(before.delivery_position, after.delivery_position)
        self.assertEqual(before.added_distance_meters, 0)
        self.assertEqual(after.added_distance_meters, 0)

    def test_all_four_representative_airports_resolve_only_to_explicit_served_locality(
        self,
    ):
        for airport, locality in (
            (self.alg, self.algiers),
            (self.cdg, self.paris),
            (self.mad, self.madrid),
            (self.fra, self.frankfurt),
        ):
            with self.subTest(iata=airport.iata_code):
                self.assertEqual(airport.resolve_matching_locality(), locality)

    def test_retired_locality_fails_closed_for_matching(self):
        request = self._request(self.paris, self.jijel)
        journey = self._drive_journey(self.paris, self.jijel)
        self.jijel.active = False
        self.jijel.save(update_fields=["active", "updated_at"])

        request.refresh_from_db()
        journey.refresh_from_db()
        self.assertIsNone(request.delivery_place.resolve_matching_locality())
        result = self._evaluate(request, journey)
        self.assertFalse(result.compatible)
        self.assertIn("canonical_geography_complete", result.rejection_codes)

    def test_paris_cdg_and_ordered_multileg_subroute_match(self):
        depart = self.now + timedelta(days=2)
        journey = Journey.objects.create(
            traveler=self.traveler,
            schema_version=2,
            start_place=self.cdg,
            destination_place=self.jijel,
            status=Journey.Status.ACTIVE,
            published_at=self.now,
        )
        flight = JourneyLeg.objects.create(
            journey=journey,
            position=0,
            mode=JourneyLeg.Mode.FLIGHT,
            origin_place=self.cdg,
            destination_place=self.alg,
            depart_at=depart,
            arrive_at=depart + timedelta(hours=3),
            capacity_kg=Decimal("8.00"),
            flight_number="AF1354",
        )
        drive = JourneyLeg.objects.create(
            journey=journey,
            position=1,
            mode=JourneyLeg.Mode.DRIVE,
            origin_place=self.algiers,
            destination_place=self.jijel,
            depart_at=depart + timedelta(hours=4),
            arrive_at=depart + timedelta(hours=9),
            capacity_kg=Decimal("8.00"),
            distance_meters=320_000,
            route_provider="catalogue_snapshot",
        )
        JourneyLegProof.objects.create(
            leg=flight,
            bucket="private",
            object_key="phase8c/cdg-alg-ticket.jpg",
            status=JourneyLegProof.Status.APPROVED,
            reviewer=self.sender,
            reviewed_at=self.now,
        )

        result = self._evaluate(self._request(self.paris, self.jijel), journey)

        self.assertTrue(result.compatible, result.rejection_codes)
        self.assertEqual(result.covered_legs, (flight, drive))
        self.assertEqual(result.pickup_position, 0)
        self.assertEqual(result.delivery_position, 2)

    def test_exact_preferred_points_remain_private_before_funding(self):
        pickup = self._preferred(
            self.paris, "Private pickup address", "48.856600", "2.352200"
        )
        dropoff = self._preferred(
            self.jijel, "Private dropoff address", "36.820600", "5.766700"
        )
        delivery = self._request(
            self.paris,
            self.jijel,
            pickup_point=pickup,
            delivery_point=dropoff,
        )
        request = SimpleNamespace(user=self.traveler)

        data = ParcelRequestSerializer(delivery, context={"request": request}).data

        self.assertEqual(data["pickup_place"]["id"], self.paris.pk)
        self.assertEqual(data["pickup_location"]["public_label"], "Paris, FR")
        self.assertNotIn("private_label", data["pickup_location"])
        self.assertNotIn("latitude", data["pickup_location"])
        self.assertNotIn("provider_metadata", data["pickup_location"])
