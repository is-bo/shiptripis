"""Operator-attested DZD settlement. This module never calls a payment provider."""

import hashlib
import json

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.admin_panel.services import record_admin_action
from apps.disputes.models import Dispute
from .models import PayoutAttempt, PayoutEvidence, PayoutEvent, PayoutFundingAllocation
from .payout_domain import (
    active_holds,
    append_event_locked,
    require_uncommitted,
    source_available_cents,
)
from .payout_execution import _lock_payout_aggregate
from .payout_profiles import require_capabilities
from .payout_reconciliation import notify_payout_state
from .money import convert_eur_cents


def authorize(actor):
    require_capabilities(
        actor,
        "view_payouts",
        "retry_payouts",
        "view_payout_sensitive",
        "view_payout_evidence",
    )
    if not settings.PAYOUT_DZD_EXECUTION_ENABLED:
        raise PermissionDenied("Manual DZD execution is disabled.")


def _gate(payout, balance):
    from .payout_manual_profiles import approved_profile
    from .models import TravelerPayoutMethod

    if (
        not payout.snapshot_version
        or payout.method != "manual"
        or payout.payout_currency != "DZD"
        or payout.provider_mode != "test"
    ):
        raise ValidationError("A versioned TEST manual DZD payout is required.")
    if payout.block_reason or payout.amount_eur_cents <= 0 or not payout.eligible_at:
        raise ValidationError("Payout is not eligible.")
    if payout.status not in ("eligible", "scheduled", "processing", "sent"):
        raise ValidationError("Payout state prevents progression.")
    deal = payout.deal
    if (
        not deal.delivery_confirmed_at
        or not deal.protection_ends_at
        or deal.protection_ends_at > timezone.now()
        or deal.disputes.filter(status__in=Dispute.ACTIVE_STATUSES).exists()
        or active_holds(payout).exists()
    ):
        raise ValidationError("Delivery, protection or hold gate prevents progression.")
    if balance.outstanding_eur_cents or balance.refunded_eur_cents:
        raise ValidationError("Funding is not settled.")
    if not payout.fx_rate_micros or payout.payout_amount_minor != convert_eur_cents(
        payout.amount_eur_cents, to_currency="DZD", rate_micros=payout.fx_rate_micros
    ):
        raise ValidationError("Frozen settlement amount is inconsistent.")
    version = payout.active_instruction_version
    if (
        not version
        or version.rail != "manual"
        or version.currency != "DZD"
        or version.method.traveler_id != payout.traveler_id
    ):
        raise ValidationError("Frozen destination is invalid.")
    TravelerPayoutMethod.objects.select_for_update(no_key=True).get(
        pk=version.method_id
    )
    if not approved_profile(version.dzd_profile_revision):
        raise ValidationError("Reviewed profile and crossed cheque are required.")


def _identity(payout):
    return hashlib.sha256(
        json.dumps(
            [
                str(payout.public_reference),
                payout.amount_eur_cents,
                payout.payout_amount_minor,
                payout.fx_rate_micros,
                payout.active_instruction_version_id,
                payout.provider_mode,
            ]
        ).encode()
    ).hexdigest()


def _event(payout, *, actor, reason, previous=None, evidence=None, ledger_id=None):
    previous = previous or payout.status
    if evidence:
        payout.state_version += 1
        payout.save(update_fields=["state_version"])
        event = PayoutEvent.objects.create(
            payout=payout,
            sequence=payout.state_version,
            previous_state=previous,
            new_state=payout.status,
            reason_code=reason,
            actor=actor,
            evidence=evidence,
            ledger_transaction_id=ledger_id,
        )
    else:
        event = append_event_locked(
            payout,
            previous=previous,
            reason=reason,
            actor=actor,
            ledger_transaction_id=ledger_id,
        )
    record_admin_action(
        actor=actor,
        action=f"payout.{reason}",
        target=payout,
        after={"event": str(event.event_uuid)},
    )
    return event


def _attempt(payout, actor, sequence):
    attempt = payout.attempts.select_for_update(no_key=True).get(
        sequence=sequence, rail="manual"
    )
    if attempt.operator_id != actor.pk:
        raise PermissionDenied(
            "Only the claiming operator may execute this instruction."
        )
    if attempt.request_fingerprint != _identity(payout):
        raise ValidationError("Instruction identity changed.")
    return attempt


@transaction.atomic
def prepare(*, actor, payout_id, expected_state_version):
    authorize(actor)
    payout, balance, sources = _lock_payout_aggregate(payout_id)
    _gate(payout, balance)
    if payout.state_version != expected_state_version or payout.status != "eligible":
        raise ValidationError("Instruction revision conflict.")
    require_uncommitted(payout)
    if payout.attempts.filter(status="prepared").exists():
        raise ValidationError("An operator already owns this instruction.")
    attempt = PayoutAttempt.objects.create(
        payout=payout,
        sequence=payout.attempts.count() + 1,
        instruction_version=payout.active_instruction_version,
        amount_revision=payout.amount_revisions.order_by("-revision").first(),
        amount_eur_cents=payout.amount_eur_cents,
        currency="DZD",
        rail="manual",
        provider_mode=payout.provider_mode,
        operator=actor,
        idempotency_key=f"manual:{payout.public_reference}:{payout.state_version}",
        request_fingerprint=_identity(payout),
    )
    needed = payout.amount_eur_cents
    credited = balance.credited_eur_cents
    for source in sources:
        if (
            source.status != "succeeded"
            or not source.succeeded_at
            or source.is_unapplied
            or source.provider_mode != payout.provider_mode
            or source.provider not in ("stripe", "chargily")
        ):
            continue
        available = source_available_cents(source)
        if source.order_id == balance.credit_source_id:
            available = min(available, credited)
        take = min(available, needed)
        if take <= 0:
            continue
        PayoutFundingAllocation.objects.create(
            payout=payout,
            attempt=attempt,
            source_attempt=source,
            allocation_key=f"manual:{attempt.pk}:{source.pk}",
            source_charge_id=source.provider_charge_id,
            provider=source.provider,
            provider_mode=source.provider_mode,
            purpose=source.order.purpose,
            currency=source.payment_currency,
            amount_eur_cents=take,
        )
        needed -= take
        if source.order_id == balance.credit_source_id:
            credited -= take
    if needed:
        raise ValidationError("Available funding does not cover this instruction.")
    if active_holds(payout).exists():
        raise ValidationError("A funding source hold prevents preparation.")
    payout.status = "scheduled"
    payout.scheduled_for = timezone.now()
    payout.save(update_fields=["status", "scheduled_for"])
    _event(
        payout, actor=actor, reason="manual_instruction_created", previous="eligible"
    )
    return payout


@transaction.atomic
def begin(*, actor, payout_id, sequence):
    authorize(actor)
    payout, balance, _ = _lock_payout_aggregate(payout_id)
    _gate(payout, balance)
    attempt = _attempt(payout, actor, sequence)
    if attempt.status != "prepared" or payout.status != "scheduled":
        raise ValidationError("Instruction is not prepared.")
    attempt.status, attempt.committed_at = "dispatch_committed", timezone.now()
    attempt.save(update_fields=["status", "committed_at"])
    payout.status = "processing"
    payout.save(update_fields=["status"])
    _event(
        payout, actor=actor, reason="manual_instruction_committed", previous="scheduled"
    )
    notify_payout_state(payout, "processing")
    return payout


@transaction.atomic
def release(*, actor, payout_id, sequence):
    authorize(actor)
    payout, _, _ = _lock_payout_aggregate(payout_id)
    attempt = _attempt(payout, actor, sequence)
    if attempt.status != "prepared" or attempt.committed_at:
        raise ValidationError("Committed instructions require recovery review.")
    from .models import PayoutFundingRelease

    for allocation in payout.funding_allocations.filter(
        attempt=attempt, release__isnull=True
    ):
        PayoutFundingRelease.objects.create(
            allocation=allocation,
            reason_code="manual_preparation_released",
            actor=actor,
        )
    attempt.status = "cancelled"
    attempt.save(update_fields=["status"])
    previous = payout.status
    if payout.status == "scheduled":
        payout.status = "eligible"
        payout.save(update_fields=["status"])
    _event(payout, actor=actor, reason="manual_preparation_released", previous=previous)
    return payout


@transaction.atomic
def confirm(
    *, actor, payout_id, sequence, evidence_reference, settled=False, confirmed=False
):
    authorize(actor)
    if confirmed is not True or type(settled) is not bool:
        raise ValidationError("Explicit exact-transfer attestation is required.")
    payout, balance, _ = _lock_payout_aggregate(payout_id)
    attempt = _attempt(payout, actor, sequence)
    if payout.status == "paid" and attempt.status == "succeeded":
        if (
            not settled
            or not attempt.manual_receipts.filter(
                evidence__public_reference=evidence_reference, completed_attested=True
            ).exists()
        ):
            raise ValidationError("Settlement replay conflicts with recorded evidence.")
        return payout
    _gate(payout, balance)
    if attempt.status not in ("dispatch_committed", "sent") or not attempt.committed_at:
        raise ValidationError("Transfer has not been committed.")
    evidence = PayoutEvidence.objects.select_for_update(no_key=True).get(
        public_reference=evidence_reference,
        owner=actor,
        purpose="transfer_receipt",
        upload_state="complete",
    )
    if PayoutEvent.objects.filter(evidence=evidence).exclude(payout=payout).exists():
        raise ValidationError("Receipt belongs to another payout.")
    if not evidence.digest or not evidence.object_key:
        raise ValidationError("Stored transfer receipt is required.")
    from .models import ManualPayoutReceipt

    receipt = ManualPayoutReceipt.objects.filter(evidence=evidence).first()
    if receipt:
        if receipt.attempt_id != attempt.pk or receipt.completed_attested != settled:
            raise ValidationError(
                "Upload new evidence for a changed settlement attestation."
            )
        return payout
    ManualPayoutReceipt.objects.create(
        attempt=attempt,
        evidence=evidence,
        revision=attempt.manual_receipts.count() + 1,
        operator=actor,
        completed_attested=settled,
    )
    previous = payout.status
    payout.sent_at = payout.sent_at or timezone.now()
    payout.status = "sent"
    payout.save(update_fields=["status", "sent_at"])
    attempt.status = "sent"
    attempt.save(update_fields=["status"])
    _event(
        payout,
        actor=actor,
        reason="manual_transfer_sent",
        previous=previous,
        evidence=evidence,
    )
    if settled:
        from .ledger import record_payout

        payout.status, payout.paid_at = "paid", timezone.now()
        payout.reference = f"manual:{attempt.pk}:{evidence.public_reference}"
        payout.admin_actor = actor
        payout.save(update_fields=["status", "paid_at", "reference", "admin_actor"])
        attempt.status, attempt.result_at = "succeeded", payout.paid_at
        attempt.save(update_fields=["status", "result_at"])
        posting = record_payout(
            payout_id=payout.pk,
            deal_id=payout.deal_id,
            traveler_id=payout.traveler_id,
            amount_eur_cents=attempt.amount_eur_cents,
        )
        _event(
            payout,
            actor=actor,
            reason="manual_transfer_settled",
            previous="sent",
            evidence=evidence,
            ledger_id=posting.transaction_id,
        )
    notify_payout_state(payout, "paid" if settled else "sent")
    return payout
