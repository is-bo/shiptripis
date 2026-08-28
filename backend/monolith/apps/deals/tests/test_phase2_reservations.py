from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.core.models import BusinessSettingsVersion
from apps.deals.models import Deal, DealEvent, DealLegAllocation, DealTermsSnapshot
from apps.deals.services import release_expired_reservations
from apps.locations.models import Location
from apps.matching.models import Match, MatchEvent, Offer
from apps.parcels.models import DeliveryRequest, ParcelRequest
from apps.trips.models import Journey, JourneyLeg


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


class Phase2ReservationLifecycleTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.sender = _user("reservation-sender@example.com")
        self.traveler = _user("reservation-traveler@example.com")
        self.outsider = _user("reservation-outsider@example.com")
        self.origin = _location("Reservation origin", "36.752500", "3.041970")
        self.midpoint = _location("Reservation midpoint", "36.190000", "5.410000")
        self.destination = _location(
            "Reservation destination",
            "36.365000",
            "6.614700",
        )
        self.journey = Journey.objects.create(
            traveler=self.traveler,
            start_location=self.origin,
            destination_location=self.destination,
            status=Journey.Status.ACTIVE,
            published_at=self.now,
        )
        self.first_leg = JourneyLeg.objects.create(
            journey=self.journey,
            position=0,
            mode=JourneyLeg.Mode.DRIVE,
            origin=self.origin,
            destination=self.midpoint,
            depart_at=self.now + timedelta(days=1),
            arrive_at=self.now + timedelta(days=1, hours=2),
            capacity_kg=Decimal("10.00"),
            distance_meters=250_000,
        )
        self.second_leg = JourneyLeg.objects.create(
            journey=self.journey,
            position=1,
            mode=JourneyLeg.Mode.DRIVE,
            origin=self.midpoint,
            destination=self.destination,
            depart_at=self.now + timedelta(days=1, hours=3),
            arrive_at=self.now + timedelta(days=1, hours=5),
            capacity_kg=Decimal("10.00"),
            distance_meters=150_000,
        )
        self.settings_version = BusinessSettingsVersion.objects.get(version=2)
        self._sequence = 0

    def _delivery_request(self, *, status=ParcelRequest.Status.OPEN):
        self._sequence += 1
        return DeliveryRequest.objects.create(
            sender=self.sender,
            kind=ParcelRequest.Kind.DELIVERY,
            schema_version=2,
            pickup_location=self.origin,
            delivery_location=self.destination,
            ready_window_start=self.now + timedelta(hours=1),
            ready_window_end=self.now + timedelta(hours=2),
            deadline_at=self.now + timedelta(days=2),
            actual_weight_kg=Decimal("2.00"),
            length_cm=Decimal("10.00"),
            width_cm=Decimal("10.00"),
            height_cm=Decimal("10.00"),
            declared_value_eur_cents=10_000,
            traveler_reward_eur_cents=1_000,
            title=f"Reservation parcel {self._sequence}",
            description="Safe reservation lifecycle parcel",
            category=ParcelRequest.ItemType.DOCUMENTS,
            item_type=ParcelRequest.ItemType.DOCUMENTS,
            description_is_accurate=True,
            item_is_legal=True,
            no_prohibited_goods=True,
            declared_value_is_accurate=True,
            customs_responsibilities_understood=True,
            status=status,
        )

    def _accepted_aggregate(self, *, expires_at):
        delivery_request = self._delivery_request(
            status=ParcelRequest.Status.MATCHED
        )
        match = Match.objects.create(
            parcel=delivery_request,
            journey=self.journey,
            start_leg=self.first_leg,
            end_leg=self.second_leg,
            sender=self.sender,
            traveler=self.traveler,
            status=Match.Status.ACCEPTED,
            matching_version="v1-matching-1",
            matched_distance_meters=400_000,
            compatibility_snapshot={"compatible": True},
            ranking_snapshot={"score": 900},
        )
        offer = Offer.objects.create(
            match=match,
            proposed_by=Offer.ProposedBy.SENDER,
            proposer=self.sender,
            economics_version=Offer.EconomicsVersion.V1_EUR,
            currency=Offer.Currency.EUR,
            traveler_reward_minor=1_000,
            commission_rate_bps=2_500,
            platform_fee_minor=250,
            sender_total_minor=1_250,
            pricing_version=self.settings_version.pricing_version,
            business_settings_version=self.settings_version,
            terms_snapshot={"currency": "EUR"},
            status=Offer.Status.ACCEPTED,
            responded_at=self.now,
        )
        deal = Deal.objects.create(
            accepted_offer=offer,
            match=match,
            delivery_request=delivery_request,
            journey=self.journey,
            sender=self.sender,
            traveler=self.traveler,
            status=Deal.Status.PAYMENT_REQUIRED,
        )
        DealTermsSnapshot.objects.create(
            deal=deal,
            currency=DealTermsSnapshot.Currency.EUR,
            traveler_reward_minor=1_000,
            commission_rate_bps=2_500,
            platform_fee_minor=250,
            sender_total_minor=1_250,
            business_settings_version=self.settings_version,
            pricing_version=self.settings_version.pricing_version,
            policy_snapshot=self.settings_version.policy,
        )
        allocations = [
            DealLegAllocation.objects.create(
                deal=deal,
                journey_leg=leg,
                allocated_weight_kg=Decimal("2.000"),
                status=DealLegAllocation.Status.PENDING_PAYMENT,
                expires_at=expires_at,
            )
            for leg in (self.first_leg, self.second_leg)
        ]
        return delivery_request, match, offer, deal, allocations

    def _pending_match(self):
        delivery_request = self._delivery_request()
        match = Match.objects.create(
            parcel=delivery_request,
            journey=self.journey,
            start_leg=self.first_leg,
            end_leg=self.second_leg,
            sender=self.sender,
            traveler=self.traveler,
            status=Match.Status.PENDING,
            matching_version="v1-matching-1",
            matched_distance_meters=400_000,
        )
        offer = Offer.objects.create(
            match=match,
            proposed_by=Offer.ProposedBy.SENDER,
            proposer=self.sender,
            economics_version=Offer.EconomicsVersion.V1_EUR,
            currency=Offer.Currency.EUR,
            traveler_reward_minor=1_000,
            commission_rate_bps=2_500,
            platform_fee_minor=250,
            sender_total_minor=1_250,
            pricing_version=self.settings_version.pricing_version,
            business_settings_version=self.settings_version,
            terms_snapshot={"currency": "EUR"},
            status=Offer.Status.PENDING,
            expires_at=self.now + timedelta(hours=1),
        )
        return match, offer

    def test_expiry_sweep_releases_only_due_reservations_and_is_idempotent(self):
        expired = self._accepted_aggregate(expires_at=self.now - timedelta(seconds=1))
        future = self._accepted_aggregate(expires_at=self.now + timedelta(hours=1))

        results = release_expired_reservations(at=self.now)
        repeated = release_expired_reservations(at=self.now)

        assert [(result.deal_id, result.released_allocations, result.changed) for result in results] == [
            (expired[3].pk, 2, True)
        ]
        assert repeated == []
        expired[0].refresh_from_db()
        expired[1].refresh_from_db()
        expired[3].refresh_from_db()
        for allocation in expired[4]:
            allocation.refresh_from_db()
            assert allocation.status == DealLegAllocation.Status.RELEASED
            assert allocation.released_at == self.now
            assert allocation.release_reason == "payment_grace_expired"
        assert expired[0].status == ParcelRequest.Status.OPEN
        assert expired[1].status == Match.Status.EXPIRED
        assert expired[3].status == Deal.Status.EXPIRED
        assert list(expired[3].events.values_list("kind", flat=True)) == [
            DealEvent.Kind.CAPACITY_RELEASED,
            DealEvent.Kind.STATUS_CHANGED,
        ]
        capacity_event = expired[3].events.get(
            kind=DealEvent.Kind.CAPACITY_RELEASED
        )
        assert capacity_event.payload["reason"] == "payment_grace_expired"
        assert capacity_event.payload["allocation_ids"] == [
            allocation.pk for allocation in expired[4]
        ]

        future[0].refresh_from_db()
        future[1].refresh_from_db()
        future[3].refresh_from_db()
        assert future[0].status == ParcelRequest.Status.MATCHED
        assert future[1].status == Match.Status.ACCEPTED
        assert future[3].status == Deal.Status.PAYMENT_REQUIRED
        assert DealLegAllocation.objects.active(at=self.now).filter(
            deal=future[3]
        ).count() == 2

    def test_sweep_batch_slots_are_per_deal_not_per_allocation_expiry(self):
        first = self._accepted_aggregate(
            expires_at=self.now - timedelta(seconds=10)
        )
        first[4][1].expires_at = self.now - timedelta(seconds=5)
        first[4][1].save(update_fields=["expires_at"])
        second = self._accepted_aggregate(
            expires_at=self.now - timedelta(seconds=1)
        )

        results = release_expired_reservations(at=self.now, limit=2)

        assert [result.deal_id for result in results] == [
            first[3].pk,
            second[3].pk,
        ]
        assert [result.released_allocations for result in results] == [2, 2]
        assert all(result.changed for result in results)
        assert DealLegAllocation.objects.filter(
            deal__in=(first[3], second[3]),
            status=DealLegAllocation.Status.RELEASED,
        ).count() == 4

    def test_match_snapshots_are_immutable_while_status_transition_saves(self):
        _request_row, match, _offer, _deal, _allocations = (
            self._accepted_aggregate(expires_at=self.now + timedelta(hours=1))
        )
        match.status = Match.Status.IN_TRANSIT
        match.save(update_fields=["status", "updated_at"])
        match.refresh_from_db()
        assert match.status == Match.Status.IN_TRANSIT

        mutations = {
            "matching_version": "tampered-version",
            "matched_distance_meters": 1,
            "compatibility_snapshot": {"compatible": False},
            "ranking_snapshot": {"score": -1},
        }
        for field, value in mutations.items():
            candidate = Match.objects.get(pk=match.pk)
            setattr(candidate, field, value)
            with self.subTest(field=field), self.assertRaisesMessage(
                ValidationError,
                "Match compatibility snapshots are immutable.",
            ):
                candidate.save(update_fields=[field, "updated_at"])

        match.refresh_from_db()
        assert match.matching_version == "v1-matching-1"
        assert match.matched_distance_meters == 400_000
        assert match.compatibility_snapshot == {"compatible": True}
        assert match.ranking_snapshot == {"score": 900}

    def test_deal_cancel_is_party_only_reopens_request_and_is_idempotent(self):
        delivery_request, match, _offer, deal, allocations = (
            self._accepted_aggregate(expires_at=self.now + timedelta(hours=1))
        )

        unauthorized = _client(self.outsider).post(
            reverse("deals-cancel", args=[deal.pk]),
            format="json",
        )
        cancelled = _client(self.sender).post(
            reverse("deals-cancel", args=[deal.pk]),
            format="json",
        )
        repeated = _client(self.traveler).post(
            reverse("deals-cancel", args=[deal.pk]),
            format="json",
        )

        assert unauthorized.status_code == 404
        assert cancelled.status_code == 200, cancelled.data
        assert cancelled.data["changed"] is True
        assert cancelled.data["released_allocations"] == 2
        assert cancelled.data["deal"]["status"] == Deal.Status.CANCELLED
        assert repeated.status_code == 200, repeated.data
        assert repeated.data["changed"] is False
        assert repeated.data["released_allocations"] == 0

        delivery_request.refresh_from_db()
        match.refresh_from_db()
        deal.refresh_from_db()
        assert delivery_request.status == ParcelRequest.Status.OPEN
        assert match.status == Match.Status.CANCELLED
        assert deal.status == Deal.Status.CANCELLED
        for allocation in allocations:
            allocation.refresh_from_db()
            assert allocation.status == DealLegAllocation.Status.RELEASED
            assert allocation.release_reason == "deal_cancelled"
            assert allocation.released_at is not None
        assert deal.events.filter(kind=DealEvent.Kind.CAPACITY_RELEASED).count() == 1
        assert deal.events.filter(kind=DealEvent.Kind.STATUS_CHANGED).count() == 1

    def test_journey_cancel_releases_deal_and_expires_other_pending_match(self):
        delivery_request, accepted_match, accepted_offer, deal, allocations = (
            self._accepted_aggregate(expires_at=self.now + timedelta(hours=1))
        )
        pending_match, pending_offer = self._pending_match()

        unauthorized = _client(self.outsider).post(
            reverse("journeys-cancel", args=[self.journey.pk]),
            format="json",
        )
        cancelled = _client(self.traveler).post(
            reverse("journeys-cancel", args=[self.journey.pk]),
            format="json",
        )
        repeated = _client(self.traveler).post(
            reverse("journeys-cancel", args=[self.journey.pk]),
            format="json",
        )

        assert unauthorized.status_code == 403
        assert cancelled.status_code == 200, cancelled.data
        assert cancelled.data["changed"] is True
        assert cancelled.data["released_allocations"] == 2
        assert repeated.status_code == 200, repeated.data
        assert repeated.data["changed"] is False
        assert repeated.data["released_allocations"] == 0

        self.journey.refresh_from_db()
        delivery_request.refresh_from_db()
        accepted_match.refresh_from_db()
        accepted_offer.refresh_from_db()
        deal.refresh_from_db()
        pending_match.refresh_from_db()
        pending_offer.refresh_from_db()
        assert self.journey.status == Journey.Status.CANCELLED
        assert delivery_request.status == ParcelRequest.Status.OPEN
        assert accepted_match.status == Match.Status.CANCELLED
        assert accepted_offer.status == Offer.Status.ACCEPTED
        assert deal.status == Deal.Status.CANCELLED
        assert pending_match.status == Match.Status.CANCELLED
        assert pending_offer.status == Offer.Status.EXPIRED
        for allocation in allocations:
            allocation.refresh_from_db()
            assert allocation.status == DealLegAllocation.Status.RELEASED
            assert allocation.release_reason == "journey_cancelled"
        assert deal.events.filter(
            kind=DealEvent.Kind.CAPACITY_RELEASED,
            payload__reason="journey_cancelled",
        ).count() == 1
        match_event = pending_match.events.get(kind=MatchEvent.Kind.MATCH_CANCELLED)
        assert match_event.actor_id == self.traveler.pk
        assert match_event.payload == {"reason": "journey_cancelled"}

    def test_journey_cancel_rejects_funded_deal_without_changing_state(self):
        delivery_request, match, offer, deal, allocations = (
            self._accepted_aggregate(expires_at=self.now + timedelta(hours=1))
        )
        deal.status = Deal.Status.FUNDED
        deal.funded_at = self.now
        deal.save(update_fields=["status", "funded_at", "updated_at"])
        DealLegAllocation.objects.filter(deal=deal).update(
            status=DealLegAllocation.Status.FUNDED,
            expires_at=None,
        )

        response = _client(self.traveler).post(
            reverse("journeys-cancel", args=[self.journey.pk]),
            format="json",
        )

        assert response.status_code == 409, response.data
        self.journey.refresh_from_db()
        delivery_request.refresh_from_db()
        match.refresh_from_db()
        offer.refresh_from_db()
        deal.refresh_from_db()
        assert self.journey.status == Journey.Status.ACTIVE
        assert delivery_request.status == ParcelRequest.Status.MATCHED
        assert match.status == Match.Status.ACCEPTED
        assert offer.status == Offer.Status.ACCEPTED
        assert deal.status == Deal.Status.FUNDED
        assert deal.funded_at == self.now
        assert deal.events.count() == 0
        for allocation in allocations:
            allocation.refresh_from_db()
            assert allocation.status == DealLegAllocation.Status.FUNDED
            assert allocation.expires_at is None
            assert allocation.released_at is None
            assert allocation.release_reason == ""
