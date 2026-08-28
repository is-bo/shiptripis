"""URL configuration for the V1 Deal handover domain.

Mounted under ``/api/`` alongside other Deal-scoped capabilities. Every
endpoint requires authentication and enforces object-level Deal membership.
"""

from __future__ import annotations

from django.urls import path

from .views import (
    HandoverDeliveryCodeRevealView,
    HandoverDeliveryCodeRotateView,
    HandoverDeliverySubmitView,
    HandoverPickupCodeRevealView,
    HandoverPickupCodeRotateView,
    HandoverPickupSubmitView,
    HandoverStateView,
)

urlpatterns = [
    path(
        "deals/<int:pk>/handover",
        HandoverStateView.as_view(),
        name="handover-state",
    ),
    path(
        "deals/<int:pk>/handover/pickup-code",
        HandoverPickupCodeRevealView.as_view(),
        name="handover-pickup-code",
    ),
    path(
        "deals/<int:pk>/handover/pickup-code/rotate",
        HandoverPickupCodeRotateView.as_view(),
        name="handover-pickup-code-rotate",
    ),
    path(
        "deals/<int:pk>/handover/delivery-code",
        HandoverDeliveryCodeRevealView.as_view(),
        name="handover-delivery-code",
    ),
    path(
        "deals/<int:pk>/handover/delivery-code/rotate",
        HandoverDeliveryCodeRotateView.as_view(),
        name="handover-delivery-code-rotate",
    ),
    path(
        "deals/<int:pk>/handover/pickup",
        HandoverPickupSubmitView.as_view(),
        name="handover-pickup-submit",
    ),
    path(
        "deals/<int:pk>/handover/delivery",
        HandoverDeliverySubmitView.as_view(),
        name="handover-delivery-submit",
    ),
]
