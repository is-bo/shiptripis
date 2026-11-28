"""L5A: progress updates and leg reminders (spec 11).

A traveler's report is a statement. It reaches the timeline of exactly the
funded parcels on the leg, tells their senders, and changes nothing else.
Reminders are durable jobs that re-read their gates and do nothing when the
question is no longer worth asking.
"""

from __future__ import annotations

from datetime import timedelta

from django.core.cache import cache
from django.forms.models import model_to_dict
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.deals.models import Deal, DealEvent
from apps.deals.tests.phase4_factories import enable_mock_rail
from apps.deals.timeline import deal_timeline
from apps.discovery.tests.support import activate_marketplace
from apps.finance.jobs import PermanentJobError, run_job
from apps.finance.models import PaymentOrder, ScheduledJob
from apps.finance.tests.factories import pay_order_with_mock
from apps.matching.v1_services import accept_offer, create_sender_offer
from apps.notifications.models import Notification
from apps.trips.models import Journey, JourneyLeg, JourneyLegProgress
from apps.trips.progress import (
    RETRACT_WINDOW,
    handle_leg_reminder,
    pending_questions,
    schedule_leg_reminders,
)
from apps.trips.services import publish_journey

from .sea_world import DRIVE, SeaWorld

ARRIVED = JourneyLegProgress.Kind.ARRIVED
DEPARTED = JourneyLegProgress.Kind.DEPARTED
AT_PORT = JourneyLegProgress.Kind.AT_PORT


def client_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


class ProgressWorld(SeaWorld):
    """A two-leg road trip (Algiers, Setif, Constantine) with parcels on it."""

    def build_progress_world(self) -> None:
        cache.clear()
        enable_mock_rail()
        self.build_sea_world()
        self.traveler = self.person("l5a-traveler@example.com")
        self.sender = self.person("l5a-sender@example.com")
        self.other_sender = self.person("l5a-other@example.com")
        self.journey = self.make_journey(
            self.traveler,
            [(DRIVE, self.algiers, self.setif), (DRIVE, self.setif, self.constantine)],
        )
        self.first, self.second = self.journey.legs.order_by("position")
        # Parcel A rides both legs, parcel B only the second.
        self.deal_a = self.funded_deal(self.sender, 0, 1)
        self.deal_b = self.funded_deal(self.other_sender, 1, 1)
        self.traveler_client = client_for(self.traveler)

    def funded_deal(self, sender, first: int, last: int) -> Deal:
        parcel = self.request_over(sender, self.journey, first, last, weight="2.40")
        legs = list(self.journey.legs.order_by("position"))
        offer = create_sender_offer(
            sender=sender,
            delivery_request=parcel,
            journey=self.journey,
            start_leg_id=legs[first].pk,
            end_leg_id=legs[last].pk,
            traveler_reward_eur_cents=4_000,
        )
        deal = accept_offer(pending_offer=offer, actor=self.traveler).deal
        order = PaymentOrder.objects.get(deal=deal, purpose=PaymentOrder.Purpose.DEAL_BALANCE)
        pay_order_with_mock(Client(), order)
        deal.refresh_from_db()
        assert deal.status == Deal.Status.FUNDED
        return deal

    def go_back_in_time(self, hours: int) -> None:
        """Move both legs' planned times ``hours`` into the past (the deals are already funded)."""

        for leg in (self.first, self.second):
            JourneyLeg.objects.filter(pk=leg.pk).update(
                depart_at=leg.depart_at - timedelta(hours=hours),
                arrive_at=leg.arrive_at - timedelta(hours=hours),
            )
        self.first.refresh_from_db()
        self.second.refresh_from_db()

    def report(self, leg, kind, *, client=None, journey=None):
        return (client or self.traveler_client).post(
            reverse("journey-leg-progress", args=((journey or self.journey).pk, leg.pk)),
            {"kind": kind},
            format="json",
        )

    def retract(self, row_id, *, client=None):
        return (client or self.traveler_client).post(
            reverse("journeys-progress-retract", args=(self.journey.pk, row_id))
        )

    def live(self, leg, kind):
        return JourneyLegProgress.objects.filter(
            leg=leg, kind=kind, retracted_at__isnull=True
        ).first()


# ---------------------------------------------------------------------------
# The ordering rules
# ---------------------------------------------------------------------------


class ProgressRulesTests(ProgressWorld, TestCase):
    def setUp(self):
        self.build_progress_world()
        self.go_back_in_time(72)

    def code(self, response):
        return response.json()["code"]

    def test_the_trip_is_reported_in_order(self):
        assert self.code(self.report(self.first, ARRIVED)) == "progress_out_of_order"
        assert self.code(self.report(self.second, DEPARTED)) == "progress_out_of_order"

        assert self.report(self.first, DEPARTED).status_code == 201
        assert self.code(self.report(self.second, DEPARTED)) == "progress_out_of_order"
        assert self.report(self.first, ARRIVED).status_code == 201
        assert self.code(self.report(self.second, ARRIVED)) == "progress_out_of_order"
        assert self.report(self.second, DEPARTED).status_code == 201
        assert self.report(self.second, ARRIVED).status_code == 201

    def test_at_the_port_is_for_a_sea_leg_only(self):
        response = self.report(self.first, AT_PORT)
        assert response.status_code == 409
        assert self.code(response) == "progress_kind_not_allowed"

    def test_at_the_port_is_refused_once_the_leg_has_departed(self):
        sea = self.make_journey(
            self.traveler, [("SEA", self.marseille, self.algiers)], start=self.now - timedelta(days=3)
        )
        self.set_sea_switch(True)
        leg = sea.legs.get()
        assert self.report(leg, DEPARTED, journey=sea).status_code == 201
        assert self.code(self.report(leg, AT_PORT, journey=sea)) == "progress_out_of_order"

    def test_the_same_report_twice_is_one_row(self):
        first = self.report(self.first, DEPARTED)
        again = self.report(self.first, DEPARTED)

        assert (first.status_code, again.status_code) == (201, 200)
        assert first.json()["id"] == again.json()["id"]
        assert JourneyLegProgress.objects.count() == 1
        assert DealEvent.objects.filter(kind=DealEvent.Kind.TRAVELER_PROGRESS).count() == 1

    def test_more_than_a_day_early_is_refused_with_the_time_it_opens(self):
        self.go_back_in_time(-48)  # the legs now depart in two days
        response = self.report(self.first, DEPARTED)

        assert response.status_code == 409
        assert self.code(response) == "progress_too_early"
        assert response.json()["available_at"]

    def test_a_day_before_is_accepted(self):
        self.go_back_in_time(-23)  # departs in 23 hours
        assert self.report(self.first, DEPARTED).status_code == 201

    def test_only_the_owner_reports(self):
        stranger = client_for(self.sender)
        response = self.report(self.first, DEPARTED, client=stranger)

        assert response.status_code == 403
        assert self.code(response) == "journey_not_owned"
        assert not JourneyLegProgress.objects.exists()

    def test_a_finished_journey_takes_no_reports(self):
        Journey.objects.filter(pk=self.journey.pk).update(status=Journey.Status.CANCELLED)
        response = self.report(self.first, DEPARTED)

        assert response.status_code == 409
        assert self.code(response) == "journey_not_reportable"

    def test_an_unknown_kind_or_leg_is_refused(self):
        assert self.report(self.first, "teleported").status_code == 400
        elsewhere = self.make_journey(self.traveler, [(DRIVE, self.oran, self.algiers)])
        leg = elsewhere.legs.get()
        assert self.report(leg, DEPARTED).status_code == 404

    def test_the_progress_read_lists_reports_and_the_next_actions(self):
        self.report(self.first, DEPARTED)
        body = self.traveler_client.get(reverse("journeys-progress", args=(self.journey.pk,))).json()

        first, second = body["legs"]
        assert [r["kind"] for r in first["reports"]] == [DEPARTED]
        assert first["reports"][0]["can_retract"] is True
        assert [a["kind"] for a in first["next_actions"]] == [ARRIVED]
        assert first["next_actions"][0]["can_report_now"] is True
        # The second leg cannot depart until the first has arrived.
        assert second["next_actions"] == []
        assert client_for(self.sender).get(
            reverse("journeys-progress", args=(self.journey.pk,))
        ).status_code == 403


# ---------------------------------------------------------------------------
# Effects: fan-out, the deal row, retraction
# ---------------------------------------------------------------------------


def deal_row(deal: Deal) -> dict:
    deal.refresh_from_db()
    return {**model_to_dict(deal), "updated_at": deal.updated_at}


class ProgressEffectsTests(ProgressWorld, TestCase):
    def setUp(self):
        self.build_progress_world()
        self.go_back_in_time(72)

    def events(self, deal, kind=DealEvent.Kind.TRAVELER_PROGRESS):
        return list(DealEvent.objects.filter(deal=deal, kind=kind))

    def test_a_report_reaches_exactly_the_parcels_on_that_leg(self):
        # Parcel B rides only the second leg.
        self.report(self.first, DEPARTED)
        assert len(self.events(self.deal_a)) == 1
        assert self.events(self.deal_b) == []

        self.report(self.first, ARRIVED)
        self.report(self.second, DEPARTED)
        assert len(self.events(self.deal_a)) == 3
        assert len(self.events(self.deal_b)) == 1

    def test_the_event_is_labelled_and_visible_to_the_sender(self):
        self.report(self.first, DEPARTED)
        event = self.events(self.deal_a)[0]

        assert event.actor_id == self.traveler.pk
        assert event.payload["source"] == "traveler_reported"
        assert event.payload["progress_kind"] == DEPARTED
        assert event.payload["leg_id"] == self.first.pk
        projected = [
            row for row in deal_timeline([event]) if row["kind"] == "traveler_progress"
        ][0]["payload"]
        assert projected["source"] == "traveler_reported"
        assert projected["progress_kind"] == DEPARTED

    def test_each_sender_is_told_once_and_only_senders(self):
        self.report(self.first, DEPARTED)
        self.report(self.first, DEPARTED)  # a repeat tells nobody twice

        told = Notification.objects.filter(channel="deal.progress_reported")
        assert [n.recipient_id for n in told] == [self.sender.pk]
        assert told[0].payload["deal_id"] == self.deal_a.pk
        assert told[0].payload["progress_kind"] == DEPARTED
        assert not told.filter(recipient=self.other_sender).exists()
        assert not told.filter(recipient=self.traveler).exists()

    def test_a_report_leaves_every_deal_row_byte_identical(self):
        before = {deal.pk: deal_row(deal) for deal in (self.deal_a, self.deal_b)}
        status_events = DealEvent.objects.filter(kind=DealEvent.Kind.STATUS_CHANGED).count()
        allocations = list(
            self.deal_a.leg_allocations.values_list("pk", "status", "allocated_weight_kg")
        )

        self.report(self.first, DEPARTED)
        self.report(self.first, ARRIVED)
        self.report(self.second, DEPARTED)
        self.report(self.second, ARRIVED)

        assert before == {deal.pk: deal_row(deal) for deal in (self.deal_a, self.deal_b)}
        assert allocations == list(
            self.deal_a.leg_allocations.values_list("pk", "status", "allocated_weight_kg")
        )
        assert status_events == DealEvent.objects.filter(
            kind=DealEvent.Kind.STATUS_CHANGED
        ).count()

    def test_a_cancelled_parcel_is_not_told(self):
        from apps.deals.models import DealLegAllocation

        DealLegAllocation.objects.filter(deal=self.deal_a).update(
            status=DealLegAllocation.Status.CANCELLED
        )
        self.report(self.first, DEPARTED)

        assert self.events(self.deal_a) == []
        assert not Notification.objects.filter(channel="deal.progress_reported").exists()


class ProgressRetractionTests(ProgressWorld, TestCase):
    def setUp(self):
        self.build_progress_world()
        self.go_back_in_time(72)

    def test_a_report_can_be_retracted_and_history_stays(self):
        row = self.report(self.first, DEPARTED).json()["id"]
        response = self.retract(row)

        assert response.status_code == 200
        assert response.json()["retracted_at"]
        assert JourneyLegProgress.objects.filter(pk=row).exists()
        assert self.live(self.first, DEPARTED) is None
        kinds = list(
            DealEvent.objects.filter(deal=self.deal_a).values_list("kind", flat=True)
        )
        assert "traveler_progress" in kinds and "traveler_progress_retracted" in kinds
        # The parcel that was never on this leg has no line to take back.
        assert not DealEvent.objects.filter(
            deal=self.deal_b, kind=DealEvent.Kind.TRAVELER_PROGRESS_RETRACTED
        ).exists()

    def test_after_a_retraction_the_leg_can_be_reported_again(self):
        row = self.report(self.first, DEPARTED).json()["id"]
        self.retract(row)
        again = self.report(self.first, DEPARTED)

        assert again.status_code == 201
        assert again.json()["id"] != row
        assert JourneyLegProgress.objects.filter(leg=self.first, kind=DEPARTED).count() == 2

    def test_retracting_twice_is_harmless(self):
        row = self.report(self.first, DEPARTED).json()["id"]
        self.retract(row)
        assert self.retract(row).status_code == 200
        assert (
            DealEvent.objects.filter(kind=DealEvent.Kind.TRAVELER_PROGRESS_RETRACTED).count() == 1
        )

    def test_the_window_closes_after_ten_minutes(self):
        row = self.report(self.first, DEPARTED).json()["id"]
        JourneyLegProgress.objects.filter(pk=row).update(
            reported_at=timezone.now() - RETRACT_WINDOW - timedelta(seconds=5)
        )
        response = self.retract(row)

        assert response.status_code == 409
        assert response.json()["code"] == "progress_retract_window_closed"
        assert self.live(self.first, DEPARTED) is not None

    def test_a_report_a_later_one_depends_on_cannot_be_retracted(self):
        departed = self.report(self.first, DEPARTED).json()["id"]
        arrived = self.report(self.first, ARRIVED).json()["id"]
        response = self.retract(departed)
        assert (response.status_code, response.json()["code"]) == (409, "progress_has_followup")

        self.report(self.second, DEPARTED)
        assert self.retract(arrived).json()["code"] == "progress_has_followup"

    def test_only_the_owner_retracts_and_only_on_this_journey(self):
        row = self.report(self.first, DEPARTED).json()["id"]
        assert self.retract(row, client=client_for(self.sender)).status_code == 403
        elsewhere = self.make_journey(self.traveler, [(DRIVE, self.oran, self.algiers)])
        response = self.traveler_client.post(
            reverse("journeys-progress-retract", args=(elsewhere.pk, row))
        )
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Reminders
# ---------------------------------------------------------------------------


def jobs():
    return ScheduledJob.objects.filter(kind=ScheduledJob.Kind.LEG_REMINDER)


def payload_for(leg, kind, *, attempt=0, planned=None):
    from apps.trips.progress import planned_at

    return {
        "leg_id": leg.pk,
        "kind": kind,
        "planned_at": (planned or planned_at(leg, kind)).isoformat(),
        "attempt": attempt,
    }


class ReminderScheduleTests(SeaWorld, TestCase):
    def setUp(self):
        cache.clear()
        self.build_sea_world()
        self.traveler = self.person("l5a-draft@example.com")

    def draft(self):
        journey = self.make_journey(
            self.traveler,
            [(DRIVE, self.algiers, self.setif), (DRIVE, self.setif, self.constantine)],
            status=Journey.Status.DRAFT,
        )
        return journey

    def test_publishing_schedules_a_departure_and_an_arrival_question_per_leg(self):
        journey = self.draft()
        assert not jobs().exists()

        publish_journey(journey=journey, actor=self.traveler)

        assert jobs().count() == 4
        legs = list(journey.legs.order_by("position"))
        for leg in legs:
            departure = jobs().get(payload__leg_id=leg.pk, payload__kind="departed")
            assert departure.run_at == leg.depart_at + timedelta(minutes=30)
            arrival = jobs().get(payload__leg_id=leg.pk, payload__kind="arrived")
            assert arrival.run_at == leg.arrive_at + timedelta(minutes=60)

    def test_scheduling_twice_adds_nothing(self):
        journey = self.draft()
        publish_journey(journey=journey, actor=self.traveler)
        schedule_leg_reminders(journey)
        publish_journey(journey=journey, actor=self.traveler)  # already active: no-op

        assert jobs().count() == 4

    def test_the_handler_is_registered(self):
        from apps.finance.jobs import HANDLERS

        assert ScheduledJob.Kind.LEG_REMINDER in HANDLERS


class ReminderHandlerTests(ProgressWorld, TestCase):
    def setUp(self):
        self.build_progress_world()
        activate_marketplace({})
        self.go_back_in_time(72)

    def notified(self):
        return Notification.objects.filter(channel="journey.leg_reminder")

    def run_handler(self, leg, kind, **kw):
        return handle_leg_reminder(payload_for(leg, kind, **kw))

    def test_it_asks_when_a_funded_leg_has_no_report(self):
        assert self.run_handler(self.first, DEPARTED) == "notified"

        (note,) = self.notified()
        assert note.recipient_id == self.traveler.pk
        assert note.payload["leg_id"] == self.first.pk
        assert note.payload["progress_kind"] == DEPARTED
        assert note.payload["journey_id"] == self.journey.pk
        # No city, schedule or parcel travels with the question.
        assert set(note.payload) >= {"leg_id", "journey_id", "progress_kind", "attempt"}
        assert not {"origin", "destination", "depart_at", "parcel_id", "deal_id"} & set(note.payload)

    def test_it_schedules_the_next_attempt_up_to_max_repeats(self):
        self.run_handler(self.first, DEPARTED)
        nxt = jobs().get(payload__attempt=1)
        assert nxt.run_at > timezone.now() + timedelta(minutes=170)

        activate_marketplace({"reminders": {"max_repeats": 1}})
        self.run_handler(self.first, DEPARTED, attempt=1)
        assert not jobs().filter(payload__attempt=2).exists()

    def test_running_twice_asks_once(self):
        self.run_handler(self.first, DEPARTED)
        self.run_handler(self.first, DEPARTED)

        assert self.notified().count() == 1
        assert jobs().filter(payload__attempt=1).count() == 1

    def test_it_does_nothing_when_reminders_are_off(self):
        activate_marketplace({"reminders": {"enabled": False}})
        assert self.run_handler(self.first, DEPARTED) == "reminders_disabled"
        assert not self.notified().exists() and not jobs().exists()

    def test_it_does_nothing_when_the_journey_is_not_live(self):
        Journey.objects.filter(pk=self.journey.pk).update(status=Journey.Status.CANCELLED)
        assert self.run_handler(self.first, DEPARTED) == "journey_not_live"
        assert not self.notified().exists()

    def test_it_does_nothing_when_the_planned_time_moved(self):
        old = self.first.depart_at
        JourneyLeg.objects.filter(pk=self.first.pk).update(depart_at=old - timedelta(hours=1))
        self.first.refresh_from_db()

        result = handle_leg_reminder(payload_for(self.first, DEPARTED, planned=old))
        assert result == "schedule_changed"
        assert not self.notified().exists()

    def test_it_does_nothing_without_a_funded_parcel(self):
        from apps.deals.models import DealLegAllocation

        DealLegAllocation.objects.filter(journey_leg=self.first).update(
            status=DealLegAllocation.Status.RELEASED
        )
        assert self.run_handler(self.first, DEPARTED) == "no_funded_parcel"
        assert not self.notified().exists()

    def test_it_does_nothing_once_the_leg_is_reported(self):
        self.report(self.first, DEPARTED)
        assert self.run_handler(self.first, DEPARTED) == "already_reported"
        assert not self.notified().exists()

    def test_a_retracted_report_is_asked_about_again(self):
        row = self.report(self.first, DEPARTED).json()["id"]
        self.retract(row)
        assert self.run_handler(self.first, DEPARTED) == "notified"

    def test_the_arrival_question_waits_for_the_departure_and_is_re_armed_by_it(self):
        assert self.run_handler(self.first, ARRIVED) == "not_yet_askable"
        assert not self.notified().exists()

        self.report(self.first, DEPARTED)
        rearmed = jobs().get(key__contains=":after")
        assert rearmed.payload["kind"] == ARRIVED
        assert handle_leg_reminder(rearmed.payload) == "notified"

    def test_a_deleted_leg_is_a_no_op(self):
        payload = payload_for(self.first, DEPARTED)
        payload["leg_id"] = 10**9
        assert handle_leg_reminder(payload) == "leg_gone"

    def test_a_malformed_payload_fails_permanently(self):
        for bad in ({}, {**payload_for(self.first, DEPARTED), "kind": "at_port"},
                    {**payload_for(self.first, DEPARTED), "planned_at": "soon"},
                    {**payload_for(self.first, DEPARTED), "attempt": -1}):
            with self.subTest(bad=bad), self.assertRaises(PermanentJobError):
                handle_leg_reminder(bad)

    def test_the_job_runner_executes_a_stored_reminder(self):
        from apps.finance.services import schedule_job
        from apps.finance.tests.factories import claim

        job = schedule_job(
            kind=ScheduledJob.Kind.LEG_REMINDER,
            key="leg_reminder:test",
            run_at=timezone.now(),
            payload=payload_for(self.first, DEPARTED),
        )
        run_job(claim(job))
        job.refresh_from_db()
        assert job.status == ScheduledJob.Status.SUCCEEDED
        assert job.last_result == "notified"

    def test_answering_resolves_the_reminder_in_the_inbox(self):
        from apps.notifications.resolution import resolved_notifications

        self.run_handler(self.first, DEPARTED)
        (row,) = resolved_notifications(self.traveler).filter(channel="journey.leg_reminder")
        assert row.resolved is False

        self.report(self.first, DEPARTED)
        (row,) = resolved_notifications(self.traveler).filter(channel="journey.leg_reminder")
        assert row.resolved is True


# ---------------------------------------------------------------------------
# What Home asks
# ---------------------------------------------------------------------------


class PendingQuestionsTests(ProgressWorld, TestCase):
    def setUp(self):
        self.build_progress_world()
        activate_marketplace({})

    def pending(self, client=None):
        response = (client or self.traveler_client).get(reverse("journeys-progress-pending"))
        assert response.status_code == 200
        return response.json()["results"]

    def test_nothing_is_due_before_the_planned_time_plus_the_delay(self):
        assert self.pending() == []

    def test_a_late_departure_is_asked_with_the_city(self):
        self.go_back_in_time(80)
        (question,) = self.pending()

        assert (question["journey_id"], question["leg_id"], question["kind"]) == (
            self.journey.pk,
            self.first.pk,
            DEPARTED,
        )
        assert question["place_name"] == "Algiers"

    def test_the_next_question_follows_the_answer(self):
        self.go_back_in_time(80)
        self.report(self.first, DEPARTED)
        (question,) = self.pending()
        assert (question["kind"], question["place_name"]) == (ARRIVED, "Sétif")

        self.report(self.first, ARRIVED)
        (question,) = self.pending()
        assert (question["leg_id"], question["kind"]) == (self.second.pk, DEPARTED)

    def test_a_leg_without_a_funded_parcel_is_never_asked(self):
        quiet = self.make_journey(
            self.traveler, [(DRIVE, self.oran, self.algiers)], start=self.now - timedelta(days=3)
        )
        self.go_back_in_time(80)
        assert quiet.pk not in {q["journey_id"] for q in self.pending()}

    def test_reminders_off_asks_nothing(self):
        self.go_back_in_time(80)
        activate_marketplace({"reminders": {"enabled": False}})
        assert self.pending() == []

    def test_it_is_only_the_callers_own_questions(self):
        self.go_back_in_time(80)
        assert self.pending(client_for(self.sender)) == []
        assert pending_questions(self.sender) == []
