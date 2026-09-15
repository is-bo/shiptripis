from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView

from apps.core.health import healthz, readyz
from apps.finance.guest_web import guest_payment_page
from apps.finance.payout_account_api import (
    StripeOnboardingRefreshView,
    StripeOnboardingReturnView,
)

connect_return = StripeOnboardingReturnView.as_view()
connect_refresh = StripeOnboardingRefreshView.as_view()

admin.site.site_header = "ShipTrip Operations"
admin.site.site_title = "ShipTrip Admin"
admin.site.index_title = "Operations dashboard"


urlpatterns = [
    # Human-facing operations routes intentionally precede Django's technical
    # model routes. The latter remain available under /admin/ for the explicit
    # owner-only Technical records area.
    path(
        "admin/",
        include(("apps.admin_panel.console_urls", "admin_console"), namespace="admin_console"),
    ),
    path("admin/", admin.site.urls),
    path("healthz", healthz),
    path("readyz", readyz),
    # Where Stripe and Chargily send the payer back. `_checkout_urls` builds
    # this from PAYMENTS_PUBLIC_BASE_URL, and nothing served it: a completed
    # hosted checkout ended on a bare "Not Found", which for a guest payer with
    # no app is the entire end of the payment.
    #
    # It answers the same way whatever `?result=` says, because the redirect is
    # not evidence — only a signature-verified webhook moves money here. The
    # reference is not read, so the page discloses nothing about the order.
    path(
        "pay/<uuid:reference>/return",
        TemplateView.as_view(template_name="payments/return.html"),
        name="payment-return",
    ),
    # The page behind a shared guest payment link. Without it the link an owner
    # shares is a URL that answers JSON, which is not something anyone can be
    # asked to forward to a relative. The token in the path is the only
    # credential and buys exactly one capability: paying this one obligation.
    path(
        "pay/guest/<str:token>",
        guest_payment_page,
        name="payment-guest-page",
    ),
    # Where Stripe sends the Traveler's browser back from hosted Connect
    # onboarding. Server-owned URLs, allowlisted in settings and bound to a
    # signed state. Returning here is not evidence that setup finished, so the
    # return route re-reads the account from Stripe and the refresh route only
    # points back at the app, where minting a new link is authenticated.
    path(
        "payouts/stripe/return",
        connect_return,
        name="payout-stripe-onboarding-return",
    ),
    path(
        "payouts/stripe/refresh",
        connect_refresh,
        name="payout-stripe-onboarding-refresh",
    ),
    path("api/", include("apps.accounts.urls")),
    # The Phase 6A least-privilege operations surface owns every /api/admin/*
    # route. Mount it before historical domain compatibility routes so a
    # duplicate legacy path can never shadow granular permissions/auditing.
    path("api/", include("apps.admin_panel.urls")),
    path("api/", include("apps.trips.urls")),
    path("api/", include("apps.locations.urls")),
    path("api/", include("apps.routing.urls")),
    path("api/", include("apps.parcels.urls")),
    path("api/", include("apps.matching.urls")),
    path("api/", include("apps.deals.urls")),
    # Phase 4 Deal-scoped domains. They are mounted before the legacy
    # `apps.verification` handover routes so a V1 Deal path can never be
    # shadowed by the retired Match-scoped one.
    path("api/", include("apps.handover.urls")),
    path("api/", include("apps.disputes.urls")),
    path("api/", include("apps.ratings.urls")),
    path("api/", include("apps.boosts.urls")),
    # V1 finance routes are mounted before the legacy payments app so a V1
    # path can never be shadowed by a legacy pattern.
    path("api/", include("apps.finance.urls")),
    path("api/", include("apps.payments.urls")),
    path("api/", include("apps.wallet.urls")),
    path("api/", include("apps.verification.urls")),
    path("api/", include("apps.notifications.urls")),
    path("api/", include("apps.chat.urls")),
]
