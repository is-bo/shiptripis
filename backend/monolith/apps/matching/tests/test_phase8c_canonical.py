from __future__ import annotations

from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.core.models import BusinessSettingsVersion
from apps.kyc.models import KycSubmission
from apps.locations.models import AirportLocalityMapping, Country, Location, Place
from apps.matching.compatibility import evaluate_compatibility
from apps.matching.discovery import evaluate_candidate
from apps.matching.policy import Phase2Policy
from apps.matching.pricing import calculate_pricing_quote
from apps.matching.public_contract import public_compatibility_payload
from apps.parcels.models import DeliveryRequest, ParcelRequest
from apps.parcels.serializers import ParcelRequestSerializer
from apps.routing.geometry import GeoPoint, haversine_meters
from apps.trips.models import Airport, Journey, JourneyLeg, JourneyLegProof

#: Phone test 2 (docs/WASSLA_PHONE_TEST_2_PLAN.md 1.6 and 1.7), in UTC. Request 1
#: is ready from 24 Nov 21:18 to 30 Nov 21:18, with the same deadline; journey
#: 11 flies ALG -> CDG, leaving 26 Nov 21:37 and arriving 27 Nov 21:37. The
#: clock stands on the evening the request was posted, before the flight, as
#: when the lead evaluated the pair.
INCIDENT_AT = datetime(2026, 11, 24, 22, 0, tzinfo=dt_timezone.utc)
INCIDENT_READY_START = datetime(2026, 11, 24, 21, 18, tzinfo=dt_timezone.utc)
INCIDENT_READY_END = datetime(2026, 11, 30, 21, 18, tzinfo=dt_timezone.utc)
INCIDENT_DEADLINE = INCIDENT_READY_END
INCIDENT_DEPART = datetime(2026, 11, 26, 21, 37, tzinfo=dt_timezone.utc)
INCIDENT_ARRIVE = datetime(2026, 11, 27, 21, 37, tzinfo=dt_timezone.utc)

#: The gates that speak about dates. A route-stop refusal names none of them.
DATE_GATES = (
    "route_time_order_feasible",
    "pickup_within_ready_window",
    "delivery_before_deadline",
)


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
        # M1: the twin Paris is no stop of this journey, which is a missing
        # pickup stop, not an order failure.
        self.assertEqual(
            close_but_different.rejection_codes, ("pickup_stop_on_route",)
        )

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

    # -- M1: route-stop reasons, on the phone test 2 dates ------------------

    def _incident_request(
        self,
        origin: Place,
        destination: Place,
        *,
        pickup_point: Location | None = None,
        delivery_point: Location | None = None,
        **windows,
    ):
        """Request 1's window and deadline, between ``origin`` and ``destination``."""

        request = self._request(
            origin,
            destination,
            pickup_point=pickup_point,
            delivery_point=delivery_point,
        )
        request.ready_window_start = windows.get("ready_start", INCIDENT_READY_START)
        request.ready_window_end = windows.get("ready_end", INCIDENT_READY_END)
        request.deadline_at = windows.get("deadline", INCIDENT_DEADLINE)
        request.save(
            update_fields=["ready_window_start", "ready_window_end", "deadline_at"]
        )
        return request

    def _incident_journey(self, *legs) -> tuple[Journey, list[JourneyLeg]]:
        """A published journey over ``(mode, origin, destination, depart, arrive)``.

        Every flight carries an approved ticket, as publication requires.
        """

        journey = Journey.objects.create(
            traveler=self.traveler,
            schema_version=2,
            start_place=legs[0][1],
            destination_place=legs[-1][2],
            status=Journey.Status.ACTIVE,
            published_at=INCIDENT_AT,
        )
        rows = []
        for position, (mode, origin, destination, depart, arrive) in enumerate(legs):
            flight = mode == JourneyLeg.Mode.FLIGHT
            leg = JourneyLeg.objects.create(
                journey=journey,
                position=position,
                mode=mode,
                origin_place=origin,
                destination_place=destination,
                depart_at=depart,
                arrive_at=arrive,
                capacity_kg=Decimal("8.00"),
                flight_number="AH1000" if flight else "",
                distance_meters=None if flight else 320_000,
                route_provider="" if flight else "catalogue_snapshot",
            )
            if flight:
                JourneyLegProof.objects.create(
                    leg=leg,
                    bucket="private",
                    object_key=f"phase8c/m1-{journey.pk}-{position}.jpg",
                    status=JourneyLegProof.Status.APPROVED,
                    reviewer=self.sender,
                    reviewed_at=INCIDENT_AT,
                )
            rows.append(leg)
        return journey, rows

    def _flight(self, origin: Place, destination: Place, depart=None, arrive=None):
        return (
            JourneyLeg.Mode.FLIGHT,
            origin,
            destination,
            depart or INCIDENT_DEPART,
            arrive or INCIDENT_ARRIVE,
        )

    def _journey_11(self) -> tuple[Journey, list[JourneyLeg]]:
        """Journey 11: one flight, ALG -> CDG, on the phone test dates."""

        return self._incident_journey(self._flight(self.alg, self.cdg))

    def _at_incident(self, delivery: DeliveryRequest, journey: Journey):
        with mock.patch("django.utils.timezone.now", return_value=INCIDENT_AT):
            return evaluate_compatibility(
                delivery_request=delivery,
                journey=journey,
                policy=self.policy,
                at=INCIDENT_AT,
            )

    def _incident(self, origin: Place, destination: Place, journey, **windows):
        """Evaluate ``origin`` -> ``destination`` on request 1's dates."""

        return self._at_incident(
            self._incident_request(origin, destination, **windows), journey
        )

    @staticmethod
    def _gates(result) -> dict[str, bool]:
        return {row["code"]: row["passed"] for row in result.checks}

    def test_incident_jijel_to_paris_on_the_alg_cdg_flight_is_a_missing_pickup_stop(
        self,
    ):
        journey, _ = self._journey_11()

        result = self._incident(self.jijel, self.paris, journey)

        self.assertFalse(result.compatible)
        self.assertEqual(result.rejection_codes, ("pickup_stop_on_route",))
        gates = self._gates(result)
        self.assertFalse(gates["pickup_stop_on_route"])
        self.assertTrue(gates["delivery_stop_on_route"])
        # Nothing is said about order or dates: those gates never ran.
        for code in ("pickup_before_delivery", *DATE_GATES):
            self.assertNotIn(code, gates)
        self.assertEqual(result.covered_legs, ())
        self.assertIsNone(result.pickup_at)
        public = public_compatibility_payload(result.as_dict())
        self.assertEqual(public["rejection_codes"], ["pickup_stop_on_route"])
        self.assertNotIn("checks", public)

    def test_incident_algiers_to_paris_on_the_same_dates_is_compatible(self):
        journey, (flight,) = self._journey_11()
        request = self._incident_request(self.algiers, self.paris)

        result = self._at_incident(request, journey)

        self.assertTrue(result.compatible, result.rejection_codes)
        self.assertEqual(result.covered_legs, (flight,))
        self.assertEqual((result.pickup_position, result.delivery_position), (0, 1))
        self.assertEqual(result.pickup_at, INCIDENT_DEPART)
        self.assertEqual(result.delivery_at, INCIDENT_ARRIVE)
        gates = self._gates(result)
        for code in (
            "pickup_stop_on_route",
            "delivery_stop_on_route",
            "pickup_before_delivery",
            *DATE_GATES,
        ):
            self.assertTrue(gates[code], code)

        # Price inputs are the flight's own: its great-circle length and its
        # arrival, with nothing added.
        flight_meters = haversine_meters(
            GeoPoint(float(self.alg.latitude), float(self.alg.longitude)),
            GeoPoint(float(self.cdg.latitude), float(self.cdg.longitude)),
        )
        method = "great_circle_trusted_coordinates"
        self.assertEqual(result.matched_distance_meters, flight_meters)
        self.assertEqual(result.matched_distance_method, method)
        self.assertEqual(result.added_distance_meters, 0)
        with mock.patch("django.utils.timezone.now", return_value=INCIDENT_AT):
            evaluation = evaluate_candidate(
                delivery_request=request,
                journey=journey,
                policy=self.policy,
                at=INCIDENT_AT,
            )
            expected = calculate_pricing_quote(
                delivery_request=request,
                matched_distance_meters=flight_meters,
                matched_distance_method=method,
                added_distance_meters=0,
                estimated_arrival_at=INCIDENT_ARRIVE,
                policy=self.policy,
            )
        self.assertEqual(evaluation.pricing.as_dict(), expected.as_dict())

    def test_a_missing_drop_off_stop_has_its_own_reason(self):
        journey, _ = self._journey_11()

        result = self._incident(self.algiers, self.madrid, journey)

        self.assertEqual(result.rejection_codes, ("delivery_stop_on_route",))
        gates = self._gates(result)
        self.assertTrue(gates["pickup_stop_on_route"])
        self.assertNotIn("pickup_before_delivery", gates)

    def test_both_stops_missing_report_both_reasons_and_no_order(self):
        journey, _ = self._journey_11()

        result = self._incident(self.jijel, self.madrid, journey)

        self.assertEqual(
            result.rejection_codes, ("pickup_stop_on_route", "delivery_stop_on_route")
        )
        self.assertNotIn("pickup_before_delivery", self._gates(result))

    def test_a_reversed_route_is_the_only_order_failure(self):
        journey, _ = self._journey_11()

        result = self._incident(self.paris, self.algiers, journey)

        self.assertFalse(result.compatible)
        self.assertEqual(result.rejection_codes, ("pickup_before_delivery",))
        gates = self._gates(result)
        self.assertTrue(gates["pickup_stop_on_route"])
        self.assertTrue(gates["delivery_stop_on_route"])
        # Staff see which stops were found; a party sees only the code.
        order = next(
            row for row in result.checks if row["code"] == "pickup_before_delivery"
        )
        self.assertEqual(
            order["details"], {"pickup_positions": [1.0], "delivery_positions": [0.0]}
        )
        public = public_compatibility_payload(result.as_dict())
        self.assertEqual(public["rejection_codes"], ["pickup_before_delivery"])
        self.assertNotIn("checks", public)
        self.assertNotIn("pickup_route_position", public)

    def test_an_unresolved_airport_is_a_catalogue_failure_not_a_missing_stop(self):
        # An airport with no active primary served locality.
        oran_airport = Place.objects.create(
            country=self.countries["DZ"],
            place_type=Place.PlaceType.AIRPORT,
            source="phase8c-test",
            source_id="airport-ORN",
            source_version="phase8c",
            name="Oran Es Senia",
            latitude=Decimal("35.6239"),
            longitude=Decimal("-0.6212"),
            iata_code="ORN",
            passenger_use=True,
        )
        journey, _ = self._journey_11()

        result = self._incident(oran_airport, self.paris, journey)

        self.assertEqual(result.rejection_codes, ("canonical_geography_complete",))
        gates = self._gates(result)
        for code in (
            "pickup_stop_on_route",
            "delivery_stop_on_route",
            "pickup_before_delivery",
        ):
            self.assertNotIn(code, gates)

        # The same airport on the journey's side breaks the leg sequence first.
        unresolved, _ = self._incident_journey(self._flight(oran_airport, self.cdg))
        result = self._incident(self.algiers, self.paris, unresolved)
        self.assertEqual(result.rejection_codes, ("journey_leg_sequence",))

    def _legacy_airport(self, place: Place) -> Location:
        return Location.objects.create(
            kind=Location.Kind.AIRPORT,
            normalized_label=f"{place.iata_code} airport",
            public_label=place.name,
            private_label=f"{place.iata_code} airport",
            city=place.name,
            country_code=place.country_id,
            latitude=place.latitude,
            longitude=place.longitude,
            coarse_latitude=place.latitude.quantize(Decimal("0.1")),
            coarse_longitude=place.longitude.quantize(Decimal("0.1")),
            coordinates_trusted=True,
            coordinate_dataset_version="airports-2026-01",
            airport=Airport.objects.get(pk=place.iata_code),
        )

    def _legacy_journey_11(self) -> Journey:
        """Journey 11 written the schema-1 way: Location rows, no catalogue."""

        alg, cdg = self._legacy_airport(self.alg), self._legacy_airport(self.cdg)
        journey = Journey.objects.create(
            traveler=self.traveler,
            start_location=alg,
            destination_location=cdg,
            status=Journey.Status.ACTIVE,
            published_at=INCIDENT_AT,
        )
        flight = JourneyLeg.objects.create(
            journey=journey,
            position=0,
            mode=JourneyLeg.Mode.FLIGHT,
            origin=alg,
            destination=cdg,
            depart_at=INCIDENT_DEPART,
            arrive_at=INCIDENT_ARRIVE,
            capacity_kg=Decimal("8.00"),
            flight_number="AH1000",
        )
        JourneyLegProof.objects.create(
            leg=flight,
            bucket="private",
            object_key=f"phase8c/m1-legacy-{journey.pk}.jpg",
            status=JourneyLegProof.Status.APPROVED,
            reviewer=self.sender,
            reviewed_at=INCIDENT_AT,
        )
        return journey

    def _quote_at_incident(self, request: DeliveryRequest, journey: Journey):
        client = APIClient()
        client.force_authenticate(user=self.sender)
        with mock.patch("django.utils.timezone.now", return_value=INCIDENT_AT):
            return client.post(
                reverse("matches-quote-v1"),
                {"parcel_id": request.pk, "journey_id": journey.pk},
                format="json",
            )

    def test_a_canonical_request_on_a_legacy_flight_is_only_a_catalogue_failure(
        self,
    ):
        # Second pass (Astra): the preferred pins must not be searched for on
        # a legacy route once the catalogue check has failed.
        pickup_pin = self._preferred(self.algiers, "Pickup pin", "36.7538", "3.0588")
        dropoff_pin = self._preferred(self.paris, "Drop-off pin", "48.8566", "2.3522")
        request = self._incident_request(
            self.algiers,
            self.paris,
            pickup_point=pickup_pin,
            delivery_point=dropoff_pin,
        )
        self.assertIsNotNone(request.pickup_location_id)
        self.assertIsNotNone(request.delivery_location_id)
        journey = self._legacy_journey_11()
        self.assertEqual(journey.schema_version, 1)

        result = self._at_incident(request, journey)
        response = self._quote_at_incident(request, journey)

        self.assertEqual(result.rejection_codes, ("canonical_geography_complete",))
        gates = self._gates(result)
        for code in (
            "pickup_stop_on_route",
            "delivery_stop_on_route",
            "pickup_before_delivery",
        ):
            self.assertNotIn(code, gates)
        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(response.data["code"], "incompatible_candidate")
        self.assertEqual(
            response.data["rejection_codes"], ["canonical_geography_complete"]
        )
        self.assertEqual(
            response.data["compatibility"]["rejection_codes"],
            ["canonical_geography_complete"],
        )

    def test_a_retired_airport_mapping_is_only_a_catalogue_failure(self):
        drive, _ = self._incident_journey(
            (
                JourneyLeg.Mode.DRIVE,
                self.algiers,
                self.jijel,
                INCIDENT_DEPART,
                INCIDENT_DEPART + timedelta(hours=5),
            )
        )
        pickup_pin = self._preferred(self.alg, "Pickup pin", "36.6910", "3.2154")
        dropoff_pin = self._preferred(self.jijel, "Drop-off pin", "36.8206", "5.7667")
        request = self._incident_request(
            self.alg, self.jijel, pickup_point=pickup_pin, delivery_point=dropoff_pin
        )
        # While ALG serves Algiers, the request rides the Algiers -> Jijel drive.
        before = self._at_incident(request, drive)
        self.assertTrue(before.compatible, before.rejection_codes)

        # The mapping is retired after posting.
        AirportLocalityMapping.objects.filter(airport=self.alg).update(active=False)
        legacy = self._legacy_journey_11()
        for journey in (drive, legacy):
            with self.subTest(schema_version=journey.schema_version):
                request.refresh_from_db()
                result = self._at_incident(request, journey)
                self.assertEqual(
                    result.rejection_codes, ("canonical_geography_complete",)
                )
                gates = self._gates(result)
                self.assertNotIn("pickup_stop_on_route", gates)
                self.assertNotIn("delivery_stop_on_route", gates)

    def test_genuine_window_and_deadline_failures_stay_distinct(self):
        journey, _ = self._journey_11()
        one_minute = timedelta(minutes=1)

        early = self._incident(
            self.algiers, self.paris, journey, ready_end=INCIDENT_DEPART - one_minute
        )
        # A deadline may not precede the ready-window end, so both move.
        missed = INCIDENT_ARRIVE - one_minute
        late = self._incident(
            self.algiers, self.paris, journey, ready_end=missed, deadline=missed
        )

        self.assertEqual(early.rejection_codes, ("pickup_within_ready_window",))
        self.assertEqual(late.rejection_codes, ("delivery_before_deadline",))
        for result in (early, late):
            gates = self._gates(result)
            self.assertTrue(gates["pickup_stop_on_route"])
            self.assertTrue(gates["delivery_stop_on_route"])
            self.assertTrue(gates["pickup_before_delivery"])

    def test_a_real_jijel_algiers_paris_journey_covers_both_legs(self):
        drive_depart = INCIDENT_DEPART - timedelta(hours=8)
        journey, (drive, flight) = self._incident_journey(
            (
                JourneyLeg.Mode.DRIVE,
                self.jijel,
                self.algiers,
                drive_depart,
                INCIDENT_DEPART - timedelta(hours=3),
            ),
            self._flight(self.alg, self.cdg),
        )

        result = self._incident(self.jijel, self.paris, journey)

        self.assertTrue(result.compatible, result.rejection_codes)
        self.assertEqual(result.covered_legs, (drive, flight))
        self.assertEqual((result.pickup_position, result.delivery_position), (0, 2))
        self.assertEqual(result.pickup_at, drive_depart)
        self.assertEqual(result.delivery_at, INCIDENT_ARRIVE)

    def test_repeated_stops_keep_alternate_pair_selection(self):
        # ALG -> CDG -> ALG -> CDG: Algiers is stops 0 and 2, Paris 1 and 3.
        out_at = INCIDENT_AT + timedelta(hours=10)
        back_at = INCIDENT_AT + timedelta(hours=16)
        journey, (out, home, again) = self._incident_journey(
            self._flight(self.alg, self.cdg, out_at, out_at + timedelta(hours=3)),
            self._flight(self.cdg, self.alg, back_at, back_at + timedelta(hours=3)),
            self._flight(self.alg, self.cdg),
        )

        # The shortest pair wins when its timing fits.
        first = self._incident(self.algiers, self.paris, journey)
        self.assertTrue(first.compatible, first.rejection_codes)
        self.assertEqual(first.covered_legs, (out,))

        # When it does not, the evaluator falls through to the later Algiers
        # stop instead of reporting a missing stop or a bad order.
        later = self._incident(
            self.algiers,
            self.paris,
            journey,
            ready_start=INCIDENT_DEPART - timedelta(hours=1),
        )
        self.assertTrue(later.compatible, later.rejection_codes)
        self.assertEqual(later.covered_legs, (again,))
        self.assertEqual((later.pickup_position, later.delivery_position), (2, 3))
        self.assertTrue(self._gates(later)["pickup_stop_on_route"])

        # The way back is a real stop pair too: Paris (1) before Algiers (2).
        homeward = self._incident(self.paris, self.algiers, journey)
        self.assertTrue(homeward.compatible, homeward.rejection_codes)
        self.assertEqual(homeward.covered_legs, (home,))
