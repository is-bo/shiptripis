"""L13A: reviews, reports and moderation (spec 18).

One world: the discovery fixture's traveler (Yacine) carries parcels for the
sender (Samira) and is rated on each delivery. `rate()` makes one completed
delivery per rating, so every rating sits on its own deal exactly as in
production.
"""

from __future__ import annotations

import json
from datetime import timedelta

from django.db import IntegrityError, connection, transaction
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.admin_panel.models import AdminAuditLog
from apps.admin_panel.permissions import ROLE_PERMISSIONS, AdminRole, assign_admin_roles
from apps.deals.models import Deal
from apps.discovery.models import PublicProfile
from apps.discovery.tests.support import (
    STATIC_STORES,
    DiscoveryWorld,
    activate_marketplace,
    client_for,
)
from apps.discovery.tests.test_privacy import FORBIDDEN_KEYS, _keys
from apps.matching.find_travelers import TRUST_AS_TRAVELER, trust_signals
from apps.matching.tests.test_v1_matching import _user
from apps.matching.v1_services import accept_offer
from apps.parcels.models import DeliveryRequest, ParcelRequest
from apps.ratings.models import Rating, RatingModeration, RatingReport
from apps.ratings.moderation import (
    ACTION_DISMISS,
    ACTION_HIDE_COMMENT,
    ACTION_LIFT,
    ACTION_REMOVE,
    ModerationError,
    decide,
)
from apps.ratings.public import SIDE_TRAVELER, countable


class ReviewsWorld(DiscoveryWorld):
    def build_reviews_world(self):
        self.build_discovery_world()
        self.traveler_profile = self.opt_in(self.traveler, (self.algiers, self.jijel))
        self.staff = User.objects.create_user(
            username="trust-l13a@example.com",
            email="trust-l13a@example.com",
            password="Sup3rStrongPass!",
            is_staff=True,
        )
        assign_admin_roles(self.staff, [AdminRole.TRUST])

    def completed_deal(self) -> Deal:
        journey, flight, drive = self._journey(self.traveler, origin=self.cdg)
        parcel = self._request(self.paris, self.jijel, title="History")
        offer = self.propose(
            delivery_request=parcel,
            journey=journey,
            start_leg_id=flight.pk,
            end_leg_id=drive.pk,
        )
        deal = accept_offer(pending_offer=offer, actor=self.traveler).deal
        # The lifecycle that completes a Deal has its own suite.
        Deal.objects.filter(pk=deal.pk).update(status=Deal.Status.COMPLETED)
        deal.refresh_from_db()
        return deal

    def rate(
        self,
        score: int = 4,
        *,
        comment: str = "Careful and on time",
        by: str = Rating.RaterRole.SENDER,
        revealed: bool = True,
        deal: Deal | None = None,
        tags=(),
    ) -> Rating:
        deal = deal or self.completed_deal()
        window = timezone.now() + (timedelta(days=-1) if revealed else timedelta(days=7))
        rater, ratee = (
            (deal.sender, deal.traveler)
            if by == Rating.RaterRole.SENDER
            else (deal.traveler, deal.sender)
        )
        return Rating.objects.create(
            deal=deal,
            rater=rater,
            ratee=ratee,
            rater_role=by,
            score=score,
            tags=list(tags),
            comment=comment,
            review_window_ends_at=window,
        )

    def moderate(self, rating, action, reason="Checked against the delivery"):
        return decide(rating_id=rating.pk, actor=self.staff, action=action, reason=reason)

    def person_reviews(self, viewer=None, user=None, **query):
        user = user or self.traveler
        return client_for(viewer or self.other).get(
            reverse("discovery-person-reviews", args=(user.public_profile.public_id,)),
            query,
        )

    def trip_reviews(self, viewer=None, journey=None, **query):
        journey = journey or self.journey
        return client_for(viewer or self.other).get(
            reverse("discovery-trip-reviews", args=(journey.pk,)), query
        )

    def report(self, rating, viewer=None, **body):
        body.setdefault("reason", RatingReport.Reason.OFFENSIVE)
        return client_for(viewer or self.other).post(
            reverse("ratings-report", args=(rating.pk,)), body, format="json"
        )

    def finder(self):
        """A second sender, with their own open request and no history with Yacine."""

        finder = _user("finder-l13a@example.com")
        request = self._request(self.paris, self.jijel, title="Finder parcel")
        DeliveryRequest.objects.filter(pk=request.pk).update(sender=finder)
        request.refresh_from_db()
        return finder, request


# ---------------------------------------------------------------------------
# The one rule
# ---------------------------------------------------------------------------


class CountableTests(ReviewsWorld, TestCase):
    def setUp(self):
        self.build_reviews_world()

    def ids(self):
        return set(
            countable(Rating.objects.filter(ratee=self.traveler), at=timezone.now())
            .values_list("pk", flat=True)
        )

    def test_blind_ratings_do_not_count_until_revealed(self):
        blind = self.rate(revealed=False)
        self.assertEqual(self.ids(), set())
        # The other side rating reveals both, exactly as the API does.
        self.rate(by=Rating.RaterRole.TRAVELER, revealed=False, deal=blind.deal)
        self.assertEqual(self.ids(), {blind.pk})

    def test_a_removed_rating_does_not_count_and_a_hidden_comment_does(self):
        hidden, removed, kept = self.rate(5), self.rate(1), self.rate(4)
        self.moderate(hidden, ACTION_HIDE_COMMENT)
        self.moderate(removed, ACTION_REMOVE)
        self.assertEqual(self.ids(), {hidden.pk, kept.pk})

    def test_trust_signals_follow_a_removal_and_its_reversal(self):
        good, bad = self.rate(5), self.rate(1)

        def rating():
            return trust_signals(
                [self.traveler.pk], at=timezone.now(), side=TRUST_AS_TRAVELER
            )[self.traveler.pk]["rating"]

        self.assertEqual(rating(), {"state": "rated", "average": 3.0, "count": 2})
        self.moderate(bad, ACTION_HIDE_COMMENT)
        self.assertEqual(rating(), {"state": "rated", "average": 3.0, "count": 2})
        self.moderate(bad, ACTION_REMOVE)
        self.assertEqual(rating(), {"state": "rated", "average": 5.0, "count": 1})
        self.moderate(good, ACTION_REMOVE)
        self.assertEqual(rating(), {"state": "new", "average": None, "count": 0})
        self.moderate(bad, ACTION_LIFT)
        self.assertEqual(rating(), {"state": "rated", "average": 1.0, "count": 1})

    def test_trust_signals_cost_the_same_with_moderated_ratings(self):
        self.rate(5)

        def queries():
            with CaptureQueriesContext(connection) as captured:
                trust_signals([self.traveler.pk], at=timezone.now(), side=None)
            return len(captured.captured_queries)

        before = queries()
        self.moderate(self.rate(1), ACTION_REMOVE)
        self.assertEqual(queries(), before)

    def test_the_review_side_and_the_trust_side_are_the_same_word(self):
        self.assertEqual(SIDE_TRAVELER, TRUST_AS_TRAVELER)

    def test_every_card_reads_the_countable_number(self):
        self.rate(5)
        self.moderate(self.rate(1), ACTION_REMOVE)
        trips = client_for(self.other).get(reverse("discovery-trips")).data["results"]
        self.assertEqual({card["traveler"]["rating"]["count"] for card in trips}, {1})
        profile = self.person_reviews().data["rating"]
        self.assertEqual(profile, {"state": "rated", "average": 5.0, "count": 1})


# ---------------------------------------------------------------------------
# Public reviews
# ---------------------------------------------------------------------------


class PersonReviewsTests(ReviewsWorld, TestCase):
    def setUp(self):
        self.build_reviews_world()

    def test_a_review_shows_exactly_the_public_fields(self):
        rating = self.rate(4, tags=())
        payload = self.person_reviews().data
        self.assertEqual(payload["state"], "results")
        self.assertEqual(payload["next_offset"], None)
        self.assertEqual(
            payload["results"],
            [
                {
                    "id": rating.pk,
                    "score": 4,
                    "tags": [],
                    "comment": "Careful and on time",
                    "comment_removed": False,
                    "written_by": "sender",
                    "month": rating.created_at.strftime("%Y-%m"),
                    "my_report": None,
                }
            ],
        )

    def test_both_sides_newest_first_and_never_a_blind_one(self):
        as_traveler = self.rate(5)
        as_sender = self.rate(3, by=Rating.RaterRole.TRAVELER, deal=self.completed_deal())
        # The traveler's sender-side ratings are on Samira; give Yacine one as a sender.
        Rating.objects.filter(pk=as_sender.pk).update(ratee=self.traveler, rater=self.sender)
        self.rate(1, revealed=False)
        results = self.person_reviews().data["results"]
        self.assertEqual([row["id"] for row in results], [as_sender.pk, as_traveler.pk])
        self.assertEqual([row["written_by"] for row in results], ["traveler", "sender"])

    def test_a_hidden_comment_reads_as_removed_and_a_removed_rating_is_gone(self):
        hidden, removed = self.rate(5, comment="Call me on 0555"), self.rate(1)
        self.moderate(hidden, ACTION_HIDE_COMMENT)
        self.moderate(removed, ACTION_REMOVE)
        results = self.person_reviews().data["results"]
        self.assertEqual([row["id"] for row in results], [hidden.pk])
        self.assertEqual(results[0]["comment"], None)
        self.assertTrue(results[0]["comment_removed"])
        self.assertEqual(results[0]["score"], 5)
        self.assertNotIn("0555", json.dumps(self.person_reviews().data))

    def test_paging(self):
        rows = [self.rate(score) for score in (1, 2, 3)]
        first = self.person_reviews(limit=2).data
        self.assertEqual([r["id"] for r in first["results"]], [rows[2].pk, rows[1].pk])
        self.assertEqual(first["next_offset"], 2)
        second = self.person_reviews(limit=2, offset=2).data
        self.assertEqual([r["id"] for r in second["results"]], [rows[0].pk])
        self.assertIsNone(second["next_offset"])

    def test_no_reviews_is_the_empty_state(self):
        payload = self.person_reviews().data
        self.assertEqual(payload["state"], "empty")
        self.assertEqual(payload["rating"], {"state": "new", "average": None, "count": 0})

    def test_switched_off_profiles_answer_disabled(self):
        self.rate()
        activate_marketplace({"discovery": {"profiles_enabled": False}})
        response = self.person_reviews()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data,
            {"state": "disabled", "results": [], "next_offset": None, "rating": None},
        )

    def test_a_hidden_or_turned_off_profile_is_not_found(self):
        public_id = self.traveler_profile.public_id
        PublicProfile.objects.filter(pk=self.traveler_profile.pk).update(
            hidden_at=timezone.now(), hidden_by=self.staff, hidden_reason="Scam reports"
        )
        response = client_for(self.other).get(
            reverse("discovery-person-reviews", args=(public_id,))
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data["code"], "profile_not_found")

    def test_my_report_says_received_then_reviewed(self):
        rating = self.rate()
        self.report(rating)
        self.assertEqual(self.person_reviews().data["results"][0]["my_report"], "received")
        self.assertIsNone(
            self.person_reviews(viewer=self.sender).data["results"][0]["my_report"]
        )
        self.moderate(rating, ACTION_DISMISS)
        self.assertEqual(self.person_reviews().data["results"][0]["my_report"], "reviewed")


class TripReviewsTests(ReviewsWorld, TestCase):
    def setUp(self):
        self.build_reviews_world()
        self.as_traveler = self.rate(5)
        # Written by the traveler about the sender: never on a trip's reviews.
        self.rate(2, by=Rating.RaterRole.TRAVELER, deal=self.as_traveler.deal)

    def ids(self, response):
        self.assertEqual(response.status_code, 200, response.data)
        return [row["id"] for row in response.data["results"]]

    def test_a_listed_trip_shows_the_owners_ratings_as_a_traveler(self):
        self.assertEqual(self.ids(self.trip_reviews()), [self.as_traveler.pk])
        self.assertEqual(
            self.trip_reviews().data["rating"], {"state": "rated", "average": 5.0, "count": 1}
        )

    def test_an_unknown_or_unlisted_journey_is_not_found(self):
        response = client_for(self.other).get(
            reverse("discovery-trip-reviews", args=(999_999,))
        )
        self.assertEqual((response.status_code, response.data["code"]), (404, "trip_not_found"))
        unlisted = self.unproven_flight_journey(self.traveler)
        self.assertEqual(self.trip_reviews(journey=unlisted).status_code, 404)

    def test_listings_off_closes_only_the_public_path(self):
        activate_marketplace({"discovery": {"listings_enabled": False}})
        self.assertEqual(self.trip_reviews().data["state"], "disabled")
        # The owner, and a sender who shares a match with the owner, still read them.
        self.assertEqual(self.ids(self.trip_reviews(viewer=self.traveler)), [self.as_traveler.pk])
        self.assertEqual(self.ids(self.trip_reviews(viewer=self.sender)), [self.as_traveler.pk])

    def test_find_travelers_context_passes_whatever_the_switch(self):
        finder, request = self.finder()
        activate_marketplace({"discovery": {"listings_enabled": False}})
        self.assertEqual(self.trip_reviews(viewer=finder).data["state"], "disabled")
        response = self.trip_reviews(viewer=finder, request=request.pk)
        self.assertEqual(self.ids(response), [self.as_traveler.pk])

    def test_every_failure_of_the_request_path_reads_as_an_unknown_journey(self):
        finder, request = self.finder()
        activate_marketplace({"discovery": {"listings_enabled": False}})
        unknown = client_for(finder).get(
            reverse("discovery-trip-reviews", args=(999_999,)), {"request": request.pk}
        )
        others_request = self.trip_reviews(viewer=finder, request=self.request.pk)
        closed = DeliveryRequest.objects.filter(pk=request.pk)
        closed.update(status=ParcelRequest.Status.CANCELLED)
        not_open = self.trip_reviews(viewer=finder, request=request.pk)
        closed.update(status=ParcelRequest.Status.OPEN)
        elsewhere = self.drive_journey(self.traveler)  # Algiers to Jijel: not from Paris
        incompatible = self.trip_reviews(viewer=finder, journey=elsewhere, request=request.pk)
        answers = [
            (response.status_code, response.data)
            for response in (unknown, others_request, not_open, incompatible)
        ]
        self.assertEqual(
            answers,
            [(404, {"code": "trip_not_found", "detail": "This trip is not available."})] * 4,
        )


# ---------------------------------------------------------------------------
# Privacy
# ---------------------------------------------------------------------------


class ReviewsPrivacyTests(ReviewsWorld, TestCase):
    def setUp(self):
        self.build_reviews_world()
        self.sender.full_name = "Samira Zekkouriqa"
        self.sender.email = "zekk.private@example.com"
        self.sender.save(update_fields=["full_name", "email"])
        self.visible = self.rate(4, comment="Kind and quick")
        self.blind = self.rate(1, comment="Blind words", revealed=False)
        self.removed = self.rate(2, comment="Removed words")
        self.moderate(self.removed, ACTION_REMOVE)

    def assertPublic(self, payload):
        text = json.dumps(payload, default=str)
        self.assertIn("Kind and quick", text)
        for secret in (
            "Zekkouriqa",
            "Samira",
            "zekk.private@example.com",
            "Blind words",
            "Removed words",
            "WSL-",
            str(self.visible.deal_id),
        ):
            self.assertNotIn(secret, text)
        forbidden = FORBIDDEN_KEYS | {
            "deal_id",
            "deal",
            "rater",
            "rater_id",
            "ratee",
            "ratee_id",
            "reporter",
            "author",
            "name",
        }
        self.assertEqual(_keys(payload, set()) & forbidden, set())
        ids = [row["id"] for row in payload["results"]]
        self.assertEqual(ids, [self.visible.pk])

    def test_the_person_reviews_are_public_only(self):
        self.assertPublic(self.person_reviews().data)

    def test_the_trip_reviews_are_public_only(self):
        self.assertPublic(self.trip_reviews().data)


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


class ReportTests(ReviewsWorld, TestCase):
    def setUp(self):
        self.build_reviews_world()
        self.rating = self.rate()

    def test_a_report_is_received_once_then_reviewed(self):
        first = self.report(self.rating, note="  Insults  ")
        self.assertEqual(first.status_code, 201)
        self.assertEqual(first.data["state"], "received")
        report = RatingReport.objects.get()
        self.assertEqual((report.reporter, report.note, report.status), (self.other, "Insults", "open"))

        second = self.report(self.rating, reason=RatingReport.Reason.UNTRUE)
        self.assertEqual((second.status_code, second.data["state"]), (200, "received"))
        self.assertEqual(RatingReport.objects.get().reason, RatingReport.Reason.OFFENSIVE)

        self.moderate(self.rating, ACTION_HIDE_COMMENT)
        third = self.report(self.rating)
        self.assertEqual((third.status_code, third.data["state"]), (200, "reviewed"))

    def test_the_database_holds_one_report_per_reporter(self):
        RatingReport.objects.create(rating=self.rating, reporter=self.other, reason="other")
        with self.assertRaises(IntegrityError), transaction.atomic():
            RatingReport.objects.create(rating=self.rating, reporter=self.other, reason="untrue")

    def test_a_blind_removed_or_unknown_review_is_not_found(self):
        blind = self.rate(revealed=False)
        removed = self.rate()
        self.moderate(removed, ACTION_REMOVE)
        for rating_id in (blind.pk, removed.pk, 999_999):
            with self.subTest(rating_id):
                response = client_for(self.other).post(
                    reverse("ratings-report", args=(rating_id,)),
                    {"reason": "offensive"},
                    format="json",
                )
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.data["code"], "review_not_found")
        self.assertFalse(RatingReport.objects.exists())

    def test_a_viewer_who_cannot_read_the_review_cannot_report_it(self):
        stranger = _user("stranger-l13a@example.com")
        PublicProfile.objects.filter(pk=self.traveler_profile.pk).update(is_discoverable=False)
        activate_marketplace({"discovery": {"listings_enabled": False}})
        self.assertEqual(self.report(self.rating, viewer=stranger).status_code, 404)
        # A sender who shares a match with the traveler still can.
        self.assertEqual(self.report(self.rating, viewer=self.sender).status_code, 409)

    def test_the_author_cannot_report_their_own_review(self):
        response = self.report(self.rating, viewer=self.sender)
        self.assertEqual((response.status_code, response.data["code"]), (409, "own_review"))

    def test_the_rated_person_may_report_from_my_ratings(self):
        self.assertEqual(self.report(self.rating, viewer=self.traveler).status_code, 201)
        removed = self.rate()
        self.moderate(removed, ACTION_REMOVE)
        response = self.report(removed, viewer=self.traveler)
        self.assertEqual((response.status_code, response.data["code"]), (409, "review_removed"))
        blind = self.rate(revealed=False)
        self.assertEqual(self.report(blind, viewer=self.traveler).status_code, 404)

    def test_find_travelers_context_lets_a_sender_report_while_listings_are_off(self):
        finder, request = self.finder()
        PublicProfile.objects.filter(pk=self.traveler_profile.pk).update(is_discoverable=False)
        activate_marketplace({"discovery": {"listings_enabled": False}})
        self.assertEqual(self.report(self.rating, viewer=finder).status_code, 404)
        response = self.report(
            self.rating, viewer=finder, journey=self.journey.pk, request=request.pk
        )
        self.assertEqual(response.status_code, 201)

    def test_journey_and_request_come_together(self):
        response = self.report(self.rating, journey=self.journey.pk)
        self.assertEqual(response.status_code, 400)

    def test_an_unknown_reason_is_refused(self):
        self.assertEqual(self.report(self.rating, reason="spam").status_code, 400)


class MyRatingsTests(ReviewsWorld, TestCase):
    def setUp(self):
        self.build_reviews_world()

    def rows(self):
        response = client_for(self.traveler).get(reverse("ratings-mine"))
        self.assertEqual(response.status_code, 200)
        return {row["id"]: row for row in response.data}

    def test_each_row_carries_the_decision_and_my_report(self):
        plain, hidden, removed = self.rate(5), self.rate(4), self.rate(1)
        self.moderate(hidden, ACTION_HIDE_COMMENT)
        self.moderate(removed, ACTION_REMOVE)
        self.report(plain, viewer=self.traveler)
        rows = self.rows()
        self.assertEqual(
            {pk: (row["moderation"], row["my_report"]) for pk, row in rows.items()},
            {
                plain.pk: (None, "received"),
                hidden.pk: ("comment_hidden", None),
                removed.pk: ("removed", None),
            },
        )
        # The rated person keeps reading their own rating as written.
        self.assertEqual(rows[hidden.pk]["comment"], "Careful and on time")

    def test_the_query_count_is_flat(self):
        self.rate(5)

        def queries():
            client = client_for(self.traveler)
            with CaptureQueriesContext(connection) as captured:
                client.get(reverse("ratings-mine"))
            return len(captured.captured_queries)

        at_one = queries()
        for _ in range(3):
            self.moderate(self.rate(2), ACTION_REMOVE)
        self.assertEqual(queries(), at_one)


# ---------------------------------------------------------------------------
# Staff decisions
# ---------------------------------------------------------------------------


class DecisionTests(ReviewsWorld, TestCase):
    def setUp(self):
        self.build_reviews_world()
        self.rating = self.rate()
        self.report(self.rating)
        self.report(self.rating, viewer=_user("second-l13a@example.com"))

    def statuses(self):
        return sorted(RatingReport.objects.values_list("status", flat=True))

    def audit(self, action):
        return AdminAuditLog.objects.get(action=action, target_id=str(self.rating.pk))

    def test_dismiss_closes_the_reports_and_changes_nothing_else(self):
        decision = self.moderate(self.rating, ACTION_DISMISS, reason="Fair criticism")
        self.assertEqual(decision.reports_closed, 2)
        self.assertEqual(self.statuses(), ["dismissed", "dismissed"])
        self.assertFalse(RatingModeration.objects.exists())
        audit = self.audit("rating.reports_dismissed")
        self.assertEqual(audit.actor, self.staff)
        self.assertEqual(audit.reason, "Fair criticism")
        self.assertEqual(audit.before, {"moderation": None, "open_reports": 2})
        self.assertEqual(audit.after, {"moderation": None, "open_reports": 0})
        self.assertTrue(audit.reference.startswith("WSL-"))
        report = RatingReport.objects.first()
        self.assertEqual((report.decided_by, report.decision_reason), (self.staff, "Fair criticism"))

    def test_hide_the_comment_then_lift_it(self):
        self.moderate(self.rating, ACTION_HIDE_COMMENT)
        self.assertEqual(self.statuses(), ["actioned", "actioned"])
        moderation = RatingModeration.objects.get(rating=self.rating)
        self.assertEqual((moderation.state, moderation.decided_by), ("comment_hidden", self.staff))
        self.assertEqual(
            self.audit("rating.comment_hidden").after,
            {"moderation": "comment_hidden", "open_reports": 0},
        )

        self.moderate(self.rating, ACTION_LIFT, reason="Second look")
        self.assertFalse(RatingModeration.objects.exists())
        self.assertEqual(
            self.audit("rating.moderation_lifted").before,
            {"moderation": "comment_hidden", "open_reports": 0},
        )
        # The rating row itself was never edited.
        self.rating.refresh_from_db()
        self.assertEqual(self.rating.comment, "Careful and on time")

    def test_remove_then_soften_to_a_hidden_comment_then_lift(self):
        self.moderate(self.rating, ACTION_REMOVE)
        self.assertEqual(RatingModeration.objects.get().state, "removed")
        self.moderate(self.rating, ACTION_HIDE_COMMENT)
        self.assertEqual(RatingModeration.objects.get().state, "comment_hidden")
        self.assertEqual(
            self.audit("rating.comment_hidden").before,
            {"moderation": "removed", "open_reports": 0},
        )
        self.moderate(self.rating, ACTION_LIFT)
        self.assertFalse(RatingModeration.objects.exists())
        self.assertEqual(AdminAuditLog.objects.filter(target_type="ratings.rating").count(), 3)

    def test_lifting_dismisses_reports_that_arrived_after_the_decision(self):
        self.moderate(self.rating, ACTION_REMOVE)
        late = RatingReport.objects.create(
            rating=self.rating, reporter=_user("late-l13a@example.com"), reason="untrue"
        )
        self.moderate(self.rating, ACTION_LIFT)
        late.refresh_from_db()
        self.assertEqual(late.status, "dismissed")

    def test_a_decision_that_changes_nothing_is_refused_and_not_audited(self):
        self.moderate(self.rating, ACTION_HIDE_COMMENT)
        for action in (ACTION_DISMISS, ACTION_HIDE_COMMENT):
            with self.subTest(action), self.assertRaises(ModerationError) as caught:
                self.moderate(self.rating, action)
            self.assertEqual(caught.exception.code, "moderation_unchanged")
        other = self.rate()
        with self.assertRaises(ModerationError) as caught:
            self.moderate(other, ACTION_LIFT)
        self.assertEqual(caught.exception.code, "moderation_unchanged")
        self.assertEqual(AdminAuditLog.objects.filter(target_type="ratings.rating").count(), 1)

    def test_an_empty_comment_cannot_be_hidden(self):
        silent = self.rate(comment="")
        with self.assertRaises(ModerationError) as caught:
            self.moderate(silent, ACTION_HIDE_COMMENT)
        self.assertEqual(caught.exception.code, "rating_has_no_comment")

    def test_a_reason_is_required(self):
        with self.assertRaises(ModerationError) as caught:
            self.moderate(self.rating, ACTION_REMOVE, reason="   ")
        self.assertEqual(caught.exception.code, "reason_required")

    def test_only_a_moderator_may_decide(self):
        assign_admin_roles(self.staff, [AdminRole.OPS])
        with self.assertRaises(ModerationError) as caught:
            self.moderate(self.rating, ACTION_REMOVE)
        self.assertEqual(caught.exception.code, "permission_denied")
        self.assertFalse(RatingModeration.objects.exists())

    def test_the_capability_belongs_to_trust_and_super_admin_only(self):
        holders = {role for role, codes in ROLE_PERMISSIONS.items() if "moderate_ratings" in codes}
        self.assertEqual(holders, {AdminRole.TRUST, AdminRole.SUPER_ADMIN})
        self.assertTrue(self.staff.has_perm("admin_panel.moderate_ratings"))


# ---------------------------------------------------------------------------
# Console
# ---------------------------------------------------------------------------


@override_settings(STORAGES=STATIC_STORES)
class ConsoleTests(ReviewsWorld, TestCase):
    def setUp(self):
        self.build_reviews_world()
        self.rating = self.rate(comment="Rude words here")
        self.report(self.rating, note="He insulted me")
        self.report(self.rating, viewer=self.sender, reason="untrue")  # the author: refused
        self.quiet = self.rate(comment="Lovely")
        self.report(self.quiet, reason=RatingReport.Reason.UNRELATED)
        self.moderate(self.quiet, ACTION_DISMISS)
        self.client.force_login(self.staff)

    def test_the_queue_lists_open_reports_first_with_reasons(self):
        response = self.client.get(reverse("admin_console:reviews"))
        self.assertEqual(response.status_code, 200)
        rows = response.context["rows"]
        self.assertEqual(len(rows), 2)
        first = rows[0]["cells"]
        self.assertIn("Rude words here", first[0]["secondary"])
        self.assertEqual(first[3]["secondary"], "Offensive")
        self.assertEqual(first[5]["primary"], "1 open report")
        self.assertEqual(rows[1]["cells"][5]["primary"], "Reports dismissed")
        open_only = self.client.get(reverse("admin_console:reviews"), {"status": "open"})
        self.assertEqual(len(open_only.context["rows"]), 1)

    def test_the_review_page_shows_the_reporter_and_decides(self):
        url = reverse("admin_console:review-detail", args=(self.rating.pk,))
        page = self.client.get(url)
        self.assertContains(page, "He insulted me")
        self.assertContains(page, self.other.email)
        self.assertEqual(
            [decision["action"] for decision in page.context["decisions"]],
            [ACTION_DISMISS, ACTION_HIDE_COMMENT, ACTION_REMOVE],
        )
        refused = self.client.post(url, {"action": ACTION_REMOVE, "remove-reason": ""})
        self.assertEqual(refused.status_code, 200)
        self.assertFalse(RatingModeration.objects.exists())

        done = self.client.post(url, {"action": ACTION_REMOVE, "remove-reason": "Insults"})
        self.assertRedirects(done, url, fetch_redirect_response=False)
        self.assertEqual(RatingModeration.objects.get().state, "removed")
        after = self.client.get(url)
        self.assertEqual(
            [decision["action"] for decision in after.context["decisions"]],
            [ACTION_HIDE_COMMENT, ACTION_LIFT],
        )
        self.assertContains(after, "Rating removed")

    def test_the_overview_counts_reviews_waiting(self):
        response = self.client.get(reverse("admin_console:overview"))
        item = next(i for i in response.context["attention"] if i["title"] == "Reported reviews")
        self.assertEqual(item["count"], 1)
        self.assertTrue(item["url"].endswith("?status=open"))

    def test_staff_without_the_capability_cannot_open_the_pages(self):
        assign_admin_roles(self.staff, [AdminRole.OPS])
        for url in (
            reverse("admin_console:reviews"),
            reverse("admin_console:review-detail", args=(self.rating.pk,)),
        ):
            with self.subTest(url):
                self.assertEqual(self.client.get(url).status_code, 403)
        overview = self.client.get(reverse("admin_console:overview"))
        self.assertNotIn(
            "Reported reviews", [item["title"] for item in overview.context["attention"]]
        )

    def test_the_person_page_shows_the_countable_rating(self):
        self.moderate(self.rating, ACTION_REMOVE)
        response = self.client.get(reverse("admin_console:user-detail", args=(self.traveler.pk,)))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "1 counted rating, 1 removed by staff")


# ---------------------------------------------------------------------------
# Query counts
# ---------------------------------------------------------------------------


class ReviewsQueryCountTests(ReviewsWorld, TestCase):
    ROWS = 20

    def setUp(self):
        self.build_reviews_world()
        self.finder_user, self.finder_request = self.finder()

    def count(self, fetch) -> tuple[int, int]:
        fetch()  # warm the policy and settings reads
        with CaptureQueriesContext(connection) as captured:
            response = fetch()
        self.assertEqual(response.status_code, 200, response.data)
        return len(captured.captured_queries), len(response.data["results"])

    def grow(self):
        for index in range(self.ROWS - 1):
            rating = self.rate(index % 5 + 1)
            if index % 3 == 0:
                self.moderate(rating, ACTION_HIDE_COMMENT)
            if index % 4 == 0:
                self.report(rating)
        self.moderate(self.rate(1), ACTION_REMOVE)  # never listed

    def assertFlat(self, fetch, pinned):
        self.rate(5)
        at_one, rows = self.count(fetch)
        self.assertEqual(rows, 1)
        self.grow()
        at_many, rows = self.count(fetch)
        self.assertEqual(rows, self.ROWS)
        self.assertEqual(at_one, at_many)
        self.assertEqual(at_one, pinned)

    def test_person_reviews(self):
        self.assertFlat(lambda: self.person_reviews(limit=self.ROWS), pinned=7)

    def test_trip_reviews(self):
        self.assertFlat(lambda: self.trip_reviews(limit=self.ROWS), pinned=7)

    def test_trip_reviews_from_find_travelers(self):
        activate_marketplace({"discovery": {"listings_enabled": False}})
        self.assertFlat(
            lambda: self.trip_reviews(
                viewer=self.finder_user, request=self.finder_request.pk, limit=self.ROWS
            ),
            # The six more are the matching engine's own single-pair verdict.
            pinned=13,
        )
