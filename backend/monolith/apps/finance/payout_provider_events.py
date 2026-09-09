"""Provider events that bear on whether a Traveler may be paid.

Three families, on two endpoints, all of them read the same way: an event means
*something changed*, never *this is now true*. Every handler here re-reads the
authoritative object from Stripe in the correct account scope before it changes
anything, because a webhook can arrive late, out of order, twice, or — for the
`funds_withdrawn` family — describe a fact that a later event already reversed.

**Platform scope** (`/api/payments/webhooks/stripe`)
    `transfer.*` reconciles ShipTrip's own outgoing money. `refund.*` and
    `charge.dispute.*` are the two ways a Sender's payment can be taken back
    after the fact, which is exactly the money a payout was about to be built
    on. `balance.available` wakes work that was waiting for liquidity.

**Connected scope** (`/api/payments/webhooks/stripe-connect`)
    `payout.*` is the Traveler's bank payout, and it is the only source of the
    word `paid`. Connected `balance.available` wakes a bank payout that was
    waiting for a Transfer's funds to settle.

Nothing here decides an amount, and nothing here pays anybody. A dispute or an
unexplained refund opens a `FinanceHold`; the hold is what stops the next
external instruction, and clearing one hold never clears another.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import (
    FinanceHold,
    PaymentAttempt,
    PaymentProviderEvent,
    PaymentRefund,
    Payout,
    ProviderDispute,
    PayoutProviderOperation,
    ScheduledJob,
    StripeDisbursement,
    StripePayoutAccount,
)
from .payout_accounts import expected_mode
from .providers.base import ProviderError, ProviderUnavailable
from .providers.stripe_connect import get_connect_gateway

logger = logging.getLogger(__name__)

#: Exactly the platform-scope additions H0 listed. No wildcard, and every entry
#: has a handler below.
PLATFORM_PAYOUT_EVENTS = frozenset(
    {
        "transfer.created",
        "transfer.reversed",
        "balance.available",
        "refund.created",
        "refund.updated",
        "refund.failed",
        "charge.dispute.created",
        "charge.dispute.updated",
        "charge.dispute.closed",
        "charge.dispute.funds_withdrawn",
        "charge.dispute.funds_reinstated",
    }
)

#: Connected-scope additions. `payout.canceled` is spelled with one `l`, which
#: is Stripe's spelling and not a typo to be helpfully corrected.
CONNECT_PAYOUT_EVENTS = frozenset(
    {
        "payout.created",
        "payout.updated",
        "payout.paid",
        "payout.failed",
        "payout.canceled",
    }
)

#: Dispute statuses that mean the money is not coming back to the platform, so
#: the hold must stand.
DISPUTE_OPEN_STATUSES = frozenset(
    {
        "warning_needs_response",
        "warning_under_review",
        "needs_response",
        "under_review",
        "lost",
    }
)


def _event_object(payload: dict) -> dict:
    data = payload.get("data") if isinstance(payload, dict) else None
    obj = data.get("object") if isinstance(data, dict) else None
    return obj if isinstance(obj, dict) else {}


def _mode_of(payload: dict) -> str:
    livemode = payload.get("livemode")
    return ("live" if livemode else "test") if type(livemode) is bool else "legacy_unknown"


def _wake(kind: str, key: str, payload: dict, *, delay_seconds: int = 0) -> None:
    """Arm a durable job. Redis is an accelerator; this table is the promise."""

    from .services import schedule_job

    schedule_job(
        kind=kind,
        key=key,
        run_at=timezone.now() + timedelta(seconds=delay_seconds),
        payload=payload,
        max_attempts=32,
        reactivate_failed=True,
    )


# ---------------------------------------------------------------------------
# Platform scope
# ---------------------------------------------------------------------------


def handle_platform_event(record: PaymentProviderEvent) -> str:
    """Apply one platform payout-domain event. Returns a safe machine note."""

    payload = dict(record.payload or {})
    event_type = record.event_type
    if _mode_of(payload) not in (expected_mode(), "legacy_unknown"):
        return "mode_isolated"
    if event_type in ("transfer.created", "transfer.reversed"):
        return _handle_transfer_event(payload)
    if event_type == "balance.available":
        _wake("payout_sweep", "payout_sweep:balance_available", {"scope": "platform"})
        return "platform_balance_available"
    if event_type.startswith("refund."):
        return _handle_refund_event(payload, event_type)
    if event_type.startswith("charge.dispute."):
        return _handle_dispute_event(payload, event_type)
    return "event_not_subscribed"


def _handle_transfer_event(payload: dict) -> str:
    from .payout_reconciliation import apply_transfer_observation

    obj = _event_object(payload)
    transfer_id = str(obj.get("id") or "")
    if not transfer_id.startswith("tr_"):
        return "transfer_id_missing"
    operation = (
        PayoutProviderOperation.objects.select_related(
            "attempt__payout", "funding_allocation"
        )
        .filter(
            kind="transfer_create",
            provider_object_id=transfer_id,
            provider_mode=expected_mode(),
        )
        .first()
    )
    if operation is None:
        # A Transfer this platform did not create through the payout domain.
        # Recorded and classified; nothing outside this server may introduce an
        # external money movement into a Deal.
        logger.warning("finance.unknown_transfer_event transfer=%s", transfer_id)
        return "unknown_transfer"
    try:
        snapshot = get_connect_gateway().retrieve_transfer(transfer_id)
    except (ProviderUnavailable, ProviderError) as exc:
        _wake(
            "payout_reconcile",
            f"payout_reconcile:{operation.attempt.payout_id}",
            {"payout_id": operation.attempt.payout_id},
            delay_seconds=60,
        )
        return f"transfer_retrieve_failed:{exc.code}"[:64]
    return apply_transfer_observation(operation, snapshot)


def _source_attempt_for(charge_id: str, payment_intent_id: str):
    queryset = PaymentAttempt.objects.select_related("order")
    if charge_id:
        found = queryset.filter(provider="stripe", provider_charge_id=charge_id).first()
        if found is not None:
            return found
    if payment_intent_id:
        return queryset.filter(
            provider="stripe", provider_payment_id=payment_intent_id
        ).first()
    return None


def _open_source_hold(attempt, *, kind: str, reason: str, reference: str, amount=None):
    """Hold the money this charge supports, at the widest correct scope.

    A Deal-scoped hold is preferred where one exists, because `active_holds`
    reaches a payout through its Deal whatever combination of balance, deposit
    and Boost captures ends up funding it. Falling back to the capture itself
    keeps an unbound deposit or Boost payment covered too.
    """

    if attempt is None:
        return None
    deal_id = attempt.order.deal_id
    lookup = {"kind": kind, "reason_code": reason[:64], "cleared_at": None}
    if deal_id:
        lookup["deal_id"] = deal_id
    else:
        lookup["source_attempt"] = attempt
    hold, created = FinanceHold.objects.get_or_create(
        **lookup,
        defaults={
            "source_reference": reference[:160],
            "amount_exposure_eur_cents": amount,
        },
    )
    if created:
        logger.warning(
            "finance.provider_hold_opened kind=%s reason=%s reference=%s",
            kind,
            reason,
            reference,
        )
    return hold


def _handle_refund_event(payload: dict, event_type: str) -> str:
    obj = _event_object(payload)
    refund_id = str(obj.get("id") or "")
    if not refund_id:
        return "refund_id_missing"
    known = PaymentRefund.objects.filter(
        provider="stripe", provider_refund_id=refund_id
    ).first()
    if known is not None:
        # ShipTrip's own refund. Its lifecycle is already owned by the refund
        # reconciler; nothing here duplicates that, and nothing here creates a
        # second refund for the same money.
        return "known_refund"
    try:
        detail = get_connect_gateway().retrieve_refund(refund_id)
    except (ProviderUnavailable, ProviderError) as exc:
        return f"refund_retrieve_failed:{exc.code}"[:64]
    attempt = _source_attempt_for(
        str(detail.get("charge") or ""), str(detail.get("payment_intent") or "")
    )
    if attempt is None:
        return "unknown_refund_source"
    if str(detail.get("status") or "") in ("failed", "canceled"):
        return "external_refund_not_settled"
    _open_source_hold(
        attempt,
        kind="refund",
        reason="external_provider_refund",
        reference=f"stripe_refund:{refund_id}",
        amount=int(detail.get("amount") or 0),
    )
    return "external_refund_held"


def _handle_dispute_event(payload: dict, event_type: str) -> str:
    obj = _event_object(payload)
    dispute_id = str(obj.get("id") or "")
    if not dispute_id:
        return "dispute_id_missing"
    try:
        detail = get_connect_gateway().retrieve_dispute(dispute_id)
    except (ProviderUnavailable, ProviderError) as exc:
        return f"dispute_retrieve_failed:{exc.code}"[:64]
    charge_id = str(detail.get("charge") or "")
    attempt = _source_attempt_for(charge_id, str(detail.get("payment_intent") or ""))
    status = str(detail.get("status") or "")
    with transaction.atomic():
        dispute, _ = ProviderDispute.objects.get_or_create(
            provider="stripe",
            platform_id=str(
                getattr(settings, "STRIPE_CONNECT_PLATFORM_ACCOUNT_ID", "") or ""
            ),
            provider_mode=expected_mode(),
            provider_object_id=dispute_id,
            defaults={
                "source_attempt": attempt,
                "source_charge_id": charge_id[:255],
                "amount_minor": int(detail.get("amount") or 0),
                "currency": str(detail.get("currency") or "EUR")[:3],
                "status": status[:32],
            },
        )
        updates = {"status": status[:32]}
        if event_type == "charge.dispute.funds_withdrawn":
            updates["funds_withdrawn_reference"] = dispute_id[:255]
        if event_type == "charge.dispute.funds_reinstated":
            updates["funds_reinstated_reference"] = dispute_id[:255]
        if attempt is not None and dispute.source_attempt_id is None:
            updates["source_attempt"] = attempt
            updates["source_charge_id"] = charge_id[:255]
        ProviderDispute.objects.filter(pk=dispute.pk).update(**updates)

    if status in DISPUTE_OPEN_STATUSES or event_type in (
        "charge.dispute.created",
        "charge.dispute.funds_withdrawn",
    ):
        _open_source_hold(
            attempt,
            kind="provider_dispute",
            reason="charge_dispute_open",
            reference=f"stripe_dispute:{dispute_id}",
            amount=int(detail.get("amount") or 0),
        )
        return "provider_dispute_held"
    if event_type == "charge.dispute.closed" and status == "won":
        # Only this dispute's own hold clears, and only on a won outcome.
        # Another hold on the same money — a refund, a ShipTrip dispute, a
        # compliance review — is untouched.
        cleared = FinanceHold.objects.filter(
            kind="provider_dispute",
            source_reference=f"stripe_dispute:{dispute_id}",
            cleared_at__isnull=True,
        ).update(cleared_at=timezone.now())
        return f"provider_dispute_cleared:{cleared}"
    return f"provider_dispute_{status or 'observed'}"[:64]


# ---------------------------------------------------------------------------
# Connected scope
# ---------------------------------------------------------------------------


def handle_connect_payout_event(payload: dict, account_id: str) -> str:
    """Reconcile one connected-account bank payout from its own scope."""

    from .payout_reconciliation import apply_bank_payout_observation

    obj = _event_object(payload)
    provider_payout_id = str(obj.get("id") or "")
    if not provider_payout_id.startswith("po_"):
        return "payout_id_missing"
    account = StripePayoutAccount.objects.filter(
        provider_account_id=account_id,
        provider_mode=expected_mode(),
        platform_id=str(
            getattr(settings, "STRIPE_CONNECT_PLATFORM_ACCOUNT_ID", "") or ""
        ),
    ).first()
    if account is None:
        return "unknown_connected_account"
    disbursement = StripeDisbursement.objects.filter(
        account=account, provider_payout_id=provider_payout_id
    ).first()
    try:
        snapshot = get_connect_gateway().retrieve_bank_payout(
            account_id=account_id, payout_id=provider_payout_id
        )
    except (ProviderUnavailable, ProviderError) as exc:
        return f"payout_retrieve_failed:{exc.code}"[:64]
    if disbursement is None:
        if snapshot.automatic:
            # Stripe's own schedule created this. The account is supposed to be
            # on `manual`, so something changed the schedule underneath the
            # application's accounting.
            reason = "unexpected_automatic_payout"
        else:
            reason = "unexpected_dashboard_payout"
        FinanceHold.objects.get_or_create(
            account=account,
            kind="compliance",
            reason_code=reason,
            cleared_at=None,
            defaults={
                "source_reference": f"stripe_payout:{provider_payout_id}"[:160],
                "amount_exposure_eur_cents": int(snapshot.amount_minor),
            },
        )
        logger.error(
            "finance.unexpected_connected_payout account=%s reason=%s",
            account.provider_account_id,
            reason,
        )
        _wake(
            "payout_account_refresh",
            f"payout_account_refresh:{account.pk}",
            {"account_id": account.pk},
        )
        return reason
    return apply_bank_payout_observation(disbursement, snapshot)


def handle_connect_balance_available(account_id: str) -> str:
    """Transferred funds settled. Wake every bank payout waiting on them."""

    account = StripePayoutAccount.objects.filter(
        provider_account_id=account_id, provider_mode=expected_mode()
    ).first()
    if account is None:
        return "unknown_connected_account"
    payout_ids = list(
        Payout.objects.filter(
            active_instruction_version__stripe_account=account,
            status__in=["processing", "sent", "scheduled", "eligible", "failed"],
        )
        .order_by("pk")
        .values_list("pk", flat=True)[:50]
    )
    for payout_id in payout_ids:
        _wake("payout_execute", f"payout_execute:{payout_id}", {"payout_id": payout_id})
    return f"connected_balance_available:{len(payout_ids)}"


def scheduled_job_kinds() -> tuple:
    """The four H3 job kinds, named once so the sweeper and tests agree."""

    return (
        ScheduledJob.Kind.PAYOUT_EXECUTE,
        ScheduledJob.Kind.PAYOUT_RECONCILE,
        ScheduledJob.Kind.PAYOUT_ACCOUNT_REFRESH,
        ScheduledJob.Kind.PAYOUT_SWEEP,
    )
