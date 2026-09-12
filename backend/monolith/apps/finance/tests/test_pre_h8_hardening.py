"""Pre-H8: real PostgreSQL state, synthetic evidence and no provider network."""

from copy import copy
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, connection, transaction
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.disputes.models import Dispute
from apps.finance.control_plane.drilldown import drilldown
from apps.finance.control_plane.filters import Scope
from apps.finance.models import Payout, ProviderDispute
from apps.finance.payout_domain import open_hold
from apps.finance.payout_evidence import upload_evidence
from apps.finance.payout_manual import prepare, begin
from apps.finance.payout_manual_profiles import approved_profile, review_profile
from apps.finance.payout_mobile import dzd_method, payout_status, payouts_for
from apps.finance.payout_profiles import (
    assign_identity_review, attest_identity, revoke_identity, submit_dzd_profile,
)
from apps.finance.payout_release import evaluate_payout_release
from apps.finance.payout_snapshots import create_snapshot
from .factories import build_scenario
from .payout_execution_harness import H3_SETTINGS, build_stripe_payout
from .test_phase8fh4_manual import build_manual, configured_h4, image_upload  # noqa: F401
from .test_phase8fh5_control_plane import no_provider_network  # noqa: F401
from .test_phase8fh6a_mobile import to_bank_stage

configured_h4_fixture = configured_h4

pytestmark = pytest.mark.django_db(transaction=True)


def projection(payout, reason, owner=None, attention=True):
    row = drilldown(Scope.parse({"mode": "test", "search": str(payout.public_reference)}),
                    metric="payout_operations")["rows"][0]
    assert (row["block_reason"], row["needs_attention"], row["attention_owner"]) == (
        reason, attention, owner,
    )
    mobile = payout_status(payouts_for(payout.traveler).get(pk=payout.pk))
    assert mobile["blocking_reason"] == (reason if attention else None)
    for secret in ("acct_", "ba_", "po_", "ccp", "'rip", "encrypted", "requirement_codes",
                   "private-marker", "object_key", "identity_attestation", "QA Synthetic"):
        assert secret not in str(row)
    return row


@pytest.mark.parametrize("change,reason,owner", [
    ({}, None, None),
    ({"details_submitted": False}, "payout_setup_required", "traveler"),
    ({"transfers_status": "pending"}, "payout_profile_under_review", "provider"),
    ({"disabled_reason": "rejected.fraud"}, "payout_profile_needs_attention", None),
    ({"requirement_codes": ["private-marker"]}, "payout_setup_required", "traveler"),
])
def test_stripe_blocker_projection(change, reason, owner):
    with override_settings(**H3_SETTINGS):
        _, payout, account, _ = build_stripe_payout(prefix="pre-h8-stripe")
        for key, value in change.items():
            setattr(account, key, value)
        account.save()
        projection(payout, reason, owner, attention=bool(reason))


@pytest.mark.parametrize("review,reason,owner", [
    ("pending", "payout_profile_under_review", "finance"),
    ("rejected", "payout_profile_needs_attention", "finance"),
    ("needs_attention", "payout_profile_needs_attention", "finance"),
])
def test_dzd_profile_blocker_projection(configured_h4, review, reason, owner):
    with patch("apps.finance.tests.test_phase8fh4_manual.review_profile"):
        s, payout, profile = build_manual(prefix="pre-h8-dzd")
    if review != "pending":
        if review == "needs_attention":
            successor(s, family="Different")
        result = review_profile(actor=s.admin, reference=profile.public_reference,
                                approve=review != "rejected")
        assert result.status == review
    projection(payout, reason, owner)


@pytest.mark.parametrize("kind", ["hold", "shiptrip", "provider", "failed", "unknown", "balance"])
def test_operational_blockers_and_precedence(kind):
    with override_settings(**H3_SETTINGS):
        s, payout, account, capture = build_stripe_payout(prefix="pre-h8-gates")
        if kind in ("hold", "shiptrip", "provider"):
            open_hold(actor=s.admin, payout_id=payout.pk, kind="manual",
                      reason_code="private-marker", source_reference="pre-h8")
            account.details_submitted = False
            account.save()
        if kind == "shiptrip":
            Dispute.objects.create(deal=s.deal, opened_by=s.sender, opened_by_role="sender",
                                   category="other", reason_text="private-marker")
        elif kind == "provider":
            ProviderDispute.objects.create(provider="stripe", platform_id="qa", provider_mode="test",
                provider_object_id="dp_qa", source_attempt=capture, amount_minor=6000,
                currency="eur", status="needs_response")
        elif kind == "failed":
            Payout.objects.filter(pk=payout.pk).update(status="failed")
        elif kind in ("unknown", "balance"):
            Payout.objects.filter(pk=payout.pk).update(
                block_reason="private-marker" if kind == "unknown" else "connected_balance_pending")
        payout.refresh_from_db()
        reason, owner = {
            "hold": ("payout_on_hold", "finance"), "shiptrip": ("dispute_active", None),
            "provider": ("dispute_active", None), "failed": ("payout_failed", "finance"),
            "unknown": ("payout_on_hold", None), "balance": ("connected_balance_pending", "provider"),
        }[kind]
        projection(payout, reason, owner, attention=kind != "balance")


def test_returned_bank_payout_projection():
    from apps.finance.payout_reconciliation import reconcile_payout
    with override_settings(**H3_SETTINGS):
        s, payout, gateway = to_bank_stage("pre-h8-return")
        gateway.payout_status = "paid"
        reconcile_payout(payout.pk, gateway=gateway)
        gateway.payout_status = "failed"
        reconcile_payout(payout.pk, gateway=gateway)
        open_hold(actor=s.admin, payout_id=payout.pk, kind="manual",
                  reason_code="private-marker", source_reference="pre-h8-return")
        projection(payout, "payout_returned", "finance")


def successor(s, *, family="Synthetic"):
    assignment = assign_identity_review(actor=s.admin, traveler_id=s.traveler.pk,
                                        reviewer_id=s.outsider.pk)
    return attest_identity(actor=s.outsider, assignment_reference=assignment.public_reference,
                           given_name="QA", family_name=family)


def replacement(s, profile):
    profile.method.refresh_from_db()
    proof = upload_evidence(actor=s.traveler, upload=image_upload())
    return submit_dzd_profile(actor=s.traveler, expected_revision=profile.method.revision,
        first_name="QA", last_name="Synthetic", ccp_number="1111111111", ccp_key="11",
        rip="1" * 20, proof_reference=proof.public_reference)


def test_h7_frozen_approval_survives_reattestation_and_replacement(configured_h4):
    s, payout, profile = build_manual(prefix="pre-h8-payout7")
    identity_a = profile.reviews.get().identity_attestation
    frozen = (payout.method_version_id, payout.active_instruction_version_id,
              payout.dzd_profile_revision_id, payout.payout_amount_minor, payout.fx_rate_micros)
    identity_b = successor(s)
    assert identity_b.supersedes_id == identity_a.pk
    assert not approved_profile(profile)
    assert approved_profile(profile, funded_payout=payout)
    assert evaluate_payout_release(deal_id=s.deal.pk) == "payout_eligible"
    payout.refresh_from_db()
    assert payout.block_reason == ""
    projection(payout, None, attention=False)
    from apps.admin_panel.console_manual_presenter import destination_of
    assert destination_of(payout, profile, payout.active_instruction_version)["review"]["approved"]
    # Re-review does not erase approval-at-funding evidence either.
    review_profile(actor=s.admin, reference=profile.public_reference, approve=True)
    identity_b = successor(s)
    assert approved_profile(profile, funded_payout=payout)
    method = replacement(s, profile)
    current = method.current_version.dzd_profile_revision
    assert dzd_method(method)["state"] == "pending_review"
    assert not approved_profile(current)
    with pytest.raises(PermissionDenied):
        review_profile(actor=s.traveler, reference=current.public_reference, approve=True)
    review = review_profile(actor=s.admin, reference=current.public_reference, approve=True)
    assert review.identity_attestation_id == identity_b.pk
    assert approved_profile(current)
    prepare(actor=s.admin, payout_id=payout.pk, expected_state_version=payout.state_version)
    begin(actor=s.admin, payout_id=payout.pk, sequence=1)
    payout.refresh_from_db()
    assert frozen == (payout.method_version_id, payout.active_instruction_version_id,
                      payout.dzd_profile_revision_id, payout.payout_amount_minor, payout.fx_rate_micros)
    method.refresh_from_db()
    assert method.current_version.dzd_profile_revision_id == current.pk != profile.pk
    with pytest.raises(DatabaseError), transaction.atomic():
        Payout.objects.filter(pk=payout.pk).update(dzd_profile_revision=current)
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("UPDATE finance_payout_method_version SET country = 'XX' WHERE id = %s",
                       [payout.method_version_id])


def test_future_snapshot_cannot_reuse_superseded_identity(configured_h4):
    s, payout, profile = build_manual(prefix="pre-h8-old")
    successor(s)
    with override_settings(PAYOUT_PROFILES_ENABLED=False):
        future = build_scenario(prefix="pre-h8-future")
        future.journey = s.journey
        future.leg = s.leg
        future.traveler = s.traveler
        future.accept(reward_eur_cents=6000)
    # Isolate the routing contract; no provider capture or financial-row rewrite.
    new = create_snapshot(deal_id=future.deal.pk, traveler_id=s.traveler.pk, amount_eur_cents=6000)
    assert new.method_version_id == payout.method_version_id
    assert not approved_profile(profile, funded_payout=new)
    assert not approved_profile(profile)
    assert approved_profile(profile, funded_payout=payout)
    unbound = copy(payout)
    unbound.snapshot_version = 0
    assert not approved_profile(profile, funded_payout=unbound)
    projection(payout, None, attention=False)


@pytest.mark.parametrize("gate", ["revoked", "kyc_expired", "rejected"])
def test_historical_exception_preserves_live_safety_gates(configured_h4, gate):
    s, payout, profile = build_manual(prefix="pre-h8-safety")
    identity = profile.reviews.get().identity_attestation
    successor(s)
    if gate == "revoked":
        revoke_identity(actor=s.outsider, attestation_reference=identity.public_reference,
                        reason_code="private-marker")
    elif gate == "kyc_expired":
        identity.kyc_submission.expires_at = timezone.now() - timedelta(seconds=1)
        identity.kyc_submission.save(update_fields=["expires_at"])
    else:
        review_profile(actor=s.admin, reference=profile.public_reference, approve=False)
    assert not approved_profile(profile, funded_payout=payout)
    with pytest.raises(ValidationError):
        prepare(actor=s.admin, payout_id=payout.pk, expected_state_version=payout.state_version)
    projection(payout, "payout_profile_needs_attention", "finance")


def test_setup_visible_before_delivery_and_drilldown_reads_are_bounded(configured_h4):
    with patch("apps.finance.tests.test_phase8fh4_manual.review_profile"):
        s, payout, _ = build_manual(prefix="pre-h8-visible", delivered=False)
    projection(payout, "payout_profile_under_review", "finance")
    from apps.finance.payout_mobile import page_context, payout_attention
    page = list(payouts_for(s.traveler))
    context = page_context(page, include_actions=False)
    with CaptureQueriesContext(connection) as queries:
        for item in page * 25:
            payout_attention(item, context=context)
    assert len(queries) == 0
