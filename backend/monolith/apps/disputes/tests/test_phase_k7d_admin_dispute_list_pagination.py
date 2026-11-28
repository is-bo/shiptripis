"""K7 D: no dispute is out of an operator's reach through the JSON API.

`GET /api/admin/disputes` is served by the admin panel's paginated envelope
(its route is registered first). It ordered by `-opened_at` alone, so disputes
opened in the same instant could swap between pages and one could be skipped;
it now breaks ties on id.
"""

from __future__ import annotations

from django.test import TestCase
from django.urls import reverse

from apps.deals.tests.phase4_factories import fund_scenario
from apps.disputes.models import Dispute
from apps.disputes.tests.test_disputes import grant, staff_client_for

CLOSED = 104


class AdminDisputeListReachabilityTests(TestCase):
    def setUp(self):
        self.scenario = fund_scenario(self.client, prefix="k7dd")
        deal = self.scenario.deal
        Dispute.objects.bulk_create(
            Dispute(
                deal=deal,
                opened_by=self.scenario.sender,
                opened_by_role=Dispute.OpenedByRole.SENDER,
                status=Dispute.Status.CLOSED,
                category=Dispute.Category.OTHER,
                reason_text=f"K7 D closed {index}",
            )
            for index in range(CLOSED)
        )
        Dispute.objects.create(
            deal=deal,
            opened_by=self.scenario.sender,
            opened_by_role=Dispute.OpenedByRole.SENDER,
            category=Dispute.Category.DAMAGED,
            reason_text="K7 D open",
        )
        self.total = CLOSED + 1
        self.support = grant(self.scenario.outsider, "Support")

    def test_the_served_endpoint_reaches_every_dispute(self):
        client = staff_client_for(self.support)
        seen: list[int] = []
        url = reverse("admin-dispute-list")
        while url:
            response = client.get(url)
            assert response.status_code == 200, response.data
            seen.extend(row["id"] for row in response.data["results"])
            url = response.data["next"]
        assert response.data["count"] == self.total
        assert sorted(seen) == sorted(Dispute.objects.values_list("pk", flat=True))
        assert len(seen) == len(set(seen)) == self.total
