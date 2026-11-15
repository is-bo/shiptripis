"""L18A: the member's own rating comes from the server.

`GET /api/users/me/ratings/summary` answers `{state, average, count}`, the same
block the member's public profile card shows, computed by `rating_summaries`
over `countable`. The app used to average its own list and kept ratings staff
had removed; there is now one average in the product.
"""

from __future__ import annotations

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework.test import APIClient

from apps.discovery.tests.support import client_for
from apps.ratings.moderation import ACTION_HIDE_COMMENT, ACTION_LIFT, ACTION_REMOVE
from apps.ratings.models import Rating
from apps.ratings.tests.test_l13a_reviews import ReviewsWorld

URL = reverse("ratings-mine-summary")


class OwnRatingSummaryTests(ReviewsWorld, TestCase):
    def setUp(self):
        self.build_reviews_world()

    def mine(self, user=None) -> dict:
        response = client_for(user or self.traveler).get(URL)
        self.assertEqual(response.status_code, 200)
        return response.data

    def card(self) -> dict:
        return self.person_reviews().data["rating"]

    def test_sign_in_is_required(self):
        self.assertEqual(APIClient().get(URL).status_code, 401)

    def test_a_member_with_no_countable_rating_is_new(self):
        self.rate(5, revealed=False)
        self.assertEqual(self.mine(), {"state": "new", "average": None, "count": 0})
        self.assertEqual(self.mine(), self.card())

    def test_it_equals_the_public_card_before_and_after_a_staff_removal(self):
        good, bad = self.rate(5), self.rate(2)
        self.assertEqual(self.mine(), {"state": "rated", "average": 3.5, "count": 2})
        self.assertEqual(self.mine(), self.card())

        self.moderate(bad, ACTION_HIDE_COMMENT)
        self.assertEqual(self.mine(), {"state": "rated", "average": 3.5, "count": 2})
        self.assertEqual(self.mine(), self.card())

        self.moderate(bad, ACTION_REMOVE)
        self.assertEqual(self.mine(), {"state": "rated", "average": 5.0, "count": 1})
        self.assertEqual(self.mine(), self.card())

        self.moderate(bad, ACTION_LIFT)
        self.moderate(good, ACTION_REMOVE)
        self.assertEqual(self.mine(), {"state": "rated", "average": 2.0, "count": 1})
        self.assertEqual(self.mine(), self.card())

    def test_both_sides_count_as_on_the_profile_card(self):
        """The whole person: what they were rated as a sender counts too."""

        carried = self.rate(4)
        self.rate(2, by=Rating.RaterRole.TRAVELER)
        sender = carried.deal.sender
        self.assertEqual(self.mine(sender), {"state": "rated", "average": 2.0, "count": 1})
        self.assertEqual(self.mine(), {"state": "rated", "average": 4.0, "count": 1})

    def test_the_answer_is_one_query_whatever_the_history(self):
        def queries():
            client = client_for(self.traveler)
            with CaptureQueriesContext(connection) as captured:
                client.get(URL)
            return len(captured.captured_queries)

        self.assertEqual(queries(), 1)
        for score in (5, 3, 1):
            self.moderate(self.rate(score), ACTION_REMOVE)
        self.rate(4)
        self.assertEqual(queries(), 1)
