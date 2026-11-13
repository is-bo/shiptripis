from django.contrib import admin
from django.urls import include, path

from apps.core.health import healthz, readyz
from apps.admin_panel.invitation_web import invitation_accept_page
from apps.finance.guest_web import guest_payment_page
from apps.finance.payment_return_web import payment_return_page
from apps.finance.payout_account_api import (
    StripeOnboardingRefreshView,
    StripeOnboardingReturnView,
)

connect_return = StripeOnboardingReturnView.as_view()
connect_refresh = StripeOnboardingRefreshView.as_view()

admin.site.site_header = "Wassla Operations"
admin.site.site_title = "Wassla Admin"
admin.site.index_title = "Operations dashboard"

# Preserve Django's 403 semantics while giving staff a useful way back into
# the console. API permission responses keep their normal JSON handling.
handler403 = "apps.admin_panel.console_views.permission_denied"


urlpatterns = [
    path("admin/invitations/accept", invitation_accept_page, name="admin-invitation-accept-page"),
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
    # this from PAYMENTS_PUBLIC_BASE_URL. Since J7D it reads the order's own
    # state -- moved only by a signature-verified webhook -- and says what that
    # is; `?result=` never decides the outcome. See `payment_return_web`.
    path(
        "pay/<uuid:reference>/return",
        payment_return_page,
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
    path("api/", include("apps.handover.urls")),
    path("api/", include("apps.disputes.urls")),
    path("api/", include("apps.ratings.urls")),
    path("api/", include("apps.boosts.urls")),
    path("api/", include("apps.finance.urls")),
    path("api/", include("apps.notifications.urls")),
    path("api/", include("apps.chat.urls")),
    path("api/", include("apps.discovery.urls")),
    path("api/", include("apps.problems.urls")),
]
