from django.urls import path

from .views import (
    JourneyCancelView,
    JourneyDetailView,
    JourneyLegProofCreateView,
    JourneyListCreateView,
    JourneyPauseView,
    JourneyPublishView,
    JourneyResumeView,
)

urlpatterns = [
    path("journeys", JourneyListCreateView.as_view(), name="journeys-list-create"),
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
    path("journeys/<int:pk>/pause", JourneyPauseView.as_view(), name="journeys-pause"),
    path(
        "journeys/<int:pk>/resume",
        JourneyResumeView.as_view(),
        name="journeys-resume",
    ),
    path(
        "journeys/<int:journey_pk>/legs/<int:leg_pk>/proof",
        JourneyLegProofCreateView.as_view(),
        name="journey-leg-proof-create",
    ),
]
