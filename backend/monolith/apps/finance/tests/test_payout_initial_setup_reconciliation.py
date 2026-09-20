"""Funded empty DZD setup, later approval, and settlement presenter contracts."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import StringIO
import json

import pytest
from django.core.management import call_command
from django.db import connection, connections, transaction
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.admin_panel.console_manual_presenter import manual_view
from apps.admin_panel.permissions import assign_admin_roles
from apps.core.financial_locks import lock_deal_lifecycle
from apps.deals.models import Deal
from apps.finance.models import PaymentAttempt, Payout, PayoutInstructionAmendment
from apps.finance.payout_evidence import upload_evidence
from apps.finance.payout_manual import prepare
from apps.finance.payout_manual_profiles import _record_profile_review, review_profile
from apps.finance.payout_profiles import (
    assign_identity_review,
    attest_identity,
    set_preference,
    submit_dzd_profile,
)
from apps.finance.payout_setup_reconciliation import (
    complete_initial_dzd_setup,
    release_after_profile_approval,
)
from apps.finance.services import reconcile_attempt
from apps.finance.settlement import apply_settlement, plan_settlement, read_deal_money
from .factories import build_scenario
from .test_phase8fh4_manual import build_manual, configured_h4, image_upload  # noqa: F401


pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("configured_h4")]


def funded_placeholder(prefix):
    with override_settings(PAYOUT_PROFILES_ENABLED=False):
        scenario = build_scenario(prefix=prefix)
        scenario.accept(reward_eur_cents=6000)
    assign_admin_roles(scenario.admin, ["finance"])
    scenario.traveler.role = "traveler"
    scenario.traveler.save(update_fields=["role"])
    method = set_preference(
        actor=scenario.traveler, currency="DZD", enabled=True, expected_revision=0
    )
    balance = scenario.balance_order()
    amount = balance.outstanding_eur_cents
    capture = PaymentAttempt.objects.create(
        order=balance,
        provider="chargily",
        provider_mode="test",
        amount_eur_cents=amount,
        payment_currency="DZD",
        provider_amount_minor=amount * 260 // 100,
        fx_rate_micros=260000000,
        fx_settings_version=scenario.policy.settings_version,
        fx_source="business_settings",
        fx_snapshot_at=timezone.now(),
        idempotency_key=f"{prefix}-capture",
        status="checkout_pending",
    )
    reconcile_attempt(
        attempt_id=capture.pk,
        outcome="succeeded",
        provider_payment_id=f"qa-{prefix}",
        provider_amount_minor=amount * 260 // 100,
        provider_currency="DZD",
    )
    payout = Payout.objects.get(deal=scenario.deal)
    assert payout.active_instruction_version.dzd_profile_revision_id is None
    assert payout.block_reason == "payout_setup_required"
    return scenario, payout, method


def submit_initial(scenario, method):
    proof = upload_evidence(actor=scenario.traveler, upload=image_upload())
    method = submit_dzd_profile(
        actor=scenario.traveler,
        expected_revision=method.revision,
        first_name="QA",
        last_name="Synthetic",
        ccp_number="1111111111",
        ccp_key="11",
        rip="1" * 20,
        proof_reference=proof.public_reference,
    )
    assign_admin_roles(scenario.outsider, ["trust_verification"])
    assignment = assign_identity_review(
        actor=scenario.admin,
        traveler_id=scenario.traveler.pk,
        reviewer_id=scenario.outsider.pk,
    )
    attest_identity(
        actor=scenario.outsider,
        assignment_reference=assignment.public_reference,
        given_name="QA",
        family_name="Synthetic",
    )
    return method.current_version.dzd_profile_revision


def complete_delivery(scenario):
    now = timezone.now()
    Deal.objects.filter(pk=scenario.deal.pk).update(
        status="protection_window",
        pickup_confirmed_at=now - timedelta(hours=96),
        delivery_code_available_at=now - timedelta(hours=95),
        delivery_code_released_at=now - timedelta(hours=95),
        delivery_confirmed_at=now - timedelta(hours=72),
        funded_scheduled_arrival_floor_at=now - timedelta(hours=73),
        protection_ends_at=now - timedelta(hours=24),
    )
    from apps.finance.payout_release import evaluate_payout_release

    evaluate_payout_release(deal_id=scenario.deal.pk)


def award_compensation(scenario, key):
    with transaction.atomic():
        aggregate = lock_deal_lifecycle(scenario.deal.pk)
        money = read_deal_money(aggregate.deal)
        plan = plan_settlement(
            money=money,
            sender_refund_eur_cents=money.collected_eur_cents // 2,
            traveler_payout_eur_cents=3000,
        )
        apply_settlement(
            plan=plan,
            settlement_key=key,
            refund_reason="sender_cancellation",
            note="Synthetic compensation",
            actor_id=scenario.admin.pk,
        )


def test_later_first_approval_reconciles_and_keeps_funding_economics():
    scenario, payout, method = funded_placeholder("initial-later")
    old = payout.active_instruction_version_id
    money = (payout.amount_eur_cents, payout.payout_amount_minor, payout.fx_rate_micros)
    complete_delivery(scenario)
    profile = submit_initial(scenario, method)
    before = manual_view(Payout.objects.get(pk=payout.pk), user=scenario.admin)
    assert not before["destination"]["present"]
    assert not before["proof"]["present"]
    assert before["destination"]["setup_followup"]["status"] == "Awaiting approval"
    review_profile(
        actor=scenario.admin, reference=profile.public_reference, approve=True
    )
    payout.refresh_from_db()
    assert payout.method_version_id == old
    assert payout.dzd_profile_revision_id is None
    assert payout.active_instruction_version_id == profile.method.current_version_id
    assert payout.status == "eligible" and payout.block_reason == ""
    assert (
        payout.amount_eur_cents,
        payout.payout_amount_minor,
        payout.fx_rate_micros,
    ) == money
    amendment = payout.instruction_amendments.get()
    assert (amendment.old_version_id, amendment.new_version_id) == (
        old,
        payout.active_instruction_version_id,
    )
    assert amendment.reason_code == "initial_payout_setup_completed"
    after = manual_view(payout, user=scenario.admin)
    assert after["destination"]["present"] and after["proof"]["present"]
    assert after["destination"]["ccp_masked"] == "•••• 1111"


def test_admin_detail_distinguishes_current_method_from_frozen_instruction(settings):
    scenario, payout, method = funded_placeholder("initial-detail")
    profile = submit_initial(scenario, method)
    client = Client()
    client.force_login(scenario.admin)
    url = reverse("admin_console:payout-detail", args=[payout.pk])
    with override_settings(
        STORAGES={
            **settings.STORAGES,
            "staticfiles": {
                "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
            },
        }
    ):
        before = client.get(url).content.decode()
        assert "Destination setup was incomplete when this payout was funded" in before
        assert "Traveler's current DZD method" in before
        assert "Awaiting approval" in before
        assert "•••• 1111" not in before
        review_profile(
            actor=scenario.admin, reference=profile.public_reference, approve=True
        )
        after = client.get(url).content.decode()
    assert (
        "approved initial setup was attached through an audited reconciliation" in after
    )
    assert "•••• 1111" in after
    assert "crossed cheque" in after.lower()
    assert "1111111111" not in after


def test_rejected_and_correction_profiles_stay_unbound():
    for index, decision in enumerate(("rejected", "needs_attention")):
        scenario, payout, method = funded_placeholder(f"initial-{index}")
        profile = submit_initial(scenario, method)
        review_profile(
            actor=scenario.admin, reference=profile.public_reference, decision=decision
        )
        payout.refresh_from_db()
        assert payout.block_reason == "payout_setup_required"
        assert payout.active_instruction_version_id == payout.method_version_id
        assert not payout.instruction_amendments.exists()


def test_corrected_revision_reconciles_only_after_approval():
    scenario, payout, method = funded_placeholder("initial-correction")
    profile = submit_initial(scenario, method)
    review_profile(
        actor=scenario.admin,
        reference=profile.public_reference,
        decision="needs_attention",
    )
    method.refresh_from_db()
    corrected = submit_initial(scenario, method)
    payout.refresh_from_db()
    assert payout.active_instruction_version_id == payout.method_version_id
    review_profile(
        actor=scenario.admin, reference=corrected.public_reference, approve=True
    )
    payout.refresh_from_db()
    assert payout.active_instruction_version_id == corrected.method.current_version_id
    assert payout.instruction_amendments.count() == 1


def test_reapproval_is_idempotent_and_real_destination_never_rebinds():
    scenario, payout, method = funded_placeholder("initial-replay")
    profile = submit_initial(scenario, method)
    review_profile(
        actor=scenario.admin, reference=profile.public_reference, approve=True
    )
    event_count = payout.events.count()
    review_count = profile.reviews.count()
    review_profile(
        actor=scenario.admin, reference=profile.public_reference, approve=True
    )
    assert profile.reviews.count() == review_count
    release_after_profile_approval(profile=profile, actor=scenario.admin)
    assert (
        complete_initial_dzd_setup(payout_id=payout.pk, actor=scenario.admin)
        == "already_reconciled"
    )
    assert payout.events.count() == event_count
    assert PayoutInstructionAmendment.objects.filter(payout=payout).count() == 1

    later = upload_evidence(actor=scenario.traveler, upload=image_upload())
    method.refresh_from_db()
    changed = submit_dzd_profile(
        actor=scenario.traveler,
        expected_revision=method.revision,
        first_name="QA",
        last_name="Synthetic",
        ccp_number="2222222222",
        ccp_key="22",
        rip="2" * 20,
        proof_reference=later.public_reference,
    )
    review_profile(
        actor=scenario.admin,
        reference=changed.current_version.dzd_profile_revision.public_reference,
        approve=True,
    )
    payout.refresh_from_db()
    assert (
        payout.active_instruction_version_id
        == profile.method.versions.get(dzd_profile_revision=profile).pk
    )
    assert payout.instruction_amendments.count() == 1


def test_approved_profile_before_funding_needs_no_reconciliation():
    _, payout, profile = build_manual(prefix="initial-before")
    assert payout.active_instruction_version_id == payout.method_version_id
    assert payout.dzd_profile_revision_id == profile.pk
    assert not payout.instruction_amendments.exists()


def test_cancellation_award_uses_settlement_gate_and_presenter():
    scenario, payout, _ = build_manual(prefix="initial-comp", delivered=False)
    award_compensation(scenario, "initial-comp-award")
    payout.refresh_from_db()
    assert payout.eligibility_basis == "cancellation_compensation"
    view = manual_view(payout, user=scenario.admin)
    codes = {row["code"] for row in view["blockers"]}
    assert "delivery_unconfirmed" not in codes
    assert "balance_order_missing" not in codes
    assert "funding_unsettled" not in codes
    prepare(
        actor=scenario.admin,
        payout_id=payout.pk,
        expected_state_version=payout.state_version,
    )


def test_placeholder_cancellation_compensation_becomes_eligible_after_approval():
    scenario, payout, method = funded_placeholder("initial-comp-later")
    award_compensation(scenario, "initial-comp-later-award")
    payout.refresh_from_db()
    assert payout.eligibility_basis == "cancellation_compensation"
    assert payout.status == "blocked" and payout.block_reason == "payout_setup_required"
    profile = submit_initial(scenario, method)
    review_profile(
        actor=scenario.admin, reference=profile.public_reference, approve=True
    )
    payout.refresh_from_db()
    assert payout.status == "eligible" and payout.block_reason == ""
    assert payout.active_instruction_version_id == profile.method.current_version_id
    codes = {
        row["code"] for row in manual_view(payout, user=scenario.admin)["blockers"]
    }
    assert "delivery_unconfirmed" not in codes
    assert "balance_order_missing" not in codes


def test_repair_command_dry_run_then_audited_execution():
    scenario, payout, method = funded_placeholder("initial-repair")
    complete_delivery(scenario)
    profile = submit_initial(scenario, method)
    _record_profile_review(
        actor=scenario.admin, reference=profile.public_reference, approve=True
    )
    output = StringIO()
    call_command("reconcile_initial_dzd_setup", stdout=output)
    inventory = json.loads(output.getvalue())
    assert inventory["candidates"] == 1
    assert inventory["travelers"] == 1
    assert inventory["approved_current"] == 1
    assert inventory["results"] == {"safe_to_reconcile": 1}
    assert not inventory["mutations"]
    assert "1111111111" not in output.getvalue()
    assert not payout.instruction_amendments.exists()
    output = StringIO()
    call_command(
        "reconcile_initial_dzd_setup",
        execute=True,
        actor_id=scenario.admin.pk,
        stdout=output,
    )
    payout.refresh_from_db()
    assert json.loads(output.getvalue())["reconciled"] == 1
    assert payout.status == "eligible" and payout.block_reason == ""


@pytest.mark.django_db(transaction=True)
def test_parallel_reconciliation_creates_one_amendment():
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL row-lock race")
    from .test_phase8fh3_concurrency import _seed_admin_roles, _seed_settings

    _seed_settings()
    _seed_admin_roles()
    scenario, payout, method = funded_placeholder("initial-race")
    profile = submit_initial(scenario, method)
    _record_profile_review(
        actor=scenario.admin, reference=profile.public_reference, approve=True
    )

    # Two release workers see the same approved profile and empty funded slot.
    def replay(_):
        connections.close_all()
        try:
            return complete_initial_dzd_setup(payout_id=payout.pk, actor=scenario.admin)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as workers:
        assert sorted(workers.map(replay, range(2))) == [
            "already_reconciled",
            "reconciled",
        ]
    assert payout.instruction_amendments.count() == 1
