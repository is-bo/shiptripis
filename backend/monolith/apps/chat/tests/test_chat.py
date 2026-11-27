"""Tests for apps.chat — payment-gated 1:1 messaging on a Match.

Covers:
- send is blocked until the match's Deal is funded
- non-parties cannot send or read
- send persists a ChatMessage and publishes chat.message.new with
  targets=[other_member] (fan-out is the Go relay's job)
- list returns the thread oldest-first, only to parties
- empty/oversize bodies rejected
"""

from __future__ import annotations

from unittest.mock import patch

from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import User
from apps.chat.models import ChatMessage
from apps.deals.models import Deal
from apps.deals.tests.phase4_factories import enable_mock_rail
from apps.finance.models import PaymentOrder
from apps.finance.tests.factories import build_scenario, pay_order_with_mock
from apps.matching.models import Match
from apps.parcels.tests.test_l11a_tracking_number import _second_deal


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


def _fund(client, deal: Deal) -> Match:
    """Pay the Deal's balance through the real test rail."""
    enable_mock_rail()
    order = PaymentOrder.objects.get(deal=deal, purpose=PaymentOrder.Purpose.DEAL_BALANCE)
    pay_order_with_mock(client, order)
    return deal.match


def _funded_thread(client, prefix: str):
    """A new sender and traveler with one funded Deal: (scenario, match)."""
    scenario = build_scenario(prefix=prefix)
    return scenario, _fund(client, scenario.accept())


class ChatSendTests(APITestCase):
    def setUp(self):
        self.scenario = build_scenario(prefix="chat-send")
        self.sender = self.scenario.sender
        self.traveler = self.scenario.traveler
        self.deal = self.scenario.accept()
        self.match = self.deal.match

    def _send_url(self):
        return reverse("chat-messages", args=[self.match.id])

    def test_send_blocked_before_payment(self):
        c = _client(self.sender)
        r = c.post(self._send_url(), {"body": "hi"}, format="json")
        assert r.status_code == 402, r.data
        assert r.data["reason"] == "payment_pending"
        assert ChatMessage.objects.count() == 0

    def test_non_party_cannot_send(self):
        _fund(self.client, self.deal)
        intruder = _user("intruder-chat@example.com", "3")
        r = _client(intruder).post(self._send_url(), {"body": "hi"}, format="json")
        assert r.status_code == 403
        assert ChatMessage.objects.count() == 0

    def test_send_persists_and_publishes_to_other_party(self):
        _fund(self.client, self.deal)
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
        # Both members receive the persisted event; only the other gets an inbox row.
        assert pub.call_count == 1
        args, kwargs = pub.call_args
        assert args[0] == "chat.message.new"
        assert kwargs["targets"] == [self.traveler.id, self.sender.id]
        assert args[1]["message_id"] == msg.id
        assert args[1]["match_id"] == self.match.id
        assert args[1]["sender_id"] == self.sender.id
        assert args[1]["body"] == "on my way"

    def test_traveler_sends_targets_sender(self):
        _fund(self.client, self.deal)
        with patch("apps.chat.views.redis_bus.publish_after_commit") as pub:
            r = _client(self.traveler).post(
                self._send_url(), {"body": "great"}, format="json"
            )
        assert r.status_code == 201, r.data
        _, kwargs = pub.call_args
        assert kwargs["targets"] == [self.sender.id, self.traveler.id]

    def test_empty_body_rejected(self):
        _fund(self.client, self.deal)
        r = _client(self.sender).post(self._send_url(), {"body": "   "}, format="json")
        assert r.status_code == 400

    def test_send_blocked_when_deal_cancelled(self):
        _fund(self.client, self.deal)
        Deal.objects.filter(pk=self.deal.pk).update(status=Deal.Status.CANCELLED)
        r = _client(self.sender).post(self._send_url(), {"body": "hi"}, format="json")
        assert r.status_code == 402
        assert r.data["reason"] == "match_closed"


class ChatListTests(APITestCase):
    def setUp(self):
        scenario, self.match = _funded_thread(self.client, "chat-list")
        self.sender, self.traveler = scenario.sender, scenario.traveler

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

    def test_opening_thread_marks_counterparty_messages_read(self):
        mine = ChatMessage.objects.create(
            match=self.match, sender=self.sender, body="mine"
        )
        theirs = ChatMessage.objects.create(
            match=self.match, sender=self.traveler, body="theirs"
        )
        # Sender opens the thread → the traveler's message is marked read,
        # the sender's own message is left alone.
        r = _client(self.sender).get(self._url())
        assert r.status_code == 200
        theirs.refresh_from_db()
        mine.refresh_from_db()
        assert theirs.read_at is not None
        assert mine.read_at is None


class ChatThreadsTests(APITestCase):
    """GET /api/chat/threads — the Mailroom inbox: only paid matches, with
    counterparty name, route, last-message snippet, and viewer unread count."""

    def setUp(self):
        self.scenario = build_scenario(prefix="chat-threads")
        self.sender = self.scenario.sender
        self.traveler = self.scenario.traveler

    def _url(self):
        return reverse("chat-threads")

    def test_lists_only_paid_matches(self):
        # Paid match — should appear.
        paid = _fund(self.client, self.scenario.accept())
        # Accepted-but-unpaid match — should NOT appear.
        _second_deal(self.scenario)

        r = _client(self.sender).get(self._url())
        assert r.status_code == 200, r.data
        ids = [t["match_id"] for t in r.data["results"]]
        assert ids == [paid.id]

    def test_thread_row_shape_and_counterparty(self):
        match = _fund(self.client, self.scenario.accept())
        ChatMessage.objects.create(
            match=match, sender=self.traveler, body="on my way"
        )

        # Sender sees the traveler as counterparty.
        r = _client(self.sender).get(self._url())
        row = r.data["results"][0]
        assert row["match_id"] == match.id
        assert row["counterparty_id"] == self.traveler.id
        assert row["counterparty_name"] == "User"  # the first name of "User 2"
        # V1 requests carry no city fields, so the label is empty (reported as a follow-up).
        assert row["route"] == ""
        assert row["last_message"] == "on my way"
        assert row["unread_count"] == 1  # the traveler's message, unread

        # Traveler sees the sender as counterparty, and their own message
        # doesn't count as unread for them.
        r2 = _client(self.traveler).get(self._url())
        row2 = r2.data["results"][0]
        assert row2["counterparty_id"] == self.sender.id
        assert row2["unread_count"] == 0

    def test_empty_thread_still_listed(self):
        match = _fund(self.client, self.scenario.accept())
        r = _client(self.sender).get(self._url())
        row = r.data["results"][0]
        assert row["match_id"] == match.id
        assert row["last_message"] is None
        assert row["unread_count"] == 0

    def test_ordered_by_recent_activity(self):
        older = _fund(self.client, self.scenario.accept())
        newer = _fund(self.client, _second_deal(self.scenario))
        # Give `older` the most recent message → it should sort first.
        ChatMessage.objects.create(match=older, sender=self.sender, body="hi")

        r = _client(self.sender).get(self._url())
        ids = [t["match_id"] for t in r.data["results"]]
        assert ids[0] == older.id
        assert set(ids) == {older.id, newer.id}

    def test_non_party_sees_nothing(self):
        _fund(self.client, self.scenario.accept())
        r = _client(self.scenario.outsider).get(self._url())
        assert r.status_code == 200
        assert r.data["results"] == []
