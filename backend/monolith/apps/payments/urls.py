"""URL config for the payments app."""

from __future__ import annotations

from django.urls import path

from .views import (
    MockWebhookView,
    PaymentIntentCancelView,
    PaymentIntentCreateView,
    PaymentIntentDetailView,
    PaymentIntentListView,
    PaymentIntentRefundView,
)

urlpatterns = [
    path("payments/intents", PaymentIntentListView.as_view(), name="payments-list"),
    path(
        "payments/intents/create",
        PaymentIntentCreateView.as_view(),
        name="payments-create",
    ),
    path(
        "payments/intents/<int:pk>",
        PaymentIntentDetailView.as_view(),
        name="payments-detail",
    ),
    path(
        "payments/intents/<int:pk>/cancel",
        PaymentIntentCancelView.as_view(),
        name="payments-cancel",
    ),
    path(
        "payments/intents/<int:pk>/refund",
        PaymentIntentRefundView.as_view(),
        name="payments-refund",
    ),
    path(
        "payments/webhook/mock",
        MockWebhookView.as_view(),
        name="payments-webhook-mock",
    ),
]
