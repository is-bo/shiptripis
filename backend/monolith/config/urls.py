from django.contrib import admin
from django.urls import include, path

from apps.core.health import healthz, readyz

admin.site.site_header = "ShipTrip Operations"
admin.site.site_title = "ShipTrip Admin"
admin.site.index_title = "Operations dashboard"


urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz", healthz),
    path("readyz", readyz),
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
