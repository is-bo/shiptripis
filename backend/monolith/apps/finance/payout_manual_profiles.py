"""Finance-only review and explicit sensitive profile access."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from apps.admin_panel.services import record_admin_action
from .models import (
    DzdPayoutProfileRevision,
    PayoutProfileReview,
    PayoutIdentityAttestation,
    TravelerPayoutMethod,
)
from .payout_profiles import require_capabilities, profile_name_consistency
from .sensitive_data import decrypt


def approved_profile(profile, *, funded_payout=None):
    """Current approval, with a narrow supersession exception for funded history.

    Only the original, still-bound instruction can use approval predating funding.
    Revocation, adverse review, invalid evidence and KYC remain live safety gates.
    """
    if (
        not profile
        or not profile.evidence_id
        or profile.evidence.upload_state != "complete"
        or profile.evidence.purpose != "account_document"
        or profile.evidence.owner_id != profile.method.traveler_id
    ):
        return False
    reviews = list(profile.reviews.all())
    review = max(reviews, key=lambda row: row.pk, default=None)
    if not review or review.status != "approved":
        return False
    identity = review.identity_attestation
    if not _valid_identity(identity, profile.method.traveler_id):
        return False
    if not list(identity.successors.all()):
        return True
    bound_at = None
    if (
        funded_payout is not None
        and funded_payout.snapshot_version
        and funded_payout.snapshot_at
        and funded_payout.method == "manual"
        and funded_payout.payout_currency == "DZD"
        and funded_payout.method_version_id
        and funded_payout.active_instruction_version_id == funded_payout.method_version_id
        and funded_payout.dzd_profile_revision_id == profile.pk
        and funded_payout.active_instruction_version.dzd_profile_revision_id == profile.pk
        and funded_payout.active_instruction_version.method_id == profile.method_id
        and funded_payout.traveler_id == profile.method.traveler_id
    ):
        historical = max(
            (row for row in reviews if row.created_at <= funded_payout.snapshot_at),
            key=lambda row: row.pk, default=None,
        )
        if historical and historical.status == "approved":
            review = historical
            identity = review.identity_attestation
            if identity.attested_at <= review.created_at:
                bound_at = funded_payout.snapshot_at
    superseded = any(
        bound_at is None or successor.attested_at <= bound_at
        for successor in identity.successors.all()
    )
    return (
        _valid_identity(identity, profile.method.traveler_id)
        and not superseded
    )


def _valid_identity(identity, traveler_id):
    """Supersession is distinct from these non-waivable safety gates."""
    return (
        identity.traveler_id == traveler_id
        and not hasattr(identity, "revocation")
        and identity.kyc_submission.status == "approved"
        and (
            not identity.kyc_submission.expires_at
            or identity.kyc_submission.expires_at > timezone.now()
        )
    )


#: The three outcomes a reviewer can record, and the safe reason code each one
#: leaves on the method. These are the *existing* `PayoutProfileReview` statuses
#: — H4 already reached all three — so naming them here makes the middle one
#: deliberately reachable rather than only arriving as a downgraded approval.
#: There is no second state machine: `approved_profile` still asks the same
#: question of the same latest review row.
REVIEW_DECISIONS = {
    "approved": "",
    "needs_attention": "profile_correction_required",
    "rejected": "profile_rejected",
}


@transaction.atomic
def review_profile(
    *, actor, reference, approve=None, accept_name_difference=False, decision=None
):
    """Record one reviewer decision against one immutable profile revision.

    `decision` is the explicit form and takes precedence: `approved`,
    `needs_attention` (the Traveler is asked to correct and resubmit) or
    `rejected`. `approve=True/False` is retained for the H4 API and maps onto
    `approved`/`rejected` unchanged, so no existing caller changes behaviour.

    Approving a profile whose account-holder name does not match the attested
    identity still requires `accept_name_difference`; without it the decision is
    recorded as `needs_attention` exactly as before.
    """

    require_capabilities(
        actor, "review_payout_profiles", "view_payout_sensitive", "view_payout_evidence"
    )
    if decision is None:
        if approve is None:
            raise ValidationError("A review decision is required.")
        decision = "approved" if approve else "rejected"
    if decision not in REVIEW_DECISIONS:
        raise ValidationError("Unknown payout profile review decision.")
    profile = DzdPayoutProfileRevision.objects.get(public_reference=reference)
    method = TravelerPayoutMethod.objects.select_for_update(no_key=True).get(
        pk=profile.method_id
    )
    if not profile.evidence_id or profile.evidence.upload_state != "complete":
        raise ValidationError("Full crossed cheque evidence required.")
    result = profile_name_consistency(actor=actor, profile=profile)
    identity = (
        PayoutIdentityAttestation.objects.filter(
            traveler_id=method.traveler_id,
            revocation__isnull=True,
            successors__isnull=True,
            kyc_submission__status="approved",
        )
        .order_by("-pk")
        .first()
    )
    if not identity or (
        identity.kyc_submission.expires_at
        and identity.kyc_submission.expires_at <= timezone.now()
    ):
        raise ValidationError("Current attested identity required.")
    status = decision
    if (
        status == "approved"
        and result["classification"] != "consistent"
        and not accept_name_difference
    ):
        status = "needs_attention"
    review = PayoutProfileReview.objects.create(
        profile=profile,
        reviewer=actor,
        identity_attestation=identity,
        status=status,
        reason_code=result["classification"],
    )
    if method.current_version.dzd_profile_revision_id == profile.pk:
        previous_status = method.status
        method.status = "ready" if status == "approved" else "needs_review"
        # A refused profile says *which* refusal it was, so the Traveler's card
        # can tell "send us a corrected cheque" apart from "this account was
        # refused". Neither code carries a reviewer's note.
        method.status_reason = REVIEW_DECISIONS[status]
        method.save(update_fields=["status", "status_reason"])
        if previous_status != method.status:
            from .payout_reconciliation import notify_profile_state

            notify_profile_state(method, state="ready" if status == "approved" else "needs_attention",
                                 key=f"dzd:{profile.public_reference}:{review.pk}")
    record_admin_action(
        actor=actor,
        action="payout_profile.reviewed",
        target=profile,
        after={
            "review": review.pk,
            "status": status,
            "name_difference_accepted": accept_name_difference,
        },
    )
    return review


@sensitive_variables()
def reveal_profile(*, actor, reference):
    require_capabilities(actor, "view_payout_sensitive", "view_payouts")
    profile = DzdPayoutProfileRevision.objects.get(public_reference=reference)
    values = {}
    for field in ("first_name", "last_name", "ccp_number", "ccp_key", "rip"):
        context = dict(
            model="DzdPayoutProfileRevision",
            record=profile.public_reference,
            field=field,
        )
        try:
            values[field] = decrypt(getattr(profile, field + "_encrypted"), **context)
        except ValidationError:
            if field != "rip":
                raise
            # H1 historical envelopes retain their authenticated field label.
            # New writes always use RIP; neither path accepts unauthenticated data.
            values[field] = decrypt(
                profile.rip_encrypted, **{**context, "field": "nip"}
            )
    record_admin_action(actor=actor, action="payout_profile.revealed", target=profile)
    return values
