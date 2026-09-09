"""The thing that finds payouts nobody is looking at any more.

Every other path into execution depends on something staying alive: a webhook
being delivered, a Redis message surviving, a `ScheduledJob` row not having
exhausted its attempts, a worker not having been killed between two statements.
Each of those is reliable most of the time, and "most of the time" is not a
property a payout rail can be built on.

So this runs on a schedule and asks three bounded, indexed questions:

* Is there an eligible Stripe payout with no live job? Arm one.
* Is there an external operation or disbursement that is not in a terminal
  state? Reconcile it, whether or not new execution is enabled — a kill switch
  must never stop the system finding out what already-sent instructions did.
* Is there a connected account whose readiness is stale under an unpaid
  obligation? Refresh it.

Everything here is a bounded page over an indexed predicate. There is no
full-table scan, and the sweep never itself calls a provider: it arms durable
jobs and returns. A sweep that found nothing costs three indexed queries.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from .models import (
    Payout,
    PayoutProviderOperation,
    ScheduledJob,
    StripeDisbursement,
    StripePayoutAccount,
)

logger = logging.getLogger(__name__)

#: How many rows one pass may claim per question. Small on purpose: the sweep
#: is a safety net, not a scheduler, and a backlog is drained over several
#: passes rather than in one long transaction.
SWEEP_PAGE = 50

#: In-flight external work is re-read every five minutes, per H0.
RECONCILE_INTERVAL_SECONDS = 300

#: A readiness observation older than this under an unpaid obligation is
#: refreshed even if nothing asked for it.
ACCOUNT_STALE_SECONDS = 6 * 3600


def _arm(kind: str, key: str, payload: dict, *, delay_seconds: int = 0) -> bool:
    """Make sure a live obligation exists for this work, and re-arm a spent one.

    `schedule_job` is idempotent on the key and will revive a *failed* job, but
    it deliberately leaves a `succeeded` one alone — for a one-shot obligation
    that is exactly right. The payout kinds are not one-shot: a payout blocked
    below the provider minimum, or one waiting on a condition that may resolve
    later, needs looking at again, and its job has already succeeded by
    correctly reporting "still blocked". Without this it would be armed once and
    then never re-checked, which is a payout quietly falling out of the queue.

    Only a job whose own `run_at` has already passed is revived, so this cannot
    shorten a deliberate wait.
    """

    from .services import schedule_job

    now = timezone.now()
    run_at = now + timedelta(seconds=delay_seconds)
    existing = ScheduledJob.objects.filter(key=key).first()
    if (
        existing is not None
        and existing.status == ScheduledJob.Status.SUCCEEDED
        and existing.run_at <= now
    ):
        ScheduledJob.objects.filter(
            pk=existing.pk, status=ScheduledJob.Status.SUCCEEDED
        ).update(
            status=ScheduledJob.Status.PENDING,
            run_at=run_at,
            attempts=0,
            locked_at=None,
            locked_by="",
            completed_at=None,
            updated_at=now,
        )
        return True
    schedule_job(
        kind=kind,
        key=key,
        run_at=run_at,
        payload=payload,
        max_attempts=32,
        reactivate_failed=True,
    )
    return existing is None or existing.status != ScheduledJob.Status.PENDING


def sweep_reconciliation(*, limit: int = SWEEP_PAGE) -> int:
    """Re-drive every nonterminal external operation and disbursement."""

    armed = 0
    payout_ids = set(
        PayoutProviderOperation.objects.filter(
            status__in=["committed", "unknown", "accepted"],
            attempt__isnull=False,
            kind__in=["transfer_create", "bank_payout_create"],
        )
        .order_by("pk")
        .values_list("attempt__payout_id", flat=True)[:limit]
    )
    payout_ids.update(
        StripeDisbursement.objects.filter(
            status__in=list(StripeDisbursement.LIVE_STATUSES)
        )
        .order_by("pk")
        .values_list("allocations__payout_id", flat=True)[:limit]
    )
    for payout_id in sorted(pk for pk in payout_ids if pk):
        if _arm(
            ScheduledJob.Kind.PAYOUT_RECONCILE,
            f"payout_reconcile:{payout_id}",
            {"payout_id": payout_id},
            delay_seconds=RECONCILE_INTERVAL_SECONDS,
        ):
            armed += 1
    return armed


def sweep_execution(*, limit: int = SWEEP_PAGE) -> int:
    """Arm work for payouts that are releasable and have no live instruction."""

    from .payout_execution import execution_enabled

    enabled, _ = execution_enabled()
    if not enabled:
        return 0
    now = timezone.now()
    # Two disjoint predicates rather than one OR, so both stay index-friendly:
    # a payout with no block reason at all, and one whose block reason a
    # condition may have resolved (setup completed, hold cleared, minimum met).
    ready = (
        Payout.objects.filter(
            method="stripe_transfer",
            snapshot_version__gt=0,
            payout_currency="EUR",
            status__in=["eligible", "scheduled", "processing", "failed"],
            eligible_at__isnull=False,
            block_reason="",
        )
        .filter(Q(next_action_at__isnull=True) | Q(next_action_at__lte=now))
        .order_by("pk")
        .values_list("pk", flat=True)[:limit]
    )
    deferred = (
        Payout.objects.filter(
            method="stripe_transfer",
            snapshot_version__gt=0,
            payout_currency="EUR",
            status="blocked",
            eligible_at__isnull=False,
            next_action_at__lte=now,
        )
        .order_by("pk")
        .values_list("pk", flat=True)[:limit]
    )
    armed = 0
    for payout_id in sorted(set(ready) | set(deferred)):
        if _arm(
            ScheduledJob.Kind.PAYOUT_EXECUTE,
            f"payout_execute:{payout_id}",
            {"payout_id": payout_id},
        ):
            armed += 1
    return armed


def sweep_accounts(*, limit: int = SWEEP_PAGE) -> int:
    """Refresh readiness for accounts holding unpaid EUR obligations."""

    cutoff = timezone.now() - timedelta(seconds=ACCOUNT_STALE_SECONDS)
    account_ids = (
        StripePayoutAccount.objects.filter(
            active=True,
            payoutmethodversion__active_payouts__status__in=[
                "eligible",
                "scheduled",
                "processing",
                "blocked",
                "failed",
            ],
        )
        .filter(Q(readiness_checked_at__isnull=True) | Q(readiness_checked_at__lt=cutoff))
        .order_by("pk")
        .values_list("pk", flat=True)
        .distinct()[:limit]
    )
    armed = 0
    for account_id in account_ids:
        if _arm(
            ScheduledJob.Kind.PAYOUT_ACCOUNT_REFRESH,
            f"payout_account_refresh:{account_id}",
            {"account_id": account_id},
        ):
            armed += 1
    return armed


def sweep_payouts(*, limit: int = SWEEP_PAGE) -> dict:
    """One bounded pass. Safe to call as often as the worker loop turns."""

    return {
        "reconcile": sweep_reconciliation(limit=limit),
        "execute": sweep_execution(limit=limit),
        "accounts": sweep_accounts(limit=limit),
    }
