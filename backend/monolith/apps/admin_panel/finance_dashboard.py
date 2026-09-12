"""H5 drilldown rows, and the primitives every Finance surface shares.

H5.2 moved the Finance landing page, the queues, the exceptions and the
reconciliation detail into `finance_operations`. What stays here is the one
page this module still owns — the exact rows behind a single H5 metric — and
the scope, formatting and access primitives that page shares with them.

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


def _read_at(value):
    """A snapshot timestamp in the reporting timezone an operator works in."""

    from datetime import datetime
    from zoneinfo import ZoneInfo

    from apps.finance.control_plane.definitions import REPORTING_TIMEZONE

    try:
        moment = datetime.fromisoformat(value).astimezone(ZoneInfo(REPORTING_TIMEZONE))
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return value
    return moment.strftime("%d %b %Y, %H:%M ") + REPORTING_TIMEZONE.split("/")[-1]


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
