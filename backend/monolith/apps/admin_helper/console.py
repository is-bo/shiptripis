"""The AI helper on the console (spec 20.2, 20.6 and 20.8, plan L15).

* `card` is the "AI helper" card on the overview: what it is, the admin's read
  key, "Create read key (8 hours)" and "Stop key", and, in the response that
  created a key, the one-time copy block. With the switch off it says so and
  offers nothing.
* `page` is the AI helper page: the admin's keys and their recent calls; a
  Super Admin also sees every admin's live keys (never a key itself) and can
  stop any of them with a reason.
* `create` and `stop` are the two POSTs. Creating needs a code entered in the
  last 10 minutes; the plain key is rendered in that one response and never
  stored, logged or put in a session.
* `AdminHelperSettingsForm` is the "AI helper" form of the Settings page.

There is no change key here: it arrives in L16, with its own button.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from apps.admin_panel.console_forms import ConsoleForm
from apps.admin_panel.permissions import has_admin_permission

from . import policy as helper_policy
from .keys import (
    STOP_ANY_PERMISSION,
    HelperKeyError,
    current_policy,
    issue_key,
    key_state,
    stop_key,
)
from .models import AdminHelperCall, AdminHelperKey
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


def _live_read_key(admin, now: datetime) -> AdminHelperKey | None:
    return (
        AdminHelperKey.objects.filter(
            admin=admin,
            kind=AdminHelperKey.Kind.READ,
            revoked_at__isnull=True,
            expires_at__gt=now,
        )
        .order_by("-created_at")
        .first()
    )


def card(request, *, issued=None) -> dict:
    """The overview card's context. ``issued`` is the `IssuedKey` this response
    shows once, or ``None``."""

    now = timezone.now()
    policy = current_policy()
    if policy is None or not policy.enabled:
        return {"enabled": False}
    key = issued.key if issued is not None else _live_read_key(request.user, now)
    return {
        "enabled": True,
        "read_hours": policy.read_key_hours,
        "read_key": (
            {"id": key.pk, "hint": key.hint, "until": _until(key.expires_at, now)}
            if key is not None
            else None
        ),
        "issued": (
            {
                # One line, exactly what the assistant needs (spec 20.7).
                "line": f"/wassla {api_address(request)} {issued.plain}",
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


def page_context(request) -> dict:
    now = timezone.now()
    admin = request.user
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
    return {
        "title": "AI helper",
        "helper": card(request),
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
    """Create the admin's read key and show it once, in this response."""

    from apps.admin_panel.console_two_step import require_fresh_two_step

    back = _back(request)
    if (refused := require_fresh_two_step(request, back)) is not None:
        return refused
    try:
        issued = issue_key(admin=request.user, kind=AdminHelperKey.Kind.READ, request=request)
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
        help_text="Change keys are not offered yet.",
    )
    prepared_action_valid_hours = forms.IntegerField(
        min_value=helper_policy.bounds("prepared_action_valid_hours")[0],
        max_value=helper_policy.bounds("prepared_action_valid_hours")[1],
        label="A prepared change waits for its admin, in hours",
        help_text="Prepared changes are not offered yet.",
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
