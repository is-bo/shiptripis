"""K4 read-path budgets over one representative canonical marketplace world.

The ceilings are deliberately broad.  Their purpose is to catch query growth
with row count and accidental detail work on collection endpoints, not to pin
Django's authentication or pagination internals to an exact number.

Set ``SHIPTRIP_K4_PROFILE=1`` to print the measured latency, query/DB time and
rendered payload bytes used by the K4 implementation record.
"""

from __future__ import annotations

import json
import os
from statistics import median
from time import perf_counter

from django.db import connection
from django.test import Client, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.chat.models import ChatMessage
from apps.deals.models import Deal
from apps.deals.tests.phase4_factories import enable_mock_rail
from apps.finance.models import PaymentOrder
from apps.finance.tests.factories import pay_order_with_mock
from apps.matching.tests.test_phase8dr_offer_locks import CanonicalOfferFixture
from apps.matching.v1_services import accept_offer
from apps.notifications.models import Notification


def _client(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


class K4ReadPathBudgets(CanonicalOfferFixture, TestCase):
    maxDiff = None

    def setUp(self) -> None:
        enable_mock_rail()
        self.build_world()
        accepted = accept_offer(
            pending_offer=self.propose(), actor=self.traveler
        )
        self.deal = accepted.deal
        pay_order_with_mock(
            Client(),
            PaymentOrder.objects.get(
                deal=self.deal, purpose=PaymentOrder.Purpose.DEAL_BALANCE
            ),
        )
        self.deal.refresh_from_db()
        self.sender_client = _client(self.sender)
        self.traveler_client = _client(self.traveler)

        ChatMessage.objects.create(
            match=self.deal.match,
            sender=self.traveler,
            body="K4 representative message",
        )
        for index in range(10):
            Notification.objects.create(
                recipient=self.sender,
                channel="system.notice",
                event_id=f"k4-notification-{index}",
                payload={"index": index},
            )

        # Matching needs an open request; acceptance closed the first one.
        self.matching_request = self._request(
            self.paris, self.jijel, title="K4 matching request"
        )

    def _add_funded_threads(self, count: int, *, prefix: str) -> None:
        for index in range(count):
            journey, flight, drive = self._journey(
                self.traveler, origin=self.cdg
            )
            delivery_request = self._request(
                self.paris, self.jijel, title=f"{prefix} {index}"
            )
            offer = self.propose(
                delivery_request=delivery_request,
                journey=journey,
                start_leg_id=flight.pk,
                end_leg_id=drive.pk,
            )
            deal = accept_offer(
                pending_offer=offer, actor=self.traveler
            ).deal
            Deal.objects.filter(pk=deal.pk).update(
                status=Deal.Status.FUNDED,
                funded_at=timezone.now(),
            )
            ChatMessage.objects.create(
                match=deal.match,
                sender=self.traveler,
                body=f"K4 thread message {index}",
            )

    @staticmethod
    def _measure(client: APIClient, path: str) -> dict[str, int | float]:
        warm = client.get(path)
        assert warm.status_code == 200, (path, warm.status_code, warm.data)

        latencies = []
        response = warm
        for _ in range(5):
            started = perf_counter()
            response = client.get(path)
            latencies.append((perf_counter() - started) * 1_000)
        with CaptureQueriesContext(connection) as captured:
            started = perf_counter()
            response = client.get(path)
            measured_latency = (perf_counter() - started) * 1_000
        assert response.status_code == 200, (path, response.status_code, response.data)
        response.render()
        return {
            "latency_ms": round(median([*latencies, measured_latency]), 2),
            "queries": len(captured.captured_queries),
            "db_ms": round(
                sum(float(row.get("time") or 0) for row in captured.captured_queries)
                * 1_000,
                2,
            ),
            "payload_bytes": len(response.content),
        }

    def _profile(self) -> dict[str, dict[str, int | float]]:
        self._add_funded_threads(4, prefix="K4 profile thread")
        return {
            "chat_inbox": self._measure(self.sender_client, "/api/chat/threads"),
            "chat_messages": self._measure(
                self.sender_client,
                f"/api/matches/{self.deal.match_id}/chat/messages?latest=1",
            ),
            "notifications": self._measure(
                self.sender_client, "/api/notifications?bucket=all"
            ),
            "unread_count": self._measure(
                self.sender_client, "/api/notifications/unread-count"
            ),
            "deal_list": self._measure(self.sender_client, "/api/deals"),
            "active_deals": self._measure(
                self.sender_client, "/api/deals?activity=active"
            ),
            "deal_detail": self._measure(
                self.sender_client, f"/api/deals/{self.deal.pk}"
            ),
            "journey_list": self._measure(
                self.traveler_client, "/api/journeys"
            ),
            "journey_detail": self._measure(
                self.traveler_client, f"/api/journeys/{self.journey.pk}"
            ),
            "request_list": self._measure(self.sender_client, "/api/parcels"),
            "request_detail": self._measure(
                self.sender_client, f"/api/parcels/{self.request.pk}"
            ),
            "find_travelers": self._measure(
                self.sender_client,
                reverse("matches-find-travelers-v1")
                + f"?parcel_id={self.matching_request.pk}",
            ),
            "payout_list": self._measure(self.traveler_client, "/api/payouts"),
            "payout_history": self._measure(
                self.traveler_client, "/api/payouts?page=1&page_size=30"
            ),
            "payout_account": self._measure_payout_account(),
            "countries": self._measure(self.sender_client, "/api/geography/countries"),
            "places": self._measure(
                self.sender_client, "/api/geography/places?country=FR"
            ),
        }

    def _measure_payout_account(self) -> dict[str, int | float]:
        with override_settings(PAYOUT_PROFILES_ENABLED=True):
            return self._measure(self.traveler_client, "/api/payouts/methods")

    def test_representative_reads_stay_within_safe_query_and_payload_budgets(self):
        profile = self._profile()
        if os.environ.get("SHIPTRIP_K4_PROFILE") == "1":
            print("K4_PROFILE=" + json.dumps(profile, sort_keys=True))

        ceilings = {
            "chat_inbox": 8,
            "chat_messages": 6,
            "notifications": 12,
            "unread_count": 10,
            "deal_list": 8,
            "active_deals": 8,
            "deal_detail": 16,
            "journey_list": 12,
            "journey_detail": 14,
            "request_list": 8,
            "request_detail": 8,
            "find_travelers": 10,
        }
        for name, ceiling in ceilings.items():
            self.assertLessEqual(profile[name]["queries"], ceiling, (name, profile[name]))

        # Broad enough for real content, tight enough to catch accidentally
        # embedding route corridors or detail aggregates in every list row.
        self.assertLess(profile["journey_list"]["payload_bytes"], 250_000)
        self.assertLess(profile["deal_list"]["payload_bytes"], 150_000)
        self.assertLess(profile["find_travelers"]["payload_bytes"], 50_000)

    def test_chat_inbox_query_count_is_flat_as_threads_grow(self):
        one = self._measure(self.sender_client, "/api/chat/threads")
        self._add_funded_threads(4, prefix="K4 flat thread")
        five = self._measure(self.sender_client, "/api/chat/threads")
        self.assertLessEqual(five["queries"], one["queries"] + 1, (one, five))

        first = self.sender_client.get("/api/chat/threads?page=1&page_size=1")
        second = self.sender_client.get("/api/chat/threads?page=2&page_size=1")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.data["count"], 5)
        self.assertNotEqual(
            first.data["results"][0]["match_id"],
            second.data["results"][0]["match_id"],
        )

    def test_array_collections_page_without_changing_their_body_shape(self):
        second_journey, _, _ = self._journey(self.traveler, origin=self.cdg)
        first = self.traveler_client.get("/api/journeys?page=1&page_size=1")
        second = self.traveler_client.get("/api/journeys?page=2&page_size=1")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertIsInstance(first.data, list)
        self.assertIsInstance(second.data, list)
        self.assertEqual(first["X-Total-Count"], "2")
        self.assertEqual(first["X-Next-Page"], "2")
        self.assertNotEqual(first.data[0]["id"], second.data[0]["id"])
        self.assertIn(
            second_journey.pk,
            {first.data[0]["id"], second.data[0]["id"]},
        )

        parcel_first = self.sender_client.get("/api/parcels?page=1&page_size=1")
        parcel_second = self.sender_client.get("/api/parcels?page=2&page_size=1")
        self.assertEqual(parcel_first.status_code, 200)
        self.assertEqual(parcel_second.status_code, 200)
        self.assertIsInstance(parcel_first.data, list)
        self.assertNotEqual(parcel_first.data[0]["id"], parcel_second.data[0]["id"])

        self._add_funded_threads(1, prefix="K4 paged match")
        match_first = self.sender_client.get("/api/matches?page=1&page_size=1")
        match_second = self.sender_client.get("/api/matches?page=2&page_size=1")
        self.assertEqual(match_first.status_code, 200)
        self.assertEqual(match_second.status_code, 200)
        self.assertIsInstance(match_first.data, list)
        self.assertNotEqual(match_first.data[0]["id"], match_second.data[0]["id"])

    def test_journey_collection_omits_detail_only_route_evidence(self):
        listing = self.traveler_client.get("/api/journeys")
        detail = self.traveler_client.get(f"/api/journeys/{self.journey.pk}")

        self.assertEqual(listing.status_code, 200)
        self.assertEqual(detail.status_code, 200)
        list_leg = next(
            row for row in listing.data if row["id"] == self.journey.pk
        )["legs"][0]
        detail_leg = detail.data["legs"][0]
        for field in ("route_polyline", "route_metadata", "proofs"):
            self.assertNotIn(field, list_leg)
            self.assertIn(field, detail_leg)

    def test_reference_catalogues_are_publicly_cacheable_and_conditional(self):
        countries = self.sender_client.get("/api/geography/countries")
        self.assertEqual(countries.status_code, 200)
        self.assertEqual(countries["Cache-Control"], "public, max-age=3600")
        self.assertTrue(countries["ETag"])

        unchanged = self.sender_client.get(
            "/api/geography/countries",
            HTTP_IF_NONE_MATCH=countries["ETag"],
        )
        self.assertEqual(unchanged.status_code, 304)
        self.assertEqual(unchanged.content, b"")
