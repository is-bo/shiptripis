"""Complete the destination of a funded payout that had no DZD profile yet."""

from django.db import transaction
from django.db import models
from django.utils import timezone

from apps.admin_panel.services import record_admin_action
from apps.core.financial_locks import lock_deal_lifecycle
from apps.disputes.models import Dispute

from .models import Payout, PayoutInstructionAmendment, TravelerPayoutMethod
from .payout_domain import append_event_locked, require_uncommitted
from .payout_manual_profiles import approved_profile
from .payout_profiles import POLICY_VERSION, require_capabilities


SETTLEMENT_BASES = frozenset({"cancellation_compensation", "dispute_settlement"})


def setup_required_payouts():
    """Read-only inventory; the domain command repeats all checks under locks."""
    return Payout.objects.filter(
        snapshot_version__gt=0,
        method="manual",
        payout_currency="DZD",
        block_reason="payout_setup_required",
        status__in=("blocked", "not_eligible"),
        method_version_id__isnull=False,
        active_instruction_version_id__isnull=False,
        dzd_profile_revision_id__isnull=True,
        active_instruction_version_id=models.F("method_version_id"),
        active_instruction_version__dzd_profile_revision_id__isnull=True,
    ).order_by("pk")


def pending_setup_rechecks():
    """An amendment committed but release evaluation was interrupted."""
    return (
        Payout.objects.filter(
            block_reason="payout_setup_required",
            status__in=("blocked", "not_eligible"),
            instruction_amendments__reason_code="initial_payout_setup_completed",
        )
        .distinct()
        .order_by("pk")
    )


def initial_setup_reason(payout, method):
    """A stable, non-sensitive refusal code for dry runs and locked writes."""
    old = payout.active_instruction_version
    if (
        payout.snapshot_version < 1
        or payout.provider_mode not in ("test", "live")
        or not payout.funding_attempt_id
        or payout.funding_attempt.provider_mode != payout.provider_mode
        or not payout.fx_rate_micros
        or payout.payout_amount_minor is None
        or payout.method != "manual"
        or payout.payout_currency != "DZD"
        or payout.block_reason != "payout_setup_required"
        or payout.status not in ("blocked", "not_eligible")
        or not old
        or payout.method_version_id != old.pk
        or payout.dzd_profile_revision_id is not None
        or old.dzd_profile_revision_id is not None
        or old.rail != "manual"
        or old.currency != "DZD"
        or old.method_id != method.pk
        or method.traveler_id != payout.traveler_id
        or method.currency != "DZD"
        or method.method != "manual"
    ):
        return "not_initial_setup_placeholder"
    if (
        payout.instruction_amendments.exists()
        or payout.instruction_confirmations.exists()
    ):
        return "instruction_change_pending_or_recorded"
    if payout.attempts.exists():
        return "payout_attempt_exists"
    version = method.current_version
    if (
        not method.enabled
        or method.status != "ready"
        or not version
        or version.pk == old.pk
        or version.method_id != method.pk
        or version.sequence <= old.sequence
        or version.rail != "manual"
        or version.currency != "DZD"
        or version.country != "DZ"
        or version.policy_version != POLICY_VERSION
        or not version.dzd_profile_revision_id
        or version.dzd_profile_revision.method_id != method.pk
        or version.created_by_id != payout.traveler_id
        or version.source != "traveler"
        or not payout.snapshot_at
        or old.consent_at > payout.snapshot_at
        or version.consent_at <= payout.snapshot_at
        or version.dzd_profile_revision.submitted_at <= payout.snapshot_at
    ):
        return "no_current_traveler_submitted_profile"
    if not approved_profile(version.dzd_profile_revision):
        return "profile_not_approved_or_identity_invalid"
    return ""


@transaction.atomic
def complete_initial_dzd_setup(*, payout_id, actor):
    """One explicit amendment from a funded empty slot to the first ready method.

    The traveler's post-funding profile submission and version consent are the
    authorization for this *initial setup* only. A real funded destination is
    never eligible here; it still needs confirm_instruction/amend_instruction.
    """
    require_capabilities(actor, "review_payout_profiles", "view_payout_sensitive")
    seed = Payout.objects.get(pk=payout_id)
    from .mode_safety import require_object_mode, require_provider_mode

    require_object_mode(seed.provider_mode)
    require_provider_mode(seed.provider_mode)
    lock_deal_lifecycle(seed.deal_id)
    payout = Payout.objects.select_for_update(no_key=True).get(pk=payout_id)
    if payout.instruction_amendments.filter(
        reason_code="initial_payout_setup_completed"
    ).exists():
        return "already_reconciled"
    if payout.block_reason != "payout_setup_required":
        return "not_setup_required"
    old = payout.active_instruction_version
    if not old:
        return "not_initial_setup_placeholder"
    method = (
        TravelerPayoutMethod.objects.select_for_update(of=("self",), no_key=True)
        .select_related("current_version__dzd_profile_revision")
        .get(pk=old.method_id)
    )
    reason = initial_setup_reason(payout, method)
    if reason:
        return reason
    require_uncommitted(payout)
    version = method.current_version
    amendment = PayoutInstructionAmendment.objects.create(
        payout=payout,
        sequence=1,
        old_version=old,
        new_version=version,
        traveler=payout.traveler,
        confirmed_at=version.consent_at,
        reviewed_by=actor,
        reason_code="initial_payout_setup_completed",
        expected_state=payout.status,
        expected_state_version=payout.state_version,
    )
    payout.active_instruction_version = version
    payout.save(update_fields=["active_instruction_version"])
    append_event_locked(
        payout,
        previous=payout.status,
        reason="initial_payout_setup_completed",
        actor=actor,
    )
    record_admin_action(
        actor=actor,
        action="payout.initial_setup_reconciled",
        target=amendment,
        after={
            "payout": payout.pk,
            "old_version": old.pk,
            "new_version": version.pk,
            "profile_revision": version.dzd_profile_revision_id,
            "source": "traveler_submission_and_admin_approval",
        },
    )
    # Snapshot fields (including the originally empty profile) remain immutable.
    # Readiness is evaluated separately after this transition commits.
    return "reconciled"


@transaction.atomic
def reevaluate_settlement_setup(*, payout_id):
    """Re-run the settlement award's readiness, without delivery-only gates."""
    seed = Payout.objects.get(pk=payout_id)
    lock_deal_lifecycle(seed.deal_id)
    payout = (
        Payout.objects.select_for_update(no_key=True)
        .select_related("deal")
        .get(pk=payout_id)
    )
    if payout.eligibility_basis not in SETTLEMENT_BASES:
        return "not_settlement_award"
    if payout.status in (
        "paid",
        "cancelled",
        "processing",
        "sent",
        "scheduled",
        "frozen",
    ):
        return f"payout_{payout.status}"
    if (
        not payout.eligibility_decision_reference
        or not payout.amount_revisions.filter(
            settlement_reference=payout.eligibility_decision_reference,
            amount_eur_cents=payout.amount_eur_cents,
        ).exists()
        or payout.amount_eur_cents <= 0
    ):
        return "settlement_award_missing"
    if payout.block_reason == "payout_setup_required":
        version = payout.active_instruction_version
        if version and approved_profile(
            version.dzd_profile_revision, funded_payout=payout
        ):
            payout.block_reason = ""
            payout.save(update_fields=["block_reason"])
    if payout.block_reason:
        return payout.block_reason
    if payout.deal.disputes.filter(status__in=Dispute.ACTIVE_STATUSES).exists():
        return "dispute_active"
    if payout.deal.delivery_confirmed_at and (
        not payout.deal.protection_ends_at
        or payout.deal.protection_ends_at > timezone.now()
    ):
        return "protection_open"
    if payout.status != "eligible":
        previous = payout.status
        payout.status = "eligible"
        payout.eligible_at = payout.eligible_at or timezone.now()
        payout.save(update_fields=["status", "eligible_at", "updated_at"])
        append_event_locked(payout, previous=previous, reason="settlement_eligibility")
    return "eligible"


def release_after_profile_approval(*, profile, actor):
    """Release both already-bound payouts and qualifying empty setup slots."""
    from .payout_release import evaluate_payout_release

    bound = Payout.objects.filter(
        dzd_profile_revision_id=profile.pk,
        status__in=("blocked", "eligible", "scheduled"),
    ).values_list("pk", "deal_id", "eligibility_basis")
    for payout_id, deal_id, basis in bound.iterator():
        if basis in SETTLEMENT_BASES:
            reevaluate_settlement_setup(payout_id=payout_id)
        else:
            evaluate_payout_release(deal_id=deal_id)
    profile.method.refresh_from_db()
    if profile.method.current_version is None or (
        profile.method.current_version.dzd_profile_revision_id != profile.pk
    ):
        return
    candidates = setup_required_payouts().filter(traveler_id=profile.method.traveler_id)
    for payout_id, deal_id, basis in candidates.values_list(
        "pk", "deal_id", "eligibility_basis"
    ).iterator():
        if complete_initial_dzd_setup(payout_id=payout_id, actor=actor) != "reconciled":
            continue
        if basis in SETTLEMENT_BASES:
            reevaluate_settlement_setup(payout_id=payout_id)
        else:
            evaluate_payout_release(deal_id=deal_id)
    for payout_id, deal_id, basis in (
        pending_setup_rechecks()
        .filter(
            traveler_id=profile.method.traveler_id,
            active_instruction_version__dzd_profile_revision_id=profile.pk,
        )
        .values_list("pk", "deal_id", "eligibility_basis")
        .iterator()
    ):
        if basis in SETTLEMENT_BASES:
            reevaluate_settlement_setup(payout_id=payout_id)
        else:
            evaluate_payout_release(deal_id=deal_id)
