"""Prepare durable local intents only. Dispatch is deliberately absent in H1."""

import hashlib
import json

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.core.financial_locks import lock_deal_lifecycle
from .models import Payout, PayoutAttempt, PayoutProviderOperation
from .payout_domain import active_holds, require_uncommitted
from .payout_profiles import require_capabilities


@transaction.atomic
def prepare_attempt(*, actor, payout_id, expected_state_version, idempotency_key):
    require_capabilities(actor, "retry_payouts", "view_payouts")
    seed = Payout.objects.get(pk=payout_id)
    lock_deal_lifecycle(seed.deal_id)
    payout = Payout.objects.select_for_update(no_key=True).get(pk=payout_id)
    existing = PayoutAttempt.objects.filter(idempotency_key=idempotency_key).first()
    if existing:
        if (
            existing.payout_id != payout.pk
            or existing.instruction_version_id != payout.active_instruction_version_id
            or existing.amount_eur_cents != payout.amount_eur_cents
        ):
            raise ValidationError(
                "Attempt replay conflicts with its immutable request."
            )
        return existing
    if (
        not payout.snapshot_version
        or payout.provider_mode not in ("test", "live")
        or payout.state_version != expected_state_version
        or payout.amount_eur_cents <= 0
        or not payout.active_instruction_version_id
    ):
        raise ValidationError("Versioned same-mode positive payout required.")
    if (
        payout.status != "eligible"
        or payout.block_reason
        or not payout.eligible_at
        or active_holds(payout).exists()
    ):
        raise ValidationError("Payout is not ready for preparation.")
    require_uncommitted(payout)
    if payout.attempts.filter(status="prepared").exists():
        raise ValidationError("Payout already has a prepared intent.")
    version = payout.active_instruction_version
    if version.stripe_account and (
        version.stripe_account.provider_mode != payout.provider_mode
        or version.stripe_account.traveler_id != payout.traveler_id
    ):
        raise ValidationError("Destination mode/owner mismatch.")
    digest = hashlib.sha256(
        json.dumps(
            [
                str(payout.public_reference),
                payout.amount_eur_cents,
                payout.payout_currency,
                str(version.public_reference),
                payout.provider_mode,
            ]
        ).encode()
    ).hexdigest()
    return PayoutAttempt.objects.create(
        payout=payout,
        sequence=payout.attempts.count() + 1,
        instruction_version=version,
        amount_revision=payout.amount_revisions.order_by("-revision").first(),
        amount_eur_cents=payout.amount_eur_cents,
        currency=payout.payout_currency,
        rail=payout.method,
        provider_mode=payout.provider_mode,
        idempotency_key=idempotency_key,
        request_fingerprint=digest,
        operator=actor if payout.method == "manual" else None,
    )


@transaction.atomic
def prepare_provider_operation(
    *, actor, attempt_id, kind, account_scope, idempotency_key
):
    require_capabilities(actor, "retry_payouts", "view_payouts")
    seed = PayoutAttempt.objects.select_related("payout").get(pk=attempt_id)
    lock_deal_lifecycle(seed.payout.deal_id)
    payout = Payout.objects.select_for_update(no_key=True).get(pk=seed.payout_id)
    attempt = PayoutAttempt.objects.select_for_update(no_key=True).get(pk=attempt_id)
    if (
        kind
        not in (
            "transfer_create",
            "bank_payout_create",
            "transfer_reverse",
            "bank_payout_cancel",
        )
        or attempt.rail != "stripe_transfer"
        or attempt.provider_mode != payout.provider_mode
    ):
        raise ValidationError("Invalid provider-operation contract.")
    account = attempt.instruction_version.stripe_account
    if not account or account_scope not in (
        account.platform_id,
        account.provider_account_id,
    ):
        raise ValidationError("Provider operation account scope mismatch.")
    if (
        kind in ("bank_payout_create", "bank_payout_cancel")
        and account_scope != account.provider_account_id
    ):
        raise ValidationError("Bank payout requires connected-account scope.")
    if (
        kind in ("transfer_create", "transfer_reverse")
        and account_scope != account.platform_id
    ):
        raise ValidationError("Transfer requires platform scope.")
    fingerprint = hashlib.sha256(
        json.dumps(
            [attempt.request_fingerprint, kind, account_scope, attempt.amount_eur_cents]
        ).encode()
    ).hexdigest()
    existing = PayoutProviderOperation.objects.filter(
        idempotency_key=idempotency_key
    ).first()
    if existing:
        if (
            existing.request_fingerprint != fingerprint
            or existing.attempt_id != attempt.pk
        ):
            raise ValidationError("Provider operation replay conflict.")
        return existing
    if attempt.status != "prepared":
        raise ValidationError("Only local prepared intents are available in H1.")
    return PayoutProviderOperation.objects.create(
        attempt=attempt,
        kind=kind,
        account_scope=account_scope,
        provider_mode=attempt.provider_mode,
        sequence=attempt.operations.count() + 1,
        idempotency_key=idempotency_key,
        request_fingerprint=fingerprint,
        amount_minor=attempt.amount_eur_cents,
        currency="EUR",
    )
