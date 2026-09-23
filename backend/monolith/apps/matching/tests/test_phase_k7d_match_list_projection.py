"""K7 D: the Offers list carries what a list reads, and the detail the rest.

`GET /api/matches` rendered about 9.6 KB per row: the Match's compatibility
snapshot plus, on each of `latest_offer` and `accepted_offer`, a
`terms_snapshot` holding the frozen pricing and a second copy of that
compatibility. The app parses those into `Match.compatibility`,
`Offer.termsPricing`, `Offer.termsCompatibility` and
`Offer.paymentGraceSeconds`, and no screen reads any of them. The list now
omits them; everything else in a row, `allowed_actions` included, is the same
value the detail returns, and the detail is unchanged.
"""

from __future__ import annotations

import json
from unittest import mock

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.finance.tests.factories import build_scenario
from apps.matching.models import Match
from apps.matching.serializers import MatchSerializer
from apps.matching.tests.test_phase_j61_offer_boost_projection import (
    accept,
    client_for,
    confirmed,
    copy_request,
    propose,
)

LIST_ONLY_DROPS = {"compatibility_snapshot"}
OFFER_LIST_DROPS = {"terms_snapshot"}


class MatchListProjectionTests(TestCase):
    def setUp(self):
        self.scenario = build_scenario(prefix="k7dm")
        self.proposed = propose(self.scenario)
        self.match_id = self.proposed["match"]

    def _pair(self, user) -> tuple[dict, dict]:
        client = client_for(user)
        listed = client.get(reverse("matches-list"))
        assert listed.status_code == 200, listed.data
        row = next(item for item in listed.data if item["id"] == self.match_id)
        detail = client.get(reverse("matches-detail", args=[self.match_id]))
        assert detail.status_code == 200, detail.data
        return row, detail.data

    def _assert_projection(self, row: dict, detail: dict, *, offers: tuple[str, ...]):
        assert set(row) == set(detail) - LIST_ONLY_DROPS
        for field in row:
            if field in offers:
                continue
            assert row[field] == detail[field], field
        for name in offers:
            assert set(row[name]) == set(detail[name]) - OFFER_LIST_DROPS, name
            for field, value in row[name].items():
                assert value == detail[name][field], (name, field)

    def test_a_pending_row_keeps_every_field_a_list_reads(self):
        for user in (self.scenario.sender, self.scenario.traveler):
            row, detail = self._pair(user)
            self._assert_projection(row, detail, offers=("latest_offer",))
            assert row["accepted_offer"] is None
            # Negotiation authority is untouched, per viewer.
            assert row["latest_offer"]["allowed_actions"] == detail["latest_offer"][
                "allowed_actions"
            ]
            for field in (
                "sender_name",
                "traveler_name",
                "status",
                "deal_id",
                "journey_id",
                "matched_distance_band",
                "parcel",
            ):
                assert field in row
            for field in (
                "traveler_reward_minor",
                "sender_total_minor",
                "traveler_total_minor",
                "sender_total_with_boost_minor",
                "boost_terms_status",
                "awaiting_party",
                "awaiting_user_id",
            ):
                assert field in row["latest_offer"]
        assert self._pair(self.scenario.traveler)[0]["latest_offer"]["allowed_actions"] == [
            "accept",
            "counter",
            "decline",
        ]
        assert self._pair(self.scenario.sender)[0]["latest_offer"]["allowed_actions"] == [
            "withdraw"
        ]

    def test_the_detail_is_still_complete(self):
        detail = self._pair(self.scenario.sender)[1]
        assert detail["compatibility_snapshot"]["covered_legs"]
        terms = detail["latest_offer"]["terms_snapshot"]
        assert terms["pricing"] and terms["compatibility"]
        offers = client_for(self.scenario.sender).get(
            reverse("matches-offers", args=[self.match_id])
        )
        assert "terms_snapshot" in offers.data[0]

    def test_an_accepted_row_and_its_size(self):
        accepted = accept(
            self.scenario.traveler, self.proposed["id"], **confirmed(self.proposed)
        )
        assert accepted.status_code == 201, accepted.data
        row, detail = self._pair(self.scenario.sender)
        self._assert_projection(row, detail, offers=("latest_offer", "accepted_offer"))
        assert row["deal_id"] == accepted.data["id"]
        assert row["accepted_offer"]["id"] == self.proposed["id"]
        assert "terms_snapshot" in detail["accepted_offer"]
        # About three quarters of a row was snapshots nobody read.
        assert len(json.dumps(row)) < 0.5 * len(json.dumps(detail))

    def test_the_trimmed_list_costs_no_extra_queries(self):
        client = client_for(self.scenario.sender)
        with CaptureQueriesContext(connection) as trimmed:
            assert client.get(reverse("matches-list")).status_code == 200
        with (
            mock.patch("apps.matching.views.MatchListSerializer", MatchSerializer),
            CaptureQueriesContext(connection) as full,
        ):
            assert client.get(reverse("matches-list")).status_code == 200
        assert len(trimmed) <= len(full)
        assert len(trimmed) <= 4

    def test_every_match_appears_once_in_order_without_distinct(self):
        # The list dropped a redundant DISTINCT that cost ~65 ms of planning.
        # Every join is single-valued, so no row can repeat; pinned here for
        # the role filters and the unfiltered sender-or-traveler union.
        for _ in range(2):
            self.scenario.delivery_request = copy_request(self.scenario.delivery_request)
            propose(self.scenario)
        expected = list(
            Match.objects.order_by("-created_at", "-pk").values_list("pk", flat=True)
        )
        assert len(expected) == 3
        for user, query in (
            (self.scenario.sender, ""),
            (self.scenario.sender, "?role=sender"),
            (self.scenario.traveler, ""),
            (self.scenario.traveler, "?role=traveler"),
        ):
            client = client_for(user)
            with CaptureQueriesContext(connection) as queries:
                listed = client.get(reverse("matches-list") + query)
            assert [row["id"] for row in listed.data] == expected, query
            assert listed["X-Total-Count"] == "3"
            assert not any("DISTINCT" in q["sql"] for q in queries.captured_queries)
            paged = [
                client.get(reverse("matches-list") + (query or "?") + f"&page={page}&page_size=1")
                .data[0]["id"]
                for page in (1, 2, 3)
            ]
            assert paged == expected
        assert client_for(self.scenario.sender).get(
            reverse("matches-list") + "?role=traveler"
        ).data == []
