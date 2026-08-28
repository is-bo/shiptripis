from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
import json
from types import SimpleNamespace
from unittest.mock import patch

from django.core.cache import cache
from django.db.models import Sum
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.core.models import BusinessSettingsVersion
from apps.deals.models import Deal, DealLegAllocation
from apps.kyc.models import KycSubmission
from apps.locations.models import Location
from apps.matching import compatibility as compatibility_module
from apps.matching.compatibility import evaluate_compatibility
from apps.matching.discovery import compatible_requests_for_journey
from apps.matching.policy import Phase2Policy
from apps.matching.pricing import PricingError, calculate_pricing_quote
from apps.matching.ranking import rank_compatible_candidate
from apps.matching.v1_services import CapacityExceeded, accept_offer, create_sender_offer
from apps.parcels.models import DeliveryRequest, ParcelRequest
from apps.routing.geometry import GeoPoint, haversine_meters
from apps.routing.providers import RouteResult, UnavailableRouteProvider
from apps.routing.testing import DeterministicFixtureRouteProvider
from apps.trips.models import Airport, Journey, JourneyLeg, JourneyLegProof
from apps.trips.serializers import JourneyCreateSerializer, JourneyLegSerializer


class _KnownDurationDetourProvider:
    name = "known_duration_fixture"

    def directions(self, points, *, profile):
        distance = sum(
            haversine_meters(first, second)
            for first, second in zip(points, points[1:], strict=False)
        )
        return RouteResult(
            distance_meters=distance,
            duration_seconds=1_400 if len(points) > 2 else 1_000,
            polyline="fixture-polyline",
            corridor_points=tuple(points),
            provider=self.name,
            profile=profile,
            metadata={"fixture": "known-duration"},
        )


class _PrefixAwareDropoffProvider:
    name = "prefix_aware_dropoff_fixture"

    def __init__(self, *, destination: GeoPoint, dropoff: GeoPoint) -> None:
        self.destination = destination
        self.dropoff = dropoff

    def directions(self, points, *, profile):
        distance = sum(
            haversine_meters(first, second)
            for first, second in zip(points, points[1:], strict=False)
        )
        if len(points) > 2:
            duration = 1_500
        elif points[-1] == self.destination:
            duration = 1_000
        elif points[-1] == self.dropoff:
            duration = 800
        else:
            duration = 600
        return RouteResult(
            distance_meters=distance,
            duration_seconds=duration,
            polyline="fixture-polyline",
            corridor_points=tuple(points),
            provider=self.name,
            profile=profile,
            metadata={"fixture": "prefix-aware-dropoff"},
        )


def _user(email: str, *, is_staff: bool = False) -> User:
    return User.objects.create_user(
        username=email,
        email=email,
        password="Sup3rStrongPass!",
        full_name=email.split("@")[0],
        is_staff=is_staff,
    )


def _location(
    label: str,
    latitude: str,
    longitude: str,
    *,
    owner: User | None = None,
    airport: bool = False,
    airport_record: Airport | None = None,
    country_code: str = "DZ",
) -> Location:
    return Location.objects.create(
        kind=Location.Kind.AIRPORT if airport else Location.Kind.MAP_POINT,
        normalized_label=f"SECRET normalized {label}",
        public_label=label,
        private_label=f"SECRET private address {label}",
        city=label,
        country_code=country_code,
        latitude=Decimal(latitude),
        longitude=Decimal(longitude),
        coarse_latitude=Decimal(latitude).quantize(Decimal("0.1")),
        coarse_longitude=Decimal(longitude).quantize(Decimal("0.1")),
        provider="fixture-provider",
        provider_place_id=f"SECRET-place-{label}",
        provider_metadata={"formatted_address": f"SECRET provider address {label}"},
        coordinates_trusted=airport,
        coordinate_dataset_version="airports-2026-01" if airport else "",
        airport=airport_record,
        owner=owner,
        created_by=owner,
    )


def _approve_kyc(user: User, suffix: str) -> None:
    KycSubmission.objects.create(
        user=user,
        document_type=KycSubmission.DocumentType.PASSPORT,
        idempotency_key=f"{suffix:0<32}"[:32],
        front_image_key=f"kyc/{suffix}/front.jpg",
        status=KycSubmission.Status.APPROVED,
        reviewed_at=timezone.now(),
    )


def _request(
    *,
    sender: User,
    pickup: Location,
    delivery: Location,
    ready_start,
    ready_end,
    deadline,
    weight: str = "1.00",
    dimensions: tuple[str, str, str] | None = ("10", "10", "10"),
) -> DeliveryRequest:
    dimension_values = dimensions or (None, None, None)
    return DeliveryRequest.objects.create(
        sender=sender,
        kind=ParcelRequest.Kind.DELIVERY,
        schema_version=2,
        pickup_location=pickup,
        delivery_location=delivery,
        ready_window_start=ready_start,
        ready_window_end=ready_end,
        deadline_at=deadline,
        actual_weight_kg=Decimal(weight),
        length_cm=dimension_values[0],
        width_cm=dimension_values[1],
        height_cm=dimension_values[2],
        declared_value_eur_cents=10_000,
        traveler_reward_eur_cents=2_000,
        title="Phase 2 parcel",
        description="Safe test parcel",
        category=ParcelRequest.ItemType.DOCUMENTS,
        item_type=ParcelRequest.ItemType.DOCUMENTS,
        description_is_accurate=True,
        item_is_legal=True,
        no_prohibited_goods=True,
        declared_value_is_accurate=True,
        customs_responsibilities_understood=True,
    )


def _phase2_policy() -> Phase2Policy:
    return Phase2Policy.from_settings(
        BusinessSettingsVersion.objects.get(version=2)
    )


class Phase2PricingTests(TestCase):
    def setUp(self):
        self.sender = _user("phase2-pricing@example.com")
        self.pickup = _location("Pricing pickup", "36.752500", "3.041970")
        self.delivery = _location("Pricing delivery", "36.365000", "6.614700")
        self.now = timezone.now()
        self.policy = _phase2_policy()

    def _quote(
        self,
        *,
        weight: str,
        distance: int,
        dimensions: tuple[str, str, str] | None = ("10", "10", "10"),
        detour: int = 0,
        slack: timedelta = timedelta(days=7),
    ):
        arrival = self.now + timedelta(days=1)
        delivery_request = _request(
            sender=self.sender,
            pickup=self.pickup,
            delivery=self.delivery,
            ready_start=self.now,
            ready_end=self.now + timedelta(days=1),
            deadline=arrival + slack,
            weight=weight,
            dimensions=dimensions,
        )
        return calculate_pricing_quote(
            delivery_request=delivery_request,
            matched_distance_meters=distance,
            matched_distance_method="test",
            added_distance_meters=detour,
            estimated_arrival_at=arrival,
            policy=self.policy,
        )

    def test_volumetric_weight_detour_urgency_and_rounding_are_decimal_exact(self):
        quote = self._quote(
            weight="1.10",
            dimensions=("50", "40", "30"),
            distance=100_000,
            detour=10_001,
            slack=timedelta(days=2),
        )

        assert quote.volumetric_weight_kg == Decimal("12.000")
        assert quote.chargeable_weight_kg == Decimal("12.000")
        assert quote.distance_band_base_cents == 400
        assert quote.weight_component_cents == 3_000
        assert quote.minimum_reward_eur_cents == 3_400
        assert quote.detour_adjustment_cents == 251
        assert quote.urgency_adjustment_cents == 150
        assert quote.recommended_reward_eur_cents == 4_500

    def test_global_floor_weight_increment_and_distance_band_boundaries(self):
        floor_quote = self._quote(weight="0.01", distance=100_000)
        next_band_quote = self._quote(weight="1.01", distance=100_001)

        assert floor_quote.chargeable_weight_kg == Decimal("0.500")
        assert floor_quote.global_floor_applied is True
        assert floor_quote.minimum_reward_eur_cents == 700
        assert floor_quote.recommended_reward_eur_cents == 850
        assert next_band_quote.chargeable_weight_kg == Decimal("1.500")
        assert next_band_quote.distance_band_base_cents == 600
        assert next_band_quote.weight_component_cents == 375
        assert next_band_quote.minimum_reward_eur_cents == 975

    def test_quote_economics_ceil_commission_without_reducing_traveler_reward(self):
        quote = self._quote(weight="1.01", distance=100_000)
        payload = quote.as_dict()

        assert quote.minimum_reward_eur_cents == 775
        assert payload["minimum_economics"] == {
            "traveler_reward_minor": 775,
            "commission_rate_bps": 2_500,
            "platform_fee_minor": 194,
            "sender_total_minor": 969,
        }
        assert payload["recommended_economics"]["traveler_reward_minor"] == 950
        assert payload["recommended_economics"]["platform_fee_minor"] == 238
        assert payload["recommended_economics"]["sender_total_minor"] == 1_188

    def test_quote_rejects_a_request_without_complete_dimensions(self):
        arrival = self.now + timedelta(days=1)
        delivery_request = _request(
            sender=self.sender,
            pickup=self.pickup,
            delivery=self.delivery,
            ready_start=self.now,
            ready_end=self.now + timedelta(days=1),
            deadline=arrival + timedelta(days=7),
        )
        # New writes reject missing dimensions at the model boundary. Retain
        # the pricing guard for historical/corrupt rows that bypassed it.
        DeliveryRequest.objects.filter(pk=delivery_request.pk).update(
            length_cm=None,
            width_cm=None,
            height_cm=None,
        )
        delivery_request.refresh_from_db()

        with self.assertRaisesMessage(
            PricingError,
            "The delivery request has no complete dimensions.",
        ):
            calculate_pricing_quote(
                delivery_request=delivery_request,
                matched_distance_meters=100_000,
                matched_distance_method="test",
                added_distance_meters=0,
                estimated_arrival_at=arrival,
                policy=self.policy,
            )


class Phase2MatchingApiTests(TestCase):
    forbidden_location_keys = {
        "latitude",
        "longitude",
        "normalized_label",
        "private_label",
        "provider",
        "provider_place_id",
        "provider_metadata",
    }

    def setUp(self):
        self.at = timezone.now()
        self.sender = _user("phase2-api-sender@example.com")
        self.traveler = _user("phase2-api-traveler@example.com")
        self.outsider = _user("phase2-api-outsider@example.com")
        _approve_kyc(self.traveler, "phase2-api-traveler")
        self.pickup = _location(
            "API pickup",
            "36.752500",
            "3.041970",
            owner=self.sender,
        )
        self.delivery = _location(
            "API delivery",
            "36.365000",
            "6.614700",
            owner=self.sender,
        )
        self.delivery_request = _request(
            sender=self.sender,
            pickup=self.pickup,
            delivery=self.delivery,
            ready_start=self.at + timedelta(hours=1),
            ready_end=self.at + timedelta(hours=3),
            deadline=self.at + timedelta(hours=6),
        )
        self.journey = Journey.objects.create(
            traveler=self.traveler,
            start_location=self.pickup,
            destination_location=self.delivery,
            status=Journey.Status.ACTIVE,
            published_at=self.at,
        )
        self.leg = JourneyLeg.objects.create(
            journey=self.journey,
            position=0,
            mode=JourneyLeg.Mode.DRIVE,
            origin=self.pickup,
            destination=self.delivery,
            depart_at=self.at + timedelta(hours=2),
            arrive_at=self.at + timedelta(hours=5),
            capacity_kg=Decimal("20.00"),
            distance_meters=200_000,
        )

    def _client(self, user: User | None = None) -> APIClient:
        client = APIClient()
        if user is not None:
            client.force_authenticate(user=user)
        return client

    def _assert_privacy_safe(self, payload) -> None:
        def assert_keys(value) -> None:
            if isinstance(value, dict):
                assert not self.forbidden_location_keys.intersection(value)
                for nested in value.values():
                    assert_keys(nested)
            elif isinstance(value, list):
                for nested in value:
                    assert_keys(nested)

        assert_keys(payload)
        payload_text = json.dumps(payload, default=str)
        assert "SECRET normalized" not in payload_text
        assert "SECRET private address" not in payload_text
        assert "SECRET-place" not in payload_text
        assert "SECRET provider address" not in payload_text
        assert "36.752500" not in payload_text
        assert "3.041970" not in payload_text

    def test_discovery_endpoints_require_auth_and_enforce_each_owner(self):
        journeys_url = reverse("matches-compatible-journeys-v1")
        requests_url = reverse("matches-compatible-requests-v1")
        quote_url = reverse("matches-quote-v1")
        anonymous = self._client()

        responses = (
            anonymous.get(journeys_url, {"parcel_id": self.delivery_request.pk}),
            anonymous.get(requests_url, {"journey_id": self.journey.pk}),
            anonymous.post(
                quote_url,
                {
                    "parcel_id": self.delivery_request.pk,
                    "journey_id": self.journey.pk,
                },
                format="json",
            ),
        )
        assert [response.status_code for response in responses] == [401, 401, 401]

        outsider = self._client(self.outsider)
        journeys_response = outsider.get(
            journeys_url,
            {"parcel_id": self.delivery_request.pk},
        )
        requests_response = outsider.get(
            requests_url,
            {"journey_id": self.journey.pk},
        )
        quote_response = outsider.post(
            quote_url,
            {
                "parcel_id": self.delivery_request.pk,
                "journey_id": self.journey.pk,
            },
            format="json",
        )

        assert journeys_response.status_code == 403
        assert requests_response.status_code == 403
        assert quote_response.status_code == 403
        assert journeys_response.data["code"] == "not_authorized"
        assert requests_response.data["code"] == "not_authorized"
        assert quote_response.data["code"] == "not_authorized"

    def test_both_discovery_directions_return_one_coarse_privacy_safe_candidate(self):
        sender_response = self._client(self.sender).get(
            reverse("matches-compatible-journeys-v1"),
            {"parcel_id": self.delivery_request.pk},
        )
        traveler_response = self._client(self.traveler).get(
            reverse("matches-compatible-requests-v1"),
            {"journey_id": self.journey.pk},
        )

        assert sender_response.status_code == 200, sender_response.data
        assert traveler_response.status_code == 200, traveler_response.data
        assert sender_response.data["count"] == 1
        assert traveler_response.data["count"] == 1
        for response in (sender_response, traveler_response):
            candidate = response.data["results"][0]
            assert candidate["delivery_request"]["id"] == self.delivery_request.pk
            assert candidate["journey"]["id"] == self.journey.pk
            assert candidate["compatibility"]["compatible"] is True
            assert candidate["delivery_request"]["pickup"]["coarse_latitude"]
            self._assert_privacy_safe(response.data)

    def test_quote_returns_explainable_components_and_stable_incompatible_error(self):
        quote_url = reverse("matches-quote-v1")
        client = self._client(self.sender)
        response = client.post(
            quote_url,
            {
                "parcel_id": self.delivery_request.pk,
                "journey_id": self.journey.pk,
            },
            format="json",
        )

        assert response.status_code == 200, response.data
        pricing = response.data["pricing"]
        assert pricing["currency"] == "EUR"
        assert pricing["matched_distance_band"] == {
            "label": "100_300km",
            "min_meters": 100_001,
            "max_meters": 300_000,
        }
        assert pricing["distance_band_base_cents"] == 600
        assert pricing["weight_component_cents"] == 250
        assert pricing["global_floor_applied"] is False
        assert pricing["urgency_adjustment_applied"] is True
        assert pricing["minimum_reward_eur_cents"] == 850
        assert pricing["recommended_reward_eur_cents"] == 1_350
        assert pricing["minimum_economics"] == {
            "traveler_reward_minor": 850,
            "commission_rate_bps": 2_500,
            "platform_fee_minor": 213,
            "sender_total_minor": 1_063,
        }
        assert pricing["recommended_economics"]["sender_total_minor"] == 1_688
        # The sender-facing quote is not the admin explain payload.
        assert "matched_distance_meters" not in pricing
        assert "detour_adjustment_cents" not in pricing
        compatibility = response.data["compatibility"]
        assert compatibility["compatible"] is True
        assert compatibility["start_leg_id"] == self.leg.pk
        assert compatibility["end_leg_id"] == self.leg.pk
        assert compatibility["covered_legs"][0]["mode"] == JourneyLeg.Mode.DRIVE
        assert "checks" not in compatibility
        assert "distance_components" not in compatibility
        assert "ranking" not in response.data
        self._assert_privacy_safe(response.data)

        reverse_request = _request(
            sender=self.sender,
            pickup=self.delivery,
            delivery=self.pickup,
            ready_start=self.at + timedelta(hours=1),
            ready_end=self.at + timedelta(hours=3),
            deadline=self.at + timedelta(hours=6),
        )
        incompatible = client.post(
            quote_url,
            {"parcel_id": reverse_request.pk, "journey_id": self.journey.pk},
            format="json",
        )

        assert incompatible.status_code == 409, incompatible.data
        assert incompatible.data["code"] == "incompatible_candidate"
        assert incompatible.data["compatibility"]["compatible"] is False
        assert "pickup_before_delivery" in incompatible.data["compatibility"][
            "rejection_codes"
        ]
        self._assert_privacy_safe(incompatible.data)


class Phase2CompatibilityTests(TestCase):
    def setUp(self):
        self.at = timezone.now()
        self.sender = _user("phase2-sender@example.com")
        self.traveler = _user("phase2-traveler@example.com")
        self.reviewer = _user("phase2-reviewer@example.com", is_staff=True)
        _approve_kyc(self.traveler, "phase2-traveler")
        self.policy = _phase2_policy()

    def _mixed_journey(self):
        origin = _location(
            "Algiers Airport",
            "36.691000",
            "3.215400",
            airport=True,
        )
        interchange = _location(
            "Constantine Airport",
            "36.276000",
            "6.620400",
            airport=True,
        )
        destination = _location("Batna", "35.555900", "6.174100")
        journey = Journey.objects.create(
            traveler=self.traveler,
            start_location=origin,
            destination_location=destination,
            status=Journey.Status.ACTIVE,
            published_at=self.at,
        )
        flight = JourneyLeg.objects.create(
            journey=journey,
            position=0,
            mode=JourneyLeg.Mode.FLIGHT,
            origin=origin,
            destination=interchange,
            depart_at=self.at + timedelta(hours=2),
            arrive_at=self.at + timedelta(hours=4),
            capacity_kg=Decimal("5.00"),
        )
        drive = JourneyLeg.objects.create(
            journey=journey,
            position=1,
            mode=JourneyLeg.Mode.DRIVE,
            origin=interchange,
            destination=destination,
            depart_at=self.at + timedelta(hours=5),
            arrive_at=self.at + timedelta(hours=7),
            capacity_kg=Decimal("5.00"),
            distance_meters=120_000,
        )
        JourneyLegProof.objects.create(
            leg=flight,
            bucket="private-proofs",
            object_key=f"flight/{flight.pk}.jpg",
            status=JourneyLegProof.Status.APPROVED,
            reviewer=self.reviewer,
            reviewed_at=self.at,
        )
        return journey, flight, drive, origin, interchange, destination

    def _canonical_paris_algiers_jijel_journey(self):
        paris_airport = Airport.objects.get(pk="CDG")
        algiers_airport = Airport.objects.get(pk="ALG")
        paris = _location(
            f"Paris CDG {Journey.objects.count()}",
            "49.009700",
            "2.547900",
            airport=True,
            airport_record=paris_airport,
            country_code="FR",
        )
        algiers = _location(
            f"Algiers ALG {Journey.objects.count()}",
            "36.691000",
            "3.215400",
            airport=True,
            airport_record=algiers_airport,
        )
        jijel = _location(
            f"Jijel {Journey.objects.count()}",
            "36.820600",
            "5.766700",
        )
        depart = self.at + timedelta(days=1)
        journey = Journey.objects.create(
            traveler=self.traveler,
            start_location=paris,
            destination_location=jijel,
            status=Journey.Status.ACTIVE,
            published_at=self.at,
        )
        flight = JourneyLeg.objects.create(
            journey=journey,
            position=0,
            mode=JourneyLeg.Mode.FLIGHT,
            origin=paris,
            destination=algiers,
            depart_at=depart,
            arrive_at=depart + timedelta(hours=3),
            capacity_kg=Decimal("20.00"),
        )
        drive = JourneyLeg.objects.create(
            journey=journey,
            position=1,
            mode=JourneyLeg.Mode.DRIVE,
            origin=algiers,
            destination=jijel,
            depart_at=depart + timedelta(hours=4),
            arrive_at=depart + timedelta(hours=8),
            capacity_kg=Decimal("20.00"),
            distance_meters=320_000,
        )
        JourneyLegProof.objects.create(
            leg=flight,
            bucket="private-proofs",
            object_key=f"flight/canonical-{flight.pk}.jpg",
            status=JourneyLegProof.Status.APPROVED,
            reviewer=self.reviewer,
            reviewed_at=self.at,
        )
        return journey, flight, drive, paris, algiers, jijel

    def _canonical_request(
        self,
        *,
        pickup,
        delivery,
        pickup_at,
        deadline,
        weight,
    ):
        return _request(
            sender=self.sender,
            pickup=pickup,
            delivery=delivery,
            ready_start=pickup_at - timedelta(minutes=30),
            ready_end=pickup_at + timedelta(minutes=30),
            deadline=deadline,
            weight=weight,
        )

    def _accept_canonical_request(
        self,
        *,
        delivery_request,
        journey,
        start_leg,
        end_leg,
    ):
        offer = create_sender_offer(
            sender=self.sender,
            delivery_request=delivery_request,
            journey=journey,
            start_leg_id=start_leg.pk,
            end_leg_id=end_leg.pk,
            traveler_reward_eur_cents=10_000,
        )
        return offer, accept_offer(pending_offer=offer, actor=self.traveler).deal

    def test_repeated_node_searches_alternate_anchor_after_short_pair_fails_time(self):
        repeated = _location("Repeated route node", "36.000000", "3.000000")
        turn = _location("Repeated route turn", "36.000000", "3.100000")
        destination = _location("Repeated route destination", "36.000000", "3.200000")
        journey = Journey.objects.create(
            traveler=self.traveler,
            start_location=repeated,
            destination_location=destination,
            status=Journey.Status.ACTIVE,
            published_at=self.at,
        )
        first = JourneyLeg.objects.create(
            journey=journey,
            position=0,
            mode=JourneyLeg.Mode.DRIVE,
            origin=repeated,
            destination=turn,
            depart_at=self.at + timedelta(hours=2),
            arrive_at=self.at + timedelta(hours=3),
            capacity_kg=Decimal("20.00"),
            distance_meters=10_000,
        )
        second = JourneyLeg.objects.create(
            journey=journey,
            position=1,
            mode=JourneyLeg.Mode.DRIVE,
            origin=turn,
            destination=repeated,
            depart_at=self.at + timedelta(hours=4),
            arrive_at=self.at + timedelta(hours=5),
            capacity_kg=Decimal("20.00"),
            distance_meters=10_000,
        )
        third = JourneyLeg.objects.create(
            journey=journey,
            position=2,
            mode=JourneyLeg.Mode.DRIVE,
            origin=repeated,
            destination=destination,
            depart_at=self.at + timedelta(hours=6),
            arrive_at=self.at + timedelta(hours=7),
            capacity_kg=Decimal("20.00"),
            distance_meters=10_000,
        )
        delivery_request = _request(
            sender=self.sender,
            pickup=repeated,
            delivery=destination,
            ready_start=self.at + timedelta(hours=1, minutes=30),
            ready_end=self.at + timedelta(hours=2, minutes=30),
            deadline=self.at + timedelta(hours=8),
            weight="5.00",
        )

        candidate_anchors = compatibility_module._candidate_anchors
        with patch(
            "apps.matching.compatibility._candidate_anchors",
            wraps=candidate_anchors,
        ) as candidate_anchor_calls:
            result = evaluate_compatibility(
                delivery_request=delivery_request,
                journey=journey,
                policy=self.policy,
                at=self.at,
                route_provider=UnavailableRouteProvider(),
            )

        assert result.compatible is True, result.as_dict()
        assert candidate_anchor_calls.call_count == 2
        assert result.pickup_position == 0.0
        assert [leg.pk for leg in result.covered_legs] == [
            first.pk,
            second.pk,
            third.pk,
        ]
        assert "pickup_within_ready_window" not in result.rejection_codes

    def test_canonical_paris_algiers_jijel_forward_and_reverse_matrix(self):
        journey, flight, drive, paris, algiers, jijel = (
            self._canonical_paris_algiers_jijel_journey()
        )
        valid = (
            (
                self._canonical_request(
                    pickup=paris,
                    delivery=algiers,
                    pickup_at=flight.depart_at,
                    deadline=flight.arrive_at + timedelta(hours=1),
                    weight="1.00",
                ),
                [flight.pk],
            ),
            (
                self._canonical_request(
                    pickup=paris,
                    delivery=jijel,
                    pickup_at=flight.depart_at,
                    deadline=drive.arrive_at + timedelta(hours=1),
                    weight="1.00",
                ),
                [flight.pk, drive.pk],
            ),
            (
                self._canonical_request(
                    pickup=algiers,
                    delivery=jijel,
                    pickup_at=drive.depart_at,
                    deadline=drive.arrive_at + timedelta(hours=1),
                    weight="1.00",
                ),
                [drive.pk],
            ),
        )
        invalid = (
            self._canonical_request(
                pickup=algiers,
                delivery=paris,
                pickup_at=drive.depart_at,
                deadline=drive.arrive_at + timedelta(hours=1),
                weight="1.00",
            ),
            self._canonical_request(
                pickup=jijel,
                delivery=algiers,
                pickup_at=drive.arrive_at,
                deadline=drive.arrive_at + timedelta(hours=1),
                weight="1.00",
            ),
        )

        for delivery_request, expected_legs in valid:
            result = evaluate_compatibility(
                delivery_request=delivery_request,
                journey=journey,
                policy=self.policy,
                at=self.at,
                route_provider=UnavailableRouteProvider(),
            )
            assert result.compatible is True, result.as_dict()
            assert [leg.pk for leg in result.covered_legs] == expected_legs

        for delivery_request in invalid:
            result = evaluate_compatibility(
                delivery_request=delivery_request,
                journey=journey,
                policy=self.policy,
                at=self.at,
                route_provider=UnavailableRouteProvider(),
            )
            assert result.compatible is False
            assert "pickup_before_delivery" in result.rejection_codes

    def test_canonical_segment_loads_capacity_boundary_and_atomic_recheck(self):
        journey, flight, drive, paris, algiers, jijel = (
            self._canonical_paris_algiers_jijel_journey()
        )
        request_specs = (
            (paris, algiers, flight.depart_at, flight.arrive_at, "10.00", flight, flight),
            (paris, jijel, flight.depart_at, drive.arrive_at, "5.00", flight, drive),
            (algiers, jijel, drive.depart_at, drive.arrive_at, "8.00", drive, drive),
        )
        for pickup, delivery, pickup_at, arrival, weight, start_leg, end_leg in request_specs:
            delivery_request = self._canonical_request(
                pickup=pickup,
                delivery=delivery,
                pickup_at=pickup_at,
                deadline=arrival + timedelta(hours=1),
                weight=weight,
            )
            self._accept_canonical_request(
                delivery_request=delivery_request,
                journey=journey,
                start_leg=start_leg,
                end_leg=end_leg,
            )

        loads = dict(
            DealLegAllocation.objects.active(at=self.at)
            .filter(journey_leg__journey=journey)
            .values("journey_leg_id")
            .annotate(total=Sum("allocated_weight_kg"))
            .values_list("journey_leg_id", "total")
        )
        assert loads == {
            flight.pk: Decimal("15.000"),
            drive.pk: Decimal("13.000"),
        }

        boundary_journey, boundary_flight, boundary_drive, b_paris, _b_alg, b_jijel = (
            self._canonical_paris_algiers_jijel_journey()
        )
        exact = self._canonical_request(
            pickup=b_paris,
            delivery=b_jijel,
            pickup_at=boundary_flight.depart_at,
            deadline=boundary_drive.arrive_at + timedelta(hours=1),
            weight="20.00",
        )
        over = self._canonical_request(
            pickup=b_paris,
            delivery=b_jijel,
            pickup_at=boundary_flight.depart_at,
            deadline=boundary_drive.arrive_at + timedelta(hours=1),
            weight="20.01",
        )
        exact_evaluation = evaluate_compatibility(
            delivery_request=exact,
            journey=boundary_journey,
            policy=self.policy,
            at=self.at,
            route_provider=UnavailableRouteProvider(),
        )
        over_evaluation = evaluate_compatibility(
            delivery_request=over,
            journey=boundary_journey,
            policy=self.policy,
            at=self.at,
            route_provider=UnavailableRouteProvider(),
        )
        assert exact_evaluation.compatible is True
        assert over_evaluation.compatible is False
        assert "capacity_available_on_every_leg" in over_evaluation.rejection_codes
        _exact_offer, exact_deal = self._accept_canonical_request(
            delivery_request=exact,
            journey=boundary_journey,
            start_leg=boundary_flight,
            end_leg=boundary_drive,
        )
        assert list(
            exact_deal.leg_allocations.values_list("allocated_weight_kg", flat=True)
        ) == [Decimal("20.000"), Decimal("20.000")]

        race_journey, race_flight, race_drive, r_paris, r_algiers, r_jijel = (
            self._canonical_paris_algiers_jijel_journey()
        )
        cross_request = self._canonical_request(
            pickup=r_paris,
            delivery=r_jijel,
            pickup_at=race_flight.depart_at,
            deadline=race_drive.arrive_at + timedelta(hours=1),
            weight="10.00",
        )
        cross_offer = create_sender_offer(
            sender=self.sender,
            delivery_request=cross_request,
            journey=race_journey,
            start_leg_id=race_flight.pk,
            end_leg_id=race_drive.pk,
            traveler_reward_eur_cents=10_000,
        )
        blocker = self._canonical_request(
            pickup=r_paris,
            delivery=r_algiers,
            pickup_at=race_flight.depart_at,
            deadline=race_flight.arrive_at + timedelta(hours=1),
            weight="15.00",
        )
        self._accept_canonical_request(
            delivery_request=blocker,
            journey=race_journey,
            start_leg=race_flight,
            end_leg=race_flight,
        )
        deal_count = Deal.objects.count()

        with self.assertRaises(CapacityExceeded):
            accept_offer(pending_offer=cross_offer, actor=self.traveler)

        cross_request.refresh_from_db()
        cross_offer.refresh_from_db()
        cross_offer.match.refresh_from_db()
        assert Deal.objects.count() == deal_count
        assert not Deal.objects.filter(accepted_offer=cross_offer).exists()
        assert cross_request.status == ParcelRequest.Status.OPEN
        assert cross_offer.status == cross_offer.Status.PENDING
        assert cross_offer.match.status == cross_offer.match.Status.PENDING
        assert DealLegAllocation.objects.active(at=self.at).filter(
            journey_leg=race_drive
        ).count() == 0

    def test_mixed_route_matches_complete_and_drive_only_subroutes(self):
        journey, flight, drive, origin, interchange, destination = (
            self._mixed_journey()
        )
        complete_request = _request(
            sender=self.sender,
            pickup=origin,
            delivery=destination,
            ready_start=self.at + timedelta(hours=1),
            ready_end=self.at + timedelta(hours=3),
            deadline=self.at + timedelta(hours=8),
        )
        drive_request = _request(
            sender=self.sender,
            pickup=interchange,
            delivery=destination,
            ready_start=self.at + timedelta(hours=4),
            ready_end=self.at + timedelta(hours=6),
            deadline=self.at + timedelta(hours=8),
        )

        complete = evaluate_compatibility(
            delivery_request=complete_request,
            journey=journey,
            policy=self.policy,
            at=self.at,
            route_provider=UnavailableRouteProvider(),
        )
        drive_only = evaluate_compatibility(
            delivery_request=drive_request,
            journey=journey,
            policy=self.policy,
            at=self.at,
            route_provider=UnavailableRouteProvider(),
        )

        assert complete.compatible is True
        assert [leg.pk for leg in complete.covered_legs] == [flight.pk, drive.pk]
        assert complete.matched_distance_method.startswith("mixed:")
        assert drive_only.compatible is True
        assert [leg.pk for leg in drive_only.covered_legs] == [drive.pk]
        assert drive_only.matched_distance_meters == 120_000
        assert drive_only.matched_distance_method == "stored_routed_road_distance"

    def test_flight_leg_requires_server_trusted_airport_coordinates(self):
        journey, _flight, _drive, origin, _interchange, destination = (
            self._mixed_journey()
        )
        delivery_request = _request(
            sender=self.sender,
            pickup=origin,
            delivery=destination,
            ready_start=self.at + timedelta(hours=1),
            ready_end=self.at + timedelta(hours=3),
            deadline=self.at + timedelta(hours=8),
        )
        origin.coordinates_trusted = False
        origin.coordinate_dataset_version = ""
        origin.save(
            update_fields=[
                "coordinates_trusted",
                "coordinate_dataset_version",
                "updated_at",
            ]
        )

        result = evaluate_compatibility(
            delivery_request=delivery_request,
            journey=journey,
            policy=self.policy,
            at=self.at,
            route_provider=UnavailableRouteProvider(),
        )

        assert result.compatible is False
        assert "flight_coordinates_trusted" in result.rejection_codes

    def test_separate_location_rows_match_when_they_share_airport_identity(self):
        alg = Airport.objects.get(pk="ALG")
        czl = Airport.objects.get(pk="CZL")
        journey_origin = _location(
            "Journey ALG",
            "36.691000",
            "3.215400",
            airport=True,
            airport_record=alg,
        )
        journey_destination = _location(
            "Journey CZL",
            "36.276000",
            "6.620400",
            airport=True,
            airport_record=czl,
        )
        request_origin = _location(
            "Request ALG",
            "36.692000",
            "3.216000",
            owner=self.sender,
            airport=True,
            airport_record=alg,
        )
        request_destination = _location(
            "Request CZL",
            "36.277000",
            "6.621000",
            owner=self.sender,
            airport=True,
            airport_record=czl,
        )
        journey = Journey.objects.create(
            traveler=self.traveler,
            start_location=journey_origin,
            destination_location=journey_destination,
            status=Journey.Status.ACTIVE,
            published_at=self.at,
        )
        flight = JourneyLeg.objects.create(
            journey=journey,
            position=0,
            mode=JourneyLeg.Mode.FLIGHT,
            origin=journey_origin,
            destination=journey_destination,
            depart_at=self.at + timedelta(hours=2),
            arrive_at=self.at + timedelta(hours=4),
            capacity_kg=Decimal("5.00"),
        )
        JourneyLegProof.objects.create(
            leg=flight,
            bucket="private-proofs",
            object_key="flight/shared-airport-identity.jpg",
            status=JourneyLegProof.Status.APPROVED,
            reviewer=self.reviewer,
            reviewed_at=self.at,
        )
        delivery_request = _request(
            sender=self.sender,
            pickup=request_origin,
            delivery=request_destination,
            ready_start=self.at + timedelta(hours=1),
            ready_end=self.at + timedelta(hours=3),
            deadline=self.at + timedelta(hours=5),
        )

        result = evaluate_compatibility(
            delivery_request=delivery_request,
            journey=journey,
            policy=self.policy,
            at=self.at,
            route_provider=UnavailableRouteProvider(),
        )

        assert result.compatible is True, result.as_dict()
        assert result.pickup_position == 0.0
        assert result.delivery_position == 1.0
        assert result.pickup_detour_meters == 0
        assert result.delivery_detour_meters == 0

    def test_drive_only_subroute_requires_uncovered_flight_proof_but_not_trust(self):
        journey, flight, drive, origin, interchange, destination = (
            self._mixed_journey()
        )
        proof = flight.proofs.get()
        proof.status = JourneyLegProof.Status.REJECTED
        proof.rejection_reason = "Approval revoked after re-review"
        proof.save(update_fields=["status", "rejection_reason", "updated_at"])
        origin.coordinates_trusted = False
        origin.coordinate_dataset_version = ""
        origin.save(
            update_fields=[
                "coordinates_trusted",
                "coordinate_dataset_version",
                "updated_at",
            ]
        )
        delivery_request = _request(
            sender=self.sender,
            pickup=interchange,
            delivery=destination,
            ready_start=self.at + timedelta(hours=4),
            ready_end=self.at + timedelta(hours=6),
            deadline=self.at + timedelta(hours=8),
        )

        result = evaluate_compatibility(
            delivery_request=delivery_request,
            journey=journey,
            policy=self.policy,
            at=self.at,
            route_provider=UnavailableRouteProvider(),
        )

        assert result.compatible is False, result.as_dict()
        assert [leg.pk for leg in result.covered_legs] == [drive.pk]
        assert "flight_proofs_approved" in result.rejection_codes
        assert "flight_coordinates_trusted" not in result.rejection_codes
        checks = {check["code"]: check for check in result.checks}
        assert checks["flight_proofs_approved"]["details"]["flight_leg_ids"] == [
            flight.pk
        ]
        assert checks["flight_coordinates_trusted"]["details"][
            "flight_leg_ids"
        ] == []

    def test_drive_detour_uses_provider_delta_and_enforces_fallback_limits(self):
        origin = _location("Drive origin", "36.000000", "3.000000")
        destination = _location("Drive destination", "36.000000", "3.200000")
        near_pickup = _location("Near pickup", "36.001000", "3.050000")
        far_pickup = _location("Far pickup", "36.200000", "3.050000")
        journey = Journey.objects.create(
            traveler=self.traveler,
            start_location=origin,
            destination_location=destination,
            status=Journey.Status.ACTIVE,
            published_at=self.at,
        )
        JourneyLeg.objects.create(
            journey=journey,
            position=0,
            mode=JourneyLeg.Mode.DRIVE,
            origin=origin,
            destination=destination,
            depart_at=self.at + timedelta(hours=2),
            arrive_at=self.at + timedelta(hours=6),
            capacity_kg=Decimal("5.00"),
            distance_meters=18_000,
        )
        near_request = _request(
            sender=self.sender,
            pickup=near_pickup,
            delivery=destination,
            ready_start=self.at + timedelta(hours=2),
            ready_end=self.at + timedelta(hours=4),
            deadline=self.at + timedelta(hours=7),
        )
        far_request = _request(
            sender=self.sender,
            pickup=far_pickup,
            delivery=destination,
            ready_start=self.at + timedelta(hours=2),
            ready_end=self.at + timedelta(hours=4),
            deadline=self.at + timedelta(hours=7),
        )
        provider = DeterministicFixtureRouteProvider()

        near = evaluate_compatibility(
            delivery_request=near_request,
            journey=journey,
            policy=self.policy,
            at=self.at,
            route_provider=provider,
        )
        far = evaluate_compatibility(
            delivery_request=far_request,
            journey=journey,
            policy=self.policy,
            at=self.at,
            route_provider=UnavailableRouteProvider(),
        )

        assert near.compatible is True
        assert near.pickup_detour_meters > 0
        assert near.route_provider == provider.name
        # One corridor lookup, baseline/detour pairs for the combined and
        # individual pickup delta, plus the carried-subroute route.
        assert provider.call_counts["directions"] == 6
        assert far.compatible is False
        assert "pickup_detour_within_limit" in far.rejection_codes
        assert "total_added_distance_within_limit" in far.rejection_codes
        assert "drive_detour_uses_spatial_fallback_not_routed_delta" in far.limitations

    def test_malformed_stored_corridor_is_labeled_as_spatial_fallback(self):
        origin = _location("Malformed corridor origin", "36.000000", "3.000000")
        destination = _location(
            "Malformed corridor destination",
            "36.000000",
            "3.200000",
        )
        pickup = _location("Malformed corridor pickup", "36.001000", "3.050000")
        journey = Journey.objects.create(
            traveler=self.traveler,
            start_location=origin,
            destination_location=destination,
            status=Journey.Status.ACTIVE,
            published_at=self.at,
        )
        leg = JourneyLeg.objects.create(
            journey=journey,
            position=0,
            mode=JourneyLeg.Mode.DRIVE,
            origin=origin,
            destination=destination,
            depart_at=self.at + timedelta(hours=2),
            arrive_at=self.at + timedelta(hours=6),
            capacity_kg=Decimal("5.00"),
            distance_meters=18_000,
            route_metadata={
                "corridor_points": [
                    {"latitude": "not-a-number", "longitude": 3.0},
                    {"latitude": 999, "longitude": 3.2},
                ]
            },
        )
        delivery_request = _request(
            sender=self.sender,
            pickup=pickup,
            delivery=destination,
            ready_start=self.at + timedelta(hours=2),
            ready_end=self.at + timedelta(hours=4),
            deadline=self.at + timedelta(hours=7),
        )

        result = evaluate_compatibility(
            delivery_request=delivery_request,
            journey=journey,
            policy=self.policy,
            at=self.at,
            route_provider=UnavailableRouteProvider(),
        )

        assert result.compatible is True, result.as_dict()
        assert [covered.pk for covered in result.covered_legs] == [leg.pk]
        assert "pickup_anchor_uses_straight_line_spatial_fallback" in (
            result.limitations
        )
        assert "drive_detour_uses_spatial_fallback_not_routed_delta" in (
            result.limitations
        )

    def test_same_drive_leg_prices_only_the_carried_interior_subroute(self):
        origin = _location("Carried origin", "36.000000", "3.000000")
        destination = _location("Carried destination", "36.000000", "3.200000")
        pickup = _location("Carried pickup", "36.010000", "3.050000")
        delivery = _location("Carried delivery", "36.010000", "3.150000")
        journey = Journey.objects.create(
            traveler=self.traveler,
            start_location=origin,
            destination_location=destination,
            status=Journey.Status.ACTIVE,
            published_at=self.at,
        )
        JourneyLeg.objects.create(
            journey=journey,
            position=0,
            mode=JourneyLeg.Mode.DRIVE,
            origin=origin,
            destination=destination,
            depart_at=self.at + timedelta(hours=2),
            arrive_at=self.at + timedelta(hours=6),
            capacity_kg=Decimal("5.00"),
        )
        delivery_request = _request(
            sender=self.sender,
            pickup=pickup,
            delivery=delivery,
            ready_start=self.at + timedelta(hours=2, minutes=30),
            ready_end=self.at + timedelta(hours=3, minutes=30),
            deadline=self.at + timedelta(hours=7),
        )
        provider = DeterministicFixtureRouteProvider()

        result = evaluate_compatibility(
            delivery_request=delivery_request,
            journey=journey,
            policy=self.policy,
            at=self.at,
            route_provider=provider,
        )
        carried_route = provider.directions(
            [
                GeoPoint(float(pickup.latitude), float(pickup.longitude)),
                GeoPoint(float(delivery.latitude), float(delivery.longitude)),
            ],
            profile="drive",
        )

        assert result.compatible is True
        assert 0 < result.pickup_position < result.delivery_position < 1
        assert result.added_distance_meters > 0
        assert result.matched_distance_meters == carried_route.distance_meters
        assert result.distance_components[0]["distance_meters"] == (
            carried_route.distance_meters
        )
        assert result.matched_distance_meters != (
            result.distance_components[0]["distance_meters"]
            + result.added_distance_meters
        )

    def test_targeted_request_matches_only_the_selected_traveler(self):
        journey, _flight, _drive, origin, _interchange, destination = (
            self._mixed_journey()
        )
        other_traveler = _user("phase2-other-traveler@example.com")
        delivery_request = _request(
            sender=self.sender,
            pickup=origin,
            delivery=destination,
            ready_start=self.at + timedelta(hours=1),
            ready_end=self.at + timedelta(hours=3),
            deadline=self.at + timedelta(hours=8),
        )
        delivery_request.target_traveler = other_traveler
        delivery_request.save(update_fields=["target_traveler", "updated_at"])

        wrong_traveler = evaluate_compatibility(
            delivery_request=delivery_request,
            journey=journey,
            policy=self.policy,
            at=self.at,
            route_provider=UnavailableRouteProvider(),
        )
        delivery_request.target_traveler = self.traveler
        delivery_request.save(update_fields=["target_traveler", "updated_at"])
        selected_traveler = evaluate_compatibility(
            delivery_request=delivery_request,
            journey=journey,
            policy=self.policy,
            at=self.at,
            route_provider=UnavailableRouteProvider(),
        )

        assert wrong_traveler.compatible is False
        assert "target_traveler_eligible" in wrong_traveler.rejection_codes
        assert selected_traveler.compatible is True

    def test_known_detour_duration_is_added_before_deadline_validation(self):
        origin = _location("Duration origin", "36.000000", "3.000000")
        destination = _location("Duration destination", "36.000000", "3.200000")
        pickup = _location("Duration pickup", "36.001000", "3.050000")
        journey = Journey.objects.create(
            traveler=self.traveler,
            start_location=origin,
            destination_location=destination,
            status=Journey.Status.ACTIVE,
            published_at=self.at,
        )
        JourneyLeg.objects.create(
            journey=journey,
            position=0,
            mode=JourneyLeg.Mode.DRIVE,
            origin=origin,
            destination=destination,
            depart_at=self.at + timedelta(hours=2),
            arrive_at=self.at + timedelta(hours=6),
            capacity_kg=Decimal("5.00"),
            distance_meters=18_000,
        )
        delivery_request = _request(
            sender=self.sender,
            pickup=pickup,
            delivery=destination,
            ready_start=self.at + timedelta(hours=2),
            ready_end=self.at + timedelta(hours=4),
            deadline=self.at + timedelta(hours=6, minutes=5),
        )

        result = evaluate_compatibility(
            delivery_request=delivery_request,
            journey=journey,
            policy=self.policy,
            at=self.at,
            route_provider=_KnownDurationDetourProvider(),
        )

        assert result.added_duration_seconds == 400
        assert result.pickup_added_duration_seconds == 0
        assert result.pickup_at == self.at + timedelta(hours=3)
        assert result.delivery_at == self.at + timedelta(hours=6, seconds=400)
        assert result.compatible is False
        assert "delivery_before_deadline" in result.rejection_codes

    def test_interior_dropoff_eta_excludes_post_dropoff_return_duration(self):
        origin = _location("Dropoff origin", "36.000000", "3.000000")
        destination = _location("Dropoff destination", "36.000000", "3.200000")
        dropoff = _location("Interior dropoff", "36.010000", "3.150000")
        journey = Journey.objects.create(
            traveler=self.traveler,
            start_location=origin,
            destination_location=destination,
            status=Journey.Status.ACTIVE,
            published_at=self.at,
        )
        JourneyLeg.objects.create(
            journey=journey,
            position=0,
            mode=JourneyLeg.Mode.DRIVE,
            origin=origin,
            destination=destination,
            depart_at=self.at + timedelta(hours=2),
            arrive_at=self.at + timedelta(hours=6),
            capacity_kg=Decimal("5.00"),
            distance_meters=18_000,
        )
        baseline_dropoff_at = self.at + timedelta(hours=5)
        delivery_request = _request(
            sender=self.sender,
            pickup=origin,
            delivery=dropoff,
            ready_start=self.at + timedelta(hours=1),
            ready_end=self.at + timedelta(hours=3),
            deadline=baseline_dropoff_at + timedelta(seconds=250),
        )
        provider = _PrefixAwareDropoffProvider(
            destination=GeoPoint(
                float(destination.latitude),
                float(destination.longitude),
            ),
            dropoff=GeoPoint(float(dropoff.latitude), float(dropoff.longitude)),
        )

        result = evaluate_compatibility(
            delivery_request=delivery_request,
            journey=journey,
            policy=self.policy,
            at=self.at,
            route_provider=provider,
        )
        strict_detour = evaluate_compatibility(
            delivery_request=delivery_request,
            journey=journey,
            policy=replace(
                self.policy,
                max_total_added_duration_seconds=400,
            ),
            at=self.at,
            route_provider=provider,
        )

        assert result.added_duration_seconds == 500
        assert result.delivery_at == baseline_dropoff_at + timedelta(seconds=200)
        assert result.delivery_at < baseline_dropoff_at + timedelta(seconds=500)
        assert result.compatible is True
        assert strict_detour.delivery_at == result.delivery_at
        assert strict_detour.compatible is False
        assert "total_added_duration_within_limit" in strict_detour.rejection_codes

    def test_pickup_clamped_to_leg_end_still_covers_and_prices_that_drive_leg(self):
        origin = _location("Clamp-end origin", "36.000000", "3.000000")
        midpoint = _location("Clamp-end midpoint", "36.000000", "3.200000")
        destination = _location("Clamp-end destination", "36.000000", "3.400000")
        pickup = _location("Off-route leg-end pickup", "36.005000", "3.200000")
        journey = Journey.objects.create(
            traveler=self.traveler,
            start_location=origin,
            destination_location=destination,
            status=Journey.Status.ACTIVE,
            published_at=self.at,
        )
        preceding_leg = JourneyLeg.objects.create(
            journey=journey,
            position=0,
            mode=JourneyLeg.Mode.DRIVE,
            origin=origin,
            destination=midpoint,
            depart_at=self.at + timedelta(hours=2),
            arrive_at=self.at + timedelta(hours=6),
            capacity_kg=Decimal("5.00"),
        )
        final_leg = JourneyLeg.objects.create(
            journey=journey,
            position=1,
            mode=JourneyLeg.Mode.DRIVE,
            origin=midpoint,
            destination=destination,
            depart_at=self.at + timedelta(hours=6, minutes=30),
            arrive_at=self.at + timedelta(hours=9),
            capacity_kg=Decimal("5.00"),
        )
        delivery_request = _request(
            sender=self.sender,
            pickup=pickup,
            delivery=destination,
            ready_start=self.at + timedelta(hours=5, minutes=30),
            ready_end=self.at + timedelta(hours=7),
            deadline=self.at + timedelta(hours=10),
        )

        result = evaluate_compatibility(
            delivery_request=delivery_request,
            journey=journey,
            policy=self.policy,
            at=self.at,
            route_provider=DeterministicFixtureRouteProvider(),
        )

        assert result.compatible is True, result.as_dict()
        assert result.pickup_position == 1.0
        assert result.delivery_position == 2.0
        assert [covered.pk for covered in result.covered_legs] == [
            preceding_leg.pk,
            final_leg.pk,
        ]
        assert result.matched_distance_meters > 0
        assert result.distance_components[0]["partial_start"] is True
        assert result.distance_components[0]["partial_end"] is False
        assert result.distance_components[0]["distance_meters"] > 0

    def test_delivery_clamped_to_leg_start_still_covers_and_prices_that_drive_leg(self):
        origin = _location("Clamp-start origin", "36.000000", "3.000000")
        destination = _location("Clamp-start destination", "36.000000", "3.200000")
        delivery = _location("Before leg start delivery", "36.005000", "2.990000")
        journey = Journey.objects.create(
            traveler=self.traveler,
            start_location=origin,
            destination_location=destination,
            status=Journey.Status.ACTIVE,
            published_at=self.at,
        )
        leg = JourneyLeg.objects.create(
            journey=journey,
            position=0,
            mode=JourneyLeg.Mode.DRIVE,
            origin=origin,
            destination=destination,
            depart_at=self.at + timedelta(hours=2),
            arrive_at=self.at + timedelta(hours=6),
            capacity_kg=Decimal("5.00"),
        )
        delivery_request = _request(
            sender=self.sender,
            pickup=origin,
            delivery=delivery,
            ready_start=self.at + timedelta(hours=1),
            ready_end=self.at + timedelta(hours=3),
            deadline=self.at + timedelta(hours=4),
        )

        result = evaluate_compatibility(
            delivery_request=delivery_request,
            journey=journey,
            policy=self.policy,
            at=self.at,
            route_provider=DeterministicFixtureRouteProvider(),
        )

        assert result.compatible is True, result.as_dict()
        assert result.pickup_position == 0.0
        assert result.delivery_position == 0.0
        assert [covered.pk for covered in result.covered_legs] == [leg.pk]
        assert result.matched_distance_meters > 0
        assert result.distance_components[0]["partial_start"] is False
        assert result.distance_components[0]["partial_end"] is True

    def test_disabled_spatial_fallback_rejects_missing_road_route(self):
        origin = _location("Fallback origin", "36.000000", "3.000000")
        destination = _location("Fallback destination", "36.000000", "3.200000")
        journey = Journey.objects.create(
            traveler=self.traveler,
            start_location=origin,
            destination_location=destination,
            status=Journey.Status.ACTIVE,
            published_at=self.at,
        )
        JourneyLeg.objects.create(
            journey=journey,
            position=0,
            mode=JourneyLeg.Mode.DRIVE,
            origin=origin,
            destination=destination,
            depart_at=self.at + timedelta(hours=2),
            arrive_at=self.at + timedelta(hours=6),
            capacity_kg=Decimal("5.00"),
        )
        delivery_request = _request(
            sender=self.sender,
            pickup=origin,
            delivery=destination,
            ready_start=self.at + timedelta(hours=1),
            ready_end=self.at + timedelta(hours=3),
            deadline=self.at + timedelta(hours=7),
        )

        result = evaluate_compatibility(
            delivery_request=delivery_request,
            journey=journey,
            policy=replace(self.policy, spatial_fallback_enabled=False),
            at=self.at,
            route_provider=UnavailableRouteProvider(),
        )

        assert result.compatible is False
        assert "route_provider_available" in result.rejection_codes
        assert result.matched_distance_method == "straight_line_spatial_fallback"

    def test_request_after_final_leg_departure_is_still_discovered_mid_leg(self):
        journey, _flight, drive, _origin, interchange, destination = (
            self._mixed_journey()
        )
        pickup = _location(
            "Final leg interior pickup",
            str((interchange.latitude + destination.latitude) / 2),
            str((interchange.longitude + destination.longitude) / 2),
        )
        delivery_request = _request(
            sender=self.sender,
            pickup=pickup,
            delivery=destination,
            ready_start=drive.depart_at + timedelta(minutes=30),
            ready_end=drive.depart_at + timedelta(hours=1, minutes=30),
            deadline=drive.arrive_at + timedelta(hours=1),
        )

        results = compatible_requests_for_journey(
            journey=journey,
            policy=self.policy,
            at=self.at,
        )

        evaluation = next(
            row for row in results if row.delivery_request.pk == delivery_request.pk
        )
        assert 1 < evaluation.compatibility.pickup_position < 2
        assert evaluation.compatibility.pickup_at > drive.depart_at
        assert evaluation.compatibility.pickup_at < drive.arrive_at

    @override_settings(
        ROUTE_PROVIDER_CLASS=(
            "apps.routing.testing.DeterministicFixtureRouteProvider"
        ),
        ROUTE_PROVIDER_OPTIONS={
            "road_distance_multiplier": "1.20",
            "speed_kph": 60,
        },
    )
    def test_journey_creation_enriches_drive_route_and_public_output_redacts_geometry(
        self,
    ):
        cache.clear()
        origin = _location("Enrichment origin", "36.752500", "3.041970")
        destination = _location("Enrichment destination", "36.365000", "6.614700")
        serializer = JourneyCreateSerializer(
            data={
                "start_location": origin.pk,
                "destination_location": destination.pk,
                "legs": [
                    {
                        "position": 0,
                        "mode": JourneyLeg.Mode.DRIVE,
                        "origin": origin.pk,
                        "destination": destination.pk,
                        "depart_at": self.at + timedelta(days=1),
                        "arrive_at": self.at + timedelta(days=1, hours=5),
                        "capacity_kg": "5.00",
                    }
                ],
            },
            context={"request": SimpleNamespace(user=self.traveler)},
        )
        assert serializer.is_valid(), serializer.errors

        journey = serializer.save()
        leg = journey.legs.get()
        owner_payload = JourneyLegSerializer(
            leg,
            context={"request": SimpleNamespace(user=self.traveler)},
        ).data
        public_payload = JourneyLegSerializer(
            leg,
            context={"request": SimpleNamespace(user=self.sender)},
        ).data

        direct_distance = haversine_meters(
            GeoPoint(float(origin.latitude), float(origin.longitude)),
            GeoPoint(float(destination.latitude), float(destination.longitude)),
        )
        assert leg.distance_meters == round(direct_distance * 1.2)
        assert leg.route_duration_seconds is not None
        assert leg.route_provider == "deterministic_fixture"
        assert leg.route_profile == "drive"
        assert leg.route_captured_at is not None
        assert leg.route_metadata["provider_metadata"] == {"fixture": True}
        assert len(leg.route_metadata["corridor_points"]) == 2
        assert "route_metadata" in owner_payload
        assert "route_polyline" in owner_payload
        assert "route_metadata" not in public_payload
        assert "route_polyline" not in public_payload

    def test_boost_changes_ranking_only_after_hard_compatibility(self):
        journey, _flight, _drive, origin, _interchange, destination = (
            self._mixed_journey()
        )
        delivery_request = _request(
            sender=self.sender,
            pickup=origin,
            delivery=destination,
            ready_start=self.at + timedelta(hours=1),
            ready_end=self.at + timedelta(hours=3),
            deadline=self.at + timedelta(hours=8),
        )
        delivery_request.ranking_boost_weight = 20
        delivery_request.ranking_boost_expires_at = self.at + timedelta(days=1)
        compatible = evaluate_compatibility(
            delivery_request=delivery_request,
            journey=journey,
            policy=self.policy,
            at=self.at,
            route_provider=UnavailableRouteProvider(),
        )

        ranking = rank_compatible_candidate(
            compatibility=compatible,
            delivery_request=delivery_request,
            policy=self.policy,
            at=self.at,
        )

        assert ranking["boost"] == {
            "active": True,
            "weight": 20,
            "points": self.policy.max_boost_points,
            "compatibility_override": False,
        }
        assert ranking["score"] == ranking["base_score"] + self.policy.max_boost_points
        with self.assertRaisesMessage(
            ValueError,
            "Hard compatibility must pass before ranking.",
        ):
            rank_compatible_candidate(
                compatibility=replace(compatible, compatible=False),
                delivery_request=delivery_request,
                policy=self.policy,
                at=self.at,
            )

    def test_admin_explanation_excludes_exact_location_and_route_secrets(self):
        journey, _flight, _drive, origin, _interchange, destination = (
            self._mixed_journey()
        )
        delivery_request = _request(
            sender=self.sender,
            pickup=origin,
            delivery=destination,
            ready_start=self.at + timedelta(hours=1),
            ready_end=self.at + timedelta(hours=3),
            deadline=self.at + timedelta(hours=8),
        )
        client = APIClient()
        client.force_authenticate(user=self.reviewer)

        response = client.get(
            reverse("matches-explain-v1"),
            {"parcel_id": delivery_request.pk, "journey_id": journey.pk},
        )

        assert response.status_code == 200, response.data
        payload_text = json.dumps(response.data, default=str)
        assert "SECRET normalized" not in payload_text
        assert "SECRET private address" not in payload_text
        assert "SECRET-place" not in payload_text
        assert "SECRET provider address" not in payload_text
        assert "route_metadata" not in payload_text
        pickup_payload = response.data["delivery_request"]["pickup"]
        assert "latitude" not in pickup_payload
        assert "longitude" not in pickup_payload
        assert "provider" not in pickup_payload
        assert "provider_place_id" not in pickup_payload
        assert "private_label" not in pickup_payload
