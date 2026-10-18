"""Browser acceptance for the existing role-bound invitation contract.

New links carry the capability in a fragment. The browser puts it in a hidden
POST field and clears the address bar; GET never consumes or looks up a token.
"""

import secrets
from types import SimpleNamespace

from django import forms
from django.contrib.auth import authenticate, get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import render
from django.utils import translation
from django.utils.translation import gettext as _, gettext_lazy
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.http import require_http_methods
from rest_framework.throttling import ScopedRateThrottle

from apps.core.languages import normalize_communication_language
from .models import AdminInvitation
from .services import accept_admin_invitation


class AcceptanceForm(forms.Form):
    token = forms.CharField(max_length=256, widget=forms.HiddenInput)
    password = forms.CharField(
        max_length=256,
        required=False,
        strip=False,
        label=gettext_lazy("Password"),
        widget=forms.PasswordInput,
    )
    full_name = forms.CharField(
        max_length=120, required=False, label=gettext_lazy("Name (optional)")
    )


@require_http_methods(["GET", "POST"])
@csrf_protect
@sensitive_post_parameters("token", "password")
@sensitive_variables("token", "password", "form", "invitation")
def invitation_accept_page(request):
    language = normalize_communication_language(request.GET.get("language"))
    with translation.override(language):
        form = AcceptanceForm(request.POST if request.method == "POST" else None)
        accepted, status = False, 200
        error = _(
            "The invitation could not be accepted. Check the link and password, or contact your administrator."
        )
        if request.method == "POST":
            try:
                # Same cache, identity derivation and login budget as the API.
                allowed = ScopedRateThrottle().allow_request(
                    request, SimpleNamespace(throttle_scope="login")
                )
            except Exception:
                allowed, status = False, 503  # authentication fails closed
            if not allowed:
                status = 429 if status != 503 else status
                form.add_error(None, _("Please try again later."))
            elif form.is_valid():
                token = form.cleaned_data["token"]
                password = form.cleaned_data["password"]
                invitation = AdminInvitation.resolve(token)
                principal = request.user if request.user.is_authenticated else None
                if invitation and principal is None:
                    existing = (
                        get_user_model()
                        .objects.filter(email__iexact=invitation.email)
                        .first()
                    )
                    if existing:
                        principal = authenticate(
                            request, username=existing.get_username(), password=password
                        )
                try:
                    accept_admin_invitation(
                        plaintext_token=token,
                        password=password,
                        full_name=form.cleaned_data["full_name"],
                        authenticated_user=principal,
                    )
                except (ValidationError, PermissionDenied):
                    form.add_error(None, error)
                    status = 400
                else:
                    accepted = True
            else:
                status = 400
        nonce = secrets.token_urlsafe(18)
        response = render(
            request,
            "admin/invitation_accept.html",
            {
                "lang": language,
                "dir": "rtl" if language == "ar" else "ltr",
                "t": {"title": _("Accept your invitation"), "languages": _("Language")},
                "form": form,
                "accepted": accepted,
                "nonce": nonce,
            },
            status=status,
        )
        response["Cache-Control"] = "no-store, private"
        response["Referrer-Policy"] = "no-referrer"
        response["Content-Security-Policy"] = (
            "default-src 'self'; base-uri 'none'; frame-ancestors 'none'; "
            "form-action 'self'; object-src 'none'; style-src 'self' 'unsafe-inline'; "
            f"script-src 'nonce-{nonce}'"
        )
        return response
