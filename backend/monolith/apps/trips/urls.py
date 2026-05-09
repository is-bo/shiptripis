from django.urls import path

from .views import (
    AirportListView,
    TripCancelView,
    TripDetailView,
    TripListCreateView,
)

urlpatterns = [
    path("airports", AirportListView.as_view(), name="airports-list"),
    path("trips", TripListCreateView.as_view(), name="trips-list-create"),
    path("trips/<int:pk>", TripDetailView.as_view(), name="trips-detail"),
    path("trips/<int:pk>/cancel", TripCancelView.as_view(), name="trips-cancel"),
]
