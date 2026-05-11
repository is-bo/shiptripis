from __future__ import annotations

from django.urls import path

from .views import HandoverIssueView, HandoverListView, HandoverVerifyView

urlpatterns = [
    path(
        "matches/<int:match_id>/handover/issue",
        HandoverIssueView.as_view(),
        name="handover-issue",
    ),
    path(
        "matches/<int:match_id>/handover/verify",
        HandoverVerifyView.as_view(),
        name="handover-verify",
    ),
    path(
        "matches/<int:match_id>/handover",
        HandoverListView.as_view(),
        name="handover-list",
    ),
]
