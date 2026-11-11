from django.urls import path

from .views import (
    JourneyCancelView,
    JourneyDetailView,
    JourneyLegProofCreateView,
    JourneyListCreateView,
    JourneyPublishView,
    JourneySearchView,
)

urlpatterns = [
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
]
