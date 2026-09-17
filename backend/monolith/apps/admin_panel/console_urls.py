from django.urls import path

from . import console_views as views
from .console_identity_checks import identity_check_detail, identity_checks
from .console_people import person_profile
from .console_payout_reviews import (
    payout_review_detail,
    payout_review_evidence,
    payout_reviews,
)
from .console_views import capability_required
from .finance_control_plane import finance_control_plane
from .finance_dashboard import finance_rows
from .finance_operations import (
    finance_dzd,
    finance_exceptions,
    finance_overview,
    finance_payouts,
    finance_reconciliation,
)

app_name = "admin_console"

urlpatterns = [
    path("finance/control-plane/", finance_control_plane, name="finance-control-plane"),
    # `finance-dashboard` stays the name of the Finance landing page through the
    # H5.2 redesign. The route is what the feature flag, the navigation and
    # every existing bookmark address; what changed is the page behind it.
    path("finance/dashboard/", finance_overview, name="finance-dashboard"),
    path("finance/payouts-hub/", finance_payouts, name="finance-payouts"),
    path("finance/manual-dzd/", finance_dzd, name="finance-dzd"),
    path("finance/exceptions/", finance_exceptions, name="finance-exceptions"),
    path(
        "finance/reconciliation/",
        finance_reconciliation,
        name="finance-reconciliation",
    ),
    path("finance/dashboard/rows/", finance_rows, name="finance-rows"),
    path("", views.overview, name="overview"),
    path("users/", views.users, name="users"),
    # J6.4. The Person profile replaces the old four-count user page at the same
    # route and name, so every existing link lands on the complete profile.
    path("users/<int:pk>/", person_profile, name="user-detail"),
    path("verification/kyc/", views.kyc_queue, name="kyc-queue"),
    path("verification/kyc/<int:pk>/", views.kyc_detail, name="kyc-detail"),
    path(
        "verification/kyc/<int:pk>/evidence/<slug:slot>/",
        views.kyc_evidence,
        name="kyc-evidence",
    ),
    # J6.4. The assigned reviewer's side of a DZD payout identity check. Guarded
    # by the same capability `attest_identity` checks.
    path(
        "verification/payout-identity/",
        capability_required("attest_payout_identity")(identity_checks),
        name="identity-checks",
    ),
    path(
        "verification/payout-identity/<uuid:reference>/",
        capability_required("attest_payout_identity")(identity_check_detail),
        name="identity-check-detail",
    ),
    path("verification/flight-proofs/", views.flight_proof_queue, name="proof-queue"),
    path(
        "verification/flight-proofs/<int:pk>/",
        views.flight_proof_detail,
        name="proof-detail",
    ),
    path(
        "verification/flight-proofs/<int:pk>/evidence/",
        views.flight_proof_evidence,
        name="proof-evidence",
    ),
    path("marketplace/requests/", views.delivery_requests, name="requests"),
    path("marketplace/journeys/", views.journeys, name="journeys"),
    path("marketplace/journeys/<int:pk>/", views.journey_detail, name="journey-detail"),
    path("marketplace/deals/", views.deals, name="deals"),
    path("marketplace/deals/<int:pk>/", views.deal_detail, name="deal-detail"),
    path("disputes/", views.disputes, name="disputes"),
    path("disputes/<int:pk>/", views.dispute_detail, name="dispute-detail"),
    path(
        "disputes/<int:pk>/evidence/<int:evidence_id>/",
        views.dispute_evidence,
        name="dispute-evidence",
    ),
    path("finance/payments/", views.payments, name="payments"),
    path("finance/payments/<int:pk>/", views.payment_detail, name="payment-detail"),
    path(
        "finance/payments/<int:pk>/reconcile/",
        views.payment_reconcile,
        name="payment-reconcile",
    ),
    path(
        "finance/payments/<int:pk>/resolve/",
        views.payment_resolve,
        name="payment-resolve",
    ),
    path("finance/refunds/", views.refunds, name="refunds"),
    path(
        "finance/refunds/new/<int:attempt_id>/", views.refund_request, name="refund-new"
    ),
    path("finance/refunds/<int:pk>/", views.refund_detail, name="refund-detail"),
    path("finance/payouts/", views.payouts, name="payouts"),
    path("finance/payouts/<int:pk>/", views.payout_detail, name="payout-detail"),
    path(
        "finance/payouts/<int:pk>/evidence/<uuid:reference>/",
        views.payout_evidence,
        name="payout-evidence",
    ),
    path(
        "finance/payout-accounts/",
        views.payout_accounts,
        name="payout-accounts",
    ),
    # The DZD payout-method review queue. Finance and Super only: the guard is
    # the same named capability the domain command checks, so the page and the
    # decision behind it cannot disagree about who may act.
    path(
        "finance/payout-reviews/",
        capability_required("review_payout_profiles")(payout_reviews),
        name="payout-reviews",
    ),
    path(
        "finance/payout-reviews/<uuid:reference>/",
        capability_required("review_payout_profiles")(payout_review_detail),
        name="payout-review-detail",
    ),
    path(
        "finance/payout-reviews/<uuid:reference>/cheque/",
        capability_required("review_payout_profiles")(payout_review_evidence),
        name="payout-review-evidence",
    ),
    path("finance/ledger/", views.ledger, name="ledger"),
    path("staff/", views.staff, name="staff"),
    path("staff/<int:pk>/role/", views.staff_role, name="staff-role"),
    path("staff/<int:pk>/access/", views.staff_access, name="staff-access"),
    path(
        "staff/invitations/<uuid:pk>/<slug:action>/",
        views.staff_invitation_action,
        name="staff-invitation-action",
    ),
    path("settings/", views.business_settings, name="settings"),
    path("system/", views.system_status, name="system"),
    path("system/jobs/", views.background_jobs, name="jobs"),
    path("system/jobs/bulk/", views.background_job_bulk, name="job-bulk"),
    path("system/jobs/<int:pk>/", views.background_job_detail, name="job-detail"),
    path(
        "system/jobs/<int:pk>/retry/",
        views.background_job_retry,
        name="job-retry",
    ),
    path(
        "system/jobs/<int:pk>/resolve/",
        views.background_job_resolve,
        name="job-resolve",
    ),
    path("system/email/", views.email_queue, name="email"),
    path("system/geography/", views.geography, name="geography"),
    path("audit/", views.audit_log, name="audit"),
    path("technical/", views.technical_records, name="technical"),
]
