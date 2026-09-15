"""The page behind a shared guest payment link.

`GuestPaymentView` is the JSON surface the app uses. This is the surface a
*person* uses: someone who was sent a link, has no ShipTrip account, and opened
it in a browser. Without it the link the owner shares is a URL that returns raw
JSON, which is not a payment experience and not something anyone should be asked
to forward to a relative.

Everything about the page is bounded by the same rule as the JSON surface:
holding the token buys exactly one capability, paying this one obligation. The
page renders an amount, a generic description and an expiry. It never renders
the sender, the traveler, the recipient, an address, a parcel, a deal or an
order reference, and the POST handler cannot be given an amount -- it reads the
outstanding balance from the locked order, exactly as the app's own checkout
does.

Every failure -- unknown token, expired, revoked, already paid, order closed --
renders the same page in the same words. Distinguishing them would let someone
holding a guessed token learn which obligations exist.
"""

from __future__ import annotations

import logging

from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from apps.core.business_settings import NoActiveBusinessSettings

from .money import format_minor
from .policy import InvalidPaymentPolicy, phase3_policy
from .providers import ProviderError
from .services import (
    FinanceError,
    guest_payment_view,
    resolve_guest_link,
    start_checkout,
)

logger = logging.getLogger(__name__)

#: Rendered in the rail picker. A payer chooses a way to pay, not a currency:
#: the settlement currency belongs to the rail and the server decides it.
PROVIDER_LABELS = {
    "stripe": "Card",
    "chargily": "Chargily (Algeria)",
    "mock": "Test rail",
}


def _throttled(request: HttpRequest) -> bool:
    """Bound token guessing on the unauthenticated page as on the API."""

    from .views import GuestPaymentThrottle

    return not GuestPaymentThrottle().allow_request(request, None)


def _unavailable(request: HttpRequest, status: int = 404) -> HttpResponse:
    """The link does not work. One page, one wording, every reason."""

    return render(
        request, "payments/guest.html", {"payable": False}, status=status
    )


def _no_rail(request: HttpRequest) -> HttpResponse:
    """The link is fine; the platform cannot take a payment right now.

    Told apart from an invalid link on purpose. "Try again shortly" and "ask
    for a new link" are different instructions, and giving a guest the wrong one
    sends them back to the sender for a link that was never the problem. It
    discloses nothing: a holder of a valid token already knows it is valid.
    """

    return render(
        request,
        "payments/guest.html",
        {"payable": False, "temporarily_unavailable": True},
        status=503,
    )


@require_http_methods(["GET", "POST"])
def guest_payment_page(request: HttpRequest, token: str) -> HttpResponse:
    """Show what is owed, or start a hosted checkout for it.

    The POST branch redirects the browser to the provider rather than returning
    JSON, and returning from that provider proves nothing: only the
    signature-verified webhook moves money, exactly as for a signed-in payer.
    """

    if _throttled(request):
        return _unavailable(request, status=429)
    try:
        link = resolve_guest_link(token)
        policy = phase3_policy()
    except (FinanceError, NoActiveBusinessSettings, InvalidPaymentPolicy):
        return _unavailable(request)

    payload = guest_payment_view(link, policy=policy)
    providers = [
        {
            "provider": row["provider"],
            "label": PROVIDER_LABELS.get(row["provider"], row["provider"]),
        }
        for row in payload["providers"]
    ]
    if not providers:
        return _no_rail(request)

    if request.method == "POST":
        chosen = request.POST.get("provider", "")
        if chosen not in {row["provider"] for row in providers}:
            return _unavailable(request)
        try:
            session = start_checkout(
                order_id=link.order_id,
                provider=chosen,
                actor_id=None,
                guest_link=link,
                guest_email=(request.POST.get("email") or "")[:254],
            )
        except (
            FinanceError,
            ProviderError,
            NoActiveBusinessSettings,
            InvalidPaymentPolicy,
        ):
            # The token is never echoed into a log line; the order is named by
            # its own id, which is not derivable from anything the payer holds.
            logger.warning("finance.guest_page_checkout_failed order=%s", link.order_id)
            return _unavailable(request, status=409)
        if not session.attempt.checkout_url:
            return _unavailable(request, status=409)
        return HttpResponseRedirect(session.attempt.checkout_url)

    return render(
        request,
        "payments/guest.html",
        {
            "payable": True,
            "amount_display": (
                f"€{format_minor(payload['amount_eur_cents'], exponent=2)}"
            ),
            "description": payload["description"],
            "providers": providers,
            "checkout_action": request.path,
        },
    )
