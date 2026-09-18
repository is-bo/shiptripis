"""Phase J7B — published request route and matching reliability.

The owner reported two things on a real device: a published request opened to
an empty route, and a Sender request and a Traveler Journey on the same route
with compatible timing never met in Find Travelers.

The empty route is a client defect and is pinned in the mobile suite. What is
pinned here is the other half of it — that the server hands every published
request its canonical route, at every status and in every language — and the
matching defect, which was on the server.

**The matching defect.** A Journey leg's arrival time was optional at write
time; the traveller app even labelled it "Optional". `evaluate_compatibility`
cannot deliver a parcel at the end of a leg whose arrival it does not know: it
compares that arrival with the Sender's deadline. So a Journey written without
one was accepted, published, listed as active and discoverable — and then
refused every request that ended on it, on `route_time_order_feasible` and
`delivery_before_deadline`. Nothing anywhere said why. The repair is at the
write contract, not in matching: an arrival is required on every leg, and
publication refuses a draft that predates the rule.

The rest of this file is the brief's matrix, run end to end over canonical
geography: direct, contained and whole multi-leg routes match; timing,
capacity, lifecycle and route negatives do not; ineligible requests say so.
"""

from __future__ import annotations

from datetime import timedelta, timezone as dt_timezone
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.finance.models import PaymentAttempt, PaymentOrder
from apps.finance.services import reconcile_attempt
from apps.matching.compatibility import evaluate_compatibility
from apps.matching.discovery import _matching_journey_queryset
from apps.matching.find_travelers import (
    STATE_NO_CANDIDATES,
    STATE_REQUEST_INELIGIBLE,
    STATE_RESULTS,
)
from apps.matching.tests.test_phase_j4_find_travelers import FindTravelersFixture
from apps.matching.tests.test_phase8dr_offer_locks import REWARD_EUR_CENTS
from apps.matching.v1_services import accept_offer
from apps.parcels.models import DeliveryRequest, ParcelMedia, ParcelRequest
from apps.trips.lifecycle import discoverable
from apps.trips.models import Journey, JourneyLeg, JourneyLegProof

FIND = "matches-find-travelers-v1"


def client_for(user, *, language: str | None = None) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    if language:
        client.credentials(HTTP_ACCEPT_LANGUAGE=language)
    return client


class RouteMatchingFixture(FindTravelersFixture):
    """The J4 canonical world, plus journeys and requests shaped per case.

    Geography: Paris, Algiers and Jijel localities; CDG serves Paris and ALG
    serves Algiers through their active primary SERVED mappings. `other` is
    Traveler B, KYC-approved like `traveler`.
    """

    def setUp(self):
        super().setUp()
        from apps.matching.tests.test_v1_matching import _approve_kyc

        _approve_kyc(self.other, "j7b-other")

    def request_between(
        self,
        origin,
        destination,
        *,
        ready_start,
        ready_end,
        deadline,
        weight: str = "2.00",
        status: str = ParcelRequest.Status.OPEN,
    ) -> DeliveryRequest:
        return DeliveryRequest.objects.create(
            sender=self.sender,
            kind=ParcelRequest.Kind.DELIVERY,
            schema_version=3,
            status=status,
            pickup_place=origin,
            delivery_place=destination,
            ready_window_start=ready_start,
            ready_window_end=ready_end,
            deadline_at=deadline,
            actual_weight_kg=Decimal(weight),
            declared_value_eur_cents=10_000,
            traveler_reward_eur_cents=REWARD_EUR_CENTS,
            title="J7B request",
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

    def journey_over(self, traveler, stops, *, status=Journey.Status.ACTIVE):
        """A published canonical journey over `stops`.

        Each stop is `(place, mode_of_the_leg_that_leaves_it, depart, arrive)`
        except the last, which is only a place. FLIGHT legs get an approved
        proof, as publication requires.
        """

        journey = Journey.objects.create(
            traveler=traveler,
            schema_version=2,
            start_place=stops[0][0],
            destination_place=stops[-1]
            if not isinstance(stops[-1], tuple)
            else stops[-1][0],
            status=status,
            published_at=self.now,
        )
        legs = []
        for position, (origin, mode, depart, arrive) in enumerate(stops[:-1]):
            destination = stops[position + 1]
            destination = (
                destination[0] if isinstance(destination, tuple) else destination
            )
            leg = JourneyLeg.objects.create(
                journey=journey,
                position=position,
                mode=mode,
                origin_place=origin,
                destination_place=destination,
                depart_at=depart,
                arrive_at=arrive,
                capacity_kg=Decimal("8.00"),
                flight_number="AH1000" if mode == JourneyLeg.Mode.FLIGHT else "",
                distance_meters=None if mode == JourneyLeg.Mode.FLIGHT else 320_000,
                route_provider=""
                if mode == JourneyLeg.Mode.FLIGHT
                else "catalogue_snapshot",
            )
            if mode == JourneyLeg.Mode.FLIGHT:
                JourneyLegProof.objects.create(
                    leg=leg,
                    bucket="private",
                    object_key=f"j7b/{uuid4().hex}.jpg",
                    status=JourneyLegProof.Status.APPROVED,
                    reviewer=self.sender,
                    reviewed_at=self.now,
                )
            legs.append(leg)
        return journey, legs

    def verdict(self, delivery_request, journey):
        return evaluate_compatibility(
            delivery_request=delivery_request,
            journey=_matching_journey_queryset(at=timezone.now()).get(pk=journey.pk),
            policy=self.policy,
        )

    def found(self, delivery_request) -> list[int]:
        return [row["journey_id"] for row in self.page(delivery_request)["results"]]


# ---------------------------------------------------------------------------
# The owner's scenario, through the endpoints the phone actually calls
# ---------------------------------------------------------------------------


@patch("apps.core.redis_bus.publish_after_commit")
class OwnerScenarioTests(RouteMatchingFixture, TestCase):
    """Account A posts Algiers → Paris; Account B flies ALG → CDG that week.

    Both halves go through the real write APIs: the Journey is created and
    published over HTTP (with its flight proof approved, as a reviewer would),
    and the request is created over HTTP and published by a Stripe-TEST
    deposit settling through the same `reconcile_attempt` the webhook uses.
    Nothing is written straight into a status column.
    """

    def setUp(self):
        super().setUp()
        self.departs = (self.now + timedelta(days=3)).replace(
            hour=10, minute=0, second=0, microsecond=0
        )

    def _journey_body(self, **leg_overrides) -> dict:
        leg = {
            "position": 0,
            "mode": "FLIGHT",
            "origin_place_id": self.alg.pk,
            "destination_place_id": self.cdg.pk,
            "depart_at": self.departs.isoformat(),
            "arrive_at": (self.departs + timedelta(hours=3)).isoformat(),
            "capacity_kg": "10.00",
            "flight_number": "AH1000",
        }
        leg.update(leg_overrides)
        leg = {key: value for key, value in leg.items() if value is not ...}
        return {
            "start_place_id": self.algiers.pk,
            "destination_place_id": self.paris.pk,
            "notes": "",
            "legs": [leg],
        }

    def _publish_journey(self, body) -> Journey:
        client = client_for(self.other)
        created = client.post(reverse("journeys-list-create"), body, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        journey = Journey.objects.get(pk=created.data["id"])
        for leg in journey.legs.filter(mode=JourneyLeg.Mode.FLIGHT):
            JourneyLegProof.objects.create(
                leg=leg,
                bucket="private",
                object_key=f"j7b/{uuid4().hex}.jpg",
                status=JourneyLegProof.Status.APPROVED,
                reviewer=self.sender,
                reviewed_at=self.now,
            )
        published = client.post(reverse("journeys-publish", args=[journey.pk]))
        self.assertEqual(published.status_code, 200, published.data)
        return journey

    def _post_request(self, **overrides) -> DeliveryRequest:
        photo = ParcelMedia.objects.create(
            parcel=None,
            uploaded_by=self.sender,
            purpose=ParcelMedia.Purpose.ITEM_PHOTO,
            bucket="shiptrip-parcel-test",
            object_key=f"parcels/staged/{uuid4().hex}.jpg",
            content_type="image/jpeg",
            bytes=2048,
        )
        body = {
            "pickup_place_id": self.algiers.pk,
            "delivery_place_id": self.paris.pk,
            "ready_window_start": (self.departs - timedelta(days=1)).isoformat(),
            "ready_window_end": (self.departs + timedelta(hours=6)).isoformat(),
            "deadline_at": (self.departs + timedelta(days=2)).isoformat(),
            "actual_weight_kg": "2.50",
            "declared_value_eur_cents": 5_000,
            "sender_proposed_reward_eur_cents": 4_000,
            "title": "Documents for Paris",
            "description": "A sealed folder of documents.",
            "category": "documents",
            "handling_notes": "",
            "fragile": False,
            "item_photo_media_id": photo.pk,
            "description_is_accurate": True,
            "item_is_legal": True,
            "no_prohibited_goods": True,
            "declared_value_is_accurate": True,
            "customs_responsibilities_understood": True,
        }
        body.update(overrides)
        created = client_for(self.sender).post(
            reverse("parcels-delivery-v1-create"), body, format="json"
        )
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data["status"], ParcelRequest.Status.AWAITING_DEPOSIT)

        order = PaymentOrder.objects.get(
            delivery_request_id=created.data["id"],
            purpose=PaymentOrder.Purpose.POSTING_DEPOSIT,
        )
        outstanding = int(order.outstanding_eur_cents)
        tag = uuid4().hex[:12]
        attempt = PaymentAttempt.objects.create(
            order=order,
            provider="stripe",
            provider_mode="test",
            amount_eur_cents=outstanding,
            payment_currency="EUR",
            provider_amount_minor=outstanding,
            idempotency_key=f"j7b-{tag}",
            provider_session_id=f"cs_j7b_{tag}",
            provider_payment_id=f"pi_j7b_{tag}",
            status=PaymentAttempt.Status.CHECKOUT_PENDING,
        )
        self.assertEqual(
            reconcile_attempt(
                attempt_id=attempt.pk,
                outcome="succeeded",
                provider_payment_id=f"pi_j7b_{tag}",
                provider_amount_minor=outstanding,
                provider_currency="EUR",
            ),
            "applied",
        )
        return DeliveryRequest.objects.select_related(
            "sender", "pickup_place", "delivery_place"
        ).get(pk=created.data["id"])

    def test_same_route_same_week_meets_at_every_stage(self, _publish):
        journey = self._publish_journey(self._journey_body())
        request = self._post_request()

        # Request detail: published, with its canonical route and no pin.
        detail = client_for(self.sender).get(
            reverse("parcels-detail", args=[request.pk])
        )
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.data["status"], ParcelRequest.Status.OPEN)
        self.assertEqual(detail.data["pickup_place"]["id"], self.algiers.pk)
        self.assertEqual(detail.data["delivery_place"]["id"], self.paris.pk)
        self.assertIsNone(detail.data["pickup_location"])
        self.assertIsNone(detail.data["delivery_location"])

        # Journey: active and discoverable.
        journey.refresh_from_db()
        self.assertEqual(journey.status, Journey.Status.ACTIVE)
        self.assertTrue(discoverable(Journey.objects.filter(pk=journey.pk)).exists())

        # Evaluator, scan, and the endpoint the app renders.
        self.assertTrue(self.verdict(request, journey).compatible)
        response = client_for(self.sender).get(reverse(FIND), {"parcel_id": request.pk})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["state"], STATE_RESULTS)
        self.assertIn(
            journey.pk, [row["journey_id"] for row in response.data["results"]]
        )
        row = next(r for r in response.data["results"] if r["journey_id"] == journey.pk)
        stops = row["route"]["stops"]
        self.assertEqual(
            [(stop["label"], stop["airport_iata"]) for stop in stops],
            [("Algiers", "ALG"), ("Paris", "CDG")],
        )

    def test_a_leg_without_an_arrival_is_refused_at_write_time(self, _publish):
        """The defect. Before J7B this was a 201, then a published journey no
        request could ever match."""

        response = client_for(self.other).post(
            reverse("journeys-list-create"),
            self._journey_body(arrive_at=...),
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("arrive_at", response.data["legs"][0])
        self.assertFalse(Journey.objects.filter(traveler=self.other).exists())

        explicit_null = client_for(self.other).post(
            reverse("journeys-list-create"),
            self._journey_body(arrive_at=None),
            format="json",
        )
        self.assertEqual(explicit_null.status_code, 400)
        self.assertIn("arrive_at", explicit_null.data["legs"][0])

    def test_a_draft_written_before_the_rule_cannot_be_published(self, _publish):
        journey = Journey.objects.create(
            traveler=self.other,
            schema_version=2,
            start_place=self.algiers,
            destination_place=self.paris,
            status=Journey.Status.DRAFT,
        )
        leg = JourneyLeg.objects.create(
            journey=journey,
            position=0,
            mode=JourneyLeg.Mode.FLIGHT,
            origin_place=self.alg,
            destination_place=self.cdg,
            depart_at=self.departs,
            arrive_at=None,
            capacity_kg=Decimal("10.00"),
            flight_number="AH1000",
        )
        JourneyLegProof.objects.create(
            leg=leg,
            bucket="private",
            object_key=f"j7b/{uuid4().hex}.jpg",
            status=JourneyLegProof.Status.APPROVED,
            reviewer=self.sender,
            reviewed_at=self.now,
        )

        response = client_for(self.other).post(
            reverse("journeys-publish", args=[journey.pk])
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "journey_leg_arrival_required")
        journey.refresh_from_db()
        self.assertEqual(journey.status, Journey.Status.DRAFT)

    def test_an_already_published_arrivalless_journey_is_why_nothing_matched(
        self, _publish
    ):
        """What a pre-J7B Journey looks like to matching — unchanged by J7B.

        The evaluator is right to refuse it: there is no instant to compare
        with the deadline. J7B does not invent one; it stops new ones being
        written.
        """

        journey, (leg,) = self.journey_over(
            self.other,
            [(self.alg, JourneyLeg.Mode.FLIGHT, self.departs, None), self.cdg],
        )
        request = self._post_request()

        verdict = self.verdict(request, journey)
        self.assertFalse(verdict.compatible)
        self.assertEqual(
            set(verdict.rejection_codes),
            {"route_time_order_feasible", "delivery_before_deadline"},
        )
        # It is still listed as active inventory, which is what hid the fault.
        self.assertTrue(discoverable(Journey.objects.filter(pk=journey.pk)).exists())
        self.assertNotIn(journey.pk, self.found(request))


# ---------------------------------------------------------------------------
# The brief's matrix
# ---------------------------------------------------------------------------


class RouteShapeTests(RouteMatchingFixture, TestCase):
    """Direct, contained and whole multi-leg routes over canonical localities."""

    def setUp(self):
        super().setUp()
        self.d = self.depart

    def _window(self, pickup_at):
        return {
            "ready_start": pickup_at - timedelta(hours=12),
            "ready_end": pickup_at + timedelta(hours=1),
            "deadline": pickup_at + timedelta(days=2),
        }

    def test_direct_exact_route(self):
        journey, _ = self.journey_over(
            self.other,
            [
                (self.alg, JourneyLeg.Mode.FLIGHT, self.d, self.d + timedelta(hours=3)),
                self.cdg,
            ],
        )
        request = self.request_between(self.algiers, self.paris, **self._window(self.d))
        self.assertTrue(self.verdict(request, journey).compatible)
        self.assertIn(journey.pk, self.found(request))

    def test_a_journey_that_contains_the_request_route(self):
        # Journey Jijel → Algiers → Paris; request Algiers → Paris.
        journey, (drive, flight) = self.journey_over(
            self.other,
            [
                (
                    self.jijel,
                    JourneyLeg.Mode.DRIVE,
                    self.d - timedelta(hours=8),
                    self.d - timedelta(hours=3),
                ),
                (self.alg, JourneyLeg.Mode.FLIGHT, self.d, self.d + timedelta(hours=3)),
                self.cdg,
            ],
        )
        request = self.request_between(self.algiers, self.paris, **self._window(self.d))
        verdict = self.verdict(request, journey)
        self.assertTrue(verdict.compatible, verdict.rejection_codes)
        self.assertEqual([leg.pk for leg in verdict.covered_legs], [flight.pk])
        row = next(
            r for r in self.page(request)["results"] if r["journey_id"] == journey.pk
        )
        self.assertEqual(row["route_fit"], "good")
        self.assertTrue(row["route"]["continues_before"])

    def test_a_request_riding_the_whole_multi_leg_journey(self):
        # Journey Jijel → Algiers → Paris; request Jijel → Paris.
        start = self.d - timedelta(hours=8)
        journey, (drive, flight) = self.journey_over(
            self.other,
            [
                (self.jijel, JourneyLeg.Mode.DRIVE, start, self.d - timedelta(hours=3)),
                (self.alg, JourneyLeg.Mode.FLIGHT, self.d, self.d + timedelta(hours=3)),
                self.cdg,
            ],
        )
        request = self.request_between(self.jijel, self.paris, **self._window(start))
        verdict = self.verdict(request, journey)
        self.assertTrue(verdict.compatible, verdict.rejection_codes)
        self.assertEqual(
            [leg.pk for leg in verdict.covered_legs], [drive.pk, flight.pk]
        )
        row = next(
            r for r in self.page(request)["results"] if r["journey_id"] == journey.pk
        )
        self.assertEqual(row["route_fit"], "excellent")

    def test_the_fixture_middle_node_request(self):
        # The J4 world: CDG → ALG → Jijel. Request Algiers → Jijel (B → C).
        pickup = self.drive_leg.depart_at
        request = self.request_between(self.algiers, self.jijel, **self._window(pickup))
        verdict = self.verdict(request, self.journey)
        self.assertTrue(verdict.compatible, verdict.rejection_codes)
        self.assertEqual([leg.pk for leg in verdict.covered_legs], [self.drive_leg.pk])
        self.assertIn(self.journey.pk, self.found(request))

    def test_the_request_can_name_airports_instead_of_cities(self):
        request = self.request_between(self.cdg, self.jijel, **self._window(self.d))
        self.assertTrue(self.verdict(request, self.journey).compatible)

    def test_a_different_route_does_not_match(self):
        oran = self._locality("DZ", "Oran", "35.6976", "-0.6337")
        request = self.request_between(self.paris, oran, **self._window(self.d))
        self.assertFalse(self.verdict(request, self.journey).compatible)
        self.assertEqual(self.page(request)["state"], STATE_NO_CANDIDATES)

    def test_the_reverse_direction_does_not_match(self):
        request = self.request_between(
            self.jijel, self.paris, **self._window(self.drive_leg.depart_at)
        )
        verdict = self.verdict(request, self.journey)
        self.assertFalse(verdict.compatible)
        self.assertIn("pickup_before_delivery", verdict.rejection_codes)

    def test_a_same_named_twin_locality_does_not_match(self):
        request = self.request_between(
            self.paris_twin, self.jijel, **self._window(self.d)
        )
        self.assertFalse(self.verdict(request, self.journey).compatible)


class TimingTests(RouteMatchingFixture, TestCase):
    """Implementation checks only; the timing policy itself is unchanged."""

    def test_arrival_after_the_deadline_does_not_match(self):
        arrival = self.drive_leg.arrive_at
        request = self.request_between(
            self.paris,
            self.jijel,
            ready_start=self.depart - timedelta(hours=1),
            ready_end=self.depart + timedelta(hours=1),
            deadline=arrival - timedelta(minutes=1),
        )
        verdict = self.verdict(request, self.journey)
        self.assertFalse(verdict.compatible)
        self.assertEqual(verdict.rejection_codes, ("delivery_before_deadline",))
        self.assertEqual(self.page(request)["state"], STATE_NO_CANDIDATES)

    def test_every_boundary_is_inclusive(self):
        # Departure exactly at ready-start, and again exactly at ready-end;
        # arrival exactly at the deadline. `<=` throughout, never `<`.
        arrival = self.drive_leg.arrive_at
        for ready_start, ready_end in (
            (self.depart, self.depart + timedelta(hours=2)),
            (self.depart - timedelta(hours=2), self.depart),
        ):
            request = self.request_between(
                self.paris,
                self.jijel,
                ready_start=ready_start,
                ready_end=ready_end,
                deadline=arrival,
            )
            verdict = self.verdict(request, self.journey)
            self.assertTrue(verdict.compatible, verdict.rejection_codes)

    def test_a_departure_outside_the_ready_window_is_the_ready_window_rule(self):
        # Recorded, not changed: the parcel is collected at the traveller's
        # departure, so that departure must fall inside the sender's window.
        request = self.request_between(
            self.paris,
            self.jijel,
            ready_start=self.depart - timedelta(days=1),
            ready_end=self.depart - timedelta(hours=1),
            deadline=self.depart + timedelta(days=2),
        )
        verdict = self.verdict(request, self.journey)
        self.assertEqual(verdict.rejection_codes, ("pickup_within_ready_window",))

    def test_offsets_are_instants_not_wall_clock_labels(self):
        """A window posted in Algiers time is the same window posted in UTC."""

        algiers = dt_timezone(timedelta(hours=1))
        utc_request = self.request_between(
            self.paris,
            self.jijel,
            ready_start=self.depart - timedelta(hours=1),
            ready_end=self.depart + timedelta(hours=1),
            deadline=self.drive_leg.arrive_at,
        )
        local_request = self.request_between(
            self.paris,
            self.jijel,
            ready_start=(self.depart - timedelta(hours=1)).astimezone(algiers),
            ready_end=(self.depart + timedelta(hours=1)).astimezone(algiers),
            deadline=self.drive_leg.arrive_at.astimezone(algiers),
        )
        self.assertTrue(self.verdict(utc_request, self.journey).compatible)
        self.assertTrue(self.verdict(local_request, self.journey).compatible)


class CapacityTests(RouteMatchingFixture, TestCase):
    def test_a_parcel_heavier_than_the_leg_does_not_match(self):
        request = self.request_between(
            self.paris,
            self.jijel,
            ready_start=self.depart - timedelta(hours=1),
            ready_end=self.depart + timedelta(hours=1),
            deadline=self.depart + timedelta(days=1),
            weight="8.01",
        )
        verdict = self.verdict(request, self.journey)
        self.assertEqual(verdict.rejection_codes, ("capacity_available_on_every_leg",))
        self.assertEqual(self.page(request)["state"], STATE_NO_CANDIDATES)

    def test_a_parcel_exactly_at_capacity_matches(self):
        request = self.request_between(
            self.paris,
            self.jijel,
            ready_start=self.depart - timedelta(hours=1),
            ready_end=self.depart + timedelta(hours=1),
            deadline=self.depart + timedelta(days=1),
            weight="8.00",
        )
        self.assertTrue(self.verdict(request, self.journey).compatible)

    def test_capacity_reserved_by_an_accepted_offer_is_subtracted(self):
        offer = self.propose()
        accept_offer(pending_offer=offer, actor=self.traveler)
        # 2 kg of the 8 kg is now allocated; a 6.5 kg parcel no longer fits.
        request = self.request_between(
            self.paris,
            self.jijel,
            ready_start=self.depart - timedelta(hours=1),
            ready_end=self.depart + timedelta(hours=1),
            deadline=self.depart + timedelta(days=1),
            weight="6.50",
        )
        verdict = self.verdict(request, self.journey)
        self.assertEqual(verdict.rejection_codes, ("capacity_available_on_every_leg",))


class LifecycleEligibilityTests(RouteMatchingFixture, TestCase):
    def test_an_inactive_journey_does_not_match(self):
        for status in (
            Journey.Status.PENDING_VERIFICATION,
            Journey.Status.DRAFT,
            Journey.Status.CANCELLED,
            Journey.Status.EXPIRED,
        ):
            self.journey.status = status
            self.journey.save(update_fields=["status"])
            self.assertEqual(self.page()["state"], STATE_NO_CANDIDATES, status)

    def test_a_newly_published_journey_is_active_not_expired(self):
        self.assertTrue(
            discoverable(Journey.objects.filter(pk=self.journey.pk)).exists()
        )
        self.assertEqual(self.found(self.request), [self.journey.pk])

    def test_an_awaiting_deposit_request_is_ineligible(self):
        self.request.status = ParcelRequest.Status.AWAITING_DEPOSIT
        self.request.save(update_fields=["status"])
        payload = self.page()
        self.assertEqual(payload["state"], STATE_REQUEST_INELIGIBLE)
        self.assertEqual(payload["reason"], "awaiting_deposit")

    def test_an_already_matched_request_is_ineligible(self):
        offer = self.propose()
        accept_offer(pending_offer=offer, actor=self.traveler)
        self.request.refresh_from_db()
        self.assertEqual(self.request.status, ParcelRequest.Status.MATCHED)
        payload = self.page()
        self.assertEqual(payload["state"], STATE_REQUEST_INELIGIBLE)
        self.assertEqual(payload["reason"], "already_matched")

    def test_a_sender_never_matches_their_own_journey(self):
        own, _ = self.journey_over(
            self.sender,
            [
                (
                    self.cdg,
                    JourneyLeg.Mode.FLIGHT,
                    self.depart,
                    self.depart + timedelta(hours=3),
                ),
                (
                    self.alg,
                    JourneyLeg.Mode.DRIVE,
                    self.depart + timedelta(hours=4),
                    self.depart + timedelta(hours=9),
                ),
                self.jijel,
            ],
        )
        from apps.matching.tests.test_v1_matching import _approve_kyc

        _approve_kyc(self.sender, "j7b-self-match")
        self.assertNotIn(own.pk, self.found(self.request))
        self.assertIn(
            "accounts_eligible", self.verdict(self.request, own).rejection_codes
        )


# ---------------------------------------------------------------------------
# The published request's route, as the server serves it
# ---------------------------------------------------------------------------


class PublishedRequestRouteTests(RouteMatchingFixture, TestCase):
    def _detail(self, request=None, *, language=None):
        request = request or self.request
        response = client_for(self.sender, language=language).get(
            reverse("parcels-detail", args=[request.pk])
        )
        self.assertEqual(response.status_code, 200)
        return response.data

    def test_the_route_is_the_canonical_places_even_with_no_meeting_point(self):
        data = self._detail()
        self.assertIsNone(data["pickup_location"])
        self.assertIsNone(data["delivery_location"])
        self.assertEqual(data["pickup_place"]["id"], self.paris.pk)
        self.assertEqual(data["pickup_place"]["name"], "Paris")
        self.assertEqual(data["pickup_place"]["place_type"], "locality")
        self.assertIsNone(data["pickup_place"]["iata_code"])
        self.assertEqual(data["delivery_place"]["id"], self.jijel.pk)
        self.assertEqual(data["delivery_place"]["country_code"], "DZ")

    def test_an_airport_endpoint_carries_its_code_and_served_city(self):
        request = self.request_between(
            self.alg,
            self.paris,
            ready_start=self.depart - timedelta(hours=1),
            ready_end=self.depart + timedelta(hours=1),
            deadline=self.depart + timedelta(days=1),
        )
        pickup = self._detail(request)["pickup_place"]
        self.assertEqual(pickup["place_type"], "airport")
        self.assertEqual(pickup["iata_code"], "ALG")
        self.assertEqual(pickup["matching_locality_name"], "Algiers")

    def test_the_route_survives_every_status(self):
        for status in (
            ParcelRequest.Status.OPEN,
            ParcelRequest.Status.MATCHED,
            ParcelRequest.Status.IN_TRANSIT,
            ParcelRequest.Status.DELIVERED,
            ParcelRequest.Status.COMPLETED,
            ParcelRequest.Status.CANCELLED,
            ParcelRequest.Status.EXPIRED,
        ):
            ParcelRequest.objects.filter(pk=self.request.pk).update(status=status)
            data = self._detail()
            self.assertEqual(data["status"], status)
            self.assertEqual(data["pickup_place"]["id"], self.paris.pk, status)
            self.assertEqual(data["delivery_place"]["id"], self.jijel.pk, status)

    def test_the_route_survives_a_real_accepted_deal(self):
        offer = self.propose()
        accept_offer(pending_offer=offer, actor=self.traveler)
        data = self._detail()
        self.assertEqual(data["status"], ParcelRequest.Status.MATCHED)
        self.assertEqual(data["pickup_place"]["id"], self.paris.pk)
        self.assertEqual(data["delivery_place"]["id"], self.jijel.pk)

    def test_every_language_receives_the_same_canonical_route(self):
        routes = {
            language: (
                self._detail(language=language)["pickup_place"],
                self._detail(language=language)["delivery_place"],
            )
            for language in ("en", "fr", "ar")
        }
        self.assertEqual(routes["en"], routes["fr"])
        self.assertEqual(routes["en"], routes["ar"])

    def test_the_list_carries_the_same_route(self):
        response = client_for(self.sender).get(reverse("parcels-list"))
        self.assertEqual(response.status_code, 200)
        rows = (
            response.data["results"]
            if isinstance(response.data, dict)
            else response.data
        )
        row = next(row for row in rows if row["id"] == self.request.pk)
        self.assertEqual(row["pickup_place"]["id"], self.paris.pk)
        self.assertEqual(row["delivery_place"]["id"], self.jijel.pk)


# ---------------------------------------------------------------------------
# Cost
# ---------------------------------------------------------------------------


class FindTravelersCostTests(RouteMatchingFixture, TestCase):
    """The HTTP call itself, at one and at ten candidates: flat."""

    def _measure(self) -> tuple[int, int]:
        self.get()
        with CaptureQueriesContext(connection) as captured:
            response = self.get(limit=50)
        self.assertEqual(response.status_code, 200)
        return len(captured.captured_queries), response.data["page"]["total"]

    def test_find_travelers_query_count_does_not_grow_with_candidates(self):
        from apps.matching.tests.test_v1_matching import _approve_kyc, _user

        one, one_total = self._measure()
        self.assertEqual(one_total, 1)
        for index in range(9):
            traveler = _user(f"j7b-cost-{index}@example.com")
            _approve_kyc(traveler, f"j7bcost{index}x")
            self._journey(traveler, origin=self.cdg)
        ten, ten_total = self._measure()
        self.assertEqual(ten_total, 10)
        self.assertEqual(one, ten)
