"""K7 D: no dispute is out of an operator's reach through the JSON API.

`GET /api/admin/disputes` is served by the admin panel's paginated envelope
(its route is registered first). It ordered by `-opened_at` alone, so disputes
opened in the same instant could swap between pages and one could be skipped;
it now breaks ties on id. The disputes app declares the same path with
its own view, which used to hard-slice `[:100]`: shadowed today, but one URL
reordering away from silently hiding every older dispute. Both are pinned here.
"""

from __future__ import annotations

from django.test import TestCase
from django.urls import resolve, reverse
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.deals.tests.phase4_factories import fund_scenario
from apps.disputes.models import Dispute
from apps.disputes.tests.test_disputes import client_for, grant
from apps.disputes.views import AdminDisputeListView

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
        client = client_for(self.support)
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

    def test_the_disputes_app_view_keeps_its_array_and_pages_past_100(self):
        # Pinned directly: the route resolves to the admin panel view first.
        assert resolve("/api/admin/disputes").url_name == "admin-dispute-list"
        view = AdminDisputeListView.as_view()
        factory = APIRequestFactory()

        def get(query=""):
            request = factory.get(f"/api/admin/disputes{query}")
            force_authenticate(request, user=self.support)
            response = view(request)
            response.render()
            return response

        first = get()
        assert first.status_code == 200
        # Existing callers: the same bare array of the newest 100.
        assert isinstance(first.data, list)
        assert len(first.data) == 100
        assert first["X-Total-Count"] == str(self.total)
        assert first["X-Next-Page"] == "2"
        newest = list(Dispute.objects.order_by("-opened_at", "-id").values_list("pk", flat=True))
        assert [row["id"] for row in first.data] == newest[:100]

        second = get("?page=2")
        assert second.status_code == 200
        assert [row["id"] for row in second.data] == newest[100:]
        assert "X-Next-Page" not in second

        only_open = get("?status=open")
        assert [row["status"] for row in only_open.data] == ["open"]
        assert only_open["X-Total-Count"] == "1"

    def test_the_disputes_app_view_still_requires_the_permission(self):
        request = APIRequestFactory().get("/api/admin/disputes")
        force_authenticate(request, user=self.scenario.sender)
        assert AdminDisputeListView.as_view()(request).status_code == 403
