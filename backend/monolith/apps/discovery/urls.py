from django.urls import path

from .views import (
    AlertDetailView,
    AlertsView,
    InterestView,
    MatchesView,
    OwnProfileView,
    PeopleView,
    PersonReviewsView,
    PersonView,
    RequestsView,
    TripReviewsView,
    TripsView,
)

urlpatterns = [
    path("discovery/matches", MatchesView.as_view(), name="discovery-matches"),
    path("discovery/trips", TripsView.as_view(), name="discovery-trips"),
    path(
        "discovery/trips/<int:pk>/reviews",
        TripReviewsView.as_view(),
        name="discovery-trip-reviews",
    ),
    path("discovery/requests", RequestsView.as_view(), name="discovery-requests"),
    path(
        "discovery/requests/<int:pk>/interest",
        InterestView.as_view(),
        name="discovery-request-interest",
    ),
    path("discovery/people", PeopleView.as_view(), name="discovery-people"),
    path(
        "discovery/people/<uuid:public_id>",
        PersonView.as_view(),
        name="discovery-person",
    ),
    path(
        "discovery/people/<uuid:public_id>/reviews",
        PersonReviewsView.as_view(),
        name="discovery-person-reviews",
    ),
    path("discovery/profile/me", OwnProfileView.as_view(), name="discovery-profile-me"),
    path("discovery/alerts", AlertsView.as_view(), name="discovery-alerts"),
    path(
        "discovery/alerts/<int:pk>", AlertDetailView.as_view(), name="discovery-alert"
    ),
]
