"""L3A: routes for everyone — sea legs, stop options, item rules and pausing.

What these tests hold the backend to (spec 5.1 to 5.7, plan L3A):

* The mode of a leg is decided by geography and the "Sea legs" switch, never
  by the client: every launch-country pair, every crossing state.
* A ferry ticket is a ticket. The same rule that guards flight legs decides
  publication, the proof upload and the server-authored ``proof_state``.
* Stop options are validated against the route they belong to, and the
  traveler's handover note never leaves the traveler before funding.
* A journey can be paused by its owner or by staff, and each pause can only be
  lifted by whoever set it.
* Sea crossings are staff configuration with an audit row per change, and the
  reviewed initial list seeds idempotently without ever undoing staff work.
"""

from __future__ import annotations

import json
import tempfile
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from itertools import product
from pathlib import Path
from unittest.mock import patch

from django.core.exceptions import PermissionDenied
from django.core.management import CommandError, call_command
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.admin_panel.models import AdminAuditLog
from apps.admin_panel.permissions import AdminRole, assign_admin_roles
from apps.core.marketplace_policy import InvalidMarketplacePolicy
from apps.locations.management.commands.seed_sea_crossings import DEFAULT_FILE
from apps.locations.models import Place, PlaceAlternateName, SeaCrossing
from apps.locations.sea_crossings import (
    SeaCrossingError,
    activate_crossing,
    create_crossing,
    deactivate_crossing,
    great_circle_meters,
)
from apps.trips.models import Journey, JourneyLegProof, JourneyStopDetail
from apps.trips.services import JourneyDomainError, pause_journey, resume_journey
from apps.trips.transport_rules import (
    MODE_UNAVAILABLE_CODE,
    SEA_CROSSING_UNAVAILABLE,
    SEA_ENDPOINT_NOT_PORT_CITY,
    SEA_LEGS_DISABLED,
    check_leg_mode,
    mode_violation_message,
    sea_legs_enabled,
)

from .sea_world import DRIVE, FLIGHT, MARSEILLE_ALGIERS_METERS, SEA, SeaWorld


def client_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def staff(world: SeaWorld, email: str, *roles: str):
    user = world.person(email, verified=False)
    user.is_staff = True
    user.save(update_fields=["is_staff"])
    assign_admin_roles(user, roles)
    return user


# ---------------------------------------------------------------------------
# The mode rule
# ---------------------------------------------------------------------------


class TransportModeMatrixTests(SeaWorld, TestCase):
    def setUp(self):
        self.build_sea_world()
        self.by_country = {
            "DZ": self.algiers,
            "FR": self.paris,
            "ES": self.barcelona,
            "DE": self.berlin,
        }

    def mode(self, mode, origin, destination):
        return check_leg_mode(position=0, mode=mode, origin=origin, destination=destination)

    def test_a_road_leg_stays_on_its_road_network_for_every_launch_country_pair(self):
        europe = {"FR", "ES", "DE"}
        for switch in (False, True):
            self.set_sea_switch(switch)
            for origin, destination in product(self.by_country, repeat=2):
                with self.subTest(switch=switch, origin=origin, destination=destination):
                    violation = self.mode(
                        DRIVE, self.by_country[origin], self.by_country[destination]
                    )
                    if origin == destination or {origin, destination} <= europe:
                        assert violation is None
                        continue
                    # The road refusal is exactly what it was before sea legs.
                    assert violation.as_payload() == {
                        "leg_position": 0,
                        "declared_mode": DRIVE,
                        "required_mode": FLIGHT,
                        "origin_country": origin,
                        "destination_country": destination,
                    }

    def test_geography_never_refuses_a_flight(self):
        for switch in (False, True):
            self.set_sea_switch(switch)
            for origin, destination in product(self.by_country.values(), repeat=2):
                with self.subTest(switch=switch, origin=origin.country_id, destination=destination.country_id):
                    assert self.mode(FLIGHT, origin, destination) is None

    def test_a_sea_leg_for_every_launch_country_pair(self):
        """Each country's port city (Germany has none), switch on."""

        self.set_sea_switch(True)
        ports = {"DZ": self.algiers, "FR": self.marseille, "ES": self.barcelona, "DE": self.berlin}
        open_lines = {("FR", "DZ"), ("DZ", "FR")}
        for origin, destination in product(ports, repeat=2):
            with self.subTest(origin=origin, destination=destination):
                violation = self.mode(SEA, ports[origin], ports[destination])
                if (origin, destination) in open_lines:
                    assert violation is None
                elif "DE" in (origin, destination):
                    assert violation.reason == SEA_ENDPOINT_NOT_PORT_CITY
                else:
                    assert violation.reason == SEA_CROSSING_UNAVAILABLE

    def test_no_sea_leg_exists_while_the_switch_is_off(self):
        violation = self.mode(SEA, self.marseille, self.algiers)

        assert violation is not None
        assert violation.reason == SEA_LEGS_DISABLED
        payload = violation.as_payload()
        assert payload["reason"] == SEA_LEGS_DISABLED
        # A sea refusal has no mode that would work, so it names none.
        assert "required_mode" not in payload
        assert mode_violation_message(violation) == (
            "Leg 0 cannot be a sea leg: sea legs are not available at the moment."
        )

    def test_an_active_crossing_opens_its_own_direction(self):
        self.set_sea_switch(True)

        assert self.mode(SEA, self.marseille, self.algiers) is None
        assert self.mode(SEA, self.algiers, self.marseille) is None

    def test_two_ports_without_a_live_line_have_no_crossing(self):
        self.set_sea_switch(True)

        # Barcelona and Oran are ports; their line is switched off, and the
        # reverse direction was never created.
        for origin, destination in ((self.barcelona, self.oran), (self.oran, self.barcelona)):
            with self.subTest(origin=origin.name):
                assert self.mode(SEA, origin, destination).reason == SEA_CROSSING_UNAVAILABLE
        # Marseille and Oran are both ports, but no line joins them.
        assert self.mode(SEA, self.marseille, self.oran).reason == SEA_CROSSING_UNAVAILABLE

    def test_a_city_without_a_line_is_not_a_port(self):
        self.set_sea_switch(True)

        assert self.mode(SEA, self.lyon, self.algiers).reason == SEA_ENDPOINT_NOT_PORT_CITY
        assert self.mode(SEA, self.marseille, self.constantine).reason == SEA_ENDPOINT_NOT_PORT_CITY

    def test_an_airport_cannot_end_a_sea_leg(self):
        self.set_sea_switch(True)

        assert self.mode(SEA, self.marseille, self.alg).reason == SEA_ENDPOINT_NOT_PORT_CITY
        assert self.mode(SEA, self.cdg, self.algiers).reason == SEA_ENDPOINT_NOT_PORT_CITY

    def test_a_retired_port_city_fails_closed(self):
        self.set_sea_switch(True)
        self.marseille.active = False
        self.marseille.save(update_fields=["active"])

        assert self.mode(SEA, self.marseille, self.algiers).reason == SEA_ENDPOINT_NOT_PORT_CITY

    def test_an_unreadable_settings_revision_keeps_sea_legs_off(self):
        self.set_sea_switch(True)
        with (
            patch(
                "apps.core.marketplace_policy.marketplace_policy",
                side_effect=InvalidMarketplacePolicy("broken"),
            ),
            self.assertLogs("apps.trips", level="WARNING"),
        ):
            assert sea_legs_enabled() is False
            assert self.mode(SEA, self.marseille, self.algiers).reason == SEA_LEGS_DISABLED


# ---------------------------------------------------------------------------
# Sea legs through the journey API
# ---------------------------------------------------------------------------


class RouteApiMixin(SeaWorld):
    def setUp(self):
        self.build_sea_world()
        self.owner = self.person("l3a-owner@example.com")
        self.client = client_for(self.owner)
        self.depart = self.now + timedelta(days=5)

    def leg(self, mode, origin, destination, index: int = 0, **overrides) -> dict:
        depart = self.depart + timedelta(hours=6 * index)
        leg = {
            "position": index,
            "mode": mode,
            "origin_place_id": origin.pk,
            "destination_place_id": destination.pk,
            "depart_at": depart.isoformat(),
            "arrive_at": (depart + timedelta(hours=4)).isoformat(),
            "capacity_kg": "10.00",
        }
        if mode == FLIGHT:
            leg["flight_number"] = "AH1006"
        leg.update(overrides)
        return leg

    def route(self, *legs: tuple, **extra) -> dict:
        built = [self.leg(*spec, index=index) for index, spec in enumerate(legs)]
        return {
            "start_place_id": legs[0][1].pk,
            "destination_place_id": legs[-1][2].pk,
            "notes": "",
            "legs": built,
            **extra,
        }

    def create(self, payload: dict):
        return self.client.post(reverse("journeys-list-create"), payload, format="json")

    def created(self, payload: dict) -> Journey:
        response = self.create(payload)
        assert response.status_code == 201, response.data
        return Journey.objects.get(pk=response.data["id"])

    def publish(self, journey: Journey):
        return self.client.post(reverse("journeys-publish", args=(journey.pk,)))

    def detail(self, journey: Journey, *, user=None):
        client = self.client if user is None else client_for(user)
        return client.get(reverse("journeys-detail", args=(journey.pk,)))


class SeaJourneyApiTests(RouteApiMixin, APITestCase):
    def test_a_sea_leg_is_refused_while_the_switch_is_off(self):
        response = self.create(self.route((SEA, self.marseille, self.algiers)))

        assert response.status_code == 400, response.data
        assert response.data["code"] == [MODE_UNAVAILABLE_CODE]
        assert response.data["reason"] == [SEA_LEGS_DISABLED]
        assert "required_mode" not in response.data
        assert Journey.objects.count() == 0

    def test_a_sea_leg_needs_a_live_line_between_two_ports(self):
        self.set_sea_switch(True)

        for (origin, destination), reason in (
            ((self.barcelona, self.oran), SEA_CROSSING_UNAVAILABLE),
            ((self.lyon, self.algiers), SEA_ENDPOINT_NOT_PORT_CITY),
        ):
            with self.subTest(origin=origin.name):
                response = self.create(self.route((SEA, origin, destination)))
                assert response.status_code == 400, response.data
                assert response.data["reason"] == [reason]
        assert Journey.objects.count() == 0

    def test_a_road_refusal_still_names_the_mode_that_works(self):
        self.set_sea_switch(True)

        response = self.create(self.route((DRIVE, self.marseille, self.algiers)))

        assert response.status_code == 400, response.data
        assert response.data["required_mode"] == [FLIGHT]
        assert "reason" not in response.data

    def test_a_sea_leg_cannot_carry_a_flight_number(self):
        self.set_sea_switch(True)
        payload = self.route((SEA, self.marseille, self.algiers))
        payload["legs"][0]["flight_number"] = "AH1006"

        response = self.create(payload)

        assert response.status_code == 400, response.data
        assert "Sea legs cannot have a flight number." in str(response.data)

    def test_a_sea_leg_takes_its_distance_from_the_crossing(self):
        self.set_sea_switch(True)

        journey = self.created(self.route((SEA, self.marseille, self.algiers)))

        leg = journey.legs.get()
        assert leg.mode == SEA
        assert leg.distance_meters == MARSEILLE_ALGIERS_METERS
        assert leg.route_provider == "sea_crossing"
        assert leg.route_profile == "sea"
        assert leg.route_metadata == {"sea_crossing_id": self.marseille_algiers.pk}
        payload = self.detail(journey).data["legs"][0]
        assert payload["proof_required"] is True
        assert payload["proof_state"] == "missing"

    def test_a_ferry_ticket_gates_publication_like_a_flight_ticket(self):
        self.set_sea_switch(True)
        journey = self.created(
            self.route(
                (DRIVE, self.lyon, self.marseille),
                (SEA, self.marseille, self.algiers),
                (DRIVE, self.algiers, self.setif),
            )
        )
        sea_leg = journey.legs.get(mode=SEA)
        reviewer = self.person("l3a-reviewer@example.com", verified=False)

        def state() -> list[str]:
            return [leg["proof_state"] for leg in self.detail(journey).data["legs"]]

        assert state() == ["not_required", "missing", "not_required"]
        response = self.publish(journey)
        assert response.status_code == 409, response.data
        assert response.data["code"] == "sea_proof_not_approved"

        rejected = self.ticket(sea_leg, JourneyLegProof.Status.REJECTED, reviewer=reviewer)
        assert state()[1] == "rejected"
        pending = self.ticket(sea_leg, JourneyLegProof.Status.PENDING)
        # A proof that can still be approved outranks an older refusal.
        assert state()[1] == "pending"
        assert self.publish(journey).data["code"] == "sea_proof_not_approved"

        JourneyLegProof.objects.filter(pk=pending.pk).update(
            status=JourneyLegProof.Status.APPROVED, reviewer=reviewer, reviewed_at=self.now
        )
        assert state()[1] == "approved"
        response = self.publish(journey)
        assert response.status_code == 200, response.data
        assert rejected.pk != pending.pk

    def test_publication_rechecks_the_sea_switch(self):
        self.set_sea_switch(True)
        journey = self.created(self.route((SEA, self.marseille, self.algiers)))
        self.ticket(journey.legs.get(), JourneyLegProof.Status.APPROVED)
        self.set_sea_switch(False)

        response = self.publish(journey)

        assert response.status_code == 409, response.data
        assert response.data["code"] == MODE_UNAVAILABLE_CODE
        journey.refresh_from_db()
        assert journey.status == Journey.Status.DRAFT

    def test_a_road_leg_takes_no_ticket(self):
        journey = self.created(self.route((DRIVE, self.algiers, self.setif)))
        leg = journey.legs.get()

        response = self.client.post(
            reverse(
                "journey-leg-proof-create",
                kwargs={"journey_pk": journey.pk, "leg_pk": leg.pk},
            )
        )

        assert response.status_code == 400, response.data
        assert response.data["code"] == "proof_not_required"
        assert self.detail(journey).data["legs"][0]["proof_required"] is False


# ---------------------------------------------------------------------------
# Stop options, item rules and secondary capacity
# ---------------------------------------------------------------------------


class RouteOptionsApiTests(RouteApiMixin, APITestCase):
    def three_stop_route(self, **extra) -> dict:
        return self.route(
            (DRIVE, self.algiers, self.setif), (DRIVE, self.setif, self.constantine), **extra
        )

    def test_every_stop_is_published_with_what_it_really_accepts(self):
        journey = self.created(
            self.three_stop_route(
                stops=[{"position": 1, "accepts_pickup": False, "handover_note": "Gate B"}]
            )
        )

        stops = self.detail(journey).data["stops"]

        assert [stop["position"] for stop in stops] == [0, 1, 2]
        assert [stop["place_id"] for stop in stops] == [
            self.algiers.pk,
            self.setif.pk,
            self.constantine.pk,
        ]
        # Nothing can be dropped where the trip starts or picked up where it ends.
        assert [(s["accepts_pickup"], s["accepts_dropoff"]) for s in stops] == [
            (True, False),
            (False, True),
            (False, True),
        ]
        assert stops[1]["handover_note"] == "Gate B"

    def test_a_stop_left_at_its_defaults_is_not_stored(self):
        journey = self.created(self.three_stop_route(stops=[{"position": 1}]))

        assert not JourneyStopDetail.objects.filter(journey=journey).exists()

    def test_the_handover_note_and_window_stay_with_the_traveler(self):
        legs = self.three_stop_route()["legs"]
        arrives = legs[0]["arrive_at"]
        leaves = legs[1]["depart_at"]
        journey = self.created(
            self.three_stop_route(
                stops=[
                    {
                        "position": 1,
                        "handover_note": "Café by the station, ask for Karim",
                        "window_start": arrives,
                        "window_end": leaves,
                    }
                ]
            )
        )
        assert self.publish(journey).status_code == 200
        stranger = self.person("l3a-stranger@example.com")

        owner_view = self.detail(journey).data
        public_view = self.detail(journey, user=stranger)

        assert owner_view["stops"][1]["window_start"] is not None
        assert public_view.status_code == 200, public_view.data
        for stop in public_view.data["stops"]:
            assert set(stop) == {"position", "place_id", "accepts_pickup", "accepts_dropoff"}
        assert "Karim" not in json.dumps(public_view.data, default=str)
        assert "pause" not in public_view.data

    def test_stop_options_are_checked_against_the_route(self):
        legs = self.three_stop_route()["legs"]
        arrive_1 = legs[0]["arrive_at"]
        depart_1 = legs[1]["depart_at"]
        early = (self.depart - timedelta(hours=1)).isoformat()
        cases = {
            "stop_position_unknown": [{"position": 3}],
            "stop_position_duplicated": [{"position": 1}, {"position": 1, "accepts_pickup": False}],
            "first_stop_dropoff_only": [{"position": 0, "accepts_pickup": False}],
            "last_stop_pickup_only": [{"position": 2, "accepts_dropoff": False}],
            "stop_window_incomplete": [{"position": 1, "window_start": arrive_1}],
            "stop_window_invalid": [
                {"position": 1, "window_start": depart_1, "window_end": arrive_1}
            ],
            "stop_window_outside_stop": [
                {"position": 1, "window_start": early, "window_end": depart_1}
            ],
        }
        too_long = self.create(
            self.three_stop_route(stops=[{"position": 1, "handover_note": "x" * 281}])
        )
        assert too_long.status_code == 400, too_long.data
        assert "stops" in too_long.data
        for reason, stops in cases.items():
            with self.subTest(reason=reason):
                response = self.create(self.three_stop_route(stops=stops))
                assert response.status_code == 400, response.data
                assert response.data["code"] == ["journey_stop_invalid"]
                assert response.data["reason"] == [reason]
        assert Journey.objects.count() == 0

    def test_a_stop_that_serves_nothing_is_allowed_in_the_middle(self):
        journey = self.created(
            self.three_stop_route(
                stops=[{"position": 1, "accepts_pickup": False, "accepts_dropoff": False}]
            )
        )

        middle = self.detail(journey).data["stops"][1]
        assert (middle["accepts_pickup"], middle["accepts_dropoff"]) == (False, False)

    def test_an_edit_replaces_the_stop_options(self):
        journey = self.created(
            self.three_stop_route(stops=[{"position": 1, "accepts_pickup": False}])
        )
        payload = self.three_stop_route(stops=[{"position": 2, "handover_note": "Lobby"}])
        for leg, existing in zip(payload["legs"], journey.legs.order_by("position"), strict=True):
            leg["id"] = existing.pk

        response = self.client.patch(
            reverse("journeys-detail", args=(journey.pk,)), payload, format="json"
        )

        assert response.status_code == 200, response.data
        rows = list(JourneyStopDetail.objects.filter(journey=journey).values_list("position", "handover_note"))
        assert rows == [(2, "Lobby")]

    def test_refused_categories_and_fragility_are_the_travelers_rules(self):
        journey = self.created(
            self.three_stop_route(
                refused_categories=["electronics", "clothing", "electronics"],
                accepts_fragile=False,
            )
        )

        assert journey.refused_categories == ["clothing", "electronics"]
        assert journey.accepts_fragile is False
        data = self.detail(journey).data
        assert data["refused_categories"] == ["clothing", "electronics"]
        assert data["accepts_fragile"] is False

    def test_a_journey_must_accept_some_kind_of_item(self):
        every = ["documents", "small_box", "electronics", "clothing", "other"]
        for refused, field in ((every, "refused_categories"), (["weapons"], "refused_categories")):
            with self.subTest(refused=refused):
                response = self.create(self.three_stop_route(refused_categories=refused))
                assert response.status_code == 400, response.data
                assert field in response.data

    def test_volume_and_parcel_limits_are_optional_and_bounded(self):
        payload = self.three_stop_route()
        payload["legs"][0].update(capacity_volume_l=40, capacity_parcels=3)
        journey = self.created(payload)

        legs = self.detail(journey).data["legs"]
        assert (legs[0]["capacity_volume_l"], legs[0]["capacity_parcels"]) == (40, 3)
        assert (legs[1]["capacity_volume_l"], legs[1]["capacity_parcels"]) == (None, None)

        for field, value in (
            ("capacity_volume_l", 0),
            ("capacity_parcels", 0),
            ("capacity_volume_l", 200_001),
            ("capacity_parcels", 10_001),
        ):
            with self.subTest(field=field, value=value):
                payload = self.three_stop_route()
                payload["legs"][0][field] = value
                assert self.create(payload).status_code == 400

    def test_the_capacity_ceiling_refuses_a_typo(self):
        payload = self.three_stop_route()
        payload["legs"][0]["capacity_kg"] = "20000.01"

        assert self.create(payload).status_code == 400


# ---------------------------------------------------------------------------
# Pausing a journey
# ---------------------------------------------------------------------------


class JourneyPauseTests(SeaWorld, APITestCase):
    def setUp(self):
        self.build_sea_world()
        self.owner = self.person("l3a-pause-owner@example.com")
        self.stranger = self.person("l3a-pause-stranger@example.com")
        self.ops = staff(self, "l3a-ops@example.com", AdminRole.OPS)
        self.support = staff(self, "l3a-support@example.com", AdminRole.SUPPORT)
        self.trip = self.journey_for(self.owner)

    def journey_for(self, traveler, **fields) -> Journey:
        return self.make_journey(
            traveler, [(DRIVE, self.algiers, self.setif)], **fields
        )

    def call(self, name: str, *, user=None):
        client = client_for(user or self.owner)
        return client.post(reverse(f"journeys-{name}", args=(self.trip.pk,)))

    def test_the_owner_pauses_and_resumes_their_own_journey(self):
        response = self.call("pause")

        assert response.status_code == 200, response.data
        assert response.data["pause"]["paused"] is True
        assert response.data["pause"]["paused_by_staff"] is False
        assert "pause_reason" not in response.data["pause"]
        assert self.call("pause").status_code == 200  # idempotent
        assert client_for(self.stranger).get(
            reverse("journeys-detail", args=(self.trip.pk,))
        ).status_code == 404

        response = self.call("resume")

        assert response.status_code == 200, response.data
        assert response.data["pause"]["paused"] is False
        assert self.call("resume").status_code == 200  # idempotent
        assert client_for(self.stranger).get(
            reverse("journeys-detail", args=(self.trip.pk,))
        ).status_code == 200

    def test_only_the_owner_may_pause_and_only_a_live_journey(self):
        response = self.call("pause", user=self.stranger)
        assert response.status_code == 403, response.data
        assert response.data["code"] == "journey_not_owned"

        self.trip = self.journey_for(self.owner, status=Journey.Status.DRAFT)
        response = self.call("pause")
        assert response.status_code == 409, response.data
        assert response.data["code"] == "journey_not_pausable"

    def test_a_staff_pause_is_audited_and_only_staff_lift_it(self):
        paused = pause_journey(
            actor=self.ops, journey_id=self.trip.pk, reason="  Reported listing  "
        )

        assert paused.paused_by_staff is True
        assert paused.pause_reason == "Reported listing"
        audit = AdminAuditLog.objects.get(action="journey.paused")
        assert audit.actor_id == self.ops.pk
        assert audit.reason == "Reported listing"
        assert audit.before["paused_at"] is None
        assert audit.after["paused_by_staff"] is True

        response = self.call("resume")
        assert response.status_code == 409, response.data
        assert response.data["code"] == "journey_paused_by_staff"
        # The owner sees that staff paused it, never the internal reason.
        owner_view = client_for(self.owner).get(reverse("journeys-detail", args=(self.trip.pk,)))
        assert owner_view.data["pause"]["paused_by_staff"] is True
        assert "Reported listing" not in json.dumps(owner_view.data, default=str)

        resumed = resume_journey(actor=self.ops, journey_id=self.trip.pk, reason="Cleared")
        assert resumed.paused_at is None and resumed.pause_reason == ""
        assert AdminAuditLog.objects.filter(action="journey.resumed", reason="Cleared").count() == 1

    def test_staff_take_over_an_owner_pause_but_cannot_lift_one(self):
        self.call("pause")

        with self.assertRaises(JourneyDomainError) as caught:
            resume_journey(actor=self.ops, journey_id=self.trip.pk, reason="Not ours")
        assert caught.exception.code == "journey_paused_by_owner"

        pause_journey(actor=self.ops, journey_id=self.trip.pk, reason="Fraud check")
        assert self.call("resume").data["code"] == "journey_paused_by_staff"

    def test_staff_may_pause_a_draft_so_publishing_cannot_list_it(self):
        draft = self.journey_for(self.owner, status=Journey.Status.DRAFT)

        paused = pause_journey(actor=self.ops, journey_id=draft.pk, reason="Hold")

        assert paused.paused_at is not None
        completed = self.journey_for(self.owner, status=Journey.Status.COMPLETED)
        with self.assertRaises(JourneyDomainError) as caught:
            pause_journey(actor=self.ops, journey_id=completed.pk, reason="Too late")
        assert caught.exception.code == "journey_not_pausable"

    def test_a_staff_pause_needs_the_permission_and_a_reason(self):
        with self.assertRaises(PermissionDenied):
            pause_journey(actor=self.support, journey_id=self.trip.pk, reason="Nope")
        with self.assertRaises(PermissionDenied):
            pause_journey(actor=self.owner, journey_id=self.trip.pk, reason="Nope")
        with self.assertRaises(JourneyDomainError) as caught:
            pause_journey(actor=self.ops, journey_id=self.trip.pk, reason="   ")
        assert caught.exception.code == "journey_pause_reason_required"
        self.trip.refresh_from_db()
        assert self.trip.paused_at is None
        assert not AdminAuditLog.objects.filter(action="journey.paused").exists()

    def test_the_database_refuses_an_inconsistent_pause(self):
        for fields in (
            {"paused_by_staff": True},
            {"pause_reason": "orphan reason"},
            {"paused_at": timezone.now(), "paused_by_staff": True, "pause_reason": ""},
            {"paused_at": timezone.now(), "pause_reason": "owner pauses carry no reason"},
        ):
            with self.subTest(fields=fields), self.assertRaises(IntegrityError), transaction.atomic():
                Journey.objects.filter(pk=self.trip.pk).update(**fields)


# ---------------------------------------------------------------------------
# Sea crossings: staff services, the public list, the seed
# ---------------------------------------------------------------------------


class SeaCrossingServiceTests(SeaWorld, TestCase):
    def setUp(self):
        self.build_sea_world()
        self.admin = staff(self, "l3a-super@example.com", AdminRole.SUPER_ADMIN)
        self.ops = staff(self, "l3a-crossing-ops@example.com", AdminRole.OPS)

    def create(self, origin, destination, **fields):
        return create_crossing(
            actor=fields.pop("actor", self.admin),
            origin_locality_id=origin.pk,
            destination_locality_id=destination.pk,
            reason=fields.pop("reason", "New ferry line"),
            **fields,
        )

    def refused(self, code: str, call) -> None:
        with self.assertRaises(SeaCrossingError) as caught:
            call()
        assert caught.exception.code == code

    def test_a_new_line_starts_inactive_with_its_great_circle_distance(self):
        crossing = self.create(self.algiers, self.oran)

        assert crossing.is_active is False
        # Algiers to Oran, haversine over catalogue coordinates.
        assert 345_000 < crossing.distance_meters < 360_000
        audit = AdminAuditLog.objects.get(action="sea_crossing.created")
        assert audit.actor_id == self.admin.pk
        assert audit.reason == "New ferry line"
        assert audit.after["is_active"] is False

    def test_a_city_without_coordinates_cannot_be_a_port(self):
        # No launch-country city lacks coordinates in the real catalogue; a
        # crossing never takes its distance from anywhere but the catalogue.
        self.refused("sea_crossing_coordinates_missing", lambda: self.create(self.barcelona, self.algiers))
        self.refused("sea_crossing_coordinates_missing", lambda: self.create(self.algiers, self.barcelona))
        assert not SeaCrossing.objects.filter(origin_locality=self.barcelona, destination_locality=self.algiers).exists()
        assert not AdminAuditLog.objects.exists()

    def test_a_line_joins_two_different_active_cities_once_per_direction(self):
        self.refused("sea_crossing_port_invalid", lambda: self.create(self.alg, self.marseille))
        self.refused("sea_crossing_ports_identical", lambda: self.create(self.oran, self.oran))
        self.create(self.algiers, self.oran)
        self.refused("sea_crossing_exists", lambda: self.create(self.algiers, self.oran))
        self.oran.active = False
        self.oran.save(update_fields=["active"])
        self.refused("sea_crossing_port_invalid", lambda: self.create(self.algiers, self.oran))

    def test_managing_lines_needs_the_settings_permission_and_a_reason(self):
        with self.assertRaises(PermissionDenied):
            self.create(self.algiers, self.oran, actor=self.ops)
        with self.assertRaises(PermissionDenied):
            deactivate_crossing(actor=self.ops, crossing_id=self.marseille_algiers.pk, reason="x")
        self.refused("sea_crossing_reason_required", lambda: self.create(self.algiers, self.oran, reason=" "))
        assert not AdminAuditLog.objects.exists()

    def test_switching_a_line_off_closes_it_from_the_next_request(self):
        self.set_sea_switch(True)
        assert check_leg_mode(position=0, mode=SEA, origin=self.marseille, destination=self.algiers) is None

        deactivate_crossing(actor=self.admin, crossing_id=self.marseille_algiers.pk, reason="Strike")

        violation = check_leg_mode(
            position=0, mode=SEA, origin=self.marseille, destination=self.algiers
        )
        assert violation.reason == SEA_CROSSING_UNAVAILABLE
        # The opposite direction is a line of its own and stays open.
        assert check_leg_mode(position=0, mode=SEA, origin=self.algiers, destination=self.marseille) is None
        audit = AdminAuditLog.objects.get(action="sea_crossing.deactivated")
        assert (audit.before["is_active"], audit.after["is_active"]) == (True, False)

        activate_crossing(actor=self.admin, crossing_id=self.marseille_algiers.pk, reason="Resumed")
        assert check_leg_mode(position=0, mode=SEA, origin=self.marseille, destination=self.algiers) is None

    def test_a_change_that_changes_nothing_writes_no_audit_row(self):
        activate_crossing(actor=self.admin, crossing_id=self.marseille_algiers.pk, reason="Again")

        assert not AdminAuditLog.objects.exists()
        self.refused(
            "sea_crossing_not_found",
            lambda: activate_crossing(actor=self.admin, crossing_id=999_999, reason="Ghost"),
        )


class SeaCrossingEndpointTests(SeaWorld, APITestCase):
    def setUp(self):
        self.build_sea_world()

    def test_anyone_may_read_the_live_lines_and_the_switch(self):
        response = self.client.get(reverse("geography-sea-crossings"))

        assert response.status_code == 200, response.data
        assert response.data["enabled"] is False
        pairs = {
            (row["origin"]["id"], row["destination"]["id"]) for row in response.data["crossings"]
        }
        assert pairs == {
            (self.marseille.pk, self.algiers.pk),
            (self.algiers.pk, self.marseille.pk),
        }
        port = response.data["crossings"][0]["origin"]
        assert set(port) == {"id", "name", "display_label", "country_code"}
        assert "max-age=300" in response["Cache-Control"]

        self.set_sea_switch(True)
        assert self.client.get(reverse("geography-sea-crossings")).data["enabled"] is True


class SeedSeaCrossingsTests(SeaWorld, TestCase):
    def setUp(self):
        self.build_sea_world()
        # The real catalogue names the capital's commune "Alger Centre"; the
        # seed reaches it through its source-backed alternate name.
        self.alger = self.city("DZ", "Alger Centre", "36.776300", "3.058500")
        PlaceAlternateName.objects.create(
            place=self.alger,
            name="Alger",
            language="fr",
            source="l3a-test",
            source_id="alt-alger",
            source_version="l3a",
        )
        # The real catalogue gives Marseille coordinates; this world's French
        # cities have none, so the seed test sets them here.
        Place.objects.filter(pk=self.marseille.pk).update(
            latitude=Decimal("43.296500"), longitude=Decimal("5.369800")
        )
        self.marseille.refresh_from_db()
        # Two catalogue cities share this name: the seed must not guess.
        self.city("DZ", "Bordj", "36.0", "4.0", suffix="east")
        self.city("DZ", "Bordj", "36.1", "4.1", suffix="west")
        self.document = {
            "version": "test-1",
            "ports": {
                "marseille": {"country": "FR", "name": "Marseille"},
                "alger": {"country": "DZ", "name": "Alger"},
                "oran": {"country": "DZ", "name": "Oran"},
                "bordj": {"country": "DZ", "name": "Bordj"},
                "atlantis": {"country": "DZ", "name": "Atlantis"},
                "barcelona": {"country": "ES", "name": "Barcelona"},
            },
            "crossings": [
                {"from": "marseille", "to": "alger", "active": True},
                {"from": "alger", "to": "marseille", "active": True},
                {"from": "alger", "to": "oran", "active": False},
                {"from": "bordj", "to": "oran", "active": True},
                {"from": "atlantis", "to": "oran", "active": True},
                {"from": "barcelona", "to": "alger", "active": True},
            ],
        }

    def seed(self) -> str:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "crossings.json"
            path.write_text(json.dumps(self.document), encoding="utf-8")
            out = StringIO()
            call_command("seed_sea_crossings", file=str(path), stdout=out)
            return out.getvalue()

    def test_the_seed_creates_reviewed_lines_and_reports_what_it_skipped(self):
        output = self.seed()

        assert "sea crossings: 3 created, 0 already present, 3 skipped" in output
        assert "more than one active catalogue city has this name" in output
        assert "no active catalogue city has this name" in output
        # A city without catalogue coordinates gets no distance from anywhere.
        assert "skipped crossing barcelona -> alger: a port city has no catalogue coordinates" in output
        assert not SeaCrossing.objects.filter(origin_locality=self.barcelona, destination_locality=self.alger).exists()
        marseille_alger = SeaCrossing.objects.get(
            origin_locality=self.marseille, destination_locality=self.alger
        )
        assert marseille_alger.is_active is True
        assert marseille_alger.distance_meters == great_circle_meters(self.marseille, self.alger)
        assert 740_000 < marseille_alger.distance_meters < 770_000
        alger_oran = SeaCrossing.objects.get(origin_locality=self.alger, destination_locality=self.oran)
        assert alger_oran.is_active is False
        audits = AdminAuditLog.objects.filter(action="sea_crossing.seeded")
        assert audits.count() == 3
        assert all(row.actor_id is None and "test-1" in row.reason for row in audits)

    def test_a_rerun_never_undoes_staff_work(self):
        self.seed()
        admin = staff(self, "l3a-seed-admin@example.com", AdminRole.SUPER_ADMIN)
        line = SeaCrossing.objects.get(origin_locality=self.marseille, destination_locality=self.alger)
        deactivate_crossing(actor=admin, crossing_id=line.pk, reason="Operator gone")
        SeaCrossing.objects.filter(pk=line.pk).update(distance_meters=760_000)

        output = self.seed()

        assert "sea crossings: 0 created, 3 already present, 3 skipped" in output
        line.refresh_from_db()
        assert (line.is_active, line.distance_meters) == (False, 760_000)
        assert AdminAuditLog.objects.filter(action="sea_crossing.seeded").count() == 3

    def test_an_unreadable_file_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "broken.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(CommandError):
                call_command("seed_sea_crossings", file=str(path), stdout=StringIO())

    def test_the_shipped_list_is_whole_and_symmetric(self):
        document = json.loads(DEFAULT_FILE.read_text(encoding="utf-8"))
        ports = document["ports"]
        lines = {(row["from"], row["to"]): row["active"] for row in document["crossings"]}

        assert len(document["crossings"]) == len(lines) == 38
        assert {code for pair in lines for code in pair} <= set(ports)
        assert {port["country"] for port in ports.values()} == {"DZ", "FR", "ES"}
        for (origin, destination), active in lines.items():
            # A ferry line runs both ways, and both directions share a state.
            assert lines[(destination, origin)] == active, (origin, destination)
        assert sum(lines.values()) == 24  # twelve live lines, two directions each
