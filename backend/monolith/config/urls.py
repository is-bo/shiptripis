from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path

admin.site.site_header = "ShipTrip Operations"
admin.site.site_title = "ShipTrip Admin"
admin.site.index_title = "Operations dashboard"


def healthz(_request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz", healthz),
    path("api/", include("apps.accounts.urls")),
    path("api/", include("apps.trips.urls")),
    path("api/", include("apps.parcels.urls")),
    path("api/", include("apps.matching.urls")),
    path("api/", include("apps.payments.urls")),
    path("api/", include("apps.wallet.urls")),
    path("api/", include("apps.verification.urls")),
]
