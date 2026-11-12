"""The L3A test world: the launch countries, three ferry ports and real gaps.

The shape is the production catalogue's, including its awkward parts: a sea
leg joins two cities rather than two terminals, and a ferry line exists once
per direction. The French and Spanish cities here deliberately carry no
coordinates, unlike the real catalogue, so these suites keep proving the
distance-floor crash guard and that a city without coordinates cannot become
a port. Tests that need a sea leg build it here so every suite proves the same
geography.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from apps.discovery.tests.support import activate_marketplace
from apps.locations.models import AirportLocalityMapping, Country, Place, SeaCrossing
from apps.matching.tests.test_v1_matching import _approve_kyc, _ensure_business_settings, _user
from apps.parcels.models import DeliveryRequest, ParcelRequest
from apps.trips.models import Journey, JourneyLeg, JourneyLegProof, JourneyStopDetail

DRIVE = JourneyLeg.Mode.DRIVE
FLIGHT = JourneyLeg.Mode.FLIGHT
SEA = JourneyLeg.Mode.SEA

#: Marseille to Algiers, great circle, as the seed computes it.
MARSEILLE_ALGIERS_METERS = 753_000


class SeaWorld:
    def build_sea_world(self) -> None:
        _ensure_business_settings()
        self.now = timezone.now()
        self.reviewer = _user("l3a-ticket-reviewer@example.com")
        self.countries = {
            code: Country.objects.create(
                code=code,
                name=name,
                source="l3a-test",
                source_id=f"country-{code}",
                source_version="l3a",
            )
            for code, name in (
                ("DZ", "Algeria"),
                ("FR", "France"),
                ("ES", "Spain"),
                ("DE", "Germany"),
            )
        }
        # No coordinates on purpose: exercises the crash guards (see above).
        self.lille = self.city("FR", "Lille")
        self.paris = self.city("FR", "Paris")
        self.lyon = self.city("FR", "Lyon")
        self.marseille = self.city("FR", "Marseille")
        self.barcelona = self.city("ES", "Barcelona")
        self.berlin = self.city("DE", "Berlin")
        self.algiers = self.city("DZ", "Algiers", "36.753800", "3.058800")
        self.setif = self.city("DZ", "Sétif", "36.191100", "5.413700")
        self.constantine = self.city("DZ", "Constantine", "36.365000", "6.614700")
        self.oran = self.city("DZ", "Oran", "35.697100", "-0.630800")
        self.alg = self.airport("DZ", "Houari Boumediene", "ALG", self.algiers, "36.691000", "3.215400")
        self.cdg = self.airport("FR", "Charles de Gaulle", "CDG", self.paris, "49.009700", "2.547900")

        self.marseille_algiers = self.crossing(self.marseille, self.algiers, active=True)
        self.algiers_marseille = self.crossing(self.algiers, self.marseille, active=True)
        # Two port cities whose only line staff have switched off.
        self.barcelona_oran = self.crossing(
            self.barcelona, self.oran, distance=520_000, active=False
        )

    # -- geography ----------------------------------------------------------

    def city(
        self,
        country: str,
        name: str,
        latitude: str | None = None,
        longitude: str | None = None,
        *,
        suffix: str = "main",
    ) -> Place:
        return Place.objects.create(
            country=self.countries[country],
            place_type=Place.PlaceType.LOCALITY,
            source="l3a-test",
            source_id=f"locality-{country}-{name}-{suffix}",
            source_version="l3a",
            name=name,
            latitude=Decimal(latitude) if latitude else None,
            longitude=Decimal(longitude) if longitude else None,
        )

    def airport(self, country: str, name: str, iata: str, served: Place, latitude: str, longitude: str) -> Place:
        place = Place.objects.create(
            country=self.countries[country],
            place_type=Place.PlaceType.AIRPORT,
            source="l3a-test",
            source_id=f"airport-{iata}",
            source_version="l3a",
            name=name,
            iata_code=iata,
            latitude=Decimal(latitude),
            longitude=Decimal(longitude),
            passenger_use=True,
        )
        AirportLocalityMapping.objects.create(
            airport=place,
            locality=served,
            relationship_type=AirportLocalityMapping.RelationshipType.SERVED,
            is_primary=True,
            source="l3a-test",
            source_id=f"mapping-{iata}",
            source_version="l3a",
        )
        return place

    def crossing(self, origin: Place, destination: Place, *, distance: int = MARSEILLE_ALGIERS_METERS, active: bool) -> SeaCrossing:
        return SeaCrossing.objects.create(
            origin_locality=origin,
            destination_locality=destination,
            distance_meters=distance,
            is_active=active,
        )

    def set_sea_switch(self, enabled: bool) -> None:
        activate_marketplace({"sea_legs_enabled": enabled})

    # -- people -------------------------------------------------------------

    def person(self, email: str, *, verified: bool = True):
        user = _user(email)
        if verified:
            _approve_kyc(user, email.split("@")[0])
        return user

    # -- inventory ----------------------------------------------------------

    def make_journey(
        self,
        traveler,
        legs: list[tuple[str, Place, Place]],
        *,
        start=None,
        capacity: str = "10.00",
        status: str = Journey.Status.ACTIVE,
        approve_tickets: bool = True,
        road_distance: int | None = 150_000,
        **leg_fields,
    ) -> Journey:
        """A published canonical journey, legs three hours apart.

        Each leg takes two hours and departs an hour after the previous one
        arrived. Ticket legs get an approved proof unless told otherwise, and
        road legs carry the stored distance a route snapshot would have left.
        """

        start = start or self.now + timedelta(days=3)
        journey = Journey.objects.create(
            traveler=traveler,
            schema_version=2,
            start_place=legs[0][1],
            destination_place=legs[-1][2],
            status=status,
            published_at=self.now if status == Journey.Status.ACTIVE else None,
        )
        for position, (mode, origin, destination) in enumerate(legs):
            depart = start + timedelta(hours=3 * position)
            fields = {
                "capacity_kg": Decimal(capacity),
                **leg_fields,
            }
            if mode == FLIGHT:
                fields["flight_number"] = f"AH{1000 + position}"
            if mode == SEA:
                fields.update(distance_meters=MARSEILLE_ALGIERS_METERS, route_provider="sea_crossing")
            if mode == DRIVE and road_distance is not None:
                fields.update(distance_meters=road_distance, route_provider="catalogue_snapshot")
            leg = JourneyLeg.objects.create(
                journey=journey,
                position=position,
                mode=mode,
                origin_place=origin,
                destination_place=destination,
                depart_at=depart,
                arrive_at=depart + timedelta(hours=2),
                **fields,
            )
            if approve_tickets and mode in (FLIGHT, SEA):
                self.ticket(leg, JourneyLegProof.Status.APPROVED)
        return journey

    def ticket(self, leg: JourneyLeg, status: str, *, reviewer=None) -> JourneyLegProof:
        reviewed = status != JourneyLegProof.Status.PENDING
        return JourneyLegProof.objects.create(
            leg=leg,
            bucket="private",
            object_key=f"l3a/{leg.pk}-{status}-{JourneyLegProof.objects.count()}.jpg",
            status=status,
            reviewer=(reviewer or self.reviewer) if reviewed else None,
            reviewed_at=self.now if reviewed else None,
            rejection_reason="Unreadable" if status == JourneyLegProof.Status.REJECTED else "",
        )

    def stop(self, journey: Journey, position: int, **fields) -> JourneyStopDetail:
        return JourneyStopDetail.objects.create(journey=journey, position=position, **fields)

    def request(
        self,
        sender,
        origin: Place,
        destination: Place,
        *,
        pickup_at,
        deliver_by,
        weight: str = "2.00",
        dimensions: tuple[str, str, str] | None = ("20.00", "15.00", "10.00"),
        category: str = ParcelRequest.ItemType.DOCUMENTS,
        fragile: bool = False,
        reward: int = 3_000,
    ) -> DeliveryRequest:
        length, width, height = dimensions or (None, None, None)
        return DeliveryRequest.objects.create(
            sender=sender,
            kind=ParcelRequest.Kind.DELIVERY,
            schema_version=3,
            pickup_place=origin,
            delivery_place=destination,
            ready_window_start=pickup_at - timedelta(hours=2),
            ready_window_end=pickup_at + timedelta(minutes=30),
            deadline_at=deliver_by,
            actual_weight_kg=Decimal(weight),
            length_cm=Decimal(length) if length else None,
            width_cm=Decimal(width) if width else None,
            height_cm=Decimal(height) if height else None,
            declared_value_eur_cents=10_000,
            traveler_reward_eur_cents=reward,
            title="L3A parcel",
            description="Sealed documents",
            category=category,
            item_type=category,
            fragile=fragile,
            description_is_accurate=True,
            item_is_legal=True,
            no_prohibited_goods=True,
            declared_value_is_accurate=True,
            customs_responsibilities_understood=True,
            base_amount_dzd=None,
        )

    def request_over(self, sender, journey: Journey, first: int, last: int, **fields) -> DeliveryRequest:
        """A request boarding at leg ``first`` and leaving after leg ``last``."""

        legs = list(journey.legs.order_by("position"))
        return self.request(
            sender,
            legs[first].origin_place.resolve_matching_locality(),
            legs[last].destination_place.resolve_matching_locality(),
            pickup_at=legs[first].depart_at,
            deliver_by=legs[last].arrive_at + timedelta(days=1),
            **fields,
        )
