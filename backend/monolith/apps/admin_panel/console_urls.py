from django.urls import path

from apps.locations.sea_crossings import MANAGE_CROSSINGS_PERMISSION
from apps.problems.services import VIEW_PROBLEMS_PERMISSION
from apps.chat.moderation import MODERATE_PERMISSION as CHAT_MODERATE_PERMISSION
from apps.ratings.moderation import MODERATE_PERMISSION
from apps.accounts.photos import MODERATE_PERMISSION as PHOTO_MODERATE_PERMISSION

from apps.admin_helper import console as helper_console

from . import console_two_step as two_step
from . import console_views as views
from .console_account import account_ban
from .console_discovery import profile_visibility
from .console_exports import finance_exports
from .console_identity_checks import identity_check_detail, identity_checks
from .console_journey_pause import journey_pause_action
from .console_notes import NOTE_ROUTE_CAPABILITIES, note_add
from .console_people import person_profile
from .console_photos import photo_remove
from .console_problems import deal_no_show, problem_detail, problems
from .console_chat_reports import chat_report_detail, chat_reports
from .console_reviews import review_detail, reviews
from .console_payout_reviews import (
    payout_review_detail,
    payout_review_evidence,
    payout_reviews,
)
from .console_sea import sea_crossing_new, sea_crossing_toggle
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
    # L14, spec 19.1. The second step after the password. The middleware keeps
    # this prefix open, and only this prefix, so the pages can be reached.
    path("two-step/", two_step.start, name="two-step"),
    path("two-step/enrol/", two_step.enrol, name="two-step-enrol"),
    path(
        "two-step/recovery-codes/",
        two_step.recovery_codes,
        name="two-step-recovery-codes",
    ),
    path("two-step/verify/", two_step.verify, name="two-step-verify"),
    path("two-step/recovery/", two_step.recovery, name="two-step-recovery"),
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
    # L14, spec 19.2. Streamed CSV downloads, `export_finance` only.
    path("finance/exports/", finance_exports, name="finance-exports"),
    path("", views.overview, name="overview"),
    # L15, spec 20. The AI helper's keys: created behind a fresh two-step code,
    # shown once, stopped by their admin or by a Super Admin.
    path(
        "ai-helper/",
        capability_required(helper_console.PAGE_PERMISSION)(helper_console.page),
        name="ai-helper",
    ),
    # L17. The skill itself, from the skill files: a zip and one pasted text.
    path(
        "ai-helper/skill.zip",
        capability_required(helper_console.PAGE_PERMISSION)(helper_console.skill_download),
        name="ai-helper-skill",
    ),
    path(
        "ai-helper/skill.txt",
        capability_required(helper_console.PAGE_PERMISSION)(helper_console.skill_instructions),
        name="ai-helper-instructions",
    ),
    path(
        "ai-helper/keys/new/",
        capability_required(helper_console.PAGE_PERMISSION)(helper_console.create),
        name="ai-helper-create",
    ),
    path(
        "ai-helper/keys/<uuid:pk>/stop/",
        capability_required(helper_console.PAGE_PERMISSION)(helper_console.stop),
        name="ai-helper-stop",
    ),
    # L16. One change the helper prepared: read, confirmed or rejected by its
    # own admin, from this two-step-verified session.
    path(
        "ai-helper/changes/<uuid:pk>/",
        capability_required(helper_console.PAGE_PERMISSION)(helper_console.change),
        name="ai-helper-change",
    ),
    path("users/", views.users, name="users"),
    # J6.4. The Person profile replaces the old four-count user page at the same
    # route and name, so every existing link lands on the complete profile.
    path("users/<int:pk>/", person_profile, name="user-detail"),
    # L16. Ban a member's account or restore it, with a reason (Super Admin).
    path(
        "users/<int:pk>/ban/",
        capability_required("manage_users")(account_ban),
        name="user-ban",
    ),
    # L16. An internal note on a delivery, a dispute or a person; the view
    # checks the capability of the page the note is for.
    path(
        "notes/<slug:target_type>/<int:pk>/",
        capability_required(*NOTE_ROUTE_CAPABILITIES)(note_add),
        name="note-add",
    ),
    # P3A, spec 21. Remove a member's profile photo, with a reason they see.
    path(
        "users/<int:pk>/photo/remove/",
        capability_required(PHOTO_MODERATE_PERMISSION)(photo_remove),
        name="user-photo-remove",
    ),
    path(
        "users/<int:pk>/public-profile/",
        capability_required("manage_users")(profile_visibility),
        name="user-profile-visibility",
    ),
    # Spec 13: the one inbox entry. The tabs are the two queues below, whose
    # routes are kept so existing links still land.
    path("verification/", views.verification, name="verification"),
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
    # L13A, spec 18. Guarded by the capability the decisions check, so the
    # page and the service behind it cannot disagree about who may act; the
    # reporter's identity is on these pages, so nobody else opens them.
    path(
        "trust/reviews/",
        capability_required(MODERATE_PERMISSION)(reviews),
        name="reviews",
    ),
    path(
        "trust/reviews/<int:pk>/",
        capability_required(MODERATE_PERMISSION)(review_detail),
        name="review-detail",
    ),
    # Store readiness, App Store 1.2. Chat messages members reported.
    path(
        "trust/chat-reports/",
        capability_required(CHAT_MODERATE_PERMISSION)(chat_reports),
        name="chat-reports",
    ),
    path(
        "trust/chat-reports/<int:pk>/",
        capability_required(CHAT_MODERATE_PERMISSION)(chat_report_detail),
        name="chat-report-detail",
    ),
    path("marketplace/requests/", views.delivery_requests, name="requests"),
    path("marketplace/journeys/", views.journeys, name="journeys"),
    path("marketplace/journeys/<int:pk>/", views.journey_detail, name="journey-detail"),
    path(
        "marketplace/journeys/<int:pk>/<slug:action>/",
        capability_required("manage_journeys")(journey_pause_action),
        name="journey-pause",
    ),
    path("marketplace/deals/", views.deals, name="deals"),
    path("marketplace/deals/<int:pk>/", views.deal_detail, name="deal-detail"),
    # L9A. The console face of the existing no-show action, guarded by the
    # capability that action checks; a no-show report links here.
    path(
        "marketplace/deals/<int:pk>/no-show/",
        capability_required("record_no_show")(deal_no_show),
        name="deal-no-show",
    ),
    path("disputes/", views.disputes, name="disputes"),
    path("disputes/<int:pk>/", views.dispute_detail, name="dispute-detail"),
    # L9A problem reports. Seen by everyone who sees disputes; acknowledging
    # and closing are checked again (`manage_disputes`) by the domain service.
    path(
        "disputes/problems/",
        capability_required(VIEW_PROBLEMS_PERMISSION)(problems),
        name="problems",
    ),
    path(
        "disputes/problems/<int:pk>/",
        capability_required(VIEW_PROBLEMS_PERMISSION)(problem_detail),
        name="problem-detail",
    ),
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
        "staff/<int:pk>/two-step-reset/",
        views.staff_two_step_reset,
        name="staff-two-step-reset",
    ),
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
    # L3B. Guarded by the permission the domain commands check, so the page
    # and the command behind it cannot disagree about who may act.
    path(
        "system/geography/sea-crossings/new/",
        capability_required(MANAGE_CROSSINGS_PERMISSION)(sea_crossing_new),
        name="sea-crossing-new",
    ),
    path(
        "system/geography/sea-crossings/<int:pk>/<slug:action>/",
        capability_required(MANAGE_CROSSINGS_PERMISSION)(sea_crossing_toggle),
        name="sea-crossing-toggle",
    ),
    path("audit/", views.audit_log, name="audit"),
    path("technical/", views.technical_records, name="technical"),
]
