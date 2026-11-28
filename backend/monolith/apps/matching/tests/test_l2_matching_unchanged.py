"""L2: removing the old shapes changes no matching result for current data.

The frozen modules hold the code as it was on main before L2. This test builds
current-shape requests (catalogue places) and journeys (catalogue places on
every leg) across the cases the matching suites use, runs the frozen and the
live code on every pair, and compares the whole result: every check in order,
the rejection codes, limitations, positions, times, distances, capacity rows and
the covered legs. L2 deletes this test and the frozen modules in its last
commit.

`_as_stored` gives the frozen code the version every write path stores (3 for
a request, 2 for a journey), so it also runs once the column is gone.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase

from apps.accounts.models import User
from apps.core.business_settings import get_active_business_settings
from apps.finance.tests.factories import make_location
from apps.locations.models import Location
from apps.matching import compatibility as live_compatibility
from apps.matching import discovery as live_discovery
from apps.matching import posting_pricing as live_posting
from apps.matching.policy import Phase2Policy
from apps.parcels.models import DeliveryRequest, ParcelRequest
from apps.routing.geometry import haversine_meters
from apps.routing.providers import RouteProviderError, RouteResult, UnavailableRouteProvider
from apps.trips import lifecycle as live_lifecycle
from apps.trips import services as live_trips
from apps.trips.models import Journey, JourneyLeg, JourneyLegProof
from apps.trips.services import JourneyDomainError
from apps.trips.tests.sea_world import DRIVE, FLIGHT, SEA, SeaWorld

from . import l2_frozen_compatibility as frozen_compatibility
from . import l2_frozen_other as frozen


class _FakeRoads:
    """A deterministic road network: 1.25 times the great circle, at 20 m/s."""

    name = "l2-fake-roads"

    def capabilities(self):
        return frozenset({"directions"})

    def directions(self, points, *, profile):
        distance = sum(
            haversine_meters(first, second)
            for first, second in zip(points, points[1:], strict=False)
        )
        distance = int(distance * 1.25)
        return RouteResult(
            distance_meters=distance,
            duration_seconds=distance // 20,
            polyline="",
            corridor_points=tuple(points),
            provider=self.name,
            profile=profile,
            metadata={},
        )


class _BrokenRoads(_FakeRoads):
    name = "l2-broken-roads"

    def directions(self, points, *, profile):
        raise RouteProviderError("down")


def _has_column(model, name: str) -> bool:
    return any(field.name == name for field in model._meta.concrete_fields)


@contextmanager
def _as_stored():
    """The version each write path stored, for the frozen code's reads."""

    with patch.object(DeliveryRequest, "schema_version", 3, create=True), patch.object(
        Journey, "schema_version", 2, create=True
    ):
        yield


def _versioned(model, value: int) -> dict:
    return {"schema_version": value} if _has_column(model, "schema_version") else {}


class MatchingUnchangedByL2Tests(SeaWorld, TestCase):
    def setUp(self):
        self.build_sea_world()
        self.at = self.now + timedelta(minutes=1)
        self.sender = self.person("l2-sender@example.com")
        self.other_sender = self.person("l2-other-sender@example.com")
        self.traveler = self.person("l2-traveler@example.com")
        self.second_traveler = self.person("l2-second@example.com")
        self.unverified = self.person("l2-unverified@example.com", verified=False)
        self.banned = self.person("l2-banned@example.com")
        User.objects.filter(pk=self.banned.pk).update(is_banned=True)
        self.banned.refresh_from_db()
        self.orn = self.airport("DZ", "Ahmed Ben Bella", "ORN", self.oran, "35.623900", "-0.621200")
        self.journeys = self._journeys()
        self.requests = self._requests()

    # -- the world ------------------------------------------------------------

    def _journey(self, legs, *, traveler=None, **fields) -> Journey:
        return self.make_journey(traveler or self.traveler, legs, **fields)

    def _journeys(self) -> dict[str, Journey]:
        j = {}
        j["flight"] = self._journey([(FLIGHT, self.alg, self.cdg)])
        j["flight_unticketed"] = self._journey(
            [(FLIGHT, self.alg, self.cdg)], approve_tickets=False
        )
        self.ticket(j["flight_unticketed"].legs.get(), JourneyLegProof.Status.PENDING)
        j["drive_stored"] = self._journey([(DRIVE, self.algiers, self.oran)])
        j["drive_routed"] = self._journey(
            [(DRIVE, self.algiers, self.setif)], road_distance=None
        )
        j["chain"] = self._journey(
            [
                (DRIVE, self.constantine, self.setif),
                (DRIVE, self.setif, self.algiers),
                (FLIGHT, self.alg, self.cdg),
                (DRIVE, self.paris, self.lyon),
            ]
        )
        JourneyLeg.objects.filter(journey=j["chain"], position=1).update(
            distance_meters=None, route_provider=""
        )
        j["loop"] = self._journey(
            [
                (DRIVE, self.algiers, self.oran),
                (DRIVE, self.oran, self.algiers),
                (FLIGHT, self.alg, self.cdg),
            ]
        )
        j["sea"] = self._journey(
            [(SEA, self.marseille, self.algiers), (DRIVE, self.algiers, self.setif)]
        )
        j["no_pickup_stop"] = self._journey([(FLIGHT, self.alg, self.cdg)])
        self.stop(j["no_pickup_stop"], 0, accepts_pickup=False)
        j["no_dropoff_stop"] = self._journey([(DRIVE, self.algiers, self.oran)])
        self.stop(j["no_dropoff_stop"], 1, accepts_dropoff=False)
        j["picky"] = self._journey([(DRIVE, self.algiers, self.oran)])
        Journey.objects.filter(pk=j["picky"].pk).update(
            refused_categories=["electronics"], accepts_fragile=False
        )
        j["small"] = self._journey(
            [(DRIVE, self.algiers, self.oran)],
            capacity="1.00",
            capacity_volume_l=1,
            capacity_parcels=1,
        )
        j["paused"] = self._journey([(DRIVE, self.algiers, self.oran)])
        Journey.objects.filter(pk=j["paused"].pk).update(paused_at=self.now)
        j["unverified"] = self._journey(
            [(DRIVE, self.algiers, self.oran)], traveler=self.unverified
        )
        j["banned"] = self._journey([(DRIVE, self.algiers, self.oran)], traveler=self.banned)
        j["draft"] = self._journey(
            [(DRIVE, self.algiers, self.oran)], status=Journey.Status.DRAFT
        )
        j["own"] = self._journey([(DRIVE, self.algiers, self.oran)], traveler=self.sender)
        j["airport_hub"] = self._journey(
            [(DRIVE, self.oran, self.alg), (FLIGHT, self.alg, self.cdg)],
            traveler=self.second_traveler,
        )
        j["flight_orn"] = self._journey([(FLIGHT, self.orn, self.cdg)])
        j["priced"] = self._journey([(FLIGHT, self.alg, self.cdg)])
        Journey.objects.filter(pk=j["priced"].pk).update(
            price_per_kg_eur_cents=400, min_price_eur_cents=1_500
        )
        j["later"] = self._journey(
            [(DRIVE, self.algiers, self.oran)], start=self.now + timedelta(days=6)
        )
        j["pinned"] = self._journey([(DRIVE, self.algiers, self.oran)])
        start_pin = self._pin("l2 journey start", self.algiers, "36.760000", "3.050000")
        end_pin = self._pin("l2 journey end", self.oran, "35.700000", "-0.640000")
        Journey.objects.filter(pk=j["pinned"].pk).update(
            start_location=start_pin, destination_location=end_pin
        )
        JourneyLeg.objects.filter(journey=j["pinned"]).update(
            origin=start_pin, destination=end_pin
        )
        # Journeys a publication check refuses.
        j["bad_endpoints"] = self._journey(
            [(DRIVE, self.algiers, self.oran)], status=Journey.Status.DRAFT
        )
        Journey.objects.filter(pk=j["bad_endpoints"].pk).update(
            destination_place=self.setif
        )
        j["disconnected"] = self._journey(
            [(DRIVE, self.algiers, self.oran), (DRIVE, self.setif, self.constantine)],
            status=Journey.Status.DRAFT,
        )
        j["same_node"] = self._journey(
            [(DRIVE, self.alg, self.algiers)], status=Journey.Status.DRAFT
        )
        j["past"] = self._journey(
            [(DRIVE, self.algiers, self.oran)], start=self.now - timedelta(days=1)
        )
        return {
            name: Journey.objects.get(pk=journey.pk) for name, journey in j.items()
        }

    def _pin(self, label, place, latitude, longitude, *, owner=None) -> Location:
        pin = make_location(label, latitude, longitude, owner=owner)
        pin.canonical_place = place
        pin.save(update_fields=["canonical_place"])
        return pin

    def _leg(self, name: str, position: int = 0) -> JourneyLeg:
        return self.journeys[name].legs.get(position=position)

    def _request(self, origin, destination, *, leg, sender=None, **fields) -> DeliveryRequest:
        deliver_by = fields.pop("deliver_by", leg.arrive_at + timedelta(days=1))
        pickup_at = fields.pop("pickup_at", leg.depart_at)
        status = fields.pop("status", ParcelRequest.Status.OPEN)
        extra = {
            key: fields.pop(key)
            for key in ("target_traveler", "pickup_location", "delivery_location")
            if key in fields
        }
        request = self.request(
            sender or self.sender,
            origin,
            destination,
            pickup_at=pickup_at,
            deliver_by=deliver_by,
            **fields,
        )
        if extra or status != ParcelRequest.Status.OPEN:
            for key, value in extra.items():
                setattr(request, key, value)
            request.status = status
            request.save()
        return request

    def _requests(self) -> dict[str, DeliveryRequest]:
        flight = self._leg("flight")
        drive = self._leg("drive_stored")
        chain0 = self._leg("chain", 0)
        chain1 = self._leg("chain", 1)
        loop0 = self._leg("loop", 0)
        loop2 = self._leg("loop", 2)
        sea = self._leg("sea")
        hub = self._leg("airport_hub")
        routed = self._leg("drive_routed")
        r = {}
        r["algiers_paris"] = self._request(self.algiers, self.paris, leg=flight)
        r["alg_cdg"] = self._request(self.alg, self.cdg, leg=flight)
        r["paris_algiers"] = self._request(self.paris, self.algiers, leg=flight)
        r["algiers_oran"] = self._request(self.algiers, self.oran, leg=drive)
        r["algiers_oran_late"] = self._request(
            self.algiers,
            self.oran,
            leg=drive,
            pickup_at=drive.depart_at + timedelta(days=3),
            deliver_by=drive.depart_at + timedelta(days=4),
        )
        r["algiers_setif"] = self._request(
            self.algiers, self.setif, leg=routed, dimensions=None
        )
        r["constantine_lyon"] = self._request(
            self.constantine,
            self.lyon,
            leg=chain0,
            deliver_by=chain0.depart_at + timedelta(days=2),
        )
        r["setif_paris"] = self._request(self.setif, self.paris, leg=chain1)
        r["setif_algiers"] = self._request(self.setif, self.algiers, leg=chain1)
        r["loop_late"] = self._request(self.algiers, self.paris, leg=loop2)
        r["loop_early"] = self._request(self.algiers, self.paris, leg=loop0)
        r["oran_algiers"] = self._request(self.oran, self.algiers, leg=self._leg("loop", 1))
        r["marseille_algiers"] = self._request(self.marseille, self.algiers, leg=sea)
        r["electronics_fragile"] = self._request(
            self.algiers,
            self.oran,
            leg=drive,
            category=ParcelRequest.ItemType.ELECTRONICS,
            fragile=True,
        )
        r["heavy"] = self._request(
            self.algiers,
            self.oran,
            leg=drive,
            weight="30.00",
            dimensions=("60.00", "50.00", "40.00"),
        )
        r["no_dimensions"] = self._request(
            self.algiers, self.oran, leg=drive, dimensions=None
        )
        r["targeted"] = self._request(
            self.algiers, self.oran, leg=drive, target_traveler=self.traveler
        )
        r["targeted_elsewhere"] = self._request(
            self.algiers, self.oran, leg=drive, target_traveler=self.second_traveler
        )
        r["cancelled"] = self._request(
            self.algiers, self.oran, leg=drive, status=ParcelRequest.Status.CANCELLED
        )
        r["window_before"] = self._request(
            self.algiers,
            self.oran,
            leg=drive,
            pickup_at=drive.depart_at - timedelta(hours=6),
        )
        r["deadline_short"] = self._request(
            self.algiers,
            self.oran,
            leg=drive,
            deliver_by=drive.depart_at + timedelta(minutes=50),
        )
        r["pinned"] = self._request(
            self.algiers,
            self.oran,
            leg=drive,
            pickup_location=self._pin(
                "l2 pickup", self.algiers, "36.700000", "3.100000", owner=self.sender
            ),
            delivery_location=self._pin(
                "l2 dropoff", self.oran, "35.710000", "-0.600000", owner=self.sender
            ),
        )
        r["berlin_paris"] = self._request(self.berlin, self.paris, leg=flight)
        r["oran_paris"] = self._request(self.oran, self.paris, leg=hub)
        r["orn_cdg"] = self._request(self.orn, self.cdg, leg=self._leg("flight_orn"))
        r["other_sender"] = self._request(
            self.algiers, self.paris, leg=flight, sender=self.other_sender, reward=4_500
        )
        return {
            name: DeliveryRequest.objects.select_related(
                "sender", "pickup_place", "delivery_place", "pickup_location", "delivery_location"
            ).get(pk=request.pk)
            for name, request in r.items()
        }

    # -- comparisons ----------------------------------------------------------

    def _policies(self) -> list[Phase2Policy]:
        policy = Phase2Policy.from_settings(get_active_business_settings())
        return [policy, replace(policy, spatial_fallback_enabled=False)]

    def _fresh(self, model, pk):
        if model is Journey:
            return Journey.objects.select_related("traveler").get(pk=pk)
        return DeliveryRequest.objects.select_related(
            "sender", "pickup_place", "delivery_place", "pickup_location", "delivery_location"
        ).get(pk=pk)

    def test_every_pair_gets_the_same_compatibility_result(self):
        providers = [UnavailableRouteProvider(), _FakeRoads(), _BrokenRoads()]
        compared = compatible = 0
        for policy in self._policies():
            for provider in providers:
                for request_name, request in self.requests.items():
                    for journey_name, journey in self.journeys.items():
                        with self.subTest(
                            request=request_name,
                            journey=journey_name,
                            provider=provider.name,
                            fallback=policy.spatial_fallback_enabled,
                        ):
                            with _as_stored():
                                old = frozen_compatibility.evaluate_compatibility(
                                    delivery_request=self._fresh(DeliveryRequest, request.pk),
                                    journey=self._fresh(Journey, journey.pk),
                                    policy=policy,
                                    at=self.at,
                                    route_provider=provider,
                                )
                            new = live_compatibility.evaluate_compatibility(
                                delivery_request=self._fresh(DeliveryRequest, request.pk),
                                journey=self._fresh(Journey, journey.pk),
                                policy=policy,
                                at=self.at,
                                route_provider=provider,
                            )
                            self.assertEqual(old.as_dict(), new.as_dict())
                            compared += 1
                            compatible += new.compatible
        # Not a vacuous comparison: both outcomes occur many times.
        self.assertGreater(compatible, 40)
        self.assertGreater(compared - compatible, 400)

    def test_both_scans_return_the_same_candidates(self):
        policy = self._policies()[0]

        def rows(evaluations):
            return [
                (
                    row.delivery_request.pk,
                    row.journey.pk,
                    row.as_dict(),
                    row.listed,
                )
                for row in evaluations
            ]

        found = 0
        for name, request in self.requests.items():
            with self.subTest(request=name):
                with _as_stored():
                    old = rows(
                        frozen.compatible_journeys_for_request(
                            delivery_request=self._fresh(DeliveryRequest, request.pk),
                            policy=policy,
                            at=self.at,
                        )
                    )
                new = rows(
                    live_discovery.compatible_journeys_for_request(
                        delivery_request=self._fresh(DeliveryRequest, request.pk),
                        policy=policy,
                        at=self.at,
                    )
                )
                self.assertEqual(old, new)
                found += len(new)
        for name, journey in self.journeys.items():
            with self.subTest(journey=name):
                old = rows(
                    frozen.compatible_requests_for_journey(
                        journey=journey, policy=policy, at=self.at
                    )
                )
                new = rows(
                    live_discovery.compatible_requests_for_journey(
                        journey=journey, policy=policy, at=self.at
                    )
                )
                self.assertEqual(old, new)
                found += len(new)
        self.assertGreater(found, 10)

    def test_the_posting_estimate_is_the_same(self):
        for name, request in self.requests.items():
            with self.subTest(request=name):
                with _as_stored():
                    old = frozen.estimate_request_route(self._fresh(DeliveryRequest, request.pk))
                new = live_posting.estimate_request_route(
                    self._fresh(DeliveryRequest, request.pk)
                )
                self.assertEqual(old, new)
        draft = {
            "pickup_place": self.algiers,
            "delivery_place": self.oran,
            "pickup_location": None,
            "delivery_location": None,
        }
        self.assertEqual(
            frozen.estimate_request_route(SimpleNamespace(schema_version=3, **draft)),
            live_posting.estimate_request_route(
                live_posting.draft_request(**_versioned(DeliveryRequest, 3), **draft)
            ),
        )

    def test_publication_checks_the_leg_chain_the_same_way(self):
        def outcome(check, journey):
            legs = list(
                journey.legs.select_related(
                    "origin_place", "destination_place", "origin", "destination"
                ).order_by("position")
            )
            try:
                check(journey, legs, at=self.now)
            except JourneyDomainError as exc:
                return exc.code, exc.message
            return None

        refused = 0
        for name, journey in self.journeys.items():
            with self.subTest(journey=name):
                with _as_stored():
                    old = outcome(frozen._validate_leg_sequence, self._fresh(Journey, journey.pk))
                new = outcome(live_trips._validate_leg_sequence, self._fresh(Journey, journey.pk))
                self.assertEqual(old, new)
                refused += old is not None
        self.assertGreaterEqual(refused, 4)

    def test_the_lifecycle_and_discoverable_journeys_are_the_same(self):
        for at in (
            self.now,
            self.now + timedelta(days=3, hours=1),
            self.now + timedelta(days=4),
            self.now + timedelta(days=10),
        ):
            with self.subTest(at=at):
                for old_fn, new_fn in (
                    (frozen.with_lifecycle, live_lifecycle.with_lifecycle),
                    (frozen.discoverable, live_lifecycle.discoverable),
                ):
                    old = list(
                        old_fn(Journey.objects.order_by("pk"), at=at).values_list(
                            "pk", "lifecycle_status"
                        )
                    )
                    new = list(
                        new_fn(Journey.objects.order_by("pk"), at=at).values_list(
                            "pk", "lifecycle_status"
                        )
                    )
                    self.assertEqual(old, new)
