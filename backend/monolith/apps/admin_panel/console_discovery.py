"""The Person profile's Discovery tab, and hiding a public profile (L2A).

Read only, except one audited action: staff may hide a member's public profile
with a reason, and show it again (spec 4.5). Hiding never edits what the
member chose; it overrides it until it is lifted, and the member sees only
that the profile is "not currently visible".
"""

from __future__ import annotations

from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse

from apps.discovery.errors import DiscoveryError
from apps.discovery.models import PublicProfile, RouteAlert, TravelerInterest
from apps.discovery.profiles import set_profile_hidden

from .console_forms import ConsoleForm
from .console_presenters import datetime_cell, status_cell, text_cell

User = get_user_model()

DISCOVERY_VIEWS = (("alerts", "Route alerts"), ("interests", "“I can carry this”"))


class ProfileVisibilityForm(ConsoleForm):
    reason = forms.CharField(
        max_length=500,
        label="Reason",
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Recorded in the audit log. The member is not shown it.",
    )


def _city(place) -> str:
    return place.display_label if place is not None else "—"


def _profile_summary(person, caps, source):
    profile = (
        PublicProfile.objects.select_related("hidden_by")
        .prefetch_related(
            "usual_routes__origin_locality__parent",
            "usual_routes__destination_locality__parent",
        )
        .filter(user=person)
        .first()
    )
    if profile is None:
        state = ("Never set up", "mute")
    elif profile.hidden_at is not None:
        state = ("Hidden by staff", "bad")
    elif profile.is_discoverable:
        state = ("Visible", "ok")
    else:
        state = ("Turned off by the member", "mute")
    hidden = profile is not None and profile.hidden_at is not None
    action = None
    if caps("manage_users"):
        query = f"?from={source}" if source else ""
        action = {
            "label": "Show profile again" if hidden else "Hide profile",
            "url": reverse("admin_console:user-profile-visibility", args=(person.pk,)) + query,
            "danger": not hidden,
        }
    return {
        "state": {"label": state[0], "tone": state[1]},
        "consented_at": profile.consented_at if profile else None,
        "consent_version": profile.consent_version if profile else "",
        "routes": [
            f"{_city(route.origin_locality)} → {_city(route.destination_locality)}"
            for route in (profile.usual_routes.all() if profile else ())
        ],
        "hidden": (
            {
                "at": profile.hidden_at,
                "by": profile.hidden_by.email if profile.hidden_by else "—",
                "reason": profile.hidden_reason,
            }
            if hidden
            else None
        ),
        "action": action,
    }


def _alerts_list(request, person, page, list_):
    queryset = (
        RouteAlert.objects.filter(user=person)
        .select_related(
            "origin_locality__parent", "destination_locality__parent", "subject_user"
        )
        .order_by("-created_at", "-pk")
    )
    page_obj = page(request, queryset)
    rows = [
        {
            "cells": (
                text_cell(alert.get_watches_display(), kind="strong"),
                text_cell(f"{_city(alert.origin_locality)} → {_city(alert.destination_locality)}"),
                text_cell(alert.subject_user.email if alert.subject_user else "Anyone"),
                datetime_cell(alert.created_at),
                status_cell("active" if alert.is_active else "cancelled",
                            "Active" if alert.is_active else "Deleted by the member"),
            )
        }
        for alert in page_obj.object_list
    ]
    return list_(
        ("Watches", "Route", "Following", "Created", "State"),
        rows, page_obj=page_obj, layout="alerts",
        empty="This person has no route alerts.",
        note="What this person asked to be told about. Notifications are in the Trust tab.",
    )


def _interests_list(request, person, page, list_):
    from django.db.models import Q

    queryset = (
        TravelerInterest.objects.filter(
            Q(traveler=person) | Q(delivery_request__sender=person)
        )
        .select_related("traveler", "delivery_request__sender")
        .order_by("-created_at", "-pk")
    )
    page_obj = page(request, queryset)
    rows = []
    for interest in page_obj.object_list:
        sent = interest.traveler_id == person.pk
        other = interest.delivery_request.sender if sent else interest.traveler
        rows.append({
            "cells": (
                text_cell("Sent" if sent else "Received", kind="strong"),
                text_cell(other.email),
                text_cell(f"Request {interest.delivery_request_id}"),
                text_cell(
                    f"Journey {interest.journey_id}",
                    href=reverse("admin_console:journey-detail", args=(interest.journey_id,)),
                ),
                datetime_cell(interest.created_at),
            )
        })
    return list_(
        ("Direction", "Other member", "Request", "Journey", "When"),
        rows, page_obj=page_obj, layout="interests",
        empty="No “I can carry this” signals involve this person.",
        note="A signal is a notification only: it is never an offer and reserves nothing.",
    )


def build_discovery(request, person, caps, header, source, *, tab_url, page, list_):
    current = request.GET.get("view", "")
    if current not in dict(DISCOVERY_VIEWS):
        current = DISCOVERY_VIEWS[0][0]
    builders = {"alerts": _alerts_list, "interests": _interests_list}
    return {
        "profile": _profile_summary(person, caps, source),
        "views": [
            {"key": key, "label": label, "current": key == current,
             "url": tab_url(person, "discovery", source=source, view=key)}
            for key, label in DISCOVERY_VIEWS
        ],
        "list": builders[current](request, person, page, list_),
    }


def profile_visibility(request, pk: int):
    """Hide a public profile, or show it again. `manage_users`, audited."""

    from .console_views import _operation_error, _render

    person = get_object_or_404(User, pk=pk)
    profile = PublicProfile.objects.filter(user=person).first()
    hiding = profile is None or profile.hidden_at is None
    form = ProfileVisibilityForm(request.POST or None)
    back = reverse("admin_console:user-detail", args=(person.pk,)) + "?tab=discovery"
    if request.method == "POST" and form.is_valid():
        try:
            set_profile_hidden(
                user=person,
                actor=request.user,
                hidden=hiding,
                reason=form.cleaned_data["reason"],
            )
            messages.success(
                request,
                "The public profile is hidden." if hiding else "The public profile can be seen again.",
            )
            return redirect(back)
        except DiscoveryError as exc:
            _operation_error(request, "Public profile visibility", exc)
    return _render(
        request,
        "admin/console/action_form.html",
        {
            "title": "Hide public profile" if hiding else "Show public profile again",
            "description": (
                "The profile disappears from discovery at once. The member keeps their own "
                "choice and sees only that the profile is not currently visible."
                if hiding
                else "The member's own choice applies again: if they had turned the profile "
                "on, it is visible from the next request."
            ),
            "form": form,
            "submit_label": "Hide profile" if hiding else "Show profile again",
            "danger": hiding,
            "back_url": back,
        },
    )
