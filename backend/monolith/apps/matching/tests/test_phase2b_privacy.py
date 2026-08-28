"""Phase 2B adversarial privacy regression.

The Phase 2 privacy tests asserted that forbidden *key names* and literal
coordinate *strings* were absent. That is structurally incapable of catching a
leak carried by derived geometry, and the Phase 2 fixtures pinned pickup to a
route node so the leaking path was never exercised at all.

These tests instead run the actual inference attack: place pickup off the
corridor, read every pre-funding surface as the counterparty, and try to solve
for the exact point using only published values plus the corridor the attacker
already owns. The internal/admin payload is attacked with the same solver as a
control, so a regression that re-publishes route positions or exact detour
metres fails here immediately rather than passing a vacuous key check.
"""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.locations.serializers import PublicLocationSerializer
from apps.matching.compatibility import PUBLIC_LOCATION_SUMMARY_FIELDS
from apps.matching.models import Match, Offer
from apps.routing.geometry import GeoPoint, haversine_meters, project_to_corridor
from apps.trips.models import Journey, JourneyLeg

from .test_phase2_matching import _approve_kyc, _location, _request, _user


#: The Location coarse quantum is 0.1 degrees, i.e. ~11.1 km of latitude and
#: ~8.9 km of longitude at this latitude. Nothing published before funding may
#: resolve a private point materially inside that cell.
COARSE_QUANTUM_DEGREES = Decimal("0.1")

CORRIDOR_ORIGIN = GeoPoint(36.700000, 4.000000)
CORRIDOR_DESTINATION = GeoPoint(36.800000, 4.200000)
SECRET_PICKUP = GeoPoint(36.755000, 4.085000)

#: Keys that must never appear anywhere in a counterparty payload. The first
#: group is exact location data; the rest is the derived geometry that defeats
#: it, plus the internal diagnostics and tuning values.
FORBIDDEN_KEYS = frozenset(
    {
        "latitude",
        "longitude",
        "normalized_label",
        "private_label",
        "provider",
        "provider_place_id",
        "provider_metadata",
        "pickup_route_position",
        "delivery_route_position",
        "pickup_detour_meters",
        "delivery_detour_meters",
        "estimated_added_distance_meters",
        "estimated_added_duration_seconds",
        "pickup_added_duration_seconds",
        "matched_distance_meters",
        "matched_distance_method",
        "distance_components",
        "capacity_remaining_by_leg",
        "checks",
        "ranking",
        "ranking_snapshot",
        "detour_adjustment_cents",
        "urgency_adjustment_cents",
        "route_metadata",
        "polyline",
        "corridor_points",
    }
)


def _grid_points(
    *,
    centre: GeoPoint,
    half_degrees: float = 0.05,
    step_degrees: float = 0.001,
) -> list[GeoPoint]:
    """Every candidate point inside the published coarse cell."""

    points: list[GeoPoint] = []
    steps = int(round(half_degrees / step_degrees))
    for lat_step in range(-steps, steps + 1):
        for lon_step in range(-steps, steps + 1):
            points.append(
                GeoPoint(
                    centre.latitude + lat_step * step_degrees,
                    centre.longitude + lon_step * step_degrees,
                )
            )
    return points


def _solve(constraint) -> list[GeoPoint]:
    """Return the candidates inside the coarse cell that survive `constraint`."""

    corridor = (CORRIDOR_ORIGIN, CORRIDOR_DESTINATION)
    survivors = []
    for point in _grid_points(centre=GeoPoint(36.8, 4.1)):
        projection = project_to_corridor(point, corridor)
        if constraint(projection):
            survivors.append(point)
    return survivors


def _spread_meters(points: list[GeoPoint]) -> int:
    if len(points) < 2:
        return 0
    latitudes = [point.latitude for point in points]
    longitudes = [point.longitude for point in points]
    return haversine_meters(
        GeoPoint(min(latitudes), min(longitudes)),
        GeoPoint(max(latitudes), max(longitudes)),
    )


def _closest_meters(points: list[GeoPoint]) -> int:
    if not points:
        return 10**9
    return min(haversine_meters(point, SECRET_PICKUP) for point in points)


def _furthest_meters(points: list[GeoPoint]) -> int:
    if not points:
        return 0
    return max(haversine_meters(point, SECRET_PICKUP) for point in points)


def _walk(payload, callback) -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            callback(key, value)
            _walk(value, callback)
    elif isinstance(payload, list):
        for value in payload:
            _walk(value, callback)


@override_settings(ROUTE_PROVIDER_CLASS="")
class Phase2BDerivedGeometryPrivacyTests(TestCase):
    """Off-corridor pickup, known exact coordinates, every public surface."""

    def setUp(self):
        self.at = timezone.now()
        self.sender = _user("phase2b-sender@example.com")
        self.traveler = _user("phase2b-traveler@example.com")
        self.harvester = _user("phase2b-harvester@example.com")
        self.admin = _user("phase2b-admin@example.com", is_staff=True)
        self.admin.is_superuser = True
        self.admin.save(update_fields=["is_superuser"])
        _approve_kyc(self.traveler, "phase2b-traveler")
        _approve_kyc(self.harvester, "phase2b-harvester")

        self.corridor_origin = _location(
            "Corridor origin",
            "36.700000",
            "4.000000",
            owner=self.traveler,
        )
        self.corridor_destination = _location(
            "Corridor destination",
            "36.800000",
            "4.200000",
            owner=self.traveler,
        )
        # Deliberately OFF the corridor: the Phase 2 fixture pinned pickup to a
        # route node, where position is an integer 0 and detour is 0, so the
        # leaking branch was never exercised.
        self.pickup = _location(
            "Secret home",
            "36.755000",
            "4.085000",
            owner=self.sender,
        )
        self.dropoff = _location(
            "Secret office",
            "36.795000",
            "4.190000",
            owner=self.sender,
        )

        self.journey = Journey.objects.create(
            traveler=self.traveler,
            start_location=self.corridor_origin,
            destination_location=self.corridor_destination,
            status=Journey.Status.ACTIVE,
            published_at=self.at,
        )
        self.leg = JourneyLeg.objects.create(
            journey=self.journey,
            position=0,
            mode=JourneyLeg.Mode.DRIVE,
            origin=self.corridor_origin,
            destination=self.corridor_destination,
            depart_at=self.at + timedelta(hours=2),
            arrive_at=self.at + timedelta(hours=6),
            capacity_kg=Decimal("20.00"),
            distance_meters=30_000,
        )
        self.delivery_request = _request(
            sender=self.sender,
            pickup=self.pickup,
            delivery=self.dropoff,
            ready_start=self.at,
            ready_end=self.at + timedelta(hours=8),
            deadline=self.at + timedelta(hours=12),
        )

    def _client(self, user) -> APIClient:
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def _assert_no_forbidden_keys(self, payload, surface: str) -> None:
        found = []

        def check(key, _value):
            if key in FORBIDDEN_KEYS:
                found.append(key)

        _walk(payload, check)
        assert not found, f"{surface} leaked internal keys {sorted(set(found))}"
        text = json.dumps(payload, default=str)
        for secret in ("36.755000", "4.085000", "36.795000", "4.190000"):
            assert secret not in text, f"{surface} leaked exact coordinate {secret}"
        for secret in (
            "SECRET normalized",
            "SECRET private address",
            "SECRET-place",
            "SECRET provider address",
        ):
            assert secret not in text, f"{surface} leaked {secret}"

    # -- the inference attack ------------------------------------------------

    def test_public_payload_cannot_resolve_below_the_coarse_cell(self):
        """A traveler who owns the corridor still cannot locate the sender."""

        response = self._client(self.traveler).get(
            reverse("matches-compatible-requests-v1"),
            {"journey_id": self.journey.pk},
        )
        assert response.status_code == 200, response.data
        assert response.data["count"] == 1
        compatibility = response.data["results"][0]["compatibility"]
        self._assert_no_forbidden_keys(response.data, "compatible-requests")

        # Everything the payload says about where the pickup is:
        band = compatibility["pickup_detour_band"]
        assert band == "under_5km"
        bounds = {"under_5km": (0, 5_000), "5_15km": (5_000, 15_000)}[band]

        survivors = _solve(
            lambda projection: bounds[0]
            <= projection.distance_meters * 2
            <= bounds[1]
        )

        # The published band is a wide corridor-parallel strip: it survives a
        # large, spatially diffuse candidate set spanning the coarse cell.
        assert len(survivors) > 1_000
        assert _spread_meters(survivors) >= 8_000, _spread_meters(survivors)
        assert _furthest_meters(survivors) >= 4_000, _furthest_meters(survivors)

    def test_the_same_solver_still_pinpoints_the_internal_admin_payload(self):
        """Control: the harness detects a leak when one is present.

        `GET /matches/explain` is IsAdminUser and deliberately keeps the
        diagnostics. Feeding its route position and exact detour to the same
        solver collapses the candidate set to a few hundred metres, which is
        exactly what a counterparty must never be able to do.
        """

        response = self._client(self.admin).get(
            reverse("matches-explain-v1"),
            {
                "parcel_id": self.delivery_request.pk,
                "journey_id": self.journey.pk,
            },
        )
        assert response.status_code == 200, response.data
        compatibility = response.data["compatibility"]
        assert compatibility["pickup_route_position"] is not None
        assert compatibility["pickup_detour_meters"] > 0
        assert compatibility["checks"]
        assert compatibility["distance_components"]
        assert compatibility["capacity_remaining_by_leg"]
        assert response.data["ranking"]["factors"]

        position = compatibility["pickup_route_position"]
        detour = compatibility["pickup_detour_meters"]
        survivors = _solve(
            lambda projection: abs(projection.distance_meters * 2 - detour) <= 400
            and abs(projection.progress - position) <= 0.01
        )

        assert survivors, "the control attack must reproduce the original leak"
        assert _closest_meters(survivors) <= 400, _closest_meters(survivors)
        assert _spread_meters(survivors) <= 2_000, _spread_meters(survivors)

    # -- surface sweep -------------------------------------------------------

    def test_every_pre_funding_surface_is_free_of_derived_geometry(self):
        sender = self._client(self.sender)
        traveler = self._client(self.traveler)

        journeys = sender.get(
            reverse("matches-compatible-journeys-v1"),
            {"parcel_id": self.delivery_request.pk},
        )
        requests = traveler.get(
            reverse("matches-compatible-requests-v1"),
            {"journey_id": self.journey.pk},
        )
        quote = sender.post(
            reverse("matches-quote-v1"),
            {
                "parcel_id": self.delivery_request.pk,
                "journey_id": self.journey.pk,
            },
            format="json",
        )
        assert journeys.status_code == 200, journeys.data
        assert requests.status_code == 200, requests.data
        assert quote.status_code == 200, quote.data
        self._assert_no_forbidden_keys(journeys.data, "compatible-journeys")
        self._assert_no_forbidden_keys(requests.data, "compatible-requests")
        self._assert_no_forbidden_keys(quote.data, "quote")

        candidate = journeys.data["results"][0]
        proposal = sender.post(
            reverse("matches-propose-v1"),
            {
                "parcel_id": self.delivery_request.pk,
                "journey_id": self.journey.pk,
                "start_leg_id": candidate["journey"]["start_leg_id"],
                "end_leg_id": candidate["journey"]["end_leg_id"],
                "traveler_reward_eur_cents": candidate["pricing"][
                    "recommended_reward_eur_cents"
                ],
            },
            format="json",
        )
        assert proposal.status_code == 201, proposal.data
        self._assert_no_forbidden_keys(proposal.data, "propose")
        match_id = proposal.data["match"]

        accepted = traveler.post(
            reverse("offers-accept", args=[proposal.data["id"]]),
            format="json",
        )
        assert accepted.status_code == 201, accepted.data
        deal_id = accepted.data["id"]
        # Acceptance is explicitly not funding.
        assert accepted.data["funded_at"] is None
        self._assert_no_forbidden_keys(accepted.data, "offers/accept")

        surfaces = {
            "matches-list(sender)": sender.get(reverse("matches-list")),
            "matches-list(traveler)": traveler.get(reverse("matches-list")),
            "matches-detail": traveler.get(reverse("matches-detail", args=[match_id])),
            "matches-offers": traveler.get(
                reverse("matches-offers", args=[match_id])
            ),
            "deals-list": traveler.get(reverse("deals-list")),
            "deals-detail": traveler.get(reverse("deals-detail", args=[deal_id])),
        }
        for name, response in surfaces.items():
            assert response.status_code == 200, (name, response.data)
            self._assert_no_forbidden_keys(response.data, name)

    def test_persisted_snapshots_keep_the_internal_form_for_audit(self):
        """Storage is unchanged; only serialization is narrowed."""

        candidate = self._client(self.sender).get(
            reverse("matches-compatible-journeys-v1"),
            {"parcel_id": self.delivery_request.pk},
        ).data["results"][0]
        proposal = self._client(self.sender).post(
            reverse("matches-propose-v1"),
            {
                "parcel_id": self.delivery_request.pk,
                "journey_id": self.journey.pk,
                "start_leg_id": candidate["journey"]["start_leg_id"],
                "end_leg_id": candidate["journey"]["end_leg_id"],
                "traveler_reward_eur_cents": candidate["pricing"][
                    "recommended_reward_eur_cents"
                ],
            },
            format="json",
        )
        assert proposal.status_code == 201, proposal.data

        match = Match.objects.get(pk=proposal.data["match"])
        offer = Offer.objects.get(pk=proposal.data["id"])
        stored_compatibility = match.compatibility_snapshot
        stored_terms = offer.terms_snapshot

        assert stored_compatibility["pickup_route_position"] is not None
        assert stored_compatibility["pickup_detour_meters"] > 0
        assert stored_compatibility["checks"]
        assert stored_compatibility["capacity_remaining_by_leg"]
        assert match.ranking_snapshot["factors"]
        assert stored_terms["policy"]["ranking"]["weights"]
        assert stored_terms["compatibility"]["distance_components"]
        assert stored_terms["pricing"]["matched_distance_meters"] > 0
        assert stored_terms["ranking"]["factors"]

    def test_a_traveler_cannot_bulk_harvest_other_senders(self):
        """The severe path: one journey, many unrelated senders, one call."""

        for index in range(3):
            other_sender = _user(f"phase2b-victim-{index}@example.com")
            pickup = _location(
                f"Victim home {index}",
                f"36.75{index}000",
                f"4.08{index}000",
                owner=other_sender,
            )
            dropoff = _location(
                f"Victim office {index}",
                "36.795000",
                "4.190000",
                owner=other_sender,
            )
            _request(
                sender=other_sender,
                pickup=pickup,
                delivery=dropoff,
                ready_start=self.at,
                ready_end=self.at + timedelta(hours=8),
                deadline=self.at + timedelta(hours=12),
            )

        response = self._client(self.traveler).get(
            reverse("matches-compatible-requests-v1"),
            {"journey_id": self.journey.pk},
        )

        assert response.status_code == 200, response.data
        assert response.data["count"] == 4
        self._assert_no_forbidden_keys(response.data, "bulk compatible-requests")
        for row in response.data["results"]:
            # The traveler cannot propose a price, so the detour-bearing
            # recommendation is withheld in this direction entirely.
            assert "recommended_reward_eur_cents" not in row["pricing"]
            assert "recommended_economics" not in row["pricing"]
            assert row["pricing"]["minimum_reward_eur_cents"] > 0

    def test_capacity_details_are_never_published(self):
        response = self._client(self.sender).get(
            reverse("matches-compatible-journeys-v1"),
            {"parcel_id": self.delivery_request.pk},
        )
        compatibility = response.data["results"][0]["compatibility"]

        assert compatibility["capacity_available_on_every_covered_leg"] is True
        text = json.dumps(response.data, default=str)
        # 20.00 kg total capacity must not be inferable from the payload.
        assert "remaining_kg" not in text
        assert "reserved_kg" not in text
        assert "capacity_kg" not in text

    def test_public_leg_summary_tracks_the_public_location_serializer(self):
        """Fail loudly if PublicLocationSerializer grows a field this mirror lacks."""

        serializer_fields = set(PublicLocationSerializer.Meta.fields) - {"created_at"}

        assert set(PUBLIC_LOCATION_SUMMARY_FIELDS) == serializer_fields

        response = self._client(self.sender).get(
            reverse("matches-compatible-journeys-v1"),
            {"parcel_id": self.delivery_request.pk},
        )
        leg = response.data["results"][0]["compatibility"]["covered_legs"][0]
        assert set(leg["origin"]) == set(PUBLIC_LOCATION_SUMMARY_FIELDS)
        assert set(leg["destination"]) == set(PUBLIC_LOCATION_SUMMARY_FIELDS)

    def test_journey_legs_publish_a_distance_band_to_non_owners(self):
        """Found while auditing: routed leg distance is endpoint-derived too.

        The leg's routed distance and duration are measured between its exact
        endpoints. At metre precision they narrow one coarse endpoint to an arc
        around the other, so only the owner sees them.
        """

        JourneyLeg.objects.filter(pk=self.leg.pk).update(
            distance_meters=21_004,
            route_duration_seconds=1_800,
        )
        owner = self._client(self.traveler).get(
            reverse("journeys-detail", args=[self.journey.pk])
        )
        other = self._client(self.harvester).get(
            reverse("journeys-detail", args=[self.journey.pk])
        )

        assert owner.status_code == 200, owner.data
        assert other.status_code == 200, other.data
        owner_leg = owner.data["legs"][0]
        other_leg = other.data["legs"][0]

        assert owner_leg["distance_meters"] == 21_004
        assert owner_leg["route_duration_seconds"] == 1_800
        assert "distance_meters" not in other_leg
        assert "route_duration_seconds" not in other_leg
        assert other_leg["distance_band"]["label"] == "under_100km"

    def test_timing_estimates_are_leg_windows_not_interpolated_instants(self):
        """An interpolated instant is a metre-resolution route position."""

        response = self._client(self.traveler).get(
            reverse("matches-compatible-requests-v1"),
            {"journey_id": self.journey.pk},
        )
        compatibility = response.data["results"][0]["compatibility"]

        assert compatibility["estimated_pickup_window"] == {
            "start": self.leg.depart_at.isoformat(),
            "end": self.leg.arrive_at.isoformat(),
        }
        assert compatibility["estimated_delivery_window"] == {
            "start": self.leg.depart_at.isoformat(),
            "end": self.leg.arrive_at.isoformat(),
        }
        assert "pickup_at" not in compatibility
        assert "delivery_at" not in compatibility
