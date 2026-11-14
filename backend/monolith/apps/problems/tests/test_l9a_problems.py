"""L9A: problem reports and no-show reports (spec 12).

A report is a statement. It reaches the other party and, for the serious
kinds, staff; it never changes the deal. Only staff record a no-show, through
the existing action, and doing so closes the open reports with a reference to
the audit row.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

from django.forms.models import model_to_dict
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.admin_panel.models import AdminAuditLog
from apps.admin_panel.permissions import assign_admin_roles
from apps.deals.models import Deal, DealEvent
from apps.deals.timeline import deal_timeline
from apps.discovery.tests.support import STATIC_STORES
from apps.finance.models import PaymentRefund
from apps.notifications.models import Notification
from apps.parcels import tracking
from apps.problems.models import ShipmentProblem
from apps.problems.services import (
    ProblemError,
    acknowledge_problem,
    close_problem,
)
from apps.trips.tests.test_l5a_progress import ProgressWorld, client_for
from apps.admin_panel.tests.two_step_helpers import staff_login

Kind = ShipmentProblem.Kind
Status = ShipmentProblem.Status


def deal_row(deal: Deal) -> dict:
    deal.refresh_from_db()
    return {**model_to_dict(deal), "updated_at": deal.updated_at}


class ProblemWorld(ProgressWorld):
    def build_problem_world(self) -> None:
        self.build_progress_world()
        self.sender_client = client_for(self.sender)
        self.deal = self.deal_a

    def staff_user(self, email: str, role: str):
        user = self.person(email, verified=False)
        user.is_staff = True
        user.save(update_fields=["is_staff"])
        assign_admin_roles(user, [role])
        return user

    def pickup_passed(self, *, minutes: int = 1, deal: Deal | None = None) -> None:
        """Move the agreed pickup into the past (funding froze it in the future)."""

        Deal.objects.filter(pk=(deal or self.deal).pk).update(
            agreed_pickup_at=timezone.now() - timedelta(minutes=minutes)
        )

    def report(self, client, kind, note="", deal=None):
        return client.post(
            reverse("deal-problems", args=((deal or self.deal).pk,)),
            {"kind": kind, "note": note},
            format="json",
        )

    def read(self, client, deal=None):
        response = client.get(reverse("deal-problems", args=((deal or self.deal).pk,)))
        assert response.status_code == 200
        return response.json()


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


class ReportingTests(ProblemWorld, TestCase):
    def setUp(self):
        self.build_problem_world()

    def test_a_party_reports_and_the_other_party_is_told(self):
        response = self.report(
            self.traveler_client, Kind.TRIP_DISRUPTED, "Flight delayed"
        )

        assert response.status_code == 201
        body = response.json()
        assert body["created"] is True
        assert body["problem"]["kind"] == Kind.TRIP_DISRUPTED
        assert body["problem"]["status"] == Status.OPEN
        assert body["problem"]["reported_by_me"] is True
        notes = Notification.objects.filter(channel="deal.problem_reported")
        assert [row.recipient_id for row in notes] == [self.sender.pk]
        payload = notes.get().payload
        assert payload["tracking_number"] == tracking.for_deal(self.deal)
        assert payload["problem_kind"] == Kind.TRIP_DISRUPTED
        assert "Flight delayed" not in json.dumps(payload)

    def test_serious_kinds_go_to_staff_at_once(self):
        for kind in (Kind.PARCEL_DAMAGED, Kind.PARCEL_MISMATCH):
            body = self.report(self.traveler_client, kind).json()
            assert body["problem"]["status"] == Status.ESCALATED
            assert body["problem"]["escalated"] is True
        for kind in (Kind.RECIPIENT_UNAVAILABLE, Kind.CUSTOMS_DELAY, Kind.OTHER):
            assert (
                self.report(self.sender_client, kind).json()["problem"]["status"]
                == Status.OPEN
            )

    def test_a_repeat_returns_the_live_report(self):
        first = self.report(self.traveler_client, Kind.OTHER, "one")
        again = self.report(self.traveler_client, Kind.OTHER, "two")

        assert (first.status_code, again.status_code) == (201, 200)
        assert again.json()["created"] is False
        assert first.json()["problem"]["id"] == again.json()["problem"]["id"]
        assert ShipmentProblem.objects.count() == 1
        assert (
            DealEvent.objects.filter(kind=DealEvent.Kind.PROBLEM_REPORTED).count() == 1
        )
        assert Notification.objects.filter(channel="deal.problem_reported").count() == 1

    def test_only_a_party_reports_or_reads(self):
        stranger = client_for(self.other_sender)
        assert self.report(stranger, Kind.OTHER).status_code == 404
        assert (
            stranger.get(reverse("deal-problems", args=(self.deal.pk,))).status_code
            == 404
        )

    def test_unknown_kind_and_long_note_are_refused(self):
        assert (
            self.report(self.sender_client, "alien_abduction").json()["code"]
            == "problem_kind_invalid"
        )
        response = self.report(self.sender_client, Kind.OTHER, "x" * 1001)
        assert response.status_code == 400
        assert response.json()["code"] == "problem_note_too_long"

    def test_an_unfunded_or_delivered_deal_takes_no_general_report(self):
        Deal.objects.filter(pk=self.deal.pk).update(
            status=Deal.Status.DELIVERY_CONFIRMED
        )
        response = self.report(self.sender_client, Kind.PARCEL_DAMAGED)

        assert response.status_code == 409
        assert response.json()["code"] == "problem_report_not_allowed"
        assert self.read(self.sender_client)["reportable_kinds"] == []

    def test_a_report_leaves_the_deal_row_byte_identical(self):
        self.pickup_passed()
        before = deal_row(self.deal)
        self.report(self.sender_client, Kind.TRAVELER_NO_SHOW, "Waited an hour")
        self.report(self.traveler_client, Kind.PARCEL_DAMAGED)

        assert deal_row(self.deal) == before

    def test_the_timeline_carries_tokens_never_the_note(self):
        self.report(
            self.traveler_client, Kind.PARCEL_DAMAGED, "Box crushed, call me on 0555"
        )
        event = DealEvent.objects.get(kind=DealEvent.Kind.PROBLEM_REPORTED)

        assert "0555" not in json.dumps(event.payload)
        projected = deal_timeline([event])[0]["payload"]
        assert projected == {
            "problem_id": event.payload["problem_id"],
            "problem_kind": Kind.PARCEL_DAMAGED,
            "problem_status": Status.ESCALATED,
            "reporter_role": "traveler",
        }

    def test_both_parties_read_every_report_and_no_private_key(self):
        self.report(self.traveler_client, Kind.PARCEL_MISMATCH, "Not the declared item")
        for client, mine in ((self.traveler_client, True), (self.sender_client, False)):
            body = self.read(client)
            assert body["tracking_number"] == tracking.for_deal(self.deal)
            assert [row["reported_by_me"] for row in body["results"]] == [mine]
            assert body["results"][0]["note"] == "Not the declared item"
            text = json.dumps(body).lower()
            for forbidden in ("@example.com", "code_hash", "address"):
                assert forbidden not in text, forbidden
            keys = set(_walk_keys(body))
            for forbidden in (
                "email",
                "phone",
                "acknowledged_by",
                "acknowledged_reason",
                "closed_by",
                "closed_reason",
                "closed_by_audit",
            ):
                assert forbidden not in keys, forbidden


def _walk_keys(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _walk_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_keys(item)


# ---------------------------------------------------------------------------
# No-show reports
# ---------------------------------------------------------------------------


class NoShowReportTests(ProblemWorld, TestCase):
    def setUp(self):
        self.build_problem_world()

    def test_the_window_opens_at_the_agreed_pickup_time(self):
        Deal.objects.filter(pk=self.deal.pk).update(
            agreed_pickup_at=timezone.now() + timedelta(minutes=5)
        )
        body = self.read(self.sender_client)
        assert body["can_report_no_show"] is False
        assert body["no_show_reason"] == "pickup_time_not_reached"
        assert body["no_show_available_at"]
        response = self.report(self.sender_client, Kind.TRAVELER_NO_SHOW)
        assert response.status_code == 409
        assert response.json()["code"] == "no_show_report_not_allowed"
        assert response.json()["reason"] == "pickup_time_not_reached"

        self.pickup_passed(minutes=0)  # exactly at the agreed time
        body = self.read(self.sender_client)
        assert body["can_report_no_show"] is True
        assert body["no_show_kind"] == Kind.TRAVELER_NO_SHOW
        assert Kind.TRAVELER_NO_SHOW in body["reportable_kinds"]
        assert Kind.SENDER_UNAVAILABLE not in body["reportable_kinds"]
        assert self.report(self.sender_client, Kind.TRAVELER_NO_SHOW).status_code == 201

    def test_the_window_closes_at_pickup(self):
        self.pickup_passed()
        Deal.objects.filter(pk=self.deal.pk).update(pickup_confirmed_at=timezone.now())

        body = self.read(self.traveler_client)
        assert (body["can_report_no_show"], body["no_show_reason"]) == (
            False,
            "pickup_already_confirmed",
        )
        response = self.report(self.traveler_client, Kind.SENDER_UNAVAILABLE)
        assert response.json()["reason"] == "pickup_already_confirmed"

    def test_no_pickup_time_and_no_funding_say_why(self):
        Deal.objects.filter(pk=self.deal.pk).update(agreed_pickup_at=None)
        assert self.read(self.sender_client)["no_show_reason"] == "pickup_time_unknown"
        Deal.objects.filter(pk=self.deal.pk).update(
            funded_at=None, funded_scheduled_arrival_floor_at=None
        )
        assert self.read(self.sender_client)["no_show_reason"] == "deal_not_funded"

    def test_only_the_party_left_waiting_reports_it(self):
        self.pickup_passed()
        response = self.report(self.traveler_client, Kind.TRAVELER_NO_SHOW)
        assert response.status_code == 403
        assert response.json()["code"] == "problem_kind_not_allowed_for_role"
        response = self.report(self.sender_client, Kind.SENDER_UNAVAILABLE)
        assert response.json()["code"] == "problem_kind_not_allowed_for_role"

    def test_one_open_no_show_report_per_person(self):
        self.pickup_passed()
        first = self.report(self.traveler_client, Kind.SENDER_UNAVAILABLE)
        again = self.report(self.traveler_client, Kind.SENDER_UNAVAILABLE, "still here")

        assert again.status_code == 200
        assert again.json()["problem"]["id"] == first.json()["problem"]["id"]
        body = self.read(self.traveler_client)
        assert (body["can_report_no_show"], body["no_show_reason"]) == (
            False,
            "already_reported",
        )
        # The other side may report their own.
        assert self.report(self.sender_client, Kind.TRAVELER_NO_SHOW).status_code == 201
        assert ShipmentProblem.objects.filter(status=Status.ESCALATED).count() == 2

    def test_both_kinds_escalate_and_tell_the_other_person(self):
        self.pickup_passed()
        self.report(self.sender_client, Kind.TRAVELER_NO_SHOW)
        problem = ShipmentProblem.objects.get()

        assert problem.status == Status.ESCALATED
        assert (
            Notification.objects.get(channel="deal.problem_reported").recipient_id
            == self.traveler.pk
        )

    def test_a_report_records_no_no_show_and_refunds_nothing(self):
        self.pickup_passed()
        self.report(self.sender_client, Kind.TRAVELER_NO_SHOW)
        self.deal.refresh_from_db()

        assert self.deal.no_show_party == ""
        assert self.deal.status == Deal.Status.FUNDED
        assert not DealEvent.objects.filter(
            deal=self.deal, kind=DealEvent.Kind.NO_SHOW_RECORDED
        ).exists()
        assert not PaymentRefund.objects.filter(order__deal=self.deal).exists()


# ---------------------------------------------------------------------------
# Staff
# ---------------------------------------------------------------------------


@override_settings(STORAGES=STATIC_STORES)
class StaffTests(ProblemWorld, TestCase):
    def setUp(self):
        self.build_problem_world()
        self.ops = self.staff_user("l9a-ops@example.com", "ops")
        self.support = self.staff_user("l9a-support@example.com", "support")
        self.finance = self.staff_user("l9a-finance@example.com", "finance")
        self.pickup_passed()
        self.report(self.sender_client, Kind.TRAVELER_NO_SHOW, "Nobody at the gate")
        self.problem = ShipmentProblem.objects.get()

    def test_acknowledge_and_close_need_a_reason_and_are_audited(self):
        before = deal_row(self.deal)
        with self.assertRaises(ProblemError) as raised:
            acknowledge_problem(problem_id=self.problem.pk, actor=self.ops, reason="  ")
        assert raised.exception.code == "reason_required"

        acknowledge_problem(
            problem_id=self.problem.pk, actor=self.ops, reason="Calling both"
        )
        self.problem.refresh_from_db()
        assert self.problem.status == Status.ACKNOWLEDGED
        close_problem(
            problem_id=self.problem.pk, actor=self.ops, reason="Sorted out in chat"
        )
        self.problem.refresh_from_db()
        assert self.problem.status == Status.CLOSED
        assert self.problem.closed_reason == "Sorted out in chat"

        audits = AdminAuditLog.objects.filter(target_type="problems.shipmentproblem")
        assert sorted(audits.values_list("action", flat=True)) == [
            "problem.acknowledged",
            "problem.closed",
        ]
        assert all(row.reason for row in audits)
        assert deal_row(self.deal) == before
        # Parties see the new state, never the staff reason.
        body = self.read(self.sender_client)
        assert body["results"][0]["status"] == Status.CLOSED
        assert "Sorted out" not in json.dumps(body)

    def test_a_role_without_manage_disputes_cannot_act(self):
        for actor in (self.support, self.finance):
            with self.assertRaises(ProblemError) as raised:
                close_problem(problem_id=self.problem.pk, actor=actor, reason="No")
            assert raised.exception.code == "not_permitted"

    def test_the_queue_lists_escalated_reports_first(self):
        self.report(self.traveler_client, Kind.CUSTOMS_DELAY)
        staff_login(self.client, self.support)
        response = self.client.get(reverse("admin_console:problems"))
        html = response.content.decode()

        assert response.status_code == 200
        assert html.index("The traveler did not come") < html.index("Customs delay")
        assert tracking.for_deal(self.deal) in html
        attention = self.client.get(
            reverse("admin_console:problems"), {"attention": "1"}
        )
        assert "Customs delay" not in attention.content.decode()
        overview = self.client.get(reverse("admin_console:overview")).content.decode()
        assert "Problems to look at" in overview

    def test_the_queue_finds_a_report_by_tracking_number(self):
        staff_login(self.client, self.support)
        number = tracking.for_deal(self.deal)
        found = self.client.get(
            reverse("admin_console:problems"), {"q": number.lower()}
        )
        assert "The traveler did not come" in found.content.decode()

    def test_the_no_show_link_carries_the_deal_and_the_party_and_nothing_else(self):
        staff_login(self.client, self.ops)
        html = self.client.get(
            reverse("admin_console:problem-detail", args=(self.problem.pk,))
        ).content.decode()
        expected = f"{reverse('admin_console:deal-no-show', args=(self.deal.pk,))}?party=traveler"
        assert f'href="{expected}"' in html
        # Support cannot record a no-show, so it is not offered a link.
        staff_login(self.client, self.support)
        html = self.client.get(
            reverse("admin_console:problem-detail", args=(self.problem.pk,))
        ).content.decode()
        assert "?party=" not in html
        assert 'value="acknowledge"' not in html

    def test_the_console_acknowledges_with_a_reason(self):
        staff_login(self.client, self.ops)
        url = reverse("admin_console:problem-detail", args=(self.problem.pk,))
        missing = self.client.post(
            url, {"action": "acknowledge", "acknowledge-reason": ""}
        )
        assert missing.status_code == 200
        self.problem.refresh_from_db()
        assert self.problem.status == Status.ESCALATED

        done = self.client.post(
            url, {"action": "acknowledge", "acknowledge-reason": "On it"}
        )
        assert done.status_code == 302
        self.problem.refresh_from_db()
        assert self.problem.status == Status.ACKNOWLEDGED
        # Support may read the report but not change it.
        staff_login(self.client, self.support)
        refused = self.client.post(url, {"action": "close", "close-reason": "No"})
        assert refused.status_code == 403

    def test_recording_the_no_show_closes_the_report_with_its_audit_row(self):
        self.report(self.traveler_client, Kind.SENDER_UNAVAILABLE)
        staff_login(self.client, self.ops)
        page = reverse("admin_console:deal-no-show", args=(self.deal.pk,))
        form = self.client.get(page, {"party": "traveler"}).content.decode()
        assert 'value="traveler" required id="id_party_1" checked' in form

        response = self.client.post(
            page, {"party": "traveler", "note": "Confirmed by phone"}
        )
        assert response.status_code == 302
        self.deal.refresh_from_db()
        assert self.deal.no_show_party == "traveler"
        audit = AdminAuditLog.objects.get(action="deal.no_show_recorded")
        reports = ShipmentProblem.objects.filter(deal=self.deal)
        assert {row.status for row in reports} == {Status.CLOSED}
        assert {row.closed_by_audit_id for row in reports} == {audit.pk}

    def test_the_api_no_show_closes_reports_too_and_a_replay_writes_no_second_audit(
        self,
    ):
        api = APIClient()
        staff_login(api, self.ops)
        url = reverse("admin-deal-no-show", args=(self.deal.pk,))
        first = api.post(url, {"party": "traveler", "note": "Checked"}, format="json")
        again = api.post(url, {"party": "traveler", "note": "Checked"}, format="json")

        assert (first.status_code, again.status_code) == (200, 200)
        assert first.json()["closed_problem_ids"] == [self.problem.pk]
        assert AdminAuditLog.objects.filter(action="deal.no_show_recorded").count() == 1
        self.problem.refresh_from_db()
        assert self.problem.status == Status.CLOSED

    def test_the_deal_page_lists_problems(self):
        staff_login(self.client, self.ops)
        html = self.client.get(
            reverse("admin_console:deal-detail", args=(self.deal.pk,))
        ).content.decode()
        assert "The traveler did not come" in html
        assert reverse("admin_console:deal-no-show", args=(self.deal.pk,)) in html


# ---------------------------------------------------------------------------
# The package's own boundary (plan L9A "Done when")
# ---------------------------------------------------------------------------


def test_problems_and_schedule_changes_never_write_a_deal_status_or_transition():
    root = Path(__file__).resolve().parents[2]
    sources = [
        *sorted((root / "problems").glob("*.py")),
        root / "trips" / "schedule_changes.py",
    ]
    forbidden = (
        "deal.status =",
        ".status = Deal.",
        "update(status",
        "_set_status(",
        "apply_pickup",
        "apply_delivery",
        "apply_completed",
        "apply_disputed",
        "apply_early_arrival",
        "cancel_funded_deal",
        "record_no_show(",
    )
    for path in sources:
        text = path.read_text()
        for needle in forbidden:
            assert needle not in text, f"{path.name}: {needle}"
