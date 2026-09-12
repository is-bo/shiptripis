"""Phase I1A: journey timing, early arrival and the payout floor.

Grouped by the thing being protected rather than by module, because every one of
these is a rule somebody could plausibly remove and still see a green suite:

* the funded arrival basis is frozen, and a Journey edit cannot move it;
* the payout floor is `max(actual + protection, funded arrival)`, on all four of
  the worked cases;
* "materially early" is one server-owned threshold, not a client's opinion;
* the sender confirms, and confirming an arrival is not confirming a delivery;
* a delivered Deal stops being an active shipment;
* the funded route reaches the sender and nothing else does;
* every action is idempotent and authorized.

Every fixture drives the production services through `phase4_factories`, so a
regression in a service breaks the fixture loudly rather than quietly passing.
"""

from __future__ import annotations

import base64
import json
import unittest
from datetime import timedelta

from django.db import connection
from django.test import TestCase, override_settings
from django.test.client import Client
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.deals import arrival as arrival_domain
from apps.deals.activity import ACTIVE, CANCELLED, COMPLETED, activity_state
from apps.deals.arrival import (
    ArrivalError,
    MATERIAL_EARLY_ARRIVAL_THRESHOLD_SECONDS,
    decide_early_arrival,
    payout_release_gate_at,
    report_early_arrival,
)
from apps.deals.models import Deal, DealArrivalReport, DealEvent
from apps.finance.models import FinanceHold, Payout, ScheduledJob
from apps.finance.payout_release import evaluate_payout_release
from apps.handover.models import DealHandoverCode
from apps.handover.services import HandoverError, reveal_code
from apps.trips.models import JourneyLeg

from .phase4_factories import (
    Phase4Scenario,
    confirm_delivery,
    confirm_pickup,
    delivered_scenario,
    freeze_at,
    fund_scenario,
    past_protection,
    record_recipient,
    release_delivery_code,
    rewind_deal,
)

POSTGRES_ONLY = unittest.skipUnless(
    connection.vendor == "postgresql",
    "Partial unique constraints and row locking are PostgreSQL behaviour.",
)


def carrying_scenario(client, *, prefix: str) -> Phase4Scenario:
    """Funded, recipient recorded, picked up: the parcel is in carriage."""

    scenario = fund_scenario(client, prefix=prefix)
    record_recipient(scenario)
    confirm_pickup(scenario)
    return scenario


def client_for(user) -> APIClient:
    """An authenticated API client. The project authenticates with JWT, so a
    session login would be refused by every endpoint under test."""

    client = APIClient()
    client.force_authenticate(user=user)
    return client


#: What a successful release looks like on either payout generation. The legacy
#: row answers `released`; a snapshot row answers `payout_<status>`, and which
#: one exists depends on `PAYOUT_PROFILES_ENABLED` rather than on anything I1A
#: decides.
def assert_released(outcome: str) -> None:
    assert outcome == "released" or outcome.startswith("payout_"), outcome


class FundedArrivalSnapshotTests(TestCase):
    """What funding freezes, and that nothing afterwards can move it."""

    def setUp(self):
        self.client = Client()

    def test_funding_freezes_the_arrival_basis_with_provenance(self):
        scenario = fund_scenario(self.client, prefix="i1a-snap")
        deal = scenario.deal
        snapshot = deal.arrival_snapshot

        assert deal.funded_scheduled_arrival_floor_at is not None
        assert snapshot["policy_version"] == arrival_domain.ARRIVAL_POLICY_VERSION
        assert snapshot["provenance"] == arrival_domain.PROVENANCE_FUNDING
        assert snapshot["basis"] in (
            arrival_domain.BASIS_MATCH_DELIVERY,
            arrival_domain.BASIS_ALLOCATED_LEG_ARRIVAL,
        )
        assert snapshot["stored_timezone"] == "UTC"
        assert snapshot["snapshot_at"]
        assert snapshot["journey_id"] == deal.journey_id
        assert snapshot["match_id"] == deal.match_id
        assert (
            snapshot["material_early_threshold_seconds"]
            == MATERIAL_EARLY_ARRIVAL_THRESHOLD_SECONDS
        )
        # The stored instant and the column agree, to the second.
        assert (
            arrival_domain.parse_instant(snapshot["scheduled_arrival_at"])
            == deal.funded_scheduled_arrival_floor_at
        )

    def test_the_frozen_route_is_only_this_deals_carrying_legs(self):
        scenario = fund_scenario(self.client, prefix="i1a-route-snap")
        legs = scenario.deal.arrival_snapshot["route"]
        allocated = {
            row.journey_leg_id for row in scenario.deal.leg_allocations.all()
        }

        assert {row["leg_id"] for row in legs} == allocated
        assert [row["position"] for row in legs] == sorted(
            row["position"] for row in legs
        )
        # Identifiers and times only. A polyline or a measured distance in here
        # would leak the traveler's exact route to the sender's projection.
        for row in legs:
            assert set(row) == {
                "leg_id",
                "position",
                "mode",
                "origin_place_id",
                "destination_place_id",
                "origin_location_id",
                "destination_location_id",
                "depart_at",
                "arrive_at",
            }

    def test_funding_records_the_basis_on_the_shared_timeline(self):
        scenario = fund_scenario(self.client, prefix="i1a-snap-event")
        event = scenario.deal.events.filter(
            kind=DealEvent.Kind.ARRIVAL_SNAPSHOT_FROZEN
        ).get()

        assert event.payload["basis"] == scenario.deal.arrival_snapshot["basis"]
        assert (
            event.payload["scheduled_arrival_at"]
            == scenario.deal.funded_scheduled_arrival_floor_at.isoformat()
        )

    def test_a_journey_schedule_edit_after_funding_cannot_move_the_floor(self):
        """Both halves: the API refuses, and the snapshot holds anyway."""

        scenario = fund_scenario(self.client, prefix="i1a-edit")
        deal = scenario.deal
        frozen_floor = deal.funded_scheduled_arrival_floor_at
        frozen_route = list(deal.arrival_snapshot["route"])

        # 1. The route is load-bearing for a funded Deal, so editing it is
        #    refused by name rather than silently ignored.
        from apps.trips.services import journey_editability

        verdict = journey_editability(scenario.base.journey, actor=scenario.traveler)
        assert verdict.editable is False
        # A published journey is refused on its status; a draft carrying a Deal
        # is refused on the dependency. Either way the refusal is named.
        assert verdict.code in (
            "journey_not_editable",
            "journey_has_dependent_state",
        )

        # 2. And if a leg time moves anyway -- an operator, a data fix, a future
        #    feature -- the funded Deal does not follow it. This is the guarantee
        #    the snapshot exists for.
        JourneyLeg.objects.filter(pk=scenario.base.leg.pk).update(
            depart_at=scenario.base.leg.depart_at + timedelta(days=9),
            arrive_at=scenario.base.leg.arrive_at + timedelta(days=9),
        )
        deal.refresh_from_db()
        assert deal.funded_scheduled_arrival_floor_at == frozen_floor
        assert deal.arrival_snapshot["route"] == frozen_route
        assert payout_release_gate_at(deal) is None  # no delivery yet


class PayoutFloorTests(TestCase):
    """The four worked cases from the I1A contract, and the null-floor case."""

    def setUp(self):
        self.client = Client()

    @staticmethod
    def _gate(*, scheduled_offset: timedelta, delivery_offset: timedelta):
        """Build the two stored columns directly and ask for the gate.

        A unit test of the formula, not of the lifecycle: the lifecycle tests
        below drive real services. Offsets are relative to one fixed instant so
        the arithmetic in the assertion is the arithmetic in the contract.
        """

        base = timezone.now()
        deal = Deal(
            delivery_confirmed_at=base + delivery_offset,
            protection_ends_at=base + delivery_offset + timedelta(hours=48),
            funded_scheduled_arrival_floor_at=base + scheduled_offset,
        )
        return base, deal

    def test_on_time_delivery_is_governed_by_protection(self):
        # Scheduled 10 Sep 18:00, delivered 10 Sep 18:15 -> 12 Sep 18:15.
        base, deal = self._gate(
            scheduled_offset=timedelta(0),
            delivery_offset=timedelta(minutes=15),
        )
        assert payout_release_gate_at(deal) == base + timedelta(
            minutes=15, hours=48
        )
        assert arrival_domain.payout_release_gate_basis(deal) == "delivery_protection"

    def test_early_delivery_still_clears_protection_when_that_is_later(self):
        # Scheduled 10 Sep 18:00, delivered 9 Sep 12:00. actual+48h = 11 Sep
        # 12:00, which is after the floor, so protection binds.
        base, deal = self._gate(
            scheduled_offset=timedelta(0),
            delivery_offset=timedelta(hours=-30),
        )
        assert payout_release_gate_at(deal) == base + timedelta(hours=18)
        assert arrival_domain.payout_release_gate_basis(deal) == "delivery_protection"

    def test_very_early_delivery_is_held_to_the_funded_schedule(self):
        # Scheduled 15 Sep 18:00, delivered 10 Sep 12:00. actual+48h = 12 Sep
        # 12:00, floor = 15 Sep 18:00 -> the floor binds.
        base, deal = self._gate(
            scheduled_offset=timedelta(days=5, hours=6),
            delivery_offset=timedelta(0),
        )
        assert payout_release_gate_at(deal) == base + timedelta(days=5, hours=6)
        assert arrival_domain.payout_release_gate_basis(deal) == "schedule_floor"

    def test_late_delivery_still_gets_the_whole_protection_window(self):
        # Scheduled 10 Sep 18:00, delivered 12 Sep 10:00 -> 14 Sep 10:00.
        base, deal = self._gate(
            scheduled_offset=timedelta(0),
            delivery_offset=timedelta(days=1, hours=16),
        )
        assert payout_release_gate_at(deal) == base + timedelta(
            days=1, hours=16 + 48
        )
        assert arrival_domain.payout_release_gate_basis(deal) == "delivery_protection"

    def test_a_deal_with_no_recoverable_schedule_keeps_the_pre_i1a_rule(self):
        base, deal = self._gate(
            scheduled_offset=timedelta(days=30), delivery_offset=timedelta(0)
        )
        deal.funded_scheduled_arrival_floor_at = None
        assert payout_release_gate_at(deal) == deal.protection_ends_at

    def test_no_gate_exists_before_a_confirmed_delivery(self):
        deal = Deal(funded_scheduled_arrival_floor_at=timezone.now())
        assert payout_release_gate_at(deal) is None


class PayoutReleaseGateTests(TestCase):
    """The gate as the release service actually applies it."""

    def setUp(self):
        self.client = Client()

    def test_protection_expiry_alone_does_not_release_a_very_early_delivery(self):
        scenario = delivered_scenario(self.client, prefix="i1a-veryearly")
        deal = scenario.deal
        # Protection has closed, and this Deal was delivered five days before it
        # was ever scheduled to arrive. `past_protection` moves every stored
        # deadline including the floor, so the floor is set afterwards.
        past_protection(scenario)
        Deal.objects.filter(pk=deal.pk).update(
            funded_scheduled_arrival_floor_at=timezone.now() + timedelta(days=5)
        )
        deal.refresh_from_db()

        result = evaluate_payout_release(deal_id=deal.pk)
        assert result == "scheduled_arrival_floor_open"

        payout = Payout.objects.get(deal_id=deal.pk)
        assert payout.status == Payout.Status.NOT_ELIGIBLE
        assert payout.eligible_at is None
        # No block reason: the traveler has nothing to fix, and calling this a
        # blocked payout would send them to a setup screen for no reason.
        assert payout.block_reason == ""
        assert payout.next_action_at is not None

        # The shipment itself is finished and reported as such.
        deal.refresh_from_db()
        assert deal.status == Deal.Status.COMPLETED
        assert activity_state(deal) == COMPLETED

    def test_the_release_job_is_rescheduled_to_the_floor_not_retried_blindly(self):
        scenario = delivered_scenario(self.client, prefix="i1a-jobfloor")
        deal = scenario.deal
        floor = timezone.now() + timedelta(days=4)
        past_protection(scenario)
        Deal.objects.filter(pk=deal.pk).update(
            funded_scheduled_arrival_floor_at=floor
        )

        evaluate_payout_release(deal_id=deal.pk)
        job = ScheduledJob.objects.get(key=f"protection_expiry:{deal.pk}")
        assert job.status == ScheduledJob.Status.PENDING
        assert abs((job.run_at - floor).total_seconds()) < 2

        # The handler agrees: it defers to the gate rather than consuming its
        # retry budget every few minutes for four days.
        from apps.finance.jobs import run_job

        outcome = run_job(job)
        job.refresh_from_db()
        assert outcome == "deferred"
        assert job.attempts == 0
        assert job.last_result == "deferred:scheduled_arrival_floor_open"
        assert job.run_at > timezone.now() + timedelta(days=3)

    def test_the_floor_releases_once_it_passes_and_records_its_basis(self):
        scenario = delivered_scenario(self.client, prefix="i1a-floorpass")
        deal = scenario.deal
        past_protection(scenario)
        # A floor in the past: honest early delivery, schedule already reached.
        Deal.objects.filter(pk=deal.pk).update(
            funded_scheduled_arrival_floor_at=timezone.now() - timedelta(minutes=5)
        )
        deal.refresh_from_db()

        assert_released(evaluate_payout_release(deal_id=deal.pk))
        payout = Payout.objects.get(deal_id=deal.pk)
        assert payout.eligible_at is not None
        assert payout.eligibility_basis == "delivery_protection"

    def test_a_floor_bound_release_names_the_schedule_as_its_basis(self):
        scenario = delivered_scenario(self.client, prefix="i1a-floorbasis")
        deal = scenario.deal
        past_protection(scenario)
        # Move everything a further two hours into the past, so there is room
        # for a floor that is *after* the protection deadline and still elapsed.
        rewind_deal(deal, timedelta(hours=2))
        deal.refresh_from_db()
        Deal.objects.filter(pk=deal.pk).update(
            funded_scheduled_arrival_floor_at=deal.protection_ends_at
            + timedelta(hours=1)
        )
        deal.refresh_from_db()
        assert deal.protection_ends_at < deal.funded_scheduled_arrival_floor_at
        assert deal.funded_scheduled_arrival_floor_at < timezone.now()

        evaluate_payout_release(deal_id=deal.pk)
        payout = Payout.objects.get(deal_id=deal.pk)
        assert payout.eligibility_basis == "schedule_floor"

    def test_repeated_evaluation_below_the_floor_changes_nothing(self):
        scenario = delivered_scenario(self.client, prefix="i1a-flooridem")
        deal = scenario.deal
        past_protection(scenario)
        Deal.objects.filter(pk=deal.pk).update(
            funded_scheduled_arrival_floor_at=timezone.now() + timedelta(days=3)
        )

        first = evaluate_payout_release(deal_id=deal.pk)
        events_after_first = deal.events.count()
        second = evaluate_payout_release(deal_id=deal.pk)

        assert first == second == "scheduled_arrival_floor_open"
        assert deal.events.count() == events_after_first
        assert Payout.objects.get(deal_id=deal.pk).status == Payout.Status.NOT_ELIGIBLE
        assert (
            ScheduledJob.objects.filter(
                key=f"protection_expiry:{deal.pk}"
            ).count()
            == 1
        )

    def test_the_existing_48_hour_protection_is_unchanged(self):
        scenario = delivered_scenario(self.client, prefix="i1a-48h")
        deal = scenario.deal

        assert deal.protection_ends_at - deal.delivery_confirmed_at == timedelta(
            seconds=172_800
        )
        assert evaluate_payout_release(deal_id=deal.pk) == "protection_open"


#: The settings the deployed service runs with. `PAYOUT_PROFILES_ENABLED` decides
#: which payout generation `ensure_payout_for_deal` creates, and the H1+ snapshot
#: row is the one production has -- so the finance-hold surface and the
#: `eligibility_basis` audit field are asserted against that row, not the legacy
#: one the default test settings would otherwise produce.
SNAPSHOT_PAYOUT_SETTINGS = dict(
    PAYOUT_PROFILES_ENABLED=True,
    PAYOUT_DATA_KEYRING=json.dumps(
        {"i1a-key": base64.b64encode(b"i" * 32).decode()}
    ),
    PAYOUT_DATA_ACTIVE_KEY_ID="i1a-key",
    PAYOUT_ACCOUNT_FINGERPRINT_KEY=base64.b64encode(b"f" * 32).decode(),
    STRIPE_CONNECT_ALLOWED_COUNTRIES=["FR"],
)


@override_settings(**SNAPSHOT_PAYOUT_SETTINGS)
class SnapshotPayoutFloorTests(TestCase):
    """The floor against the payout row production actually creates."""

    def setUp(self):
        self.client = Client()

    def _delivered(self, prefix: str):
        """A delivered Deal whose payout is an H1+ snapshot row.

        With payout profiles on, funding refuses until the traveler has declared
        a payout preference -- H1's own precondition -- so the preference is set
        before the scenario is funded rather than patched in afterwards.
        """

        from apps.finance.payout_profiles import set_preference
        from apps.finance.tests.factories import build_scenario, pay_order_with_mock

        from .phase4_factories import (
            confirm_delivery as _confirm,
            confirm_pickup as _pickup,
            enable_mock_rail,
            record_recipient as _recipient,
            release_delivery_code as _release,
        )

        enable_mock_rail()
        base = build_scenario(prefix=prefix)
        base.accept(reward_eur_cents=2_000)
        set_preference(
            actor=base.traveler,
            currency="DZD",
            enabled=True,
            expected_revision=0,
        )
        pay_order_with_mock(self.client, base.balance_order())
        base.deal.refresh_from_db()
        assert base.deal.status == Deal.Status.FUNDED, base.deal.status
        scenario = Phase4Scenario(base=base)
        _recipient(scenario)
        _pickup(scenario)
        _release(scenario)
        _confirm(scenario)
        return scenario

    def test_a_finance_hold_still_blocks_after_the_floor_passes(self):
        scenario = self._delivered("i1a-hold")
        deal = scenario.deal
        past_protection(scenario)
        deal.refresh_from_db()
        payout = Payout.objects.get(deal_id=deal.pk)
        assert payout.snapshot_version, "This class exists to exercise H1+ rows."
        FinanceHold.objects.create(
            payout=payout,
            kind="manual",
            reason_code="i1a_regression",
            source_reference="i1a",
            opened_by=scenario.admin,
        )

        assert evaluate_payout_release(deal_id=deal.pk) == "finance_hold_active"

    def test_a_hold_outranks_an_elapsed_floor(self):
        """Order matters: the floor opening must not bypass an existing hold."""

        scenario = self._delivered("i1a-hold-floor")
        deal = scenario.deal
        past_protection(scenario)
        rewind_deal(deal, timedelta(hours=2))
        deal.refresh_from_db()
        Deal.objects.filter(pk=deal.pk).update(
            funded_scheduled_arrival_floor_at=deal.protection_ends_at
            + timedelta(hours=1)
        )
        FinanceHold.objects.create(
            payout=Payout.objects.get(deal_id=deal.pk),
            kind="compliance",
            reason_code="i1a_regression",
            source_reference="i1a",
            opened_by=scenario.admin,
        )

        assert evaluate_payout_release(deal_id=deal.pk) == "finance_hold_active"
        assert Payout.objects.get(deal_id=deal.pk).eligible_at is None

    def test_the_snapshot_row_records_the_schedule_as_its_basis(self):
        scenario = self._delivered("i1a-snapshot-basis")
        deal = scenario.deal
        past_protection(scenario)
        rewind_deal(deal, timedelta(hours=2))
        deal.refresh_from_db()
        Deal.objects.filter(pk=deal.pk).update(
            funded_scheduled_arrival_floor_at=deal.protection_ends_at
            + timedelta(hours=1)
        )

        assert evaluate_payout_release(deal_id=deal.pk).startswith("payout_")
        payout = Payout.objects.get(deal_id=deal.pk)
        assert payout.eligible_at is not None
        assert payout.eligibility_basis == "schedule_floor"

    def test_the_snapshot_row_waits_for_a_future_floor(self):
        scenario = self._delivered("i1a-snapshot-wait")
        deal = scenario.deal
        past_protection(scenario)
        Deal.objects.filter(pk=deal.pk).update(
            funded_scheduled_arrival_floor_at=timezone.now() + timedelta(days=6)
        )

        assert evaluate_payout_release(deal_id=deal.pk) == (
            "scheduled_arrival_floor_open"
        )
        payout = Payout.objects.get(deal_id=deal.pk)
        assert payout.status == Payout.Status.NOT_ELIGIBLE
        assert payout.eligible_at is None
        assert payout.next_action_at is not None


class MaterialEarlyArrivalTests(TestCase):
    """One threshold, owned by the server, applied under the lock."""

    def setUp(self):
        self.client = Client()

    def test_a_trivially_early_arrival_is_refused_and_explained(self):
        scenario = carrying_scenario(self.client, prefix="i1a-trivial")
        deal = scenario.deal
        # One hour before the funded arrival: real, but not material.
        Deal.objects.filter(pk=deal.pk).update(
            funded_scheduled_arrival_floor_at=timezone.now() + timedelta(hours=1)
        )
        deal.refresh_from_db()

        with self.assertRaises(ArrivalError) as caught:
            report_early_arrival(deal_id=deal.pk, actor_id=scenario.traveler.pk)
        assert caught.exception.code == "not_materially_early"
        assert caught.exception.details()["threshold_seconds"] == (
            MATERIAL_EARLY_ARRIVAL_THRESHOLD_SECONDS
        )
        assert not DealArrivalReport.objects.filter(deal_id=deal.pk).exists()

    def test_the_projection_refuses_the_action_before_the_client_can_offer_it(self):
        scenario = carrying_scenario(self.client, prefix="i1a-avail")
        deal = scenario.deal
        Deal.objects.filter(pk=deal.pk).update(
            funded_scheduled_arrival_floor_at=timezone.now() + timedelta(hours=2)
        )
        deal.refresh_from_db()

        projection = arrival_domain.arrival_projection(
            deal=deal, viewer_id=scenario.traveler.pk
        )
        assert projection["report_available"] is False
        assert projection["report_unavailable_reason"] == "not_materially_early"
        assert projection["is_materially_early_now"] is False
        assert projection["available_actions"] == []

    def test_a_materially_early_arrival_is_offered_and_accepted(self):
        scenario = carrying_scenario(self.client, prefix="i1a-material")
        deal = scenario.deal
        Deal.objects.filter(pk=deal.pk).update(
            funded_scheduled_arrival_floor_at=timezone.now() + timedelta(days=3)
        )
        deal.refresh_from_db()

        projection = arrival_domain.arrival_projection(
            deal=deal, viewer_id=scenario.traveler.pk
        )
        assert projection["report_available"] is True
        assert projection["is_materially_early_now"] is True
        assert projection["available_actions"] == ["report_early_arrival"]

        result = report_early_arrival(
            deal_id=deal.pk, actor_id=scenario.traveler.pk
        )
        report = DealArrivalReport.objects.get(pk=result.report_id)
        assert result.changed is True
        assert report.status == DealArrivalReport.Status.PENDING_CONFIRMATION
        assert report.early_by_seconds > MATERIAL_EARLY_ARRIVAL_THRESHOLD_SECONDS
        assert report.threshold_seconds == MATERIAL_EARLY_ARRIVAL_THRESHOLD_SECONDS
        assert report.scheduled_arrival_at == deal.funded_scheduled_arrival_floor_at
        assert report.reported_deal_status == Deal.Status.IN_TRANSIT

    def test_the_threshold_is_read_from_the_deals_own_snapshot(self):
        """A later change to the constant cannot reinterpret a funded Deal."""

        scenario = carrying_scenario(self.client, prefix="i1a-frozenthreshold")
        deal = scenario.deal
        snapshot = dict(deal.arrival_snapshot)
        snapshot["material_early_threshold_seconds"] = 60
        Deal.objects.filter(pk=deal.pk).update(
            arrival_snapshot=snapshot,
            funded_scheduled_arrival_floor_at=timezone.now() + timedelta(minutes=30),
        )
        deal.refresh_from_db()

        assert arrival_domain.material_threshold(deal) == 60
        result = report_early_arrival(
            deal_id=deal.pk, actor_id=scenario.traveler.pk
        )
        assert DealArrivalReport.objects.get(pk=result.report_id).threshold_seconds == 60

    def test_an_arrival_cannot_be_reported_before_the_parcel_is_collected(self):
        scenario = fund_scenario(self.client, prefix="i1a-precarriage")
        record_recipient(scenario)
        Deal.objects.filter(pk=scenario.deal.pk).update(
            funded_scheduled_arrival_floor_at=timezone.now() + timedelta(days=2)
        )

        with self.assertRaises(ArrivalError) as caught:
            report_early_arrival(
                deal_id=scenario.deal.pk, actor_id=scenario.traveler.pk
            )
        assert caught.exception.code == "arrival_requires_carriage"

    def test_an_arrival_cannot_be_reported_after_delivery(self):
        scenario = delivered_scenario(self.client, prefix="i1a-postdelivery")
        Deal.objects.filter(pk=scenario.deal.pk).update(
            funded_scheduled_arrival_floor_at=timezone.now() + timedelta(days=2)
        )

        with self.assertRaises(ArrivalError) as caught:
            report_early_arrival(
                deal_id=scenario.deal.pk, actor_id=scenario.traveler.pk
            )
        assert caught.exception.code == "delivery_already_confirmed"


class EarlyArrivalFlowTests(TestCase):
    """Report, confirm, decline -- and what each one is not."""

    def setUp(self):
        self.client = Client()

    def _reported(self, prefix: str):
        scenario = carrying_scenario(self.client, prefix=prefix)
        Deal.objects.filter(pk=scenario.deal.pk).update(
            funded_scheduled_arrival_floor_at=timezone.now() + timedelta(days=4)
        )
        result = report_early_arrival(
            deal_id=scenario.deal.pk, actor_id=scenario.traveler.pk
        )
        return scenario, DealArrivalReport.objects.get(pk=result.report_id)

    def test_a_report_waits_for_the_sender_and_never_self_confirms(self):
        scenario, report = self._reported("i1a-pending")
        deal = scenario.deal

        assert report.status == DealArrivalReport.Status.PENDING_CONFIRMATION
        assert deal.arrival_confirmed_at is None
        projection = arrival_domain.arrival_projection(
            deal=deal, viewer_id=scenario.traveler.pk
        )
        assert projection["state"] == "pending_confirmation"
        # The traveler is not offered the confirmation of their own claim.
        assert projection["available_actions"] == []

        sender_view = arrival_domain.arrival_projection(
            deal=deal, viewer_id=scenario.sender.pk
        )
        assert sender_view["available_actions"] == [
            "confirm_early_arrival",
            "decline_early_arrival",
        ]

    def test_the_sender_confirms_and_the_deal_records_an_arrival_not_a_delivery(self):
        scenario, report = self._reported("i1a-confirm")
        deal = scenario.deal

        result = decide_early_arrival(
            deal_id=deal.pk, actor_id=scenario.sender.pk, confirm=True
        )
        deal.refresh_from_db()
        report.refresh_from_db()

        assert result.changed is True
        assert report.status == DealArrivalReport.Status.CONFIRMED
        assert report.decided_by_id == scenario.sender.pk
        assert deal.arrival_confirmed_at is not None

        # The three things a confirmed arrival is emphatically not.
        assert deal.delivery_confirmed_at is None
        assert deal.protection_ends_at is None
        assert deal.status == Deal.Status.IN_TRANSIT
        assert Payout.objects.get(deal_id=deal.pk).status == (
            Payout.Status.NOT_ELIGIBLE
        )

        event = deal.events.filter(
            kind=DealEvent.Kind.EARLY_ARRIVAL_CONFIRMED
        ).get()
        assert event.payload["starts_protection_window"] is False
        assert event.payload["releases_delivery_code"] is False

    def test_confirmation_does_not_move_the_payout_floor(self):
        scenario, _ = self._reported("i1a-confirm-floor")
        deal = scenario.deal
        before = deal.funded_scheduled_arrival_floor_at

        decide_early_arrival(
            deal_id=deal.pk, actor_id=scenario.sender.pk, confirm=True
        )
        deal.refresh_from_db()
        assert deal.funded_scheduled_arrival_floor_at == before

        # And carrying the Deal all the way to a delivered, protection-expired
        # state still leaves the floor in charge.
        release_delivery_code(scenario)
        confirm_delivery(scenario)
        past_protection(scenario)
        Deal.objects.filter(pk=deal.pk).update(
            funded_scheduled_arrival_floor_at=before
        )
        deal.refresh_from_db()
        assert deal.funded_scheduled_arrival_floor_at == before
        assert evaluate_payout_release(deal_id=deal.pk) == (
            "scheduled_arrival_floor_open"
        )

    def test_the_sender_may_decline_and_the_traveler_may_report_again(self):
        scenario, report = self._reported("i1a-decline")
        deal = scenario.deal

        decide_early_arrival(
            deal_id=deal.pk, actor_id=scenario.sender.pk, confirm=False
        )
        report.refresh_from_db()
        deal.refresh_from_db()
        assert report.status == DealArrivalReport.Status.DECLINED
        assert deal.arrival_confirmed_at is None
        assert arrival_domain.arrival_projection(
            deal=deal, viewer_id=scenario.traveler.pk
        )["state"] == "declined"

        again = report_early_arrival(
            deal_id=deal.pk, actor_id=scenario.traveler.pk
        )
        assert again.changed is True
        assert again.report_id != report.pk

    def test_a_duplicate_report_resolves_to_the_one_open_claim(self):
        scenario, report = self._reported("i1a-dupreport")
        deal = scenario.deal
        events_before = deal.events.count()

        repeat = report_early_arrival(
            deal_id=deal.pk, actor_id=scenario.traveler.pk
        )
        assert repeat.changed is False
        assert repeat.report_id == report.pk
        assert DealArrivalReport.objects.filter(deal_id=deal.pk).count() == 1
        assert deal.events.count() == events_before

    def test_a_duplicate_confirmation_is_safe(self):
        scenario, report = self._reported("i1a-dupconfirm")
        deal = scenario.deal

        first = decide_early_arrival(
            deal_id=deal.pk, actor_id=scenario.sender.pk, confirm=True
        )
        confirmed_at = Deal.objects.values_list(
            "arrival_confirmed_at", flat=True
        ).get(pk=deal.pk)
        events_before = deal.events.count()

        second = decide_early_arrival(
            deal_id=deal.pk, actor_id=scenario.sender.pk, confirm=True
        )
        assert first.changed is True
        assert second.changed is False
        assert second.report_id == report.pk
        assert deal.events.count() == events_before
        assert (
            Deal.objects.values_list("arrival_confirmed_at", flat=True).get(
                pk=deal.pk
            )
            == confirmed_at
        )

    def test_an_answer_cannot_be_reversed_after_the_fact(self):
        scenario, _ = self._reported("i1a-noflip")
        deal = scenario.deal
        decide_early_arrival(
            deal_id=deal.pk, actor_id=scenario.sender.pk, confirm=True
        )

        with self.assertRaises(ArrivalError) as caught:
            decide_early_arrival(
                deal_id=deal.pk, actor_id=scenario.sender.pk, confirm=False
            )
        assert caught.exception.code == "no_open_arrival_report"

    def test_notifications_are_one_per_fact(self):
        from apps.notifications.models import Notification

        scenario, report = self._reported("i1a-notify")
        deal = scenario.deal
        report_early_arrival(deal_id=deal.pk, actor_id=scenario.traveler.pk)

        to_sender = Notification.objects.filter(
            recipient_id=scenario.sender.pk, channel="deal.arrival_reported"
        )
        assert to_sender.count() == 1
        # Resource identities only: nothing about the schedule or the route.
        assert set(to_sender.get().payload) <= {
            "event_id",
            "ts",
            "targets",
            "deal_id",
            "match_id",
            "parcel_id",
            "journey_id",
        }

        decide_early_arrival(
            deal_id=deal.pk, actor_id=scenario.sender.pk, confirm=True
        )
        decide_early_arrival(
            deal_id=deal.pk, actor_id=scenario.sender.pk, confirm=True
        )
        assert (
            Notification.objects.filter(
                recipient_id=scenario.traveler.pk,
                channel="deal.arrival_confirmed",
            ).count()
            == 1
        )


class ArrivalAuthorizationTests(TestCase):
    """Who may act, and what the wrong party is told."""

    def setUp(self):
        self.client = Client()

    def _carrying(self, prefix: str):
        scenario = carrying_scenario(self.client, prefix=prefix)
        Deal.objects.filter(pk=scenario.deal.pk).update(
            funded_scheduled_arrival_floor_at=timezone.now() + timedelta(days=4)
        )
        scenario.deal.refresh_from_db()
        return scenario

    def test_the_sender_cannot_report_the_travelers_arrival(self):
        scenario = self._carrying("i1a-auth-sender")
        with self.assertRaises(ArrivalError) as caught:
            report_early_arrival(
                deal_id=scenario.deal.pk, actor_id=scenario.sender.pk
            )
        assert caught.exception.code == "not_traveler"

    def test_the_traveler_cannot_confirm_their_own_arrival(self):
        scenario = self._carrying("i1a-auth-traveler")
        report_early_arrival(
            deal_id=scenario.deal.pk, actor_id=scenario.traveler.pk
        )
        with self.assertRaises(ArrivalError) as caught:
            decide_early_arrival(
                deal_id=scenario.deal.pk,
                actor_id=scenario.traveler.pk,
                confirm=True,
            )
        assert caught.exception.code == "not_sender"

    def test_an_unrelated_user_reaches_neither_the_deal_nor_the_action(self):
        scenario = self._carrying("i1a-auth-outsider")
        self.client = client_for(scenario.outsider)
        url = reverse(
            "deals-arrival-action", args=[scenario.deal.pk, "report"]
        )
        assert self.client.post(url).status_code == 404

        detail = self.client.get(reverse("deals-detail", args=[scenario.deal.pk]))
        assert detail.status_code == 404

    def test_the_api_answers_the_wrong_party_with_403_and_a_code(self):
        scenario = self._carrying("i1a-auth-api")
        self.client = client_for(scenario.sender)
        response = self.client.post(
            reverse("deals-arrival-action", args=[scenario.deal.pk, "report"])
        )
        assert response.status_code == 403
        assert response.json()["code"] == "not_traveler"


class ArrivalApiTests(TestCase):
    """The endpoints as Flutter will call them."""

    def setUp(self):
        self.client = Client()

    def test_the_round_trip_returns_one_authoritative_document(self):
        scenario = carrying_scenario(self.client, prefix="i1a-api")
        deal = scenario.deal
        Deal.objects.filter(pk=deal.pk).update(
            funded_scheduled_arrival_floor_at=timezone.now() + timedelta(days=4)
        )

        self.client = client_for(scenario.traveler)
        reported = self.client.post(
            reverse("deals-arrival-action", args=[deal.pk, "report"])
        )
        assert reported.status_code == 200
        body = reported.json()
        assert body["changed"] is True
        assert body["arrival_report_status"] == "pending_confirmation"
        assert body["deal"]["arrival"]["state"] == "pending_confirmation"
        assert body["deal"]["arrival"]["available_actions"] == []

        # A retry of the same call is a success, not a conflict.
        again = self.client.post(
            reverse("deals-arrival-action", args=[deal.pk, "report"])
        )
        assert again.status_code == 200
        assert again.json()["changed"] is False

        self.client = client_for(scenario.sender)
        detail = self.client.get(reverse("deals-detail", args=[deal.pk])).json()
        assert detail["arrival"]["available_actions"] == [
            "confirm_early_arrival",
            "decline_early_arrival",
        ]
        confirmed = self.client.post(
            reverse("deals-arrival-action", args=[deal.pk, "confirm"])
        )
        assert confirmed.status_code == 200
        assert confirmed.json()["deal"]["arrival"]["state"] == "confirmed"
        assert confirmed.json()["deal"]["arrival_confirmed_at"]
        assert confirmed.json()["deal"]["delivery_confirmed_at"] is None

    def test_an_unknown_arrival_action_is_not_invented(self):
        scenario = carrying_scenario(self.client, prefix="i1a-api-unknown")
        self.client = client_for(scenario.traveler)
        response = self.client.post(
            reverse("deals-arrival-action", args=[scenario.deal.pk, "teleport"])
        )
        assert response.status_code == 404

    def test_the_detail_projection_states_the_payout_floor(self):
        scenario = delivered_scenario(self.client, prefix="i1a-api-floor")
        deal = scenario.deal
        self.client = client_for(scenario.traveler)
        block = self.client.get(reverse("deals-detail", args=[deal.pk])).json()[
            "protection"
        ]["payout_floor"]

        assert block["protection_ends_at"]
        assert block["funded_scheduled_arrival_floor_at"]
        assert block["payout_eligible_from"]
        assert block["basis"] in ("delivery_protection", "schedule_floor")
        assert block["gate_open"] is False


class DeliveryCodeSecurityTests(TestCase):
    """I1A changes nothing about who may hold a delivery code."""

    def setUp(self):
        self.client = Client()

    def test_a_confirmed_early_arrival_reveals_nothing_to_the_traveler(self):
        scenario = carrying_scenario(self.client, prefix="i1a-code")
        deal = scenario.deal
        Deal.objects.filter(pk=deal.pk).update(
            funded_scheduled_arrival_floor_at=timezone.now() + timedelta(days=4)
        )
        report_early_arrival(deal_id=deal.pk, actor_id=scenario.traveler.pk)
        decide_early_arrival(
            deal_id=deal.pk, actor_id=scenario.sender.pk, confirm=True
        )
        deal.refresh_from_db()

        from apps.handover.services import handover_state

        state = handover_state(deal=deal, viewer_id=scenario.traveler.pk)
        assert state["traveler_can_view_delivery_code"] is False
        assert state["can_reveal_delivery_code"] is False

        with self.assertRaises(HandoverError):
            reveal_code(
                deal_id=deal.pk,
                kind=DealHandoverCode.Kind.DELIVERY,
                actor_id=scenario.traveler.pk,
            )

    def test_the_30_minute_buffer_survives_a_confirmed_arrival(self):
        scenario = carrying_scenario(self.client, prefix="i1a-buffer")
        deal = scenario.deal
        Deal.objects.filter(pk=deal.pk).update(
            funded_scheduled_arrival_floor_at=timezone.now() + timedelta(days=4)
        )
        report_early_arrival(deal_id=deal.pk, actor_id=scenario.traveler.pk)
        decide_early_arrival(
            deal_id=deal.pk, actor_id=scenario.sender.pk, confirm=True
        )
        deal.refresh_from_db()

        assert deal.delivery_code_available_at - deal.pickup_confirmed_at == (
            timedelta(seconds=1_800)
        )
        with freeze_at(deal.delivery_code_available_at - timedelta(seconds=1)):
            with self.assertRaises(HandoverError) as caught:
                reveal_code(
                    deal_id=deal.pk,
                    kind=DealHandoverCode.Kind.DELIVERY,
                    actor_id=scenario.sender.pk,
                )
        assert caught.exception.code in (
            "delivery_code_buffer_open",
            "code_not_available",
        )

    def test_no_arrival_event_payload_can_carry_code_material(self):
        scenario = carrying_scenario(self.client, prefix="i1a-code-payload")
        deal = scenario.deal
        secret = scenario.pickup_code
        assert secret
        Deal.objects.filter(pk=deal.pk).update(
            funded_scheduled_arrival_floor_at=timezone.now() + timedelta(days=4)
        )
        report_early_arrival(deal_id=deal.pk, actor_id=scenario.traveler.pk)
        decide_early_arrival(
            deal_id=deal.pk, actor_id=scenario.sender.pk, confirm=True
        )

        from apps.deals.timeline import PARTY_VISIBLE_PAYLOAD_KEYS, deal_timeline

        arrival_kinds = {
            DealEvent.Kind.EARLY_ARRIVAL_REPORTED,
            DealEvent.Kind.EARLY_ARRIVAL_CONFIRMED,
            DealEvent.Kind.ARRIVAL_SNAPSHOT_FROZEN,
        }
        rows = [
            row
            for row in deal_timeline(deal.events.all())
            if row["kind"] in arrival_kinds
        ]
        assert rows
        for row in rows:
            # The allowlist is the wall; this asserts the wall is where the new
            # payloads are, and that the one real secret in this scenario -- a
            # live handover code -- is nowhere in any of them.
            assert set(row["payload"]) <= PARTY_VISIBLE_PAYLOAD_KEYS
            rendered = repr(row["payload"])
            assert secret not in rendered
            assert "delivery_code" not in rendered.replace(
                "releases_delivery_code", ""
            )


class ActiveSendingTests(TestCase):
    """A delivered Deal is not an active shipment."""

    def setUp(self):
        self.client = Client()

    def test_a_delivered_deal_leaves_active_and_becomes_completed(self):
        scenario = delivered_scenario(self.client, prefix="i1a-activity")
        deal = scenario.deal

        assert deal.status == Deal.Status.PROTECTION_WINDOW
        assert activity_state(deal) == COMPLETED

        self.client = client_for(scenario.sender)
        active = self.client.get(reverse("deals-list"), {"activity": "active"}).json()
        completed = self.client.get(
            reverse("deals-list"), {"activity": "completed"}
        ).json()

        assert deal.pk not in [row["id"] for row in active["results"]]
        assert deal.pk in [row["id"] for row in completed["results"]]
        assert completed["results"][0]["activity_state"] == COMPLETED

    def test_a_carried_deal_is_active(self):
        scenario = carrying_scenario(self.client, prefix="i1a-activity-live")
        assert activity_state(scenario.deal) == ACTIVE

        self.client = client_for(scenario.sender)
        active = self.client.get(reverse("deals-list"), {"activity": "active"}).json()
        assert scenario.deal.pk in [row["id"] for row in active["results"]]

    def test_a_pending_payout_does_not_keep_a_finished_shipment_active(self):
        """The payout's own state is still readable; the shipment is not active."""

        scenario = delivered_scenario(self.client, prefix="i1a-activity-payout")
        deal = scenario.deal
        past_protection(scenario)
        Deal.objects.filter(pk=deal.pk).update(
            funded_scheduled_arrival_floor_at=timezone.now() + timedelta(days=3)
        )
        evaluate_payout_release(deal_id=deal.pk)
        deal.refresh_from_db()

        assert deal.status == Deal.Status.COMPLETED
        assert activity_state(deal) == COMPLETED

        self.client = client_for(scenario.traveler)
        detail = self.client.get(reverse("deals-detail", args=[deal.pk])).json()
        assert detail["activity_state"] == COMPLETED
        assert detail["payout_summary"]["display_state"] == "release_pending"
        assert detail["payout_summary"]["blocking_reason"] == (
            "scheduled_arrival_pending"
        )
        assert detail["payout_summary"]["earliest_release_at"]

    def test_a_cancelled_deal_is_neither_active_nor_completed(self):
        scenario = fund_scenario(self.client, prefix="i1a-activity-cancel")
        deal = scenario.deal
        Deal.objects.filter(pk=deal.pk).update(status=Deal.Status.CANCELLED)
        deal.refresh_from_db()
        assert activity_state(deal) == CANCELLED

    def test_a_refund_outranks_the_delivery_fact(self):
        scenario = delivered_scenario(self.client, prefix="i1a-activity-refund")
        deal = scenario.deal
        Deal.objects.filter(pk=deal.pk).update(status=Deal.Status.REFUNDED)
        deal.refresh_from_db()
        assert activity_state(deal) == CANCELLED

    def test_an_unknown_activity_filter_is_refused(self):
        scenario = fund_scenario(self.client, prefix="i1a-activity-bad")
        self.client = client_for(scenario.sender)
        response = self.client.get(reverse("deals-list"), {"activity": "sideways"})
        assert response.status_code == 400


class SenderRouteProjectionTests(TestCase):
    """What the sender sees of the traveler's route, and what they do not."""

    def setUp(self):
        self.client = Client()

    def test_the_sender_sees_the_ordered_funded_route(self):
        scenario = fund_scenario(self.client, prefix="i1a-route")
        deal = scenario.deal
        self.client = client_for(scenario.sender)
        route = self.client.get(reverse("deals-detail", args=[deal.pk])).json()[
            "route"
        ]

        assert route["basis"] == "funded_snapshot"
        assert route["journey_id"] == deal.journey_id
        assert route["legs"]
        assert [leg["position"] for leg in route["legs"]] == sorted(
            leg["position"] for leg in route["legs"]
        )
        for leg in route["legs"]:
            assert leg["mode"] in ("FLIGHT", "DRIVE")
            assert leg["carries_parcel"] is True
            assert leg["origin"] is not None
            assert leg["destination"] is not None

    def test_the_route_carries_no_private_traveler_detail(self):
        scenario = fund_scenario(self.client, prefix="i1a-route-privacy")
        self.client = client_for(scenario.sender)
        route = self.client.get(
            reverse("deals-detail", args=[scenario.deal.pk])
        ).json()["route"]

        forbidden = {
            "route_polyline",
            "route_metadata",
            "departure_airport_metadata",
            "arrival_airport_metadata",
            "distance_meters",
            "route_duration_seconds",
            "capacity_kg",
            "proofs",
            "flight_number",
            "allowed_detour_meters",
        }
        for leg in route["legs"]:
            assert forbidden.isdisjoint(leg)
            for endpoint in (leg["origin"], leg["destination"]):
                assert "latitude" not in endpoint
                assert "longitude" not in endpoint
                assert "private_label" not in endpoint

    def test_the_route_covers_only_the_legs_that_carry_this_parcel(self):
        scenario = fund_scenario(self.client, prefix="i1a-route-scope")
        deal = scenario.deal
        # A second leg the traveler owns but this Deal does not use.
        unrelated = JourneyLeg.objects.create(
            journey=scenario.base.journey,
            position=9,
            mode=JourneyLeg.Mode.DRIVE,
            origin=scenario.base.leg.destination,
            destination=scenario.base.leg.origin,
            depart_at=scenario.base.leg.arrive_at + timedelta(hours=2),
            arrive_at=scenario.base.leg.arrive_at + timedelta(hours=6),
            capacity_kg=scenario.base.leg.capacity_kg,
        )

        self.client = client_for(scenario.sender)
        route = self.client.get(reverse("deals-detail", args=[deal.pk])).json()[
            "route"
        ]
        assert unrelated.pk not in [leg["leg_id"] for leg in route["legs"]]

    def test_there_is_no_route_before_funding(self):
        from apps.deals.route import funded_route

        scenario = fund_scenario(self.client, prefix="i1a-route-prefund")
        deal = scenario.deal
        deal.funded_at = None
        assert funded_route(deal=deal, viewer_id=deal.sender_id) is None

    def test_a_non_party_gets_no_route(self):
        from apps.deals.route import funded_route

        scenario = fund_scenario(self.client, prefix="i1a-route-outsider")
        assert (
            funded_route(deal=scenario.deal, viewer_id=scenario.outsider.pk) is None
        )

    def test_a_legacy_deal_without_a_snapshot_falls_back_and_says_so(self):
        from apps.deals.route import funded_route

        scenario = fund_scenario(self.client, prefix="i1a-route-legacy")
        deal = scenario.deal
        Deal.objects.filter(pk=deal.pk).update(arrival_snapshot={})
        deal.refresh_from_db()

        route = funded_route(deal=deal, viewer_id=deal.sender_id)
        assert route["basis"] == "live_journey"
        assert route["legs"]


class HistoricalDealTests(TestCase):
    """Deals funded before I1A, and the one thing the backfill will not do."""

    def setUp(self):
        self.client = Client()

    def test_a_null_floor_reproduces_the_pre_i1a_release_exactly(self):
        scenario = delivered_scenario(self.client, prefix="i1a-legacy-release")
        deal = scenario.deal
        Deal.objects.filter(pk=deal.pk).update(
            funded_scheduled_arrival_floor_at=None, arrival_snapshot={}
        )
        past_protection(scenario)
        deal.refresh_from_db()

        assert payout_release_gate_at(deal) == deal.protection_ends_at
        assert_released(evaluate_payout_release(deal_id=deal.pk))

    def test_a_legacy_deal_offers_no_arrival_action_rather_than_a_guess(self):
        scenario = carrying_scenario(self.client, prefix="i1a-legacy-action")
        deal = scenario.deal
        Deal.objects.filter(pk=deal.pk).update(
            funded_scheduled_arrival_floor_at=None, arrival_snapshot={}
        )
        deal.refresh_from_db()

        projection = arrival_domain.arrival_projection(
            deal=deal, viewer_id=scenario.traveler.pk
        )
        assert projection["report_available"] is False
        assert projection["report_unavailable_reason"] == "arrival_basis_missing"
        assert projection["funded_scheduled_arrival_at"] is None
        assert projection["is_materially_early_now"] is False

        with self.assertRaises(ArrivalError) as caught:
            report_early_arrival(deal_id=deal.pk, actor_id=scenario.traveler.pk)
        assert caught.exception.code == "arrival_basis_missing"

    def test_the_backfill_rule_never_touches_a_released_payout(self):
        scenario = delivered_scenario(self.client, prefix="i1a-backfill-guard")
        deal = scenario.deal
        past_protection(scenario)
        Deal.objects.filter(pk=deal.pk).update(
            funded_scheduled_arrival_floor_at=None, arrival_snapshot={}
        )
        evaluate_payout_release(deal_id=deal.pk)
        payout = Payout.objects.get(deal_id=deal.pk)
        assert payout.status not in ("not_eligible", "frozen")

        _run_backfill()
        deal.refresh_from_db()
        # A decided payout keeps the eligibility it was granted; the backfill
        # refuses to add a constraint after the fact.
        assert deal.funded_scheduled_arrival_floor_at is None
        assert deal.arrival_snapshot == {}

    def test_the_backfill_recovers_what_it_can_and_fabricates_nothing(self):
        recoverable = fund_scenario(self.client, prefix="i1a-backfill-yes")
        expected = arrival_domain.parse_instant(
            recoverable.base.offer.match.compatibility_snapshot["delivery_at"]
        )
        unrecoverable = fund_scenario(self.client, prefix="i1a-backfill-no")
        from apps.matching.models import Match

        snapshot = dict(unrecoverable.base.offer.match.compatibility_snapshot)
        snapshot.pop("delivery_at", None)
        Match.objects.filter(pk=unrecoverable.base.offer.match_id).update(
            compatibility_snapshot=snapshot
        )
        for scenario in (recoverable, unrecoverable):
            Deal.objects.filter(pk=scenario.deal.pk).update(
                funded_scheduled_arrival_floor_at=None, arrival_snapshot={}
            )

        _run_backfill()

        recovered = Deal.objects.get(pk=recoverable.deal.pk)
        assert recovered.funded_scheduled_arrival_floor_at == expected
        assert recovered.arrival_snapshot["provenance"] == (
            "legacy_match_snapshot_v1"
        )
        assert recovered.arrival_snapshot["basis"] == (
            "match_delivery_interpolation"
        )
        # No reconstructed route is passed off as a frozen one.
        assert recovered.arrival_snapshot["route"] == []

        missing = Deal.objects.get(pk=unrecoverable.deal.pk)
        assert missing.funded_scheduled_arrival_floor_at is None
        assert missing.arrival_snapshot["basis"] == "unavailable"
        assert payout_release_gate_at(missing) is None


def _run_backfill():
    """Run the I1A migration's own data step, not a copy of its rule.

    Imported by module path and called with the live app registry. A
    reimplementation here would test the test rather than the migration, which
    is the part that actually runs against production data once.
    """

    import importlib

    from django.apps import apps as django_apps

    module = importlib.import_module(
        "apps.deals.migrations.0008_phase_i1a_journey_timing"
    )
    module.backfill_arrival_basis(django_apps, None)


@POSTGRES_ONLY
class ArrivalConcurrencyTests(TestCase):
    """The database's own guarantees, not the service's."""

    def setUp(self):
        self.client = Client()

    def test_two_open_claims_cannot_exist_for_one_deal(self):
        from django.db import IntegrityError, transaction

        scenario = carrying_scenario(self.client, prefix="i1a-race")
        deal = scenario.deal
        Deal.objects.filter(pk=deal.pk).update(
            funded_scheduled_arrival_floor_at=timezone.now() + timedelta(days=4)
        )
        deal.refresh_from_db()
        report_early_arrival(deal_id=deal.pk, actor_id=scenario.traveler.pk)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                DealArrivalReport.objects.create(
                    deal=deal,
                    reported_by=scenario.traveler,
                    reported_at=timezone.now(),
                    reported_deal_status=deal.status,
                    scheduled_arrival_at=deal.funded_scheduled_arrival_floor_at,
                    early_by_seconds=90_000,
                    threshold_seconds=21_600,
                    basis="match_delivery_interpolation",
                )

    def test_two_confirmed_claims_cannot_exist_for_one_deal(self):
        from django.db import IntegrityError, transaction

        scenario = carrying_scenario(self.client, prefix="i1a-race-confirm")
        deal = scenario.deal
        Deal.objects.filter(pk=deal.pk).update(
            funded_scheduled_arrival_floor_at=timezone.now() + timedelta(days=4)
        )
        deal.refresh_from_db()
        report_early_arrival(deal_id=deal.pk, actor_id=scenario.traveler.pk)
        decide_early_arrival(
            deal_id=deal.pk, actor_id=scenario.sender.pk, confirm=True
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                DealArrivalReport.objects.create(
                    deal=deal,
                    reported_by=scenario.traveler,
                    reported_at=timezone.now(),
                    reported_deal_status=deal.status,
                    scheduled_arrival_at=deal.funded_scheduled_arrival_floor_at,
                    early_by_seconds=90_000,
                    threshold_seconds=21_600,
                    basis="match_delivery_interpolation",
                    status=DealArrivalReport.Status.CONFIRMED,
                    decided_by=scenario.sender,
                    decided_at=timezone.now(),
                )

    def test_a_delivery_confirmed_while_a_claim_is_open_still_completes(self):
        """Arrival and delivery are independent; neither corrupts the other."""

        scenario = carrying_scenario(self.client, prefix="i1a-race-delivery")
        deal = scenario.deal
        Deal.objects.filter(pk=deal.pk).update(
            funded_scheduled_arrival_floor_at=timezone.now() + timedelta(days=4)
        )
        deal.refresh_from_db()
        report_early_arrival(deal_id=deal.pk, actor_id=scenario.traveler.pk)

        release_delivery_code(scenario)
        confirm_delivery(scenario)
        deal.refresh_from_db()

        assert deal.status == Deal.Status.PROTECTION_WINDOW
        assert deal.protection_ends_at is not None
        # The claim is left exactly as it was: unanswered, and now unanswerable.
        report = DealArrivalReport.objects.get(deal_id=deal.pk)
        assert report.status == DealArrivalReport.Status.PENDING_CONFIRMATION
        assert arrival_domain.arrival_projection(
            deal=deal, viewer_id=scenario.sender.pk
        )["available_actions"] == []
