"""Banning a member's account, or restoring it, from the person page (plan L16).

One audited action with a required reason, `manage_users` only (Super Admin).
The rule lives in `staff_actions.set_account_ban`: staff accounts are changed
on Staff & access and nobody bans their own account. A ban signs the person
out; it does not cancel deliveries, move money or release a payout.
"""

from __future__ import annotations

from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse

from .console_forms import ConsoleForm
from .people_links import display_name
from .permissions import has_admin_permission
from .staff_actions import BAN_PERMISSION, StaffActionError, ban_refusal, set_account_ban

User = get_user_model()


class AccountBanForm(ConsoleForm):
    reason = forms.CharField(
        max_length=500,
        label="Reason",
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Recorded in the audit log and kept internal. The person is not shown it.",
    )


def header_action(request, person) -> dict | None:
    """The person page's "Ban account" or "Restore account" link, when it applies."""

    if not has_admin_permission(request.user, BAN_PERMISSION):
        return None
    if ban_refusal(request.user, person, banned=not person.is_banned) is not None:
        return None
    return {
        "label": "Restore account" if person.is_banned else "Ban account",
        "url": reverse("admin_console:user-ban", args=(person.pk,)),
        "primary": False,
    }


def account_ban(request, pk: int):
    from .console_views import _operation_error, _render

    person = get_object_or_404(User, pk=pk)
    banning = not person.is_banned
    refusal = ban_refusal(request.user, person, banned=banning)
    form = AccountBanForm(request.POST or None)
    back = reverse("admin_console:user-detail", args=(person.pk,))
    if request.method == "POST" and refusal is None and form.is_valid():
        try:
            set_account_ban(
                actor=request.user,
                user_id=person.pk,
                banned=banning,
                reason=form.cleaned_data["reason"],
            )
        except StaffActionError as exc:
            _operation_error(request, "Changing the account", exc)
        else:
            messages.success(
                request,
                "The account is banned. The person is signed out and cannot sign in."
                if banning
                else "The account is restored. The person can sign in again.",
            )
            return redirect(back)
    who = f"{display_name(person)} (person {person.pk})"
    if refusal is not None:
        description = str(refusal)
    elif banning:
        description = (
            f"{who} is signed out at once and cannot sign in, including in the middle "
            "of a delivery. Their deliveries, payments and payouts are not changed."
        )
    else:
        description = f"{who} becomes active again and can sign in."
    return _render(
        request,
        "admin/console/action_form.html",
        {
            "title": "Ban account" if banning else "Restore account",
            "description": description,
            "form": form if refusal is None else None,
            "submit_label": "Ban account" if banning else "Restore account",
            "danger": banning,
            "back_url": back,
        },
    )
