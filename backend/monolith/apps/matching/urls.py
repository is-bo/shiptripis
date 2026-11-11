"""URL config for the matching app."""

from __future__ import annotations

from django.urls import path

from .views import (
    MatchCancelView,
    MatchChatEligibilityView,
    MatchDetailView,
    MatchListView,
    OfferDeclineView,
    OfferListView,
    OfferWithdrawView,
)
from .v1_views import (
    CandidateExplanationV1View,
    CompatibleRequestsV1View,
    CounterOfferV1View,
    FindTravelersV1View,
    OfferAcceptV1View,
    SenderProposeV1View,
    PricingQuoteV1View,
)

urlpatterns = [
    path("matches", MatchListView.as_view(), name="matches-list"),
    path("matches/propose", SenderProposeV1View.as_view(), name="matches-propose-v1"),
    path(
        "matches/find-travelers",
        FindTravelersV1View.as_view(),
        name="matches-find-travelers-v1",
    ),
    path(
        "matches/compatible-requests",
        CompatibleRequestsV1View.as_view(),
        name="matches-compatible-requests-v1",
    ),
    path("matches/quote", PricingQuoteV1View.as_view(), name="matches-quote-v1"),
    path(
        "matches/explain",
        CandidateExplanationV1View.as_view(),
        name="matches-explain-v1",
    ),
    path("matches/<int:pk>", MatchDetailView.as_view(), name="matches-detail"),
    path("matches/<int:pk>/cancel", MatchCancelView.as_view(), name="matches-cancel"),
    path(
        "matches/<int:pk>/chat-eligibility",
        MatchChatEligibilityView.as_view(),
        name="matches-chat-eligibility",
    ),
    path("matches/<int:pk>/offers", OfferListView.as_view(), name="matches-offers"),
    path(
        "offers/<int:pk>/counter",
        CounterOfferV1View.as_view(),
        name="offers-counter-v1",
    ),
    path("offers/<int:pk>/accept", OfferAcceptV1View.as_view(), name="offers-accept"),
    path("offers/<int:pk>/decline", OfferDeclineView.as_view(), name="offers-decline"),
    path("offers/<int:pk>/withdraw", OfferWithdrawView.as_view(), name="offers-withdraw"),
]
