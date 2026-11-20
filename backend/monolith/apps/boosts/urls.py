"""URL configuration for sender Boost.

Mounted under ``/api/``. Every per-request route is owner-or-staff: a Boost is
the sender's own commercial decision, not public information about the request.
"""

from __future__ import annotations

from django.urls import path

from .views import BoostPolicyView, RequestBoostIntentView

urlpatterns = [
    path("boosts/policy", BoostPolicyView.as_view(), name="boosts-policy"),
    path(
        "parcels/<int:pk>/boost",
        RequestBoostIntentView.as_view(),
        name="boosts-intent",
    ),
]
