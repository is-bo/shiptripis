"""The one staff work list (spec 20.5, plan L15).

Every queue an admin may have to act on is defined here, once: who sees it,
which rows it counts, since when the oldest has waited, how urgent it is and
where to open it. The console overview and the AI helper's briefing both render
`work_items(admin)`; neither builds a list of its own, so "what needs me" has
one answer whoever asks.

**Severity is a fixed rule written next to each item**, never a guess: an item
starts at its base level and, where a rule says so, becomes ``urgent`` once its
oldest row has waited longer than that rule's limit. Raised items are ordered
most urgent first, then the longest waiting first, then in the order below.
Items with nothing waiting are kept, at the end, so "nothing to do" and "not
checked" never look the same.

**The rows are the count.** An item with a queue (`queue_type`) exposes the
exact rows it counts through `rows(code, admin)`, each annotated with
``waiting_since``, so the helper's `queues/<code>` lists what the count counted.
Items about documents (ID, tickets, payout methods, payout identity) and the
email queue (it holds recipients' addresses) are a count and a link only.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db.models import (
    Count,
    Exists,
    F,
    Min,
    OuterRef,
    Q,
    QuerySet,
    Subquery,
)
from django.db.models.functions import Coalesce
from django.urls import reverse
from django.utils import timezone

from apps.disputes.models import Dispute
from apps.finance.models import PaymentAttempt, PaymentRefund, Payout, ScheduledJob
from apps.finance.operations import payment_attention_queryset
from apps.notifications.models import OutboundMessage
from apps.ratings.models import Rating, RatingReport

from . import verification_inbox as inbox
from .permissions import has_admin_permission

URGENT = "urgent"
TODAY = "today"
INFO = "info"
SEVERITY_RANK = {URGENT: 0, TODAY: 1, INFO: 2}


@dataclass(frozen=True, slots=True)
class Severity:
    """``base`` while the queue is fresh; ``urgent`` once its oldest row has
    waited longer than ``urgent_after`` (when set)."""

    base: str
    urgent_after: timedelta | None = None

    def level(self, count: int, oldest: datetime | None, now: datetime) -> str:
        if not count:
            return INFO
        if self.urgent_after is not None and oldest is not None and now - oldest > self.urgent_after:
            return URGENT
        return self.base


@dataclass(frozen=True, slots=True)
class WorkItem:
    code: str
    #: The capabilities of the console page the item opens: any of them shows
    #: the item, exactly as any of them opens that page.
    permission: tuple[str, ...]
    title: str
    #: Why it matters, in one sentence.
    hint: str
    #: What to do, in one plain sentence (the helper's ``next_step``).
    next_step: str
    count: int
    oldest_waiting_since: datetime | None
    severity: str
    route: str
    query: str
    #: The record type of the rows `rows()` lists, or ``None`` for a count only.
    queue_type: str | None

    @property
    def url(self) -> str:
        url = reverse(self.route)
        if not self.query:
            return url
        return f"{url}{self.query}" if self.query.startswith("#") else f"{url}?{self.query}"

    @property
    def raised(self) -> bool:
        return self.count > 0


@dataclass(frozen=True, slots=True)
class _Queue:
    code: str
    #: The gate of the console page at ``route`` (its `capability_required`).
    permission: tuple[str, ...]
    title: str
    hint: str
    next_step: str
    route: str
    query: str
    severity: Severity
    #: The rows the item counts, annotated with ``waiting_since``.
    rows: Callable[..., QuerySet] | None = None
    #: Overrides measuring ``rows``: ``(admin) -> (count, oldest)``.
    measure: Callable[..., tuple[int, datetime | None]] | None = None
    queue_type: str | None = None


def _since(queryset: QuerySet, expression) -> QuerySet:
    return queryset.annotate(waiting_since=expression)


# --- the rows of each queue --------------------------------------------------------


def _id_checks(admin=None):
    return _since(inbox.waiting(inbox.TABS[0]), F("created_at"))


def _tickets(admin=None):
    return _since(inbox.waiting(inbox.TABS[1]), F("created_at"))


def _disputes(admin=None):
    return _since(
        Dispute.objects.filter(status__in=Dispute.ACTIVE_STATUSES), F("opened_at")
    )


def _problems(admin=None):
    from .console_problems import waiting

    return _since(waiting(), Coalesce("escalated_at", "created_at"))


def _open_reports_of(rating_ref):
    return RatingReport.objects.filter(rating_id=rating_ref, status=RatingReport.Status.OPEN)


def _reviews(admin=None):
    first_open = (
        _open_reports_of(OuterRef("pk")).order_by("created_at").values("created_at")[:1]
    )
    return _since(
        Rating.objects.filter(Exists(_open_reports_of(OuterRef("pk")))),
        Subquery(first_open),
    )


def _measure_reviews(admin=None):
    # The same set as `_reviews`: one row per review with an open report, and
    # its oldest open report is the oldest of them all.
    totals = RatingReport.objects.filter(status=RatingReport.Status.OPEN).aggregate(
        count=Count("rating_id", distinct=True), oldest=Min("created_at")
    )
    return totals["count"], totals["oldest"]


def _payout_methods(admin=None):
    from .console_payout_reviews import awaiting_review

    return _since(awaiting_review(), F("current_version__created_at"))


def _payout_identity(admin):
    from .console_identity_checks import waiting_rows

    return _since(waiting_rows(admin), F("created_at"))


def _payments(admin=None):
    return _since(payment_attention_queryset(PaymentAttempt.objects.all()), F("updated_at"))


def _refunds(admin=None):
    return _since(
        PaymentRefund.objects.filter(
            requires_manual_action=True,
            status__in=(PaymentRefund.Status.PENDING, PaymentRefund.Status.PROCESSING),
        ),
        F("created_at"),
    )


def _payouts(admin=None):
    return _since(
        Payout.objects.filter(
            Q(status=Payout.Status.FAILED)
            | Q(status=Payout.Status.ELIGIBLE, method=Payout.Method.MANUAL)
        ),
        Coalesce("eligible_at", "created_at"),
    )


def _email(admin=None):
    return _since(
        OutboundMessage.objects.filter(status=OutboundMessage.Status.FAILED), F("updated_at")
    )


def _jobs(admin=None):
    return _since(
        ScheduledJob.objects.filter(status=ScheduledJob.Status.FAILED, resolution=""),
        Coalesce("completed_at", "updated_at"),
    )


#: The work list, in the order equal items are shown. Each severity rule is the
#: whole rule for its item.
QUEUES: tuple[_Queue, ...] = (
    _Queue(
        code="id_checks",
        permission=(inbox.TABS[0].permission,),
        title="ID checks to review",
        hint="Travelers remain blocked from publishing until these are decided.",
        next_step="Open each ID check, look at the document, then approve, ask for a new upload or reject.",
        route=inbox.TABS[0].route,
        query=f"status={inbox.WAITING_STATUS}",
        # A traveler cannot publish: urgent once one waited over 24 hours.
        severity=Severity(TODAY, urgent_after=timedelta(hours=24)),
        rows=_id_checks,
    ),
    _Queue(
        code="tickets",
        permission=(inbox.TABS[1].permission,),
        title="Tickets to review",
        hint="Flight and ferry legs are not matchable until their ticket is approved.",
        next_step="Open each ticket, compare it with the trip, then approve, ask for a new upload or reject.",
        route=inbox.TABS[1].route,
        query=f"status={inbox.WAITING_STATUS}",
        # Trips are mostly the same day: urgent once one waited over 2 hours.
        severity=Severity(TODAY, urgent_after=timedelta(hours=2)),
        rows=_tickets,
    ),
    _Queue(
        code="disputes",
        permission=("view_disputes",),
        title="Open disputes",
        hint="Payout stays frozen while an active dispute needs a decision.",
        next_step="Open each dispute, read both sides and the evidence, then decide it.",
        route="admin_console:disputes",
        query="attention=1",
        # Money is frozen and two people are waiting: always urgent.
        severity=Severity(URGENT),
        rows=_disputes,
        queue_type="dispute",
    ),
    _Queue(
        code="problems",
        permission=("view_disputes",),
        title="Problems to look at",
        hint="Damaged or mismatched parcels and no-show reports waiting for staff.",
        next_step="Open each report and acknowledge it, or record the no-show it describes.",
        route="admin_console:problems",
        query="attention=1",
        # A parcel may be moving right now: always urgent.
        severity=Severity(URGENT),
        rows=_problems,
        queue_type="problem",
    ),
    _Queue(
        code="reviews",
        permission=("moderate_ratings",),
        title="Reported reviews",
        hint="Members reported these reviews. Dismiss, hide the comment or remove the rating.",
        next_step="Open each reported review, read it and the reports, then dismiss, hide the comment or remove it.",
        route="admin_console:reviews",
        query="status=open",
        # Nothing is blocked while it waits: today, urgent after 72 hours.
        severity=Severity(TODAY, urgent_after=timedelta(hours=72)),
        rows=_reviews,
        measure=_measure_reviews,
        queue_type="review_report",
    ),
    _Queue(
        code="payout_methods",
        permission=("review_payout_profiles",),
        title="Payout methods awaiting approval",
        hint="Travelers submitted DZD payout details that need review.",
        next_step="Open each payout method, check the details against the documents, then decide.",
        route="admin_console:payout-reviews",
        query="",
        # No payout can be sent there yet: urgent after 48 hours.
        severity=Severity(TODAY, urgent_after=timedelta(hours=48)),
        rows=_payout_methods,
    ),
    _Queue(
        code="payout_identity",
        permission=("attest_payout_identity",),
        title="Payout identity checks assigned to you",
        hint="Confirm a Traveler's legal name so their payout method can be decided.",
        next_step="Open each check assigned to you and confirm the legal name on the approved ID.",
        route="admin_console:identity-checks",
        query="",
        # Finance is waiting on this person: urgent after 48 hours.
        severity=Severity(TODAY, urgent_after=timedelta(hours=48)),
        rows=_payout_identity,
    ),
    _Queue(
        code="payments",
        permission=("view_payment_attempts", "view_payment_orders"),
        title="Payments needing finance review",
        hint="Unapplied captures and amount/currency anomalies need a decision.",
        next_step="Open each payment and reconcile it or record how it was resolved.",
        route="admin_console:payments",
        query="attention=1",
        # Money was taken that no order absorbed: always urgent.
        severity=Severity(URGENT),
        rows=_payments,
        queue_type="payment",
    ),
    _Queue(
        code="refunds",
        permission=("issue_refunds", "settle_manual_refunds"),
        title="Refunds requiring operator action",
        hint="Automatic settlement is blocked or has exhausted retries.",
        next_step="Open each refund and settle it by hand, or fix what blocks it.",
        route="admin_console:refunds",
        query="manual=1",
        # A person is owed money the system could not return: always urgent.
        severity=Severity(URGENT),
        rows=_refunds,
        queue_type="refund",
    ),
    _Queue(
        code="payouts",
        permission=("view_payouts",),
        title="Payouts requiring action",
        hint="Eligible manual payouts and failed releases are waiting.",
        next_step="Open each payout and send it, or fix why it failed.",
        route="admin_console:payouts",
        query="attention=1",
        # A traveler is waiting for earned money: urgent after 24 hours.
        severity=Severity(TODAY, urgent_after=timedelta(hours=24)),
        rows=_payouts,
        queue_type="payout",
    ),
    _Queue(
        code="email",
        permission=("view_provider_health",),
        title="Failed transactional email",
        hint="The obligation is durable, but delivery has not succeeded.",
        next_step="Open the email queue and check why sending failed.",
        route="admin_console:email",
        query="status=failed",
        # The message is kept and can be sent again: today.
        severity=Severity(TODAY),
        rows=_email,
    ),
    _Queue(
        code="jobs",
        permission=("view_scheduled_jobs", "view_operational_incidents"),
        title="Background jobs needing attention",
        hint="Terminal, unresolved work needs retry or an audited resolution.",
        next_step="Open each job, read its error category, then retry it or resolve it with a reason.",
        route="admin_console:jobs",
        query="status=failed",
        # A promised piece of work stopped for good: always urgent.
        severity=Severity(URGENT),
        rows=_jobs,
        queue_type="job",
    ),
    _Queue(
        code="providers",
        permission=("view_provider_health", "view_operational_incidents", "view_scheduled_jobs"),
        title="Provider configuration warnings",
        hint="A provider is enabled without the configuration required to operate.",
        next_step="Open System health and fix the provider marked in red.",
        route="admin_console:system",
        query="#providers",
        # Payments or email may be failing for everyone: always urgent.
        severity=Severity(URGENT),
    ),
)
_BY_CODE = {queue.code: queue for queue in QUEUES}
CODES = tuple(_BY_CODE)


def visible(queue: _Queue, admin) -> bool:
    """The admin may open the item's console page, so they see the item."""

    return any(has_admin_permission(admin, code) for code in queue.permission)


def _measure(queue: _Queue, admin, provider_rows) -> tuple[int, datetime | None]:
    if queue.code == "providers":
        return sum(1 for row in provider_rows if row["tone"] == "bad"), None
    if queue.measure is not None:
        return queue.measure(admin)
    totals = queue.rows(admin).aggregate(count=Count("pk"), oldest=Min("waiting_since"))
    return totals["count"], totals["oldest"]


def _item(queue: _Queue, admin, provider_rows, now: datetime) -> WorkItem:
    count, oldest = _measure(queue, admin, provider_rows)
    count = int(count or 0)
    return WorkItem(
        code=queue.code,
        permission=queue.permission,
        title=queue.title,
        hint=queue.hint,
        next_step=queue.next_step,
        count=count,
        oldest_waiting_since=oldest if count else None,
        severity=queue.severity.level(count, oldest, now),
        route=queue.route,
        query=queue.query,
        queue_type=queue.queue_type,
    )


def _providers(queue: _Queue, provider_rows):
    if queue.code != "providers" or provider_rows is not None:
        return provider_rows or ()
    from .console_views import _provider_rows

    return _provider_rows()


def work_items(admin, *, provider_rows=None, now: datetime | None = None) -> list[WorkItem]:
    """The admin's work list: raised items in order, then the clear ones.

    ``provider_rows`` are the console's provider readiness rows; pass them when
    the caller already built them, otherwise they are built here for an admin
    who may see them.
    """

    now = now or timezone.now()
    items: list[tuple[int, WorkItem]] = []
    for position, queue in enumerate(QUEUES):
        if not visible(queue, admin):
            continue
        if queue.code == "providers":
            provider_rows = _providers(queue, provider_rows)
        items.append((position, _item(queue, admin, provider_rows or (), now)))

    def order(entry):
        position, item = entry
        if not item.raised:
            return (1, 0, 0.0, position)
        waited = item.oldest_waiting_since
        return (
            0,
            SEVERITY_RANK[item.severity],
            waited.timestamp() if waited else float("inf"),
            position,
        )

    return [item for _position, item in sorted(items, key=order)]


def work_item(code: str, admin, *, now: datetime | None = None) -> WorkItem | None:
    """One item of the admin's work list, or ``None`` when they may not see it."""

    queue = _BY_CODE.get(code)
    if queue is None or not visible(queue, admin):
        return None
    return _item(queue, admin, _providers(queue, None), now or timezone.now())


def sees_providers(admin) -> bool:
    """Whether the admin's work list holds the provider item, so whoever
    renders it should build the provider rows once and pass them in."""

    return visible(_BY_CODE["providers"], admin)


def queue_definition(code: str) -> _Queue | None:
    return _BY_CODE.get(code)


def rows(code: str, admin) -> QuerySet:
    """The rows one item counts, oldest first, each with ``waiting_since``."""

    queue = _BY_CODE[code]
    if queue.rows is None:
        raise LookupError(f"Work item {code!r} has no rows.")
    return queue.rows(admin).order_by("waiting_since", "pk")
