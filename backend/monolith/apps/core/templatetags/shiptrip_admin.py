"""The shell and the queue panel of the ShipTrip operations console.

Two things live here, both of them about orientation rather than data.

**Navigation.** The console has twenty destinations. Listing all twenty at
equal weight answers "where can I go" and never answers "where am I", which is
the question an operator actually has open. So the shell renders two rows: the
ten sections, and then only the current section's destinations. A section stays
lit while the operator is anywhere inside it, including on a detail page opened
from one of its queues.

**The queue panel** on Django's own dashboard. That page is an alphabetical
directory of registered models; a directory never answers "is anything wrong
right now", and answering it by opening nine changelists in turn is how a stuck
refund survives a shift. Every row is a **count of rows in a state a person has
to act on**, linked to the changelist already filtered to exactly that state.
Nothing is summed, converted or derived: the panel counts, and the changelist
behind the link is the authority for what it counted. Rows at zero stay visible
and quiet, so an empty queue reads as *checked* rather than as *missing*.
"""

from __future__ import annotations

from dataclasses import dataclass

from django import template
from django.apps import apps
from django.db.models import Q
from django.urls import NoReverseMatch, reverse
from django.utils.html import format_html, mark_safe

from apps.admin_panel.permissions import has_admin_permission
from apps.core.admin_display import (
    format_eur,
    humanize_action,
    humanize_object,
    tone_for,
)

register = template.Library()

register.filter("eur", format_eur)
register.filter("status_tone", tone_for)


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------

#: One small stroke icon per section. The icon is a second, non-textual cue for
#: an operator who navigates by shape rather than by re-reading ten labels; the
#: label is always present, so the icon never carries meaning on its own.
SECTION_ICONS = {
    "Overview": "M3 11.5 12 4l9 7.5M5.5 10.2V19.5h13V10.2",
    "People": "M12 11.5a3.6 3.6 0 1 0 0-7.2 3.6 3.6 0 0 0 0 7.2ZM4.8 20a7.2 7.2 0 0 1 14.4 0",
    "Verification": "M12 3.5 5.2 6v5.8c0 4 2.9 7.1 6.8 8.7 3.9-1.6 6.8-4.7 6.8-8.7V6L12 3.5Zm-2.6 8.4 2.1 2.1 4-4.2",
    "Marketplace": "M3.6 7.9 12 4l8.4 3.9v8.2L12 20l-8.4-3.9V7.9Zm0 0L12 11.8m0 0 8.4-3.9M12 11.8V20",
    "Disputes": "M12 4.2v15.6M6.6 7.4h10.8M8.4 7.4 5.7 13.1h5.4L8.4 7.4Zm7.2 0-2.7 5.7h5.4l-2.7-5.7Z",
    "Finance": "M16 7.6a5.2 5.2 0 1 0 0 8.8M5.4 10.6h7.2M5.4 13.4h7.2",
    "Staff": "M13.8 10.2a3.4 3.4 0 1 1 3.3-4.2h3.4l-1.6 2.9h-2v2.4",
    "Settings": "M4.6 7.6h14.8M4.6 12h14.8M4.6 16.4h14.8M9 5.6v4M15.4 10v4M11.2 14.4v4",
    "System": "M3.6 12h4L10 6.4l4 11.2 2.4-5.6h4",
    "Reference": "M4.8 5.4h5.6a1.8 1.8 0 0 1 1.6 1.8v11.4a1.8 1.8 0 0 0-1.6-1.4H4.8V5.4Zm14.4 0h-5.6a1.8 1.8 0 0 0-1.6 1.8v11.4a1.8 1.8 0 0 1 1.6-1.4h5.6V5.4Z",
}

#: ``(section, ((label, route, capabilities, highlight_routes), ...))``.
#: ``highlight_routes`` lists every url name that should keep the destination
#: lit, so opening one KYC submission never makes the console look like it
#: left Verification. ``__superuser__`` is the owner-only escape hatch.
NAVIGATION = (
    (
        "Overview",
        (("Overview", "admin_console:overview", ("view_dashboard",), ("overview",)),),
    ),
    (
        "People",
        (("Users", "admin_console:users", ("view_users",), ("users", "user-detail")),),
    ),
    (
        "Verification",
        (
            (
                "KYC review",
                "admin_console:kyc-queue",
                ("view_kyc",),
                ("kyc-queue", "kyc-detail", "kyc-evidence"),
            ),
            (
                "Flight proofs",
                "admin_console:proof-queue",
                ("view_flight_proofs",),
                ("proof-queue", "proof-detail", "proof-evidence"),
            ),
        ),
    ),
    (
        "Marketplace",
        (
            (
                "Delivery requests",
                "admin_console:requests",
                ("view_requests",),
                ("requests",),
            ),
            (
                "Journeys",
                "admin_console:journeys",
                ("view_journeys",),
                ("journeys", "journey-detail"),
            ),
            ("Deals", "admin_console:deals", ("view_deals",), ("deals", "deal-detail")),
        ),
    ),
    (
        "Disputes",
        (
            (
                "Disputes",
                "admin_console:disputes",
                ("view_disputes",),
                ("disputes", "dispute-detail", "dispute-evidence"),
            ),
        ),
    ),
    (
        "Finance",
        (
            (
                "Payments",
                "admin_console:payments",
                ("view_payment_attempts", "view_payment_orders"),
                ("payments", "refund-new"),
            ),
            (
                "Refunds",
                "admin_console:refunds",
                ("issue_refunds", "settle_manual_refunds"),
                ("refunds", "refund-detail"),
            ),
            (
                "Payouts",
                "admin_console:payouts",
                ("view_payouts",),
                ("payouts", "payout-detail"),
            ),
            (
                "Payout accounts",
                "admin_console:payout-accounts",
                ("view_finance_summary",),
                ("payout-accounts",),
            ),
            ("Ledger", "admin_console:ledger", ("reconcile_finance",), ("ledger",)),
        ),
    ),
    (
        "Staff",
        (
            (
                "Staff & access",
                "admin_console:staff",
                ("manage_admins",),
                ("staff", "staff-role", "staff-access", "staff-invitation-action"),
            ),
        ),
    ),
    (
        "Settings",
        (
            (
                "Business settings",
                "admin_console:settings",
                ("view_settings",),
                ("settings",),
            ),
        ),
    ),
    (
        "System",
        (
            (
                "Health",
                "admin_console:system",
                (
                    "view_provider_health",
                    "view_operational_incidents",
                    "view_scheduled_jobs",
                ),
                ("system",),
            ),
            (
                "Background jobs",
                "admin_console:jobs",
                ("view_scheduled_jobs", "view_operational_incidents"),
                ("jobs",),
            ),
            (
                "Email queue",
                "admin_console:email",
                ("view_provider_health",),
                ("email",),
            ),
        ),
    ),
    (
        "Reference",
        (
            (
                "Geography catalogue",
                "admin_console:geography",
                ("view_operational_incidents", "view_journeys"),
                ("geography",),
            ),
            ("Audit log", "admin_console:audit", ("view_audit_log",), ("audit",)),
            (
                "Technical records",
                "admin_console:technical",
                ("__superuser__",),
                ("technical",),
            ),
        ),
    ),
)


def _may_reach(user, capabilities: tuple[str, ...]) -> bool:
    """UI filtering only. The view's own capability check stays authoritative."""

    if not capabilities:
        return True
    if capabilities == ("__superuser__",):
        return bool(user.is_superuser)
    return any(has_admin_permission(user, code) for code in capabilities)


def _navigation_sections(user):
    """The destinations this staff role may reach, grouped into sections."""

    sections = []
    for label, entries in NAVIGATION:
        items = []
        for item_label, route, capabilities, routes in entries:
            if not _may_reach(user, capabilities):
                continue
            try:
                url = reverse(route)
            except NoReverseMatch:  # pragma: no cover - defensive
                continue
            items.append(
                {
                    "label": item_label,
                    "url": url,
                    "route": route.split(":")[-1],
                    "routes": routes,
                }
            )
        if items:
            sections.append({"label": label, "items": tuple(items)})
    return tuple(sections)


def _section_icon(name: str):
    path = SECTION_ICONS.get(name)
    if not path:
        return ""
    return format_html(
        '<svg class="st-nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor"'
        ' stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"'
        ' aria-hidden="true" focusable="false"><path d="{}"/></svg>',
        path,
    )


@register.simple_tag(takes_context=True)
def operations_navigation(context):
    """Render the two-level console navigation for the current staff role."""

    request = context.get("request")
    user = getattr(request, "user", None)
    if request is None or not getattr(user, "is_authenticated", False):
        return ""
    sections = _navigation_sections(user)
    if not sections:
        return ""
    match = getattr(request, "resolver_match", None)
    current = getattr(match, "url_name", "") or ""

    active = None
    for section in sections:
        if any(current in item["routes"] for item in section["items"]):
            active = section
            break

    tabs = [
        format_html(
            '<a class="st-nav-tab{}" href="{}"{}>{}<span>{}</span></a>',
            " is-current" if section is active else "",
            section["items"][0]["url"],
            mark_safe(' aria-current="true"' if section is active else ""),
            _section_icon(section["label"]),
            section["label"],
        )
        for section in sections
    ]
    primary = format_html(
        '<div class="st-nav-primary">{}</div>',
        mark_safe("".join(str(tab) for tab in tabs)),
    )

    secondary = ""
    if active and len(active["items"]) > 1:
        links = [
            format_html(
                '<a class="st-nav-link{}" href="{}"{}>{}</a>',
                " is-current" if current in item["routes"] else "",
                item["url"],
                mark_safe(' aria-current="page"' if current in item["routes"] else ""),
                item["label"],
            )
            for item in active["items"]
        ]
        secondary = format_html(
            '<div class="st-nav-secondary"><span class="st-nav-section">{}</span>{}</div>',
            active["label"],
            mark_safe("".join(str(link) for link in links)),
        )

    return format_html(
        '<nav class="st-primary-nav" aria-label="Operations navigation">{}{}</nav>',
        primary,
        mark_safe(str(secondary)),
    )


@register.simple_tag(takes_context=True)
def operations_destinations(context):
    """Every destination this role may reach, grouped by section.

    The shell's second row only carries the current section, which keeps it
    readable but would otherwise leave the other sections' destinations one
    guess away. The overview renders this map so nothing is ever unreachable
    from the page an operator lands on.
    """

    request = context.get("request")
    user = getattr(request, "user", None)
    if request is None or not getattr(user, "is_authenticated", False):
        return ()
    return _navigation_sections(user)


# ---------------------------------------------------------------------------
# Wording
# ---------------------------------------------------------------------------

register.filter("admin_action", humanize_action)
register.filter("object_label", humanize_object)


# ---------------------------------------------------------------------------
# The queue panel on Django's own dashboard
# ---------------------------------------------------------------------------


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


@register.simple_tag(takes_context=True)
def needs_attention(context):
    """Render the queue panel. Silent for a user who cannot see any of it."""

    request = context.get("request")
    if request is None or not getattr(request.user, "is_active", False):
        return ""
    if not (request.user.is_staff and request.user.is_superuser):
        # Least privilege: the panel counts rows across finance, KYC and
        # disputes at once, so it is shown only to an operator who could open
        # every one of those changelists anyway.
        return ""
    rows = [row for row in (_row(queue) for queue in QUEUES) if row is not None]
    if not rows:
        return ""
    raised = sum(1 for row in rows if row["raised"])
    summary = (
        f"{raised} queue{'s' if raised != 1 else ''} with work waiting"
        if raised
        else "Every queue is empty right now."
    )
    list_items = []
    for row in rows:
        list_items.append(
            format_html(
                '<li class="st-attention-row st-attention-{}"><a href="{}">'
                '<span class="st-attention-count">{}</span>'
                '<span class="st-attention-label">{}</span>'
                '<span class="st-attention-hint">{}</span></a></li>',
                row["tone"],
                row["url"],
                row["count"],
                row["label"],
                row["hint"],
            )
        )
    return format_html(
        '<section class="st-attention" aria-labelledby="st-attention-title">'
        '<div class="st-attention-head"><h2 id="st-attention-title">Needs attention</h2>'
        '<p class="st-attention-summary">{}</p></div>'
        '<ul class="st-attention-list">{}</ul>'
        '<p class="st-attention-foot">Each number is a count of rows in that state, '
        "linked to the changelist filtered to exactly those rows.</p></section>",
        summary,
        mark_safe("".join(str(item) for item in list_items)),
    )
