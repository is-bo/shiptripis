"""K5: the Deal list carries the viewer's pending actions, at a flat query cost.

The mobile "needs your attention" list used to fetch every Deal's detail to
read five booleans. The list row now carries them in `attention`, computed by
the same functions as the detail's `handover` and `ratings` blocks. These tests
hold three things:

* parity -- at every lifecycle step, for both parties, the list says exactly
  what the detail says;
* cost -- the list's query count does not grow with the number of Deals;
* scope -- `current` and `history` cover what the app reads, and pages are
  stable.
"""

from __future__ import annotations

from datetime import timedelta

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from apps.deals.lifecycle import rating_window
from apps.deals.models import Deal
from apps.notifications.models import Notification
from apps.notifications.resolution import resolved_notifications
from apps.ratings.models import Rating

from .phase4_factories import (
    confirm_delivery,
    confirm_pickup,
    delivered_scenario,
    fund_scenario,
    record_recipient,
    release_delivery_code,
)

HANDOVER_KEYS = (
    "can_reveal_pickup_code",
    "can_submit_pickup_code",
    "can_reveal_delivery_code",
    "can_submit_delivery_code",
)


def _client(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user)
    return client


def _rows(client, query: str = "") -> list[dict]:
    response = client.get(f"/api/deals{query}")
    assert response.status_code == 200, response.content
    return response.json()["results"]


class DealListAttentionParityTests(TestCase):
    def _assert_parity(self, scenario, step: str) -> None:
        deal_id = scenario.deal.pk
        for party in (scenario.sender, scenario.traveler):
            client = _client(party)
            row = next(r for r in _rows(client) if r["id"] == deal_id)
            detail = client.get(f"/api/deals/{deal_id}").json()
            expected = {key: detail["handover"][key] for key in HANDOVER_KEYS}
            expected["can_rate"] = detail["ratings"]["can_rate"]
            self.assertEqual(
                row["attention"], expected, f"{step}: party {party.pk}"
            )

    def test_list_attention_matches_detail_through_the_lifecycle(self):
        scenario = fund_scenario(APIClient(), prefix="k5par")
        self._assert_parity(scenario, "funded")
        record_recipient(scenario)
        self._assert_parity(scenario, "pickup_ready")
        confirm_pickup(scenario)
        # Inside the 30-minute buffer: nobody may reveal or submit.
        self._assert_parity(scenario, "in_transit, buffered")
        release_delivery_code(scenario)
        self._assert_parity(scenario, "delivery_ready")
        confirm_delivery(scenario)
        self._assert_parity(scenario, "delivered, review window open")

        Rating.objects.create(
            deal=scenario.deal,
            rater=scenario.sender,
            ratee=scenario.traveler,
            rater_role=Rating.RaterRole.SENDER,
            score=5,
            review_window_ends_at=scenario.deal.rating_window_ends_at,
        )
        self._assert_parity(scenario, "delivered, sender rated")

    def test_attention_never_carries_code_material(self):
        scenario = fund_scenario(APIClient(), prefix="k5sec")
        record_recipient(scenario)
        confirm_pickup(scenario)
        release_delivery_code(scenario)
        row = _rows(_client(scenario.traveler))[0]
        self.assertEqual(
            set(row["attention"]), {*HANDOVER_KEYS, "can_rate"}
        )
        self.assertTrue(all(isinstance(v, bool) for v in row["attention"].values()))
        # The traveler submits the delivery code; they are never offered it.
        self.assertFalse(row["attention"]["can_reveal_delivery_code"])
        self.assertTrue(row["attention"]["can_submit_delivery_code"])


class DealListQueryCostTests(TestCase):
    def _sender_with_deals(self, count: int):
        first = fund_scenario(APIClient(), prefix="k5q0")
        record_recipient(first)
        for index in range(1, count):
            other = fund_scenario(APIClient(), prefix=f"k5q{index}")
            if index % 2:
                record_recipient(other)
            Deal.objects.filter(pk=other.deal.pk).update(sender=first.sender)
        return first.sender

    def _queries(self, user, query: str) -> int:
        client = _client(user)
        client.get(f"/api/deals{query}")  # warm per-process caches
        with CaptureQueriesContext(connection) as captured:
            response = client.get(f"/api/deals{query}")
        self.assertEqual(response.status_code, 200)
        return len(captured)

    def test_list_query_count_is_flat_in_the_number_of_deals(self):
        sender = self._sender_with_deals(4)
        client = _client(sender)
        rows = _rows(client, "?scope=current")
        self.assertEqual(len(rows), 4)
        self.assertTrue(any(r["attention"]["can_reveal_pickup_code"] for r in rows))

        four = self._queries(sender, "?scope=current")
        # Two more Deals for the same sender must not cost two more queries.
        for index in (8, 9):
            other = fund_scenario(APIClient(), prefix=f"k5q{index}")
            Deal.objects.filter(pk=other.deal.pk).update(sender=sender)
        six = self._queries(sender, "?scope=current")
        self.assertEqual(six, four)


class DealListScopeTests(TestCase):
    def setUp(self):
        self.active = fund_scenario(APIClient(), prefix="k5s0")
        self.sender = self.active.sender
        cancelled = fund_scenario(APIClient(), prefix="k5s1")
        Deal.objects.filter(pk=cancelled.deal.pk).update(
            sender=self.sender, status=Deal.Status.CANCELLED
        )
        self.cancelled_id = cancelled.deal.pk
        self.client_ = _client(self.sender)

    def test_current_and_history_partition_the_party_deals(self):
        everything = {r["id"] for r in _rows(self.client_)}
        current = {r["id"] for r in _rows(self.client_, "?scope=current")}
        history = {r["id"] for r in _rows(self.client_, "?scope=history")}
        self.assertEqual(current, {self.active.deal.pk})
        self.assertEqual(history, {self.cancelled_id})
        self.assertEqual(current | history, everything)

    def test_unknown_scope_is_rejected(self):
        response = self.client_.get("/api/deals?scope=everything")
        self.assertEqual(response.status_code, 400)
        self.assertIn("scope", response.json())

    def test_page_size_is_opt_in_and_capped(self):
        body = self.client_.get("/api/deals?page_size=1").json()
        self.assertEqual(body["count"], 2)
        self.assertEqual(len(body["results"]), 1)
        self.assertIsNotNone(body["next"])
        second = self.client_.get("/api/deals?page_size=1&page=2").json()
        self.assertNotEqual(body["results"][0]["id"], second["results"][0]["id"])
        # Above the cap DRF clamps rather than failing; the default stays 20.
        capped = self.client_.get("/api/deals?page_size=5000")
        self.assertEqual(capped.status_code, 200)


class DealListCurrentReviewWindowTests(TestCase):
    """`current` keeps a Deal exactly while the inbox would still ask for a rating.

    The review window, not the activity bucket, decides: a Deal partially
    refunded after delivery is "cancelled" yet ratable, and a Deal confirmed
    before `rating_window_ends_at` existed has its deadline computed from its
    frozen policy -- neither kept forever nor dropped.
    """

    def _current_ids(self, user) -> set[int]:
        return {r["id"] for r in _rows(_client(user), "?scope=current")}

    def _inbox_asks_to_rate(self, user, deal_id: int) -> bool:
        notification = Notification.objects.create(
            recipient=user,
            channel="rating.required",
            event_id=f"k5-rate-{deal_id}-{user.pk}",
            payload={"deal_id": deal_id},
        )
        row = resolved_notifications(user).get(pk=notification.pk)
        return not row.resolved

    def test_partial_refund_after_delivery_stays_current_while_ratable(self):
        scenario = delivered_scenario(APIClient(), prefix="k5pr")
        Deal.objects.filter(pk=scenario.deal.pk).update(
            status=Deal.Status.PARTIALLY_REFUNDED
        )
        deal_id = scenario.deal.pk
        for party in (scenario.sender, scenario.traveler):
            client = _client(party)
            row = next(
                r for r in _rows(client, "?scope=current") if r["id"] == deal_id
            )
            detail = client.get(f"/api/deals/{deal_id}").json()
            self.assertTrue(row["attention"]["can_rate"])
            self.assertEqual(
                row["attention"]["can_rate"], detail["ratings"]["can_rate"]
            )
            self.assertTrue(self._inbox_asks_to_rate(party, deal_id))
            # History stays "not active", so the two scopes overlap here.
            history = {r["id"] for r in _rows(client, "?scope=history")}
            self.assertIn(deal_id, history)

    def test_completed_deal_leaves_current_when_its_review_window_closes(self):
        scenario = delivered_scenario(APIClient(), prefix="k5cl")
        Deal.objects.filter(pk=scenario.deal.pk).update(
            status=Deal.Status.COMPLETED,
            rating_window_ends_at=timezone.now() - timedelta(seconds=1),
        )
        self.assertNotIn(scenario.deal.pk, self._current_ids(scenario.sender))
        self.assertFalse(
            _client(scenario.sender)
            .get(f"/api/deals/{scenario.deal.pk}")
            .json()["ratings"]["can_rate"]
        )

    def test_legacy_deal_without_a_stored_window_follows_the_inbox_predicate(self):
        open_ = delivered_scenario(APIClient(), prefix="k5lo")
        closed = delivered_scenario(APIClient(), prefix="k5lc")
        window = rating_window(closed.deal)
        Deal.objects.filter(pk=open_.deal.pk).update(
            status=Deal.Status.COMPLETED, rating_window_ends_at=None
        )
        Deal.objects.filter(pk=closed.deal.pk).update(
            status=Deal.Status.COMPLETED,
            rating_window_ends_at=None,
            delivery_confirmed_at=timezone.now() - window - timedelta(days=1),
        )
        for scenario, expected in ((open_, True), (closed, False)):
            user, deal_id = scenario.sender, scenario.deal.pk
            detail = _client(user).get(f"/api/deals/{deal_id}").json()
            self.assertEqual(detail["ratings"]["can_rate"], expected)
            self.assertEqual(self._inbox_asks_to_rate(user, deal_id), expected)
            self.assertEqual(deal_id in self._current_ids(user), expected)
