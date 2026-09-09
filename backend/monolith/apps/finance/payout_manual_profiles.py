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


def approved_profile(profile):
    if (
        not profile
        or not profile.evidence_id
        or profile.evidence.upload_state != "complete"
        or profile.evidence.purpose != "account_document"
        or profile.evidence.owner_id != profile.method.traveler_id
    ):
        return False
    review = (
        profile.reviews.order_by("-pk")
        .select_related("identity_attestation__kyc_submission")
        .first()
    )
    if not review or review.status != "approved":
        return False
    identity = review.identity_attestation
    return (
        identity.traveler_id == profile.method.traveler_id
        and not hasattr(identity, "revocation")
        and not identity.successors.exists()
        and identity.kyc_submission.status == "approved"
        and (
            not identity.kyc_submission.expires_at
            or identity.kyc_submission.expires_at > timezone.now()
        )
    )


@transaction.atomic
def review_profile(*, actor, reference, approve, accept_name_difference=False):
    require_capabilities(
        actor, "review_payout_profiles", "view_payout_sensitive", "view_payout_evidence"
    )
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
    status = "approved" if approve else "rejected"
    if (
        approve
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
        method.status = "ready" if status == "approved" else "needs_review"
        method.status_reason = "" if status == "approved" else "profile_review_required"
        method.save(update_fields=["status", "status_reason"])
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
