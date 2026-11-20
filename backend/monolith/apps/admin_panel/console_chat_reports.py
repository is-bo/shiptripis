"""Reported chat messages in the console (App Store 1.2, plan STORE).

One queue of the messages members reported, the ones with open reports first.
A message's page shows it in its conversation (the messages just before and
after it), every report with its reporter (the sender is never told who
reported), and the decisions, each with a required reason that is audited and
stays internal. The rules live in `apps.chat.moderation`; these views collect
reasons and show outcomes. Suspending a member who keeps sending abuse is the
person page's own action.
"""

from __future__ import annotations

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count, IntegerField, Max, OuterRef, Subquery, Value
from django.db.models.functions import Coalesce
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect

from apps.chat.models import ChatMessage, ChatMessageReport
from apps.chat.moderation import (
    ACTION_DISMISS,
    ACTION_REMOVE,
    ACTION_RESTORE,
    ACTIONS,
    MODERATE_PERMISSION,
    ChatModerationError,
    available_decisions,
    decide,
)
from apps.parcels import tracking

from . import tracking_search
from .console_presenters import age_label, ref_cell, text_cell
from .console_reviews import DecisionForm
from .models import AdminAuditLog
from .permissions import has_admin_permission
from .utils import admin_url, bounded_query_text, positive_page

STATE_OPEN = "open"
STATE_DECIDED = "decided"
QUEUE_QUERY = {
    "q": bounded_query_text,
    "status": frozenset({STATE_OPEN, STATE_DECIDED}),
    "page": positive_page,
}

#: How many messages before and after the reported one its page shows.
CONTEXT_MESSAGES = 5

#: What each decision is called on its button, its help and its success message.
DECISIONS = {
    ACTION_DISMISS: (
        "Dismiss the reports",
        "The message stays as it is.",
        "The reports are dismissed. The message is unchanged.",
    ),
    ACTION_REMOVE: (
        "Remove the message",
        "Both members see “Removed by Wassla” in its place. What it said stays here "
        "and in the audit log.",
        "The message is removed from the conversation.",
    ),
    ACTION_RESTORE: (
        "Restore the message",
        "Both members see the message as written again.",
        "The message is restored.",
    ),
}


def _open_reports():
    return ChatMessageReport.objects.filter(
        message_id=OuterRef("pk"), status=ChatMessageReport.Status.OPEN
    )


def _queue(request):
    from .console_views import _search

    open_count = (
        _open_reports().order_by().values("message_id").annotate(n=Count("pk")).values("n")
    )
    queryset = (
        ChatMessage.objects.filter(reports__isnull=False)
        .select_related("sender", "match__parcel", "match__sender", "match__traveler")
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
        ("sender__email", "match__sender__email", "match__traveler__email", "body"),
        tracking_paths=tuple(f"match__{path}" for path in tracking_search.MATCH),
    )


def _reasons_by_message(message_ids) -> dict[int, list[str]]:
    """Each message's report reasons, most frequent first, in one query."""

    labels = dict(ChatMessageReport.Reason.choices)
    reasons: dict[int, list[str]] = {}
    rows = (
        ChatMessageReport.objects.filter(message_id__in=message_ids)
        .values("message_id", "reason")
        .annotate(n=Count("pk"))
        .order_by("message_id", "-n", "reason")
    )
    for row in rows:
        label = labels[row["reason"]]
        reasons.setdefault(row["message_id"], []).append(
            f"{label} ×{row['n']}" if row["n"] > 1 else label
        )
    return reasons


def _state_cell(message) -> dict:
    if message.open_report_count:
        count = message.open_report_count
        return {
            "primary": f"{count} open report{'s' if count != 1 else ''}",
            "secondary": "Removed" if message.removed_at else "",
            "kind": "status",
            "tone": "attn",
        }
    if message.removed_at:
        return {"primary": "Message removed", "kind": "status", "tone": "bad"}
    return {"primary": "Reports dismissed", "kind": "status", "tone": "mute"}


def _excerpt(text: str, limit: int = 90) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _name(user) -> str:
    return user.full_name or user.email


def chat_reports(request):
    from .console_views import _page, _person_link, _table

    page_obj = _page(request, _queue(request))
    reasons = _reasons_by_message([message.pk for message in page_obj.object_list])
    rows = []
    for message in page_obj.object_list:
        match = message.match
        recipient = match.traveler if message.sender_id == match.sender_id else match.sender
        rows.append(
            {
                "cells": (
                    text_cell(
                        _excerpt(message.body),
                        message.created_at.strftime("%d %b %Y, %H:%M"),
                        href=admin_url(
                            request,
                            "admin_console:chat-report-detail",
                            route_kwargs={"pk": message.pk},
                            preserve_query=QUEUE_QUERY,
                        ),
                        opens_row=True,
                        aria_label=f"Open the reported message {message.pk}",
                    ),
                    text_cell(
                        _name(message.sender),
                        f"to {_name(recipient)}",
                        href=_person_link(request, message.sender, "chat-reports"),
                        secondary_href=_person_link(request, recipient, "chat-reports"),
                    ),
                    ref_cell(tracking.for_request(match.parcel)),
                    text_cell(
                        f"{message.report_count} report{'s' if message.report_count != 1 else ''}",
                        ", ".join(reasons.get(message.pk, ())),
                    ),
                    text_cell(f"{age_label(message.last_reported_at)} ago"),
                    _state_cell(message),
                )
            }
        )
    status = request.GET.get("status", "")
    return _table(
        request,
        title="Reported chat messages",
        description=(
            "Messages members reported. Open reports come first; act on each within a "
            "day. The sender is never told who reported."
        ),
        eyebrow="Trust",
        columns=("Message", "Sent by", "Tracking number", "Reports", "Last report", "State"),
        rows=rows,
        page_obj=page_obj,
        empty_title=(
            "No message is waiting"
            if status == STATE_OPEN
            else "No reported messages found"
        ),
        empty_text="When a member reports a chat message, it appears here.",
        filter_choices=((STATE_OPEN, "Open reports"), (STATE_DECIDED, "Decided")),
        search_placeholder="Search tracking number, participant or message",
    )


def chat_report_detail(request, pk: int):
    from .console_views import _operation_error, _render

    message = get_object_or_404(
        ChatMessage.objects.select_related(
            "sender", "removed_by", "match__parcel", "match__sender", "match__traveler"
        ).filter(reports__isnull=False).distinct(),
        pk=pk,
    )
    match = message.match
    reports = list(
        ChatMessageReport.objects.filter(message=message)
        .select_related("reporter", "decided_by")
        .order_by("-created_at", "-pk")
    )
    open_reports = sum(1 for r in reports if r.status == ChatMessageReport.Status.OPEN)
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
                    message_id=message.pk,
                    actor=request.user,
                    action=action,
                    reason=form.cleaned_data["reason"],
                )
            except ChatModerationError as exc:
                _operation_error(request, "Deciding on the message", exc)
            else:
                messages.success(request, DECISIONS[action][2])
                return redirect("admin_console:chat-report-detail", pk=message.pk)

    thread = ChatMessage.objects.filter(match=match).select_related("sender")
    before = list(thread.filter(pk__lt=message.pk).order_by("-pk")[:CONTEXT_MESSAGES])
    after = list(thread.filter(pk__gt=message.pk).order_by("pk")[:CONTEXT_MESSAGES])
    conversation = [*reversed(before), message, *after]

    available = available_decisions(message, open_reports)
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
            target_type="chat.chatmessage", target_id=str(message.pk)
        ).select_related("actor")[:20]
    deal = getattr(match, "deal", None)
    return _render(
        request,
        "admin/console/chat_report_detail.html",
        {
            "title": f"Reported message · {tracking.for_request(match.parcel)}",
            "message": message,
            "conversation": conversation,
            "reports": reports,
            "open_reports": open_reports,
            "deal": deal,
            "tracking_number": tracking.for_request(match.parcel),
            "may_moderate": may_moderate,
            "decisions": decisions,
            "audits": audits,
            "may_view_deal": deal is not None and has_admin_permission(request.user, "view_deals"),
            "queue_url": admin_url(
                request, "admin_console:chat-reports", preserve_query=QUEUE_QUERY
            ),
        },
    )
