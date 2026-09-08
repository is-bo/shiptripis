"""Versioned preference/profile commands. No provider or storage I/O."""

import hashlib
import json

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from apps.accounts.models import User
from apps.admin_panel.permissions import has_all_admin_permissions
from apps.admin_panel.services import record_admin_action
from apps.kyc.models import KycSubmission
from .models import (
    TravelerPayoutMethod,
    PayoutMethodVersion,
    DzdPayoutProfileRevision,
    PayoutIdentityAttestation,
    PayoutIdentityReviewAssignment,
    PayoutIdentityRevocation,
)
from .sensitive_data import encrypt, decrypt, account_fingerprint, normalize_digits

POLICY_VERSION = "payout_profile_v1"


def require_profiles():
    if not settings.PAYOUT_PROFILES_ENABLED:
        raise PermissionDenied("Payout profiles are disabled.")


def require_capabilities(actor, *codes):
    require_profiles()
    if not has_all_admin_permissions(actor, *codes):
        raise PermissionDenied("Payout capability required.")


def _traveler(actor):
    require_profiles()
    user = User.objects.get(pk=actor.pk)
    if not user.is_active or user.is_banned or user.role not in ("traveler", "both"):
        raise PermissionDenied("Traveler access required.")
    return user


def _method(actor, currency, expected_revision):
    user = _traveler(actor)
    # A fixed row exists for each preference once set. Serialize initial insert
    # with the user witness, before method rows; funding takes existing methods
    # only and never acquires User after Payout.
    User.objects.select_for_update(no_key=True).get(pk=user.pk)
    if currency not in ("EUR", "DZD"):
        raise ValidationError("Unsupported payout currency.")
    method, _ = TravelerPayoutMethod.objects.get_or_create(
        traveler=user,
        method="manual" if currency == "DZD" else "stripe_connect",
        defaults={"currency": currency},
    )
    method = TravelerPayoutMethod.objects.select_for_update(no_key=True).get(
        pk=method.pk
    )
    if type(expected_revision) is not int or method.revision != expected_revision:
        raise ValidationError("Payout method revision conflict.")
    return method


def _version(method, *, actor, country="", profile=None):
    sequence = (
        method.versions.order_by("-sequence").values_list("sequence", flat=True).first()
        or 0
    ) + 1
    content = [
        str(method.public_reference),
        sequence,
        method.currency,
        country,
        str(profile.public_reference) if profile else None,
        POLICY_VERSION,
    ]
    return PayoutMethodVersion.objects.create(
        method=method,
        sequence=sequence,
        rail="manual" if method.currency == "DZD" else "stripe_transfer",
        currency=method.currency,
        country=country,
        dzd_profile_revision=profile,
        policy_version=POLICY_VERSION,
        consent_at=timezone.now(),
        created_by=actor,
        content_hash=hashlib.sha256(json.dumps(content).encode()).hexdigest(),
    )


@transaction.atomic
def set_preference(
    *,
    actor,
    currency,
    enabled,
    expected_revision,
    country="",
    consent_policy=POLICY_VERSION,
):
    if type(enabled) is not bool or consent_policy != POLICY_VERSION:
        raise ValidationError(
            "Explicit current policy consent and boolean preference required."
        )
    method = _method(actor, currency, expected_revision)
    method.currency = currency
    method.save(update_fields=["currency"])
    if enabled and currency == "EUR":
        allowed = set(settings.STRIPE_CONNECT_ALLOWED_COUNTRIES) & {"FR", "DE", "ES"}
        if country not in allowed:
            raise ValidationError("Payout country is unavailable.")
    if not enabled and method.current_version_id is None:
        # Disabled method is a preference only, not a destination snapshot.
        country = ""
    if enabled and method.current_version_id is None:
        method.current_version = _version(method, actor=actor, country=country)
    elif enabled and currency == "EUR" and country != method.current_version.country:
        method.current_version = _version(method, actor=actor, country=country)
        method.status = "setup_required"
    method.enabled = enabled
    method.revision += 1
    # Preference changes must not erase the destination's review/readiness.
    # The API projects disabled separately when enabled is false.
    method.save(
        update_fields=[
            "currency",
            "enabled",
            "revision",
            "status",
            "current_version",
            "updated_at",
        ]
    )
    record_admin_action(
        actor=actor,
        action="payout_method.enabled" if enabled else "payout_method.disabled",
        target=method,
        after={"currency": currency, "revision": method.revision},
    )
    return method


@sensitive_variables()
@transaction.atomic
def submit_dzd_profile(
    *,
    actor,
    expected_revision,
    first_name,
    last_name,
    ccp_number,
    ccp_key,
    nip,
    consent_policy=POLICY_VERSION,
):
    if (
        consent_policy != POLICY_VERSION
        or not first_name.strip()
        or not last_name.strip()
        or max(len(first_name), len(last_name)) > 160
    ):
        raise ValidationError("Profile names and current consent are required.")
    method = _method(actor, "DZD", expected_revision)
    method.currency = "DZD"
    method.save(update_fields=["currency"])
    number = normalize_digits(ccp_number, minimum=1, maximum=20)
    key = normalize_digits(ccp_key, minimum=2, maximum=2)
    nip = normalize_digits(nip, minimum=20, maximum=20)
    fingerprint = account_fingerprint(number, key, nip)
    sequence = (
        method.dzd_revisions.order_by("-sequence")
        .values_list("sequence", flat=True)
        .first()
        or 0
    ) + 1
    profile = DzdPayoutProfileRevision(
        method=method,
        sequence=sequence,
        ccp_last_four=number[-4:],
        nip_last_four=nip[-4:],
        account_fingerprint=fingerprint,
    )
    for field, value in {
        "first_name": first_name,
        "last_name": last_name,
        "ccp_number": number,
        "ccp_key": key,
        "nip": nip,
    }.items():
        setattr(
            profile,
            field + "_encrypted",
            encrypt(
                value,
                model="DzdPayoutProfileRevision",
                record=profile.public_reference,
                field=field,
            ),
        )
    profile.save()
    method.current_version = _version(
        method, actor=actor, country="DZ", profile=profile
    )
    method.revision += 1
    method.status = "pending_review"
    # Duplicate accounts never disclose the other traveler or auto-reject.
    duplicate = (
        DzdPayoutProfileRevision.objects.filter(account_fingerprint=fingerprint)
        .exclude(method__traveler=actor)
        .exists()
    )
    method.status_reason = (
        "cross_user_account_review" if duplicate else "profile_review_required"
    )
    method.save(
        update_fields=[
            "currency",
            "current_version",
            "revision",
            "status",
            "status_reason",
            "updated_at",
        ]
    )
    record_admin_action(
        actor=actor,
        action="payout_profile.submitted",
        target=profile,
        after={"sequence": sequence},
    )
    record_admin_action(
        actor=actor,
        action="payout_method.destination_versioned",
        target=method,
        after={"revision": method.revision},
    )
    return method


@transaction.atomic
def assign_identity_review(*, actor, traveler_id, reviewer_id):
    require_capabilities(actor, "review_payout_profiles", "view_payout_sensitive")
    reviewer = User.objects.get(pk=reviewer_id)
    if not has_all_admin_permissions(reviewer, "attest_payout_identity"):
        raise PermissionDenied("Identity reviewer capability required.")
    kyc = (
        KycSubmission.objects.filter(user_id=traveler_id, status="approved")
        .order_by("-reviewed_at", "-pk")
        .first()
    )
    if not kyc or (kyc.expires_at and kyc.expires_at <= timezone.now()):
        raise ValidationError("Approved KYC required.")
    assignment = PayoutIdentityReviewAssignment.objects.create(
        traveler_id=traveler_id,
        reviewer=reviewer,
        kyc_submission=kyc,
        assigned_by=actor,
    )
    record_admin_action(
        actor=actor, action="payout_identity.assigned", target=assignment
    )
    return assignment


@sensitive_variables()
@transaction.atomic
def attest_identity(
    *, actor, assignment_reference, given_name, family_name, aliases=()
):
    require_capabilities(actor, "attest_payout_identity")
    assignment = PayoutIdentityReviewAssignment.objects.get(
        public_reference=assignment_reference, reviewer=actor, closed_at__isnull=True
    )
    # KYC witness precedes payout identity/profile records in canonical order.
    kyc = KycSubmission.objects.select_for_update(no_key=True).get(
        pk=assignment.kyc_submission_id
    )
    assignment = PayoutIdentityReviewAssignment.objects.select_for_update(
        no_key=True
    ).get(pk=assignment.pk)
    if (
        assignment.closed_at
        or kyc.status != "approved"
        or (kyc.expires_at and kyc.expires_at <= timezone.now())
    ):
        raise ValidationError("Current approved KYC and open assignment required.")
    if (
        not given_name.strip()
        or not family_name.strip()
        or max(len(given_name), len(family_name)) > 160
    ):
        raise ValidationError("Legal given and family names required.")
    if (
        not isinstance(aliases, (list, tuple))
        or len(aliases) > 10
        or any(
            not isinstance(a, (list, tuple))
            or len(a) != 2
            or any(not isinstance(v, str) or not v.strip() or len(v) > 160 for v in a)
            for a in aliases
        )
    ):
        raise ValidationError("Invalid attested aliases.")
    previous = (
        PayoutIdentityAttestation.objects.filter(traveler=assignment.traveler)
        .order_by("-attested_at", "-pk")
        .first()
    )
    record = PayoutIdentityAttestation(
        traveler=assignment.traveler,
        kyc_submission=kyc,
        attested_by=actor,
        policy_version=POLICY_VERSION,
        supersedes=previous,
    )
    for field, value in {
        "given_name": given_name,
        "family_name": family_name,
        "aliases": json.dumps(aliases),
    }.items():
        setattr(
            record,
            field + "_encrypted",
            encrypt(
                value,
                model="PayoutIdentityAttestation",
                record=record.public_reference,
                field=field,
            ),
        )
    record.save()
    assignment.closed_at = timezone.now()
    assignment.save(update_fields=["closed_at"])
    record_admin_action(
        actor=actor,
        action="payout_identity.attested",
        target=record,
        after={"policy_version": POLICY_VERSION},
    )
    return record


@transaction.atomic
def revoke_identity(*, actor, attestation_reference, reason_code):
    require_capabilities(actor, "attest_payout_identity")
    record = PayoutIdentityAttestation.objects.get(
        public_reference=attestation_reference
    )
    if record.attested_by_id != actor.pk or not reason_code:
        raise PermissionDenied("Only the attesting reviewer can revoke this authority.")
    revocation, created = PayoutIdentityRevocation.objects.get_or_create(
        attestation=record, defaults={"actor": actor, "reason_code": reason_code}
    )
    if created:
        record_admin_action(
            actor=actor, action="payout_identity.revoked", target=revocation
        )
    return revocation


@sensitive_variables()
def profile_name_consistency(*, actor, profile):
    require_capabilities(actor, "review_payout_profiles", "view_payout_sensitive")
    attestation = (
        PayoutIdentityAttestation.objects.filter(
            traveler_id=profile.method.traveler_id,
            revocation__isnull=True,
            successors__isnull=True,
            kyc_submission__status="approved",
        )
        .select_related("kyc_submission")
        .order_by("-attested_at", "-pk")
        .first()
    )
    from .payout_identity import compare_names

    if not attestation or (
        attestation.kyc_submission.expires_at
        and attestation.kyc_submission.expires_at <= timezone.now()
    ):
        return compare_names("", "")
    given = decrypt(
        profile.first_name_encrypted,
        model="DzdPayoutProfileRevision",
        record=profile.public_reference,
        field="first_name",
    )
    family = decrypt(
        profile.last_name_encrypted,
        model="DzdPayoutProfileRevision",
        record=profile.public_reference,
        field="last_name",
    )
    verified_given = decrypt(
        attestation.given_name_encrypted,
        model="PayoutIdentityAttestation",
        record=attestation.public_reference,
        field="given_name",
    )
    verified_family = decrypt(
        attestation.family_name_encrypted,
        model="PayoutIdentityAttestation",
        record=attestation.public_reference,
        field="family_name",
    )
    aliases = json.loads(
        decrypt(
            attestation.aliases_encrypted,
            model="PayoutIdentityAttestation",
            record=attestation.public_reference,
            field="aliases",
        )
    )
    result = compare_names(
        given,
        family,
        attested_given=verified_given,
        attested_family=verified_family,
        aliases=aliases,
    )
    record_admin_action(
        actor=actor,
        action="payout_identity.compared",
        target=profile,
        after={"classification": result["classification"]},
    )
    return result
