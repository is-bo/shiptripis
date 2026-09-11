"""The Finance control-plane dashboard (H5.1): presentation over H5, only.

Everything on these two pages is a rendering of what
`apps.finance.control_plane` returned. This module chooses which of H5's values
to show, what to call them in an operator's words, and where a value can be
opened into the rows behind it. It does not add, subtract, convert, estimate or
re-derive a single amount — H5 stays the financial authority, and a total that
H5 does not publish does not appear here.

Three rules hold the boundary:

* **No arithmetic on money.** The only numeric work below is formatting integer
  cents and frozen minor units for display.
* **Null is not zero.** H5 deliberately returns `None`/`partial` where a value
  is unknown. That distinction survives into the page as *Not available* or
  *Partial*, never as `€0.00`.
* **Read-only.** Both views are GET-only and neither reaches any service that
  can move money. Acting on a payout stays on H3/H4's own audited screens,
  which the drilldown links to.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import OperationalError
from django.http import Http404
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from apps.admin_panel import finance_dashboard_labels as words
from apps.core.admin_display import format_eur
from apps.finance.control_plane.drilldown import drilldown
from apps.finance.control_plane.filters import Scope
from apps.finance.control_plane.snapshot import build_snapshot
from apps.finance.models import Payout

from .console_presenters import decimal_micros, format_minor_amount
from .permissions import has_admin_permission, has_all_admin_permissions

#: Every filter H5's `Scope` accepts for a page request. `metric`, `page` and
#: `page_size` belong to the drilldown and are added there.
SCOPE_FIELDS = (
    "mode",
    "period",
    "start",
    "end",
    "provider",
    "rail",
    "state",
    "held",
    "currency",
    "operation",
    "search",
)

#: The two readings of H5's `time_basis`. A period figure is a flow inside the
#: selected range; a current figure is a balance as at the snapshot, and H5
#: states plainly that the period selector does not touch those. H5's own
#: `time_basis` string stays authoritative and is printed in full in the metric
#: dictionary; it names database columns, which is the wrong register for a
#: tile, so a tile carries this two-way reading of it instead.
PERIOD = "period"
CURRENT = "current"
BASIS_LABELS = {
    PERIOD: "In the selected period",
    CURRENT: "Current balance, whatever period is selected",
}

#: Metrics H5 exposes as a contributing-row query. `net_funded` is absent on
#: purpose: H5 composes it from two components and drills through those.
_NON_DRILLABLE = frozenset({"net_funded"})

_DRILLDOWN_COLUMN_ORDER = (
    "payout_reference",
    "deal_reference",
    "traveler_reference",
    "order_reference",
    "source_attempt_order_reference",
    "row_reference",
    "amount_eur_cents",
    "settlement",
    "status",
    "bucket",
    "operation_stage",
    "rail",
    "funding_mix",
    "account",
    "transaction_kind",
    "provider",
    "purpose",
    "markers",
    "connected",
    "transit",
    "attempt_succeeded_at",
    "succeeded_at",
    "settlement_at",
    "recognition_at",
    "effective_at",
    "transaction_created_at",
    "fx_rate_micros",
    "fx_snapshot_at",
)

_NUMERIC_FIELDS = frozenset({"amount_eur_cents", "connected", "transit", "settlement"})

_TIME_FIELDS = frozenset(
    {
        "attempt_succeeded_at",
        "succeeded_at",
        "settlement_at",
        "recognition_at",
        "effective_at",
        "transaction_created_at",
        "fx_snapshot_at",
    }
)

_ENUM_FIELDS = {
    "bucket": words.LIABILITY_LABELS,
    "operation_stage": words.STAGE_LABELS,
    "rail": words.RAILS,
    "funding_mix": words.FUNDING_MIX,
    "account": words.LEDGER_ACCOUNTS,
    "transaction_kind": words.TRANSACTION_KINDS,
    "provider": words.PROVIDERS,
    "purpose": words.PURPOSES,
}


# ---------------------------------------------------------------------------
# Values
# ---------------------------------------------------------------------------


def _plural(count, metric):
    singular, plural = words.COUNT_NOUNS.get(metric, ("", ""))
    if count is None or not singular:
        return ""
    return f"{count:,} {singular if count == 1 else plural}"


def value(entry, metric=""):
    """One H5 `{count, amount_eur_cents, status}` result, ready to render.

    `amount_eur_cents is None` is H5 saying it does not know the total, which
    is a different statement from knowing it to be zero. Both survive.
    """

    entry = entry or {}
    amount = entry.get("amount_eur_cents")
    status = entry.get("status", "available")
    known = entry.get("known_amount_eur_cents")
    result = {
        "text": format_eur(amount) if amount is not None else "",
        "available": amount is not None,
        "partial": status == "partial",
        "count": entry.get("count"),
        "count_text": _plural(entry.get("count"), metric),
        "known_text": "",
        "dzd_text": "",
        "dzd_missing": entry.get("dzd_missing_count") or 0,
    }
    if amount is None:
        result["text"] = "Partial" if status == "partial" else "Not available"
    if known is not None:
        result["known_text"] = f"Known so far: {format_eur(known)}"
    if "amount_dzd" in entry:
        dzd_amount = entry.get("amount_dzd")
        result["dzd_text"] = (
            format_minor_amount(dzd_amount, 0, "DZD")
            if dzd_amount is not None
            else "Partial"
        )
    return result


@dataclass(frozen=True)
class Kpi:
    """One H5 metric as it appears on the page."""

    metric: str
    label: str
    #: A short line the KPI cannot be read correctly without. H5's own
    #: definition sentence is rendered underneath it.
    note: str = ""
    #: Whether the figure moves with the period selector. See `BASIS_LABELS`.
    basis: str = PERIOD
    lead: bool = False
    tone: str = ""


def _kpi(snapshot, spec, links):
    metrics = snapshot["metrics"]
    if spec.metric not in metrics:
        return None
    definition = snapshot["definitions"].get(spec.metric) or {}
    return {
        "key": spec.metric,
        "label": spec.label,
        "note": spec.note,
        "definition": definition.get("definition", ""),
        "time_basis": definition.get("time_basis", ""),
        "basis": BASIS_LABELS[spec.basis],
        "value": value(metrics[spec.metric], spec.metric),
        "url": links(spec.metric) if spec.metric not in _NON_DRILLABLE else "",
        "lead": spec.lead,
        "tone": spec.tone,
    }


def _group(snapshot, specs, links):
    return [row for row in (_kpi(snapshot, spec, links) for spec in specs) if row]


# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------


def default_mode():
    """The environment's own provider mode, so the page never guesses TEST.

    H5 requires an explicit mode and offers no default, because reporting the
    wrong environment's money is worse than refusing. The configured
    credentials already answer the question; if they do not, the page opens on
    the sandbox rather than on a claim about real money.
    """

    try:
        from apps.finance.policy import phase3_policy
        from apps.finance.providers import (
            MODE_LIVE,
            MODE_TEST,
            PaymentProvider,
            available_providers,
        )

        modes = {
            row.credential_mode
            for row in available_providers(phase3_policy())
            if row.provider in (PaymentProvider.STRIPE, PaymentProvider.CHARGILY)
        }
        if MODE_LIVE in modes:
            return "live"
        if MODE_TEST in modes:
            return "test"
    except Exception:  # pragma: no cover - configuration probing must not 500
        pass
    return "test"


def scope_params(request, **overrides):
    """The request's H5 filters, with a mode and this page's own defaults."""

    # Unknown keys are deliberately left in place: `Scope.parse` refuses them
    # and the operator is told, rather than being shown a different question's
    # answer under the filters they thought they had set.
    params = request.GET.copy()
    if not params.get("mode"):
        params["mode"] = default_mode()
    if not params.get("period"):
        params["period"] = "30d"
    for key, replacement in overrides.items():
        params[key] = replacement
    return params


def _query(params, **overrides):
    values = {
        key: params.get(key, "")
        for key in (*SCOPE_FIELDS, "metric", "page", "page_size")
    }
    values.update(overrides)
    return urlencode({key: item for key, item in values.items() if item})


def _link_factory(params):
    rows = reverse("admin_console:finance-rows")

    def link(metric, **overrides):
        if metric in _NON_DRILLABLE:
            return ""
        return f"{rows}?{_query(params, metric=metric, page='', **overrides)}"

    return link


def _filter_state(params, scope):
    """The filter form's current selection, in words rather than in enums."""

    applied = []
    for key, labels in (
        ("provider", words.PROVIDERS),
        ("rail", words.RAILS),
        ("currency", {"EUR": "Settled in EUR", "DZD": "Settled in DZD"}),
        ("operation", words.STAGE_LABELS),
    ):
        selected = params.get(key, "")
        if selected:
            applied.append(labels.get(selected) or words.humanise(selected))
    if params.get("state"):
        applied.append(
            dict(Payout.Status.choices).get(params["state"])
            or words.humanise(params["state"])
        )
    if params.get("held"):
        applied.append(dict(words.HELD_CHOICES).get(params["held"], ""))
    if params.get("search"):
        applied.append(f"reference {params['search']}")
    return {
        "mode": params.get("mode", ""),
        "mode_label": words.MODES.get(params.get("mode", ""), "—"),
        "mode_help": words.MODE_HELP.get(params.get("mode", ""), ""),
        "period": params.get("period", "30d"),
        "start": params.get("start", ""),
        "end": params.get("end", ""),
        "provider": params.get("provider", ""),
        "rail": params.get("rail", ""),
        "state": params.get("state", ""),
        "held": params.get("held", ""),
        "currency": params.get("currency", ""),
        "operation": params.get("operation", ""),
        "search": params.get("search", ""),
        "applied": applied,
        "range_text": _range_text(scope),
        "mode_choices": tuple(words.MODES.items()),
        "period_choices": words.PERIODS,
        "provider_choices": (("", "All providers"), *words.PROVIDERS.items()),
        "rail_choices": (("", "All rails"), *words.RAILS.items()),
        "state_choices": (("", "All payout states"), *Payout.Status.choices),
        "held_choices": words.HELD_CHOICES,
        "currency_choices": (("", "Any currency"), ("EUR", "EUR"), ("DZD", "DZD")),
        "operation_choices": (("", "All stages"), *_operation_choices()),
    }


def _operation_choices():
    from apps.finance.control_plane.definitions import OPERATION_STAGES

    seen, rows = set(), []
    ordered = (*words.STRIPE_STAGE_ORDER, *words.MANUAL_STAGE_ORDER, *OPERATION_STAGES)
    for stage in ordered:
        if stage in seen or stage not in OPERATION_STAGES:
            continue
        seen.add(stage)
        rows.append((stage, words.STAGE_LABELS.get(stage) or words.humanise(stage)))
    return tuple(rows)


def _range_text(scope):
    if scope is None:
        return ""
    # `Scope` stores a half-open range; the last included day is the day before
    # its exclusive end, which is the day an operator actually selected.
    from datetime import timedelta

    first = scope.start.date()
    last = (scope.end - timedelta(days=1)).date()
    if first == last:
        return first.strftime("%d %b %Y")
    return f"{first.strftime('%d %b %Y')} – {last.strftime('%d %b %Y')}"


# ---------------------------------------------------------------------------
# Snapshot view model
# ---------------------------------------------------------------------------

FUNDED = (
    Kpi(
        "gross_funded",
        "Gross funded volume",
        note="Money processed through ShipTrip. This is not ShipTrip's income.",
        lead=True,
    ),
    Kpi(
        "net_funded",
        "Net funded volume",
        note="Gross funded, less refunds finalised in this period.",
    ),
    Kpi("deposits_collected", "Posting deposits collected"),
    Kpi("boost_funded", "Boost funded"),
)

EARNINGS = (
    Kpi(
        "recognized_revenue",
        "Recognised ShipTrip revenue",
        note="What ShipTrip has actually earned in this period.",
        lead=True,
    ),
    Kpi(
        "pending_earnings",
        "Pending platform earnings",
        note="Allocated to ShipTrip, with no final earning evidence yet.",
        basis=CURRENT,
    ),
)

OBLIGATIONS = (
    Kpi(
        "traveler_outstanding",
        "Outstanding Traveler liability",
        note="Owed to Travelers right now. Never ShipTrip income.",
        basis=CURRENT,
        lead=True,
        tone="attn",
    ),
    Kpi(
        "payouts_settled",
        "Paid to Travelers",
        note="Historical flow in this period. Not part of the outstanding total above.",
    ),
    Kpi("payout_returns", "Payouts returned by the bank"),
)

LOCATION = (
    Kpi(
        "connected_funds",
        "At connected accounts",
        note="ShipTrip's euros sitting at Travelers' connected accounts. Not yet paid out.",
        basis=CURRENT,
    ),
    Kpi(
        "bank_in_transit",
        "Bank payout in transit",
        note="Left the connected balance, outcome not yet known.",
        basis=CURRENT,
    ),
    Kpi(
        "externally_committed",
        "Externally committed",
        note="Overlaps the buckets above. Never added to the liability total.",
        basis=CURRENT,
    ),
    Kpi("source_reserved", "Source funding reserved", basis=CURRENT),
)

REFUNDS = (
    Kpi(
        "refunds_outstanding",
        "Outstanding refunds",
        note="Pending and processing together. Money ShipTrip still owes back.",
        basis=CURRENT,
        lead=True,
        tone="attn",
    ),
    Kpi("refunds_requested", "Requested", basis=CURRENT),
    Kpi("refunds_processing", "Processing", basis=CURRENT),
    Kpi("refunds_finalized", "Finalised in this period"),
    Kpi(
        "refunds_applied",
        "Finalised against applied funding",
        note="The only refunds subtracted from funded volume, and subtracted once.",
    ),
    Kpi(
        "refunds_failed",
        "Failed execution",
        note="Entitlement unresolved. A person has to decide these.",
        basis=CURRENT,
        tone="attn",
    ),
    Kpi(
        "deposits_refunded",
        "Posting deposits refunded",
        note="The posting-deposit share of the finalised refunds above, not an extra amount.",
    ),
)

RISK = (
    Kpi(
        "user_disputed_payouts",
        "Payouts frozen by a ShipTrip dispute",
        note="Opened inside ShipTrip. Payout is frozen while it is open.",
        basis=CURRENT,
        lead=True,
    ),
    Kpi("held_payouts", "Payouts under a Finance hold", basis=CURRENT),
    Kpi(
        "provider_disputed_payouts",
        "Payouts touched by a provider dispute",
        note="Raised at the card network, against the money that funded the Deal.",
        basis=CURRENT,
    ),
    Kpi(
        "provider_disputes",
        "Provider disputes to recover",
        note="Canonical amount only where it is known. Unknown stays unknown.",
        basis=CURRENT,
        tone="attn",
    ),
)

DEPOSITS = (
    Kpi(
        "deposits_held",
        "Deposits still held",
        note="Collected from Senders and not yet credited, refunded or forfeited.",
        basis=CURRENT,
    ),
    Kpi(
        "deposits_credited",
        "Deposits credited into Deals",
        note="A deposit moving into its Deal. No new money arrives here.",
    ),
)

#: The three amounts the page exists to keep apart. Money that moved through
#: ShipTrip, money ShipTrip earned, and money ShipTrip owes are routinely read
#: as one figure; naming all three at the top, in words, is the cheapest place
#: to stop that.
HEADLINE = (
    (
        "gross_funded",
        "Money processed",
        "Funded through ShipTrip in this period, before refunds. This is volume, not income.",
        False,
    ),
    (
        "recognized_revenue",
        "ShipTrip earned",
        "Platform revenue recognised in this period, against final earning evidence.",
        True,
    ),
    (
        "traveler_outstanding",
        "Owed to Travelers",
        "Outstanding right now, across every state. This money is never ShipTrip's.",
        False,
    ),
)


def _headline(snapshot, links):
    metrics = snapshot["metrics"]
    return [
        {
            "key": key,
            "label": label,
            "says": says,
            "lead": lead,
            "value": value(metrics[key], key),
            "url": links(key),
        }
        for key, label, says, lead in HEADLINE
        if key in metrics
    ]


def _rail_sections(snapshot, links):
    """`rail_operations`, one section per rail, in lifecycle order."""

    orders = {
        "stripe_eur": words.STRIPE_STAGE_ORDER,
        "manual_dzd": words.MANUAL_STAGE_ORDER,
    }
    grouped = {}
    for row in snapshot["rail_operations"]:
        grouped.setdefault(row["rail"], []).append(row)
    sections = [
        _rail_section(rail, grouped.pop(rail, []), orders[rail], links)
        for rail in ("stripe_eur", "manual_dzd")
    ]
    # An unclassified or unrecognised rail is an anomaly, not a queue: it is
    # shown when it holds something and stays out of the way when it does not.
    sections.extend(
        _rail_section(rail, rows, (), links)
        for rail, rows in grouped.items()
        if rows
    )
    return sections


def _rail_section(rail, rows, order, links):
    ranking = {stage: index for index, stage in enumerate(order)}
    rows = sorted(rows, key=lambda row: ranking.get(row["operation_stage"], len(order)))
    return {
        "rail": rail,
        "label": words.RAILS.get(rail) or words.humanise(rail),
        "help": words.RAIL_HELP.get(rail, ""),
        "is_manual": rail == "manual_dzd",
        "stages": [
            {
                "stage": row["operation_stage"],
                "label": words.STAGE_LABELS.get(row["operation_stage"])
                or words.humanise(row["operation_stage"]),
                "help": words.STAGE_HELP.get(row["operation_stage"], ""),
                "value": value(row, "payout_operations"),
                "url": links(
                    "payout_operations",
                    rail=rail,
                    operation=row["operation_stage"],
                ),
            }
            for row in rows
        ],
    }


def _liability_buckets(snapshot, links):
    metrics = snapshot["metrics"]
    rows = []
    for bucket in words.LIABILITY_ORDER:
        key = f"liability_{bucket}"
        if key not in metrics:
            continue
        rows.append(
            {
                "bucket": bucket,
                "label": words.LIABILITY_LABELS.get(bucket) or words.humanise(bucket),
                "help": words.LIABILITY_HELP.get(bucket, ""),
                "value": value(metrics[key], key),
                "url": links(key),
                "tone": "bad" if bucket == "inconsistent" else "",
            }
        )
    return rows


def _liability_split(snapshot):
    """`payouts`: the same outstanding payable, by rail and funding source."""

    return [
        {
            "rail": words.RAILS.get(row["rail"]) or words.humanise(row["rail"]),
            "bucket": words.LIABILITY_LABELS.get(row["bucket"])
            or words.humanise(row["bucket"]),
            "funding": words.FUNDING_MIX.get(row["funding_mix"])
            or words.humanise(row["funding_mix"]),
            "is_manual": row["rail"] == "manual_dzd",
            "value": value(row, "traveler_outstanding"),
        }
        for row in snapshot["payouts"]
    ]


def _providers(snapshot, params):
    dashboard = reverse("admin_console:finance-dashboard")
    rows = []
    for provider, block in snapshot["providers"].items():
        balance = block.get("balance") or {}
        rows.append(
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
                # H5 makes no provider balance request and asserts no wallet
                # figure. Rendering "€0" here would be a material lie.
                "balance_available": balance.get("status") == "available",
                "balance_text": (
                    format_eur(balance.get("amount"))
                    if balance.get("status") == "available"
                    else "Provider-reported balance unavailable"
                ),
                "scope_url": f"{dashboard}?{_query(params, provider=provider)}",
            }
        )
    return rows


def _integrity(snapshot):
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
    issues = [
        {"label": words.DATA_ISSUE_LABELS.get(key) or words.humanise(key), "count": count}
        for key, count in integrity["data_issues"].items()
        if count
    ]
    provenance = [
        {"label": words.humanise(key), **row}
        for key, row in (integrity.get("provenance") or {}).items()
    ]
    return {
        "status": integrity["status"],
        "title": title,
        "tone": tone,
        "summary": summary,
        "comparisons": comparisons,
        "unbalanced": integrity["unbalanced_transaction_count"],
        "warnings": [
            words.WARNING_LABELS.get(code) or words.humanise(code)
            for code in integrity["warnings"]
        ],
        "data_issues": issues,
        "attributed_legacy_entries": integrity.get(
            "source_attributed_legacy_entry_count", 0
        ),
        "provenance": provenance,
        "revenue_basis": words.humanise(integrity.get("revenue_basis", "")),
        "provider_cash": words.humanise(
            integrity.get("provider_cash_reconciliation", "")
        ),
    }


def _read_at(value):
    """The snapshot timestamp in the reporting timezone an operator works in."""

    from datetime import datetime
    from zoneinfo import ZoneInfo

    from apps.finance.control_plane.definitions import REPORTING_TIMEZONE

    try:
        moment = datetime.fromisoformat(value).astimezone(ZoneInfo(REPORTING_TIMEZONE))
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return value
    return moment.strftime("%d %b %Y, %H:%M ") + REPORTING_TIMEZONE.split("/")[-1]


def build_view(snapshot, params, scope):
    links = _link_factory(params)
    dashboard = reverse("admin_console:finance-dashboard")
    provider_costs = snapshot.get("provider_costs") or {}
    categories = snapshot.get("revenue_categories") or {}
    return {
        "snapshot": {
            "as_of": _read_at(snapshot["as_of"]),
            "version": snapshot["definition_version"],
            "timezone": snapshot["reporting_timezone"],
            "balance_basis": snapshot["balance_basis"],
            "provider_semantics": snapshot["provider_filter_semantics"],
            "limitations": snapshot["limitations"],
        },
        "headline": _headline(snapshot, links),
        "funded": _group(snapshot, FUNDED, links),
        "earnings": _group(snapshot, EARNINGS, links),
        "obligations": _group(snapshot, OBLIGATIONS, links),
        "location": _group(snapshot, LOCATION, links),
        "refunds": _group(snapshot, REFUNDS, links),
        "risk": _group(snapshot, RISK, links),
        "deposits": _group(snapshot, DEPOSITS, links),
        "buckets": _liability_buckets(snapshot, links),
        "liability_split": _liability_split(snapshot),
        "rails": _rail_sections(snapshot, links),
        "providers": _providers(snapshot, params),
        "provider_costs_available": provider_costs.get("status") == "available",
        "provider_costs_text": (
            format_eur(provider_costs.get("amount_eur_cents"))
            if provider_costs.get("status") == "available"
            else "Not available"
        ),
        "revenue_categories_available": categories.get("status") == "available",
        "revenue_categories_reason": categories.get("reason", ""),
        "integrity": _integrity(snapshot),
        "definitions": sorted(
            (
                {"key": key, "label": row["name"], **row}
                for key, row in snapshot["definitions"].items()
            ),
            key=lambda row: row["label"],
        ),
        "legacy_url": f"{dashboard}?{_query(params, mode='legacy_unknown')}",
        "in_legacy_mode": scope.mode == "legacy_unknown",
        "refresh_url": f"{dashboard}?{_query(params)}",
        "reset_url": dashboard,
    }


# ---------------------------------------------------------------------------
# Drilldown view model
# ---------------------------------------------------------------------------


def _settlement_cell(row):
    amount = row.get("payout_amount_minor")
    if amount is None:
        return "Not recorded"
    return format_minor_amount(
        amount, row.get("payout_amount_exponent") or 0, row.get("payout_currency") or ""
    )


def _rate_cell(row):
    micros = row.get("fx_rate_micros")
    if not micros:
        return "Not recorded"
    rate = decimal_micros(int(micros)).normalize()
    return f"1 EUR = {rate:,f} {row.get('payout_currency') or ''}".strip()


def _marker_cell(row):
    """Only the three facts that say something is holding this payout up.

    H5's `exposed` flag is deliberately not a marker. It is true of any award
    with an accepted instruction, including one that has already been paid, and
    every payout row already carries an `operation_stage` that says where the
    money actually is — paid, at the connected account, in bank transit. A
    marker reading "Externally committed" next to a stage reading "Paid" is two
    columns contradicting each other about the same row.
    """

    marks = []
    if row.get("has_hold"):
        marks.append("Hold")
    if row.get("has_user_dispute"):
        marks.append("ShipTrip dispute")
    if row.get("has_provider_dispute"):
        marks.append("Provider dispute")
    return marks


def _row_pk(row, kind):
    """The primary key behind an H5 drilldown row reference.

    H5 stamps every row with `<KIND>-<primary key>` precisely because the
    legacy finance tables carry no UUID of their own. For a payout row that key
    is the Payout id, which is what the H3/H4 operational screen is addressed
    by, so the link needs no extra query and exposes nothing new.
    """

    prefix, _, identifier = str(row.get("row_reference") or "").partition("-")
    if prefix != kind or not identifier.isdigit():
        return None
    return int(identifier)


def _format_field(field, raw):
    if field in _NUMERIC_FIELDS:
        return format_eur(raw) if raw is not None else "Not available"
    if field in _TIME_FIELDS:
        return str(raw).replace("T", " ")[:16] if raw else "—"
    if field in _ENUM_FIELDS:
        return _ENUM_FIELDS[field].get(raw) or words.humanise(raw)
    if field == "status":
        return dict(Payout.Status.choices).get(raw) or words.humanise(raw)
    if isinstance(raw, bool):
        return "Yes" if raw else "No"
    if raw in (None, ""):
        return "—"
    return str(raw)


def _ordered(row):
    ranking = {field: index for index, field in enumerate(_DRILLDOWN_COLUMN_ORDER)}
    return sorted(row, key=lambda field: (ranking.get(field, len(ranking)), field))


def _kind(field):
    if field in _NUMERIC_FIELDS:
        return "money"
    if field in _TIME_FIELDS:
        return "time"
    if field.endswith("_reference"):
        return "ref"
    if field in ("status", "bucket", "operation_stage"):
        return "status"
    return "text"


def build_rows(result, params, *, user):
    """H5 drilldown rows as a table, plus a safe link to operational detail."""

    payout_detail = has_admin_permission(user, "view_payouts")
    refund_detail = any(
        has_admin_permission(user, code)
        for code in ("issue_refunds", "settle_manual_refunds")
    )
    # The exclusive liability bucket classifies *outstanding* payable. The
    # operational cohort deliberately includes settled awards, whose payable is
    # zero, so their bucket is not a statement about liability at all — and
    # "Processing or externally committed" beside a stage of "Paid" reads as a
    # contradiction. The stage is the authoritative column there.
    liability_bucket = result["metric"] != "payout_operations"
    fields, rows = [], []
    for raw in result["rows"]:
        row = dict(raw)
        if not liability_bucket:
            row.pop("bucket", None)
        derived = {
            key: row.pop(key, None)
            for key in (
                "payout_amount_minor",
                "payout_amount_exponent",
                "payout_currency",
                "has_hold",
                "has_user_dispute",
                "has_provider_dispute",
                "exposed",
            )
        }
        if derived["payout_currency"] or derived["payout_amount_minor"] is not None:
            row["settlement"] = _settlement_cell(derived)
        if "fx_rate_micros" in row:
            row["fx_rate_micros"] = _rate_cell({**derived, **raw})
        markers = _marker_cell(derived)
        if any(key in raw for key in ("has_hold", "has_user_dispute")):
            row["markers"] = markers
        cells = []
        for field in _ordered(row):
            if field == "markers":
                cells.append({"field": field, "kind": "markers", "markers": markers})
                continue
            cells.append(
                {
                    "field": field,
                    "kind": _kind(field),
                    "text": row[field]
                    if field in ("settlement", "fx_rate_micros")
                    else _format_field(field, row[field]),
                }
            )
        payout_pk = _row_pk(raw, "PAYOUT")
        refund_pk = _row_pk(raw, "REFUND")
        link = ""
        if payout_pk and payout_detail:
            link = reverse("admin_console:payout-detail", args=[payout_pk])
        elif refund_pk and refund_detail:
            link = reverse("admin_console:refund-detail", args=[refund_pk])
        rows.append(
            {
                "cells": cells,
                "open_url": link,
                # Fifty rows whose only link says "open this row" is fifty
                # identical stops for a screen reader. The Deal reference is
                # already on the row and is short enough to be heard.
                "open_label": "Open the operational record for "
                + (raw.get("deal_reference") or raw.get("row_reference") or "this row"),
            }
        )
        if not fields:
            fields = _ordered(row)
    columns = [
        {
            "field": field,
            "label": words.FIELD_LABELS.get(field)
            or words.humanise(field).replace(" eur cents", ""),
            "numeric": field in _NUMERIC_FIELDS,
        }
        for field in fields
    ]
    page = result["page"]
    return {
        "columns": columns,
        "rows": rows,
        "page": page,
        "page_size": result["page_size"],
        "has_next": result["has_next"],
        "has_previous": page > 1,
        "previous_url": _rows_url(params, page - 1) if page > 1 else "",
        "next_url": _rows_url(params, page + 1) if result["has_next"] else "",
        "totals": value(result["totals"], result["metric"]),
        "as_of": _read_at(result["as_of"]),
        "version": result["definition_version"],
    }


def _rows_url(params, page):
    return f"{reverse('admin_console:finance-rows')}?{_query(params, page=str(page))}"


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------


def _guard(request):
    """Finance and Super only, and only while the flag is on.

    The capability check runs first so a role that may not see Finance data
    learns nothing from the flag's state, and the flag answers 404 rather than
    403 so a disabled dashboard is indistinguishable from a route that was
    never built.
    """

    if not has_all_admin_permissions(request.user, "view_finance_summary"):
        raise PermissionDenied("Finance summary access is required.")
    if not settings.FINANCE_DASHBOARD_ENABLED:
        raise Http404


def _render(request, template, context, *, status=200):
    from .console_views import _render as render_console

    return render_console(request, template, context, status=status)


def _page_context(request, params, scope=None):
    return {
        "title": "Finance control plane",
        "eyebrow": "Finance · read-only",
        "filters": _filter_state(params, scope),
        "query": _query(params),
        "dashboard_url": reverse("admin_console:finance-dashboard"),
        "rows_url": reverse("admin_console:finance-rows"),
        "reset_url": reverse("admin_console:finance-dashboard"),
    }


@never_cache
@staff_member_required
@require_GET
def finance_dashboard(request):
    """One bounded snapshot per view. No polling, no per-KPI request."""

    _guard(request)
    params = scope_params(request)
    try:
        scope = Scope.parse(params)
    except ValidationError as exc:
        return _render(
            request,
            "admin/console/finance_dashboard.html",
            {**_page_context(request, params), "errors": list(exc.messages)},
            status=400,
        )
    try:
        snapshot = build_snapshot(scope)
    except OperationalError:
        return _render(
            request,
            "admin/console/finance_dashboard.html",
            {**_page_context(request, params, scope), "unavailable": True},
            status=503,
        )
    return _render(
        request,
        "admin/console/finance_dashboard.html",
        {
            **_page_context(request, params, scope),
            **build_view(snapshot, params, scope),
        },
    )


@never_cache
@staff_member_required
@require_GET
def finance_rows(request):
    """The exact rows behind one H5 metric, bounded and paged by H5."""

    _guard(request)
    params = scope_params(request)
    metric = params.get("metric", "")
    dashboard = reverse("admin_console:finance-dashboard")
    back_url = f"{dashboard}?{_query(params, metric='', page='')}"
    context = {
        **_page_context(request, params),
        "metric": metric,
        "metric_label": "",
        "back_url": back_url,
    }
    try:
        scope = Scope.parse(params)
        result = drilldown(
            scope,
            metric=metric,
            page=params.get("page") or 1,
            page_size=params.get("page_size") or 50,
        )
    except ValidationError as exc:
        return _render(
            request,
            "admin/console/finance_rows.html",
            {**context, "errors": list(exc.messages)},
            status=400,
        )
    except OperationalError:
        return _render(
            request,
            "admin/console/finance_rows.html",
            {**context, "unavailable": True},
            status=503,
        )
    from apps.finance.control_plane.definitions import DEFINITIONS

    definition = DEFINITIONS.get(metric)
    context.update(
        _page_context(request, params, scope),
        metric=metric,
        metric_label=definition.name if definition else words.humanise(metric),
        metric_definition=definition.definition if definition else "",
        metric_time_basis=definition.time_basis if definition else "",
        metric_exclusion=definition.exclusion if definition else "",
        back_url=back_url,
        **build_rows(result, params, user=request.user),
    )
    return _render(request, "admin/console/finance_rows.html", context)
