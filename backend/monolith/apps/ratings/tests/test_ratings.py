"""Ratings: the blind window, immutability, deal-derived identity and the reveal.

Four things are being defended here:

**Who may rate is derived from the Deal, never from the request.** The sender
rates the traveler and the traveler rates the sender; the role, the rater and
the ratee are read directly off the locked Deal row. A third party, the parcel
recipient and caller-supplied ratee parameters cannot alter who is rating whom.

**A rating is immutable once written.** A rating cannot be edited or deleted;
only the internal `revealed_at` timestamp is allowed to change. This ensures
that a party cannot alter their rating after seeing what the other side submitted.

**Visibility is computed, not merely stored.** The `is_revealed` predicate governs
what a viewer may see: a rater sees their own rating immediately, but the counterparty
cannot see it until either both sides submit or the frozen review window expires.

**The reveal is durable and idempotent.** When the review window closes, the
durable `rating_reveal` job stamps `revealed_at` safely and idempotently without
re-disclosing ratings or duplicating timeline events.
"""

from __future__ import annotations

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.phase4_policy import phase4_policy
from apps.deals.models import DealEvent
from apps.deals.tests.phase4_factories import (
    delivered_scenario,
    freeze_at,
    fund_scenario,
    record_recipient,
)
from apps.finance.jobs import run_due_jobs
from apps.finance.models import ScheduledJob
from apps.ratings.models import Rating
from apps.ratings.services import (
    NotAuthorized,
    RatingError,
    is_revealed,
    rating_state,
    reveal_ratings_for_deal,
    submit_rating,
)


def client_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


# --- window and state gates ---------------------------------------------------


class RatingWindowTests(TestCase):
    def test_party_cannot_rate_before_delivery_confirmation(self):
        scenario = fund_scenario(self.client, prefix="rw1")
        record_recipient(scenario)
        with self.assertRaises(RatingError) as caught:
            submit_rating(
                deal_id=scenario.deal.pk,
                actor_id=scenario.sender.pk,
                score=5,
            )
        assert caught.exception.code == "rating_not_available"

    def test_party_may_rate_inside_the_review_window(self):
        scenario = delivered_scenario(self.client, prefix="rw2")
        with freeze_at(scenario.deal.rating_window_ends_at - timedelta(seconds=1)):
            rating = submit_rating(
                deal_id=scenario.deal.pk,
                actor_id=scenario.sender.pk,
                score=5,
            )
        assert rating.pk is not None

    def test_party_cannot_rate_after_the_review_window_has_closed(self):
        scenario = delivered_scenario(self.client, prefix="rw3")
        with freeze_at(scenario.deal.rating_window_ends_at + timedelta(seconds=1)):
            with self.assertRaises(RatingError) as caught:
                submit_rating(
                    deal_id=scenario.deal.pk,
                    actor_id=scenario.sender.pk,
                    score=5,
                )
        assert caught.exception.code == "rating_window_closed"
        assert not Rating.objects.filter(deal_id=scenario.deal.pk).exists()


# --- authorization and identity -----------------------------------------------


class RatingAuthorizationAndIdentityTests(TestCase):
    def test_sender_rates_traveler_and_traveler_rates_sender_identities_are_derived(
        self,
    ):
        """The rater and ratee identities and roles are derived from the locked Deal.

        Nothing in the caller parameters can reassign who rates whom.
        """
        scenario = delivered_scenario(self.client, prefix="raid1")

        r1 = submit_rating(
            deal_id=scenario.deal.pk,
            actor_id=scenario.sender.pk,
            score=5,
        )
        assert r1.rater_role == Rating.RaterRole.SENDER
        assert r1.rater_id == scenario.sender.pk
        assert r1.ratee_id == scenario.traveler.pk

        r2 = submit_rating(
            deal_id=scenario.deal.pk,
            actor_id=scenario.traveler.pk,
            score=4,
        )
        assert r2.rater_role == Rating.RaterRole.TRAVELER
        assert r2.rater_id == scenario.traveler.pk
        assert r2.ratee_id == scenario.sender.pk

    def test_an_outsider_is_refused(self):
        # The parcel recipient has no user account on the platform, so only
        # the authenticated sender and traveler are authorized parties.
        scenario = delivered_scenario(self.client, prefix="raid2")
        with self.assertRaises(NotAuthorized):
            submit_rating(
                deal_id=scenario.deal.pk,
                actor_id=scenario.outsider.pk,
                score=5,
            )

    def test_a_second_rating_from_the_same_side_is_refused(self):
        scenario = delivered_scenario(self.client, prefix="raid3")
        submit_rating(
            deal_id=scenario.deal.pk,
            actor_id=scenario.sender.pk,
            score=5,
        )
        with self.assertRaises(RatingError) as caught:
            submit_rating(
                deal_id=scenario.deal.pk,
                actor_id=scenario.sender.pk,
                score=4,
            )
        assert caught.exception.code == "rating_already_submitted"


# --- validation ---------------------------------------------------------------


class RatingValidationTests(TestCase):
    def test_score_must_be_an_integer_between_one_and_five(self):
        scenario = delivered_scenario(self.client, prefix="rv1")
        for invalid_score in (0, 6, -1, True, "5"):
            with self.assertRaises(RatingError) as caught:
                submit_rating(
                    deal_id=scenario.deal.pk,
                    actor_id=scenario.sender.pk,
                    score=invalid_score,
                )
            assert caught.exception.code == "rating_score_invalid"

    def test_unknown_tag_is_refused_and_valid_tag_is_accepted(self):
        scenario = delivered_scenario(self.client, prefix="rv2")
        with self.assertRaises(RatingError) as caught:
            submit_rating(
                deal_id=scenario.deal.pk,
                actor_id=scenario.sender.pk,
                score=5,
                tags=["unknown_rating_tag_xyz"],
            )
        assert caught.exception.code == "rating_tag_invalid"

        policy = phase4_policy().ratings
        assert len(policy.allowed_tags) > 0
        valid_tag = policy.allowed_tags[0]
        rating = submit_rating(
            deal_id=scenario.deal.pk,
            actor_id=scenario.sender.pk,
            score=5,
            tags=[valid_tag],
        )
        assert rating.tags == [valid_tag]


# --- blind reveal -------------------------------------------------------------


class RatingBlindRevealTests(TestCase):
    def test_blind_window_one_side_submitted_versus_both_sides_submitted(self):
        """After only one side submits: the rater sees their own rating, the
        counterparty does not. After both submit: both are revealed immediately,
        and a RATING_REVEALED event exists.
        """
        scenario = delivered_scenario(self.client, prefix="rbr1")
        deal = scenario.deal

        r1 = submit_rating(
            deal_id=deal.pk,
            actor_id=scenario.sender.pk,
            score=5,
            comment="Great traveler!",
        )
        assert not is_revealed(r1, deal=deal)
        assert r1.revealed_at is None

        # Sender sees their own submitted review.
        state_sender = rating_state(deal=deal, viewer_id=scenario.sender.pk)
        assert len(state_sender["ratings"]) == 1
        assert state_sender["ratings"][0]["score"] == 5
        assert state_sender["ratings"][0]["is_mine"] is True
        assert state_sender["submitted"] is True
        assert state_sender["counterparty_submitted"] is False

        # Traveler sees nothing yet, but knows the other party has submitted.
        state_traveler = rating_state(deal=deal, viewer_id=scenario.traveler.pk)
        assert len(state_traveler["ratings"]) == 0
        assert state_traveler["submitted"] is False
        assert state_traveler["counterparty_submitted"] is True
        assert state_traveler["can_rate"] is True

        # When the traveler submits, both ratings become revealed immediately.
        r2 = submit_rating(
            deal_id=deal.pk,
            actor_id=scenario.traveler.pk,
            score=4,
            comment="Smooth handover.",
        )
        r1.refresh_from_db()
        r2.refresh_from_db()
        assert is_revealed(r1, deal=deal) is True
        assert is_revealed(r2, deal=deal) is True
        assert r1.revealed_at is not None
        assert r2.revealed_at is not None
        assert DealEvent.objects.filter(
            deal=deal, kind=DealEvent.Kind.RATING_REVEALED
        ).exists()

        state_sender_after = rating_state(deal=deal, viewer_id=scenario.sender.pk)
        state_traveler_after = rating_state(deal=deal, viewer_id=scenario.traveler.pk)
        assert len(state_sender_after["ratings"]) == 2
        assert len(state_traveler_after["ratings"]) == 2
        assert state_sender_after["both_sides_submitted"] is True

    def test_single_submitted_rating_revealed_when_window_closes_without_reveal_job(
        self,
    ):
        """With only one rating submitted, advancing past the window reveals it
        via the predicate even before the durable reveal job has run.
        """
        scenario = delivered_scenario(self.client, prefix="rbr2")
        deal = scenario.deal

        r1 = submit_rating(
            deal_id=deal.pk,
            actor_id=scenario.sender.pk,
            score=5,
        )
        assert r1.revealed_at is None

        with freeze_at(deal.rating_window_ends_at + timedelta(seconds=1)):
            assert is_revealed(r1, deal=deal) is True
            state_traveler = rating_state(deal=deal, viewer_id=scenario.traveler.pk)
            assert len(state_traveler["ratings"]) == 1
            assert state_traveler["ratings"][0]["score"] == 5
            assert state_traveler["ratings"][0]["is_revealed"] is True

    def test_reveal_ratings_for_deal_is_idempotent(self):
        scenario = delivered_scenario(self.client, prefix="rbr3")
        deal = scenario.deal

        r1 = submit_rating(
            deal_id=deal.pk,
            actor_id=scenario.sender.pk,
            score=5,
        )

        with freeze_at(deal.rating_window_ends_at + timedelta(minutes=5)):
            outcome1 = reveal_ratings_for_deal(deal_id=deal.pk)
            assert outcome1 == "revealed=1"
            r1.refresh_from_db()
            revealed_at = r1.revealed_at
            assert revealed_at is not None
            assert (
                DealEvent.objects.filter(
                    deal=deal, kind=DealEvent.Kind.RATING_REVEALED
                ).count()
                == 1
            )

            outcome2 = reveal_ratings_for_deal(deal_id=deal.pk)
            assert outcome2 == "already_revealed"
            r1.refresh_from_db()
            assert r1.revealed_at == revealed_at
            assert (
                DealEvent.objects.filter(
                    deal=deal, kind=DealEvent.Kind.RATING_REVEALED
                ).count()
                == 1
            )


# --- durable scheduled jobs ---------------------------------------------------


class RatingDurableJobTests(TestCase):
    def test_rating_reveal_scheduled_job_executes_on_due_jobs(self):
        scenario = delivered_scenario(self.client, prefix="rdj1")
        deal = scenario.deal
        r1 = submit_rating(deal_id=deal.pk, actor_id=scenario.sender.pk, score=5)

        job = ScheduledJob.objects.get(
            kind=ScheduledJob.Kind.RATING_REVEAL, key=f"rating_reveal:{deal.pk}"
        )
        assert job.run_at == deal.rating_window_ends_at

        # Move the scheduled job into the past and advance the clock past window expiry.
        ScheduledJob.objects.filter(pk=job.pk).update(
            run_at=timezone.now() - timedelta(minutes=5)
        )
        with freeze_at(deal.rating_window_ends_at + timedelta(minutes=5)):
            run_due_jobs(limit=50)

        job.refresh_from_db()
        assert job.status == ScheduledJob.Status.SUCCEEDED
        r1.refresh_from_db()
        assert r1.revealed_at is not None


# --- immutability and timeline hygiene ----------------------------------------


class RatingImmutabilityAndTimelineTests(TestCase):
    def test_rating_is_immutable_and_cannot_be_deleted(self):
        scenario = delivered_scenario(self.client, prefix="rim1")
        rating = submit_rating(
            deal_id=scenario.deal.pk,
            actor_id=scenario.sender.pk,
            score=5,
            comment="Initial statement.",
        )

        rating.score = 1
        with self.assertRaises(ValidationError):
            rating.save()

        with self.assertRaises(ValidationError):
            rating.save(update_fields=["score"])

        with self.assertRaises(ValidationError):
            rating.delete()

        # Stamping revealed_at via explicit update_fields is permitted.
        rating.revealed_at = timezone.now()
        rating.save(update_fields=["revealed_at", "updated_at"])

    def test_deal_timeline_records_rating_submitted_without_leaking_score(self):
        scenario = delivered_scenario(self.client, prefix="rim2")
        rating = submit_rating(
            deal_id=scenario.deal.pk,
            actor_id=scenario.sender.pk,
            score=5,
        )

        event = DealEvent.objects.get(
            deal=scenario.deal, kind=DealEvent.Kind.RATING_SUBMITTED
        )
        assert event.payload["rater_role"] == Rating.RaterRole.SENDER
        assert event.payload["rating_id"] == rating.pk

        # Score must never appear anywhere in the deal event timeline payload.
        for deal_event in DealEvent.objects.filter(deal=scenario.deal):
            assert "score" not in deal_event.payload
            assert 5 not in deal_event.payload.values()


# --- API surface --------------------------------------------------------------


class RatingApiTests(TestCase):
    def test_ratings_api_endpoints_authentication_authorization_and_projection(
        self,
    ):
        scenario = delivered_scenario(self.client, prefix="rapi1")
        sender = client_for(scenario.sender)
        traveler = client_for(scenario.traveler)
        outsider = client_for(scenario.outsider)
        anon = APIClient()

        # Unauthenticated calls are rejected with 401.
        assert (
            anon.get(reverse("ratings-list", args=[scenario.deal.pk])).status_code
            == 401
        )
        assert (
            anon.post(
                reverse("ratings-submit", args=[scenario.deal.pk]), {"score": 5}
            ).status_code
            == 401
        )
        assert anon.get(reverse("ratings-mine")).status_code == 401

        # Outsider calls are rejected with 403.
        assert (
            outsider.get(
                reverse("ratings-list", args=[scenario.deal.pk])
            ).status_code
            in (403, 404)
        )
        assert (
            outsider.post(
                reverse("ratings-submit", args=[scenario.deal.pk]), {"score": 5}
            ).status_code
            in (403, 404)
        )

        # Sender submits rating with extra bogus identity fields in body;
        # the API ignores them and derives the correct rater and ratee from the deal.
        res = sender.post(
            reverse("ratings-submit", args=[scenario.deal.pk]),
            {
                "score": 5,
                "comment": "Great experience!",
                "tags": [],
                "ratee": 99999,
                "rater": 99999,
                "rater_role": "traveler",
            },
            format="json",
        )
        assert res.status_code == 201, res.data
        assert res.data["rater_role"] == "sender"
        assert res.data["rater_id"] == scenario.sender.pk
        assert res.data["ratee_id"] == scenario.traveler.pk

        # Sender reads deal rating state.
        list_res = sender.get(reverse("ratings-list", args=[scenario.deal.pk]))
        assert list_res.status_code == 200, list_res.data
        assert list_res.data["submitted"] is True

        # Traveler reads ratings-mine; the sender's review is still blind.
        mine_res = traveler.get(reverse("ratings-mine"))
        assert mine_res.status_code == 200
        assert len(mine_res.data) == 0

        # Traveler submits rating; both are now revealed.
        res2 = traveler.post(
            reverse("ratings-submit", args=[scenario.deal.pk]),
            {"score": 4, "comment": "Smooth delivery."},
            format="json",
        )
        assert res2.status_code == 201, res2.data

        # Traveler reads ratings-mine again; sender's review is now visible.
        mine_res2 = traveler.get(reverse("ratings-mine"))
        assert mine_res2.status_code == 200
        assert len(mine_res2.data) == 1
        assert mine_res2.data[0]["score"] == 5
