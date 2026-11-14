"""The AI helper on the console (spec 20.2, 20.4, 20.6 and 20.8, plans L15 and L16).

* `card` is the "AI helper" card on the overview: what it is, the admin's read
  and change keys, "Create read key (8 hours)", "Create change key (30
  minutes)" and "Stop key", and, in the response that created a key, the
  one-time copy block with its expiry. With the switch off it says so and
  offers nothing.
* `page` is the AI helper page: the changes waiting for the admin's
  confirmation, their recent decisions, the admin's keys and their recent
  calls; a Super Admin also sees every admin's live keys (never a key itself)
  and can stop any of them with a reason.
* `create` and `stop` are the key POSTs. Creating needs a code entered in the
  last 10 minutes; the plain key is rendered in that one response and never
  stored, logged or put in a session.
* `change` is one prepared change: its summary, record, values in words and
  the helper's reason, then "Confirm" with the admin's own reason, or "Reject"
  (`apps.admin_helper.prepared`). With the switch off it is read only.
* `AdminHelperSettingsForm` is the "AI helper" form of the Settings page.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from apps.admin_panel.console_forms import ConsoleForm
from apps.admin_panel.permissions import has_admin_permission

from . import policy as helper_policy
from . import prepared as changes
from .keys import (
    STOP_ANY_PERMISSION,
    HelperKeyError,
    current_policy,
    issue_key,
    key_state,
    stop_key,
)
from .models import AdminHelperCall, AdminHelperKey, PreparedAction
from .people import short_name

#: Where the AI helper lives on the console: the same pages as the overview.
PAGE_PERMISSION = "view_dashboard"
RECENT_CALLS = 50


def api_address(request) -> str:
    """This server's helper address, as the assistant is given it."""

    return request.build_absolute_uri(reverse("admin-helper-guide")).rsplit("/guide", 1)[0]


def _until(moment: datetime, now: datetime) -> str:
    local, today = timezone.localtime(moment), timezone.localtime(now).date()
    if local.date() == today:
        return local.strftime("%H:%M")
    if local.date() == today + timedelta(days=1):
        return f"{local:%H:%M} tomorrow"
    return f"{local:%d %b, %H:%M}"


def _live_keys(admin, now: datetime) -> dict[str, AdminHelperKey]:
    """The admin's live key of each kind, in one query (at most one per kind)."""

    live = AdminHelperKey.objects.filter(admin=admin, revoked_at__isnull=True, expires_at__gt=now)
    return {key.kind: key for key in live.order_by("created_at")}


def _key_line(key: AdminHelperKey | None, now: datetime) -> dict | None:
    if key is None:
        return None
    return {"id": key.pk, "hint": key.hint, "until": _until(key.expires_at, now)}


def card(request, *, issued=None) -> dict:
    """The overview card's context. ``issued`` is the `IssuedKey` this response
    shows once, or ``None``."""

    now = timezone.now()
    policy = current_policy()
    if policy is None or not policy.enabled:
        return {"enabled": False}
    keys = _live_keys(request.user, now)
    if issued is not None:
        keys[issued.key.kind] = issued.key
    return {
        "enabled": True,
        "read_hours": policy.read_key_hours,
        "change_minutes": policy.change_key_minutes,
        "read_key": _key_line(keys.get(AdminHelperKey.Kind.READ), now),
        "change_key": _key_line(keys.get(AdminHelperKey.Kind.CHANGE), now),
        "issued": (
            {
                # One line, exactly what the assistant needs (spec 20.7).
                "line": f"/wassla {api_address(request)} {issued.plain}",
                "kind": issued.key.kind,
                "until": _until(issued.key.expires_at, now),
            }
            if issued is not None
            else None
        ),
    }


def _state(key: AdminHelperKey, now: datetime) -> dict:
    state = key_state(key, at=now)
    if state == "live":
        return {"label": f"Active until {_until(key.expires_at, now)}", "tone": "ok", "live": True}
    if state == "expired":
        return {"label": "Expired", "tone": "mute", "live": False}
    return {"label": key.get_revoked_reason_display(), "tone": "mute", "live": False}


def _key_rows(keys, now: datetime, *, with_admin: bool = False) -> list[dict]:
    return [
        {
            "id": key.pk,
            "kind": key.get_kind_display(),
            "hint": key.hint,
            "created_at": key.created_at,
            "last_used_at": key.last_used_at,
            "use_count": key.use_count,
            "state": _state(key, now),
            "admin": (
                {"id": key.admin_id, "name": short_name(key.admin), "email": key.admin.email}
                if with_admin
                else None
            ),
        }
        for key in keys
    ]


#: What a prepared change's record is called on the console, by target type.
_RECORD_WORDS = {
    "deal": "the delivery",
    "dispute": "the dispute",
    "person": "the person",
    "problem": "the report",
    "payment": "the payment",
    "journey": "the journey",
    "sea_crossing": "the sea crossings",
    "job": "the background job",
    "payout": "the payout",
    "review_report": "the review",
}
RECENT_DECISIONS = 20


def record_link(prepared: PreparedAction) -> dict:
    """The console page of a change's record, as a link."""

    from .resources import REGISTRY

    if prepared.target_type == "sea_crossing":
        url = reverse("admin_console:geography")
    else:
        url = REGISTRY[prepared.target_type].console_path_for(prepared.target_id)
    return {"label": f"Open {_RECORD_WORDS[prepared.target_type]}", "url": url}


def _status_tone(prepared: PreparedAction) -> str:
    return {
        PreparedAction.Status.WAITING: "wait",
        PreparedAction.Status.CONFIRMED: "ok",
        PreparedAction.Status.FAILED: "bad",
    }.get(prepared.status, "mute")


def _change_row(request, prepared: PreparedAction, now: datetime) -> dict:
    look = changes.look(request.user, prepared) if prepared.status == PreparedAction.Status.WAITING else None
    return {
        "id": prepared.pk,
        "url": reverse("admin_console:ai-helper-change", args=(prepared.pk,)),
        "summary": prepared.summary,
        "title": look.entry.title if look and look.entry else "",
        "record": record_link(prepared),
        "details": look.details if look else [],
        "problem": look.problem if look else "",
        "helper_reason": prepared.helper_reason,
        "created_at": prepared.created_at,
        "until": _until(prepared.expires_at, now),
        "status": prepared.get_status_display(),
        "tone": _status_tone(prepared),
        "decided_at": prepared.decided_at,
        "outcome": (prepared.outcome or {}).get("message", ""),
    }


def page_context(request) -> dict:
    now = timezone.now()
    admin = request.user
    waiting = [_change_row(request, row, now) for row in changes.waiting_for(admin, at=now)]
    decided = [
        _change_row(request, row, now)
        for row in PreparedAction.objects.filter(admin=admin)
        .exclude(status=PreparedAction.Status.WAITING)
        .order_by("-decided_at", "-pk")[:RECENT_DECISIONS]
    ]
    may_stop_any = has_admin_permission(admin, STOP_ANY_PERMISSION)
    own = AdminHelperKey.objects.filter(admin=admin).order_by("-created_at")[:20]
    calls = (
        AdminHelperCall.objects.filter(key__admin=admin)
        .select_related("key")
        .order_by("-at", "-pk")[:RECENT_CALLS]
    )
    everyone = []
    if may_stop_any:
        everyone = _key_rows(
            AdminHelperKey.objects.filter(revoked_at__isnull=True, expires_at__gt=now)
            .exclude(admin=admin)
            .select_related("admin")
            .order_by("admin__email", "kind"),
            now,
            with_admin=True,
        )
    helper = card(request)
    return {
        "title": "AI helper",
        "helper": helper,
        "waiting": waiting,
        "decided": decided,
        # Read only with the switch off (spec 20.8).
        "may_decide": helper["enabled"],
        "own_keys": _key_rows(own, now),
        "calls": [
            {"at": call.at, "hint": call.key.hint, "method": call.method,
             "path": call.path, "status": call.status, "ok": call.status < 400}
            for call in calls
        ],
        "may_stop_any": may_stop_any,
        "everyone": everyone,
        "api_address": api_address(request),
    }


def _render_page(request, template: str, context: dict):
    from apps.admin_panel.console_views import _render

    response = _render(request, template, context)
    # A page that may carry a key must never be stored by anything.
    response["Cache-Control"] = "no-store"
    return response


# The three views below are routed through the console's `capability_required`
# with `PAGE_PERMISSION` (`apps/admin_panel/console_urls.py`), like every
# console page: staff only, past the second step, with that capability.


def page(request):
    return _render_page(request, "admin/console/ai_helper.html", page_context(request))


def _back(request) -> str:
    return (
        reverse("admin_console:ai-helper")
        if request.POST.get("from") == "page"
        else f"{reverse('admin_console:overview')}#st-ai-helper"
    )


@never_cache
@require_POST
def create(request):
    """Create the admin's read or change key and show it once, in this response."""

    from apps.admin_panel.console_two_step import require_fresh_two_step

    back = _back(request)
    kind = request.POST.get("kind", AdminHelperKey.Kind.READ)
    if kind not in AdminHelperKey.Kind.values:
        raise Http404
    if (refused := require_fresh_two_step(request, back)) is not None:
        return refused
    try:
        issued = issue_key(admin=request.user, kind=kind, request=request)
    except HelperKeyError as exc:
        messages.error(request, str(exc))
        return redirect(back)
    if request.POST.get("from") == "page":
        context = page_context(request)
        context["helper"] = card(request, issued=issued)
        return _render_page(request, "admin/console/ai_helper.html", context)
    from apps.admin_panel.console_views import overview_context

    context = overview_context(request)
    context["helper"] = card(request, issued=issued)
    return _render_page(request, "admin/console/overview.html", context)


class StopKeyForm(ConsoleForm):
    reason = forms.CharField(
        required=False,
        max_length=500,
        label="Why stop this admin's key?",
        widget=forms.TextInput(attrs={"placeholder": "Required for another admin's key"}),
    )


@never_cache
@require_POST
def stop(request, pk):
    back = _back(request)
    form = StopKeyForm(request.POST)
    form.is_valid()
    try:
        key = stop_key(actor=request.user, key_id=pk, reason=form.cleaned_data.get("reason", ""))
    except AdminHelperKey.DoesNotExist:
        messages.error(request, "That key does not exist.")
    except HelperKeyError as exc:
        messages.error(request, f"{exc} Write why you are stopping this admin's key.")
    except PermissionDenied as exc:
        messages.error(request, str(exc))
    else:
        whose = "Your" if key.admin_id == request.user.pk else f"{short_name(key.admin)}'s"
        messages.success(request, f"{whose} key ending {key.hint} is stopped. It no longer works.")
    return redirect(back)


class AdminHelperSettingsForm(ConsoleForm):
    """Spec 20.8: the switch, the key durations, the validity of prepared
    actions and the rate limit, saved as one audited settings revision."""

    enabled = forms.BooleanField(
        required=False,
        label="AI helper is on",
        help_text=(
            "Off: every key stops at once and for good, and no key can be created. "
            "Turning it on again revives none of them."
        ),
    )
    read_key_hours = forms.IntegerField(
        min_value=helper_policy.bounds("read_key_hours")[0],
        max_value=helper_policy.bounds("read_key_hours")[1],
        label="A read key lasts, in hours",
        help_text="From its creation, even while it is used. Applies to keys created from now on.",
    )
    change_key_minutes = forms.IntegerField(
        min_value=helper_policy.bounds("change_key_minutes")[0],
        max_value=helper_policy.bounds("change_key_minutes")[1],
        label="A change key lasts, in minutes",
        help_text=(
            "From its creation. A change key adds notes, acknowledges problems and prepares "
            "other changes for its admin to confirm. Applies to keys created from now on."
        ),
    )
    prepared_action_valid_hours = forms.IntegerField(
        min_value=helper_policy.bounds("prepared_action_valid_hours")[0],
        max_value=helper_policy.bounds("prepared_action_valid_hours")[1],
        label="A prepared change waits for its admin, in hours",
        help_text="Then it expires unconfirmed. Applies to changes prepared from now on.",
    )
    requests_per_minute = forms.IntegerField(
        min_value=helper_policy.bounds("requests_per_minute")[0],
        max_value=helper_policy.bounds("requests_per_minute")[1],
        label="Calls one key may make per minute",
    )
    reason = forms.CharField(
        max_length=500,
        label="Reason for change",
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    confirm = forms.BooleanField(
        label="I understand this applies to every admin's AI helper from the next call."
    )

    @staticmethod
    def initial_from(policy: helper_policy.AdminHelperPolicy) -> dict:
        return {
            "enabled": policy.enabled,
            "read_key_hours": policy.read_key_hours,
            "change_key_minutes": policy.change_key_minutes,
            "prepared_action_valid_hours": policy.prepared_action_valid_hours,
            "requests_per_minute": policy.requests_per_minute,
        }

    def path_updates(self) -> dict:
        return {
            f"{helper_policy.SECTION}.{name}": self.cleaned_data[name]
            for name in (
                "enabled",
                "read_key_hours",
                "change_key_minutes",
                "prepared_action_valid_hours",
                "requests_per_minute",
            )
        }


class ConfirmChangeForm(ConsoleForm):
    """The admin's own reason for a change, pre-filled with the helper's. Its
    longest length is the console form's own for that action."""

    def __init__(self, *args, max_length: int, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["reason"] = forms.CharField(
            max_length=max_length,
            label="Your reason",
            widget=forms.Textarea(attrs={"rows": 3}),
            help_text="Recorded in the audit log as yours. Change it if the AI helper's words "
            "are not yours.",
        )


def _heading(title: str) -> str:
    """A registry title as a page heading: its first clause, without the full
    stop ("Ban a member's account. They are signed out at once." reads "Ban a
    member's account"). The server's summary below says the rest."""

    return re.split(r"\. |: |; | \(", title, maxsplit=1)[0].rstrip(".")


@never_cache
def change(request, pk):
    """One prepared change: read it, then confirm it or reject it. Only its own admin."""

    now = timezone.now()
    prepared = PreparedAction.objects.filter(pk=pk, admin=request.user).first()
    if prepared is None:
        raise Http404
    look = changes.look(request.user, prepared)
    max_length = look.entry.reason_max_length if look.entry else PreparedAction.REASON_MAX_LENGTH
    decision = request.POST.get("decision", "") if request.method == "POST" else ""
    form = ConfirmChangeForm(
        request.POST if decision == "confirm" else None,
        initial={"reason": prepared.helper_reason},
        max_length=max_length,
    )
    here = reverse("admin_console:ai-helper-change", args=(prepared.pk,))
    if request.method == "POST":
        if decision not in ("confirm", "reject"):
            raise Http404
        try:
            if decision == "reject":
                result = changes.reject(request=request, action_id=prepared.pk)
            elif form.is_valid():
                result = changes.confirm(
                    request=request, action_id=prepared.pk, reason=form.cleaned_data["reason"]
                )
            else:
                result = False
        except changes.NotDecidable as exc:
            messages.error(request, str(exc))
            return redirect(here)
        if result is None:
            raise Http404
        if result is not False:
            if result.status == PreparedAction.Status.CONFIRMED:
                messages.success(request, result.message)
            elif result.status == PreparedAction.Status.REJECTED:
                messages.info(request, result.message)
            else:
                messages.error(request, result.message)
            return redirect(here)
    policy = current_policy()
    enabled = policy is not None and policy.enabled
    waiting = prepared.status == PreparedAction.Status.WAITING and prepared.expires_at > now
    others = changes.waiting_for(request.user, at=now).exclude(pk=prepared.pk).count()
    return _render_page(
        request,
        "admin/console/ai_helper_change.html",
        {
            "title": _heading(look.entry.title) if look.entry else "A change your AI helper prepared",
            "change": prepared,
            "status": PreparedAction.Status.EXPIRED.label
            if prepared.status == PreparedAction.Status.WAITING and not waiting
            else prepared.get_status_display(),
            "tone": "mute" if prepared.status == PreparedAction.Status.WAITING and not waiting
            else _status_tone(prepared),
            "record": record_link(prepared),
            "details": look.details,
            "fresh_note": look.entry.fresh_note if look.fresh and look.entry else "",
            "problem": look.problem,
            "waiting": waiting,
            "may_decide": waiting and enabled,
            "switched_off": not enabled,
            "until": _until(prepared.expires_at, now),
            "outcome": (prepared.outcome or {}).get("message", ""),
            "your_reason": (prepared.outcome or {}).get("reason", ""),
            "form": form,
            "others": others,
            "back_url": f"{reverse('admin_console:ai-helper')}#st-helper-waiting",
        },
    )
