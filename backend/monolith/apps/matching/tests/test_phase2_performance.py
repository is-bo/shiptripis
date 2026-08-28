from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.cache import caches
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import User
from apps.core.models import BusinessSettingsVersion
from apps.kyc.models import KycSubmission
from apps.locations.models import Location
from apps.matching.discovery import (
    compatible_journeys_for_request,
    compatible_requests_for_journey,
)
from apps.matching.policy import Phase2Policy
from apps.parcels.models import DeliveryRequest, ParcelRequest
from apps.routing.providers import BudgetedRouteProvider, CachedRouteProvider
from apps.routing.testing import DeterministicFixtureRouteProvider
from apps.trips.models import Journey, JourneyLeg


SMALL_CANDIDATE_COUNT = 3
LARGE_CANDIDATE_COUNT = 24


def _user(sequence: int, role: str) -> User:
    email = f"phase2-perf-{role}-{sequence}@example.com"
    return User.objects.create(
        username=email,
        email=email,
        full_name=f"Performance {role} {sequence}",
    )


def _location(label: str, latitude: str, longitude: str) -> Location:
    return Location.objects.create(
        kind=Location.Kind.MAP_POINT,
        normalized_label=f"Exact {label}",
        public_label=label,
        private_label=f"Private {label}",
        city=label,
        country_code="DZ",
        latitude=Decimal(latitude),
        longitude=Decimal(longitude),
        coarse_latitude=Decimal(latitude).quantize(Decimal("0.1")),
        coarse_longitude=Decimal(longitude).quantize(Decimal("0.1")),
    )


def _approve_kyc(user: User, sequence: int) -> None:
    KycSubmission.objects.create(
        user=user,
        document_type=KycSubmission.DocumentType.PASSPORT,
        idempotency_key=f"phase2perf{sequence:022d}",
        front_image_key=f"kyc/phase2-performance/{sequence}.jpg",
        status=KycSubmission.Status.APPROVED,
        reviewed_at=timezone.now(),
    )


def _delivery_request(
    *,
    sender: User,
    pickup: Location,
    delivery: Location,
    depart_at,
    sequence: int,
) -> DeliveryRequest:
    return DeliveryRequest.objects.create(
        sender=sender,
        kind=ParcelRequest.Kind.DELIVERY,
        schema_version=2,
        pickup_location=pickup,
        delivery_location=delivery,
        ready_window_start=depart_at - timedelta(hours=1),
        ready_window_end=depart_at + timedelta(hours=2),
        deadline_at=depart_at + timedelta(hours=6),
        actual_weight_kg=Decimal("1.00"),
        length_cm=Decimal("10.00"),
        width_cm=Decimal("10.00"),
        height_cm=Decimal("10.00"),
        declared_value_eur_cents=10_000,
        traveler_reward_eur_cents=2_000,
        title=f"Performance parcel {sequence}",
        description="Safe performance regression fixture",
        category=ParcelRequest.ItemType.DOCUMENTS,
        item_type=ParcelRequest.ItemType.DOCUMENTS,
        description_is_accurate=True,
        item_is_legal=True,
        no_prohibited_goods=True,
        declared_value_is_accurate=True,
        customs_responsibilities_understood=True,
    )


def _journey(
    *,
    traveler: User,
    origin: Location,
    destination: Location,
    depart_at,
    sequence: int,
    route_metadata: dict | None = None,
) -> Journey:
    journey = Journey.objects.create(
        traveler=traveler,
        start_location=origin,
        destination_location=destination,
        status=Journey.Status.ACTIVE,
        published_at=depart_at - timedelta(days=1, seconds=sequence),
    )
    JourneyLeg.objects.create(
        journey=journey,
        position=0,
        mode=JourneyLeg.Mode.DRIVE,
        origin=origin,
        destination=destination,
        depart_at=depart_at,
        arrive_at=depart_at + timedelta(hours=3),
        capacity_kg=Decimal("10.00"),
        distance_meters=20_000,
        route_duration_seconds=10_800,
        route_provider="performance_fixture",
        route_profile="drive",
        route_metadata=route_metadata or {},
    )
    return journey


class Phase2DiscoveryQueryCountTests(TestCase):
    def setUp(self) -> None:
        self.at = timezone.now()
        self.depart_at = self.at + timedelta(days=2)
        self.policy = Phase2Policy.from_settings(
            BusinessSettingsVersion.objects.get(version=2)
        )
        self.origin = _location("Performance origin", "36.000000", "3.000000")
        self.destination = _location(
            "Performance destination", "36.000000", "3.200000"
        )

    def _create_journey_candidates(self, start: int, stop: int) -> None:
        for sequence in range(start, stop):
            traveler = _user(sequence, "traveler")
            _approve_kyc(traveler, sequence)
            _journey(
                traveler=traveler,
                origin=self.origin,
                destination=self.destination,
                depart_at=self.depart_at,
                sequence=sequence,
            )

    def _create_request_candidates(
        self,
        start: int,
        stop: int,
        *,
        pickup: Location | None = None,
        delivery: Location | None = None,
    ) -> None:
        pickup = pickup or self.origin
        delivery = delivery or self.destination
        for sequence in range(start, stop):
            sender = _user(sequence, "sender")
            _delivery_request(
                sender=sender,
                pickup=pickup,
                delivery=delivery,
                depart_at=self.depart_at,
                sequence=sequence,
            )

    @staticmethod
    def _capture_queries(callback):
        with CaptureQueriesContext(connection) as queries:
            result = callback()
        return result, len(queries)

    def test_request_to_journeys_query_count_is_constant_across_candidate_volume(self):
        sender = _user(10_000, "request-owner")
        delivery_request = _delivery_request(
            sender=sender,
            pickup=self.origin,
            delivery=self.destination,
            depart_at=self.depart_at,
            sequence=10_000,
        )
        provider = DeterministicFixtureRouteProvider()
        self._create_journey_candidates(0, SMALL_CANDIDATE_COUNT)

        with patch("apps.matching.discovery.get_route_provider", return_value=provider):
            small_results, small_queries = self._capture_queries(
                lambda: compatible_journeys_for_request(
                    delivery_request=delivery_request,
                    policy=self.policy,
                    at=self.at,
                )
            )
            self._create_journey_candidates(
                SMALL_CANDIDATE_COUNT,
                LARGE_CANDIDATE_COUNT,
            )
            large_results, large_queries = self._capture_queries(
                lambda: compatible_journeys_for_request(
                    delivery_request=delivery_request,
                    policy=self.policy,
                    at=self.at,
                )
            )

        assert len(small_results) == SMALL_CANDIDATE_COUNT
        assert len(large_results) == LARGE_CANDIDATE_COUNT
        assert small_queries == large_queries
        assert large_queries <= 3
        assert provider.call_counts["directions"] == 0

    def test_journey_to_requests_query_count_is_constant_across_candidate_volume(self):
        traveler = _user(20_000, "journey-owner")
        _approve_kyc(traveler, 20_000)
        journey = _journey(
            traveler=traveler,
            origin=self.origin,
            destination=self.destination,
            depart_at=self.depart_at,
            sequence=20_000,
        )
        provider = DeterministicFixtureRouteProvider()
        self._create_request_candidates(0, SMALL_CANDIDATE_COUNT)

        with patch("apps.matching.discovery.get_route_provider", return_value=provider):
            small_results, small_queries = self._capture_queries(
                lambda: compatible_requests_for_journey(
                    journey=journey,
                    policy=self.policy,
                    at=self.at,
                )
            )
            self._create_request_candidates(
                SMALL_CANDIDATE_COUNT,
                LARGE_CANDIDATE_COUNT,
            )
            large_results, large_queries = self._capture_queries(
                lambda: compatible_requests_for_journey(
                    journey=journey,
                    policy=self.policy,
                    at=self.at,
                )
            )

        assert len(small_results) == SMALL_CANDIDATE_COUNT
        assert len(large_results) == LARGE_CANDIDATE_COUNT
        assert small_queries == large_queries
        assert large_queries <= 3
        assert provider.call_counts["directions"] == 0

    def test_public_serialization_adds_no_query_per_candidate(self):
        """Phase 2B added a covered-leg summary to every candidate row.

        The legs and their endpoint Locations are already prefetched by
        discovery, so rendering the richer payload must stay at zero further
        queries no matter how many candidates come back.
        """

        traveler = _user(40_000, "serialization-journey-owner")
        _approve_kyc(traveler, 40_000)
        journey = _journey(
            traveler=traveler,
            origin=self.origin,
            destination=self.destination,
            depart_at=self.depart_at,
            sequence=40_000,
        )
        provider = DeterministicFixtureRouteProvider()
        self._create_request_candidates(0, SMALL_CANDIDATE_COUNT)

        with patch("apps.matching.discovery.get_route_provider", return_value=provider):
            small = compatible_requests_for_journey(
                journey=journey,
                policy=self.policy,
                at=self.at,
            )
            with CaptureQueriesContext(connection) as small_queries:
                small_payload = [
                    row.as_public_dict(include_recommendation=False) for row in small
                ]
            self._create_request_candidates(
                SMALL_CANDIDATE_COUNT,
                LARGE_CANDIDATE_COUNT,
            )
            large = compatible_requests_for_journey(
                journey=journey,
                policy=self.policy,
                at=self.at,
            )
            with CaptureQueriesContext(connection) as large_queries:
                large_payload = [
                    row.as_public_dict(include_recommendation=False) for row in large
                ]

        assert len(small_payload) == SMALL_CANDIDATE_COUNT
        assert len(large_payload) == LARGE_CANDIDATE_COUNT
        assert len(small_queries) == 0
        assert len(large_queries) == 0
        assert large_payload[0]["journey"]["covered_legs"]
        assert large_payload[0]["journey"]["start_leg_id"]

    @override_settings(ROUTE_PROVIDER_CACHE_NAMESPACE="phase2-performance-tests")
    def test_identical_off_route_candidates_share_cache_misses_within_call_budget(self):
        traveler = _user(30_000, "cached-journey-owner")
        _approve_kyc(traveler, 30_000)
        route_metadata = {
            "corridor_points": [
                [float(self.origin.latitude), float(self.origin.longitude)],
                [float(self.destination.latitude), float(self.destination.longitude)],
            ]
        }
        journey = _journey(
            traveler=traveler,
            origin=self.origin,
            destination=self.destination,
            depart_at=self.depart_at,
            sequence=30_000,
            route_metadata=route_metadata,
        )
        pickup = _location("Cached pickup", "36.002000", "3.050000")
        delivery = _location("Cached delivery", "35.998000", "3.150000")
        self._create_request_candidates(
            0,
            LARGE_CANDIDATE_COUNT,
            pickup=pickup,
            delivery=delivery,
        )
        raw_provider = DeterministicFixtureRouteProvider()
        budgeted_provider = BudgetedRouteProvider(raw_provider, max_calls=9)
        cached_provider = CachedRouteProvider(budgeted_provider)
        caches["routing"].clear()

        with patch(
            "apps.matching.discovery.get_route_provider",
            return_value=cached_provider,
        ):
            results = compatible_requests_for_journey(
                journey=journey,
                policy=self.policy,
                at=self.at,
            )

        assert len(results) == LARGE_CANDIDATE_COUNT
        assert raw_provider.call_counts["directions"] == 9
        assert budgeted_provider.calls == 9
