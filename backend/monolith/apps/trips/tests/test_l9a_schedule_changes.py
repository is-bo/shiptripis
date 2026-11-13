"""L9A: a traveler changes the times of a published trip (spec 12).

Small changes apply at once and tell the senders. A change that moves a
parcel's arrival past its deadline, or more than the threshold away from what
its sender agreed to, waits for that sender. Declining keeps the old times and
makes the sender's cancellation the traveler's. Nothing here writes a deal's
status or its money.
"""

from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.forms.models import model_to_dict
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.financial_locks import lock_deal_lifecycle
from apps.deals.cancellation import cancel_funded_deal, quote_cancellation
from apps.deals.lifecycle import apply_pickup_confirmed
from apps.deals.models import Deal, DealEvent
from apps.discovery.tests.support import activate_marketplace
from apps.finance.jobs import PermanentJobError
from apps.finance.models import ScheduledJob
from apps.matching.models import Offer
from apps.matching.v1_services import V1OfferError, accept_offer, create_sender_offer
from apps.notifications.models import Notification
from apps.notifications.resolution import resolved_notifications
from apps.parcels import tracking
from apps.parcels.models import DeliveryRequest
from apps.trips.models import (
    Journey,
    JourneyLeg,
    JourneyLegProgress,
    JourneyLegProof,
    JourneyScheduleChange,
    JourneyScheduleChangeConsent,
)
from apps.trips.progress import handle_leg_reminder
from apps.trips.schedule_changes import handle_settle_job, settle

from .sea_world import DRIVE, FLIGHT
from .test_l5a_progress import ProgressWorld, client_for

Change = JourneyScheduleChange
Consent = JourneyScheduleChangeConsent
THRESHOLD = timedelta(minutes=360)


def iso(value) -> str:
    return value.isoformat()


def frozen(deal: Deal) -> dict:
    """What a schedule change must never touch on a deal."""

    deal.refresh_from_db()
    row = model_to_dict(deal)
    return {
        "status": row["status"],
        "arrival_snapshot": row["arrival_snapshot"],
        "funded_scheduled_arrival_floor_at": deal.funded_scheduled_arrival_floor_at,
        "agreed_pickup_at": deal.agreed_pickup_at,
        "funded_at": deal.funded_at,
    }


class ScheduleWorld(ProgressWorld):
    """Parcel A rides both legs, parcel B only the second; both drop off at Constantine."""

    def build_schedule_world(self) -> None:
        self.build_progress_world()
        self.sender_client = client_for(self.sender)
        self.other_client = client_for(self.other_sender)

    def times(self, leg: JourneyLeg, minutes: int) -> dict:
        leg.refresh_from_db()
        delta = timedelta(minutes=minutes)
        return {
            "id": leg.pk,
            "depart_at": iso(leg.depart_at + delta),
            "arrive_at": iso(leg.arrive_at + delta),
        }

    def later(self, minutes: int, *legs: JourneyLeg) -> list[dict]:
        return [self.times(leg, minutes) for leg in (legs or (self.second,))]

    def propose(self, legs, *, client=None, journey=None, reason="Flight moved"):
        return (client or self.traveler_client).post(
            reverse("journey-schedule-changes", args=((journey or self.journey).pk,)),
            {"legs": legs, "reason": reason},
            format="json",
        )

    def preview(self, legs):
        response = self.traveler_client.post(
            reverse("journey-schedule-change-preview", args=(self.journey.pk,)),
            {"legs": legs},
            format="json",
        )
        assert response.status_code == 200, response.content
        return response.json()

    def answer(self, client, deal, action):
        return client.post(
            reverse("deal-schedule-change-answer", args=(deal.pk, action))
        )

    def sender_read(self, client, deal):
        response = client.get(reverse("deal-schedule-change", args=(deal.pk,)))
        assert response.status_code == 200
        return response.json()

    def material(self, body) -> dict[int, list[str]]:
        return {
            row["deal_id"]: row["reasons"] for row in body["parcels"] if row["material"]
        }

    def leg_times(self, leg):
        leg.refresh_from_db()
        return leg.depart_at, leg.arrive_at


# ---------------------------------------------------------------------------
# Which parcels need their sender
# ---------------------------------------------------------------------------


class ClassificationTests(ScheduleWorld, TestCase):
    def setUp(self):
        self.build_schedule_world()

    def test_a_shift_of_exactly_the_threshold_applies_without_asking(self):
        minutes = int(THRESHOLD.total_seconds() // 60)
        body = self.preview(self.later(minutes))

        assert body["applies_at_once"] is True
        assert {row["deal_id"] for row in body["parcels"]} == {
            self.deal_a.pk,
            self.deal_b.pk,
        }
        assert self.material(body) == {}

    def test_one_minute_past_the_threshold_needs_the_sender(self):
        minutes = int(THRESHOLD.total_seconds() // 60) + 1
        body = self.preview(self.later(minutes))

        assert body["applies_at_once"] is False
        # A boards on the first leg, whose times stay; B boards on the second.
        assert self.material(body) == {
            self.deal_a.pk: ["shift"],
            self.deal_b.pk: ["shift", "pickup"],
        }

    def test_earlier_counts_the_same_as_later(self):
        minutes = -(int(THRESHOLD.total_seconds() // 60) + 1)
        legs = [self.times(self.first, minutes), self.times(self.second, minutes)]
        assert self.material(self.preview(legs)) == {
            self.deal_a.pk: ["shift", "pickup"],
            self.deal_b.pk: ["shift", "pickup"],
        }

    def test_arriving_exactly_at_the_deadline_is_fine_and_a_minute_after_is_not(self):
        DeliveryRequest.objects.filter(pk=self.deal_a.delivery_request_id).update(
            deadline_at=self.second.arrive_at + timedelta(minutes=30)
        )
        assert self.material(self.preview(self.later(30))) == {}
        assert self.material(self.preview(self.later(31))) == {
            self.deal_a.pk: ["deadline"]
        }

    def test_the_deadline_counts_only_when_later_than_agreed(self):
        # The agreed arrival is already past this deadline; arriving earlier
        # than agreed, though still after it, asks nobody.
        DeliveryRequest.objects.filter(pk=self.deal_a.delivery_request_id).update(
            deadline_at=self.second.arrive_at - timedelta(hours=1)
        )
        self.second.refresh_from_db()
        earlier_arrival = [
            {
                "id": self.second.pk,
                "depart_at": iso(self.second.depart_at),
                "arrive_at": iso(self.second.arrive_at - timedelta(minutes=20)),
            }
        ]
        assert self.material(self.preview(earlier_arrival)) == {}
        assert self.material(self.preview(self.later(1))) == {
            self.deal_a.pk: ["deadline"]
        }

    def test_a_pickup_moved_before_the_agreed_time_needs_the_sender(self):
        # Only the first leg leaves earlier: A boards there, B does not ride it.
        self.first.refresh_from_db()
        legs = [
            {
                "id": self.first.pk,
                "depart_at": iso(self.first.depart_at - timedelta(minutes=30)),
                "arrive_at": iso(self.first.arrive_at),
            }
        ]
        body = self.preview(legs)
        assert [row["deal_id"] for row in body["parcels"]] == [self.deal_a.pk]
        assert self.material(body) == {self.deal_a.pk: ["pickup"]}

    def test_a_change_off_the_parcel_legs_does_not_touch_it(self):
        # Only the first leg's arrival moves, by a little: B is not on it, and
        # A's pickup and drop-off times are what they were.
        self.first.refresh_from_db()
        legs = [
            {
                "id": self.first.pk,
                "depart_at": iso(self.first.depart_at),
                "arrive_at": iso(self.first.arrive_at + timedelta(minutes=20)),
            }
        ]
        body = self.preview(legs)
        assert [row["deal_id"] for row in body["parcels"]] == [self.deal_a.pk]
        assert self.material(body) == {}

    def test_small_changes_cannot_add_up_unnoticed(self):
        # Three changes of 150 minutes: the first two apply without asking, the
        # third is 450 minutes from what the senders agreed to.
        assert self.propose(self.later(150)).json()["status"] == Change.Status.APPLIED
        assert self.propose(self.later(150)).json()["status"] == Change.Status.APPLIED
        assert self.material(self.preview(self.later(150))) == {
            self.deal_a.pk: ["shift"],
            self.deal_b.pk: ["shift", "pickup"],
        }

    def test_an_accepted_change_becomes_the_new_baseline(self):
        change = self.propose(self.later(420)).json()
        self.answer(self.sender_client, self.deal_a, "accept")
        self.answer(self.other_client, self.deal_b, "accept")
        assert Change.objects.get(pk=change["id"]).status == Change.Status.APPLIED
        # Thirty more minutes is small against the accepted times, pickup too.
        assert self.material(self.preview(self.later(30))) == {}

    def test_the_threshold_is_a_business_setting(self):
        activate_marketplace({"route_change": {"material_shift_minutes": 60}})
        assert self.material(self.preview(self.later(61))) == {
            self.deal_a.pk: ["shift"],
            self.deal_b.pk: ["shift", "pickup"],
        }


class CollectedParcelTests(ScheduleWorld, TestCase):
    """A collected parcel's sender can no longer cancel: told, never asked."""

    def setUp(self):
        self.build_schedule_world()

    def collect(self, deal):
        with self.captureOnCommitCallbacks(execute=True):
            with transaction.atomic():
                aggregate = lock_deal_lifecycle(deal.pk)
                apply_pickup_confirmed(aggregate, actor_id=self.traveler.pk)
        deal.refresh_from_db()

    def test_a_collected_parcel_is_informed_and_never_blocks(self):
        self.collect(self.deal_b)
        body = self.propose(self.later(420)).json()

        assert body["status"] == Change.Status.PENDING_SENDERS
        assert body["waiting_for"] == 1
        row_b = next(row for row in body["parcels"] if row["deal_id"] == self.deal_b.pk)
        assert (row_b["material"], row_b["informed"], row_b["reasons"]) == (
            False,
            True,
            [],
        )
        assert list(Consent.objects.values_list("deal_id", flat=True)) == [
            self.deal_a.pk
        ]
        view = self.sender_read(self.other_client, self.deal_b)["change"]
        assert (view["informed"], view["can_answer"]) == (True, False)
        assert view["actions"] == ["report_problem", "open_dispute"]
        refused = self.answer(self.other_client, self.deal_b, "decline")
        assert refused.json()["code"] == "schedule_change_answer_not_needed"

        self.answer(self.sender_client, self.deal_a, "accept")

        assert Change.objects.get(pk=body["id"]).status == Change.Status.APPLIED
        told = Notification.objects.filter(
            channel="journey.schedule_change_applied", recipient=self.other_sender
        )
        assert told.count() == 1
        event = DealEvent.objects.get(
            deal=self.deal_b, kind=DealEvent.Kind.SCHEDULE_CHANGE_APPLIED
        )
        assert event.payload["informed"] is True
        assert event.payload["arrival_before"] != event.payload["arrival_after"]

    def test_a_pickup_confirmed_while_the_sender_is_asked_stops_blocking(self):
        body = self.propose(self.later(420)).json()
        self.answer(self.sender_client, self.deal_a, "accept")
        change = Change.objects.get(pk=body["id"])
        assert change.status == Change.Status.PENDING_SENDERS

        self.collect(self.deal_b)

        change.refresh_from_db()
        assert change.status == Change.Status.APPLIED
        # The consent row stays as it was, unanswered; it no longer counts.
        assert Consent.objects.get(deal=self.deal_b).state == Consent.State.PENDING


# ---------------------------------------------------------------------------
# Applying, waiting, answering and withdrawing
# ---------------------------------------------------------------------------


class SmallChangeTests(ScheduleWorld, TestCase):
    def setUp(self):
        self.build_schedule_world()

    def test_a_small_change_applies_at_once_and_tells_the_senders(self):
        before_a, before_b = frozen(self.deal_a), frozen(self.deal_b)
        old_second = self.leg_times(self.second)

        response = self.propose(self.later(60))

        assert response.status_code == 201, response.content
        body = response.json()
        assert body["status"] == Change.Status.APPLIED
        assert body["waiting_for"] == 0
        assert self.leg_times(self.second) == (
            old_second[0] + timedelta(hours=1),
            old_second[1] + timedelta(hours=1),
        )
        assert not Consent.objects.exists()
        applied = Notification.objects.filter(channel="journey.schedule_change_applied")
        assert sorted(applied.values_list("recipient_id", flat=True)) == sorted(
            [self.sender.pk, self.other_sender.pk]
        )
        payload = applied.get(recipient=self.sender).payload
        assert payload["tracking_number"] == tracking.for_deal(self.deal_a)
        assert payload["schedule_change_id"] == body["id"]
        # Applied at once: the traveler sees it in the answer, not as a notice.
        assert not applied.filter(recipient=self.traveler).exists()
        assert (
            DealEvent.objects.filter(
                kind=DealEvent.Kind.SCHEDULE_CHANGE_APPLIED
            ).count()
            == 2
        )
        # The deal itself, its arrival snapshot and floor are untouched.
        assert (frozen(self.deal_a), frozen(self.deal_b)) == (before_a, before_b)

    def test_leg_reminders_follow_the_new_times(self):
        old_arrive = self.leg_times(self.second)[1]

        self.propose(self.later(60))

        new_depart, new_arrive = self.leg_times(self.second)
        jobs = ScheduledJob.objects.filter(
            kind=ScheduledJob.Kind.LEG_REMINDER, payload__leg_id=self.second.pk
        )
        assert jobs.filter(
            payload__kind="arrived", payload__planned_at=iso(new_arrive)
        ).exists()
        assert jobs.filter(
            payload__kind="departed", payload__planned_at=iso(new_depart)
        ).exists()
        # A reminder planned for the old time finds it moved and asks nothing.
        stale = {
            "leg_id": self.second.pk,
            "kind": "arrived",
            "planned_at": iso(old_arrive),
            "attempt": 0,
        }
        assert handle_leg_reminder(stale) == "schedule_changed"

    def test_the_same_times_are_refused_as_empty(self):
        self.second.refresh_from_db()
        response = self.propose(self.later(0))
        assert response.status_code == 409
        assert response.json()["code"] == "schedule_change_empty"
        assert not Change.objects.exists()

    def test_a_new_departure_must_be_in_the_future(self):
        self.go_back_in_time(80)  # both legs departed hours ago
        response = self.propose(self.later(30))
        assert response.json()["code"] == "leg_departure_in_past"

    def test_a_departed_leg_keeps_its_departure_and_an_arrived_one_cannot_move(self):
        self.go_back_in_time(73)  # the first leg departed an hour ago
        assert (
            self.report(self.first, JourneyLegProgress.Kind.DEPARTED).status_code == 201
        )
        moved = self.propose([self.times(self.first, 30)])
        assert moved.json()["code"] == "leg_already_departed"
        # Its arrival may still move. (Moving the clock back made the parcels'
        # agreed arrival days away, so the preview's materiality is moot here.)
        self.first.refresh_from_db()
        later_arrival = [
            {
                "id": self.first.pk,
                "depart_at": iso(self.first.depart_at),
                "arrive_at": iso(self.first.arrive_at + timedelta(minutes=20)),
            }
        ]
        assert self.preview(later_arrival)["legs"][0]["changed"] is True
        assert (
            self.report(self.first, JourneyLegProgress.Kind.ARRIVED).status_code == 201
        )
        assert self.propose(later_arrival).json()["code"] == "leg_already_arrived"

    def test_times_that_break_the_chain_are_refused(self):
        self.first.refresh_from_db()
        overlap = [
            {
                "id": self.first.pk,
                "depart_at": iso(self.first.depart_at),
                "arrive_at": iso(self.second.depart_at + timedelta(hours=1)),
            }
        ]
        response = self.propose(overlap)
        assert response.status_code in (400, 409)
        assert not Change.objects.exists()

    def test_only_the_owner_changes_times_and_only_on_a_live_journey(self):
        stranger = self.propose(self.later(60), client=self.sender_client)
        assert stranger.status_code == 403
        assert stranger.json()["code"] == "journey_not_owned"
        Journey.objects.filter(pk=self.journey.pk).update(
            status=Journey.Status.COMPLETED
        )
        assert (
            self.propose(self.later(60)).json()["code"] == "journey_not_reschedulable"
        )

    def test_malformed_bodies_are_refused(self):
        for legs in (
            None,
            [],
            [{"id": "x"}],
            [{"id": self.second.pk, "depart_at": "tomorrow"}],
        ):
            response = self.propose(legs)
            assert response.status_code == 400, legs
            assert response.json()["code"] == "schedule_change_invalid"
        twice = self.later(30) + self.later(40)
        assert self.propose(twice).json()["code"] == "schedule_change_invalid"
        naive = [{**self.later(30)[0], "depart_at": "2030-01-01T10:00:00"}]
        assert self.propose(naive).status_code == 400

    def test_a_retimed_ticket_leg_goes_back_to_review_and_stops_proposals(self):
        flight_journey = self.make_journey(
            self.traveler, [(FLIGHT, self.alg, self.cdg)]
        )
        leg = flight_journey.legs.get()
        proof = JourneyLegProof.objects.get(leg=leg)
        assert proof.status == JourneyLegProof.Status.APPROVED

        def offer(email):
            sender = self.person(email)
            parcel = self.request_over(sender, flight_journey, 0, 0, weight="1.00")
            return create_sender_offer(
                sender=sender,
                delivery_request=parcel,
                journey=flight_journey,
                start_leg_id=leg.pk,
                end_leg_id=leg.pk,
                traveler_reward_eur_cents=3_000,
            )

        assert offer("l9a-before@example.com").status == Offer.Status.PENDING
        preview = self.traveler_client.post(
            reverse("journey-schedule-change-preview", args=(flight_journey.pk,)),
            {"legs": [self.times(leg, 45)]},
            format="json",
        ).json()
        assert [notice["code"] for notice in preview["notices"]] == ["ticket_recheck"]
        assert preview["notices"][0]["text"]
        # Proposing alone changes nothing: the ticket is re-checked on apply.
        proof.refresh_from_db()
        assert proof.status == JourneyLegProof.Status.APPROVED

        response = self.propose([self.times(leg, 45)], journey=flight_journey)

        assert response.json()["status"] == Change.Status.APPLIED
        proof.refresh_from_db()
        assert proof.status == JourneyLegProof.Status.PENDING
        with self.assertRaises(V1OfferError):
            offer("l9a-after@example.com")

    def test_a_drive_needs_no_ticket_notice(self):
        assert self.preview(self.later(30))["notices"] == []


class WaitingChangeTests(ScheduleWorld, TestCase):
    def setUp(self):
        self.build_schedule_world()
        self.old_second = self.leg_times(self.second)
        response = self.propose(self.later(420))
        assert response.status_code == 201, response.content
        self.body = response.json()
        self.change = Change.objects.get(pk=self.body["id"])

    def test_a_material_change_waits_and_asks_each_sender(self):
        assert self.body["status"] == Change.Status.PENDING_SENDERS
        assert self.body["waiting_for"] == 2
        assert self.leg_times(self.second) == self.old_second
        assert set(Consent.objects.values_list("deal_id", "state")) == {
            (self.deal_a.pk, Consent.State.PENDING),
            (self.deal_b.pk, Consent.State.PENDING),
        }
        asked = Notification.objects.filter(channel="journey.schedule_change_proposed")
        assert sorted(asked.values_list("recipient_id", flat=True)) == sorted(
            [self.sender.pk, self.other_sender.pk]
        )
        assert ScheduledJob.objects.filter(
            kind=ScheduledJob.Kind.SCHEDULE_CHANGE_SETTLE,
            payload__schedule_change_id=self.change.pk,
        ).exists()
        assert (
            DealEvent.objects.filter(
                kind=DealEvent.Kind.SCHEDULE_CHANGE_PROPOSED
            ).count()
            == 2
        )

    def test_one_waiting_change_at_a_time(self):
        response = self.propose(self.later(30))
        assert response.status_code == 409
        assert response.json()["code"] == "schedule_change_pending"
        assert response.json()["schedule_change_id"] == self.change.pk

    def test_it_applies_when_the_last_sender_accepts(self):
        before = frozen(self.deal_a)
        first = self.answer(self.sender_client, self.deal_a, "accept")
        assert first.status_code == 200
        assert first.json()["change"]["consent_state"] == Consent.State.ACCEPTED
        self.change.refresh_from_db()
        assert self.change.status == Change.Status.PENDING_SENDERS
        assert self.leg_times(self.second) == self.old_second

        self.answer(self.other_client, self.deal_b, "accept")

        self.change.refresh_from_db()
        assert self.change.status == Change.Status.APPLIED
        assert self.leg_times(self.second)[1] == self.old_second[1] + timedelta(
            minutes=420
        )
        assert frozen(self.deal_a) == before
        told = Notification.objects.filter(
            channel="journey.schedule_change_applied", recipient=self.traveler
        )
        assert told.count() == 1
        answered = Notification.objects.filter(
            channel="journey.schedule_change_answered", recipient=self.traveler
        )
        assert answered.count() == 2

    def test_declining_keeps_the_old_times_and_the_change_waiting(self):
        response = self.answer(self.sender_client, self.deal_a, "decline")
        assert response.json()["change"]["consent_state"] == Consent.State.DECLINED
        self.answer(self.other_client, self.deal_b, "accept")

        self.change.refresh_from_db()
        assert self.change.status == Change.Status.PENDING_SENDERS
        assert self.leg_times(self.second) == self.old_second
        # The sender may change their mind while it waits.
        self.answer(self.sender_client, self.deal_a, "accept")
        self.change.refresh_from_db()
        assert self.change.status == Change.Status.APPLIED

    def test_the_same_answer_twice_is_one_event(self):
        self.answer(self.sender_client, self.deal_a, "decline")
        self.answer(self.sender_client, self.deal_a, "decline")
        assert (
            DealEvent.objects.filter(
                kind=DealEvent.Kind.SCHEDULE_CHANGE_DECLINED
            ).count()
            == 1
        )

    def test_only_the_sender_answers(self):
        # The traveler is not this parcel's sender: the deal is not theirs to answer.
        assert (
            self.answer(self.traveler_client, self.deal_a, "accept").status_code == 404
        )
        # Another sender cannot answer for this parcel either.
        assert self.answer(self.other_client, self.deal_a, "accept").status_code == 404
        assert self.answer(self.sender_client, self.deal_a, "maybe").status_code == 404

    def test_the_traveler_withdraws_and_the_times_stay(self):
        self.answer(self.sender_client, self.deal_a, "decline")
        url = reverse(
            "journey-schedule-change-withdraw", args=(self.journey.pk, self.change.pk)
        )
        assert self.sender_client.post(url).status_code == 403
        response = self.traveler_client.post(url)

        assert response.status_code == 200
        assert response.json()["status"] == Change.Status.WITHDRAWN
        assert response.json()["withdrawn_by"] == Change.WithdrawnBy.TRAVELER
        assert self.leg_times(self.second) == self.old_second
        told = Notification.objects.filter(channel="journey.schedule_change_withdrawn")
        assert sorted(told.values_list("recipient_id", flat=True)) == sorted(
            [self.sender.pk, self.other_sender.pk]
        )
        # Withdrawn: the decline no longer makes a cancellation the traveler's.
        assert (
            quote_cancellation(
                deal_id=self.deal_a.pk, actor_id=self.sender.pk
            ).caused_by
            == "sender"
        )
        # Again is a no-op; a new change may follow.
        assert self.traveler_client.post(url).status_code == 200
        assert self.propose(self.later(30)).json()["status"] == Change.Status.APPLIED

    def test_an_applied_change_cannot_be_withdrawn(self):
        self.answer(self.sender_client, self.deal_a, "accept")
        self.answer(self.other_client, self.deal_b, "accept")
        url = reverse(
            "journey-schedule-change-withdraw", args=(self.journey.pk, self.change.pk)
        )
        response = self.traveler_client.post(url)
        assert response.status_code == 409
        assert response.json()["code"] == "schedule_change_not_pending"

    def test_nothing_to_answer_when_the_sender_is_not_asked(self):
        self.traveler_client.post(
            reverse(
                "journey-schedule-change-withdraw",
                args=(self.journey.pk, self.change.pk),
            )
        )
        response = self.answer(self.sender_client, self.deal_a, "accept")
        assert response.status_code == 409
        assert response.json()["code"] == "schedule_change_answer_not_needed"

    def test_the_proposed_notice_resolves_once_answered(self):
        def resolved():
            row = resolved_notifications(self.sender).get(
                channel="journey.schedule_change_proposed"
            )
            return row.resolved

        assert resolved() is False
        self.answer(self.sender_client, self.deal_a, "decline")
        assert resolved() is True

    def test_the_settle_job_reschedules_itself_while_waiting(self):
        assert handle_settle_job({"schedule_change_id": self.change.pk}) == "waiting"
        assert handle_settle_job({"schedule_change_id": 999_999}) == "change_gone"
        with self.assertRaises(PermanentJobError):
            handle_settle_job({"schedule_change_id": "1"})

    def test_a_journey_that_stops_being_live_withdraws_the_change(self):
        Journey.objects.filter(pk=self.journey.pk).update(
            status=Journey.Status.CANCELLED
        )
        assert settle(self.change.pk) == "withdrawn"
        self.change.refresh_from_db()
        assert self.change.withdrawn_by == Change.WithdrawnBy.NO_LONGER_VALID
        assert Notification.objects.filter(
            channel="journey.schedule_change_withdrawn", recipient=self.traveler
        ).exists()

    def test_a_parcel_funded_while_it_waits_is_asked_too(self):
        third_sender = self.person("l9a-third@example.com")
        deal_c = self.funded_deal(third_sender, 1, 1)
        assert settle(self.change.pk) == "waiting"
        assert Consent.objects.filter(change=self.change, deal=deal_c).exists()


# ---------------------------------------------------------------------------
# Cancelling after declining
# ---------------------------------------------------------------------------


class DeclineThenCancelTests(ScheduleWorld, TestCase):
    def setUp(self):
        self.build_schedule_world()
        # Inside the free-cancellation cutoff: a sender cancelling on their own
        # would owe the traveler compensation.
        Deal.objects.filter(pk=self.deal_a.pk).update(
            agreed_pickup_at=timezone.now() + timedelta(hours=2)
        )
        self.change = Change.objects.get(pk=self.propose(self.later(420)).json()["id"])

    def test_before_declining_a_late_sender_cancellation_is_the_sender_s(self):
        quote = quote_cancellation(deal_id=self.deal_a.pk, actor_id=self.sender.pk)
        assert (quote.caused_by, quote.is_late) == ("sender", True)
        assert quote.traveler_compensation_eur_cents > 0

    def test_after_declining_the_amounts_are_exactly_a_traveler_cancellation(self):
        self.answer(self.sender_client, self.deal_a, "decline")
        as_sender = quote_cancellation(deal_id=self.deal_a.pk, actor_id=self.sender.pk)
        as_traveler = quote_cancellation(
            deal_id=self.deal_a.pk, actor_id=self.traveler.pk
        )

        assert as_sender.caused_by == "traveler"
        assert as_sender.is_late is False
        assert (
            as_sender.collected_eur_cents,
            as_sender.sender_refund_eur_cents,
            as_sender.traveler_compensation_eur_cents,
            as_sender.platform_fee_eur_cents,
        ) == (
            as_traveler.collected_eur_cents,
            as_traveler.sender_refund_eur_cents,
            as_traveler.traveler_compensation_eur_cents,
            as_traveler.platform_fee_eur_cents,
        )
        assert as_sender.traveler_compensation_eur_cents == 0

    def test_cancelling_settles_the_waiting_change(self):
        self.answer(self.sender_client, self.deal_a, "decline")
        self.answer(self.other_client, self.deal_b, "accept")
        old_second = self.leg_times(self.second)

        with self.captureOnCommitCallbacks(execute=True):
            quote = cancel_funded_deal(deal_id=self.deal_a.pk, actor_id=self.sender.pk)

        assert quote.caused_by == "traveler"
        self.deal_a.refresh_from_db()
        assert self.deal_a.status == Deal.Status.REFUNDED
        assert self.deal_a.cancellation_reason == "declined_schedule_change"
        cancelled = DealEvent.objects.get(
            deal=self.deal_a, kind=DealEvent.Kind.CANCELLED_AFTER_FUNDING
        )
        assert cancelled.payload["caused_by"] == "traveler"
        # A's sender is gone; B accepted; the change is now in force.
        self.change.refresh_from_db()
        assert self.change.status == Change.Status.APPLIED
        assert self.leg_times(self.second)[1] == old_second[1] + timedelta(minutes=420)


# ---------------------------------------------------------------------------
# Offers still open when the times change
# ---------------------------------------------------------------------------


class PendingOfferTests(ScheduleWorld, TestCase):
    def setUp(self):
        self.build_schedule_world()

    def test_a_pending_offer_is_checked_against_the_new_times_at_acceptance(self):
        journey = self.make_journey(
            self.traveler,
            [(DRIVE, self.algiers, self.setif)],
            start=timezone.now() + timedelta(days=4),
        )
        leg = journey.legs.get()
        sender = self.person("l9a-offer@example.com")
        parcel = self.request_over(sender, journey, 0, 0, weight="1.00")
        DeliveryRequest.objects.filter(pk=parcel.pk).update(
            deadline_at=leg.arrive_at + timedelta(hours=1)
        )
        offer = create_sender_offer(
            sender=sender,
            delivery_request=parcel,
            journey=journey,
            start_leg_id=leg.pk,
            end_leg_id=leg.pk,
            traveler_reward_eur_cents=3_000,
        )

        # No deal yet, so nothing waits: the new times apply at once.
        response = self.propose([self.times(leg, 180)], journey=journey)
        assert response.json()["status"] == Change.Status.APPLIED

        with self.assertRaises(V1OfferError):
            accept_offer(pending_offer=offer, actor=self.traveler)
        offer.refresh_from_db()
        assert offer.status == Offer.Status.PENDING


# ---------------------------------------------------------------------------
# What each side reads
# ---------------------------------------------------------------------------


class ReadingTests(ScheduleWorld, TestCase):
    def setUp(self):
        self.build_schedule_world()
        self.change = Change.objects.get(pk=self.propose(self.later(420)).json()["id"])

    def test_the_sender_sees_only_their_parcel_and_its_legs(self):
        body = self.sender_read(self.other_client, self.deal_b)
        change = body["change"]

        assert body["tracking_number"] == tracking.for_deal(self.deal_b)
        assert change["can_answer"] is True
        assert change["reasons"] == ["shift", "pickup"]
        assert change["informed"] is False and change["actions"] == []
        assert [leg["leg_id"] for leg in change["legs"]] == [self.second.pk]
        text = str(body)
        assert tracking.for_deal(self.deal_a) not in text
        assert "@example.com" not in text
        assert "affected" not in change and "parcels" not in change

    def test_parcel_a_sees_both_its_legs(self):
        change = self.sender_read(self.sender_client, self.deal_a)["change"]
        assert [leg["leg_id"] for leg in change["legs"]] == [
            self.first.pk,
            self.second.pk,
        ]
        assert [leg["changed"] for leg in change["legs"]] == [False, True]

    def test_a_sender_never_reads_another_parcel(self):
        response = self.other_client.get(
            reverse("deal-schedule-change", args=(self.deal_a.pk,))
        )
        assert response.status_code == 404
        response = self.traveler_client.get(
            reverse("deal-schedule-change", args=(self.deal_a.pk,))
        )
        assert response.status_code == 404

    def test_a_parcel_no_change_touched_reads_none(self):
        self.traveler_client.post(
            reverse(
                "journey-schedule-change-withdraw",
                args=(self.journey.pk, self.change.pk),
            )
        )
        # Only the first leg's departure moves: B is not on it.
        self.first.refresh_from_db()
        self.propose(
            [
                {
                    "id": self.first.pk,
                    "depart_at": iso(self.first.depart_at - timedelta(minutes=15)),
                    "arrive_at": iso(self.first.arrive_at),
                }
            ]
        )
        # B still sees the withdrawn change, the latest that touched it.
        body = self.sender_read(self.other_client, self.deal_b)
        assert body["change"]["id"] == self.change.pk
        assert body["change"]["can_answer"] is False

    def test_the_traveler_lists_changes_with_every_parcel(self):
        response = self.traveler_client.get(
            reverse("journey-schedule-changes", args=(self.journey.pk,))
        )
        assert response.status_code == 200
        (row,) = response.json()["results"]
        assert row["id"] == self.change.pk
        assert {parcel["deal_id"] for parcel in row["parcels"]} == {
            self.deal_a.pk,
            self.deal_b.pk,
        }
        assert all(parcel["consent_state"] == "pending" for parcel in row["parcels"])
        assert "@example.com" not in str(row)
        stranger = self.sender_client.get(
            reverse("journey-schedule-changes", args=(self.journey.pk,))
        )
        assert stranger.status_code == 403

    def test_the_timeline_carries_the_change_to_the_parties(self):
        from apps.deals.timeline import deal_timeline

        events = DealEvent.objects.filter(
            deal=self.deal_a, kind=DealEvent.Kind.SCHEDULE_CHANGE_PROPOSED
        )
        (row,) = deal_timeline(list(events))
        assert row["payload"]["schedule_change_id"] == self.change.pk
        assert row["payload"]["material_reasons"] == ["shift"]
        assert row["payload"]["consent_state"] == "pending"
