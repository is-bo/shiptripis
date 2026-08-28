"""URL configuration for the V1 paid-boost domain.

Mounted under ``/api/``. The catalogue is authenticated because prices are
server-authoritative and there is no anonymous surface that needs them; the
per-request routes are owner-or-staff, because boost history is not public.

`boosts-purchase` and `boosts-list` are the same path under two names, one per
verb, since Django resolves a request by path and only then dispatches on the
method. Both reverse to `parcels/<id>/boosts`.
"""

from __future__ import annotations

from django.urls import path

from .views import BoostPackageListView, RequestBoostView

urlpatterns = [
    path(
        "boosts/packages",
        BoostPackageListView.as_view(),
        name="boosts-packages",
    ),
    path(
        "parcels/<int:pk>/boosts",
        RequestBoostView.as_view(),
        name="boosts-purchase",
    ),
    path(
        "parcels/<int:pk>/boosts",
        RequestBoostView.as_view(),
        name="boosts-list",
    ),
]
