"""The helper's call log, kept 30 days (spec 20.6, plan L15).

Every call made with a valid key is recorded once its response is built: time,
key, method, path (without the query string) and status. The admin reads their
own recent calls on the AI helper page.

Pruning is a durable `ScheduledJob`, one per day that had calls, due when that
day's rows pass 30 days. A row therefore always has a job that will remove it,
whatever happens to the workers in between, and nothing has to re-arm itself.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from datetime import timezone as dt_timezone

from django.db.models import F
from django.utils import timezone

from .models import AdminHelperCall, AdminHelperKey

RETENTION = timedelta(days=30)
PRUNE_JOB_PREFIX = "admin_helper_call_prune"


def record_call(key: AdminHelperKey, *, method: str, path: str, status: int) -> None:
    now = timezone.now()
    AdminHelperCall.objects.create(
        key=key, method=method[:8], path=path[:300], status=status, at=now
    )
    AdminHelperKey.objects.filter(pk=key.pk).update(
        last_used_at=now, use_count=F("use_count") + 1
    )
    schedule_prune(now)


def schedule_prune(moment: datetime) -> None:
    """Make sure the rows written on ``moment``'s day have their removal due."""

    from apps.finance.models import ScheduledJob
    from apps.finance.services import schedule_job

    day = moment.astimezone(dt_timezone.utc).date()
    end_of_day = datetime.combine(day + timedelta(days=1), time.min, tzinfo=dt_timezone.utc)
    schedule_job(
        kind=ScheduledJob.Kind.ADMIN_HELPER_CALL_PRUNE,
        key=f"{PRUNE_JOB_PREFIX}:{day.isoformat()}",
        run_at=end_of_day + RETENTION,
        payload={"day": day.isoformat()},
    )


def prune_calls(*, now: datetime | None = None) -> int:
    """Delete every call older than 30 days; return how many."""

    cutoff = (now or timezone.now()) - RETENTION
    deleted, _ = AdminHelperCall.objects.filter(at__lt=cutoff).delete()
    return deleted


def handle_prune_job(payload: dict) -> str:
    return f"deleted={prune_calls()}"
