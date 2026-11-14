"""Reported reviews in the console (spec 18, plan L13A).

One queue of the reviews members reported, the ones with open reports first,
each with the delivery it belongs to, how many reports it has and why. A
review's page shows it as written, every report with its reporter (staff only:
the author is never told who reported), and the four decisions, each with a
required reason that is audited and stays internal. The rules live in
`apps.ratings.moderation`; these views collect reasons and show outcomes.
"""

from __future__ import annotations

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count, IntegerField, Max, OuterRef, Subquery, Value
from django.db.models.functions import Coalesce
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect

from apps.parcels import tracking
from apps.ratings.models import Rating, RatingModeration, RatingReport
from apps.ratings.moderation import (
    ACTION_DISMISS,
    ACTION_HIDE_COMMENT,
    ACTION_LIFT,
    ACTION_REMOVE,
    ACTIONS,
    MODERATE_PERMISSION,
    ModerationError,
    decide,
)
from apps.ratings.services import is_revealed

from . import tracking_search
from .console_forms import ConsoleForm
from .console_presenters import age_label, ref_cell, text_cell
from .models import AdminAuditLog
from .permissions import has_admin_permission
from .utils import admin_url, bounded_query_text, positive_page

STATE_OPEN = "open"
STATE_DECIDED = "decided"
REVIEW_QUEUE_QUERY = {
    "q": bounded_query_text,
    "status": frozenset({STATE_OPEN, STATE_DECIDED}),
    "page": positive_page,
}

#: What each decision is called on its button and in the success message.
DECISIONS = {
    ACTION_DISMISS: (
        "Dismiss the reports",
        "The review stays as it is.",
        "The reports are dismissed. The review is unchanged.",
    ),
    ACTION_HIDE_COMMENT: (
        "Hide the comment",
        "The score and tags still count. The text is replaced by “Comment removed by Wassla”.",
        "The comment is hidden. The score still counts.",
    ),
    ACTION_REMOVE: (
        "Remove the rating",
        "It leaves every public average, count and list. The rated person still sees "
        "it, marked “Removed by Wassla, not counted”.",
        "The rating is removed from every public average, count and list.",
    ),
    ACTION_LIFT: (
        "Lift the decision",
        "The review is shown and counted as written again.",
        "The decision is lifted. The review is shown as written.",
    ),
}


class DecisionForm(ConsoleForm):
    reason = forms.CharField(
        max_length=500,
        label="Reason",
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Recorded in the audit log and kept internal: members never see it.",
    )


def _open_reports():
    return RatingReport.objects.filter(
        rating_id=OuterRef("pk"), status=RatingReport.Status.OPEN
    )


def _queue(request):
    from .console_views import _search

    open_count = (
        _open_reports().order_by().values("rating_id").annotate(n=Count("pk")).values("n")
    )
    queryset = (
        Rating.objects.filter(reports__isnull=False)
        .select_related("deal__delivery_request", "rater", "ratee", "moderation")
        .annotate(
            report_count=Count("reports", distinct=True),
            open_report_count=Coalesce(
                Subquery(open_count, output_field=IntegerField()), Value(0)
            ),
            last_reported_at=Max("reports__created_at"),
        )
        # Open reports first, the longest waiting at the top; then the rest.
        .order_by("-open_report_count", "last_reported_at", "pk")
    )
    status = request.GET.get("status", "")
    if status == STATE_OPEN:
        queryset = queryset.filter(open_report_count__gt=0)
    elif status == STATE_DECIDED:
        queryset = queryset.filter(open_report_count=0).order_by("-last_reported_at", "-pk")
    return _search(
        queryset,
        request,
        ("rater__email", "ratee__email", "comment"),
        tracking_paths=tuple(f"deal__{path}" for path in tracking_search.DEAL),
    )


def _reasons_by_rating(rating_ids) -> dict[int, list[str]]:
    """Each review's report reasons, most frequent first, in one query."""

    labels = dict(RatingReport.Reason.choices)
    reasons: dict[int, list[str]] = {}
    rows = (
        RatingReport.objects.filter(rating_id__in=rating_ids)
        .values("rating_id", "reason")
        .annotate(n=Count("pk"))
        .order_by("rating_id", "-n", "reason")
    )
    for row in rows:
        label = labels[row["reason"]]
        reasons.setdefault(row["rating_id"], []).append(
            f"{label} ×{row['n']}" if row["n"] > 1 else label
        )
    return reasons


_MODERATION_CHIPS = {
    RatingModeration.State.COMMENT_HIDDEN: ("Comment hidden", "info"),
    RatingModeration.State.REMOVED: ("Rating removed", "bad"),
}


def _moderation_of(rating) -> RatingModeration | None:
    """The standing decision, read from `select_related` without a query."""

    try:
        return rating.moderation
    except RatingModeration.DoesNotExist:
        return None


def _state_cell(rating) -> dict:
    moderation = _moderation_of(rating)
    decided = _MODERATION_CHIPS[moderation.state] if moderation else None
    if rating.open_report_count:
        count = rating.open_report_count
        return {
            "primary": f"{count} open report{'s' if count != 1 else ''}",
            "secondary": decided[0] if decided else "",
            "kind": "status",
            "tone": "attn",
        }
    primary, tone = decided or ("Reports dismissed", "mute")
    return {"primary": primary, "kind": "status", "tone": tone}


def _excerpt(text: str, limit: int = 90) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def reviews(request):
    from .console_views import _page, _person_link, _table

    page_obj = _page(request, _queue(request))
    reasons = _reasons_by_rating([rating.pk for rating in page_obj.object_list])
    rows = []
    for rating in page_obj.object_list:
        rows.append(
            {
                "cells": (
                    text_cell(
                        f"{'★' * rating.score}{'☆' * (5 - rating.score)} {rating.score}/5",
                        _excerpt(rating.comment) or "No comment",
                        href=admin_url(
                            request,
                            "admin_console:review-detail",
                            route_kwargs={"pk": rating.pk},
                            preserve_query=REVIEW_QUEUE_QUERY,
                        ),
                        opens_row=True,
                        aria_label=f"Open the review {rating.pk}",
                    ),
                    text_cell(
                        rating.ratee.full_name or rating.ratee.email,
                        f"rated by the {rating.get_rater_role_display().split()[0].lower()}, "
                        f"{rating.rater.full_name or rating.rater.email}",
                        href=_person_link(request, rating.ratee, "reviews"),
                        secondary_href=_person_link(request, rating.rater, "reviews"),
                    ),
                    ref_cell(tracking.for_deal(rating.deal)),
                    text_cell(
                        f"{rating.report_count} report{'s' if rating.report_count != 1 else ''}",
                        ", ".join(reasons.get(rating.pk, ())),
                    ),
                    text_cell(f"{age_label(rating.last_reported_at)} ago"),
                    _state_cell(rating),
                )
            }
        )
    status = request.GET.get("status", "")
    return _table(
        request,
        title="Reported reviews",
        description=(
            "Reviews members reported. Open reports come first. Decide each with a "
            "reason; the author is never told who reported."
        ),
        eyebrow="Trust",
        columns=("Review", "About", "Tracking number", "Reports", "Last report", "State"),
        rows=rows,
        page_obj=page_obj,
        empty_title=(
            "No review is waiting"
            if status == STATE_OPEN
            else "No reported reviews found"
        ),
        empty_text="When a member reports a review, it appears here.",
        filter_choices=((STATE_OPEN, "Open reports"), (STATE_DECIDED, "Decided")),
        search_placeholder="Search tracking number, participant or comment",
    )


def available_decisions(rating, moderation, open_reports: int) -> dict[str, bool]:
    """Which of the four decisions the review page offers now (and the AI
    helper may prepare): the same answer for both."""

    state = moderation.state if moderation else None
    return {
        ACTION_DISMISS: bool(open_reports),
        ACTION_HIDE_COMMENT: state != RatingModeration.State.COMMENT_HIDDEN
        and bool((rating.comment or "").strip()),
        ACTION_REMOVE: state != RatingModeration.State.REMOVED,
        ACTION_LIFT: moderation is not None,
    }


def review_detail(request, pk: int):
    from .console_views import _operation_error, _render

    rating = get_object_or_404(
        Rating.objects.select_related(
            "deal__delivery_request", "deal__sender", "deal__traveler", "rater", "ratee"
        ).prefetch_related("deal__ratings"),
        pk=pk,
    )
    moderation = (
        RatingModeration.objects.select_related("decided_by").filter(rating=rating).first()
    )
    reports = list(
        RatingReport.objects.filter(rating=rating)
        .select_related("reporter", "decided_by")
        .order_by("-created_at", "-pk")
    )
    open_reports = sum(1 for report in reports if report.status == RatingReport.Status.OPEN)
    may_moderate = has_admin_permission(request.user, MODERATE_PERMISSION)

    action = request.POST.get("action", "") if request.method == "POST" else ""
    forms_by_action = {
        key: DecisionForm(request.POST if action == key else None, prefix=key)
        for key in ACTIONS
    }
    if action:
        if action not in ACTIONS:
            raise Http404
        if not may_moderate:
            raise PermissionDenied
        form = forms_by_action[action]
        if form.is_valid():
            try:
                decide(
                    rating_id=rating.pk,
                    actor=request.user,
                    action=action,
                    reason=form.cleaned_data["reason"],
                )
            except ModerationError as exc:
                _operation_error(request, "Deciding on the review", exc)
            else:
                messages.success(request, DECISIONS[action][2])
                return redirect("admin_console:review-detail", pk=rating.pk)

    available = available_decisions(rating, moderation, open_reports)
    decisions = [
        {
            "action": key,
            "title": DECISIONS[key][0],
            "help": DECISIONS[key][1],
            "form": forms_by_action[key],
            "danger": key == ACTION_REMOVE,
        }
        for key in ACTIONS
        if may_moderate and available[key]
    ]
    audits = []
    if has_admin_permission(request.user, "view_audit_log"):
        audits = AdminAuditLog.objects.filter(
            target_type="ratings.rating", target_id=str(rating.pk)
        ).select_related("actor")[:20]
    deal = rating.deal
    return _render(
        request,
        "admin/console/review_detail.html",
        {
            "title": f"Review · {tracking.for_deal(deal)}",
            "rating": rating,
            "written_by": "sender" if rating.rater_role == Rating.RaterRole.SENDER else "traveler",
            "revealed": is_revealed(rating, deal=deal),
            "moderation": moderation,
            "reports": reports,
            "open_reports": open_reports,
            "deal": deal,
            "tracking_number": tracking.for_deal(deal),
            "may_moderate": may_moderate,
            "decisions": decisions,
            "audits": audits,
            "may_view_deal": has_admin_permission(request.user, "view_deals"),
            "queue_url": admin_url(
                request, "admin_console:reviews", preserve_query=REVIEW_QUEUE_QUERY
            ),
        },
    )
