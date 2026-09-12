"""H5.2 — the Finance operations workspace.

H5 is a control plane and H5.1 rendered it faithfully: every published figure,
every comparison, every stated limit, on one page. That page is financially
correct and operationally unusable. It opens with ten filters, carries roughly
thirty equally-weighted figures and six tables, and buries the only two queues a
Finance operator actually works — the dinar transfers waiting for a person, and
the payouts that are stuck — three screens below the accounting.

This module does not change any of that arithmetic. It changes who each surface
is addressed to. Five destinations replace one page:

* **Overview** — what needs a person today, what is queued, three totals.
* **Payouts** — every payout, grouped by whether it is stuck, due, moving or done.
* **Manual DZD** — the dinar queue, which is the most human-sensitive workflow.
* **Refunds & disputes** — the exceptions, each naming who acts next.
* **Reconciliation** — H5.1's audit surface, intact, for the people who need it.

Three rules hold the financial boundary, inherited verbatim from H5.1 and
tightened by one:

* **No arithmetic on money.** An amount is shown only where H5 published that
  exact figure. A cohort spanning more than one published figure carries a
  count and no amount, because adding two of H5's amounts together would
  publish a total H5 did not.
* **Counts may be grouped.** H5's buckets and stages are disjoint by
  construction, and a count of rows is not a financial total. Cohort badges are
  sums of counts and nothing else.
* **Null is not zero, and read-only stays read-only.** Every view here is GET,
  and none of them reaches a service that can move money. `Pay now`, `Mark
  paid`, `Refund` and `Reverse` stay on the audited screens that own them.

One further boundary is worth naming because it is the only place this module
reads a model directly. A queue needs two facts H5 deliberately does not
publish — how long a payout has been waiting, and what is blocking it — and
neither is money. `_operational_facts` reads exactly those two columns for the
payouts already on screen. It reads no amount, and no figure on any page comes
from it.
"""

from __future__ import annotations

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import ValidationError
from django.db import OperationalError
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from apps.admin_panel import finance_dashboard_labels as words
from apps.core.admin_display import format_eur
from apps.finance.control_plane.drilldown import drilldown
from apps.finance.control_plane.filters import Scope
from apps.finance.control_plane.snapshot import build_snapshot

from .console_presenters import format_minor_amount
from .finance_dashboard import (
    SCOPE_FIELDS,
    _guard,
    _read_at,
    _render,
    scope_params,
    value,
)
from .permissions import has_admin_permission

#: The only query keys these pages own beyond H5's own scope. `cohort` selects a
#: tab and means nothing to H5, so it is carried through links but never reaches
#: `Scope.parse`, which refuses a filter it does not recognise rather than
#: answering a different question from the one that was asked.
PAGE_FIELDS = (*SCOPE_FIELDS, "cohort")


def _link(params, **overrides):
    """A URL query that keeps the operator's scope and their selected tab."""

    from urllib.parse import urlencode

    values = {key: params.get(key, "") for key in PAGE_FIELDS}
    values.update(overrides)
    return urlencode({key: item for key, item in values.items() if item})


#: Query keys that belong to the page rather than to H5.
_PAGE_ONLY = ("cohort", "page", "page_size", "metric")


def _scope_only(params, **overrides):
    """The request's filters, minus this module's own keys.

    Unknown keys are deliberately left in rather than whitelisted away. H5
    refuses a filter it does not recognise and the operator is told, instead of
    being shown a different question's answer under the filters they thought
    they had set. The `QueryDict` is copied rather than flattened because
    `MultiValueDict` subclasses `dict` and stores lists — `{**params}` yields
    `["test"]` where `params["mode"]` yields `"test"` — and because H5's own
    repeated-filter check needs `getlist` to still be there.
    """

    values = params.copy()
    for key in _PAGE_ONLY:
        values.pop(key, None)
    for key, item in overrides.items():
        values[key] = item
    return values

# ---------------------------------------------------------------------------
# Operator language
# ---------------------------------------------------------------------------
#
# Presentation only. Nothing below renames a backend enum or restates a
# definition; it is the plainer register the operational surfaces speak, beside
# the accounting register the reconciliation page keeps. An operator settling a
# dinar transfer should not need to know what a rail is.

#: The three amounts the Overview leads with. H5's own definition sentence
#: stays available on the reconciliation surface, not on the card face.
HEADLINE = (
    ("gross_funded", "Money processed", "Funded through ShipTrip in this period"),
    ("recognized_revenue", "ShipTrip earned", "Platform revenue earned in this period"),
    ("traveler_outstanding", "Owed to Travelers", "Outstanding now. Never ShipTrip's"),
)

#: Rail stages as an operator reads them. `words.STAGE_LABELS` remains the
#: accounting register and is what the drilldown and reconciliation still print.
STAGES = {
    **words.STAGE_LABELS,
    "connected_funds": "Held in Stripe",
    "connected_balance_pending": "Stripe balance not yet available",
    "bank_processing": "Bank transfer processing",
    "bank_in_transit": "Sent to bank",
    "transfer_committed_or_unknown": "Committed, outcome unconfirmed",
    "transfer_sent": "Sent, awaiting settlement",
    "failed_or_returned": "Returned by the bank",
    "settled": "Paid",
}

#: "Rail" is an engineering word for the route money takes. The operator's
#: question is which method pays this person.
METHODS = {
    "stripe_eur": "Stripe EUR",
    "manual_dzd": "Manual DZD",
    "legacy_unclassified": "Unclassified method",
}

#: Finance health in one line. The six comparisons live on the reconciliation
#: page; this is the only reading the operational surfaces carry.
HEALTH = {
    "ok": ("Finance reconciled", "ok", "Every comparison agrees and the ledger balances."),
    "warning": (
        "Finance warning — review",
        "wait",
        "Totals still agree. A stated condition needs a person to read it.",
    ),
    "mismatch": (
        "Finance mismatch — investigation required",
        "bad",
        "A reported total disagrees with its independent record.",
    ),
}

# ---------------------------------------------------------------------------
# Operational cohorts
# ---------------------------------------------------------------------------
#
# H5 publishes 25 operation stages and 11 exclusive liability buckets. Both are
# correct and both stay. Neither is a work queue: the operator's question is not
# "which bucket is this" but "is it stuck, is it mine, is it moving, or is it
# done". The cohorts are that question and nothing more — a pure regrouping in
# which every stage appears exactly once and no stage is dropped.

ATTENTION_STAGES = (
    "blocked_or_failed",
    "failed_or_returned",
    "held",
    "disputed",
    "blocked",
    "inconsistent",
)
READY_STAGES = ("waiting_for_finance", "claimed", "eligible", "scheduled")
MOVING_STAGES = (
    "transfer_processing",
    "transfer_sent",
    "processing",
    "connected_funds",
    "connected_balance_pending",
    "bank_processing",
    "bank_in_transit",
    "transfer_committed_or_unknown",
    "sent",
)
NOT_DUE_STAGES = ("pre_delivery", "protection", "awaiting_release")
PAID_STAGES = ("settled",)

#: `(key, label, blurb, tone, stages)`. Only the first cohort may shout.
PAYOUT_COHORTS = (
    ("attention", "Needs attention", "Stuck, refused or frozen. A person has to act.", "bad", ATTENTION_STAGES),
    ("ready", "Ready", "Due now, with nothing blocking them.", "attn", READY_STAGES),
    ("moving", "Processing", "On their way. Worth watching, not worth touching.", "", MOVING_STAGES),
    ("not_due", "Not due yet", "Delivery or the protection window still to run.", "", NOT_DUE_STAGES),
    ("paid", "Paid", "Money has reached the Traveler.", "ok", PAID_STAGES),
)

#: The manual dinar queue, in the order one payout travels it.
DZD_COHORTS = (
    ("waiting", "Waiting for Finance", "Released, and nobody has picked them up.", "attn", ("waiting_for_finance",)),
    ("claimed", "Claimed / in progress", "An operator has taken these and is sending them.", "", ("claimed", "transfer_processing")),
    ("sent", "Sent / awaiting settlement", "Recorded as sent, not yet attested as paid.", "", ("transfer_sent",)),
    ("completed", "Completed", "Attested as paid. The euro obligation is discharged.", "ok", ("settled",)),
)

#: The Overview's needs-attention list. Each row is one authoritative H5 value,
#: the words for it, who acts next, and how strongly it is drawn. `metric` reads
#: an H5 metric; `stage` reads rail-operations instead, and carries no amount
#: because it can span both payout methods.
ATTENTION = (
    {
        "key": "blocked",
        "metric": "liability_blocked",
        "label": "Payouts blocked or failed",
        "says": "Payment could not be made. The Traveler is still owed.",
        "owner": "Finance",
        "tone": "bad",
        "cohort": "attention",
    },
    {
        "key": "returned",
        "stage": "failed_or_returned",
        "label": "Payouts returned by the bank",
        "says": "The bank refused the payout or sent the money back.",
        "owner": "Finance",
        "tone": "bad",
        "cohort": "attention",
    },
    {
        "key": "refunds_failed",
        "metric": "refunds_failed",
        "label": "Refunds that failed to execute",
        "says": "Entitlement is unresolved. A person has to decide these.",
        "owner": "Finance",
        "tone": "bad",
        "exceptions": True,
    },
    {
        "key": "inconsistent",
        "metric": "liability_inconsistent",
        "label": "Payouts whose state and balance disagree",
        "says": "A reconciliation defect, not a work queue. Investigate before acting.",
        "owner": "Finance lead",
        "tone": "bad",
        "cohort": "attention",
    },
    {
        "key": "holds",
        "metric": "held_payouts",
        "label": "Payouts under a Finance hold",
        "says": "Finance froze these deliberately, and Finance has to clear them.",
        "owner": "Finance",
        "tone": "attn",
        "exceptions": True,
    },
    {
        "key": "disputes",
        "metric": "user_disputed_payouts",
        "label": "Payouts frozen by a ShipTrip dispute",
        "says": "The payout stays frozen until the dispute is resolved.",
        "owner": "Support / Ops",
        "tone": "attn",
        "exceptions": True,
    },
    {
        "key": "provider_disputes",
        "metric": "provider_disputed_payouts",
        "label": "Payouts touched by a provider dispute",
        "says": "Raised at the card network against the money that funded the Deal.",
        "owner": "Finance / Risk",
        "tone": "attn",
        "exceptions": True,
    },
)

#: Existing `AdminAuditLog` actions — the immutable record the console already
#: writes when an operator changes a payout or a refund. No new event is emitted
#: for this feed and no total is derived from it. Access events are deliberately
#: absent: a dashboard line naming who opened a Traveler's bank details is
#: surveillance, not finance activity.
ACTIVITY = {
    "payout.hold_opened": "Finance hold opened",
    "payout.hold_cleared": "Finance hold cleared",
    "payout.instruction_confirmed": "Payout instruction confirmed",
    "payout.instruction_amended": "Payout instruction amended",
    "payout.manually_completed": "Payout marked settled by hand",
    "payout.bank_payout_retry": "Bank payout retried",
    "payout.operation_flagged": "Payout flagged for recovery",
    "payout.reconcile_refreshed": "Payout refreshed against the provider",
    "payout.manual_prepared": "Manual payout claimed",
    "payout.manual_begun": "Manual transfer started",
    "payout.manual_released": "Manual transfer released",
    "payout.manual_confirmed": "Manual transfer receipt recorded",
    "payout.manual_settled": "Manual transfer attested as paid",
    "payout_evidence.uploaded": "Payout receipt uploaded",
    "payout_profile.reviewed": "Payout profile reviewed",
    "refund.requested": "Refund requested",
    "refund.manually_settled": "Refund settled by hand",
}

ACTIVITY_EXCLUDED = (
    "payout_evidence.viewed",
    "payout_profile.revealed",
    "payout_account.dashboard_opened",
)

PERIOD_CHOICES = words.PERIODS


# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------


def _url(name):
    return reverse(f"admin_console:{name}")


def _scope_bar(params, scope, *, here, health=None, refine=()):
    """Three controls, not ten.

    Environment and the reference lookup are a form, because both are chosen or
    typed and then applied. The period is four links, because it is the control
    an operator changes most and a round trip through a submit button for it is
    a tax. Custom dates appear only once `custom` has been chosen.

    This is not the ten-control form folded into an accordion. The other seven
    controls are gone from here entirely; `refine` puts the two or three that
    mean something on a given queue next to that queue, and nowhere else.
    """

    period = params.get("period", "30d")
    # A refine control renders its own input, so it must not ALSO ride along as
    # a hidden field: `Scope.parse` refuses a filter submitted twice rather than
    # guessing which value was meant.
    visible = {"mode", "search", "period", "start", "end", *(name for name, *_ in refine)}
    return {
        "mode": params.get("mode", ""),
        "mode_label": words.MODES.get(params.get("mode", ""), "—"),
        "mode_help": words.MODE_HELP.get(params.get("mode", ""), ""),
        "mode_choices": tuple(words.MODES.items()),
        "period": period,
        "periods": [
            {
                "value": item,
                "label": label,
                "url": f"{here}?{_link(params, period=item, page='')}",
                "current": period == item,
            }
            for item, label in PERIOD_CHOICES
        ],
        "custom": period == "custom",
        "start": params.get("start", ""),
        "end": params.get("end", ""),
        "search": params.get("search", ""),
        # Everything the visible controls do not carry, so applying the form
        # never silently drops the tab or the queue filter already in force.
        "hidden": [
            (key, params.get(key, ""))
            for key in PAGE_FIELDS
            if key not in visible and params.get(key)
        ],
        "refine": [
            {
                "name": name,
                "label": label,
                "value": params.get(name, ""),
                "choices": choices,
            }
            for name, label, choices in refine
        ],
        "range_text": _range_text(scope),
        "action": here,
        "reset_url": here,
        "refresh_url": f"{here}?{_link(params)}",
        "health": health,
    }


#: Contextual filters, per queue. Each is a filter H5 already validates, placed
#: where it answers a question the operator is actually asking on that page.
REFINE_PAYOUTS = (
    # The two real methods only. `legacy_unclassified` is an anomaly with no
    # queue of its own, and offering it here would advertise a destination
    # that is empty by design; those rows are investigated from the
    # reconciliation split table instead.
    (
        "rail",
        "Payout method",
        (("", "Any method"), ("stripe_eur", "Stripe EUR"), ("manual_dzd", "Manual DZD")),
    ),
    ("held", "Holds and disputes", words.HELD_CHOICES),
)
REFINE_DZD = (("held", "Holds and disputes", words.HELD_CHOICES),)
REFINE_EXCEPTIONS = (
    ("provider", "Funding provider", (("", "All providers"), *words.PROVIDERS.items())),
)


def _range_text(scope):
    if scope is None:
        return ""
    from datetime import timedelta

    first = scope.start.date()
    last = (scope.end - timedelta(days=1)).date()
    if first == last:
        return first.strftime("%d %b %Y")
    return f"{first.strftime('%d %b %Y')} – {last.strftime('%d %b %Y')}"


def _health(snapshot):
    """The reconciliation verdict as one line, with the table left behind."""

    integrity = snapshot["integrity"]
    status = integrity["status"]
    title, tone, says = HEALTH.get(status, (words.humanise(status), "mute", ""))
    disagreeing = [
        words.COMPARISON_LABELS.get(key) or words.humanise(key)
        for key, row in integrity["comparisons"].items()
        if row["difference_eur_cents"] or row["row_mismatches"]
    ]
    return {
        "status": status,
        "title": title,
        "tone": tone,
        "says": says,
        "ok": status == "ok",
        "serious": status == "mismatch",
        "disagreeing": disagreeing,
        "warnings": [
            words.WARNING_LABELS.get(code) or words.humanise(code)
            for code in integrity["warnings"]
        ],
        "url": _url("finance-reconciliation"),
    }


# ---------------------------------------------------------------------------
# Cohorts
# ---------------------------------------------------------------------------


def _stage_index(snapshot, *, rail=None):
    """`rail_operations` keyed by stage, optionally narrowed to one method."""

    index = {}
    for row in snapshot["rail_operations"]:
        if rail is not None and row["rail"] != rail:
            continue
        index.setdefault(row["operation_stage"], []).append(row)
    return index


def _cohort_rows(index, stages):
    return [row for stage in stages for row in index.get(stage, [])]


def _cohorts(snapshot, specs, *, rail=None, here="", params=None):
    """Cohort tabs: a count badge, and the H5 stages behind it.

    The badge adds counts, which H5's disjoint stages make safe. It never adds
    amounts — where a cohort covers more than one published figure the amount is
    simply absent, and the stages underneath carry their own.
    """

    index = _stage_index(snapshot, rail=rail)
    out = []
    for key, label, blurb, tone, stages in specs:
        rows = _cohort_rows(index, stages)
        singular = rows[0] if len(rows) == 1 else None
        out.append(
            {
                "key": key,
                "label": label,
                "blurb": blurb,
                "tone": tone,
                "count": sum(row["count"] for row in rows),
                # An amount only where exactly one H5 figure backs the cohort.
                "amount": format_eur(singular["amount_eur_cents"]) if singular else "",
                "stages": [
                    {
                        "stage": row["operation_stage"],
                        "label": STAGES.get(row["operation_stage"])
                        or words.humanise(row["operation_stage"]),
                        "help": words.STAGE_HELP.get(row["operation_stage"], ""),
                        "count": row["count"],
                        "amount": format_eur(row["amount_eur_cents"]),
                        "method": METHODS.get(row["rail"]) or words.humanise(row["rail"]),
                        "dzd": _dzd_text(row),
                        "dzd_missing": row.get("dzd_missing_count") or 0,
                    }
                    for row in rows
                ],
                "url": f"{here}?{_link(params or {}, cohort=key, page='')}" if here else "",
            }
        )
    return out


def _dzd_text(row):
    if "amount_dzd" not in row:
        return ""
    amount = row.get("amount_dzd")
    return format_minor_amount(amount, 0, "DZD") if amount is not None else "Partial"


def _pick(cohorts, requested, *, fallback):
    """The selected tab: the one asked for, else the first with work in it."""

    keys = {row["key"] for row in cohorts}
    if requested in keys:
        return requested
    for row in cohorts:
        if row["count"]:
            return row["key"]
    return fallback


# ---------------------------------------------------------------------------
# Queue rows
# ---------------------------------------------------------------------------

#: The one place this module reads a model. Neither column is money.
_OPERATIONAL_COLUMNS = ("id", "eligible_at", "created_at")


def _operational_facts(references):
    """Waiting time for the payouts already on screen.

    H5 publishes the authoritative safe blocker, but not the clock.
    These two columns are operational facts about a
    payout record, of exactly the kind the Payouts console table has always
    rendered, and reading them here changes no figure on any page — no amount,
    count or total below comes from this query.
    """

    identifiers = []
    for reference in references:
        prefix, _, raw = str(reference or "").partition("-")
        if prefix == "PAYOUT" and raw.isdigit():
            identifiers.append(int(raw))
    if not identifiers:
        return {}
    from apps.finance.models import Payout

    rows = Payout.objects.filter(pk__in=identifiers).values(*_OPERATIONAL_COLUMNS)
    return {row["id"]: row for row in rows}


def _age(moment, *, now):
    if not moment:
        return ""
    delta = now - moment
    seconds = int(delta.total_seconds())
    if seconds < 0:
        return "just now"
    if seconds < 3600:
        return f"{max(seconds // 60, 1)} min"
    if seconds < 172800:
        return f"{seconds // 3600} hr"
    return f"{seconds // 86400} days"


def _blocker(code):
    if not code:
        return ""
    from .console_manual_presenter import BLOCK_REASONS

    return BLOCK_REASONS.get(code, (words.humanise(code), ""))[0]


def _queue_rows(params, *, stage, user, limit=50, manual=False, rail=None):
    """One H5 drilldown, rendered as a queue rather than as a ledger extract.

    The drilldown is the authority for every reference and every amount here.
    This adds no column H5 did not return except the two operational facts
    above, and drops the ledger columns an operator working a queue never reads.
    """

    overrides = {"operation": stage}
    if rail:
        overrides["rail"] = rail
    result = drilldown(
        Scope.parse(_scope_only(params, **overrides)),
        metric="payout_operations",
        page=1,
        page_size=limit,
    )
    facts = _operational_facts(row.get("row_reference") for row in result["rows"])
    may_open = has_admin_permission(user, "view_payouts")
    now = timezone.now()
    rows = []
    for raw in result["rows"]:
        prefix, _, identifier = str(raw.get("row_reference") or "").partition("-")
        pk = int(identifier) if prefix == "PAYOUT" and identifier.isdigit() else None
        fact = facts.get(pk, {})
        markers = []
        if raw.get("has_hold"):
            markers.append(("Hold", "attn"))
        if raw.get("has_user_dispute"):
            markers.append(("ShipTrip dispute", "bad"))
        if raw.get("has_provider_dispute"):
            markers.append(("Provider dispute", "bad"))
        rows.append(
            {
                "payout": raw.get("payout_reference") or "—",
                "deal": raw.get("deal_reference") or "—",
                "traveler": raw.get("traveler_reference") or "—",
                "eur": format_eur(raw["amount_eur_cents"])
                if raw.get("amount_eur_cents") is not None
                else "Not available",
                "dzd": format_minor_amount(
                    raw["payout_amount_minor"],
                    raw.get("payout_amount_exponent") or 0,
                    raw.get("payout_currency") or "",
                )
                if manual and raw.get("payout_amount_minor") is not None
                else "",
                "method": METHODS.get(raw.get("rail")) or words.humanise(raw.get("rail")),
                "stage": STAGES.get(raw.get("operation_stage"))
                or words.humanise(raw.get("operation_stage")),
                "age": _age(fact.get("eligible_at") or fact.get("created_at"), now=now),
                "blocker": _blocker(raw.get("block_reason")),
                "markers": markers,
                "url": reverse("admin_console:payout-detail", args=[pk])
                if pk and may_open
                else "",
            }
        )
    return {
        "rows": rows,
        "more": result["has_next"],
        "totals": value(result["totals"], "payout_operations"),
    }


# ---------------------------------------------------------------------------
# Recent activity
# ---------------------------------------------------------------------------


def _drilldown_url(params, *, stage, rail=None):
    """The H5 drilldown for one stage — the ledger view of the same rows.

    A queue shows the first fifty and says so. Everything beyond that, and every
    column a reconciler needs and an operator does not, stays on the drilldown
    the control plane already publishes.
    """

    overrides = {"metric": "payout_operations", "operation": stage}
    if rail:
        overrides["rail"] = rail
    return f"{_url('finance-rows')}?{_scope_only(params, **overrides).urlencode()}"


def _activity(limit=6):
    """The last few finance actions, from the console's own immutable log.

    If the log cannot be read the feed is omitted rather than faked; it is
    context, and no page depends on it.
    """

    try:
        from .models import AdminAuditLog

        entries = list(
            AdminAuditLog.objects.filter(action__in=tuple(ACTIVITY))
            .exclude(action__in=ACTIVITY_EXCLUDED)
            .select_related("actor")
            .order_by("-created_at")[:limit]
        )
    except Exception:  # pragma: no cover - the feed must never break a page
        return []
    now = timezone.now()
    return [
        {
            "label": ACTIVITY.get(entry.action) or words.humanise(entry.action),
            "reference": entry.reference or "",
            "actor": getattr(entry.actor, "email", "") or "System",
            "age": _age(entry.created_at, now=now),
        }
        for entry in entries
    ]


# ---------------------------------------------------------------------------
# View models
# ---------------------------------------------------------------------------


def build_overview(snapshot, params, scope, *, user):
    """Five zones. Nothing on this page can move money."""

    metrics = snapshot["metrics"]
    index = _stage_index(snapshot)
    payouts_url = _url("finance-payouts")
    exceptions_url = _url("finance-exceptions")

    attention = []
    for spec in ATTENTION:
        if "metric" in spec:
            entry = metrics.get(spec["metric"])
            if entry is None:
                continue
            count = entry.get("count") or 0
            reading = value(entry, spec["metric"])
            amount = reading["text"] if reading["available"] else ""
        else:
            rows = index.get(spec["stage"], [])
            count = sum(row["count"] for row in rows)
            # Spans both payout methods, so H5 published no single amount for
            # it and this row deliberately carries none.
            amount = ""
        if not count:
            continue
        target = exceptions_url if spec.get("exceptions") else payouts_url
        attention.append(
            {
                **spec,
                "count": count,
                "amount": amount,
                "url": f"{target}?{_link(params, cohort=spec.get('cohort', ''), page='')}",
            }
        )

    dzd = _cohorts(snapshot, DZD_COHORTS, rail="manual_dzd")
    stripe = _cohorts(snapshot, PAYOUT_COHORTS, rail="stripe_eur")
    # Blocked, held and disputed dinar payouts are in none of the four queue
    # cohorts. Without this the lane reads 0 / 0 / 0 while a transfer is stuck,
    # which is the most misleading thing this page could say.
    dzd_stuck = sum(
        row["count"] for row in _cohort_rows(_stage_index(snapshot, rail="manual_dzd"), ATTENTION_STAGES)
    )
    return {
        "attention": attention,
        "attention_total": sum(row["count"] for row in attention),
        "dzd": {
            "cohorts": dzd,
            "waiting": next((row for row in dzd if row["key"] == "waiting"), None),
            "total": sum(row["count"] for row in dzd),
            "stuck": dzd_stuck,
            "url": _url("finance-dzd"),
        },
        "stripe": {
            "moving": next((row for row in stripe if row["key"] == "moving"), None),
            "attention": next((row for row in stripe if row["key"] == "attention"), None),
            "ready": next((row for row in stripe if row["key"] == "ready"), None),
            "total": sum(row["count"] for row in stripe),
            "url": f"{payouts_url}?{_link(params, cohort='moving', page='')}",
        },
        "headline": [
            {
                "key": key,
                "label": label,
                "says": says,
                "value": value(metrics[key], key),
            }
            for key, label, says in HEADLINE
            if key in metrics
        ],
        "activity": _activity(),
        "payouts_url": payouts_url,
        "exceptions_url": exceptions_url,
        "reconciliation_url": _url("finance-reconciliation"),
    }


def build_payouts(snapshot, params, scope, *, user, requested):
    here = _url("finance-payouts")
    cohorts = _cohorts(snapshot, PAYOUT_COHORTS, here=here, params=params)
    selected = _pick(cohorts, requested, fallback="attention")
    current = next(row for row in cohorts if row["key"] == selected)
    groups = [
        {
            **stage,
            "rows_url": _drilldown_url(params, stage=stage["stage"]),
            "queue": _queue_rows(params, stage=stage["stage"], user=user),
        }
        for stage in current["stages"]
    ]
    return {
        "cohorts": cohorts,
        "selected": selected,
        "current": current,
        "groups": groups,
        "here": here,
        "dzd_url": _url("finance-dzd"),
        "accounts_url": reverse("admin_console:payout-accounts"),
        "legacy_url": reverse("admin_console:payouts"),
    }


def build_dzd(snapshot, params, scope, *, user, requested):
    here = _url("finance-dzd")
    cohorts = _cohorts(snapshot, DZD_COHORTS, rail="manual_dzd", here=here, params=params)
    selected = _pick(cohorts, requested, fallback="waiting")
    current = next(row for row in cohorts if row["key"] == selected)
    groups = [
        {
            **stage,
            "rows_url": _drilldown_url(params, stage=stage["stage"], rail="manual_dzd"),
            "queue": _queue_rows(
                params,
                stage=stage["stage"],
                user=user,
                manual=True,
                rail="manual_dzd",
            ),
        }
        for stage in current["stages"]
    ]
    # Blocked, held and disputed dinar payouts are not one of the four queue
    # cohorts and must not be quietly missing from the page either.
    index = _stage_index(snapshot, rail="manual_dzd")
    stuck = _cohort_rows(index, ATTENTION_STAGES)
    return {
        "cohorts": cohorts,
        "selected": selected,
        "current": current,
        "groups": groups,
        "here": here,
        "stuck": sum(row["count"] for row in stuck),
        "stuck_url": f"{_url('finance-payouts')}?{_link(params, cohort='attention', rail='manual_dzd', page='')}",
        "execution_enabled": settings.PAYOUT_DZD_EXECUTION_ENABLED,
    }


def build_exceptions(snapshot, params, scope, *, user):
    """Refunds, holds and disputes, each naming who acts next."""

    metrics = snapshot["metrics"]

    def read(key):
        entry = metrics.get(key)
        return value(entry, key) if entry is not None else None

    refunds = [
        {
            "key": key,
            "label": label,
            "says": says,
            "owner": owner,
            "tone": tone,
            "value": read(key),
        }
        for key, label, says, owner, tone in (
            (
                "refunds_failed",
                "Failed to execute",
                "The refund could not be sent and entitlement is unresolved.",
                "Finance",
                "bad",
            ),
            (
                "refunds_requested",
                "Requested",
                "Raised and not yet sent to the provider.",
                "Finance",
                "attn",
            ),
            (
                "refunds_processing",
                "Processing",
                "With the provider. Nobody is blocked.",
                "Provider",
                "",
            ),
            (
                "refunds_finalized",
                "Finalised in this period",
                "Complete. Shown as history, not as work.",
                "—",
                "ok",
            ),
        )
        # Zero is not an exception. A lifecycle stage with nothing in it is
        # filed as silence, not as a card that has to be read every morning.
        if (read(key) or {}).get("count")
    ]
    blocks = [
        {
            "key": key,
            "label": label,
            "says": says,
            "owner": owner,
            "tone": tone,
            "url": url,
            "value": read(key),
        }
        for key, label, says, owner, tone, url in (
            (
                "held_payouts",
                "Finance hold",
                "Finance froze the payout deliberately. It stays frozen until Finance clears it.",
                "Finance",
                "attn",
                f"{_url('finance-payouts')}?{_link(params, held='true', cohort='attention', page='')}",
            ),
            (
                "user_disputed_payouts",
                "ShipTrip dispute",
                "A dispute inside ShipTrip freezes the payout. Support or Ops owns the outcome.",
                "Support / Ops",
                "attn",
                reverse("admin_console:disputes"),
            ),
            (
                "provider_disputed_payouts",
                "Provider dispute",
                "Raised at the card network against the money that funded the Deal.",
                "Finance / Risk",
                "attn",
                f"{_url('finance-payouts')}?{_link(params, held='disputed', page='')}",
            ),
        )
        if (read(key) or {}).get("count")
    ]
    recover = read("provider_disputes")
    return {
        "refunds": refunds,
        "blocks": blocks,
        "blocks_open": any(row["value"]["count"] for row in blocks),
        "recover": recover,
        "refunds_url": reverse("admin_console:refunds"),
        "disputes_url": reverse("admin_console:disputes"),
        "payments_url": reverse("admin_console:payments"),
    }


def build_reconciliation(snapshot, params, scope):
    """H5.1's audit surface, intact.

    Nothing was weakened to move it here. Every comparison, every difference,
    every mismatched-row count, ledger conservation, the data issues, the
    warnings, the provenance and the metric dictionary are all still on this
    page; they have simply stopped competing with a work queue for the same
    screen. The register stays technical because the reader is a Finance lead,
    a CFO, an auditor, or an engineer in the middle of an investigation.
    """

    integrity = snapshot["integrity"]
    title, tone, summary = words.INTEGRITY_STATES.get(
        integrity["status"], (words.humanise(integrity["status"]), "mute", "")
    )
    comparisons = [
        {
            "key": key,
            "label": words.COMPARISON_LABELS.get(key) or words.humanise(key),
            "help": words.COMPARISON_HELP.get(key, ""),
            "reported": format_eur(row["reported_eur_cents"]),
            "authority": format_eur(row["authority_eur_cents"]),
            "difference": format_eur(row["difference_eur_cents"]),
            "row_mismatches": row["row_mismatches"],
            "agrees": not row["difference_eur_cents"] and not row["row_mismatches"],
        }
        for key, row in integrity["comparisons"].items()
    ]
    providers = []
    for provider, block in snapshot["providers"].items():
        balance = block.get("balance") or {}
        providers.append(
            {
                "provider": provider,
                "label": words.PROVIDERS.get(provider) or words.humanise(provider),
                "metrics": [
                    {"label": label, "value": value(block[key], key)}
                    for key, label in (
                        ("gross_funded", "Funded through this provider"),
                        ("refunds_outstanding", "Refunds outstanding"),
                        ("refunds_finalized", "Refunds finalised in this period"),
                        ("source_reserved", "Funding reserved against payouts"),
                    )
                    if key in block
                ],
                "balance_available": balance.get("status") == "available",
                "balance_text": (
                    format_eur(balance.get("amount"))
                    if balance.get("status") == "available"
                    else "Provider-reported balance unavailable"
                ),
            }
        )
    provider_costs = snapshot.get("provider_costs") or {}
    categories = snapshot.get("revenue_categories") or {}
    metrics = snapshot["metrics"]
    buckets = [
        {
            "bucket": bucket,
            "label": words.LIABILITY_LABELS.get(bucket) or words.humanise(bucket),
            "help": words.LIABILITY_HELP.get(bucket, ""),
            "value": value(metrics[f"liability_{bucket}"], f"liability_{bucket}"),
            "tone": "bad" if bucket == "inconsistent" else "",
        }
        for bucket in words.LIABILITY_ORDER
        if f"liability_{bucket}" in metrics
    ]
    split = [
        {
            "rail": words.RAILS.get(row["rail"]) or words.humanise(row["rail"]),
            "bucket": words.LIABILITY_LABELS.get(row["bucket"]) or words.humanise(row["bucket"]),
            "funding": words.FUNDING_MIX.get(row["funding_mix"]) or words.humanise(row["funding_mix"]),
            "is_manual": row["rail"] == "manual_dzd",
            "value": value(row, "traveler_outstanding"),
        }
        for row in snapshot["payouts"]
    ]
    return {
        "verdict": {
            "status": integrity["status"],
            "title": title,
            "tone": tone,
            "summary": summary,
        },
        "comparisons": comparisons,
        "unbalanced": integrity["unbalanced_transaction_count"],
        "warnings": [
            words.WARNING_LABELS.get(code) or words.humanise(code)
            for code in integrity["warnings"]
        ],
        "data_issues": [
            {"label": words.DATA_ISSUE_LABELS.get(key) or words.humanise(key), "count": count}
            for key, count in integrity["data_issues"].items()
            if count
        ],
        "attributed_legacy_entries": integrity.get("source_attributed_legacy_entry_count", 0),
        "provenance": [
            {"label": words.humanise(key), **row}
            for key, row in (integrity.get("provenance") or {}).items()
        ],
        "revenue_basis": words.humanise(integrity.get("revenue_basis", "")),
        "provider_cash": words.humanise(integrity.get("provider_cash_reconciliation", "")),
        "buckets": buckets,
        "split": split,
        "providers": providers,
        "provider_costs_available": provider_costs.get("status") == "available",
        "provider_costs_text": (
            format_eur(provider_costs.get("amount_eur_cents"))
            if provider_costs.get("status") == "available"
            else "Not available"
        ),
        "revenue_categories_available": categories.get("status") == "available",
        "revenue_categories_reason": categories.get("reason", ""),
        "definitions": sorted(
            ({"key": key, "label": row["name"], **row} for key, row in snapshot["definitions"].items()),
            key=lambda row: row["label"],
        ),
        "snapshot": {
            "as_of": _read_at(snapshot["as_of"]),
            "version": snapshot["definition_version"],
            "timezone": snapshot["reporting_timezone"],
            "balance_basis": snapshot["balance_basis"],
            "provider_semantics": snapshot["provider_filter_semantics"],
            "limitations": snapshot["limitations"],
        },
    }


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

def _page(request, template, *, title, eyebrow, current, build, refine=(), status_on_error=400):
    """One bounded snapshot per view, and one shape for every failure."""

    _guard(request)
    params = scope_params(request)
    base = {
        "title": title,
        "eyebrow": eyebrow,
        "scope": _scope_bar(params, None, here=_url(current), refine=refine),
    }
    try:
        scope = Scope.parse(_scope_only(params))
    except ValidationError as exc:
        return _render(request, template, {**base, "errors": list(exc.messages)}, status=status_on_error)
    try:
        snapshot = build_snapshot(scope)
    except OperationalError:
        return _render(
            request,
            template,
            {**base, "scope": _scope_bar(params, scope, here=_url(current), refine=refine), "unavailable": True},
            status=503,
        )
    health = _health(snapshot)
    return _render(
        request,
        template,
        {
            **base,
            "scope": _scope_bar(params, scope, here=_url(current), health=health, refine=refine),
            "health": health,
            "in_legacy_mode": scope.mode == "legacy_unknown",
            "legacy_url": f"{_url(current)}?{_link(params, mode='legacy_unknown')}",
            "as_of": _read_at(snapshot["as_of"]),
            **build(snapshot, params, scope),
        },
    )


@never_cache
@staff_member_required
@require_GET
def finance_overview(request):
    return _page(
        request,
        "admin/console/finance_overview.html",
        title="Finance",
        eyebrow="Finance · operations",
        current="finance-dashboard",
        build=lambda snapshot, params, scope: build_overview(
            snapshot, params, scope, user=request.user
        ),
    )


@never_cache
@staff_member_required
@require_GET
def finance_payouts(request):
    requested = request.GET.get("cohort", "")
    return _page(
        request,
        "admin/console/finance_payouts.html",
        title="Payouts",
        eyebrow="Finance · payout operations",
        current="finance-payouts",
        refine=REFINE_PAYOUTS,
        build=lambda snapshot, params, scope: build_payouts(
            snapshot, params, scope, user=request.user, requested=requested
        ),
    )


@never_cache
@staff_member_required
@require_GET
def finance_dzd(request):
    requested = request.GET.get("cohort", "")
    return _page(
        request,
        "admin/console/finance_dzd.html",
        title="Manual DZD payouts",
        eyebrow="Finance · manual dinar queue",
        current="finance-dzd",
        refine=REFINE_DZD,
        build=lambda snapshot, params, scope: build_dzd(
            snapshot, params, scope, user=request.user, requested=requested
        ),
    )


@never_cache
@staff_member_required
@require_GET
def finance_exceptions(request):
    return _page(
        request,
        "admin/console/finance_exceptions.html",
        title="Refunds & disputes",
        eyebrow="Finance · exceptions",
        current="finance-exceptions",
        refine=REFINE_EXCEPTIONS,
        build=lambda snapshot, params, scope: build_exceptions(
            snapshot, params, scope, user=request.user
        ),
    )


@never_cache
@staff_member_required
@require_GET
def finance_reconciliation(request):
    return _page(
        request,
        "admin/console/finance_reconciliation.html",
        title="Reconciliation",
        eyebrow="Finance · audit",
        current="finance-reconciliation",
        build=build_reconciliation,
    )
