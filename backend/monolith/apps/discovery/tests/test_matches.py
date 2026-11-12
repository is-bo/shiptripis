"""L2A Matches tier: a fan-in over the existing engines, never a second one."""

from __future__ import annotations

from django.test import TestCase
from django.urls import reverse

from apps.parcels.models import DeliveryRequest, ParcelRequest
from apps.trips.models import Journey

from .support import DiscoveryWorld, client_for

MATCHES = "discovery-matches"


class MatchesTierTests(DiscoveryWorld, TestCase):
    def setUp(self):
        self.build_discovery_world()

    def matches(self, viewer, role):
        response = client_for(viewer).get(reverse(MATCHES), {"role": role})
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def test_a_senders_group_is_the_find_travelers_first_page(self):
        payload = self.matches(self.sender, "sender")

        self.assertEqual(payload["state"], "results")
        [group] = payload["groups"]
        self.assertEqual(group["request"]["id"], self.request.pk)
        self.assertEqual(group["request"]["pickup"]["label"], "Paris")
        engine = client_for(self.sender).get(
            reverse("matches-find-travelers-v1"),
            {"parcel_id": self.request.pk, "limit": 3},
        )
        self.assertEqual(group["results"], engine.data["results"])
        self.assertEqual(
            [row["journey_id"] for row in group["results"]], [self.journey.pk]
        )
        self.assertFalse(group["more_available"])

    def test_a_travelers_group_is_the_compatible_requests_head(self):
        payload = self.matches(self.traveler, "traveler")

        [group] = payload["groups"]
        self.assertEqual(group["journey"]["id"], self.journey.pk)
        engine = client_for(self.traveler).get(
            reverse("matches-compatible-requests-v1"), {"journey_id": self.journey.pk}
        )
        self.assertEqual(group["results"], engine.data["results"][:3])
        self.assertEqual(len(group["results"]), 1)

    def test_items_without_a_compatible_counterpart_answer_none(self):
        Journey.objects.filter(pk=self.journey.pk).update(status=Journey.Status.CANCELLED)

        payload = self.matches(self.sender, "sender")

        self.assertEqual(payload["state"], "none")
        self.assertEqual(payload["groups"][0]["results"], [])

    def test_no_open_items_answers_no_active_items(self):
        DeliveryRequest.objects.filter(pk=self.request.pk).update(
            status=ParcelRequest.Status.CANCELLED
        )
        self.assertEqual(
            self.matches(self.sender, "sender"), {"state": "no_active_items", "groups": []}
        )
        self.assertEqual(self.matches(self.other, "traveler")["state"], "no_active_items")

    def test_at_most_three_items_and_three_results_each(self):
        for index in range(4):
            self._request(self.algiers, self.jijel, title=f"Extra {index}")
        for index in range(4):
            self.drive_journey(self.new_traveler(f"l2a-m{index}@example.com"), days=2)

        payload = self.matches(self.sender, "sender")

        self.assertEqual(len(payload["groups"]), 3)
        newest = payload["groups"][0]
        self.assertEqual(len(newest["results"]), 3)
        self.assertTrue(newest["more_available"])

    def test_role_is_required(self):
        response = client_for(self.sender).get(reverse(MATCHES))
        self.assertEqual(response.status_code, 400)
