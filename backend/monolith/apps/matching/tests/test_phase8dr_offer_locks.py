"""Phase 8D-R — the V1 negotiation row locks, against canonical geography.

`JourneyLeg.origin`/`destination` became nullable with Phase 8C canonical
geography, so `select_related("origin", "destination")` compiles to a LEFT
OUTER JOIN. A bare `FOR UPDATE` over that join is rejected by PostgreSQL
("FOR UPDATE cannot be applied to the nullable side of an outer join") and
silently dropped by SQLite, which has no `has_select_for_update` — so the
sender-offer path could not create a single offer on PostgreSQL while every
SQLite run stayed green.

These tests therefore assert three separate things:

* the negotiation behaves correctly over a canonical FLIGHT + DRIVE journey
  whose legs carry no `Location` rows at all, which is the shape that made the
  join nullable in production;
* every row lock the negotiation emits names the table it locks whenever its
  query outer-joins, which is the structural property the repair restored;
* the leg rows are really locked — the repair did not buy a compiling query by
  giving up concurrency protection.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier, Event
from unittest.mock import patch

from django.db import (
    IntegrityError,
    OperationalError,
    close_old_connections,
    connection,
    connections,
    transaction,
)
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import User
from apps.deals.models import Deal, DealLegAllocation
from apps.locations.models import AirportLocalityMapping, Country, Place
from apps.matching.models import Match, MatchEvent, Offer
from apps.matching.v1_services import (
    InvalidLegRange,
    JourneyNotActive,
    OfferAuthorizationError,
    OfferStateError,
    RequestNotOpen,
    accept_offer,
    counter_offer,
    create_sender_offer,
)
from apps.parcels.models import DeliveryRequest, ParcelRequest
from apps.trips.models import Journey, JourneyLeg, JourneyLegProof

from .test_v1_matching import _approve_kyc, _ensure_business_settings, _user

REWARD_EUR_CENTS = 3_000


class CanonicalOfferFixture:
    """A canonical Paris → Jijel request over a CDG → ALG → Jijel journey.

    Every leg is described by `origin_place`/`destination_place` only. The
    legacy `origin`/`destination` Location columns stay NULL, which is what
    turns `select_related("origin", "destination")` into an outer join.
    """

    def build_world(self) -> None:
        _ensure_business_settings()
        self.now = timezone.now()
        self.depart = self.now + timedelta(days=2)
        self.sender = _user("phase8dr-sender@example.com")
        self.traveler = _user("phase8dr-traveler@example.com")
        self.other = _user("phase8dr-other@example.com")
        self.kyc = _approve_kyc(self.traveler, "phase8dr-traveler")

        self.countries = {
            code: Country.objects.create(
                code=code,
                name=name,
                source="phase8dr-test",
                source_id=f"country-{code}",
                source_version="phase8dr",
            )
            for code, name in (("DZ", "Algeria"), ("FR", "France"))
        }
        self.paris = self._locality("FR", "Paris", "48.8566", "2.3522")
        # A second, distinct canonical Paris a few metres away. Canonical
        # identity must reject it; proximity must never rescue it.
        self.paris_twin = self._locality(
            "FR", "Paris", "48.8567", "2.3523", suffix="twin"
        )
        self.algiers = self._locality("DZ", "Algiers", "36.7538", "3.0588")
        self.jijel = self._locality("DZ", "Jijel", "36.8206", "5.7667")
        self.cdg = self._airport("FR", "Paris Charles de Gaulle", "CDG", self.paris)
        self.alg = self._airport("DZ", "Houari Boumediene", "ALG", self.algiers)

        self.request = self._request(self.paris, self.jijel)
        self.journey, self.flight_leg, self.drive_leg = self._journey(self.traveler)

    def _locality(
        self,
        country_code: str,
        name: str,
        latitude: str,
        longitude: str,
        *,
        suffix: str = "main",
    ) -> Place:
        return Place.objects.create(
            country=self.countries[country_code],
            place_type=Place.PlaceType.LOCALITY,
            source="phase8dr-test",
            source_id=f"locality-{country_code}-{name}-{suffix}",
            source_version="phase8dr",
            name=name,
            latitude=Decimal(latitude),
            longitude=Decimal(longitude),
        )

    def _airport(
        self, country_code: str, name: str, iata: str, locality: Place
    ) -> Place:
        airport = Place.objects.create(
            country=self.countries[country_code],
            place_type=Place.PlaceType.AIRPORT,
            source="phase8dr-test",
            source_id=f"airport-{iata}",
            source_version="phase8dr",
            name=name,
            latitude=locality.latitude,
            longitude=locality.longitude,
            iata_code=iata,
            passenger_use=True,
        )
        AirportLocalityMapping.objects.create(
            airport=airport,
            locality=locality,
            relationship_type=AirportLocalityMapping.RelationshipType.SERVED,
            is_primary=True,
            source="phase8dr-test",
            source_id=f"mapping-{iata}",
            source_version="phase8dr",
        )
        return airport

    def _request(
        self, origin: Place, destination: Place, *, title: str = "Canonical request"
    ) -> DeliveryRequest:
        return DeliveryRequest.objects.create(
            sender=self.sender,
            kind=ParcelRequest.Kind.DELIVERY,
            schema_version=3,
            pickup_place=origin,
            delivery_place=destination,
            ready_window_start=self.depart - timedelta(hours=1),
            ready_window_end=self.depart + timedelta(hours=1),
            deadline_at=self.depart + timedelta(hours=16),
            actual_weight_kg=Decimal("2.00"),
            length_cm=Decimal("20.00"),
            width_cm=Decimal("15.00"),
            height_cm=Decimal("10.00"),
            declared_value_eur_cents=10_000,
            traveler_reward_eur_cents=REWARD_EUR_CENTS,
            title=title,
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

    def _journey(
        self, traveler: User, *, origin: Place | None = None
    ) -> tuple[Journey, JourneyLeg, JourneyLeg]:
        origin = origin or self.cdg
        journey = Journey.objects.create(
            traveler=traveler,
            schema_version=2,
            start_place=origin,
            destination_place=self.jijel,
            status=Journey.Status.ACTIVE,
            published_at=self.now,
        )
        flight = JourneyLeg.objects.create(
            journey=journey,
            position=0,
            mode=JourneyLeg.Mode.FLIGHT,
            origin_place=origin,
            destination_place=self.alg,
            depart_at=self.depart,
            arrive_at=self.depart + timedelta(hours=3),
            capacity_kg=Decimal("8.00"),
            flight_number="AF1354",
        )
        drive = JourneyLeg.objects.create(
            journey=journey,
            position=1,
            mode=JourneyLeg.Mode.DRIVE,
            origin_place=self.algiers,
            destination_place=self.jijel,
            depart_at=self.depart + timedelta(hours=4),
            arrive_at=self.depart + timedelta(hours=9),
            capacity_kg=Decimal("8.00"),
            distance_meters=320_000,
            route_provider="catalogue_snapshot",
        )
        JourneyLegProof.objects.create(
            leg=flight,
            bucket="private",
            object_key=f"phase8dr/{journey.pk}-ticket.jpg",
            status=JourneyLegProof.Status.APPROVED,
            reviewer=self.sender,
            reviewed_at=self.now,
        )
        return journey, flight, drive

    def propose(self, **overrides) -> Offer:
        kwargs = {
            "sender": self.sender,
            "delivery_request": self.request,
            "journey": self.journey,
            "start_leg_id": self.flight_leg.pk,
            "end_leg_id": self.drive_leg.pk,
            "traveler_reward_eur_cents": REWARD_EUR_CENTS,
        }
        kwargs.update(overrides)
        return create_sender_offer(**kwargs)


class CanonicalSenderOfferTests(CanonicalOfferFixture, TestCase):
    """The gates the sender-offer transaction must still enforce."""

    def setUp(self):
        self.build_world()

    def test_legs_under_test_really_have_no_location_rows(self):
        # If this ever stops holding, the regressions below stop covering the
        # outer join they were written for.
        self.assertEqual(
            JourneyLeg.objects.filter(
                journey=self.journey, origin__isnull=True, destination__isnull=True
            ).count(),
            2,
        )

    def test_sender_creates_one_offer_over_the_canonical_subroute(self):
        offer = self.propose()

        match = offer.match
        self.assertEqual(match.parcel_id, self.request.parcelrequest_ptr_id)
        self.assertEqual(match.journey_id, self.journey.pk)
        self.assertEqual(match.sender_id, self.sender.pk)
        self.assertEqual(match.traveler_id, self.traveler.pk)
        self.assertEqual(match.status, Match.Status.PENDING)
        self.assertEqual(match.start_leg_id, self.flight_leg.pk)
        self.assertEqual(match.end_leg_id, self.drive_leg.pk)
        self.assertTrue(match.compatibility_snapshot["compatible"])

        self.assertEqual(offer.proposed_by, Offer.ProposedBy.SENDER)
        self.assertEqual(offer.proposer_id, self.sender.pk)
        self.assertEqual(offer.status, Offer.Status.PENDING)
        self.assertEqual(offer.currency, Offer.Currency.EUR)
        self.assertEqual(offer.economics_version, Offer.EconomicsVersion.V1_EUR)
        self.assertEqual(offer.traveler_reward_minor, REWARD_EUR_CENTS)
        self.assertIsNotNone(offer.business_settings_version_id)

        event = MatchEvent.objects.get(match=match, kind=MatchEvent.Kind.OFFER_CREATED)
        self.assertEqual(event.payload["start_leg_id"], self.flight_leg.pk)
        self.assertEqual(event.payload["end_leg_id"], self.drive_leg.pk)
        self.assertEqual(Match.objects.count(), 1)
        self.assertEqual(Offer.objects.count(), 1)

    def test_only_the_request_sender_may_propose(self):
        with self.assertRaises(OfferAuthorizationError) as caught:
            self.propose(sender=self.other)
        self.assertEqual(caught.exception.code, "not_authorized")
        self.assertEqual(Match.objects.count(), 0)

    def test_a_sender_cannot_propose_to_their_own_journey(self):
        _approve_kyc(self.sender, "phase8dr-self")
        journey, flight, drive = self._journey(self.sender)

        with self.assertRaises(OfferAuthorizationError):
            self.propose(journey=journey, start_leg_id=flight.pk, end_leg_id=drive.pk)
        self.assertEqual(Match.objects.count(), 0)

    def test_a_targeted_request_refuses_a_different_traveler(self):
        self.request.target_traveler = self.other
        self.request.save(update_fields=["target_traveler", "updated_at"])

        with self.assertRaises(OfferAuthorizationError):
            self.propose()
        self.assertEqual(Match.objects.count(), 0)

    def test_a_closed_request_takes_no_offer(self):
        self.request.status = ParcelRequest.Status.MATCHED
        self.request.save(update_fields=["status", "updated_at"])

        with self.assertRaises(RequestNotOpen):
            self.propose()
        self.assertEqual(Match.objects.count(), 0)

    def test_an_inactive_journey_takes_no_offer(self):
        self.journey.status = Journey.Status.CANCELLED
        self.journey.save(update_fields=["status", "updated_at"])

        with self.assertRaises(JourneyNotActive):
            self.propose()
        self.assertEqual(Match.objects.count(), 0)

    def test_a_request_closed_after_preflight_is_refused_under_the_lock(self):
        """The locked re-read, not the preflight, is what decides."""

        from apps.matching import v1_services

        original = v1_services._preflight_evaluation

        def close_the_request(**kwargs):
            provider = original(**kwargs)
            DeliveryRequest.objects.filter(pk=self.request.pk).update(
                status=ParcelRequest.Status.MATCHED
            )
            return provider

        with patch.object(v1_services, "_preflight_evaluation", close_the_request):
            with self.assertRaises(RequestNotOpen):
                self.propose()
        self.assertEqual(Match.objects.count(), 0)

    def test_a_journey_cancelled_after_preflight_is_refused_under_the_lock(self):
        from apps.matching import v1_services

        original = v1_services._preflight_evaluation

        def cancel_the_journey(**kwargs):
            provider = original(**kwargs)
            Journey.objects.filter(pk=self.journey.pk).update(
                status=Journey.Status.CANCELLED
            )
            return provider

        with patch.object(v1_services, "_preflight_evaluation", cancel_the_journey):
            with self.assertRaises(JourneyNotActive):
                self.propose()
        self.assertEqual(Match.objects.count(), 0)

    def test_canonical_identity_is_still_the_whole_compatibility_rule(self):
        """A metres-away twin locality is a different place, and stays one.

        The two requests differ only in which canonical Paris they name. The
        journey, the legs, the weight and the reward are identical, so the
        refusal below can only come from locality identity — never from
        distance, radius or a matching name.
        """

        twin_request = self._request(
            self.paris_twin, self.jijel, title="Twin-locality request"
        )

        with self.assertRaises(OfferStateError):
            self.propose(delivery_request=twin_request)
        self.assertEqual(Match.objects.count(), 0)

        self.assertIsNotNone(self.propose())
        self.assertEqual(Match.objects.count(), 1)

    def test_the_submitted_leg_range_must_equal_the_server_subroute(self):
        with self.assertRaises(InvalidLegRange):
            self.propose(start_leg_id=self.drive_leg.pk, end_leg_id=self.drive_leg.pk)
        self.assertEqual(Match.objects.count(), 0)

    def test_the_traveler_can_counter_the_canonical_offer(self):
        offer = self.propose()

        child = counter_offer(
            pending_offer=offer,
            actor=self.traveler,
            traveler_reward_eur_cents=REWARD_EUR_CENTS + 400,
        )

        offer.refresh_from_db()
        self.assertEqual(offer.status, Offer.Status.COUNTERED)
        self.assertEqual(child.parent_offer_id, offer.pk)
        self.assertEqual(child.proposed_by, Offer.ProposedBy.TRAVELER)
        self.assertEqual(child.traveler_reward_minor, REWARD_EUR_CENTS + 400)

    def test_acceptance_allocates_both_canonical_legs(self):
        offer = self.propose()

        accepted = accept_offer(pending_offer=offer, actor=self.traveler)

        self.assertTrue(accepted.created)
        self.assertEqual(Deal.objects.count(), 1)
        allocated = set(
            DealLegAllocation.objects.filter(deal=accepted.deal).values_list(
                "journey_leg_id", flat=True
            )
        )
        self.assertEqual(allocated, {self.flight_leg.pk, self.drive_leg.pk})


class CanonicalOfferLockShapeTests(CanonicalOfferFixture, TestCase):
    """Every emitted row lock must name its table when the query outer-joins.

    This is the structural guard. On a backend without row locks the assertion
    is vacuous, so the test says so rather than passing silently.
    """

    def setUp(self):
        self.build_world()

    def _assert_locks_are_well_formed(self, captured) -> int:
        # Phase 8D-F took the whole canonical graph down to FOR NO KEY UPDATE,
        # so both modes have to be recognised here. The rule this guard exists
        # for is unchanged: whichever mode a locking query uses, it must name
        # its tables when it outer-joins.
        locking = []
        for entry in captured.captured_queries:
            mode = next(
                (
                    candidate
                    for candidate in ("FOR NO KEY UPDATE", "FOR UPDATE")
                    if candidate in entry["sql"]
                ),
                None,
            )
            if mode is not None:
                locking.append((mode, entry["sql"]))
        for mode, sql in locking:
            if "LEFT OUTER JOIN" in sql:
                self.assertIn(
                    f"{mode} OF",
                    sql,
                    msg=(
                        "A lock over an outer join must name its tables; "
                        "PostgreSQL rejects a bare row lock there."
                    ),
                )
        return len(locking)

    def test_create_counter_and_accept_emit_only_well_formed_locks(self):
        with CaptureQueriesContext(connection) as captured:
            offer = self.propose()
            child = counter_offer(
                pending_offer=offer,
                actor=self.traveler,
                traveler_reward_eur_cents=REWARD_EUR_CENTS + 400,
            )
            accept_offer(pending_offer=child, actor=self.sender)

        locking = self._assert_locks_are_well_formed(captured)
        if connection.features.has_select_for_update:
            self.assertGreater(
                locking,
                0,
                "This backend locks rows, so the negotiation must emit locks.",
            )


@skipUnlessDBFeature("has_select_for_update")
class CanonicalOfferLockConcurrencyTests(CanonicalOfferFixture, TransactionTestCase):
    """The repaired lock still has to be a lock."""

    reset_sequences = True

    def setUp(self):
        self.build_world()

    def _touch_the_flight_leg(self) -> str:
        close_old_connections()
        try:
            with transaction.atomic():
                with connections["default"].cursor() as cursor:
                    cursor.execute("SET LOCAL lock_timeout = '750ms'")
                JourneyLeg.objects.filter(pk=self.flight_leg.pk).update(
                    capacity_kg=Decimal("1.00")
                )
            return "updated"
        except OperationalError:
            return "blocked"
        finally:
            connections.close_all()

    def test_offer_creation_holds_the_journey_leg_rows_until_commit(self):
        reached_offer_insert = Event()
        release_offer_insert = Event()
        original_save = Offer.save

        def paused_save(instance, *args, **kwargs):
            if instance._state.adding:
                reached_offer_insert.set()
                if not release_offer_insert.wait(timeout=10):
                    raise AssertionError("Timed out holding the offer locks.")
            return original_save(instance, *args, **kwargs)

        def propose_in_thread():
            close_old_connections()
            try:
                return self.propose().pk
            finally:
                connections.close_all()

        with patch.object(Offer, "save", paused_save):
            with ThreadPoolExecutor(max_workers=2) as executor:
                proposal = executor.submit(propose_in_thread)
                self.assertTrue(
                    reached_offer_insert.wait(timeout=10),
                    "The proposal never reached its Offer insert.",
                )
                competitor = executor.submit(self._touch_the_flight_leg)
                blocked_result = competitor.result(timeout=5)
                release_offer_insert.set()
                offer_id = proposal.result(timeout=10)

        self.assertEqual(blocked_result, "blocked")
        self.assertTrue(Offer.objects.filter(pk=offer_id).exists())
        # The same write succeeds once nothing holds the leg, so the block
        # above was the lock and not a broken statement.
        self.assertEqual(self._touch_the_flight_leg(), "updated")

    def _propose_after_barrier(self, request_id: int, barrier: Barrier) -> str:
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            self.propose(delivery_request=DeliveryRequest.objects.get(pk=request_id))
            return "created"
        except IntegrityError:
            return "conflict"
        except OfferStateError:
            return "refused"
        finally:
            connections.close_all()

    def test_two_racing_proposals_on_one_request_leave_one_pending_match(self):
        barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    lambda _: self._propose_after_barrier(self.request.pk, barrier),
                    range(2),
                )
            )

        self.assertEqual(results.count("created"), 1, results)
        self.assertEqual(
            Match.objects.filter(
                parcel_id=self.request.parcelrequest_ptr_id,
                journey_id=self.journey.pk,
                status=Match.Status.PENDING,
            ).count(),
            1,
        )
        self.assertEqual(Offer.objects.count(), Match.objects.count())

    def test_two_requests_sharing_one_journey_propose_without_deadlock(self):
        second = self._request(self.paris, self.jijel, title="Second canonical")
        barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    lambda request_id: self._propose_after_barrier(
                        request_id, barrier
                    ),
                    (self.request.pk, second.pk),
                )
            )

        self.assertEqual(results, ["created", "created"], results)
        self.assertEqual(Match.objects.count(), 2)
        self.assertEqual(Offer.objects.count(), 2)
