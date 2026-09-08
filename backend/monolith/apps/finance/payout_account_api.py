"""Owner-scoped Stripe Connect setup API, plus the two hosted-return routes.

Four authenticated actions, one per thing a Traveler can actually do:

* **Continue with Stripe** — `POST .../stripe/onboarding` creates or reuses the
  account and returns one short-lived hosted URL.
* **Resume setup** — the same call after an expired link. Stripe's Account Link
  lives about five minutes; a new one is minted by an authenticated request,
  never by following a redirect.
* **Refresh status** — `POST .../stripe/refresh` re-reads Stripe and
  re-evaluates readiness.
* **Manage with Stripe** — `POST .../stripe/dashboard` returns a single-use
  Express Dashboard URL so bank details are changed at Stripe, not here.

The two hosted routes (`/payouts/stripe/return`, `/payouts/stripe/refresh`) are
where Stripe sends the browser. They carry a signed state and nothing else, and
they can do exactly one thing: ask Stripe what the account's state now is.
Returning from onboarding is not evidence of anything — a Traveler who taps
"back" lands on the same URL as one who finished.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError as DomainError
from django.http import Http404
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET
from django.core.cache import cache
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from .payout_accounts import (
    ConnectUnavailable,
    CountryUnsupported,
    allowed_countries,
    open_dashboard,
    read_onboarding_state,
    refresh_account,
    require_connect_enabled,
    resolve_state_account,
    start_onboarding,
)
from .payout_profile_api import StrictInput, method_projection
from .providers.base import ProviderError
from .providers.stripe_connect import get_connect_gateway
from .models import TravelerPayoutMethod

logger = logging.getLogger(__name__)


class ConnectThrottle(UserRateThrottle):
    #: Every action behind this throttle makes a live provider call, so the
    #: budget is per-user and deliberately small.
    rate = "10/min"
    scope = "payout_connect"


class OnboardingInput(StrictInput):
    #: Only meaningful on the first call, and only ever an account country the
    #: deployment has actually validated.
    country = serializers.CharField(
        max_length=2, required=False, default="", allow_blank=True
    )


class ConnectView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ConnectThrottle]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not settings.PAYOUT_PROFILES_ENABLED:
            raise Http404

    def _method(self, request):
        method = TravelerPayoutMethod.objects.filter(
            traveler=request.user, method="stripe_connect"
        ).first()
        if not method:
            raise DomainError("Enable the EUR payout preference first.")
        return method

    def _account(self, request):
        """The Traveler's own account, resolved from their own method row.

        Ownership is derived server-side from the authenticated user every
        time. There is no request field naming an account, so there is nothing
        for one Traveler to point at another's setup with.
        """

        method = self._method(request)
        version = method.current_version
        account = version.stripe_account if version else None
        if not account or account.traveler_id != request.user.pk or not account.active:
            raise DomainError("No Stripe payout account is set up for this Traveler.")
        return method, account

    def handle_exception(self, exc):
        if isinstance(exc, CountryUnsupported):
            # A distinct, actionable contract: the client can name the
            # supported countries and offer the DZD manual rail instead of
            # showing a generic validation failure.
            return Response(
                {
                    "code": "payout_country_unsupported",
                    "detail": "Stripe EUR payouts are not available for this "
                    "account country.",
                    "supported_countries": list(allowed_countries()),
                    "alternative": {"currency": "DZD", "rail": "manual"},
                },
                status=400,
            )
        if isinstance(exc, ConnectUnavailable):
            return Response(
                {
                    "code": "stripe_connect_unavailable",
                    "detail": "Stripe payout setup is not available yet.",
                },
                status=409,
            )
        if isinstance(exc, ProviderError):
            # Provider prose never reaches the client; a stable machine code
            # does. An outage leaves the stored readiness exactly as it was.
            logger.warning("finance.connect_provider_error code=%s", exc.code)
            return Response(
                {
                    "code": "stripe_connect_provider_error",
                    "detail": "Stripe could not be reached. Nothing changed.",
                },
                status=502,
            )
        if isinstance(exc, DomainError):
            return Response(
                {
                    "code": getattr(exc, "code", "") or "payout_setup_invalid",
                    "detail": "Payout setup validation failed.",
                },
                status=400,
            )
        return super().handle_exception(exc)


class StripeOnboardingView(ConnectView):
    """Continue or resume Stripe-hosted onboarding."""

    def post(self, request):
        data = OnboardingInput(data=request.data)
        data.is_valid(raise_exception=True)
        require_connect_enabled()
        result = start_onboarding(
            actor=request.user, country=data.validated_data["country"].upper()
        )
        method = self._method(request)
        return Response(
            {
                # The only place this URL ever appears. Not persisted, not
                # audited, not logged, not pushed.
                "onboarding_url": result["url"],
                "expires_at": result["expires_at"],
                "method": method_projection(method),
            },
            status=201,
        )


class StripeReadinessRefreshView(ConnectView):
    """Re-read authoritative account state from Stripe."""

    def post(self, request):
        require_connect_enabled()
        _, account = self._account(request)
        refresh_account(account, gateway=get_connect_gateway())
        return Response({"method": method_projection(self._method(request))})


class StripeDashboardView(ConnectView):
    """Single-use Express Dashboard access for the account's own owner."""

    def post(self, request):
        url = open_dashboard(actor=request.user)
        return Response({"dashboard_url": url}, status=201)


@method_decorator(never_cache, name="dispatch")
@method_decorator(require_GET, name="dispatch")
class _HostedStateView(View):
    """Shared handling for the two Stripe-hosted redirect targets.

    Plain Django views, not DRF: these render HTML for a browser Stripe
    redirected, and content negotiation has no business in that path. The
    signed state is the only credential, and it authorises exactly one thing.
    """

    outcome = ""

    def get(self, request):
        state = request.GET.get("state", "")
        context = {"outcome": self.outcome, "valid": False, "status": None}
        try:
            account = resolve_state_account(read_onboarding_state(state))
        except DomainError:
            # An expired or tampered state is a dead end by design, and the page
            # says so without revealing whether any account exists.
            return render(request, "payments/connect_return.html", context, status=400)
        context["valid"] = True
        context["status"] = self._resolve(account)
        return render(request, "payments/connect_return.html", context)

    def _resolve(self, account):
        return account.status


class StripeOnboardingReturnView(_HostedStateView):
    """Where Stripe sends the Traveler when they leave or finish onboarding.

    Landing here proves only that a browser navigated. The account's state is
    whatever a fresh authoritative retrieve says it is, so that is what runs —
    and a short per-account cooldown keeps a reloaded tab from turning into a
    provider request per keystroke.
    """

    outcome = "return"

    def _resolve(self, account):
        key = f"connect_return_refresh:{account.pk}"
        if cache.get(key):
            return account.status
        cache.set(key, 1, timeout=15)
        try:
            refreshed, _ = refresh_account(account, gateway=get_connect_gateway())
            return refreshed.status
        except (ProviderError, DomainError, PermissionDenied):
            # A provider outage on the return leg must not look like a failed
            # setup. Report the last known state; the app can refresh later.
            logger.warning("finance.connect_return_refresh_failed")
            return account.status


class StripeOnboardingRefreshView(_HostedStateView):
    """Where Stripe sends the Traveler when the Account Link is stale.

    Stripe's guidance is to mint a replacement link here. This deployment
    deliberately does not: minting a hosted onboarding link from an
    unauthenticated redirect would make the signed state a credential for
    creating Stripe sessions. The page sends the Traveler back to the app,
    where "Resume setup" is an authenticated request.
    """

    outcome = "refresh"
