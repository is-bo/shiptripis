from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from importlib import import_module
from threading import Barrier, Event
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import (
    IntegrityError,
    OperationalError,
    close_old_connections,
    connection,
    connections,
    transaction,
)
from django.db.models import Sum
from django.test import TransactionTestCase, skipUnlessDBFeature
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import User
from apps.chat.models import ChatMessage
from apps.core.models import BusinessSettingsVersion
from apps.deals.models import Deal, DealLegAllocation, DealTermsSnapshot
from apps.kyc.models import KycSubmission
from apps.locations.models import Location
from apps.matching.models import Match, Offer
from apps.matching.v1_services import (
    CapacityExceeded,
    OfferStateError,
    accept_offer,
    counter_offer,
    create_sender_offer,
)
from apps.parcels.models import DeliveryRequest, ParcelRequest
from apps.payments.models import PaymentIntent
from apps.trips.models import Airport, Journey, JourneyLeg, JourneyLegProof
from apps.verification.models import HandoverCode
from apps.wallet.models import Hold


def _user(email: str) -> User:
    return User.objects.create_user(
        username=email,
        email=email,
        password="Sup3rStrongPass!",
        full_name=email.split("@")[0],
    )


def _client(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _approve_kyc(user: User, suffix: str) -> KycSubmission:
    return KycSubmission.objects.create(
        user=user,
        document_type=KycSubmission.DocumentType.PASSPORT,
        idempotency_key=f"{suffix:0<32}"[:32],
        front_image_key=f"kyc/{suffix}/front.jpg",
        status=KycSubmission.Status.APPROVED,
        reviewed_at=timezone.now(),
    )


def _ensure_business_settings() -> BusinessSettingsVersion:
    """Provision explicit test state after TransactionTestCase database flushes."""
    active = BusinessSettingsVersion.objects.filter(
        status=BusinessSettingsVersion.Status.ACTIVE
    ).first()
    if active is not None:
        return active
    # Re-seed the *current* revision. Acceptance now creates the Deal's balance
    # obligation in the same transaction, so it needs the Phase 3 payment
    # policy exactly as production has it; the Phase 2 policy alone would make
    # every acceptance fail closed.
    phase3_policy_document = import_module(
        "apps.core.migrations.0005_seed_phase3_payment_settings"
    ).PHASE3_POLICY
    return BusinessSettingsVersion.objects.create(
        version=3,
        status=BusinessSettingsVersion.Status.ACTIVE,
        canonical_currency="EUR",
        commission_rate_bps=2500,
        pricing_version="v1-payments-1",
        policy=deepcopy(phase3_policy_document),
        activated_at=timezone.now(),
    )


def _location(label: str, owner: User | None = None) -> Location:
    return Location.objects.create(
        kind=Location.Kind.MAP_POINT,
        normalized_label=f"exact {label}",
        public_label=label,
        private_label=f"Apartment 4, {label}",
        city=label,
        country_code="DZ",
        latitude=Decimal("36.752500"),
        longitude=Decimal("3.041970"),
        coarse_latitude=Decimal("36.750000"),
        coarse_longitude=Decimal("3.040000"),
        owner=owner,
        created_by=owner,
    )


class V1OfferDealTests(APITestCase):
    def setUp(self):
        _ensure_business_settings()
        self.sender = _user("v1-sender@example.com")
        self.traveler = _user("v1-traveler@example.com")
        self.other_traveler = _user("v1-other@example.com")
        self.kyc = _approve_kyc(self.traveler, "v1-traveler")
        self.pickup = _location("Algiers", self.sender)
        self.midpoint = _location("Setif")
        self.delivery = _location("Jijel", self.sender)
        depart = timezone.now() + timedelta(days=3)
        self.journey = Journey.objects.create(
            traveler=self.traveler,
            start_location=self.pickup,
            destination_location=self.delivery,
            status=Journey.Status.ACTIVE,
            published_at=timezone.now(),
        )
        self.first_leg = JourneyLeg.objects.create(
            journey=self.journey,
            position=0,
            mode=JourneyLeg.Mode.DRIVE,
            origin=self.pickup,
            destination=self.midpoint,
            depart_at=depart,
            arrive_at=depart + timedelta(hours=3),
            capacity_kg=Decimal("4.00"),
        )
        self.second_leg = JourneyLeg.objects.create(
            journey=self.journey,
            position=1,
            mode=JourneyLeg.Mode.DRIVE,
            origin=self.midpoint,
            destination=self.delivery,
            depart_at=depart + timedelta(hours=4),
            arrive_at=depart + timedelta(hours=7),
            capacity_kg=Decimal("4.00"),
        )
        self.request = self._delivery_request(Decimal("3.00"))

    def _delivery_request(self, weight: Decimal) -> DeliveryRequest:
        depart = self.first_leg.depart_at
        return DeliveryRequest.objects.create(
            sender=self.sender,
            kind=ParcelRequest.Kind.DELIVERY,
            schema_version=2,
            pickup_location=self.pickup,
            delivery_location=self.delivery,
            ready_window_start=depart - timedelta(hours=1),
            ready_window_end=depart + timedelta(hours=1),
            deadline_at=depart + timedelta(hours=8),
            actual_weight_kg=weight,
            length_cm=Decimal("20.00"),
            width_cm=Decimal("15.00"),
            height_cm=Decimal("10.00"),
            declared_value_eur_cents=10_000,
            traveler_reward_eur_cents=2_000,
            title="Documents",
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

    def _propose(self, delivery_request: DeliveryRequest | None = None):
        delivery_request = delivery_request or self.request
        return _client(self.sender).post(
            reverse("matches-propose-v1"),
            {
                "parcel_id": delivery_request.pk,
                "journey_id": self.journey.pk,
                "start_leg_id": self.first_leg.pk,
                "end_leg_id": self.second_leg.pk,
                "traveler_reward_eur_cents": 2_000,
            },
            format="json",
        )

    def test_sender_proposes_first_with_frozen_eur_terms(self):
        response = self._propose()

        assert response.status_code == 201, response.data
        offer = Offer.objects.get(pk=response.data["id"])
        assert offer.proposed_by == Offer.ProposedBy.SENDER
        assert offer.currency == Offer.Currency.EUR
        assert offer.economics_version == Offer.EconomicsVersion.V1_EUR
        assert offer.traveler_reward_minor == 2_000
        assert offer.platform_fee_minor == 500
        assert offer.sender_total_minor == 2_500
        assert offer.base_amount_dzd == offer.total_dzd == 0
        # The active revision advances with each phase; assert the offer froze
        # whichever one was active, not a hard-coded number.
        assert (
            offer.business_settings_version
            == BusinessSettingsVersion.objects.get(status="active")
        )
        assert offer.match.trip_id is None
        assert offer.match.start_leg_id == self.first_leg.pk
        assert offer.match.end_leg_id == self.second_leg.pk

        offer.sender_total_minor += 1
        with self.assertRaises(ValidationError):
            offer.save()

        with self.assertRaises(IntegrityError), transaction.atomic():
            Offer.objects.filter(pk=offer.pk).update(total_dzd=1)

        with CaptureQueriesContext(connection) as queries:
            match_list = _client(self.sender).get(reverse("matches-list"))
        assert match_list.status_code == 200
        assert match_list.data[0]["parcel"]["actual_weight_kg"] == "3.00"
        assert len(queries) <= 4

    def test_offer_economics_version_has_no_legacy_creation_default(self):
        """A new Offer has to state its economics; there is no legacy fallback.

        `LEGACY_DZD` used to be the field default, so any code path that forgot
        to set `economics_version` silently produced a legacy DZD offer. The
        field now has no default at all, which makes that mistake a database
        error rather than a wrong price.
        """

        field = Offer._meta.get_field("economics_version")
        assert field.has_default() is False

        offer = Offer.objects.get(pk=self._propose().data["id"])
        assert offer.economics_version == Offer.EconomicsVersion.V1_EUR
        assert offer.currency == Offer.Currency.EUR

    def test_decline_withdraw_and_match_cancel_follow_sender_first_rules(self):
        proposal = self._propose()
        offer_id = proposal.data["id"]

        own_decline = _client(self.sender).post(
            reverse("offers-decline", args=[offer_id]), format="json"
        )
        outsider_decline = _client(self.other_traveler).post(
            reverse("offers-decline", args=[offer_id]), format="json"
        )
        declined = _client(self.traveler).post(
            reverse("offers-decline", args=[offer_id]), format="json"
        )

        assert own_decline.status_code == 403
        assert outsider_decline.status_code == 403
        assert declined.status_code == 200
        assert declined.data["status"] == Offer.Status.DECLINED
        # Decline and withdraw are one user-visible outcome, so both terminate
        # the Match as CANCELLED; EXPIRED stays reserved for system endings.
        assert (
            Match.objects.get(pk=proposal.data["match"]).status
            == Match.Status.CANCELLED
        )
        assert declined.data["allowed_actions"] == []
        assert declined.data["awaiting_party"] is None

        replacement = self._propose()
        traveler_withdraw = _client(self.traveler).post(
            reverse("offers-withdraw", args=[replacement.data["id"]]), format="json"
        )
        withdrawn = _client(self.sender).post(
            reverse("offers-withdraw", args=[replacement.data["id"]]), format="json"
        )
        assert traveler_withdraw.status_code == 403
        assert withdrawn.status_code == 200
        assert withdrawn.data["status"] == Offer.Status.WITHDRAWN
        assert (
            Match.objects.get(pk=replacement.data["match"]).status
            == Match.Status.CANCELLED
        )

        third = self._propose()
        cancelled = _client(self.traveler).post(
            reverse("matches-cancel", args=[third.data["match"]]), format="json"
        )
        assert cancelled.status_code == 200
        assert cancelled.data["status"] == Match.Status.CANCELLED
        assert Offer.objects.get(pk=third.data["id"]).status == Offer.Status.WITHDRAWN

    def test_counter_then_accept_creates_deal_terms_and_segment_allocations(self):
        proposal = self._propose()
        counter = _client(self.traveler).post(
            reverse("offers-counter-v1", args=[proposal.data["id"]]),
            {"traveler_reward_eur_cents": 2_400},
            format="json",
        )
        assert counter.status_code == 201, counter.data

        accepted = _client(self.sender).post(
            reverse("offers-accept", args=[counter.data["id"]]), format="json"
        )

        assert accepted.status_code == 201, accepted.data
        deal = Deal.objects.select_related("terms").get(pk=accepted.data["id"])
        assert deal.status == Deal.Status.PAYMENT_REQUIRED
        assert deal.terms.currency == DealTermsSnapshot.Currency.EUR
        assert deal.terms.traveler_reward_minor == 2_400
        assert deal.terms.platform_fee_minor == 600
        assert deal.terms.sender_total_minor == 3_000
        assert list(
            deal.leg_allocations.order_by("journey_leg__position").values_list(
                "allocated_weight_kg", flat=True
            )
        ) == [Decimal("3.000"), Decimal("3.000")]

        with CaptureQueriesContext(connection) as queries:
            deal_list = _client(self.sender).get(reverse("deals-list"))
        assert deal_list.status_code == 200
        assert (
            deal_list.data["results"][0]["terms"]["business_settings_version"]
            == BusinessSettingsVersion.objects.get(status="active").version
        )
        assert len(queries) <= 4
        self.request.refresh_from_db()
        assert self.request.status == ParcelRequest.Status.MATCHED

        repeated = _client(self.sender).post(
            reverse("offers-accept", args=[counter.data["id"]]), format="json"
        )
        assert repeated.status_code == 200
        assert repeated.data["id"] == deal.pk

        outsider = _client(self.other_traveler).post(
            reverse("offers-accept", args=[counter.data["id"]]), format="json"
        )
        assert outsider.status_code == 403
        assert "id" not in outsider.data

    def test_v1_deal_requires_funding_before_chat_and_cannot_enter_legacy_payment_or_handover(self):
        proposal = self._propose()
        accepted = _client(self.traveler).post(
            reverse("offers-accept", args=[proposal.data["id"]]), format="json"
        )
        assert accepted.status_code == 201
        offer = Offer.objects.select_related("match").get(pk=proposal.data["id"])

        payment = _client(self.sender).post(
            reverse("payments-create"),
            {"offer_id": offer.pk, "currency": "EUR"},
            format="json",
        )
        handover = _client(self.sender).post(
            reverse("handover-issue", args=[offer.match_id]),
            {"kind": HandoverCode.Kind.PICKUP},
            format="json",
        )
        chat = _client(self.sender).post(
            reverse("chat-messages", args=[offer.match_id]),
            {"body": "unsafe legacy chat"},
            format="json",
        )

        assert payment.status_code == 409
        assert payment.data["code"] == "v1_deal_payment_not_available"
        assert handover.status_code == 409
        assert chat.status_code == 402
        assert chat.data == {
            "reason": "payment_pending",
            "match_id": offer.match_id,
        }
        deal = Deal.objects.get(match_id=offer.match_id)
        assert deal.status == Deal.Status.PAYMENT_REQUIRED
        assert deal.funded_at is None
        assert ChatMessage.objects.count() == 0
        assert PaymentIntent.objects.count() == 0
        assert HandoverCode.objects.count() == 0
        assert Hold.objects.count() == 0
        offer.match.refresh_from_db()
        assert offer.match.status == Match.Status.ACCEPTED

    def test_accepted_deal_blocks_direct_request_cancellation(self):
        proposal = self._propose()
        accepted = _client(self.traveler).post(
            reverse("offers-accept", args=[proposal.data["id"]]), format="json"
        )
        assert accepted.status_code == 201

        cancelled = _client(self.sender).post(
            reverse("parcels-cancel", args=[self.request.pk]), format="json"
        )

        assert cancelled.status_code == 409
        assert cancelled.data["code"] == "deal_cancellation_not_available"
        assert (
            DealLegAllocation.objects.filter(
                deal_id=accepted.data["id"],
                status=DealLegAllocation.Status.PENDING_PAYMENT,
            ).count()
            == 2
        )

    def test_targeted_request_rejects_a_different_traveler(self):
        self.request.target_traveler = self.other_traveler
        self.request.save(update_fields=["target_traveler", "updated_at"])

        response = self._propose()

        assert response.status_code == 403
        assert Offer.objects.count() == 0

    def test_reward_has_an_explicit_upper_bound(self):
        response = _client(self.sender).post(
            reverse("matches-propose-v1"),
            {
                "parcel_id": self.request.pk,
                "journey_id": self.journey.pk,
                "start_leg_id": self.first_leg.pk,
                "end_leg_id": self.second_leg.pk,
                "traveler_reward_eur_cents": 100_000_001,
            },
            format="json",
        )

        assert response.status_code == 400
        assert "traveler_reward_eur_cents" in response.data
        assert Offer.objects.count() == 0

    def test_accept_rechecks_current_kyc(self):
        proposal = self._propose()
        self.kyc.status = KycSubmission.Status.EXPIRED
        self.kyc.save(update_fields=["status", "updated_at"])

        accepted = _client(self.traveler).post(
            reverse("offers-accept", args=[proposal.data["id"]]), format="json"
        )

        assert accepted.status_code == 409
        assert Deal.objects.count() == 0

    def test_accept_rejects_segment_overbooking_without_partial_state(self):
        first_offer = self._propose()
        second_request = self._delivery_request(Decimal("2.00"))
        second_offer = self._propose(second_request)
        first_accept = _client(self.traveler).post(
            reverse("offers-accept", args=[first_offer.data["id"]]), format="json"
        )
        assert first_accept.status_code == 201

        rejected = _client(self.traveler).post(
            reverse("offers-accept", args=[second_offer.data["id"]]), format="json"
        )

        assert rejected.status_code == 409
        assert rejected.data["code"] == "capacity_exceeded"
        assert Deal.objects.count() == 1
        assert DealLegAllocation.objects.count() == 2
        second_request.refresh_from_db()
        assert second_request.status == ParcelRequest.Status.OPEN
        assert (
            Offer.objects.get(pk=second_offer.data["id"]).status == Offer.Status.PENDING
        )

    def test_legacy_matching_write_routes_are_gone(self):
        client = _client(self.sender)
        assert (
            client.post(reverse("matches-apply"), {}, format="json").status_code == 410
        )
        assert (
            client.post(reverse("matches-apply-to-trip"), {}, format="json").status_code
            == 410
        )

    def test_exact_locations_reveal_to_traveler_only_after_funding(self):
        proposal = self._propose()
        accepted = _client(self.traveler).post(
            reverse("offers-accept", args=[proposal.data["id"]]), format="json"
        )
        deal = Deal.objects.get(pk=accepted.data["id"])

        before = _client(self.traveler).get(
            reverse("parcels-detail", args=[self.request.pk])
        )
        assert "private_label" not in before.data["pickup_location"]
        assert "latitude" not in before.data["pickup_location"]

        deal.funded_at = timezone.now()
        deal.status = Deal.Status.FUNDED
        deal.save(update_fields=["funded_at", "status", "updated_at"])
        after = _client(self.traveler).get(
            reverse("parcels-detail", args=[self.request.pk])
        )
        assert after.data["pickup_location"]["private_label"] == "Apartment 4, Algiers"
        assert "latitude" in after.data["pickup_location"]

    def test_terms_and_business_inputs_are_immutable(self):
        proposal = self._propose()
        accepted = _client(self.traveler).post(
            reverse("offers-accept", args=[proposal.data["id"]]), format="json"
        )
        terms = DealTermsSnapshot.objects.get(deal_id=accepted.data["id"])
        terms.sender_total_minor += 1
        with self.assertRaises(ValidationError):
            terms.save()

        with self.assertRaises(IntegrityError), transaction.atomic():
            DealTermsSnapshot.objects.filter(pk=terms.pk).update(
                business_settings_version=None
            )

        settings_version = BusinessSettingsVersion.objects.get(version=2)
        settings_version.commission_rate_bps = 1200
        with self.assertRaises(ValidationError):
            settings_version.save()


@skipUnlessDBFeature("has_select_for_update")
class V1CapacityConcurrencyTests(TransactionTestCase):
    """Exercise the real row-lock boundary; skipped by the SQLite fast suite."""

    reset_sequences = True

    def setUp(self):
        _ensure_business_settings()
        self.sender = _user("race-sender@example.com")
        self.traveler = _user("race-traveler@example.com")
        self.kyc = _approve_kyc(self.traveler, "race-traveler")
        origin = self.origin = _location("Race Origin", self.sender)
        destination = self.destination = _location("Race Destination", self.sender)
        now = timezone.now()
        journey = self.journey = Journey.objects.create(
            traveler=self.traveler,
            start_location=origin,
            destination_location=destination,
            status=Journey.Status.ACTIVE,
            published_at=now,
        )
        leg = self.leg = JourneyLeg.objects.create(
            journey=journey,
            position=0,
            mode=JourneyLeg.Mode.DRIVE,
            origin=origin,
            destination=destination,
            depart_at=now + timedelta(days=2),
            arrive_at=now + timedelta(days=2, hours=3),
            capacity_kg=Decimal("4.00"),
        )
        offers = []
        for index in range(2):
            delivery_request = DeliveryRequest.objects.create(
                sender=self.sender,
                kind=ParcelRequest.Kind.DELIVERY,
                schema_version=2,
                pickup_location=origin,
                delivery_location=destination,
                ready_window_start=now + timedelta(days=2, hours=-1),
                ready_window_end=now + timedelta(days=2, hours=1),
                deadline_at=now + timedelta(days=2, hours=4),
                actual_weight_kg=Decimal("3.00"),
                length_cm=Decimal("20.00"),
                width_cm=Decimal("15.00"),
                height_cm=Decimal("10.00"),
                declared_value_eur_cents=1_000,
                traveler_reward_eur_cents=2_000,
                title=f"Race parcel {index}",
                description="Concurrency test",
                category=ParcelRequest.ItemType.OTHER,
                item_type=ParcelRequest.ItemType.OTHER,
                description_is_accurate=True,
                item_is_legal=True,
                no_prohibited_goods=True,
                declared_value_is_accurate=True,
                customs_responsibilities_understood=True,
            )
            offers.append(
                create_sender_offer(
                    sender=self.sender,
                    delivery_request=delivery_request,
                    journey=journey,
                    start_leg_id=leg.pk,
                    end_leg_id=leg.pk,
                    traveler_reward_eur_cents=2_000,
                ).pk
            )
        self.offer_ids = offers

    def _assert_acceptance_blocks_eligibility_update(self, update_callback) -> None:
        deal_save_reached = Event()
        allow_deal_save = Event()
        original_save = Deal.save

        def paused_deal_save(instance, *args, **kwargs):
            if instance._state.adding:
                deal_save_reached.set()
                if not allow_deal_save.wait(timeout=10):
                    raise AssertionError("Timed out while holding acceptance locks.")
            return original_save(instance, *args, **kwargs)

        def accept_first_offer():
            close_old_connections()
            try:
                return accept_offer(
                    pending_offer=Offer.objects.get(pk=self.offer_ids[0]),
                    actor=User.objects.get(pk=self.traveler.pk),
                )
            finally:
                connections.close_all()

        def attempt_update():
            close_old_connections()
            try:
                with transaction.atomic():
                    with connections["default"].cursor() as cursor:
                        cursor.execute("SET LOCAL lock_timeout = '750ms'")
                    update_callback()
                return "updated"
            except OperationalError:
                return "blocked"
            finally:
                connections.close_all()

        with patch.object(Deal, "save", paused_deal_save):
            with ThreadPoolExecutor(max_workers=2) as executor:
                acceptance = executor.submit(accept_first_offer)
                self.assertTrue(
                    deal_save_reached.wait(timeout=10),
                    "Acceptance never reached Deal creation.",
                )
                revocation = executor.submit(attempt_update)
                update_result = revocation.result(timeout=5)
                allow_deal_save.set()
                accepted = acceptance.result(timeout=10)

        self.assertEqual(update_result, "blocked")
        self.assertTrue(accepted.created)
        self.assertEqual(Deal.objects.count(), 1)

    def test_acceptance_holds_kyc_witness_until_deal_commit(self):
        self._assert_acceptance_blocks_eligibility_update(
            lambda: KycSubmission.objects.filter(pk=self.kyc.pk).update(
                status=KycSubmission.Status.EXPIRED
            )
        )

    def test_acceptance_holds_flight_proof_witness_until_deal_commit(self):
        origin_airport = Airport.objects.create(
            iata="RCO", city="Race Origin", name="Race Origin", country="DZ"
        )
        destination_airport = Airport.objects.create(
            iata="RCD",
            city="Race Destination",
            name="Race Destination",
            country="DZ",
        )
        for location, airport in (
            (self.origin, origin_airport),
            (self.destination, destination_airport),
        ):
            Location.objects.filter(pk=location.pk).update(
                kind=Location.Kind.AIRPORT,
                airport=airport,
                coordinates_trusted=True,
                coordinate_dataset_version="phase2-concurrency-fixture-v1",
            )
        JourneyLeg.objects.filter(pk=self.leg.pk).update(
            mode=JourneyLeg.Mode.FLIGHT,
            flight_number="ST100",
        )
        proof = JourneyLegProof.objects.create(
            leg=self.leg,
            bucket="private-proofs",
            object_key="flight/concurrency-proof.jpg",
            status=JourneyLegProof.Status.APPROVED,
            reviewer=self.sender,
            reviewed_at=timezone.now(),
        )

        self._assert_acceptance_blocks_eligibility_update(
            lambda: JourneyLegProof.objects.filter(pk=proof.pk).update(
                status=JourneyLegProof.Status.REJECTED,
                rejection_reason="Approval revoked after re-review",
            )
        )

    def _accept_after_barrier(self, offer_id: int, barrier: Barrier) -> str:
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            accept_offer(
                pending_offer=Offer.objects.get(pk=offer_id),
                actor=User.objects.get(pk=self.traveler.pk),
            )
            return "accepted"
        except CapacityExceeded:
            return "capacity_exceeded"
        finally:
            connections.close_all()

    def test_concurrent_acceptance_cannot_overbook_one_leg(self):
        barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    lambda offer_id: self._accept_after_barrier(offer_id, barrier),
                    self.offer_ids,
                )
            )

        assert sorted(results) == ["accepted", "capacity_exceeded"]
        assert Deal.objects.count() == 1
        assert DealLegAllocation.objects.aggregate(total=Sum("allocated_weight_kg"))[
            "total"
        ] == Decimal("3.000")


@skipUnlessDBFeature("has_select_for_update")
class V1NegotiationConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        _ensure_business_settings()
        self.sender = _user("negotiation-sender@example.com")
        self.travelers = [
            _user("negotiation-a@example.com"),
            _user("negotiation-b@example.com"),
        ]
        for index, traveler in enumerate(self.travelers):
            _approve_kyc(traveler, f"negotiation-{index}")
        self.origin = _location("Negotiation Origin", self.sender)
        self.destination = _location("Negotiation Destination", self.sender)
        now = timezone.now()
        self.request = DeliveryRequest.objects.create(
            sender=self.sender,
            kind=ParcelRequest.Kind.DELIVERY,
            schema_version=2,
            pickup_location=self.origin,
            delivery_location=self.destination,
            ready_window_start=now + timedelta(hours=23),
            ready_window_end=now + timedelta(days=1, hours=2),
            deadline_at=now + timedelta(days=2),
            actual_weight_kg=Decimal("2.00"),
            length_cm=Decimal("20.00"),
            width_cm=Decimal("15.00"),
            height_cm=Decimal("10.00"),
            declared_value_eur_cents=1_000,
            traveler_reward_eur_cents=2_000,
            title="Concurrent request",
            description="Concurrency test",
            category=ParcelRequest.ItemType.OTHER,
            item_type=ParcelRequest.ItemType.OTHER,
            description_is_accurate=True,
            item_is_legal=True,
            no_prohibited_goods=True,
            declared_value_is_accurate=True,
            customs_responsibilities_understood=True,
        )
        self.offers = []
        for index, traveler in enumerate(self.travelers):
            journey = Journey.objects.create(
                traveler=traveler,
                start_location=self.origin,
                destination_location=self.destination,
                status=Journey.Status.ACTIVE,
                published_at=now,
            )
            leg = JourneyLeg.objects.create(
                journey=journey,
                position=0,
                mode=JourneyLeg.Mode.DRIVE,
                origin=self.origin,
                destination=self.destination,
                depart_at=now + timedelta(days=1, hours=index),
                arrive_at=now + timedelta(days=1, hours=index + 2),
                capacity_kg=Decimal("5.00"),
            )
            self.offers.append(
                create_sender_offer(
                    sender=self.sender,
                    delivery_request=self.request,
                    journey=journey,
                    start_leg_id=leg.pk,
                    end_leg_id=leg.pk,
                    traveler_reward_eur_cents=2_000,
                ).pk
            )

    def _accept(self, pair: tuple[int, int], barrier: Barrier) -> str:
        offer_id, traveler_id = pair
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            accept_offer(
                pending_offer=Offer.objects.get(pk=offer_id),
                actor=User.objects.get(pk=traveler_id),
            )
            return "accepted"
        except OfferStateError:
            return "conflict"
        finally:
            connections.close_all()

    def test_competing_matches_for_one_request_serialize_without_deadlock(self):
        barrier = Barrier(2)
        pairs = [
            (offer_id, traveler.pk)
            for offer_id, traveler in zip(self.offers, self.travelers, strict=True)
        ]
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(lambda pair: self._accept(pair, barrier), pairs)
            )

        assert sorted(results) == ["accepted", "conflict"]
        assert Deal.objects.count() == 1
        assert DealLegAllocation.objects.count() == 1

    def _accept_or_counter(self, action: str, offer_id: int, barrier: Barrier) -> str:
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            actor = User.objects.get(pk=self.travelers[0].pk)
            offer = Offer.objects.get(pk=offer_id)
            if action == "accept":
                accept_offer(pending_offer=offer, actor=actor)
            else:
                counter_offer(
                    pending_offer=offer,
                    actor=actor,
                    traveler_reward_eur_cents=2_400,
                )
            return action
        except OfferStateError:
            return "conflict"
        finally:
            connections.close_all()

    def test_accept_and_counter_share_one_lock_order(self):
        barrier = Barrier(2)
        offer_id = self.offers[0]
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    lambda action: self._accept_or_counter(action, offer_id, barrier),
                    ("accept", "counter"),
                )
            )

        # One side must lose, and the winner determines the whole terminal
        # state. Asserting `Deal.objects.count() in {0, 1}` instead would pass
        # no matter what the code did, which is not a concurrency test.
        assert results.count("conflict") == 1
        winner = next(result for result in results if result != "conflict")
        match_id = Offer.objects.get(pk=offer_id).match_id
        offers_on_match = Offer.objects.filter(match_id=match_id).count()
        if winner == "accept":
            assert Deal.objects.count() == 1
            assert offers_on_match == 1
        else:
            assert winner == "counter"
            assert Deal.objects.count() == 0
            assert offers_on_match == 2
