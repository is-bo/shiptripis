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
    PayoutDetailView,
    PostingDepositView,
)
from .webhooks import ChargilyWebhookView, MockWebhookView, StripeWebhookView
from .connect_webhooks import StripeConnectWebhookView
from .payout_profile_api import (
    PayoutMethodsView,
    DzdProfileView,
    PayoutIdentityReviewView,
)
from .payout_account_api import (
    StripeDashboardView,
    StripeOnboardingView,
    StripeReadinessRefreshView,
)

from .payout_manual_api import (
    EvidenceUploadView,
    ReceiptUploadView,
    EvidenceReadView,
    RevealView,
    ReviewView,
    ManualDetailView,
)

urlpatterns = [
    path("payouts/proofs", EvidenceUploadView.as_view()),
    path("admin/payouts/receipts", ReceiptUploadView.as_view()),
    path("admin/payouts/evidence/<uuid:reference>", EvidenceReadView.as_view()),
    path("admin/payouts/profiles/<uuid:reference>/reveal", RevealView.as_view()),
    path("admin/payouts/profiles/<uuid:reference>/review", ReviewView.as_view()),
    path("admin/payouts/<int:pk>/manual", ManualDetailView.as_view()),
    path(
        "admin/payouts/<int:pk>/manual/prepare",
        ManualDetailView.as_view(),
        {"action": "prepare"},
    ),
    path(
        "admin/payouts/<int:pk>/manual/begin",
        ManualDetailView.as_view(),
        {"action": "begin"},
    ),
    path(
        "admin/payouts/<int:pk>/manual/release",
        ManualDetailView.as_view(),
        {"action": "release"},
    ),
    path(
        "admin/payouts/<int:pk>/manual/confirm",
        ManualDetailView.as_view(),
        {"action": "confirm"},
    ),
    path("payouts/methods", PayoutMethodsView.as_view(), name="payout-methods"),
    path("payouts/profiles/dzd", DzdProfileView.as_view(), name="payout-dzd-profile"),
    # H2 Stripe Connect setup. Every one of these is owner-scoped from the
    # authenticated user; none accepts a connected-account id as input.
    path(
        "payouts/methods/stripe/onboarding",
        StripeOnboardingView.as_view(),
        name="payout-stripe-onboarding",
    ),
    path(
        "payouts/methods/stripe/refresh",
        StripeReadinessRefreshView.as_view(),
        name="payout-stripe-refresh",
    ),
    path(
        "payouts/methods/stripe/dashboard",
        StripeDashboardView.as_view(),
        name="payout-stripe-dashboard",
    ),
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
    path("payouts/<uuid:reference>", PayoutDetailView.as_view(), name="finance-payout-detail"),
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
    # Connected accounts. A separate URL, a separate scope and its own
    # signing secret: neither endpoint's secret can verify the other's events,
    # and neither endpoint's handler can apply the other's.
    path(
        "payments/webhooks/stripe-connect",
        StripeConnectWebhookView.as_view(),
        name="finance-webhook-stripe-connect",
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
