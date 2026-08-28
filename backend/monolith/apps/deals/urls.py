from django.urls import path

from .views import (
    DealCancellationQuoteView,
    DealCancelView,
    DealDetailView,
    DealListView,
    DealRecipientView,
)


urlpatterns = [
    path("deals", DealListView.as_view(), name="deals-list"),
    path("deals/<int:pk>", DealDetailView.as_view(), name="deals-detail"),
    path(
        "deals/<int:pk>/recipient",
        DealRecipientView.as_view(),
        name="deals-recipient",
    ),
    path(
        "deals/<int:pk>/cancellation",
        DealCancellationQuoteView.as_view(),
        name="deals-cancellation-quote",
    ),
    path("deals/<int:pk>/cancel", DealCancelView.as_view(), name="deals-cancel"),
]
