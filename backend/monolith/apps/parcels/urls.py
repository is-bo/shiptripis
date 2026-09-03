from django.urls import path

from .views import (
    DeliveryCreateView,
    DeliveryQuoteView,
    DeliveryV1CreateView,
    OpenParcelSearchView,
    ParcelCancelView,
    ParcelDetailView,
    ParcelItemPhotoStageView,
    ParcelListView,
    ParcelMediaUploadView,
    ParcelMediaUrlView,
    ProductCreateView,
)

urlpatterns = [
    path(
        "parcels/quote/delivery",
        DeliveryQuoteView.as_view(),
        name="parcels-quote-delivery",
    ),
    path("parcels/open", OpenParcelSearchView.as_view(), name="parcels-open-search"),
    # Ahead of `parcels/<int:pk>` only by being a literal; kept adjacent to the
    # other collection routes so the ordering is visible rather than lucky.
    path(
        "parcels/media",
        ParcelItemPhotoStageView.as_view(),
        name="parcels-item-photo-stage",
    ),
    path("parcels", ParcelListView.as_view(), name="parcels-list"),
    path(
        "parcels/delivery", DeliveryCreateView.as_view(), name="parcels-delivery-create"
    ),
    path(
        "parcels/delivery/v1",
        DeliveryV1CreateView.as_view(),
        name="parcels-delivery-v1-create",
    ),
    path("parcels/product", ProductCreateView.as_view(), name="parcels-product-create"),
    path("parcels/<int:pk>", ParcelDetailView.as_view(), name="parcels-detail"),
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
