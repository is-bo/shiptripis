from django.urls import path

from .views import (
    DeliveryCreateView,
    DeliveryQuoteView,
    OpenParcelSearchView,
    ParcelCancelView,
    ParcelDetailView,
    ParcelListView,
    ProductCreateView,
)

urlpatterns = [
    path(
        "parcels/quote/delivery",
        DeliveryQuoteView.as_view(),
        name="parcels-quote-delivery",
    ),
    path("parcels/open", OpenParcelSearchView.as_view(), name="parcels-open-search"),
    path("parcels", ParcelListView.as_view(), name="parcels-list"),
    path("parcels/delivery", DeliveryCreateView.as_view(), name="parcels-delivery-create"),
    path("parcels/product", ProductCreateView.as_view(), name="parcels-product-create"),
    path("parcels/<int:pk>", ParcelDetailView.as_view(), name="parcels-detail"),
    path("parcels/<int:pk>/cancel", ParcelCancelView.as_view(), name="parcels-cancel"),
]
