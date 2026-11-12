"""Sea crossings in the Geography console (L3B).

A crossing is one direction of a ferry line between two catalogue cities. The
rules live in `apps.locations.sea_crossings`: a reason for every change, one
audit row per change, permission `manage_settings`. These views only collect
the reason and show the result, so the page and the domain command cannot
disagree about who may act or what a change does.
"""

from __future__ import annotations

from decimal import Decimal

from django import forms
from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse

from apps.core.business_settings import NoActiveBusinessSettings
from apps.core.marketplace_policy import InvalidMarketplacePolicy, marketplace_policy
from apps.locations.models import Country, SeaCrossing
from apps.locations.sea_crossings import (
    MANAGE_CROSSINGS_PERMISSION,
    MAX_CROSSING_DISTANCE_KM,
    SeaCrossingError,
    activate_crossing,
    create_crossing,
    deactivate_crossing,
    resolve_port,
)

from .console_forms import ConsoleForm
from .permissions import has_admin_permission

BACK_URL_NAME = "admin_console:geography"
ANCHOR = "#st-sea-crossings"

#: Refusals that belong to a field of the add form rather than to the page.
_FIELD_FOR_CODE = {
    "sea_crossing_distance_required": "distance_km",
    "sea_crossing_distance_invalid": "distance_km",
    "sea_crossing_ports_identical": "destination_city",
    "sea_crossing_exists": None,  # a form-level error
}


def may_manage_crossings(user) -> bool:
    return has_admin_permission(user, MANAGE_CROSSINGS_PERMISSION)


def sea_switch_state() -> bool | None:
    """The "Sea legs" switch, or None when the settings cannot be read."""

    try:
        return marketplace_policy().sea_legs_enabled
    except (NoActiveBusinessSettings, InvalidMarketplacePolicy):
        return None


def crossing_rows(user) -> list[dict]:
    """Every crossing for the Geography page, with the action that fits it."""

    may_manage = may_manage_crossings(user)
    crossings = SeaCrossing.objects.select_related(
        "origin_locality__country", "destination_locality__country"
    ).order_by("origin_locality__name", "destination_locality__name", "pk")
    rows = []
    for crossing in crossings:
        action = None
        if may_manage:
            name = "deactivate" if crossing.is_active else "activate"
            action = {
                "label": "Turn off" if crossing.is_active else "Turn on",
                "url": reverse(
                    "admin_console:sea-crossing-toggle", args=(crossing.pk, name)
                ),
            }
        rows.append(
            {
                "origin": crossing.origin_locality,
                "destination": crossing.destination_locality,
                "kilometres": round(crossing.distance_meters / 1000),
                "is_active": crossing.is_active,
                "action": action,
            }
        )
    return rows


class SeaCrossingForm(ConsoleForm):
    origin_country = forms.ModelChoiceField(
        queryset=Country.objects.order_by("name"),
        label="From: country",
        empty_label=None,
    )
    origin_city = forms.CharField(
        max_length=200,
        label="From: city",
        help_text="The catalogue name, for example Marseille.",
    )
    destination_country = forms.ModelChoiceField(
        queryset=Country.objects.order_by("name"),
        label="To: country",
        empty_label=None,
    )
    destination_city = forms.CharField(
        max_length=200,
        label="To: city",
        help_text="The catalogue name, for example Algiers.",
    )
    distance_km = forms.DecimalField(
        required=False,
        min_value=Decimal("0.001"),
        max_value=MAX_CROSSING_DISTANCE_KM,
        max_digits=7,
        decimal_places=3,
        label="Distance in kilometres",
        help_text=(
            "Needed only when a city has no catalogue coordinates (most French "
            "and Spanish cities). Great-circle distance, measured the same way "
            "as a flight."
        ),
    )
    start_active = forms.BooleanField(
        required=False,
        label="Turn it on straight away",
        help_text=(
            "Left unchecked, the crossing is saved switched off. A sea leg can "
            "use a crossing only while it is on and the Sea legs switch in "
            "Settings is on."
        ),
    )
    reason = forms.CharField(
        max_length=500,
        label="Reason",
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Recorded in the audit log.",
    )

    origin = None
    destination = None

    def clean(self):
        cleaned = super().clean()
        for side in ("origin", "destination"):
            country = cleaned.get(f"{side}_country")
            city = cleaned.get(f"{side}_city")
            if country is None or not city:
                continue
            place, why = resolve_port(country.code, city)
            if place is None:
                self.add_error(f"{side}_city", f"This city cannot be used: {why}.")
            setattr(self, side, place)
        return cleaned


class CrossingReasonForm(ConsoleForm):
    reason = forms.CharField(
        max_length=500,
        label="Reason",
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Recorded in the audit log.",
    )


def _line(crossing: SeaCrossing) -> str:
    origin, destination = crossing.origin_locality, crossing.destination_locality
    return (
        f"{origin.name}, {origin.country_id} → {destination.name}, "
        f"{destination.country_id}"
    )


def sea_crossing_new(request):
    from .console_views import _operation_error, _render

    form = SeaCrossingForm(request.POST or None)
    back = reverse(BACK_URL_NAME) + ANCHOR
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            crossing = create_crossing(
                actor=request.user,
                origin_locality_id=form.origin.pk,
                destination_locality_id=form.destination.pk,
                reason=data["reason"],
                active=data["start_active"],
                distance_km=data["distance_km"],
            )
        except SeaCrossingError as exc:
            if exc.code in _FIELD_FOR_CODE:
                form.add_error(_FIELD_FOR_CODE[exc.code], exc.message)
            else:
                _operation_error(request, "Adding the sea crossing", exc)
        else:
            messages.success(
                request,
                f"{_line(crossing)} was added"
                f"{' and is on' if crossing.is_active else ', switched off'}.",
            )
            return redirect(back)
    return _render(
        request,
        "admin/console/action_form.html",
        {
            "title": "Add a sea crossing",
            "description": (
                "One direction of a ferry line between two catalogue cities. Add the "
                "return direction as its own crossing. Nothing changes for members "
                "until the crossing is on and the Sea legs switch is on."
            ),
            "form": form,
            "submit_label": "Add crossing",
            "danger": False,
            "back_url": back,
        },
    )


def sea_crossing_toggle(request, pk: int, action: str):
    from .console_views import _operation_error, _render

    if action not in ("activate", "deactivate"):
        raise Http404
    crossing = get_object_or_404(
        SeaCrossing.objects.select_related(
            "origin_locality__country", "destination_locality__country"
        ),
        pk=pk,
    )
    turning_on = action == "activate"
    form = CrossingReasonForm(request.POST or None)
    back = reverse(BACK_URL_NAME) + ANCHOR
    line = _line(crossing)
    if request.method == "POST" and form.is_valid():
        change = activate_crossing if turning_on else deactivate_crossing
        try:
            change(
                actor=request.user,
                crossing_id=crossing.pk,
                reason=form.cleaned_data["reason"],
            )
        except SeaCrossingError as exc:
            _operation_error(request, "Changing the sea crossing", exc)
        else:
            messages.success(request, f"{line} is now {'on' if turning_on else 'off'}.")
            return redirect(back)
    return _render(
        request,
        "admin/console/action_form.html",
        {
            "title": f"{'Turn on' if turning_on else 'Turn off'} {line}",
            "description": (
                "Travelers can use this line for sea legs again, from the next request."
                if turning_on
                else "New sea legs and new offers on every journey that uses this line "
                "stop from the next request. Funded deals are never touched."
            ),
            "form": form,
            "submit_label": "Turn on" if turning_on else "Turn off",
            "danger": not turning_on,
            "back_url": back,
        },
    )
