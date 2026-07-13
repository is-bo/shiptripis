"""Tests for apps.chat — payment-gated 1:1 messaging on a Match.

Covers:
- send is blocked until the match's accepted offer has a succeeded payment
- non-parties cannot send or read
- send persists a ChatMessage and publishes chat.message.new with
  targets=[other_member] (fan-out is the Go relay's job)
- list returns the thread oldest-first, only to parties
- empty/oversize bodies rejected
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import User
from apps.matching.models import Match, Offer
from apps.parcels.models import DeliveryRequest, ParcelRequest
from apps.payments.models import PaymentIntent
from apps.trips.models import Trip
from apps.chat.models import ChatMessage


def _user(email: str, suffix: str = "1") -> User:
    return User.objects.create_user(
        username=email,
        email=email,
        password="Sup3rStrongPass!",
        full_name=f"User {suffix}",
        phone=f"+21355500033{suffix}",
        wilaya="16",
    )


def _client(user: User) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def _make_match(sender: User, traveler: User, *, status=Match.Status.ACCEPTED) -> Match:
    parcel = DeliveryRequest.objects.create(
        sender=sender,
        kind=ParcelRequest.Kind.DELIVERY,
        origin_id="ALG",
        destination_id="CDG",
        weight_kg=2,
        item_type=ParcelRequest.ItemType.DOCUMENTS,
        description="docs",
        base_amount_dzd=4000,
    )
    trip = Trip.objects.create(
        traveler=traveler,
        origin_id="ALG",
        destination_id="CDG",
        departure_at=timezone.now() + timedelta(days=5),
        capacity_kg=8,
    )
    return Match.objects.create(
        parcel=parcel,
        trip=trip,
        sender=sender,
        traveler=traveler,
        status=status,
    )


def _accepted_offer(match: Match, traveler: User) -> Offer:
    return Offer.objects.create(
        match=match,
        proposed_by=Offer.ProposedBy.TRAVELER,
        proposer=traveler,
        base_amount_dzd=4000,
        commission_dzd=1000,
        total_dzd=5000,
        status=Offer.Status.ACCEPTED,
    )


def _pay(offer: Offer, payer: User) -> PaymentIntent:
    return PaymentIntent.objects.create(
        offer=offer,
        payer=payer,
        provider="mock",
        provider_intent_id=f"pi_mock_{offer.id}",
        amount_minor=offer.total_dzd,
        currency="DZD",
        status=PaymentIntent.Status.SUCCEEDED,
    )


class ChatSendTests(APITestCase):
    def setUp(self):
        self.sender = _user("chatsender@example.com", "1")
        self.traveler = _user("chattraveler@example.com", "2")
        self.match = _make_match(self.sender, self.traveler)
        self.offer = _accepted_offer(self.match, self.traveler)

    def _send_url(self):
        return reverse("chat-messages", args=[self.match.id])

    def test_send_blocked_before_payment(self):
        c = _client(self.sender)
        r = c.post(self._send_url(), {"body": "hi"}, format="json")
        assert r.status_code == 402, r.data
        assert r.data["reason"] == "payment_pending"
        assert ChatMessage.objects.count() == 0

    def test_non_party_cannot_send(self):
        _pay(self.offer, self.sender)
        intruder = _user("intruder-chat@example.com", "3")
        r = _client(intruder).post(self._send_url(), {"body": "hi"}, format="json")
        assert r.status_code == 403
        assert ChatMessage.objects.count() == 0

    def test_send_persists_and_publishes_to_other_party(self):
        _pay(self.offer, self.sender)
        with patch("apps.chat.views.redis_bus.publish_after_commit") as pub:
            r = _client(self.sender).post(
                self._send_url(), {"body": "on my way"}, format="json"
            )
        assert r.status_code == 201, r.data
        msg = ChatMessage.objects.get()
        assert msg.sender_id == self.sender.id
        assert msg.match_id == self.match.id
        assert msg.body == "on my way"
        assert r.data["id"] == msg.id
        assert r.data["sender_id"] == self.sender.id
        assert r.data["body"] == "on my way"
        # published once, to the traveler (the OTHER member), on chat.message.new
        assert pub.call_count == 1
        args, kwargs = pub.call_args
        assert args[0] == "chat.message.new"
        assert kwargs["targets"] == [self.traveler.id]
        assert args[1]["message_id"] == msg.id
        assert args[1]["match_id"] == self.match.id
        assert args[1]["sender_id"] == self.sender.id
        assert args[1]["body"] == "on my way"

    def test_traveler_sends_targets_sender(self):
        _pay(self.offer, self.sender)
        with patch("apps.chat.views.redis_bus.publish_after_commit") as pub:
            r = _client(self.traveler).post(
                self._send_url(), {"body": "great"}, format="json"
            )
        assert r.status_code == 201, r.data
        _, kwargs = pub.call_args
        assert kwargs["targets"] == [self.sender.id]

    def test_empty_body_rejected(self):
        _pay(self.offer, self.sender)
        r = _client(self.sender).post(self._send_url(), {"body": "   "}, format="json")
        assert r.status_code == 400

    def test_send_blocked_when_match_cancelled(self):
        _pay(self.offer, self.sender)
        self.match.status = Match.Status.CANCELLED
        self.match.save(update_fields=["status"])
        r = _client(self.sender).post(self._send_url(), {"body": "hi"}, format="json")
        assert r.status_code == 402
        assert r.data["reason"] == "match_closed"


class ChatListTests(APITestCase):
    def setUp(self):
        self.sender = _user("chatsender2@example.com", "4")
        self.traveler = _user("chattraveler2@example.com", "5")
        self.match = _make_match(self.sender, self.traveler)
        self.offer = _accepted_offer(self.match, self.traveler)
        _pay(self.offer, self.sender)

    def _url(self):
        return reverse("chat-messages", args=[self.match.id])

    def test_list_returns_thread_oldest_first(self):
        ChatMessage.objects.create(match=self.match, sender=self.sender, body="one")
        ChatMessage.objects.create(match=self.match, sender=self.traveler, body="two")
        r = _client(self.sender).get(self._url())
        assert r.status_code == 200
        bodies = [m["body"] for m in r.data["results"]]
        assert bodies == ["one", "two"]

    def test_non_party_cannot_list(self):
        intruder = _user("intruder-chat2@example.com", "6")
        r = _client(intruder).get(self._url())
        assert r.status_code == 403
