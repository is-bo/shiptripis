"""Tests for apps.matching — the routed Match reads, cancel and chat gate.

Covers:
- either party cancels a pending match; nobody else can
- list and detail visibility, including full names
- chat eligibility for historical pre-V1 matches settled through the retired
  `PaymentIntent`

V1 negotiation (propose, counter, accept, decline, withdraw) is covered in
`test_v1_matching.py`.
"""

from __future__ import annotations

from datetime import timedelta

from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import User
from apps.matching.models import Match, Offer
from apps.parcels.models import DeliveryRequest, ParcelRequest
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
            economics_version=Offer.EconomicsVersion.LEGACY_DZD,
            currency=Offer.Currency.DZD,
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
            economics_version=Offer.EconomicsVersion.LEGACY_DZD,
            currency=Offer.Currency.DZD,
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

    def test_match_detail_includes_full_names(self):
        self.sender.full_name = "Amine Khelifi"
        self.sender.save(update_fields=["full_name"])
        self.traveler.full_name = "Yacine Bensalah"
        self.traveler.save(update_fields=["full_name"])
        c = _client(self.sender)
        r = c.get(reverse("matches-detail", args=[self.match.id]))
        assert r.status_code == 200
        assert r.data["sender_name"] == "Amine Khelifi"
        assert r.data["traveler_name"] == "Yacine Bensalah"

    def test_match_list_includes_full_names(self):
        self.sender.full_name = "Amine Khelifi"
        self.sender.save(update_fields=["full_name"])
        self.traveler.full_name = "Yacine Bensalah"
        self.traveler.save(update_fields=["full_name"])
        c = _client(self.sender)
        r = c.get(reverse("matches-list"))
        assert r.status_code == 200
        row = next(m for m in r.data if m["id"] == self.match.id)
        assert row["sender_name"] == "Amine Khelifi"
        assert row["traveler_name"] == "Yacine Bensalah"


class ChatEligibilityTests(APITestCase):
    """GET /api/matches/<id>/chat-eligibility — payment-gated chat."""

    def setUp(self):
        self.sender = _user("sender-chat@example.com", "1")
        self.traveler = _user("traveler-chat@example.com", "2")
        self.outsider = _user("outsider@example.com", "3")
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
            base_fee_dzd=0,
            commission_dzd=1000,
            total_dzd=5000,
            economics_version=Offer.EconomicsVersion.LEGACY_DZD,
            currency=Offer.Currency.DZD,
            status=Offer.Status.PENDING,
        )

    def _accept_offer(self):
        self.offer.status = Offer.Status.ACCEPTED
        self.offer.save(update_fields=["status"])
        self.match.status = Match.Status.ACCEPTED
        self.match.save(update_fields=["status"])

    def _succeed_payment(self):
        from apps.payments.models import PaymentIntent

        return PaymentIntent.objects.create(
            offer=self.offer,
            payer=self.sender,
            amount_minor=5000,
            currency="DZD",
            provider=PaymentIntent.Provider.MOCK,
            provider_intent_id=f"pi_test_{self.offer.id}",
            status=PaymentIntent.Status.SUCCEEDED,
        )

    def test_unauth_rejected(self):
        c = APIClient()
        r = c.get(reverse("matches-chat-eligibility", args=[self.match.id]))
        assert r.status_code == 401

    def test_outsider_gets_not_a_party(self):
        c = _client(self.outsider)
        r = c.get(reverse("matches-chat-eligibility", args=[self.match.id]))
        assert r.status_code == 200
        assert r.data == {
            "eligible": False,
            "reason": "not_a_party",
            "match_id": self.match.id,
            "blocked_by_me": False,
        }

    def test_party_with_no_accepted_offer_blocked(self):
        c = _client(self.sender)
        r = c.get(reverse("matches-chat-eligibility", args=[self.match.id]))
        assert r.status_code == 200
        assert r.data["eligible"] is False
        assert r.data["reason"] == "no_accepted_offer"

    def test_accepted_offer_without_payment_blocked(self):
        self._accept_offer()
        c = _client(self.sender)
        r = c.get(reverse("matches-chat-eligibility", args=[self.match.id]))
        assert r.status_code == 200
        assert r.data["eligible"] is False
        assert r.data["reason"] == "payment_pending"

    def test_pending_payment_blocked(self):
        from apps.payments.models import PaymentIntent

        self._accept_offer()
        PaymentIntent.objects.create(
            offer=self.offer,
            payer=self.sender,
            amount_minor=5000,
            currency="DZD",
            provider=PaymentIntent.Provider.MOCK,
            provider_intent_id=f"pi_pending_{self.offer.id}",
            status=PaymentIntent.Status.PROCESSING,
        )
        c = _client(self.sender)
        r = c.get(reverse("matches-chat-eligibility", args=[self.match.id]))
        assert r.data["eligible"] is False
        assert r.data["reason"] == "payment_pending"

    def test_succeeded_payment_unlocks_chat_for_sender(self):
        self._accept_offer()
        self._succeed_payment()
        c = _client(self.sender)
        r = c.get(reverse("matches-chat-eligibility", args=[self.match.id]))
        assert r.status_code == 200
        assert r.data == {
            "eligible": True,
            "reason": "ok",
            "match_id": self.match.id,
            "blocked_by_me": False,
        }

    def test_succeeded_payment_unlocks_chat_for_traveler(self):
        self._accept_offer()
        self._succeed_payment()
        c = _client(self.traveler)
        r = c.get(reverse("matches-chat-eligibility", args=[self.match.id]))
        assert r.data["eligible"] is True

    def test_cancelled_match_blocks_chat_even_after_payment(self):
        self._accept_offer()
        self._succeed_payment()
        self.match.status = Match.Status.CANCELLED
        self.match.save(update_fields=["status"])
        c = _client(self.sender)
        r = c.get(reverse("matches-chat-eligibility", args=[self.match.id]))
        assert r.data["eligible"] is False
        assert r.data["reason"] == "match_closed"

    def test_404_for_unknown_match(self):
        c = _client(self.sender)
        r = c.get(reverse("matches-chat-eligibility", args=[999999]))
        assert r.status_code == 404
