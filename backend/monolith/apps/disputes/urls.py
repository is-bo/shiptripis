"""URL configuration for the V1 disputes domain.

Mounted under ``/api/`` alongside the other Deal-scoped capabilities. The party
routes require authentication and Deal membership; the operations routes require
a named Django permission, checked by `apps.core.permissions`.
"""

from __future__ import annotations

from django.urls import path

from .views import (
    AdminDealNoShowView,
    AdminDisputeListView,
    AdminDisputeResolveView,
    AdminDisputeStatusView,
    DealDisputesView,
    DisputeDetailView,
    DisputeEvidenceUrlView,
    DisputeEvidenceView,
)

urlpatterns = [
    # One resource, two verbs, two names. Both entries resolve to the same
    # view, so `disputes-open` and `disputes-list` reverse to the same URL and
    # POST and GET are both served -- which registering a POST-only view first
    # would quietly break.
    path(
        "deals/<int:pk>/disputes",
        DealDisputesView.as_view(),
        name="disputes-open",
    ),
    path(
        "deals/<int:pk>/disputes",
        DealDisputesView.as_view(),
        name="disputes-list",
    ),
    path("disputes/<int:pk>", DisputeDetailView.as_view(), name="disputes-detail"),
    path(
        "disputes/<int:pk>/evidence",
        DisputeEvidenceView.as_view(),
        name="disputes-evidence",
    ),
    path(
        "disputes/<int:pk>/evidence/<int:evidence_id>/url",
        DisputeEvidenceUrlView.as_view(),
        name="disputes-evidence-url",
    ),
    path(
        "admin/disputes",
        AdminDisputeListView.as_view(),
        name="disputes-admin-list",
    ),
    path(
        "admin/disputes/<int:pk>/status",
        AdminDisputeStatusView.as_view(),
        name="disputes-admin-status",
    ),
    path(
        "admin/disputes/<int:pk>/resolve",
        AdminDisputeResolveView.as_view(),
        name="disputes-admin-resolve",
    ),
    path(
        "admin/deals/<int:pk>/no-show",
        AdminDealNoShowView.as_view(),
        name="deals-admin-no-show",
    ),
]
