"""URL config for the matching app."""

from __future__ import annotations

from django.urls import path

from .views import (
    CounterOfferView,
    MatchCancelView,
    MatchChatEligibilityView,
    MatchDetailView,
    MatchListView,
    OfferAcceptView,
    OfferDeclineView,
    OfferListView,
    OfferWithdrawView,
    SenderApplyView,
    TravelerApplyView,
)

urlpatterns = [
    path("matches", MatchListView.as_view(), name="matches-list"),
    path("matches/apply", TravelerApplyView.as_view(), name="matches-apply"),
    path(
        "matches/apply-to-trip",
        SenderApplyView.as_view(),
        name="matches-apply-to-trip",
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
        "matches/<int:pk>/offers/counter",
        CounterOfferView.as_view(),
        name="matches-offers-counter",
    ),
    path("offers/<int:pk>/accept", OfferAcceptView.as_view(), name="offers-accept"),
    path("offers/<int:pk>/decline", OfferDeclineView.as_view(), name="offers-decline"),
    path("offers/<int:pk>/withdraw", OfferWithdrawView.as_view(), name="offers-withdraw"),
]
