"""The legacy review deadline stays queryable on SQLite and PostgreSQL."""

from datetime import datetime, timedelta, timezone as datetime_timezone
from uuid import uuid4

from django.db.models import F
from django.test import TestCase
from rest_framework.test import APIClient

from apps.deals.models import Deal
from apps.deals.tests.phase4_factories import delivered_scenario, freeze_at
from apps.notifications.models import Notification
from apps.notifications.resolution import resolved_notifications
from apps.ratings.services import rating_state, submit_rating, with_review_deadline


class LegacyReviewDeadlineTests(TestCase):
    def setUp(self):
        self.scenario = delivered_scenario(APIClient(), prefix="j82")
        self.confirmed_at = datetime(2026, 9, 1, 12, tzinfo=datetime_timezone.utc)
        self.deal = self.scenario.deal

    def set_legacy_policy(self, policy):
        Deal.objects.filter(pk=self.deal.pk).update(
            delivery_confirmed_at=self.confirmed_at,
            rating_window_ends_at=None,
            lifecycle_policy=policy,
        )
        self.deal.refresh_from_db()

    def prompt(self, user):
        return Notification.objects.create(
            recipient=user,
            channel="rating.prompt",
            event_id=uuid4().hex,
            payload={"deal_id": self.deal.pk},
        )

    def test_default_legacy_deadline_and_notification_boundary(self):
        self.set_legacy_policy({})
        deadline = self.confirmed_at + timedelta(days=14)
        rows = with_review_deadline(Deal.objects.filter(pk=self.deal.pk))

        self.assertEqual(
            rows.annotate(computed_deadline=F("review_deadline"))
            .order_by("review_deadline")
            .get()
            .computed_deadline,
            deadline,
        )
        self.assertTrue(
            rows.filter(
                review_deadline__gt=deadline - timedelta(microseconds=1)
            ).exists()
        )
        self.assertFalse(rows.filter(review_deadline__gt=deadline).exists())
        self.assertFalse(
            rows.filter(
                review_deadline__gt=deadline + timedelta(microseconds=1)
            ).exists()
        )

        prompt = self.prompt(self.scenario.sender)
        required = Notification.objects.create(
            recipient=self.scenario.sender,
            channel="rating.required",
            event_id=uuid4().hex,
            payload={"deal_id": self.deal.pk},
        )
        for instant, expected_resolved in (
            (deadline - timedelta(microseconds=1), False),
            (deadline, True),
            (deadline + timedelta(microseconds=1), True),
        ):
            self.assertEqual(
                resolved_notifications(self.scenario.sender, at=instant)
                .get(pk=prompt.pk)
                .resolved,
                expected_resolved,
            )
            self.assertEqual(
                resolved_notifications(self.scenario.sender, at=instant)
                .get(pk=required.pk)
                .resolved,
                expected_resolved,
            )
        self.assertEqual(
            rating_state(
                deal=self.deal,
                viewer_id=self.scenario.sender.pk,
                at=deadline - timedelta(microseconds=1),
            )["state"],
            "available",
        )
        self.assertEqual(
            rating_state(
                deal=self.deal, viewer_id=self.scenario.sender.pk, at=deadline
            )["state"],
            "expired",
        )
        self.assertEqual(
            rating_state(
                deal=self.deal,
                viewer_id=self.scenario.sender.pk,
                at=deadline + timedelta(microseconds=1),
            )["state"],
            "expired",
        )

    def test_invalid_legacy_policy_values_keep_fourteen_day_fallback(self):
        deadline = self.confirmed_at + timedelta(days=14)
        for policy_value in ("604800", True, -1, 10_000_000_000):
            with self.subTest(policy_value=policy_value):
                self.set_legacy_policy({"rating_review_window_seconds": policy_value})
                self.assertEqual(
                    with_review_deadline(Deal.objects.filter(pk=self.deal.pk))
                    .annotate(computed_deadline=F("review_deadline"))
                    .get()
                    .computed_deadline,
                    deadline,
                )

    def test_frozen_per_deal_duration_and_already_rated_state(self):
        self.set_legacy_policy({"rating_review_window_seconds": 7 * 24 * 60 * 60})
        deadline = self.confirmed_at + timedelta(days=7)
        rows = with_review_deadline(Deal.objects.filter(pk=self.deal.pk))
        self.assertEqual(
            rows.annotate(computed_deadline=F("review_deadline"))
            .get()
            .computed_deadline,
            deadline,
        )

        sender_prompt = self.prompt(self.scenario.sender)
        traveler_prompt = self.prompt(self.scenario.traveler)
        before = deadline - timedelta(microseconds=1)
        self.assertFalse(
            resolved_notifications(self.scenario.sender, at=before)
            .get(pk=sender_prompt.pk)
            .resolved
        )
        with freeze_at(before):
            rating = submit_rating(
                deal_id=self.deal.pk, actor_id=self.scenario.sender.pk, score=5
            )
        self.assertEqual(rating.review_window_ends_at, deadline)
        self.assertTrue(
            resolved_notifications(self.scenario.sender, at=before)
            .get(pk=sender_prompt.pk)
            .resolved
        )
        self.assertFalse(
            resolved_notifications(self.scenario.traveler, at=before)
            .get(pk=traveler_prompt.pk)
            .resolved
        )
        self.deal.refresh_from_db()
        self.assertEqual(
            rating_state(
                deal=self.deal, viewer_id=self.scenario.traveler.pk, at=before
            )["ratings"],
            [],
        )
        self.assertEqual(
            len(
                rating_state(
                    deal=self.deal, viewer_id=self.scenario.traveler.pk, at=deadline
                )["ratings"]
            ),
            1,
        )
        self.assertTrue(
            resolved_notifications(self.scenario.traveler, at=deadline)
            .get(pk=traveler_prompt.pk)
            .resolved
        )
