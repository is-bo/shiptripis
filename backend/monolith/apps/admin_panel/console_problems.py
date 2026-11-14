"""Problem reports in the console (spec 12 and 13, plan L9A).

One queue of the problems parties reported on their deliveries, the serious
kinds first. Staff acknowledge a report or close it, each with a reason that
is audited and stays internal. A no-show report carries a "Record a no-show"
link to the deal's no-show page with the party pre-selected; recording it is
the existing money rule, and closes the report with a reference to the audit
row. The rules live in `apps.problems.services` and
`apps.admin_panel.services.record_deal_no_show`; these views collect reasons.
"""

from __future__ import annotations

from django import forms
from django.contrib import messages
from django.db.models import Case, IntegerField, Value, When
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse

from apps.deals.cancellation import CancellationError
from apps.deals.lifecycle import PRE_PICKUP_STATUSES
from apps.deals.models import Deal
from apps.parcels import tracking
from apps.problems.models import ShipmentProblem
from apps.problems.services import (
    MANAGE_PROBLEMS_PERMISSION,
    ProblemError,
    acknowledge_problem,
    close_problem,
    record_no_show_link_party,
)

from . import tracking_search
from .console_forms import ConsoleForm
from .console_presenters import age_label, ref_cell, status_cell, text_cell
from .models import AdminAuditLog
from .permissions import has_admin_permission
from .services import record_deal_no_show
from .utils import admin_url, bounded_query_text, positive_page

PROBLEM_QUEUE_QUERY = {
    "q": bounded_query_text,
    "status": frozenset(ShipmentProblem.Status.values),
    "attention": frozenset({"1"}),
    "page": positive_page,
}

#: Serious first, then the oldest: what a staff member should open next.
_URGENCY = Case(
    When(status=ShipmentProblem.Status.ESCALATED, then=Value(0)),
    When(status=ShipmentProblem.Status.OPEN, then=Value(1)),
    When(status=ShipmentProblem.Status.ACKNOWLEDGED, then=Value(2)),
    default=Value(3),
    output_field=IntegerField(),
)


def waiting():
    """Reports in front of staff that nobody has picked up yet (the work list)."""

    return ShipmentProblem.objects.filter(status=ShipmentProblem.Status.ESCALATED)


class ProblemReasonForm(ConsoleForm):
    reason = forms.CharField(
        max_length=500,
        label="Reason",
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Recorded in the audit log and kept internal: the parties see only the new state.",
    )


class NoShowForm(ConsoleForm):
    party = forms.ChoiceField(
        choices=Deal.NoShowParty.choices,
        label="Who did not come",
        widget=forms.RadioSelect,
    )
    note = forms.CharField(
        max_length=255,
        label="Note",
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Required. Stored on the delivery's timeline and in the audit log.",
    )


def _queryset(request):
    from .console_views import _filter_choice, _search

    queryset = ShipmentProblem.objects.select_related(
        "deal__delivery_request", "deal__sender", "deal__traveler", "reported_by"
    ).order_by(_URGENCY, "created_at", "pk")
    if request.GET.get("attention") == "1":
        queryset = queryset.filter(status=ShipmentProblem.Status.ESCALATED)
    else:
        queryset = _filter_choice(queryset, request)
    return _search(
        queryset,
        request,
        ("deal__sender__email", "deal__traveler__email"),
        tracking_paths=tuple(f"deal__{path}" for path in tracking_search.DEAL),
    )


def problems(request):
    from .console_views import _page, _person_link, _table

    page_obj = _page(request, _queryset(request))
    rows = []
    for problem in page_obj.object_list:
        deal = problem.deal
        reporter, other = (
            (deal.sender, deal.traveler)
            if problem.reporter_role == ShipmentProblem.Role.SENDER
            else (deal.traveler, deal.sender)
        )
        rows.append(
            {
                "cells": (
                    ref_cell(
                        tracking.for_deal(deal),
                        f"Problem {problem.pk}",
                        href=admin_url(
                            request,
                            "admin_console:problem-detail",
                            route_kwargs={"pk": problem.pk},
                            preserve_query=PROBLEM_QUEUE_QUERY,
                        ),
                        opens_row=True,
                    ),
                    text_cell(problem.get_kind_display()),
                    text_cell(
                        reporter.full_name or reporter.email,
                        f"the {problem.get_reporter_role_display().lower()}, about "
                        f"{other.full_name or other.email}",
                        href=_person_link(request, reporter, "problems"),
                        secondary_href=_person_link(request, other, "problems"),
                    ),
                    text_cell(f"{age_label(problem.created_at)} ago"),
                    status_cell(problem.status, problem.get_status_display()),
                )
            }
        )
    return _table(
        request,
        title="Problems",
        description=(
            "What senders and travelers reported on their deliveries. Escalated "
            "reports are first; a report never changes a delivery or its money."
        ),
        eyebrow="Disputes",
        columns=("Tracking number", "Problem", "Reported by", "Age", "State"),
        rows=rows,
        page_obj=page_obj,
        empty_title="No escalated problems"
        if request.GET.get("attention") == "1"
        else "No problems found",
        empty_text="Nothing reported is waiting on staff.",
        filter_choices=tuple(ShipmentProblem.Status.choices),
        search_placeholder="Search tracking number or participant",
    )


def _no_show_link(problem: ShipmentProblem, *, user) -> dict | None:
    """The "Record a no-show" link of a live no-show report: deal and party, nothing else."""

    party = record_no_show_link_party(problem)
    if (
        not party
        or problem.status == ShipmentProblem.Status.CLOSED
        or not has_admin_permission(user, "record_no_show")
    ):
        return None
    return {
        "url": f"{reverse('admin_console:deal-no-show', args=(problem.deal_id,))}?party={party}",
        "label": "Record a no-show",
        "party": party,
    }


def problem_detail(request, pk: int):
    from .console_views import _operation_error, _render

    problem = get_object_or_404(
        ShipmentProblem.objects.select_related(
            "deal__delivery_request",
            "deal__sender",
            "deal__traveler",
            "reported_by",
            "acknowledged_by",
            "closed_by",
            "closed_by_audit",
        ),
        pk=pk,
    )
    may_manage = has_admin_permission(request.user, MANAGE_PROBLEMS_PERMISSION)
    action = request.POST.get("action", "") if request.method == "POST" else ""
    acknowledge_form = ProblemReasonForm(
        request.POST if action == "acknowledge" else None, prefix="acknowledge"
    )
    close_form = ProblemReasonForm(
        request.POST if action == "close" else None, prefix="close"
    )
    if action:
        if action not in ("acknowledge", "close"):
            raise Http404
        if not may_manage:
            from django.core.exceptions import PermissionDenied

            raise PermissionDenied
        form = acknowledge_form if action == "acknowledge" else close_form
        if form.is_valid():
            change = acknowledge_problem if action == "acknowledge" else close_problem
            try:
                change(
                    problem_id=problem.pk,
                    actor=request.user,
                    reason=form.cleaned_data["reason"],
                )
            except ProblemError as exc:
                _operation_error(request, "Updating the problem", exc)
            else:
                messages.success(
                    request,
                    "The problem is acknowledged."
                    if action == "acknowledge"
                    else "The problem is closed. The delivery is unchanged.",
                )
                return redirect("admin_console:problem-detail", pk=problem.pk)
    audits = []
    if has_admin_permission(request.user, "view_audit_log"):
        audits = AdminAuditLog.objects.filter(
            target_type="problems.shipmentproblem", target_id=str(problem.pk)
        ).select_related("actor")[:20]
    live = problem.status != ShipmentProblem.Status.CLOSED
    return _render(
        request,
        "admin/console/problem_detail.html",
        {
            "title": f"{problem.get_kind_display()} · {tracking.for_deal(problem.deal)}",
            "problem": problem,
            "reported_ago": age_label(problem.created_at),
            "deal": problem.deal,
            "tracking_number": tracking.for_deal(problem.deal),
            "may_manage": may_manage,
            "can_acknowledge": may_manage
            and problem.status
            in (ShipmentProblem.Status.OPEN, ShipmentProblem.Status.ESCALATED),
            "can_close": may_manage and live,
            "acknowledge_form": acknowledge_form,
            "close_form": close_form,
            "no_show_link": _no_show_link(problem, user=request.user),
            "audits": audits,
            "queue_url": admin_url(
                request, "admin_console:problems", preserve_query=PROBLEM_QUEUE_QUERY
            ),
        },
    )


def deal_no_show(request, pk: int):
    """Record an admin-reviewed no-show on a funded delivery before pickup.

    The console face of the existing action (`POST /api/admin/deals/<id>/no-show`):
    same capability, same service, same audit row. A no-show report links here
    with the party pre-selected.
    """

    from .console_views import _operation_error, _render

    deal = get_object_or_404(Deal.objects.select_related("delivery_request"), pk=pk)
    party = request.GET.get("party", "")
    initial = {"party": party} if party in Deal.NoShowParty.values else {}
    form = NoShowForm(request.POST or None, initial=initial)
    back = reverse("admin_console:deal-detail", args=(deal.pk,))
    recordable = (
        not deal.no_show_party
        and deal.pickup_confirmed_at is None
        and deal.status in PRE_PICKUP_STATUSES
    )
    if request.method == "POST" and form.is_valid():
        try:
            result = record_deal_no_show(
                actor=request.user,
                deal_id=deal.pk,
                party=form.cleaned_data["party"],
                note=form.cleaned_data["note"],
            )
        except CancellationError as exc:
            _operation_error(request, "Recording the no-show", exc)
        else:
            messages.success(
                request,
                "The no-show is recorded and the sender was refunded in full."
                if result.get("sender_refunded")
                else "The no-show is recorded.",
            )
            return redirect(back)
    return _render(
        request,
        "admin/console/action_form.html",
        {
            "title": f"Record a no-show · {tracking.for_deal(deal)}",
            "description": (
                "Only for a funded delivery whose pickup was never confirmed. A "
                "traveler no-show refunds the sender in full and cancels the "
                "delivery; a sender no-show is recorded without a refund. Open "
                "no-show reports on this delivery are closed with this decision."
                if recordable
                else "This delivery cannot take a no-show decision: it is not a "
                "funded delivery waiting for pickup, or a no-show is already recorded."
            ),
            "form": form if recordable else None,
            "submit_label": "Record the no-show",
            "danger": True,
            "back_url": back,
        },
    )
