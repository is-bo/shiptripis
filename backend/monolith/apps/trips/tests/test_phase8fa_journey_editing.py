"""Phase 8F-A: route editing, transport-mode reality, and flight proof.

Three things the owner's real-device QA found, proved here rather than
described:

1. A configured journey could not be edited at all.
2. The app allowed a DRIVE leg between Algeria and France, which is not a
   journey anyone can make.
3. Flight-proof upload failed with a generic server error.

The mode tests are deliberately written as country pairs rather than as
"Algeria is special", because the rule is about road networks: the same code
has to keep France↔Germany driveable while refusing Jijel↔Marseille.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase, APITransactionTestCase

from apps.accounts.models import User
from apps.kyc.models import KycSubmission
from apps.locations.models import AirportLocalityMapping, Country, Place
from apps.trips.models import Journey, JourneyLeg, JourneyLegProof
from apps.trips.services import (
    JourneyDomainError,
    journey_editability,
    replace_journey_route,
)
from apps.trips.transport_rules import (
    DRIVE,
    FLIGHT,
    available_modes,
    check_leg_mode,
    default_mode,
    drive_is_available,
)

def _png_bytes() -> bytes:
    """A genuine 2x2 PNG.

    The view verifies the decoded image, not the declared type, so a
    hand-written byte string with a wrong CRC would test the rejection path
    rather than the success path.
    """

    from io import BytesIO

    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (2, 2), (10, 120, 90)).save(buffer, format="PNG")
    return buffer.getvalue()


PNG_2x2 = _png_bytes()


def _user(email: str) -> User:
    return User.objects.create_user(
        username=email,
        email=email,
        password="Sup3rStrongPass!",
        full_name="Route Tester",
        role=User.Role.BOTH,
    )


def _client(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _approve_kyc(user: User) -> KycSubmission:
    return KycSubmission.objects.create(
        user=user,
        document_type=KycSubmission.DocumentType.PASSPORT,
        idempotency_key=f"{user.pk:032d}",
        front_image_key=f"kyc/{user.pk}/front.jpg",
        status=KycSubmission.Status.APPROVED,
    )


class GeographyFixture:
    """The four launch countries with the places these tests actually route."""

    def build_geography(self) -> None:
        def country(code: str, name: str) -> Country:
            return Country.objects.create(
                code=code,
                name=name,
                source="phase8fa-test",
                source_id=f"country-{code.lower()}",
                source_version="phase8fa",
            )

        self.dz = country("DZ", "Algeria")
        self.fr = country("FR", "France")
        self.es = country("ES", "Spain")
        self.de = country("DE", "Germany")

        def locality(country_row, name, lat, lon) -> Place:
            return Place.objects.create(
                country=country_row,
                place_type=Place.PlaceType.LOCALITY,
                source="phase8fa-test",
                source_id=f"locality-{name.lower()}",
                source_version="phase8fa",
                name=name,
                latitude=lat,
                longitude=lon,
            )

        self.jijel = locality(self.dz, "Jijel", "36.820600", "5.766700")
        self.algiers = locality(self.dz, "Algiers", "36.753800", "3.058800")
        self.oran = locality(self.dz, "Oran", "35.699400", "-0.641700")
        self.paris = locality(self.fr, "Paris", "48.856600", "2.352200")
        self.marseille = locality(self.fr, "Marseille", "43.296500", "5.369800")
        self.madrid = locality(self.es, "Madrid", "40.416800", "-3.703800")
        self.berlin = locality(self.de, "Berlin", "52.520000", "13.405000")

        def airport(country_row, served, name, iata, lat, lon) -> Place:
            place = Place.objects.create(
                country=country_row,
                place_type=Place.PlaceType.AIRPORT,
                source="phase8fa-test",
                source_id=f"airport-{iata}",
                source_version="phase8fa",
                name=name,
                iata_code=iata,
                latitude=lat,
                longitude=lon,
                passenger_use=True,
            )
            AirportLocalityMapping.objects.create(
                airport=place,
                locality=served,
                relationship_type=AirportLocalityMapping.RelationshipType.SERVED,
                is_primary=True,
                source="phase8fa-test",
                source_id=f"mapping-{iata}",
                source_version="phase8fa",
            )
            return place

        self.alg = airport(
            self.dz, self.algiers, "Houari Boumediene", "ALG", "36.691000", "3.215400"
        )
        self.cdg = airport(
            self.fr, self.paris, "Charles de Gaulle", "CDG", "49.009700", "2.547900"
        )
        self.mad = airport(
            self.es, self.madrid, "Barajas", "MAD", "40.471900", "-3.562600"
        )
        self.gjl = airport(
            self.dz, self.jijel, "Jijel Ferhat Abbas", "GJL", "36.795100", "5.873600"
        )
        self.orn = airport(
            self.dz, self.oran, "Oran Es Senia", "ORN", "35.623900", "-0.621100"
        )


# ---------------------------------------------------------------------------
# The rule itself
# ---------------------------------------------------------------------------


class TransportRuleTests(APITestCase, GeographyFixture):
    def setUp(self):
        self.build_geography()

    def test_algeria_and_europe_are_different_road_networks(self):
        assert drive_is_available("DZ", "FR") is False
        assert drive_is_available("FR", "DZ") is False
        assert drive_is_available("DZ", "ES") is False
        assert drive_is_available("DE", "DZ") is False

    def test_domestic_and_continental_pairs_may_drive(self):
        assert drive_is_available("DZ", "DZ") is True
        assert drive_is_available("FR", "FR") is True
        assert drive_is_available("FR", "DE") is True
        assert drive_is_available("FR", "ES") is True
        assert drive_is_available("ES", "DE") is True

    def test_an_unknown_country_fails_closed(self):
        # A catalogue country nobody has declared a road network for must not
        # become driveable by accident.
        assert drive_is_available("DZ", "MA") is False
        assert drive_is_available("MA", "MA") is True
        assert available_modes("FR", "MA") == (FLIGHT,)

    def test_available_modes_narrow_across_the_boundary(self):
        assert available_modes("DZ", "FR") == (FLIGHT,)
        assert available_modes("DZ", "DZ") == (FLIGHT, DRIVE)

    def test_defaults_help_without_inventing_an_impossible_mode(self):
        assert default_mode(self.jijel, self.algiers) == DRIVE
        assert default_mode(self.paris, self.berlin) == DRIVE
        assert default_mode(self.alg, self.cdg) == FLIGHT
        # Two localities across the boundary still default to FLIGHT even
        # though neither of them is an airport: the alternative is a default
        # nobody can travel.
        assert default_mode(self.jijel, self.paris) == FLIGHT

    def test_check_leg_mode_only_objects_to_impossible_drives(self):
        assert (
            check_leg_mode(
                position=0, mode=FLIGHT, origin=self.jijel, destination=self.paris
            )
            is None
        )
        assert (
            check_leg_mode(
                position=0, mode=DRIVE, origin=self.jijel, destination=self.algiers
            )
            is None
        )
        violation = check_leg_mode(
            position=2, mode=DRIVE, origin=self.jijel, destination=self.marseille
        )
        assert violation is not None
        assert violation.position == 2
        assert violation.required_mode == FLIGHT
        assert violation.as_payload()["origin_country"] == "DZ"
        assert violation.as_payload()["destination_country"] == "FR"


# ---------------------------------------------------------------------------
# The rule through the API
# ---------------------------------------------------------------------------


class JourneyModeApiTests(APITestCase, GeographyFixture):
    def setUp(self):
        self.build_geography()
        self.owner = _user("mode-owner@example.com")
        self.client = _client(self.owner)
        self.depart = timezone.now() + timedelta(days=7)

    def _create(self, payload: dict):
        return self.client.post(
            reverse("journeys-list-create"), payload, format="json"
        )

    def _single_leg(self, origin, destination, mode, **overrides) -> dict:
        leg = {
            "position": 0,
            "mode": mode,
            "origin_place_id": origin.pk,
            "destination_place_id": destination.pk,
            "depart_at": self.depart.isoformat(),
            "arrive_at": (self.depart + timedelta(hours=3)).isoformat(),
            "capacity_kg": "10.00",
        }
        if mode == FLIGHT:
            leg["flight_number"] = "AH1006"
        leg.update(overrides)
        return {
            "start_place_id": origin.pk,
            "destination_place_id": destination.pk,
            "notes": "",
            "legs": [leg],
        }

    def test_algeria_to_france_drive_is_refused(self):
        response = self._create(
            self._single_leg(self.jijel, self.marseille, DRIVE)
        )

        assert response.status_code == 400, response.data
        assert response.data["code"] == ["journey_leg_mode_unavailable"]
        assert response.data["required_mode"] == ["FLIGHT"]
        assert response.data["origin_country"] == ["DZ"]
        assert response.data["destination_country"] == ["FR"]
        assert Journey.objects.count() == 0

    def test_france_to_algeria_drive_is_refused(self):
        response = self._create(self._single_leg(self.paris, self.algiers, DRIVE))

        assert response.status_code == 400, response.data
        assert response.data["code"] == ["journey_leg_mode_unavailable"]
        assert Journey.objects.count() == 0

    def test_spain_to_algeria_drive_is_refused(self):
        response = self._create(self._single_leg(self.madrid, self.oran, DRIVE))

        assert response.status_code == 400, response.data
        assert response.data["code"] == ["journey_leg_mode_unavailable"]

    def test_algerian_domestic_drive_is_allowed(self):
        response = self._create(self._single_leg(self.jijel, self.algiers, DRIVE))

        assert response.status_code == 201, response.data
        assert JourneyLeg.objects.get().mode == DRIVE

    def test_france_to_germany_drive_remains_allowed(self):
        response = self._create(self._single_leg(self.paris, self.berlin, DRIVE))

        assert response.status_code == 201, response.data

    def test_france_to_spain_drive_remains_allowed(self):
        response = self._create(self._single_leg(self.marseille, self.madrid, DRIVE))

        assert response.status_code == 201, response.data

    def test_international_flight_between_airports_is_allowed(self):
        response = self._create(self._single_leg(self.alg, self.cdg, FLIGHT))

        assert response.status_code == 201, response.data
        leg = JourneyLeg.objects.get()
        assert leg.mode == FLIGHT
        assert leg.origin_place_id == self.alg.pk
        assert leg.destination_place_id == self.cdg.pk

    def test_the_refusal_names_the_offending_leg_in_a_longer_route(self):
        payload = {
            "start_place_id": self.jijel.pk,
            "destination_place_id": self.marseille.pk,
            "notes": "",
            "legs": [
                {
                    "position": 0,
                    "mode": DRIVE,
                    "origin_place_id": self.jijel.pk,
                    "destination_place_id": self.algiers.pk,
                    "depart_at": self.depart.isoformat(),
                    "arrive_at": (self.depart + timedelta(hours=4)).isoformat(),
                    "capacity_kg": "10.00",
                },
                {
                    "position": 1,
                    "mode": DRIVE,
                    "origin_place_id": self.algiers.pk,
                    "destination_place_id": self.marseille.pk,
                    "depart_at": (self.depart + timedelta(hours=6)).isoformat(),
                    "capacity_kg": "10.00",
                },
            ],
        }

        response = self._create(payload)

        assert response.status_code == 400, response.data
        assert int(response.data["leg_position"][0]) == 1

    def test_publication_rechecks_a_leg_that_became_impossible(self):
        # A journey written before the rule existed, or whose place moved
        # country in a catalogue refresh, must not slip through publication.
        response = self._create(self._single_leg(self.jijel, self.algiers, DRIVE))
        assert response.status_code == 201, response.data
        journey = Journey.objects.get()
        leg = journey.legs.get()
        JourneyLeg.objects.filter(pk=leg.pk).update(
            destination_place=self.marseille
        )
        Journey.objects.filter(pk=journey.pk).update(
            destination_place=self.marseille
        )
        _approve_kyc(self.owner)

        response = self.client.post(reverse("journeys-publish", args=(journey.pk,)))

        assert response.status_code == 409, response.data
        assert response.data["code"] == "journey_leg_mode_unavailable"
        journey.refresh_from_db()
        assert journey.status == Journey.Status.DRAFT


# ---------------------------------------------------------------------------
# Editing
# ---------------------------------------------------------------------------


class JourneyEditApiTests(APITestCase, GeographyFixture):
    """The owner's actual scenario: Jijel to Paris, then Algiers in between.

    Note what a *stop* is here. ALG's served locality is Algiers and CDG's is
    Paris, so an airport is not a separate stop from the city it serves — it
    is how that stop is reached by air. Two consecutive stops must be
    different localities, which is why "CDG then Paris" is not a leg and
    "Jijel then ALG" is.
    """

    def setUp(self):
        self.build_geography()
        self.owner = _user("edit-owner@example.com")
        self.other = _user("edit-other@example.com")
        self.client = _client(self.owner)
        self.depart = timezone.now() + timedelta(days=10)

    # -- fixtures ---------------------------------------------------------

    def _create(self, payload: dict, *, user: User | None = None) -> Journey:
        response = (self.client if user is None else _client(user)).post(
            reverse("journeys-list-create"), payload, format="json"
        )
        assert response.status_code == 201, response.data
        return Journey.objects.get(pk=response.data["id"])

    def _direct_flight_payload(self) -> dict:
        """Jijel → Paris as the app first builds it: one flight, GJL to CDG."""

        return {
            "start_place_id": self.jijel.pk,
            "destination_place_id": self.paris.pk,
            "notes": "First draft",
            "legs": [
                {
                    "position": 0,
                    "mode": FLIGHT,
                    "origin_place_id": self.gjl.pk,
                    "destination_place_id": self.cdg.pk,
                    "depart_at": self.depart.isoformat(),
                    "arrive_at": (self.depart + timedelta(hours=3)).isoformat(),
                    "capacity_kg": "12.00",
                    "flight_number": "AH1006",
                },
            ],
        }

    def _via_algiers_payload(self, keep_flight_leg_id: int | None) -> dict:
        """The route the owner wanted: Jijel, then Algiers, then Paris."""

        flight = {
            "mode": FLIGHT,
            "origin_place_id": self.alg.pk,
            "destination_place_id": self.cdg.pk,
            "depart_at": (self.depart + timedelta(hours=6)).isoformat(),
            "arrive_at": (self.depart + timedelta(hours=9)).isoformat(),
            "capacity_kg": "12.00",
            "flight_number": "AH1006",
        }
        if keep_flight_leg_id is not None:
            flight["id"] = keep_flight_leg_id
        return {
            "start_place_id": self.jijel.pk,
            "destination_place_id": self.paris.pk,
            "notes": "Driving to Algiers first",
            "legs": [
                {
                    "mode": DRIVE,
                    "origin_place_id": self.jijel.pk,
                    "destination_place_id": self.alg.pk,
                    "depart_at": self.depart.isoformat(),
                    "arrive_at": (self.depart + timedelta(hours=5)).isoformat(),
                    "capacity_kg": "12.00",
                },
                flight,
            ],
        }

    def _two_leg_journey(self) -> Journey:
        """A journey already in the Jijel → Algiers → Paris shape."""

        payload = self._via_algiers_payload(keep_flight_leg_id=None)
        payload["legs"][0]["position"] = 0
        payload["legs"][1]["position"] = 1
        return self._create(payload)

    def _edit(self, journey: Journey, payload: dict, *, as_user: User | None = None):
        client = self.client if as_user is None else _client(as_user)
        return client.patch(
            reverse("journeys-detail", args=(journey.pk,)),
            payload,
            format="json",
        )

    # -- authorisation and status ----------------------------------------

    def test_a_draft_journey_is_editable(self):
        journey = self._create(self._direct_flight_payload())

        editability = journey_editability(journey, actor=self.owner)

        assert editability.editable is True
        assert editability.code == ""

    def test_another_users_journey_is_not_editable(self):
        journey = self._create(self._direct_flight_payload())

        editability = journey_editability(journey, actor=self.other)

        assert editability.editable is False
        assert editability.code == "journey_not_owned"

    def test_another_user_cannot_patch_the_route(self):
        journey = self._create(self._direct_flight_payload())

        response = self._edit(
            journey,
            self._via_algiers_payload(keep_flight_leg_id=None),
            as_user=self.other,
        )

        assert response.status_code == 403
        assert response.data["code"] == "journey_not_owned"
        assert journey.legs.count() == 1

    def test_an_active_journey_cannot_be_edited_and_says_why(self):
        journey = self._create(self._direct_flight_payload())
        Journey.objects.filter(pk=journey.pk).update(status=Journey.Status.ACTIVE)
        journey.refresh_from_db()

        response = self._edit(
            journey, self._via_algiers_payload(keep_flight_leg_id=None)
        )

        assert response.status_code == 409
        assert response.data["code"] == "journey_not_editable"
        # The reason names the status rather than shrugging.
        assert "active" in response.data["detail"]
        assert response.data["status"] == Journey.Status.ACTIVE

    def test_in_progress_completed_and_cancelled_are_all_refused(self):
        journey = self._create(self._direct_flight_payload())
        for blocked in (
            Journey.Status.IN_PROGRESS,
            Journey.Status.COMPLETED,
            Journey.Status.CANCELLED,
            Journey.Status.EXPIRED,
        ):
            Journey.objects.filter(pk=journey.pk).update(status=blocked)
            journey.refresh_from_db()
            editability = journey_editability(journey, actor=self.owner)
            assert editability.editable is False, blocked
            assert editability.code == "journey_not_editable"

    def test_pending_verification_stays_editable(self):
        journey = self._create(self._direct_flight_payload())
        Journey.objects.filter(pk=journey.pk).update(
            status=Journey.Status.PENDING_VERIFICATION
        )
        journey.refresh_from_db()

        assert journey_editability(journey, actor=self.owner).editable is True

    def test_detail_tells_the_owner_it_is_editable(self):
        journey = self._create(self._direct_flight_payload())

        response = self.client.get(reverse("journeys-detail", args=(journey.pk,)))

        assert response.status_code == 200
        assert response.data["editable"] is True
        assert response.data["edit_blocked_code"] is None

    def test_detail_tells_the_owner_why_it_is_not_editable(self):
        journey = self._create(self._direct_flight_payload())
        Journey.objects.filter(pk=journey.pk).update(status=Journey.Status.ACTIVE)

        response = self.client.get(reverse("journeys-detail", args=(journey.pk,)))

        assert response.status_code == 200
        assert response.data["editable"] is False
        assert response.data["edit_blocked_code"] == "journey_not_editable"

    def test_detail_hides_editability_from_a_non_owner(self):
        journey = self._create(self._direct_flight_payload())
        Journey.objects.filter(pk=journey.pk).update(status=Journey.Status.ACTIVE)
        _approve_kyc(self.owner)
        JourneyLegProof.objects.create(
            leg=journey.legs.get(),
            bucket="proof",
            object_key="k.jpg",
            status=JourneyLegProof.Status.APPROVED,
            reviewer=self.other,
            reviewed_at=timezone.now(),
        )

        response = _client(self.other).get(
            reverse("journeys-detail", args=(journey.pk,))
        )

        assert response.status_code == 200
        assert "editable" not in response.data
        assert "edit_blocked_code" not in response.data

    # -- the actual edit --------------------------------------------------

    def test_inserting_an_intermediate_stop_keeps_the_destination(self):
        """The finding, directly: Algiers goes in without Paris coming out."""

        journey = self._create(self._direct_flight_payload())
        flight = journey.legs.get()

        response = self._edit(
            journey, self._via_algiers_payload(keep_flight_leg_id=flight.pk)
        )

        assert response.status_code == 200, response.data
        legs = list(journey.legs.order_by("position"))
        assert [leg.position for leg in legs] == [0, 1]
        assert legs[0].origin_place_id == self.jijel.pk
        assert legs[0].destination_place_id == self.alg.pk
        assert legs[0].mode == DRIVE
        assert legs[1].origin_place_id == self.alg.pk
        assert legs[1].destination_place_id == self.cdg.pk
        journey.refresh_from_db()
        assert journey.start_place_id == self.jijel.pk
        assert journey.destination_place_id == self.paris.pk
        assert response.data["route_change"]["legs_created"] == 1
        assert response.data["route_change"]["legs_updated"] == 1
        assert response.data["route_change"]["legs_removed"] == 0

    def test_inserting_two_stops_in_one_edit(self):
        journey = self._create(self._direct_flight_payload())

        response = self._edit(
            journey,
            {
                "start_place_id": self.jijel.pk,
                "destination_place_id": self.madrid.pk,
                "notes": "",
                "legs": [
                    {
                        "mode": DRIVE,
                        "origin_place_id": self.jijel.pk,
                        "destination_place_id": self.alg.pk,
                        "depart_at": self.depart.isoformat(),
                        "arrive_at": (self.depart + timedelta(hours=5)).isoformat(),
                        "capacity_kg": "12.00",
                    },
                    {
                        "mode": FLIGHT,
                        "origin_place_id": self.alg.pk,
                        "destination_place_id": self.cdg.pk,
                        "depart_at": (self.depart + timedelta(hours=7)).isoformat(),
                        "arrive_at": (self.depart + timedelta(hours=10)).isoformat(),
                        "capacity_kg": "12.00",
                        "flight_number": "AH1006",
                    },
                    {
                        "mode": DRIVE,
                        "origin_place_id": self.cdg.pk,
                        "destination_place_id": self.madrid.pk,
                        "depart_at": (self.depart + timedelta(hours=12)).isoformat(),
                        "capacity_kg": "12.00",
                    },
                ],
            },
        )

        assert response.status_code == 200, response.data
        assert [leg.position for leg in journey.legs.order_by("position")] == [0, 1, 2]

    def test_the_chain_stays_connected_after_an_edit(self):
        journey = self._create(self._direct_flight_payload())
        flight = journey.legs.get()

        self._edit(journey, self._via_algiers_payload(keep_flight_leg_id=flight.pk))

        legs = list(journey.legs.order_by("position"))
        for previous, following in zip(legs, legs[1:]):
            assert (
                previous.destination_place.resolve_matching_locality()
                == following.origin_place.resolve_matching_locality()
            )

    def test_a_disconnected_edit_is_refused(self):
        journey = self._create(self._direct_flight_payload())
        payload = self._via_algiers_payload(keep_flight_leg_id=None)
        # Leg 2 now takes off from Madrid, which leg 1 never reaches.
        payload["legs"][1]["origin_place_id"] = self.mad.pk

        response = self._edit(journey, payload)

        assert response.status_code == 400, response.data
        assert journey.legs.count() == 1

    def test_removing_a_middle_stop_rejoins_the_route(self):
        journey = self._two_leg_journey()
        assert journey.legs.count() == 2
        flight = journey.legs.order_by("position").last()

        response = self._edit(
            journey,
            {
                "start_place_id": self.jijel.pk,
                "destination_place_id": self.paris.pk,
                "notes": "Straight through after all",
                "legs": [
                    {
                        "id": flight.pk,
                        "mode": FLIGHT,
                        "origin_place_id": self.gjl.pk,
                        "destination_place_id": self.cdg.pk,
                        "depart_at": self.depart.isoformat(),
                        "arrive_at": (self.depart + timedelta(hours=3)).isoformat(),
                        "capacity_kg": "12.00",
                        "flight_number": "AH1006",
                    }
                ],
            },
        )

        assert response.status_code == 200, response.data
        legs = list(journey.legs.all())
        assert len(legs) == 1
        assert legs[0].pk == flight.pk
        assert legs[0].position == 0
        assert legs[0].origin_place_id == self.gjl.pk
        assert response.data["route_change"]["legs_removed"] == 1

    def test_changing_a_middle_stop_updates_both_touching_legs(self):
        journey = self._two_leg_journey()
        drive, flight = list(journey.legs.order_by("position"))

        # Oran instead of Algiers, on both sides of the stop at once.
        response = self._edit(
            journey,
            {
                "start_place_id": self.jijel.pk,
                "destination_place_id": self.paris.pk,
                "notes": "Via Oran",
                "legs": [
                    {
                        "id": drive.pk,
                        "mode": DRIVE,
                        "origin_place_id": self.jijel.pk,
                        "destination_place_id": self.orn.pk,
                        "depart_at": self.depart.isoformat(),
                        "arrive_at": (self.depart + timedelta(hours=7)).isoformat(),
                        "capacity_kg": "12.00",
                    },
                    {
                        "id": flight.pk,
                        "mode": FLIGHT,
                        "origin_place_id": self.orn.pk,
                        "destination_place_id": self.cdg.pk,
                        "depart_at": (self.depart + timedelta(hours=9)).isoformat(),
                        "arrive_at": (self.depart + timedelta(hours=12)).isoformat(),
                        "capacity_kg": "12.00",
                        "flight_number": "AH1006",
                    },
                ],
            },
        )

        assert response.status_code == 200, response.data
        drive.refresh_from_db()
        flight.refresh_from_db()
        assert drive.destination_place_id == self.orn.pk
        assert flight.origin_place_id == self.orn.pk

    def test_reordering_stops_does_not_collide_on_position(self):
        """Positions are unique per journey, so a swap has to be staged."""

        journey = self._two_leg_journey()
        drive, flight = list(journey.legs.order_by("position"))

        # Paris → Algiers → Jijel: the same two legs, the other way round.
        response = self._edit(
            journey,
            {
                "start_place_id": self.paris.pk,
                "destination_place_id": self.jijel.pk,
                "notes": "Coming home",
                "legs": [
                    {
                        "id": flight.pk,
                        "mode": FLIGHT,
                        "origin_place_id": self.cdg.pk,
                        "destination_place_id": self.alg.pk,
                        "depart_at": self.depart.isoformat(),
                        "arrive_at": (self.depart + timedelta(hours=3)).isoformat(),
                        "capacity_kg": "12.00",
                        "flight_number": "AH1005",
                    },
                    {
                        "id": drive.pk,
                        "mode": DRIVE,
                        "origin_place_id": self.alg.pk,
                        "destination_place_id": self.jijel.pk,
                        "depart_at": (self.depart + timedelta(hours=5)).isoformat(),
                        "capacity_kg": "12.00",
                    },
                ],
            },
        )

        assert response.status_code == 200, response.data
        flight.refresh_from_db()
        drive.refresh_from_db()
        assert flight.position == 0
        assert drive.position == 1

    def test_an_edit_cannot_introduce_an_impossible_drive(self):
        journey = self._create(self._direct_flight_payload())

        response = self._edit(
            journey,
            {
                "start_place_id": self.jijel.pk,
                "destination_place_id": self.paris.pk,
                "notes": "",
                "legs": [
                    {
                        "mode": DRIVE,
                        "origin_place_id": self.jijel.pk,
                        "destination_place_id": self.paris.pk,
                        "depart_at": self.depart.isoformat(),
                        "capacity_kg": "12.00",
                    }
                ],
            },
        )

        assert response.status_code == 400, response.data
        assert response.data["code"] == ["journey_leg_mode_unavailable"]
        # Nothing was written: the original flight leg is untouched.
        assert journey.legs.count() == 1
        assert journey.legs.get().mode == FLIGHT

    def test_an_edit_cannot_borrow_another_journeys_leg(self):
        journey = self._create(self._direct_flight_payload())
        stranger = self._create(self._direct_flight_payload(), user=self.other)
        payload = self._via_algiers_payload(
            keep_flight_leg_id=stranger.legs.get().pk
        )

        response = self._edit(journey, payload)

        assert response.status_code == 400, response.data
        assert "legs" in response.data
        assert journey.legs.count() == 1
        assert stranger.legs.count() == 1

    # -- proof consequences ----------------------------------------------

    def _approved_proof(self, leg: JourneyLeg) -> JourneyLegProof:
        return JourneyLegProof.objects.create(
            leg=leg,
            bucket="shiptrip-media",
            object_key=f"journeys/{leg.journey_id}/legs/{leg.pk}/proofs/x.jpg",
            status=JourneyLegProof.Status.APPROVED,
            reviewer=self.other,
            reviewed_at=timezone.now(),
        )

    def _unchanged_flight_payload(self, journey: Journey, **drive_overrides) -> dict:
        drive, flight = list(journey.legs.order_by("position"))
        drive_leg = {
            "id": drive.pk,
            "mode": DRIVE,
            "origin_place_id": self.jijel.pk,
            "destination_place_id": self.alg.pk,
            "depart_at": self.depart.isoformat(),
            "arrive_at": (self.depart + timedelta(hours=5)).isoformat(),
            "capacity_kg": "12.00",
        }
        drive_leg.update(drive_overrides)
        return {
            "start_place_id": self.jijel.pk,
            "destination_place_id": self.paris.pk,
            "notes": "Edited",
            "legs": [
                drive_leg,
                {
                    "id": flight.pk,
                    "mode": FLIGHT,
                    "origin_place_id": self.alg.pk,
                    "destination_place_id": self.cdg.pk,
                    "depart_at": (self.depart + timedelta(hours=6)).isoformat(),
                    "arrive_at": (self.depart + timedelta(hours=9)).isoformat(),
                    "capacity_kg": "12.00",
                    "flight_number": "AH1006",
                },
            ],
        }

    def test_an_untouched_flight_leg_keeps_its_approved_proof(self):
        journey = self._two_leg_journey()
        proof = self._approved_proof(journey.legs.order_by("position").last())

        response = self._edit(journey, self._unchanged_flight_payload(journey))

        assert response.status_code == 200, response.data
        proof.refresh_from_db()
        assert proof.status == JourneyLegProof.Status.APPROVED
        assert response.data["route_change"]["proofs_reset_for_review"] == 0

    def test_a_capacity_edit_does_not_invalidate_proof(self):
        # A boarding pass does not stop proving the flight because the
        # traveller decided to carry less.
        journey = self._two_leg_journey()
        proof = self._approved_proof(journey.legs.order_by("position").last())
        payload = self._unchanged_flight_payload(journey)
        payload["legs"][1]["capacity_kg"] = "6.00"

        response = self._edit(journey, payload)

        assert response.status_code == 200, response.data
        proof.refresh_from_db()
        assert proof.status == JourneyLegProof.Status.APPROVED

    def test_editing_a_neighbouring_drive_leg_leaves_proof_alone(self):
        journey = self._two_leg_journey()
        proof = self._approved_proof(journey.legs.order_by("position").last())

        response = self._edit(
            journey,
            self._unchanged_flight_payload(
                journey, capacity_kg="4.00", arrive_at=None
            ),
        )

        assert response.status_code == 200, response.data
        proof.refresh_from_db()
        assert proof.status == JourneyLegProof.Status.APPROVED

    def test_changing_the_flight_number_sends_proof_back_for_review(self):
        journey = self._two_leg_journey()
        proof = self._approved_proof(journey.legs.order_by("position").last())
        payload = self._unchanged_flight_payload(journey)
        payload["legs"][1]["flight_number"] = "AH9999"

        response = self._edit(journey, payload)

        assert response.status_code == 200, response.data
        proof.refresh_from_db()
        assert proof.status == JourneyLegProof.Status.PENDING
        assert proof.reviewer_id is None
        assert proof.reviewed_at is None
        assert response.data["route_change"]["proofs_reset_for_review"] == 1
        # The earlier decision is preserved rather than erased.
        history = proof.metadata["invalidations"]
        assert history[-1]["previous_status"] == JourneyLegProof.Status.APPROVED
        assert history[-1]["previous_reviewer_id"] == self.other.pk
        assert "flight_number" in history[-1]["changed_fields"]

    def test_changing_the_arrival_airport_sends_proof_back_for_review(self):
        journey = self._two_leg_journey()
        proof = self._approved_proof(journey.legs.order_by("position").last())
        payload = self._unchanged_flight_payload(journey)
        payload["legs"][1]["destination_place_id"] = self.mad.pk
        payload["destination_place_id"] = self.madrid.pk

        response = self._edit(journey, payload)

        assert response.status_code == 200, response.data
        proof.refresh_from_db()
        assert proof.status == JourneyLegProof.Status.PENDING
        changed = proof.metadata["invalidations"][-1]["changed_fields"]
        assert "destination_place_id" in changed

    def test_changing_the_departure_airport_sends_proof_back_for_review(self):
        journey = self._two_leg_journey()
        proof = self._approved_proof(journey.legs.order_by("position").last())
        payload = self._unchanged_flight_payload(journey)
        payload["legs"][0]["destination_place_id"] = self.orn.pk
        payload["legs"][1]["origin_place_id"] = self.orn.pk

        response = self._edit(journey, payload)

        assert response.status_code == 200, response.data
        proof.refresh_from_db()
        assert proof.status == JourneyLegProof.Status.PENDING
        assert (
            "origin_place_id" in proof.metadata["invalidations"][-1]["changed_fields"]
        )

    def test_changing_the_flight_time_sends_proof_back_for_review(self):
        journey = self._two_leg_journey()
        proof = self._approved_proof(journey.legs.order_by("position").last())
        payload = self._unchanged_flight_payload(journey)
        payload["legs"][1]["depart_at"] = (
            self.depart + timedelta(days=1)
        ).isoformat()
        payload["legs"][1]["arrive_at"] = (
            self.depart + timedelta(days=1, hours=3)
        ).isoformat()

        response = self._edit(journey, payload)

        assert response.status_code == 200, response.data
        proof.refresh_from_db()
        assert proof.status == JourneyLegProof.Status.PENDING
        assert "depart_at" in proof.metadata["invalidations"][-1]["changed_fields"]

    def test_a_rejected_proof_is_not_reopened_by_an_edit(self):
        journey = self._two_leg_journey()
        proof = JourneyLegProof.objects.create(
            leg=journey.legs.order_by("position").last(),
            bucket="shiptrip-media",
            object_key="rejected.jpg",
            status=JourneyLegProof.Status.REJECTED,
            reviewer=self.other,
            reviewed_at=timezone.now(),
            rejection_reason="Unreadable",
        )
        payload = self._unchanged_flight_payload(journey)
        payload["legs"][1]["flight_number"] = "AH4242"

        self._edit(journey, payload)

        proof.refresh_from_db()
        assert proof.status == JourneyLegProof.Status.REJECTED
        assert proof.rejection_reason == "Unreadable"

    def test_an_invalidated_journey_can_no_longer_publish(self):
        """The point of the invalidation, end to end."""

        journey = self._two_leg_journey()
        _approve_kyc(self.owner)
        self._approved_proof(journey.legs.order_by("position").last())
        assert (
            self.client.post(
                reverse("journeys-publish", args=(journey.pk,))
            ).status_code
            == 200
        )
        Journey.objects.filter(pk=journey.pk).update(status=Journey.Status.DRAFT)

        payload = self._unchanged_flight_payload(journey)
        payload["legs"][1]["flight_number"] = "AH7777"
        assert self._edit(journey, payload).status_code == 200

        response = self.client.post(reverse("journeys-publish", args=(journey.pk,)))

        assert response.status_code == 409
        assert response.data["code"] == "flight_proof_not_approved"

    def test_removing_a_flight_leg_reports_its_discarded_proof(self):
        journey = self._two_leg_journey()
        self._approved_proof(journey.legs.order_by("position").last())

        response = self._edit(
            journey,
            {
                "start_place_id": self.paris.pk,
                "destination_place_id": self.madrid.pk,
                "notes": "Different journey entirely",
                "legs": [
                    {
                        "mode": DRIVE,
                        "origin_place_id": self.paris.pk,
                        "destination_place_id": self.madrid.pk,
                        "depart_at": self.depart.isoformat(),
                        "capacity_kg": "5.00",
                    }
                ],
            },
        )

        assert response.status_code == 200, response.data
        assert response.data["route_change"]["legs_removed"] == 2
        assert response.data["route_change"]["proofs_discarded"] == 1
        assert JourneyLegProof.objects.count() == 0

    def test_an_edit_returns_the_whole_rebuilt_journey(self):
        journey = self._create(self._direct_flight_payload())
        flight = journey.legs.get()

        response = self._edit(
            journey, self._via_algiers_payload(keep_flight_leg_id=flight.pk)
        )

        assert response.status_code == 200, response.data
        assert len(response.data["legs"]) == 2
        assert response.data["legs"][0]["origin_place"]["id"] == self.jijel.pk
        assert response.data["legs"][1]["destination_place"]["iata_code"] == "CDG"
        assert response.data["editable"] is True
        assert response.data["notes"] == "Driving to Algiers first"



class JourneyEditDependentStateTests(APITestCase, GeographyFixture):
    """A route somebody else is relying on is not the traveller's to move."""

    def setUp(self):
        self.build_geography()
        self.owner = _user("dependent-owner@example.com")
        self.sender = _user("dependent-sender@example.com")
        self.client = _client(self.owner)
        self.depart = timezone.now() + timedelta(days=9)
        response = self.client.post(
            reverse("journeys-list-create"),
            {
                "start_place_id": self.jijel.pk,
                "destination_place_id": self.algiers.pk,
                "notes": "",
                "legs": [
                    {
                        "position": 0,
                        "mode": DRIVE,
                        "origin_place_id": self.jijel.pk,
                        "destination_place_id": self.algiers.pk,
                        "depart_at": self.depart.isoformat(),
                        "capacity_kg": "9.00",
                    }
                ],
            },
            format="json",
        )
        assert response.status_code == 201, response.data
        self.journey = Journey.objects.get(pk=response.data["id"])

    def test_a_pending_match_blocks_editing_even_on_a_draft(self):
        from apps.matching.models import Match
        from apps.parcels.models import DeliveryRequest

        parcel = DeliveryRequest.objects.create(
            sender=self.sender,
            kind=DeliveryRequest.Kind.DELIVERY,
            schema_version=3,
            pickup_place=self.jijel,
            delivery_place=self.algiers,
            ready_window_start=self.depart - timedelta(hours=1),
            ready_window_end=self.depart + timedelta(hours=1),
            deadline_at=self.depart + timedelta(days=2),
            actual_weight_kg=Decimal("2.00"),
            length_cm=Decimal("20.00"),
            width_cm=Decimal("15.00"),
            height_cm=Decimal("10.00"),
            declared_value_eur_cents=10_000,
            traveler_reward_eur_cents=2_000,
            title="Dependent state request",
            description="Sealed documents",
            category=DeliveryRequest.ItemType.DOCUMENTS,
            item_type=DeliveryRequest.ItemType.DOCUMENTS,
            description_is_accurate=True,
            item_is_legal=True,
            no_prohibited_goods=True,
            declared_value_is_accurate=True,
            customs_responsibilities_understood=True,
        )
        leg = self.journey.legs.get()
        Match.objects.create(
            parcel=parcel,
            journey=self.journey,
            start_leg=leg,
            end_leg=leg,
            sender=self.sender,
            traveler=self.owner,
            status=Match.Status.PENDING,
        )

        editability = journey_editability(self.journey, actor=self.owner)

        assert editability.editable is False
        assert editability.code == "journey_has_dependent_state"


# ---------------------------------------------------------------------------
# Flight proof
# ---------------------------------------------------------------------------


@override_settings(S3_BUCKET_PROOF="shiptrip-proof-test")
class FlightProofUploadTests(APITestCase, GeographyFixture):
    def setUp(self):
        self.build_geography()
        self.owner = _user("proof-owner@example.com")
        self.other = _user("proof-other@example.com")
        self.client = _client(self.owner)
        self.depart = timezone.now() + timedelta(days=6)
        response = self.client.post(
            reverse("journeys-list-create"),
            {
                "start_place_id": self.algiers.pk,
                "destination_place_id": self.paris.pk,
                "notes": "",
                "legs": [
                    {
                        "position": 0,
                        "mode": FLIGHT,
                        "origin_place_id": self.alg.pk,
                        "destination_place_id": self.cdg.pk,
                        "depart_at": self.depart.isoformat(),
                        "arrive_at": (self.depart + timedelta(hours=3)).isoformat(),
                        "capacity_kg": "11.00",
                        "flight_number": "AH1006",
                    },
                    {
                        "position": 1,
                        "mode": DRIVE,
                        "origin_place_id": self.cdg.pk,
                        "destination_place_id": self.paris.pk,
                        "depart_at": (self.depart + timedelta(hours=4)).isoformat(),
                        "capacity_kg": "11.00",
                    },
                ],
            },
            format="json",
        )
        assert response.status_code == 201, response.data
        self.journey = Journey.objects.get(pk=response.data["id"])
        self.flight_leg, self.drive_leg = list(self.journey.legs.order_by("position"))

    def _url(self, leg: JourneyLeg) -> str:
        return reverse(
            "journey-leg-proof-create", args=(self.journey.pk, leg.pk)
        )

    def _upload(self, *, leg=None, data=None, client=None):
        leg = leg or self.flight_leg
        payload = {
            "kind": "boarding_pass",
            "photo": SimpleUploadedFile("pass.png", PNG_2x2, content_type="image/png"),
        }
        if data:
            payload.update(data)
        return (client or self.client).post(
            self._url(leg), payload, format="multipart"
        )

    def test_a_valid_upload_succeeds_and_lands_in_the_proof_bucket(self):
        with patch("apps.trips.views.put_object") as put_object:
            response = self._upload()

        assert response.status_code == 201, response.data
        proof = JourneyLegProof.objects.get()
        assert proof.leg_id == self.flight_leg.pk
        assert proof.status == JourneyLegProof.Status.PENDING
        assert proof.kind == "boarding_pass"
        # The bucket Django's own credential owns — not the KYC bucket, whose
        # credential belongs to the Go service. That mismatch is exactly what
        # produced the deployed 500.
        assert proof.bucket == "shiptrip-proof-test"
        assert put_object.call_args.kwargs["bucket"] == "shiptrip-proof-test"
        assert proof.object_key.startswith(
            f"journeys/{self.journey.pk}/legs/{self.flight_leg.pk}/proofs/"
        )

    def test_a_storage_failure_is_a_structured_503_not_a_crash(self):
        from botocore.exceptions import ClientError

        error = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "Access Denied."}},
            "PutObject",
        )
        with patch("apps.trips.views.put_object", side_effect=error):
            response = self._upload()

        assert response.status_code == 503, response.data
        assert response.data["code"] == "proof_storage_unavailable"
        # The provider's own words never reach the phone.
        assert "AccessDenied" not in str(response.data)
        assert JourneyLegProof.objects.count() == 0

    def test_a_non_owner_cannot_upload_proof(self):
        with patch("apps.trips.views.put_object"):
            response = self._upload(client=_client(self.other))

        assert response.status_code == 403
        assert response.data["code"] == "journey_not_owned"
        assert JourneyLegProof.objects.count() == 0

    def test_a_drive_leg_refuses_proof_with_a_code(self):
        with patch("apps.trips.views.put_object"):
            response = self._upload(leg=self.drive_leg)

        assert response.status_code == 400
        assert response.data["code"] == "proof_only_for_flight"

    def test_a_published_journey_refuses_more_proof(self):
        Journey.objects.filter(pk=self.journey.pk).update(
            status=Journey.Status.ACTIVE
        )

        with patch("apps.trips.views.put_object"):
            response = self._upload()

        assert response.status_code == 409
        assert response.data["code"] == "journey_proof_upload_closed"

    def test_a_missing_file_is_named_as_such(self):
        response = self.client.post(
            self._url(self.flight_leg), {"kind": "ticket"}, format="multipart"
        )

        assert response.status_code == 400
        assert response.data["code"] == "proof_file_missing"

    def test_an_unsupported_type_is_a_415_with_a_code(self):
        response = self.client.post(
            self._url(self.flight_leg),
            {
                "kind": "ticket",
                "photo": SimpleUploadedFile(
                    "pass.pdf", b"%PDF-1.4", content_type="application/pdf"
                ),
            },
            format="multipart",
        )

        assert response.status_code == 415
        assert response.data["code"] == "proof_media_type_unsupported"

    def test_a_renamed_file_is_refused_on_its_bytes(self):
        response = self.client.post(
            self._url(self.flight_leg),
            {
                "kind": "ticket",
                "photo": SimpleUploadedFile(
                    "pass.png", b"not an image at all", content_type="image/png"
                ),
            },
            format="multipart",
        )

        assert response.status_code == 415
        assert response.data["code"] == "proof_media_type_unsupported"

    def test_an_oversized_file_is_a_413_with_a_code(self):
        oversized = SimpleUploadedFile(
            "big.png", b"\x89PNG" + b"0" * (10 * 1024 * 1024 + 1), "image/png"
        )

        response = self.client.post(
            self._url(self.flight_leg),
            {"kind": "ticket", "photo": oversized},
            format="multipart",
        )

        assert response.status_code == 413
        assert response.data["code"] == "proof_file_too_large"

    def test_an_unknown_kind_is_refused(self):
        with patch("apps.trips.views.put_object"):
            response = self._upload(data={"kind": "selfie-with-the-plane"})

        assert response.status_code == 400
        assert response.data["code"] == "proof_kind_unknown"

    def test_a_retry_with_the_same_key_does_not_duplicate_the_proof(self):
        with patch("apps.trips.views.put_object"):
            first = self._upload(data={"idempotency_key": "device-abc-123"})
            second = self._upload(data={"idempotency_key": "device-abc-123"})

        assert first.status_code == 201, first.data
        assert second.status_code == 200, second.data
        assert first.data["id"] == second.data["id"]
        assert JourneyLegProof.objects.count() == 1

    def test_a_different_key_is_a_genuinely_new_proof(self):
        with patch("apps.trips.views.put_object"):
            self._upload(data={"idempotency_key": "device-abc-123"})
            self._upload(data={"idempotency_key": "device-abc-124"})

        assert JourneyLegProof.objects.count() == 2

    def test_uploads_without_a_key_are_not_collapsed_together(self):
        # The empty key means "no opinion", not "the same request twice".
        with patch("apps.trips.views.put_object"):
            self._upload()
            self._upload()

        assert JourneyLegProof.objects.count() == 2


@override_settings(S3_BUCKET_PROOF="shiptrip-proof-test")
class FlightProofConcurrencyTests(APITransactionTestCase, GeographyFixture):
    """The idempotency guarantee is a database constraint, not a lookup.

    A `SELECT` then `INSERT` is a race on a phone that fires the same retry
    twice. PostgreSQL's partial unique index is what actually holds, so it is
    exercised here on a real connection rather than assumed.
    """

    def setUp(self):
        self.build_geography()
        self.owner = _user("race-owner@example.com")
        self.depart = timezone.now() + timedelta(days=6)
        self.journey = Journey.objects.create(
            traveler=self.owner,
            schema_version=2,
            start_place=self.algiers,
            destination_place=self.paris,
            status=Journey.Status.DRAFT,
        )
        self.leg = JourneyLeg.objects.create(
            journey=self.journey,
            position=0,
            mode=FLIGHT,
            origin_place=self.alg,
            destination_place=self.cdg,
            depart_at=self.depart,
            capacity_kg=Decimal("10.00"),
            flight_number="AH1006",
        )

    def test_the_partial_unique_index_is_real_in_postgres(self):
        assert connection.vendor == "postgresql"
        from django.db import IntegrityError

        JourneyLegProof.objects.create(
            leg=self.leg,
            bucket="b",
            object_key="one.jpg",
            idempotency_key="same-key",
        )
        try:
            JourneyLegProof.objects.create(
                leg=self.leg,
                bucket="b",
                object_key="two.jpg",
                idempotency_key="same-key",
            )
        except IntegrityError:
            pass
        else:  # pragma: no cover - the assertion below reports it
            raise AssertionError("a duplicate idempotency key was accepted")

    def test_unkeyed_proofs_are_exempt_from_the_index(self):
        JourneyLegProof.objects.create(leg=self.leg, bucket="b", object_key="a.jpg")
        JourneyLegProof.objects.create(leg=self.leg, bucket="b", object_key="b.jpg")

        assert JourneyLegProof.objects.filter(leg=self.leg).count() == 2


class ReplaceJourneyRouteServiceTests(APITestCase, GeographyFixture):
    """The service refuses directly, not only through the view."""

    def setUp(self):
        self.build_geography()
        self.owner = _user("service-owner@example.com")
        self.depart = timezone.now() + timedelta(days=8)
        self.journey = Journey.objects.create(
            traveler=self.owner,
            schema_version=2,
            start_place=self.jijel,
            destination_place=self.algiers,
            status=Journey.Status.ACTIVE,
        )
        JourneyLeg.objects.create(
            journey=self.journey,
            position=0,
            mode=DRIVE,
            origin_place=self.jijel,
            destination_place=self.algiers,
            depart_at=self.depart,
            capacity_kg=Decimal("7.00"),
        )

    def test_a_live_journey_cannot_be_rewritten_through_the_service(self):
        try:
            replace_journey_route(
                journey=self.journey,
                actor=self.owner,
                start_place=self.jijel,
                destination_place=self.oran,
                start_location=None,
                destination_location=None,
                notes="",
                legs=[
                    {
                        "mode": DRIVE,
                        "origin_place": self.jijel,
                        "destination_place": self.oran,
                        "depart_at": self.depart,
                        "capacity_kg": Decimal("7.00"),
                    }
                ],
            )
        except JourneyDomainError as exc:
            assert exc.code == "journey_not_editable"
        else:  # pragma: no cover
            raise AssertionError("an active journey was rewritten")
        assert self.journey.legs.get().destination_place_id == self.algiers.pk
