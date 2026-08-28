"""URL configuration for the V1 Deal ratings domain.

Mounted under ``/api/`` alongside the other Deal-scoped capabilities. Every
route requires authentication; who may rate whom is decided from the Deal, not
from the path.

`ratings-submit` and `ratings-list` are the same path under two names, one per
verb, because Django resolves a request by path and only then dispatches on the
method. Both names reverse to `deals/<id>/ratings`, which is what the clients
and the tests quote.
"""

from __future__ import annotations

from django.urls import path

from .views import DealRatingsView, MyRatingsView

urlpatterns = [
    path(
        "deals/<int:pk>/ratings",
        DealRatingsView.as_view(),
        name="ratings-submit",
    ),
    path(
        "deals/<int:pk>/ratings",
        DealRatingsView.as_view(),
        name="ratings-list",
    ),
    path(
        "users/me/ratings",
        MyRatingsView.as_view(),
        name="ratings-mine",
    ),
]
