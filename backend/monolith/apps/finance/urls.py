"""URL config for the V1 finance app."""

from __future__ import annotations

from django.urls import path

from .views import (
    AdminManualPayoutView,
    AdminRefundSettleView,
    AdminRefundView,
    DealPaymentView,
    GuestCheckoutView,
    GuestLinkCreateView,
    GuestLinkRevokeView,
    GuestPaymentView,
    PaymentCheckoutView,
    PaymentOrderDetailView,
    PaymentOrderListView,
    PaymentProvidersView,
    PayoutListView,
    PostingDepositView,
)
from .webhooks import ChargilyWebhookView, MockWebhookView, StripeWebhookView
from .payout_profile_api import (
    PayoutMethodsView,
    DzdProfileView,
    PayoutIdentityReviewView,
)

urlpatterns = [
    path("payouts/methods", PayoutMethodsView.as_view(), name="payout-methods"),
    path("payouts/profiles/dzd", DzdProfileView.as_view(), name="payout-dzd-profile"),
    path(
        "admin/payout-identity-reviews/<uuid:reference>",
        PayoutIdentityReviewView.as_view(),
        name="payout-identity-review",
    ),
    path(
        "payments/providers",
        PaymentProvidersView.as_view(),
        name="finance-providers",
    ),
    path("payments/orders", PaymentOrderListView.as_view(), name="finance-orders"),
    path(
        "payments/orders/<uuid:reference>",
        PaymentOrderDetailView.as_view(),
        name="finance-order-detail",
    ),
    path(
        "payments/orders/<uuid:reference>/checkout",
        PaymentCheckoutView.as_view(),
        name="finance-order-checkout",
    ),
    path(
        "payments/orders/<uuid:reference>/guest-link",
        GuestLinkCreateView.as_view(),
        name="finance-order-guest-link",
    ),
    path(
        "payments/orders/<uuid:reference>/guest-link/revoke",
        GuestLinkRevokeView.as_view(),
        name="finance-order-guest-link-revoke",
    ),
    path(
        "parcels/<int:pk>/posting-deposit",
        PostingDepositView.as_view(),
        name="finance-posting-deposit",
    ),
    path(
        "deals/<int:pk>/payment",
        DealPaymentView.as_view(),
        name="finance-deal-payment",
    ),
    path("payouts", PayoutListView.as_view(), name="finance-payouts"),
    path(
        "admin/payouts/<int:pk>/complete",
        AdminManualPayoutView.as_view(),
        name="finance-admin-payout-complete",
    ),
    path(
        "admin/payments/orders/<uuid:reference>/refund",
        AdminRefundView.as_view(),
        name="finance-admin-refund",
    ),
    path(
        "admin/payments/refunds/<int:pk>/settle",
        AdminRefundSettleView.as_view(),
        name="finance-admin-refund-settle",
    ),
    # Unauthenticated guest surface. The token is the only credential and it
    # grants exactly one capability: paying this obligation.
    path(
        "payments/guest/<str:token>",
        GuestPaymentView.as_view(),
        name="finance-guest-payment",
    ),
    path(
        "payments/guest/<str:token>/checkout",
        GuestCheckoutView.as_view(),
        name="finance-guest-checkout",
    ),
    # Provider webhooks. Signature-verified, idempotent, and never gated on
    # business availability so money already in flight always reconciles.
    path(
        "payments/webhooks/stripe",
        StripeWebhookView.as_view(),
        name="finance-webhook-stripe",
    ),
    path(
        "payments/webhooks/chargily",
        ChargilyWebhookView.as_view(),
        name="finance-webhook-chargily",
    ),
    path(
        "payments/webhooks/mock",
        MockWebhookView.as_view(),
        name="finance-webhook-mock",
    ),
]
