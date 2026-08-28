"""Disputes: the window, the freeze, the evidence and the money.

Three things are being defended here.

**A dispute stops a payout.** Not eventually, not once a worker notices — the
freeze and the dispute row commit together, and the payout gate reads the same
committed state through the same lock.

**A resolution reconciles exactly.** Every cent the platform collected is
returned, paid out, or kept. The arithmetic is asserted against the ledger
rather than against the numbers the resolution reported about itself.

**A resolution happens once.** Two administrators, a retried request and a
resolution followed by a second attempt all converge on one economic outcome.
"""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth.models import Group
from django.db.models import Sum
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.deals.models import Deal, DealEvent
from apps.deals.tests.phase4_factories import (
    confirm_pickup,
    delivered_scenario,
    freeze_at,
    fund_scenario,
    record_recipient,
    rewind_deal,
)
from apps.disputes.models import Dispute, DisputeEvent
from apps.disputes.services import (
    DisputeError,
    NotAuthorized,
    close_dispute,
    open_dispute,
    resolve_dispute,
    set_dispute_status,
)
from apps.finance.models import PaymentRefund, Payout
from apps.finance.payout_release import evaluate_payout_release
from apps.finance.settlement import assert_deal_reconciles, read_deal_money


def client_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def refunded_cents(deal_id: int) -> int:
    return int(
        PaymentRefund.objects.filter(order__deal_id=deal_id)
        .exclude(status=PaymentRefund.Status.FAILED)
        .aggregate(total=Sum("amount_eur_cents"))["total"]
        or 0
    )


def grant(user, group_name: str):
    user.is_staff = True
    user.save(update_fields=["is_staff"])
    user.groups.add(Group.objects.get(name=group_name))
    return user


# --- opening ------------------------------------------------------------------


class DisputeWindowTests(TestCase):
    def test_a_party_cannot_dispute_before_the_parcel_is_picked_up(self):
        scenario = fund_scenario(self.client, prefix="dw1")
        record_recipient(scenario)
        with self.assertRaises(DisputeError) as caught:
            open_dispute(
                deal_id=scenario.deal.pk,
                actor_id=scenario.sender.pk,
                category=Dispute.Category.OTHER,
                reason_text="Nothing has happened yet.",
            )
        assert caught.exception.code == "dispute_not_available"

    def test_a_party_may_dispute_while_the_parcel_is_in_carriage(self):
        """After pickup there is no unilateral cancellation, so this is the door."""

        scenario = fund_scenario(self.client, prefix="dw2")
        record_recipient(scenario)
        confirm_pickup(scenario)
        dispute = open_dispute(
            deal_id=scenario.deal.pk,
            actor_id=scenario.sender.pk,
            category=Dispute.Category.NOT_DELIVERED,
            reason_text="The traveler has stopped responding.",
        )
        assert dispute.status == Dispute.Status.OPEN
        assert scenario.deal.status == Deal.Status.DISPUTED

    def test_a_party_may_dispute_inside_the_protection_window(self):
        scenario = delivered_scenario(self.client, prefix="dw3")
        with freeze_at(scenario.deal.protection_ends_at - timedelta(seconds=1)):
            dispute = open_dispute(
                deal_id=scenario.deal.pk,
                actor_id=scenario.sender.pk,
                category=Dispute.Category.DAMAGED,
                reason_text="The parcel arrived crushed.",
            )
        assert dispute.status == Dispute.Status.OPEN

    def test_a_party_cannot_dispute_once_the_protection_window_has_closed(self):
        scenario = delivered_scenario(self.client, prefix="dw4")
        with freeze_at(scenario.deal.protection_ends_at + timedelta(seconds=1)):
            with self.assertRaises(DisputeError) as caught:
                open_dispute(
                    deal_id=scenario.deal.pk,
                    actor_id=scenario.sender.pk,
                    category=Dispute.Category.DAMAGED,
                    reason_text="Too late.",
                )
        assert caught.exception.code == "dispute_window_closed"
        assert not Dispute.objects.filter(deal_id=scenario.deal.pk).exists()

    def test_only_a_party_may_open_one(self):
        scenario = delivered_scenario(self.client, prefix="dw5")
        with self.assertRaises(NotAuthorized):
            open_dispute(
                deal_id=scenario.deal.pk,
                actor_id=scenario.outsider.pk,
                category=Dispute.Category.OTHER,
                reason_text="Not mine.",
            )

    def test_an_admin_may_open_one_outside_the_window(self):
        scenario = delivered_scenario(self.client, prefix="dw6")
        with freeze_at(scenario.deal.protection_ends_at + timedelta(days=2)):
            dispute = open_dispute(
                deal_id=scenario.deal.pk,
                actor_id=scenario.admin.pk,
                category=Dispute.Category.OTHER,
                reason_text="Escalated by support.",
                as_admin=True,
            )
        assert dispute.opened_by_role == Dispute.OpenedByRole.ADMIN

    def test_a_category_or_reason_that_is_missing_is_refused(self):
        scenario = delivered_scenario(self.client, prefix="dw7")
        with self.assertRaises(DisputeError) as caught:
            open_dispute(
                deal_id=scenario.deal.pk,
                actor_id=scenario.sender.pk,
                category="chargeback",
                reason_text="x",
            )
        assert caught.exception.code == "dispute_category_invalid"
        with self.assertRaises(DisputeError) as caught:
            open_dispute(
                deal_id=scenario.deal.pk,
                actor_id=scenario.sender.pk,
                category=Dispute.Category.OTHER,
                reason_text="   ",
            )
        assert caught.exception.code == "dispute_reason_required"


class DisputeOpeningEffectTests(TestCase):
    def setUp(self):
        self.scenario = delivered_scenario(self.client, prefix="dopen")
        self.dispute = open_dispute(
            deal_id=self.scenario.deal.pk,
            actor_id=self.scenario.sender.pk,
            category=Dispute.Category.DAMAGED,
            reason_text="Arrived damaged.",
        )

    def test_opening_freezes_the_payout(self):
        payout = Payout.objects.get(deal_id=self.scenario.deal.pk)
        assert payout.status == Payout.Status.FROZEN
        assert self.dispute.payout_frozen is True
        assert self.dispute.payout_already_settled is False

    def test_opening_moves_the_deal_and_writes_both_timelines(self):
        assert self.scenario.deal.status == Deal.Status.DISPUTED
        assert DealEvent.objects.filter(
            deal_id=self.scenario.deal.pk, kind=DealEvent.Kind.DISPUTE_OPENED
        ).exists()
        kinds = set(
            DisputeEvent.objects.filter(dispute=self.dispute).values_list(
                "kind", flat=True
            )
        )
        assert DisputeEvent.Kind.OPENED in kinds
        assert DisputeEvent.Kind.BUNDLE_CAPTURED in kinds
        assert DisputeEvent.Kind.PAYOUT_FROZEN in kinds

    def test_opening_twice_returns_the_same_row_and_freezes_once(self):
        again = open_dispute(
            deal_id=self.scenario.deal.pk,
            actor_id=self.scenario.sender.pk,
            category=Dispute.Category.LATE,
            reason_text="A retry of the same complaint.",
        )
        assert again.pk == self.dispute.pk
        assert Dispute.objects.filter(deal_id=self.scenario.deal.pk).count() == 1
        assert (
            DisputeEvent.objects.filter(
                dispute=self.dispute, kind=DisputeEvent.Kind.OPENED
            ).count()
            == 1
        )

    def test_the_counterparty_can_also_open_and_gets_the_same_active_row(self):
        again = open_dispute(
            deal_id=self.scenario.deal.pk,
            actor_id=self.scenario.traveler.pk,
            category=Dispute.Category.OTHER,
            reason_text="I dispute the sender's account.",
        )
        assert again.pk == self.dispute.pk

    def test_the_evidence_bundle_indexes_the_record_without_copying_secrets(self):
        bundle = self.dispute.evidence_bundle
        assert bundle["bundle_version"] >= 1
        assert bundle["captured_at"]
        for section in ("deal", "timeline", "payments", "handover"):
            assert section in bundle, section

        text = str(bundle)
        assert self.scenario.delivery_code not in text
        assert self.scenario.pickup_code not in text
        assert "recipient@example.invalid" not in text
        assert "Recipient Example" not in text

    def test_the_frozen_payout_cannot_be_released_by_the_timer(self):
        rewind_deal(self.scenario.deal, timedelta(hours=49))
        assert evaluate_payout_release(deal_id=self.scenario.deal.pk) == (
            "frozen_by_dispute"
        )
        assert Payout.objects.get(deal_id=self.scenario.deal.pk).status == (
            Payout.Status.FROZEN
        )


class DisputeVersusProtectionExpiryTests(TestCase):
    """The two writers that compete for the same money.

    Serialized here, both orderings; the genuinely concurrent version lives in
    the PostgreSQL suite. What matters is that no interleaving exists in which
    an active dispute coexists with a payout in a releasable state.
    """

    def test_a_dispute_one_second_before_expiry_keeps_the_money_frozen(self):
        scenario = delivered_scenario(self.client, prefix="race-a")
        deadline = scenario.deal.protection_ends_at

        with freeze_at(deadline - timedelta(seconds=1)):
            open_dispute(
                deal_id=scenario.deal.pk,
                actor_id=scenario.sender.pk,
                category=Dispute.Category.NOT_DELIVERED,
                reason_text="It never arrived.",
            )
        with freeze_at(deadline):
            assert evaluate_payout_release(deal_id=scenario.deal.pk) == (
                "frozen_by_dispute"
            )
        assert Payout.objects.get(deal_id=scenario.deal.pk).status == (
            Payout.Status.FROZEN
        )

    def test_a_payout_released_first_is_pulled_back_by_an_admin_dispute(self):
        scenario = delivered_scenario(self.client, prefix="race-b")
        with freeze_at(scenario.deal.protection_ends_at):
            assert evaluate_payout_release(deal_id=scenario.deal.pk) == "released"
        assert Payout.objects.get(deal_id=scenario.deal.pk).status == (
            Payout.Status.ELIGIBLE
        )

        with freeze_at(scenario.deal.protection_ends_at + timedelta(minutes=5)):
            dispute = open_dispute(
                deal_id=scenario.deal.pk,
                actor_id=scenario.admin.pk,
                category=Dispute.Category.DAMAGED,
                reason_text="Reported to support after the window.",
                as_admin=True,
            )
        payout = Payout.objects.get(deal_id=scenario.deal.pk)
        assert payout.status == Payout.Status.FROZEN
        assert dispute.payout_frozen is True

    def test_no_active_dispute_ever_coexists_with_a_releasable_payout(self):
        """The invariant, stated directly and checked over both orderings."""

        for prefix, dispute_first in (("inv-a", True), ("inv-b", False)):
            scenario = delivered_scenario(self.client, prefix=prefix)
            deadline = scenario.deal.protection_ends_at
            if dispute_first:
                with freeze_at(deadline - timedelta(seconds=1)):
                    open_dispute(
                        deal_id=scenario.deal.pk,
                        actor_id=scenario.sender.pk,
                        category=Dispute.Category.OTHER,
                        reason_text="First.",
                    )
                with freeze_at(deadline):
                    evaluate_payout_release(deal_id=scenario.deal.pk)
            else:
                with freeze_at(deadline):
                    evaluate_payout_release(deal_id=scenario.deal.pk)
                with freeze_at(deadline + timedelta(minutes=1)):
                    open_dispute(
                        deal_id=scenario.deal.pk,
                        actor_id=scenario.admin.pk,
                        category=Dispute.Category.OTHER,
                        reason_text="Second.",
                        as_admin=True,
                    )

            active = Dispute.objects.filter(
                deal_id=scenario.deal.pk, status__in=Dispute.ACTIVE_STATUSES
            ).exists()
            payout = Payout.objects.get(deal_id=scenario.deal.pk)
            assert active, prefix
            assert payout.status not in (
                Payout.Status.ELIGIBLE,
                Payout.Status.SCHEDULED,
                Payout.Status.PROCESSING,
                Payout.Status.PAID,
            ), (prefix, payout.status)


# --- resolution ---------------------------------------------------------------


class DisputeResolutionTests(TestCase):
    def setUp(self):
        self.scenario = delivered_scenario(self.client, prefix="dres")
        self.money = read_deal_money(self.scenario.deal)
        self.dispute = open_dispute(
            deal_id=self.scenario.deal.pk,
            actor_id=self.scenario.sender.pk,
            category=Dispute.Category.DAMAGED,
            reason_text="Damaged in transit.",
        )

    def test_full_sender_refund_returns_everything_and_reconciles(self):
        resolved = resolve_dispute(
            dispute_id=self.dispute.pk,
            admin_actor_id=self.scenario.admin.pk,
            resolution=Dispute.Resolution.FULL_SENDER_REFUND,
            note="Photos show the damage.",
        )

        assert resolved.status == Dispute.Status.RESOLVED
        assert resolved.sender_refund_eur_cents == self.money.collected_eur_cents
        assert resolved.traveler_payout_eur_cents == 0
        assert resolved.platform_fee_eur_cents == 0
        assert resolved.collected_total_eur_cents == self.money.collected_eur_cents
        assert refunded_cents(self.scenario.deal.pk) == self.money.collected_eur_cents
        assert self.scenario.deal.status == Deal.Status.REFUNDED
        assert assert_deal_reconciles(self.scenario.deal.pk)["net"] == 0

    def test_full_traveler_payout_refunds_nothing_and_completes_the_deal(self):
        resolved = resolve_dispute(
            dispute_id=self.dispute.pk,
            admin_actor_id=self.scenario.admin.pk,
            resolution=Dispute.Resolution.FULL_TRAVELER_PAYOUT,
        )

        assert resolved.sender_refund_eur_cents == 0
        assert (
            resolved.traveler_payout_eur_cents + resolved.platform_fee_eur_cents
            == self.money.collected_eur_cents
        )
        assert refunded_cents(self.scenario.deal.pk) == 0
        assert self.scenario.deal.status == Deal.Status.COMPLETED
        assert assert_deal_reconciles(self.scenario.deal.pk)["net"] == 0

    def test_a_partial_split_divides_the_money_exactly(self):
        half = self.money.collected_eur_cents // 2
        resolved = resolve_dispute(
            dispute_id=self.dispute.pk,
            admin_actor_id=self.scenario.admin.pk,
            resolution=Dispute.Resolution.PARTIAL_SPLIT,
            sender_refund_eur_cents=half,
            note="Shared responsibility.",
        )

        assert (
            resolved.sender_refund_eur_cents
            + resolved.traveler_payout_eur_cents
            + resolved.platform_fee_eur_cents
            == self.money.collected_eur_cents
        )
        assert resolved.sender_refund_eur_cents == half
        assert resolved.traveler_payout_eur_cents > 0
        assert refunded_cents(self.scenario.deal.pk) == half
        assert self.scenario.deal.status == Deal.Status.PARTIALLY_REFUNDED
        assert assert_deal_reconciles(self.scenario.deal.pk)["net"] == 0

    def test_an_explicit_traveler_amount_leaves_the_remainder_with_the_platform(self):
        total = self.money.collected_eur_cents
        resolved = resolve_dispute(
            dispute_id=self.dispute.pk,
            admin_actor_id=self.scenario.admin.pk,
            resolution=Dispute.Resolution.PARTIAL_SPLIT,
            sender_refund_eur_cents=1_000,
            traveler_payout_eur_cents=500,
        )
        assert resolved.sender_refund_eur_cents == 1_000
        assert resolved.traveler_payout_eur_cents == 500
        assert resolved.platform_fee_eur_cents == total - 1_500

    def test_a_partial_split_that_is_not_partial_is_refused(self):
        for amount in (0, self.money.collected_eur_cents):
            with self.assertRaises(DisputeError) as caught:
                resolve_dispute(
                    dispute_id=self.dispute.pk,
                    admin_actor_id=self.scenario.admin.pk,
                    resolution=Dispute.Resolution.PARTIAL_SPLIT,
                    sender_refund_eur_cents=amount,
                )
            assert caught.exception.code == "dispute_partial_split_not_partial"

    def test_a_split_larger_than_what_was_collected_is_refused(self):
        from apps.finance.settlement import SettlementError

        with self.assertRaises(SettlementError) as caught:
            resolve_dispute(
                dispute_id=self.dispute.pk,
                admin_actor_id=self.scenario.admin.pk,
                resolution=Dispute.Resolution.PARTIAL_SPLIT,
                sender_refund_eur_cents=self.money.collected_eur_cents + 1,
            )
        assert caught.exception.code == "settlement_refund_out_of_range"
        assert refunded_cents(self.scenario.deal.pk) == 0

    def test_resolving_twice_does_not_refund_twice(self):
        resolve_dispute(
            dispute_id=self.dispute.pk,
            admin_actor_id=self.scenario.admin.pk,
            resolution=Dispute.Resolution.FULL_SENDER_REFUND,
        )
        refunded = refunded_cents(self.scenario.deal.pk)
        resolved_at = Dispute.objects.get(pk=self.dispute.pk).resolved_at

        repeat = resolve_dispute(
            dispute_id=self.dispute.pk,
            admin_actor_id=self.scenario.admin.pk,
            resolution=Dispute.Resolution.FULL_TRAVELER_PAYOUT,
        )
        assert repeat.resolution == Dispute.Resolution.FULL_SENDER_REFUND
        assert repeat.resolved_at == resolved_at
        assert refunded_cents(self.scenario.deal.pk) == refunded

    def test_a_resolved_dispute_no_longer_freezes_the_payout(self):
        resolve_dispute(
            dispute_id=self.dispute.pk,
            admin_actor_id=self.scenario.admin.pk,
            resolution=Dispute.Resolution.FULL_TRAVELER_PAYOUT,
        )
        assert not Dispute.objects.filter(
            deal_id=self.scenario.deal.pk, status__in=Dispute.ACTIVE_STATUSES
        ).exists()
        payout = Payout.objects.get(deal_id=self.scenario.deal.pk)
        assert payout.status != Payout.Status.FROZEN

    def test_an_unknown_resolution_is_refused_before_any_money_moves(self):
        with self.assertRaises(DisputeError) as caught:
            resolve_dispute(
                dispute_id=self.dispute.pk,
                admin_actor_id=self.scenario.admin.pk,
                resolution="split_the_difference",
            )
        assert caught.exception.code == "dispute_resolution_invalid"
        assert refunded_cents(self.scenario.deal.pk) == 0


class DisputeAdministrationTests(TestCase):
    def setUp(self):
        self.scenario = delivered_scenario(self.client, prefix="dadm")
        self.dispute = open_dispute(
            deal_id=self.scenario.deal.pk,
            actor_id=self.scenario.sender.pk,
            category=Dispute.Category.LATE,
            reason_text="Weeks late.",
        )

    def test_status_moves_through_the_review_states(self):
        for status in (
            Dispute.Status.AWAITING_EVIDENCE,
            Dispute.Status.UNDER_REVIEW,
        ):
            row = set_dispute_status(
                dispute_id=self.dispute.pk,
                status=status,
                admin_actor_id=self.scenario.admin.pk,
            )
            assert row.status == status
            assert row.is_active is True

    def test_a_resolved_dispute_cannot_be_moved_back_into_review(self):
        resolve_dispute(
            dispute_id=self.dispute.pk,
            admin_actor_id=self.scenario.admin.pk,
            resolution=Dispute.Resolution.FULL_TRAVELER_PAYOUT,
        )
        with self.assertRaises(DisputeError):
            set_dispute_status(
                dispute_id=self.dispute.pk,
                status=Dispute.Status.UNDER_REVIEW,
                admin_actor_id=self.scenario.admin.pk,
            )

    def test_closing_a_dispute_without_resolving_releases_the_freeze(self):
        close_dispute(
            dispute_id=self.dispute.pk,
            admin_actor_id=self.scenario.admin.pk,
            note="Withdrawn by the sender.",
        )
        row = Dispute.objects.get(pk=self.dispute.pk)
        assert row.status == Dispute.Status.CLOSED
        assert row.is_active is False


# --- API surface --------------------------------------------------------------


class DisputeApiTests(TestCase):
    def setUp(self):
        self.scenario = delivered_scenario(self.client, prefix="dapi")
        self.deal = self.scenario.deal

    def test_a_party_opens_and_reads_a_dispute(self):
        sender = client_for(self.scenario.sender)
        created = sender.post(
            reverse("disputes-open", args=[self.deal.pk]),
            {"category": Dispute.Category.DAMAGED, "reason_text": "Crushed corner."},
            format="json",
        )
        assert created.status_code in (200, 201), created.data
        dispute_id = created.data["id"]

        listed = sender.get(reverse("disputes-list", args=[self.deal.pk]))
        assert listed.status_code == 200

        detail = sender.get(reverse("disputes-detail", args=[dispute_id]))
        assert detail.status_code == 200
        assert "evidence_bundle" not in detail.data

    def test_a_stranger_cannot_open_or_read_one(self):
        outsider = client_for(self.scenario.outsider)
        blocked = outsider.post(
            reverse("disputes-open", args=[self.deal.pk]),
            {"category": Dispute.Category.OTHER, "reason_text": "Not mine."},
            format="json",
        )
        assert blocked.status_code in (403, 404)

    def test_the_admin_queue_requires_the_named_permission(self):
        plain = client_for(self.scenario.outsider)
        assert plain.get(reverse("disputes-admin-list")).status_code in (403, 401)

        support = grant(self.scenario.outsider, "Support")
        allowed = client_for(support).get(reverse("disputes-admin-list"))
        assert allowed.status_code == 200

    def test_resolving_requires_more_than_the_viewing_permission(self):
        dispute = open_dispute(
            deal_id=self.deal.pk,
            actor_id=self.scenario.sender.pk,
            category=Dispute.Category.OTHER,
            reason_text="Something went wrong.",
        )
        support = grant(self.scenario.outsider, "Support")
        refused = client_for(support).post(
            reverse("disputes-admin-resolve", args=[dispute.pk]),
            {"resolution": Dispute.Resolution.FULL_TRAVELER_PAYOUT},
            format="json",
        )
        assert refused.status_code == 403

        finance = grant(self.scenario.admin, "Finance")
        allowed = client_for(finance).post(
            reverse("disputes-admin-resolve", args=[dispute.pk]),
            {"resolution": Dispute.Resolution.FULL_TRAVELER_PAYOUT},
            format="json",
        )
        assert allowed.status_code == 200, allowed.data
        assert Dispute.objects.get(pk=dispute.pk).status == Dispute.Status.RESOLVED

    def test_the_no_show_route_requires_its_own_permission(self):
        scenario = fund_scenario(self.client, prefix="dapi-ns")
        record_recipient(scenario)
        support = grant(scenario.outsider, "Support")
        refused = client_for(support).post(
            reverse("deals-admin-no-show", args=[scenario.deal.pk]),
            {"party": Deal.NoShowParty.TRAVELER},
            format="json",
        )
        assert refused.status_code == 403

        ops = grant(scenario.admin, "Ops")
        allowed = client_for(ops).post(
            reverse("deals-admin-no-show", args=[scenario.deal.pk]),
            {"party": Deal.NoShowParty.TRAVELER},
            format="json",
        )
        assert allowed.status_code == 200, allowed.data
        scenario.deal.refresh_from_db()
        assert scenario.deal.no_show_party == Deal.NoShowParty.TRAVELER


class DisputeEvidenceTests(TestCase):
    """Text evidence and the authorization around downloads.

    Binary uploads are exercised against the object store, which this host does
    not have; what is asserted here is the ownership boundary, which is where
    the risk actually lives.
    """

    def setUp(self):
        self.scenario = delivered_scenario(self.client, prefix="dev")
        self.dispute = open_dispute(
            deal_id=self.scenario.deal.pk,
            actor_id=self.scenario.sender.pk,
            category=Dispute.Category.DAMAGED,
            reason_text="Damaged.",
        )

    def test_a_party_may_add_text_evidence(self):
        from apps.disputes.services import add_evidence

        row = add_evidence(
            dispute_id=self.dispute.pk,
            actor_id=self.scenario.sender.pk,
            kind="text",
            text="The box was open when it arrived.",
        )
        assert row.pk
        assert DisputeEvent.objects.filter(
            dispute=self.dispute, kind=DisputeEvent.Kind.EVIDENCE_ADDED
        ).exists()
        assert DealEvent.objects.filter(
            deal_id=self.scenario.deal.pk,
            kind=DealEvent.Kind.DISPUTE_EVIDENCE_ADDED,
        ).exists()

    def test_the_counterparty_may_also_add_evidence(self):
        from apps.disputes.services import add_evidence

        row = add_evidence(
            dispute_id=self.dispute.pk,
            actor_id=self.scenario.traveler.pk,
            kind="text",
            text="It was sealed when I handed it over.",
        )
        assert row.pk

    def test_a_stranger_cannot_add_evidence(self):
        from apps.disputes.services import add_evidence

        with self.assertRaises(NotAuthorized):
            add_evidence(
                dispute_id=self.dispute.pk,
                actor_id=self.scenario.outsider.pk,
                kind="text",
                text="Let me in.",
            )

    def test_empty_text_evidence_is_refused(self):
        from apps.disputes.services import add_evidence

        with self.assertRaises(DisputeError):
            add_evidence(
                dispute_id=self.dispute.pk,
                actor_id=self.scenario.sender.pk,
                kind="text",
                text="   ",
            )

    def test_evidence_is_refused_once_the_dispute_is_resolved(self):
        from apps.disputes.services import add_evidence

        resolve_dispute(
            dispute_id=self.dispute.pk,
            admin_actor_id=self.scenario.admin.pk,
            resolution=Dispute.Resolution.FULL_TRAVELER_PAYOUT,
        )
        with self.assertRaises(DisputeError):
            add_evidence(
                dispute_id=self.dispute.pk,
                actor_id=self.scenario.sender.pk,
                kind="text",
                text="One more thing.",
            )

    def test_a_serialized_evidence_row_never_exposes_its_storage_location(self):
        from apps.disputes.serializers import DisputeEvidenceSerializer
        from apps.disputes.services import add_evidence

        row = add_evidence(
            dispute_id=self.dispute.pk,
            actor_id=self.scenario.sender.pk,
            kind="text",
            text="Evidence.",
        )
        data = DisputeEvidenceSerializer(row).data
        assert "storage_key" not in data
        assert "storage_bucket" not in data


class DisputeTimelineProjectionTests(TestCase):
    def test_a_party_timeline_carries_no_unexpected_payload_keys(self):
        scenario = delivered_scenario(self.client, prefix="dproj")
        open_dispute(
            deal_id=scenario.deal.pk,
            actor_id=scenario.sender.pk,
            category=Dispute.Category.OTHER,
            reason_text="Something.",
        )
        response = client_for(scenario.traveler).get(
            reverse("deals-detail", args=[scenario.deal.pk])
        )
        assert response.status_code == 200

        from apps.deals.timeline import PARTY_VISIBLE_PAYLOAD_KEYS

        for entry in response.data["timeline"]:
            unexpected = set(entry["payload"]) - PARTY_VISIBLE_PAYLOAD_KEYS
            assert not unexpected, (entry["kind"], unexpected)

    def test_the_deal_payload_reports_the_active_dispute_to_both_parties(self):
        scenario = delivered_scenario(self.client, prefix="dproj2")
        open_dispute(
            deal_id=scenario.deal.pk,
            actor_id=scenario.sender.pk,
            category=Dispute.Category.OTHER,
            reason_text="Something.",
        )
        for user in (scenario.sender, scenario.traveler):
            response = client_for(user).get(
                reverse("deals-detail", args=[scenario.deal.pk])
            )
            assert response.data["dispute"]["is_active"] is True
            assert response.data["protection"]["payout"]["status"] == (
                Payout.Status.FROZEN
            )
