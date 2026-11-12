from django.urls import path

from .pricing_api import PricingQuoteDraftView, RequestPricingView
from .views import (
    DeliveryV1CreateView,
    ParcelCancelView,
    ParcelDetailView,
    ParcelItemPhotoStageView,
    ParcelListView,
    ParcelMediaUploadView,
    ParcelMediaUrlView,
)

urlpatterns = [
    # Priced before anything is written, so the minimum and the recommendation
    # are on screen before the sender chooses rather than after.
    path(
        "parcels/pricing-quote",
        PricingQuoteDraftView.as_view(),
        name="parcels-pricing-quote",
    ),
    # Ahead of `parcels/<int:pk>` only by being a literal; kept adjacent to the
    # other collection routes so the ordering is visible rather than lucky.
    path(
        "parcels/media",
        ParcelItemPhotoStageView.as_view(),
        name="parcels-item-photo-stage",
    ),
    path("parcels", ParcelListView.as_view(), name="parcels-list"),
    path(
        "parcels/delivery/v1",
        DeliveryV1CreateView.as_view(),
        name="parcels-delivery-v1-create",
    ),
    path("parcels/<int:pk>", ParcelDetailView.as_view(), name="parcels-detail"),
    path(
        "parcels/<int:pk>/pricing",
        RequestPricingView.as_view(),
        name="parcels-pricing",
    ),
    path("parcels/<int:pk>/cancel", ParcelCancelView.as_view(), name="parcels-cancel"),
    path(
        "parcels/<int:pk>/media",
        ParcelMediaUploadView.as_view(),
        name="parcels-media-upload",
    ),
    path(
        "parcels/<int:pk>/media/<int:media_id>/url",
        ParcelMediaUrlView.as_view(),
        name="parcels-media-url",
    ),
]
