from django.urls import path

from .views import (
    AirportListView,
    JourneyCancelView,
    JourneyDetailView,
    JourneyLegProofCreateView,
    JourneyListCreateView,
    JourneyPublishView,
    JourneySearchView,
    TripCancelView,
    TripDetailView,
    TripListCreateView,
    TripMediaUploadView,
    TripSearchView,
)

urlpatterns = [
    path("airports", AirportListView.as_view(), name="airports-list"),
    path("journeys", JourneyListCreateView.as_view(), name="journeys-list-create"),
    path("journeys/search", JourneySearchView.as_view(), name="journeys-search"),
    path("journeys/<int:pk>", JourneyDetailView.as_view(), name="journeys-detail"),
    path(
        "journeys/<int:pk>/publish",
        JourneyPublishView.as_view(),
        name="journeys-publish",
    ),
    path(
        "journeys/<int:pk>/cancel",
        JourneyCancelView.as_view(),
        name="journeys-cancel",
    ),
    path(
        "journeys/<int:journey_pk>/legs/<int:leg_pk>/proof",
        JourneyLegProofCreateView.as_view(),
        name="journey-leg-proof-create",
    ),
    path("trips", TripListCreateView.as_view(), name="trips-list-create"),
    path("trips/search", TripSearchView.as_view(), name="trips-search"),
    path("trips/<int:pk>", TripDetailView.as_view(), name="trips-detail"),
    path("trips/<int:pk>/cancel", TripCancelView.as_view(), name="trips-cancel"),
    path(
        "trips/<int:pk>/media",
        TripMediaUploadView.as_view(),
        name="trips-media-upload",
    ),
]
