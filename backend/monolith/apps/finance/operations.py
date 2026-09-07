"""Safe operational recovery controls for finance attempts and durable jobs.

These helpers change attention/queue state only.  They never declare money
paid, write the ledger, or call a provider.  Provider work is always delegated
to the existing idempotent ScheduledJob handlers after the transaction commits.
"""

from __future__ import annotations

from django.db import transaction
from django.db.models import Exists, OuterRef, Q, QuerySet
from django.utils import timezone

from apps.notifications.models import OutboundMessage

from .models import PaymentAttempt, PaymentRefund, ScheduledJob
from .services import schedule_job


class FinanceOperationsError(RuntimeError):
    code = "finance_operation_refused"

    def __init__(self, message: str, *, code: str | None = None):
        super().__init__(message)
        if code:
            self.code = code


# A normal provider-declared decline/failure moved no money and is historical,
# not an operator queue item.  These codes mean a success was reported but the
# amount/currency could not be safely accepted, so a person must investigate.
ATTENTION_FAILURE_CODES = frozenset(
    {"amount_unverifiable", "amount_mismatch", "currency_mismatch"}
)


def _reactivate_completed_job(job: ScheduledJob) -> ScheduledJob:
    """Re-arm a completed idempotent recovery job under its existing key."""

    if job.status not in {
        ScheduledJob.Status.SUCCEEDED,
        ScheduledJob.Status.CANCELLED,
    }:
        return job
    job = ScheduledJob.objects.select_for_update(no_key=True).get(pk=job.pk)
    if job.status not in {
        ScheduledJob.Status.SUCCEEDED,
        ScheduledJob.Status.CANCELLED,
    }:
        return job
    job.status = ScheduledJob.Status.PENDING
    job.run_at = timezone.now()
    job.attempts = 0
    job.locked_at = None
    job.locked_by = ""
    job.completed_at = None
    job.resolution = ""
    job.resolved_at = None
    job.resolved_by = None
    job.resolution_reason = ""
    job.save(
        update_fields=(
            "status",
            "run_at",
            "attempts",
            "locked_at",
            "locked_by",
            "completed_at",
            "resolution",
            "resolved_at",
            "resolved_by",
            "resolution_reason",
            "updated_at",
        )
    )
    return job


def payment_attention_queryset(
    queryset: QuerySet[PaymentAttempt] | None = None,
) -> QuerySet[PaymentAttempt]:
    """Return only payment attempts that need a finance decision now.

    An unapplied capture automatically leaves this queue once its full,
    purpose-bound refund succeeds.  The attempt and refund remain immutable
    financial history.  Explicitly resolved anomalies are likewise retained
    but hidden from the active queue.
    """

    queryset = queryset if queryset is not None else PaymentAttempt.objects.all()
    settled_refund = PaymentRefund.objects.filter(
        attempt_id=OuterRef("pk"),
        reason=PaymentRefund.Reason.UNAPPLIED_PAYMENT,
        status=PaymentRefund.Status.SUCCEEDED,
        amount_eur_cents=OuterRef("amount_eur_cents"),
    )
    return (
        queryset.annotate(has_settled_unapplied_refund=Exists(settled_refund))
        .filter(operational_resolution="")
        .filter(
            Q(is_unapplied=True, has_settled_unapplied_refund=False)
            | Q(
                status=PaymentAttempt.Status.FAILED,
                failure_code__in=ATTENTION_FAILURE_CODES,
            )
        )
    )


@transaction.atomic
def retry_failed_job(*, job_id: int) -> ScheduledJob:
    """Re-arm one terminal job while a worker may be active.

    Only FAILED rows can be retried.  A RUNNING row is owned by a worker and is
    deliberately never stolen by an admin request.
    """

    job = ScheduledJob.objects.select_for_update(no_key=True).get(pk=job_id)
    if job.status != ScheduledJob.Status.FAILED:
        raise FinanceOperationsError(
            "Only a terminal failed job can be retried.", code="job_not_failed"
        )
    if job.resolution:
        raise FinanceOperationsError(
            "A resolved job cannot be retried without reopening its review.",
            code="job_already_resolved",
        )
    job.status = ScheduledJob.Status.PENDING
    job.run_at = timezone.now()
    job.attempts = 0
    job.locked_at = None
    job.locked_by = ""
    job.completed_at = None
    job.resolution = ""
    job.resolved_at = None
    job.resolved_by = None
    job.resolution_reason = ""
    job.save(
        update_fields=(
            "status",
            "run_at",
            "attempts",
            "locked_at",
            "locked_by",
            "completed_at",
            "resolution",
            "resolved_at",
            "resolved_by",
            "resolution_reason",
            "updated_at",
        )
    )
    return job


@transaction.atomic
def resolve_failed_job(
    *, job_id: int, actor_id: int, resolution: str, reason: str
) -> ScheduledJob:
    """Archive one terminal failure from the active queue, without deleting it."""

    reason = (reason or "").strip()
    if not reason:
        raise FinanceOperationsError(
            "A resolution reason is required.", code="resolution_reason_required"
        )
    if resolution not in ScheduledJob.Resolution.values:
        raise FinanceOperationsError(
            "Unsupported job resolution.", code="invalid_job_resolution"
        )
    job = ScheduledJob.objects.select_for_update(no_key=True).get(pk=job_id)
    if job.status != ScheduledJob.Status.FAILED:
        raise FinanceOperationsError(
            "Only a terminal failed job can be resolved.", code="job_not_failed"
        )
    if job.resolution:
        raise FinanceOperationsError(
            "This job is already resolved.", code="job_already_resolved"
        )
    if (
        resolution == ScheduledJob.Resolution.DISMISSED
        and job.kind == ScheduledJob.Kind.OUTBOUND_MESSAGE
    ):
        message_id = (job.payload or {}).get("message_id")
        if isinstance(message_id, int):
            message = (
                OutboundMessage.objects.select_for_update(no_key=True)
                .filter(pk=message_id)
                .first()
            )
            if message is not None and message.status == OutboundMessage.Status.PENDING:
                message.status = OutboundMessage.Status.CANCELLED
                message.next_attempt_at = None
                message.last_error = "Cancelled through audited job dismissal."
                message.save(
                    update_fields=(
                        "status",
                        "next_attempt_at",
                        "last_error",
                        "updated_at",
                    )
                )
    job.resolution = resolution
    job.resolved_at = timezone.now()
    job.resolved_by_id = actor_id
    job.resolution_reason = reason[:500]
    job.save(
        update_fields=(
            "resolution",
            "resolved_at",
            "resolved_by",
            "resolution_reason",
            "updated_at",
        )
    )
    return job


@transaction.atomic
def queue_payment_reconciliation(*, attempt_id: int) -> tuple[ScheduledJob, str]:
    """Queue the existing authoritative recovery path; never mutate money here."""

    attempt = PaymentAttempt.objects.select_for_update(no_key=True).get(pk=attempt_id)
    if attempt.is_unapplied:
        refund = (
            PaymentRefund.objects.filter(
                attempt=attempt, reason=PaymentRefund.Reason.UNAPPLIED_PAYMENT
            )
            .order_by("pk")
            .first()
        )
        if refund is None:
            raise FinanceOperationsError(
                "This capture has no refund obligation; engineering review is required.",
                code="unapplied_refund_missing",
            )
        if refund.status == PaymentRefund.Status.SUCCEEDED:
            raise FinanceOperationsError(
                "The unapplied capture has already been fully refunded.",
                code="refund_already_succeeded",
            )
        job = schedule_job(
            kind=ScheduledJob.Kind.REFUND_RECONCILE,
            key=f"refund_reconcile:{refund.pk}",
            run_at=timezone.now(),
            payload={"refund_id": refund.pk},
            max_attempts=32,
            reactivate_failed=True,
        )
        return _reactivate_completed_job(job), "refund_reconciliation"

    if attempt.status == PaymentAttempt.Status.SUCCEEDED:
        raise FinanceOperationsError(
            "This payment is already applied.", code="payment_already_applied"
        )
    if not attempt.provider_session_id and attempt.provider == "chargily":
        # Chargily has no documented checkout-create idempotency contract.  A
        # blind recreation could charge twice, so this case stays manual.
        raise FinanceOperationsError(
            "Chargily did not return a checkout reference; it cannot be retried safely.",
            code="provider_session_unknown",
        )
    job = schedule_job(
        kind=ScheduledJob.Kind.PROVIDER_RECONCILE,
        key=f"provider_reconcile:{attempt.pk}",
        run_at=timezone.now(),
        payload={"attempt_id": attempt.pk},
        max_attempts=32,
        reactivate_failed=True,
    )
    return _reactivate_completed_job(job), "provider_reconciliation"


@transaction.atomic
def resolve_payment_attention(
    *, attempt_id: int, actor_id: int, resolution: str, reason: str
) -> PaymentAttempt:
    """Resolve attention metadata only after real money is already safe."""

    reason = (reason or "").strip()
    if not reason:
        raise FinanceOperationsError(
            "A resolution reason is required.", code="resolution_reason_required"
        )
    if resolution not in PaymentAttempt.OperationalResolution.values:
        raise FinanceOperationsError(
            "Unsupported payment resolution.", code="invalid_payment_resolution"
        )
    attempt = PaymentAttempt.objects.select_for_update(no_key=True).get(pk=attempt_id)
    if attempt.operational_resolution:
        raise FinanceOperationsError(
            "This payment attention item is already resolved.",
            code="payment_already_resolved",
        )
    if attempt.is_unapplied:
        settled = PaymentRefund.objects.filter(
            attempt=attempt,
            reason=PaymentRefund.Reason.UNAPPLIED_PAYMENT,
            status=PaymentRefund.Status.SUCCEEDED,
            amount_eur_cents=attempt.amount_eur_cents,
        ).exists()
        if not settled:
            raise FinanceOperationsError(
                "Unapplied money cannot be dismissed before its full refund succeeds.",
                code="unapplied_money_unsettled",
            )
    elif not (
        attempt.status == PaymentAttempt.Status.FAILED
        and attempt.failure_code in ATTENTION_FAILURE_CODES
    ):
        raise FinanceOperationsError(
            "This attempt is historical and is not in the finance attention queue.",
            code="payment_not_actionable",
        )
    attempt.operational_resolution = resolution
    attempt.operational_resolved_at = timezone.now()
    attempt.operational_resolved_by_id = actor_id
    attempt.operational_resolution_reason = reason[:500]
    attempt.save(
        update_fields=(
            "operational_resolution",
            "operational_resolved_at",
            "operational_resolved_by",
            "operational_resolution_reason",
            "updated_at",
        )
    )
    return attempt
