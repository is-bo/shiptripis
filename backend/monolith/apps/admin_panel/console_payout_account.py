"""Retiring a Traveler's Stripe payout account from the console (F1b).

For an account opened for the wrong country: Stripe never changes an account's
country, so Finance retires it and the Traveler's next onboarding opens a new
one for the country now declared. The rule, the locks and the audit row live in
`apps.finance.payout_accounts.retire_account`; this view only collects the reason.
"""

from __future__ import annotations

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect

from apps.finance.models import StripePayoutAccount
from apps.finance.payout_accounts import account_country, mask_account, retire_account

from .console_forms import ConsoleForm
from .console_people import _tab_url


class RetireAccountForm(ConsoleForm):
    reason = forms.CharField(
        max_length=500,
        label="Reason",
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Recorded in the audit log. The traveler is not shown it.",
    )


def payout_account_retire(request, pk: int):
    """`retry_payouts` only; the guard is on the URL, the domain re-checks it."""

    from .console_views import _render

    account = get_object_or_404(StripePayoutAccount.objects.select_related("traveler"), pk=pk)
    back = _tab_url(account.traveler, "payouts")
    form = RetireAccountForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            retire_account(
                actor=request.user, account_id=account.pk, reason=form.cleaned_data["reason"]
            )
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, " ".join(getattr(exc, "messages", None) or [str(exc)]))
        else:
            messages.success(
                request,
                "The Stripe payout account is retired. The traveler's next payout setup "
                "opens a new account for the country they declare.",
            )
            return redirect(back)
    return _render(
        request,
        "admin/console/action_form.html",
        {
            "title": f"Retire Stripe payout account {mask_account(account.provider_account_id)}",
            "description": (
                f"Opened for {account_country(account)} in {account.provider_mode} mode. "
                "The account stops receiving payouts here and the traveler is offered "
                "payout setup again. Payouts already funded keep their instructions, "
                "and a payout still in progress to this account blocks the retirement. "
                "Nothing changes at Stripe."
            ),
            "form": form,
            "submit_label": "Retire account",
            "danger": True,
            "back_url": back,
        },
    )
