"""The queue panel that sits at the top of the operations dashboard.

Django's admin index is an alphabetical list of every registered model. It is
a directory, and a directory answers "where do I go to look at payouts" — it
never answers "is anything wrong right now". On an operational surface that is
the more important question, and answering it by opening nine changelists in
turn is how a stuck refund survives a shift.

Every row here is a **count of rows in a state a person has to act on**, linked
to the changelist already filtered to exactly that state. Nothing is summed,
converted or derived: the panel counts, and the changelist behind the link is
the authority for what it counted. Rows at zero stay visible and quiet, so an
empty queue reads as *checked* rather than as *missing*.
"""

from __future__ import annotations

from dataclasses import dataclass

from django import template
from django.apps import apps
from django.db.models import Q
from django.urls import NoReverseMatch, reverse

register = template.Library()


@dataclass(frozen=True)
class Queue:
    """One thing an operator may have to do, and how many of it there are."""

    label: str
    #: What the operator should do about it, in one short line.
    hint: str
    app_label: str
    model_name: str
    #: Query string appended to the changelist so the link lands on the rows
    #: that were counted, not on the unfiltered list.
    query: str
    filters: Q
    #: `bad` outranks `attn` outranks `wait` in the panel ordering.
    tone: str = "attn"


#: Ordered by how bad it is for the row to sit unattended, not by app.
QUEUES: tuple[Queue, ...] = (
    Queue(
        label="Disputes awaiting a decision",
        hint="Payout is frozen while these are open.",
        app_label="disputes",
        model_name="dispute",
        query="status__in=open,awaiting_evidence,under_review",
        filters=Q(status__in=("open", "awaiting_evidence", "under_review")),
        tone="bad",
    ),
    Queue(
        label="Refunds needing manual action",
        hint="The provider could not settle these automatically.",
        app_label="finance",
        model_name="paymentrefund",
        query="requires_manual_action__exact=1",
        filters=Q(requires_manual_action=True),
        tone="bad",
    ),
    Queue(
        label="Payments received but unapplied",
        hint="Money arrived that no order could be credited with.",
        app_label="finance",
        model_name="paymentattempt",
        query="is_unapplied__exact=1",
        filters=Q(is_unapplied=True),
        tone="bad",
    ),
    Queue(
        label="Payouts eligible for manual settlement",
        hint="Protection has closed and no dispute is open.",
        app_label="finance",
        model_name="payout",
        query="status__exact=eligible&method__exact=manual",
        filters=Q(status="eligible", method="manual"),
    ),
    Queue(
        label="KYC submissions to review",
        hint="A traveler cannot be matched until this is decided.",
        app_label="kyc",
        model_name="kycsubmission",
        query="status__exact=pending",
        filters=Q(status="pending"),
    ),
    Queue(
        label="Flight proofs to review",
        hint="A flight leg is unmatchable until its proof is approved.",
        app_label="trips",
        model_name="journeylegproof",
        query="status__exact=pending",
        filters=Q(status="pending"),
    ),
    Queue(
        label="Provider events not applied",
        hint="A webhook failed its signature check or its handler.",
        app_label="finance",
        model_name="paymentproviderevent",
        query="processing_result__in=retryable,failed",
        filters=Q(processing_result__in=("retryable", "failed")),
    ),
    Queue(
        label="Scheduled jobs failed",
        hint="Requeue once the cause is understood.",
        app_label="finance",
        model_name="scheduledjob",
        query="status__exact=failed",
        filters=Q(status="failed"),
    ),
    Queue(
        label="Transactional email failed",
        hint="The obligation is durable; the send is not getting through.",
        app_label="notifications",
        model_name="outboundmessage",
        query="status__exact=failed",
        filters=Q(status="failed"),
    ),
)


def _row(queue: Queue) -> dict | None:
    """Resolve one queue, or `None` if its model or admin is not available."""

    try:
        model = apps.get_model(queue.app_label, queue.model_name)
    except LookupError:
        return None
    try:
        url = reverse(f"admin:{queue.app_label}_{queue.model_name}_changelist")
    except NoReverseMatch:
        return None
    count = model._default_manager.filter(queue.filters).count()
    return {
        "label": queue.label,
        "hint": queue.hint,
        "count": count,
        "url": f"{url}?{queue.query}",
        # A queue at zero is not an alarm, whatever its configured tone is.
        "tone": queue.tone if count else "mute",
        "raised": bool(count),
    }


@register.inclusion_tag("admin/shiptrip/needs_attention.html", takes_context=True)
def needs_attention(context):
    """Render the queue panel. Silent for a user who cannot see any of it."""

    request = context.get("request")
    if request is None or not getattr(request.user, "is_active", False):
        return {"rows": [], "raised": 0}
    if not (request.user.is_staff and request.user.is_superuser):
        # Least privilege: the panel counts rows across finance, KYC and
        # disputes at once, so it is shown only to an operator who could open
        # every one of those changelists anyway.
        return {"rows": [], "raised": 0}
    rows = [row for row in (_row(queue) for queue in QUEUES) if row is not None]
    return {"rows": rows, "raised": sum(1 for row in rows if row["raised"])}
