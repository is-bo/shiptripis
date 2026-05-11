"""Tests for apps.matching — Match + Offer chain.

Covers:
- traveler apply creates Match + first Offer with frozen pricing
- corridor mismatch / non-open parcel / wrong actor rejected
- counter chain: counter creates child, parents go to `countered`
- accept locks pricing + transitions Match + Parcel
- decline + withdraw + cancel state transitions
- only one accepted/pending per match (DB constraint)
- frozen pricing matches `apps.core.pricing` for delivery + product
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import User
from apps.matching.models import Match, Offer
from apps.parcels.models import DeliveryRequest, ParcelRequest, ProductRequest
from apps.trips.models import Trip


def _user(email: str, suffix: str = "1") -> User:
    return User.objects.create_user(
        username=email,
        email=email,
        password="Sup3rStrongPass!",
        full_name=f"User {suffix}",
        phone=f"+21355500022{suffix}",
        wilaya="16",
    )


def _client(user: User) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def _make_delivery(sender: User, **kw) -> DeliveryRequest:
    return DeliveryRequest.objects.create(
        sender=sender,
        kind=ParcelRequest.Kind.DELIVERY,
        origin_id="ALG",
        destination_id="CDG",
        weight_kg=2,
        item_type=ParcelRequest.ItemType.DOCUMENTS,
        description="docs",
        base_amount_dzd=4000,
        **kw,
    )


def _make_product(sender: User, **kw) -> ProductRequest:
    return ProductRequest.objects.create(
        sender=sender,
        kind=ParcelRequest.Kind.PRODUCT,
        origin_id="CDG",
        destination_id="ALG",
        weight_kg=1,
        item_type=ParcelRequest.ItemType.ELECTRONICS,
        product_price_dzd=40000,
        store_name="Fnac",
        product_url="https://fnac.fr/x",
        **kw,
    )


def _make_trip(traveler: User, *, origin="ALG", destination="CDG", **kw) -> Trip:
    return Trip.objects.create(
        traveler=traveler,
        origin_id=origin,
        destination_id=destination,
        departure_at=timezone.now() + timedelta(days=2),
        capacity_kg=20,
        status=Trip.Status.ACTIVE,
        **kw,
    )


class TravelerApplyTests(APITestCase):
    def setUp(self):
        self.sender = _user("sender@example.com", "1")
        self.traveler = _user("traveler@example.com", "2")
        self.parcel = _make_delivery(self.sender)
        self.trip = _make_trip(self.traveler)

    @patch("apps.matching.views.redis_bus.publish_after_commit")
    def test_traveler_apply_creates_match_and_first_offer(self, pub):
        c = _client(self.traveler)
        r = c.post(
            reverse("matches-apply"),
            {"parcel_id": self.parcel.id, "trip_id": self.trip.id},
            format="json",
        )
        assert r.status_code == 201, r.data
        assert r.data["status"] == "pending"
        assert r.data["sender_id"] == self.sender.id
        assert r.data["traveler_id"] == self.traveler.id

        match = Match.objects.get(pk=r.data["id"])
        offer = match.offers.get()
        assert offer.proposed_by == "traveler"
        assert offer.proposer_id == self.traveler.id
        # delivery quote: 4000 base, 25% commission, total=5000
        assert offer.base_amount_dzd == 4000
        assert offer.commission_dzd == 1000
        assert offer.total_dzd == 5000
        assert offer.base_fee_dzd == 0

        # publishes match.created + offer.created
        channels_called = [args.args[0] for args in pub.call_args_list]
        assert "match.created" in channels_called
        assert "offer.created" in channels_called

    def test_traveler_apply_with_custom_amount(self):
        c = _client(self.traveler)
        r = c.post(
            reverse("matches-apply"),
            {
                "parcel_id": self.parcel.id,
                "trip_id": self.trip.id,
                "base_amount_dzd": 6000,
            },
            format="json",
        )
        assert r.status_code == 201, r.data
        offer = Match.objects.get(pk=r.data["id"]).offers.get()
        assert offer.base_amount_dzd == 6000
        assert offer.commission_dzd == 1500  # 25% of 6000
        assert offer.total_dzd == 7500

    def test_product_apply_uses_product_pricing(self):
        product = _make_product(self.sender)
        trip2 = _make_trip(self.traveler, origin="CDG", destination="ALG")
        c = _client(self.traveler)
        r = c.post(
            reverse("matches-apply"),
            {"parcel_id": product.id, "trip_id": trip2.id},
            format="json",
        )
        assert r.status_code == 201, r.data
        offer = Match.objects.get(pk=r.data["id"]).offers.get()
        # 40000 product → tier 30k-55k → 7%, base_fee 2500
        # total = 40000 + 2500 + 2800 = 45300
        assert offer.base_amount_dzd == 40000
        assert offer.base_fee_dzd == 2500
        assert offer.commission_dzd == 2800
        assert offer.total_dzd == 45300

    def test_corridor_mismatch_rejected(self):
        # parcel ALG→CDG, trip CDG→ALG
        bad_trip = _make_trip(self.traveler, origin="CDG", destination="ALG")
        c = _client(self.traveler)
        r = c.post(
            reverse("matches-apply"),
            {"parcel_id": self.parcel.id, "trip_id": bad_trip.id},
            format="json",
        )
        assert r.status_code == 400

    def test_apply_to_own_parcel_rejected(self):
        own = _make_delivery(self.traveler)
        my_trip = _make_trip(self.traveler)
        c = _client(self.traveler)
        r = c.post(
            reverse("matches-apply"),
            {"parcel_id": own.id, "trip_id": my_trip.id},
            format="json",
        )
        assert r.status_code == 400

    def test_apply_with_other_users_trip_rejected(self):
        intruder = _user("intruder@example.com", "3")
        c = _client(intruder)
        r = c.post(
            reverse("matches-apply"),
            {"parcel_id": self.parcel.id, "trip_id": self.trip.id},
            format="json",
        )
        assert r.status_code == 403

    def test_duplicate_pending_rejected(self):
        c = _client(self.traveler)
        r1 = c.post(
            reverse("matches-apply"),
            {"parcel_id": self.parcel.id, "trip_id": self.trip.id},
            format="json",
        )
        assert r1.status_code == 201
        r2 = c.post(
            reverse("matches-apply"),
            {"parcel_id": self.parcel.id, "trip_id": self.trip.id},
            format="json",
        )
        assert r2.status_code == 409


class CounterAcceptTests(APITestCase):
    """Counter chain + accept transitions."""

    def setUp(self):
        self.sender = _user("sender2@example.com", "4")
        self.traveler = _user("traveler2@example.com", "5")
        self.parcel = _make_delivery(self.sender)
        self.trip = _make_trip(self.traveler)
        # Traveler applies (first offer).
        self.match = Match.objects.create(
            parcel=self.parcel,
            trip=self.trip,
            sender=self.sender,
            traveler=self.traveler,
            status=Match.Status.PENDING,
        )
        self.first = Offer.objects.create(
            match=self.match,
            proposed_by=Offer.ProposedBy.TRAVELER,
            proposer=self.traveler,
            base_amount_dzd=4000,
            commission_dzd=1000,
            total_dzd=5000,
        )

    def test_sender_counters_first_offer(self):
        c = _client(self.sender)
        r = c.post(
            reverse("matches-offers-counter", args=[self.match.id]),
            {"base_amount_dzd": 3500},
            format="json",
        )
        assert r.status_code == 201, r.data
        # parent went to countered, child is pending
        self.first.refresh_from_db()
        assert self.first.status == "countered"
        child = self.match.offers.exclude(pk=self.first.pk).get()
        assert child.proposed_by == "sender"
        assert child.parent_offer_id == self.first.id
        assert child.base_amount_dzd == 3500
        assert child.commission_dzd == 875
        assert child.total_dzd == 4375

    def test_proposer_cannot_counter_own_offer(self):
        c = _client(self.traveler)
        r = c.post(
            reverse("matches-offers-counter", args=[self.match.id]),
            {"base_amount_dzd": 3500},
            format="json",
        )
        assert r.status_code == 403

    def test_sender_accepts_offer_locks_match_and_parcel(self):
        c = _client(self.sender)
        r = c.post(reverse("offers-accept", args=[self.first.id]), format="json")
        assert r.status_code == 200, r.data
        self.first.refresh_from_db()
        self.match.refresh_from_db()
        self.parcel.refresh_from_db()
        assert self.first.status == "accepted"
        assert self.match.status == "accepted"
        assert self.parcel.status == "matched"
        assert self.first.responded_at is not None

    def test_proposer_cannot_accept_own_offer(self):
        c = _client(self.traveler)
        r = c.post(reverse("offers-accept", args=[self.first.id]), format="json")
        assert r.status_code == 403

    def test_decline_keeps_match_pending(self):
        c = _client(self.sender)
        r = c.post(reverse("offers-decline", args=[self.first.id]), format="json")
        assert r.status_code == 200
        self.first.refresh_from_db()
        self.match.refresh_from_db()
        assert self.first.status == "declined"
        assert self.match.status == "pending"

    def test_proposer_withdraws_own_offer(self):
        c = _client(self.traveler)
        r = c.post(reverse("offers-withdraw", args=[self.first.id]), format="json")
        assert r.status_code == 200
        self.first.refresh_from_db()
        assert self.first.status == "withdrawn"

    def test_non_proposer_cannot_withdraw(self):
        c = _client(self.sender)
        r = c.post(reverse("offers-withdraw", args=[self.first.id]), format="json")
        assert r.status_code == 403


class MatchCancelTests(APITestCase):
    def setUp(self):
        self.sender = _user("sender3@example.com", "6")
        self.traveler = _user("traveler3@example.com", "7")
        parcel = _make_delivery(self.sender)
        trip = _make_trip(self.traveler)
        self.match = Match.objects.create(
            parcel=parcel,
            trip=trip,
            sender=self.sender,
            traveler=self.traveler,
            status=Match.Status.PENDING,
        )
        self.offer = Offer.objects.create(
            match=self.match,
            proposed_by=Offer.ProposedBy.TRAVELER,
            proposer=self.traveler,
            base_amount_dzd=4000,
            commission_dzd=1000,
            total_dzd=5000,
        )

    def test_either_party_can_cancel_pending(self):
        c = _client(self.sender)
        r = c.post(reverse("matches-cancel", args=[self.match.id]), format="json")
        assert r.status_code == 200
        self.match.refresh_from_db()
        self.offer.refresh_from_db()
        assert self.match.status == "cancelled"
        assert self.offer.status == "withdrawn"

    def test_non_party_cannot_cancel(self):
        intruder = _user("intruder2@example.com", "8")
        c = _client(intruder)
        r = c.post(reverse("matches-cancel", args=[self.match.id]), format="json")
        assert r.status_code == 403

    def test_cannot_cancel_accepted_match(self):
        self.match.status = Match.Status.ACCEPTED
        self.match.save()
        c = _client(self.sender)
        r = c.post(reverse("matches-cancel", args=[self.match.id]), format="json")
        assert r.status_code == 409


class MatchListAndDetailTests(APITestCase):
    def setUp(self):
        self.sender = _user("sender4@example.com", "9")
        self.traveler = _user("traveler4@example.com", "10")
        parcel = _make_delivery(self.sender)
        trip = _make_trip(self.traveler)
        self.match = Match.objects.create(
            parcel=parcel,
            trip=trip,
            sender=self.sender,
            traveler=self.traveler,
            status=Match.Status.PENDING,
        )
        Offer.objects.create(
            match=self.match,
            proposed_by=Offer.ProposedBy.TRAVELER,
            proposer=self.traveler,
            base_amount_dzd=4000,
            commission_dzd=1000,
            total_dzd=5000,
        )

    def test_sender_sees_match_in_list(self):
        c = _client(self.sender)
        r = c.get(reverse("matches-list"))
        assert r.status_code == 200
        ids = [m["id"] for m in r.data]
        assert self.match.id in ids

    def test_traveler_sees_match_in_list(self):
        c = _client(self.traveler)
        r = c.get(reverse("matches-list") + "?role=traveler")
        assert r.status_code == 200
        ids = [m["id"] for m in r.data]
        assert self.match.id in ids

    def test_non_party_cannot_see_detail(self):
        intruder = _user("intruder3@example.com", "11")
        c = _client(intruder)
        r = c.get(reverse("matches-detail", args=[self.match.id]))
        assert r.status_code == 403

    def test_party_sees_latest_offer_in_detail(self):
        c = _client(self.sender)
        r = c.get(reverse("matches-detail", args=[self.match.id]))
        assert r.status_code == 200
        assert r.data["latest_offer"]["total_dzd"] == 5000
        assert r.data["accepted_offer"] is None
