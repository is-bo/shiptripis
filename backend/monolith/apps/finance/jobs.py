"""Durable financial job handlers and the claim/run loop.

The scheduling contract is: the `ScheduledJob` row is the obligation. Redis may
make delivery prompt, but nothing here reads Redis, and a job that exists in
this table will run even if every cache and queue in the system is wiped.

Claiming uses `SELECT ... FOR UPDATE SKIP LOCKED` where the database supports
it, so several workers can share the queue without running the same job twice.
On SQLite (tests, local) the loop degrades to a plain locked read, which is
correct because there is only one writer.

Handlers must be idempotent in their own right. The lock stops concurrent runs;
idempotency is what makes a *retried* run safe, and every handler here is
written so a second execution is a no-op rather than a second refund.
"""

from __future__ import annotations

import logging
import os
import socket
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db import connection, transaction
from django.utils import timezone

from apps.deals.models import Deal
from apps.parcels.models import ParcelRequest

from .models import (
    PaymentAttempt,
    PaymentOrder,
    PaymentProviderEvent,
    PaymentRefund,
    Payout,
    ScheduledJob,
)

logger = logging.getLogger(__name__)


class JobFailed(RuntimeError):
    """A handler could not complete; the job is retried with backoff."""


@dataclass(frozen=True, slots=True)
class JobRunReport:
    claimed: int
    succeeded: int
    failed: int
    results: list[str]


def worker_identity() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"[:64]


# --- handlers ----------------------------------------------------------------


def handle_deposit_expiry_refund(payload: dict) -> str:
    """Refund a posting deposit when the request expired unmatched.

    Idempotent at three levels: the request is only expired once, the refund
    carries a stable idempotency key, and `request_refund` returns the existing
    row rather than raising when that key already exists. Running this handler
    ten times refunds once.
    """

    from .services import refund_order_in_full

    request_id = payload.get("delivery_request_id")
    if not isinstance(request_id, int):
        raise JobFailed("deposit_expiry_refund needs an integer delivery_request_id.")

    with transaction.atomic():
        request_row = (
            ParcelRequest.objects.select_for_update().filter(pk=request_id).first()
        )
        if request_row is None:
            return "request_missing"
        if request_row.status in (
            ParcelRequest.Status.MATCHED,
            ParcelRequest.Status.IN_TRANSIT,
            ParcelRequest.Status.DELIVERED,
            ParcelRequest.Status.COMPLETED,
        ):
            # It found a traveler. The deposit is credited into the deal
            # balance, not refunded.
            return "request_matched"
        if (
            request_row.deadline_at is not None
            and request_row.deadline_at > timezone.now()
        ):
            raise JobFailed("The request has not reached its deadline yet.")
        if request_row.status == ParcelRequest.Status.OPEN:
            request_row.status = ParcelRequest.Status.EXPIRED
            request_row.save(update_fields=["status", "updated_at"])

        order = (
            PaymentOrder.objects.select_for_update()
            .filter(
                delivery_request_id=request_id,
                purpose=PaymentOrder.Purpose.POSTING_DEPOSIT,
            )
            .exclude(status=PaymentOrder.Status.CANCELLED)
            .first()
        )
        if order is None:
            return "no_deposit_order"
        # `credited_into` is the reverse side of a self-referential one-to-one,
        # so it has no `_id` attribute; ask the queryset instead of the instance.
        if PaymentOrder.objects.filter(credit_source_id=order.pk).exists():
            return "deposit_already_credited"
        order_id = order.pk
        if int(order.paid_eur_cents) <= 0:
            from .services import cancel_order

            cancel_order(order_id=order_id, reason="deposit_expired_unpaid")
            return "deposit_unpaid_cancelled"

    refunds = refund_order_in_full(
        order_id=order_id,
        reason=PaymentRefund.Reason.DEPOSIT_EXPIRY,
    )
    return f"refunds_raised={len(refunds)}"


def handle_payment_grace_release(payload: dict) -> str:
    """Release a reservation whose payment grace lapsed.

    The database-backed sweep in `apps.deals.services` is the primary path; this
    job is the per-deal companion that arms at acceptance, so the obligation is
    recorded even if the sweep daemon is not running.
    """

    from apps.deals.services import release_pending_deal_reservation

    deal_id = payload.get("deal_id")
    if not isinstance(deal_id, int):
        raise JobFailed("payment_grace_release needs an integer deal_id.")
    if not Deal.objects.filter(pk=deal_id).exists():
        return "deal_missing"
    result = release_pending_deal_reservation(
        deal_id=deal_id,
        reason="payment_grace_expired",
        require_expired=True,
    )
    return "released" if result.changed else "no_op"


def handle_attempt_expiry(payload: dict) -> str:
    """Close a hosted checkout the customer never completed."""

    from .services import reconcile_attempt

    attempt_id = payload.get("attempt_id")
    if not isinstance(attempt_id, int):
        raise JobFailed("attempt_expiry needs an integer attempt_id.")
    attempt = PaymentAttempt.objects.filter(pk=attempt_id).first()
    if attempt is None:
        return "attempt_missing"
    if attempt.status not in PaymentAttempt.OPEN_STATUSES:
        return "attempt_already_terminal"
    if attempt.expires_at is not None and attempt.expires_at > timezone.now():
        raise JobFailed("The attempt has not expired yet.")
    return reconcile_attempt(attempt_id=attempt_id, outcome="expired")


def handle_provider_reconcile(payload: dict) -> str:
    """Ask the provider what really happened, for a webhook that never came.

    Providers do not guarantee delivery, so an integration that only listens
    will eventually strand a paid order. This polls the provider's own API and
    feeds the answer through the same reconciliation path a webhook uses.
    """

    from .providers import ProviderError, get_gateway
    from .services import reconcile_attempt, recover_checkout_attempt

    attempt_id = payload.get("attempt_id")
    if not isinstance(attempt_id, int):
        raise JobFailed("provider_reconcile needs an integer attempt_id.")
    attempt = PaymentAttempt.objects.filter(pk=attempt_id).first()
    if attempt is None:
        return "attempt_missing"
    if attempt.status == PaymentAttempt.Status.SUCCEEDED:
        return "already_succeeded"
    if not attempt.provider_session_id:
        if attempt.provider in {"mock", "stripe"}:
            try:
                recover_checkout_attempt(attempt_id=attempt.pk)
            except ProviderError as exc:
                raise JobFailed(f"checkout handle recovery failed: {exc.code}") from exc
            attempt.refresh_from_db()
        if not attempt.provider_session_id:
            # Chargily does not expose a documented idempotent checkout-create
            # contract. Re-creating blindly could charge twice, so keep this
            # visible for operator reconciliation instead.
            raise JobFailed("provider session is unknown; operator review required")
    try:
        gateway = get_gateway(attempt.provider)
        snapshot = gateway.fetch_attempt(
            provider_session_id=attempt.provider_session_id,
            provider_payment_id=attempt.provider_payment_id,
        )
    except ProviderError as exc:
        raise JobFailed(f"provider reconciliation failed: {exc.code}") from exc
    if snapshot.outcome == "ignored":
        raise JobFailed("provider still reports the attempt as pending")
    result = reconcile_attempt(
        attempt_id=attempt_id,
        outcome=snapshot.outcome,
        provider_payment_id=snapshot.provider_payment_id,
        provider_amount_minor=snapshot.amount_minor,
        provider_currency=snapshot.currency,
    )
    if snapshot.outcome == "processing":
        raise JobFailed("provider reports processing; poll again")
    return result


def handle_provider_event_process(payload: dict) -> str:
    """Re-drive a received provider event until its economic effect commits."""

    from .services import _mark_event_retryable, process_provider_event

    event_id = payload.get("event_id")
    if not isinstance(event_id, int):
        raise JobFailed("provider_event_process needs an integer event_id.")
    if not PaymentProviderEvent.objects.filter(pk=event_id).exists():
        return "event_missing"
    try:
        return process_provider_event(event_id=event_id)
    except Exception as exc:
        _mark_event_retryable(event_id, exc)
        raise JobFailed(
            f"provider event application failed: {type(exc).__name__}"
        ) from exc


def handle_refund_reconcile(payload: dict) -> str:
    """Drive or poll a non-terminal refund using its stable provider key."""

    from .services import _settle_refund_with_provider

    refund_id = payload.get("refund_id")
    if not isinstance(refund_id, int):
        raise JobFailed("refund_reconcile needs an integer refund_id.")
    refund = PaymentRefund.objects.filter(pk=refund_id).first()
    if refund is None:
        return "refund_missing"
    if refund.status == PaymentRefund.Status.SUCCEEDED:
        return "already_succeeded"
    result = _settle_refund_with_provider(refund_id=refund_id)
    if result in {
        "provider_unavailable",
        "provider_pending",
        "manual_action_required",
    }:
        raise JobFailed(f"refund remains unresolved: {result}")
    return result


def handle_payout_release_check(payload: dict) -> str:
    """Re-evaluate one payout against the Phase 4 release gate.

    Armed at funding, when nobody yet knows when delivery will be confirmed, so
    it is the safety net rather than the primary trigger: `protection_expiry`
    is scheduled the moment the protection deadline exists and is what normally
    releases the money. This one exists so a Deal whose protection job was
    somehow lost still gets looked at.
    """

    from .payout_release import evaluate_payout_release

    payout_id = payload.get("payout_id")
    if not isinstance(payout_id, int):
        raise JobFailed("payout_release_check needs an integer payout_id.")
    payout = Payout.objects.filter(pk=payout_id).first()
    if payout is None:
        return "payout_missing"
    if payout.status not in Payout.PRE_RELEASE_STATUSES:
        return f"payout_{payout.status}"
    result = evaluate_payout_release(
        deal_id=payout.deal_id, reason="payout_release_check"
    )
    if result in {
        "delivery_not_confirmed",
        "protection_not_armed",
        "protection_open",
    }:
        # Armed at funding, when nobody knows when delivery will happen, this
        # job's first fire lands 48 hours later -- usually while the parcel is
        # still moving. Returning a string would mark the obligation
        # discharged and retire the safety net before it could ever help, which
        # is the whole reason it exists. Retry instead, like every other
        # early-fire handler here.
        raise JobFailed(f"payout is not releasable yet: {result}")
    return result


# --- Phase 4 lifecycle handlers ----------------------------------------------


def handle_delivery_code_release(payload: dict) -> str:
    """Release the delivery code exactly once, 30 minutes after pickup.

    This is the whole reason the job is a row rather than a timer: stop the
    worker, let the window pass, start it again, and the code becomes available
    and the recipient is emailed once - not zero times, not twice. The handler
    itself refuses to run early, so a job whose run_at was somehow moved
    forward cannot shorten the safety buffer.
    """

    from apps.handover.services import HandoverError, release_delivery_code

    deal_id = payload.get("deal_id")
    if not isinstance(deal_id, int):
        raise JobFailed("delivery_code_release needs an integer deal_id.")
    if not Deal.objects.filter(pk=deal_id).exists():
        return "deal_missing"
    from apps.deals.lifecycle import DealLifecycleError

    try:
        return release_delivery_code(deal_id=deal_id)
    except DealLifecycleError as exc:
        # The Deal moved out from under the release -- disputed, cancelled or
        # settled. The transaction already rolled back, so nothing was
        # promoted and no email was armed. Retrying cannot change the answer,
        # so record it rather than exhausting the retry budget and raising an
        # ERROR alert for correct behaviour.
        return f"refused_{exc.code}"
    except HandoverError as exc:
        # `delivery_code_buffer_open` means this fired early. Retrying with
        # backoff is exactly right; the state check is the authority, not the
        # schedule.
        raise JobFailed(f"delivery code release refused: {exc.code}") from exc


def handle_protection_expiry(payload: dict) -> str:
    """Close the 48-hour protection window and decide the payout."""

    from .payout_release import evaluate_payout_release

    deal_id = payload.get("deal_id")
    if not isinstance(deal_id, int):
        raise JobFailed("protection_expiry needs an integer deal_id.")
    if not Deal.objects.filter(pk=deal_id).exists():
        return "deal_missing"
    result = evaluate_payout_release(
        deal_id=deal_id, reason="protection_window_expired"
    )
    if result == "protection_open":
        # Fired early. Retry rather than record a decision that has not been
        # earned yet.
        raise JobFailed("the protection window has not closed yet")
    return result


def handle_rating_reveal(payload: dict) -> str:
    """Reveal both sides once the blind review window closes."""

    from apps.ratings.services import reveal_ratings_for_deal

    deal_id = payload.get("deal_id")
    if not isinstance(deal_id, int):
        raise JobFailed("rating_reveal needs an integer deal_id.")
    if not Deal.objects.filter(pk=deal_id).exists():
        return "deal_missing"
    result = reveal_ratings_for_deal(deal_id=deal_id)
    if result == "not_due":
        # Fired early. `revealed_at` is only an audit stamp -- visibility is
        # recomputed from the window frozen on each rating -- but retiring the
        # obligation would mean the stamp is never written at all.
        raise JobFailed("the review window has not closed yet")
    return result


def handle_boost_expiry(payload: dict) -> str:
    """Retire a boost whose paid window has ended, keeping its history."""

    from apps.boosts.services import expire_boost

    purchase_id = payload.get("boost_purchase_id")
    if not isinstance(purchase_id, int):
        raise JobFailed("boost_expiry needs an integer boost_purchase_id.")
    result = expire_boost(purchase_id=purchase_id)
    if result == "not_due":
        # Fired early. Recording that as success would mark the obligation
        # discharged without doing it, leaving the purchase `active` forever.
        # Ranking would still end on time -- the hook compares against
        # `expires_at` -- but the row and the derived columns would go stale,
        # and a stale row is what an operator or a dispute later reads.
        raise JobFailed("the boost window has not closed yet")
    return result


def handle_outbound_message(payload: dict) -> str:
    """Carry one durable transactional message to the email transport."""

    from apps.notifications.outbox import dispatch_message

    message_id = payload.get("message_id")
    if not isinstance(message_id, int):
        raise JobFailed("outbound_message needs an integer message_id.")
    try:
        result = dispatch_message(message_id=message_id)
    except Exception as exc:  # noqa: BLE001 - transport failures are retryable
        raise JobFailed(
            f"outbound message dispatch failed: {type(exc).__name__}"
        ) from exc
    if result == "disabled":
        # Do not discharge the durable job while the operator kill switch is
        # active. The message row stays pending and the normal retry/sweep path
        # can carry it after an approved activation.
        raise JobFailed("transactional email is disabled")
    return result


HANDLERS = {
    ScheduledJob.Kind.DEPOSIT_EXPIRY_REFUND: handle_deposit_expiry_refund,
    ScheduledJob.Kind.PAYMENT_GRACE_RELEASE: handle_payment_grace_release,
    ScheduledJob.Kind.ATTEMPT_EXPIRY: handle_attempt_expiry,
    ScheduledJob.Kind.PROVIDER_RECONCILE: handle_provider_reconcile,
    ScheduledJob.Kind.PROVIDER_EVENT_PROCESS: handle_provider_event_process,
    ScheduledJob.Kind.REFUND_RECONCILE: handle_refund_reconcile,
    ScheduledJob.Kind.PAYOUT_RELEASE_CHECK: handle_payout_release_check,
    ScheduledJob.Kind.DELIVERY_CODE_RELEASE: handle_delivery_code_release,
    ScheduledJob.Kind.PROTECTION_EXPIRY: handle_protection_expiry,
    ScheduledJob.Kind.RATING_REVEAL: handle_rating_reveal,
    ScheduledJob.Kind.BOOST_EXPIRY: handle_boost_expiry,
    ScheduledJob.Kind.OUTBOUND_MESSAGE: handle_outbound_message,
}


# --- claim / run -------------------------------------------------------------


def _retry_delay(attempts: int) -> timedelta:
    """Exponential backoff, capped so a stuck job still retries daily."""

    return timedelta(seconds=min(60 * (2 ** max(0, attempts - 1)), 6 * 3_600))


def claim_due_jobs(*, limit: int, at: datetime | None = None) -> list[ScheduledJob]:
    """Atomically take up to `limit` due jobs for this worker."""

    at = at or timezone.now()
    if limit <= 0 or limit > 500:
        raise ValueError("Job claim limit must be between 1 and 500.")
    identity = worker_identity()
    claimed: list[ScheduledJob] = []
    with transaction.atomic():
        queryset = ScheduledJob.objects.filter(
            status=ScheduledJob.Status.PENDING, run_at__lte=at
        ).order_by("run_at", "id")
        if connection.features.has_select_for_update_skip_locked:
            queryset = queryset.select_for_update(skip_locked=True)
        else:
            queryset = queryset.select_for_update()
        rows = list(queryset[:limit])
        if rows:
            ScheduledJob.objects.filter(pk__in=[row.pk for row in rows]).update(
                status=ScheduledJob.Status.RUNNING,
                locked_at=at,
                locked_by=identity,
                updated_at=at,
            )
            claimed = list(ScheduledJob.objects.filter(pk__in=[r.pk for r in rows]))
    return claimed


def run_job(job: ScheduledJob) -> str:
    """Execute one claimed job and record its outcome. Never raises."""

    handler = HANDLERS.get(job.kind)
    now = timezone.now()
    if handler is None:
        ScheduledJob.objects.filter(pk=job.pk).update(
            status=ScheduledJob.Status.FAILED,
            last_error=f"No handler for kind {job.kind!r}.",
            completed_at=now,
            updated_at=now,
        )
        logger.error("finance.job_no_handler job=%s kind=%s", job.pk, job.kind)
        return "no_handler"

    attempts = int(job.attempts) + 1
    try:
        result = handler(dict(job.payload or {}))
    except Exception as exc:  # noqa: BLE001 - a job must never kill the loop
        failed_permanently = attempts >= int(job.max_attempts)
        ScheduledJob.objects.filter(pk=job.pk).update(
            status=(
                ScheduledJob.Status.FAILED
                if failed_permanently
                else ScheduledJob.Status.PENDING
            ),
            attempts=attempts,
            last_error=f"{type(exc).__name__}: {exc}"[:500],
            run_at=now + _retry_delay(attempts),
            locked_at=None,
            locked_by="",
            completed_at=now if failed_permanently else None,
            updated_at=now,
        )
        if failed_permanently:
            # The retry budget is gone. This is now a human obligation, not a
            # scheduling one — log it at error level so it reaches alerting
            # rather than sitting in a queue nobody reads.
            logger.error(
                "finance.job_exhausted job=%s kind=%s key=%s attempts=%s error=%s",
                job.pk,
                job.kind,
                job.key,
                attempts,
                type(exc).__name__,
            )
        else:
            logger.warning(
                "finance.job_failed job=%s kind=%s attempts=%s error=%s",
                job.pk,
                job.kind,
                attempts,
                type(exc).__name__,
            )
        return "failed"

    ScheduledJob.objects.filter(pk=job.pk).update(
        status=ScheduledJob.Status.SUCCEEDED,
        attempts=attempts,
        last_result=str(result)[:255],
        last_error="",
        locked_at=None,
        locked_by="",
        completed_at=now,
        updated_at=now,
    )
    return str(result)


def run_due_jobs(*, limit: int = 50, at: datetime | None = None) -> JobRunReport:
    """Claim and run every due job, up to `limit`."""

    jobs = claim_due_jobs(limit=limit, at=at)
    results = [run_job(job) for job in jobs]
    failed = sum(1 for result in results if result in {"failed", "no_handler"})
    return JobRunReport(
        claimed=len(jobs),
        succeeded=len(results) - failed,
        failed=failed,
        results=results,
    )


def requeue_stuck_jobs(*, stale_after_seconds: int = 900) -> int:
    """Return jobs whose worker died mid-run to the pending queue."""

    cutoff = timezone.now() - timedelta(seconds=stale_after_seconds)
    return ScheduledJob.objects.filter(
        status=ScheduledJob.Status.RUNNING, locked_at__lt=cutoff
    ).update(
        status=ScheduledJob.Status.PENDING,
        locked_at=None,
        locked_by="",
        updated_at=timezone.now(),
    )
