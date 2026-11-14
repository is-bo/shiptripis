"""The two-step pages under ``/admin/two-step/`` (spec 19.1, L14).

Reached after the password, before anything else in the console:

* ``two-step/``: sends the person to enrolment or to the code page;
* ``two-step/enrol/``: the QR code, the same key as text, and a code to confirm;
* ``two-step/recovery-codes/``: the ten recovery codes, shown once;
* ``two-step/verify/``: a code from the app. Also where a step that needs a
  *fresh* code (spec 19.1) sends someone who entered theirs too long ago;
* ``two-step/recovery/``: a recovery code instead of the app.

Each page needs a signed-in staff member and nothing more: the middleware
leaves this prefix open precisely so these pages can be reached. Every decision
is `apps.admin_panel.two_step`'s; these views only render it.
"""

from __future__ import annotations

from urllib.parse import urlencode

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.http import HttpResponseRedirect
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters

from . import two_step
from .console_forms import ConsoleForm
from .permissions import has_admin_access


class CodeForm(ConsoleForm):
    code = forms.CharField(
        label="6-digit code",
        max_length=12,
        strip=True,
        widget=forms.TextInput(
            attrs={
                "autocomplete": "one-time-code",
                "inputmode": "numeric",
                "autofocus": True,
                "spellcheck": "false",
                "dir": "ltr",
                "class": "st-code-input",
            }
        ),
    )


class RecoveryCodeForm(ConsoleForm):
    code = forms.CharField(
        label="Recovery code",
        max_length=40,
        strip=True,
        widget=forms.TextInput(
            attrs={
                "autocomplete": "off",
                "autocapitalize": "none",
                "autofocus": True,
                "spellcheck": "false",
                "dir": "ltr",
                "class": "st-code-input",
                "placeholder": "xxxx-xxxx-xxxx-xxxx",
            }
        ),
    )


def _next_url(request) -> str:
    """Where to go afterwards: a console address on this host, or the overview."""

    candidate = request.POST.get("next") or request.GET.get("next") or ""
    if (
        candidate
        and candidate.startswith("/admin/")
        and not candidate.startswith(reverse("admin_console:two-step"))
        and url_has_allowed_host_and_scheme(
            candidate,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        )
    ):
        return candidate
    return reverse("admin_console:overview")


def _with_next(route: str, next_url: str) -> str:
    return f"{reverse(route)}?{urlencode({'next': next_url})}"


def _staff_only(view):
    """Signed-in staff only; everyone else goes to the password sign-in."""

    def wrapped(request, *args, **kwargs):
        if not has_admin_access(request.user):
            return HttpResponseRedirect(
                f"{reverse('admin:login')}?{urlencode({'next': request.get_full_path()})}"
            )
        return view(request, *args, **kwargs)

    wrapped.__name__ = view.__name__
    wrapped.__doc__ = view.__doc__
    return never_cache(wrapped)


def _render(request, template: str, context: dict, *, status: int = 200):
    response = render(
        request,
        template,
        {
            **admin.site.each_context(request),
            "next_url": _next_url(request),
            **context,
        },
        status=status,
    )
    response["Cache-Control"] = "private, no-store"
    return response


def _refusal(outcome: two_step.Outcome, wrong: str) -> str:
    """The message for a refused code; a lockout has its own notice instead."""

    return "" if outcome.reason == two_step.LOCKED else wrong


WRONG_APP_CODE = (
    "That code did not work. Check that the time on your phone is set "
    "automatically, then try the newest code."
)
WRONG_RECOVERY_CODE = "That recovery code did not work, or it was already used."


@_staff_only
def start(request):
    """Enrolment for a first sign-in, the code page for everyone else."""

    route = (
        "admin_console:two-step-verify"
        if two_step.is_enrolled(request.user)
        else "admin_console:two-step-enrol"
    )
    return redirect(_with_next(route, _next_url(request)))


@_staff_only
@sensitive_post_parameters("code")
def enrol(request):
    next_url = _next_url(request)
    if two_step.is_enrolled(request.user):
        return redirect(_with_next("admin_console:two-step-verify", next_url))
    try:
        row = two_step.pending_enrolment(request.user)
    except ValidationError:
        return redirect(_with_next("admin_console:two-step-verify", next_url))
    except ImproperlyConfigured:
        # Only a server without the encryption keyring gets here; production
        # refuses to start without one. Say so rather than fail.
        return _render(
            request,
            "admin/two_step/unavailable.html",
            {"title": "Two-step sign-in is not available"},
            status=503,
        )
    form = CodeForm(request.POST or None)
    error = ""
    locked_until = None
    if request.method == "POST" and form.is_valid():
        outcome = two_step.confirm_enrolment(request.user, form.cleaned_data["code"])
        if outcome.ok:
            two_step.mark_verified(request, request.user)
            request.session[two_step.RECOVERY_DISPLAY_SESSION_KEY] = outcome.recovery_codes
            return redirect(_with_next("admin_console:two-step-recovery-codes", next_url))
        if outcome.reason == two_step.ALREADY_ENROLLED:
            return redirect(_with_next("admin_console:two-step-verify", next_url))
        error = _refusal(outcome, WRONG_APP_CODE)
        locked_until = outcome.locked_until
        form = CodeForm()  # a refused code is never shown back
    secret = two_step.secret_text(row)
    return _render(
        request,
        "admin/two_step/enrol.html",
        {
            "title": "Set up two-step sign-in",
            "form": form,
            "error": error,
            "locked_until": locked_until,
            "qr_svg": two_step.qr_svg(two_step.provisioning_uri(request.user, secret)),
            "secret_grouped": two_step.grouped_secret(secret),
        },
        status=400 if (error or locked_until) else 200,
    )


@_staff_only
def recovery_codes(request):
    """The ten codes of a just-finished enrolment. They are shown once."""

    codes = request.session.pop(two_step.RECOVERY_DISPLAY_SESSION_KEY, None)
    if not codes or not two_step.two_step_satisfied(request):
        return redirect(_next_url(request))
    return _render(
        request,
        "admin/two_step/recovery_codes.html",
        {"title": "Save your recovery codes", "codes": codes},
    )


@_staff_only
@sensitive_post_parameters("code")
def verify(request):
    next_url = _next_url(request)
    if not two_step.is_enrolled(request.user):
        return redirect(_with_next("admin_console:two-step-enrol", next_url))
    confirming = two_step.two_step_satisfied(request)
    form = CodeForm(request.POST or None)
    error = ""
    locked_until = None
    if request.method == "POST" and form.is_valid():
        outcome = two_step.verify_code(request.user, form.cleaned_data["code"])
        if outcome.ok:
            two_step.mark_verified(request, request.user)
            return redirect(next_url)
        error = _refusal(outcome, WRONG_APP_CODE)
        locked_until = outcome.locked_until
        form = CodeForm()  # a refused code is never shown back
    return _render(
        request,
        "admin/two_step/verify.html",
        {
            "title": "Confirm it's you" if confirming else "Two-step sign-in",
            "confirming": confirming,
            "form": form,
            "error": error,
            "locked_until": locked_until,
            "fresh_minutes": two_step.FRESH_MINUTES,
        },
        status=400 if (error or locked_until) else 200,
    )


@_staff_only
@sensitive_post_parameters("code")
def recovery(request):
    next_url = _next_url(request)
    if not two_step.is_enrolled(request.user):
        return redirect(_with_next("admin_console:two-step-enrol", next_url))
    form = RecoveryCodeForm(request.POST or None)
    error = ""
    locked_until = None
    if request.method == "POST" and form.is_valid():
        outcome = two_step.use_recovery_code(request.user, form.cleaned_data["code"])
        if outcome.ok:
            two_step.mark_verified(request, request.user)
            left = outcome.recovery_codes_left
            messages.warning(
                request,
                f"You used a recovery code. {left} of {two_step.RECOVERY_CODE_COUNT} left."
                + (
                    " Ask a Super Admin to reset your two-step sign-in so you can set it up again."
                    if left <= 3
                    else ""
                ),
            )
            return redirect(next_url)
        error = _refusal(outcome, WRONG_RECOVERY_CODE)
        locked_until = outcome.locked_until
        form = RecoveryCodeForm()  # a refused code is never shown back
    return _render(
        request,
        "admin/two_step/recovery.html",
        {
            "title": "Use a recovery code",
            "form": form,
            "error": error,
            "locked_until": locked_until,
        },
        status=400 if (error or locked_until) else 200,
    )


def require_fresh_two_step(request, back_to: str):
    """``None`` when a code was entered recently, else the redirect to enter one.

    For the console steps spec 19.1 lists (staff role change, second-step
    reset; L15 adds helper keys). The POST that needed it is not replayed: the
    person comes back to ``back_to`` and does it again.
    """

    if two_step.fresh_two_step(request):
        return None
    messages.info(
        request,
        f"This change needs a code entered in the last {two_step.FRESH_MINUTES} minutes. "
        "Enter one, then make the change again.",
    )
    return redirect(_with_next("admin_console:two-step-verify", back_to))
