"""URL configuration for sender Boost.

Mounted under ``/api/``. Every per-request route is owner-or-staff: a Boost is
the sender's own commercial decision, not public information about the request.

`parcels/<id>/boost` is the J2 reward and `parcels/<id>/boosts` is the retired
package history. They are deliberately different paths, and `boosts-list` and
`boosts-purchase` remain as names on the second so existing `reverse()` calls
keep resolving to the surface they always meant.
"""

from __future__ import annotations

from django.urls import path

from .views import (
    BoostPolicyView,
    RequestBoostHistoryView,
    RequestBoostIntentView,
    RetiredBoostPackageView,
)

urlpatterns = [
    path("boosts/policy", BoostPolicyView.as_view(), name="boosts-policy"),
    # Retired J1 surfaces. They answer 410, not 404.
    path(
        "boosts/packages",
        RetiredBoostPackageView.as_view(),
        name="boosts-packages",
    ),
    path("boosts/preview", RetiredBoostPackageView.as_view(), name="boosts-preview"),
    path(
        "parcels/<int:pk>/boost",
        RequestBoostIntentView.as_view(),
        name="boosts-intent",
    ),
    path(
        "parcels/<int:pk>/boosts",
        RequestBoostHistoryView.as_view(),
        name="boosts-purchase",
    ),
    path(
        "parcels/<int:pk>/boosts",
        RequestBoostHistoryView.as_view(),
        name="boosts-list",
    ),
]
