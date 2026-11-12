"""Pausing and resuming a journey from the console (L3B).

A staff pause takes a journey out of discovery and refuses new offers on it
until staff lift it (spec 5.7); the traveler cannot lift it and is told only to
contact support. The reason is internal: it is recorded here and in the audit
log and never reaches the member. The rules (who may, which statuses, the
audit row) live in `apps.trips.services`; these views only collect the reason.
"""

from __future__ import annotations

from django import forms
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse

from apps.trips.models import Journey
from apps.trips.services import (
    STAFF_PAUSABLE_JOURNEY_STATUSES,
    JourneyDomainError,
    pause_journey,
    resume_journey,
)

from .console_forms import ConsoleForm


class JourneyPauseForm(ConsoleForm):
    reason = forms.CharField(
        max_length=500,
        label="Reason",
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text=(
            "Recorded in the audit log and kept internal: the traveler is told "
            "only to contact support."
        ),
    )


def pause_state(journey: Journey, *, may_manage: bool) -> dict:
    """What the journey page shows about a pause, and which action it offers."""

    if journey.paused_at is None:
        state = "running"
    elif journey.paused_by_staff:
        state = "staff"
    else:
        state = "owner"
    action = None
    if may_manage:
        if state == "staff":
            action = {"name": "resume", "label": "Resume journey"}
        elif journey.status in STAFF_PAUSABLE_JOURNEY_STATUSES:
            action = {
                "name": "pause",
                "label": "Take over the pause" if state == "owner" else "Pause journey",
            }
    return {
        "state": state,
        "since": journey.paused_at,
        "reason": journey.pause_reason if state == "staff" else "",
        "action": action,
    }


def journey_pause_action(request, pk: int, action: str):
    """`manage_journeys` only; the guard is on the URL, the domain re-checks it."""

    from django.http import Http404

    from .console_views import _operation_error, _render

    if action not in ("pause", "resume"):
        raise Http404
    journey = get_object_or_404(Journey, pk=pk)
    pausing = action == "pause"
    form = JourneyPauseForm(request.POST or None)
    back = reverse("admin_console:journey-detail", args=(journey.pk,))
    if request.method == "POST" and form.is_valid():
        change = pause_journey if pausing else resume_journey
        try:
            change(
                actor=request.user,
                journey_id=journey.pk,
                reason=form.cleaned_data["reason"],
            )
        except JourneyDomainError as exc:
            _operation_error(request, "Changing the journey pause", exc)
        else:
            messages.success(
                request,
                "The journey is paused. It is out of discovery and takes no new offers."
                if pausing
                else "The journey is no longer paused.",
            )
            return redirect(back)
    return _render(
        request,
        "admin/console/action_form.html",
        {
            "title": f"{'Pause' if pausing else 'Resume'} journey {journey.pk}",
            "description": (
                "The journey leaves every discovery surface and takes no new offers. "
                "Offers already pending cannot be accepted until it is resumed. "
                "Funded deals are not affected."
                if pausing
                else "The journey can be found and offered on again from the next request."
            ),
            "form": form,
            "submit_label": "Pause journey" if pausing else "Resume journey",
            "danger": pausing,
            "back_url": back,
        },
    )
