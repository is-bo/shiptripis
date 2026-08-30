"""Seed the local admin-preview database with representative operational states.

Local review only, never imported by the app. Every deal is driven through the
real services, so what the admin renders is what the services actually produce.
"""

from __future__ import annotations

from datetime import timedelta

from django.test import Client
from django.utils import timezone

from apps.accounts.models import User
from apps.core.models import BusinessSettingsVersion
from apps.deals.models import Deal
from apps.deals.tests.phase4_factories import (
    delivered_scenario,
    enable_mock_rail,
    past_protection,
)
from apps.disputes.models import Dispute, DisputeEvent, DisputeEvidence
from apps.finance.models import (
    PaymentAttempt,
    PaymentOrder,
    PaymentProviderEvent,
    PaymentRefund,
    Payout,
    ScheduledJob,
)
from apps.finance.tests.factories import build_scenario, make_user
from apps.kyc.models import KycSubmission
from apps.notifications.models import OutboundMessage
from apps.trips.models import JourneyLegProof

now = timezone.now()
client = Client()
enable_mock_rail()

# --- 1. A delivered deal past protection: the healthy end state ---------------
done = past_protection(delivered_scenario(client, prefix="ok"))
Payout.objects.update_or_create(
    deal=done.deal,
    defaults=dict(
        traveler=done.traveler,
        amount_eur_cents=3_000,
        method=Payout.Method.MANUAL,
        status=Payout.Status.ELIGIBLE,
        eligible_at=now - timedelta(hours=2),
        reference="PAYOUT-OK-1",
    ),
)

# --- 2. A delivered deal with an open dispute: payout frozen ------------------
hot = delivered_scenario(client, prefix="dsp")
deal = hot.deal
dispute = Dispute.objects.create(
    deal=deal,
    opened_by=hot.sender,
    opened_by_role=Dispute.OpenedByRole.SENDER,
    status=Dispute.Status.UNDER_REVIEW,
    category=Dispute.Category.DAMAGED,
    reason_text=(
        "Box arrived crushed on one corner and the contents rattle. Photos "
        "attached. The traveler says it was handed over in that state."
    ),
    protection_ends_at=now + timedelta(hours=30),
    payout_frozen=True,
)
DisputeEvent.objects.create(
    dispute=dispute, kind=DisputeEvent.Kind.OPENED, actor=hot.sender
)
DisputeEvent.objects.create(dispute=dispute, kind=DisputeEvent.Kind.PAYOUT_FROZEN)
DisputeEvent.objects.create(
    dispute=dispute, kind=DisputeEvent.Kind.EVIDENCE_ADDED, actor=hot.sender
)
DisputeEvent.objects.create(
    dispute=dispute,
    kind=DisputeEvent.Kind.STATUS_CHANGED,
    payload={"to": "under_review"},
)
DisputeEvidence.objects.create(
    dispute=dispute,
    submitted_by=hot.sender,
    kind=DisputeEvidence.Kind.PHOTO,
    storage_bucket="disputes",
    storage_key=str(dispute.public_reference) + "/corner.jpg",
    content_type="image/jpeg",
    size_bytes=418_233,
    content_sha256="a" * 64,
)
DisputeEvidence.objects.create(
    dispute=dispute,
    submitted_by=hot.traveler,
    kind=DisputeEvidence.Kind.TEXT,
    text="Handed over sealed at 18:40; the recipient signed without comment.",
)
Payout.objects.update_or_create(
    deal=deal,
    defaults=dict(
        traveler=hot.traveler,
        amount_eur_cents=3_000,
        method=Payout.Method.MANUAL,
        status=Payout.Status.NOT_ELIGIBLE,
        reference="PAYOUT-FROZEN-1",
        notes="Frozen by dispute review.",
    ),
)

# --- 3. A resolved dispute, so the queue carries both states ------------------
old = delivered_scenario(client, prefix="rsv")
resolved = Dispute.objects.create(
    deal=old.deal,
    opened_by=old.traveler,
    opened_by_role=Dispute.OpenedByRole.TRAVELER,
    status=Dispute.Status.RESOLVED,
    category=Dispute.Category.LATE,
    reason_text="Recipient was unreachable for two days after arrival.",
    resolution=Dispute.Resolution.PARTIAL_SPLIT,
    sender_refund_eur_cents=1_000,
    traveler_payout_eur_cents=2_000,
    platform_fee_eur_cents=750,
    collected_total_eur_cents=3_750,
    resolution_note="Split agreed by both sides after evidence review.",
    resolved_at=now - timedelta(days=1),
    resolved_by=old.admin,
    payout_already_settled=True,
)
DisputeEvent.objects.create(dispute=resolved, kind=DisputeEvent.Kind.RESOLVED)

# --- 4. An unfunded deal carrying a failed attempt and an unapplied payment ---
stuck = build_scenario(prefix="fail")
stuck.accept(reward_eur_cents=4_500)
order = stuck.balance_order()
PaymentAttempt.objects.create(
    order=order,
    provider="mock",
    payer=stuck.sender,
    amount_eur_cents=order.amount_eur_cents,
    payment_currency="EUR",
    provider_amount_minor=order.amount_eur_cents,
    provider_amount_exponent=2,
    idempotency_key="attempt-failed-1",
    status=PaymentAttempt.Status.FAILED,
    failure_code="card_declined",
    failure_message="Issuer declined the authorisation.",
)
unapplied = PaymentAttempt.objects.create(
    order=order,
    provider="mock",
    guest_email="guest@example.invalid",
    amount_eur_cents=2_500,
    payment_currency="DZD",
    provider_amount_minor=372_500,
    provider_amount_exponent=2,
    fx_rate_micros=149_000_000,
    fx_source="platform-configured",
    idempotency_key="attempt-unapplied-1",
    status=PaymentAttempt.Status.SUCCEEDED,
    is_unapplied=True,
    succeeded_at=now - timedelta(hours=5),
)
PaymentProviderEvent.objects.create(
    provider="mock",
    provider_event_id="evt-unverified-1",
    event_type="checkout.updated",
    attempt=unapplied,
    order=order,
    signature_verified=False,
    processing_result=PaymentProviderEvent.ProcessingResult.RETRYABLE,
    processing_note="Signature did not verify against the configured secret.",
    processing_attempts=3,
    last_error_code="bad_signature",
    last_error_message="HMAC mismatch",
    next_retry_at=now + timedelta(minutes=12),
)
PaymentProviderEvent.objects.create(
    provider="mock",
    provider_event_id="evt-applied-1",
    event_type="checkout.paid",
    order=order,
    signature_verified=True,
    processing_result=PaymentProviderEvent.ProcessingResult.APPLIED,
    processed_at=now - timedelta(hours=4),
)
PaymentRefund.objects.create(
    order=order,
    attempt=unapplied,
    amount_eur_cents=2_500,
    provider="mock",
    idempotency_key="refund-manual-1",
    reason=PaymentRefund.Reason.UNAPPLIED_PAYMENT,
    status=PaymentRefund.Status.FAILED,
    failure_code="provider_unavailable",
    failure_message="Refund endpoint returned 503 three times.",
    processing_attempts=3,
    requires_manual_action=True,
    requested_by=stuck.admin,
)

# --- 5. Jobs: one waiting, one retrying, one dead -----------------------------
ScheduledJob.objects.update_or_create(
    key="preview-payout-release-1",
    defaults=dict(
        kind=ScheduledJob.Kind.PAYOUT_RELEASE_CHECK,
        run_at=now + timedelta(hours=6),
        status=ScheduledJob.Status.PENDING,
        payload={"deal": str(done.deal.pk)},
    ),
)
ScheduledJob.objects.update_or_create(
    key="preview-provider-reconcile-1",
    defaults=dict(
        kind=ScheduledJob.Kind.PROVIDER_RECONCILE,
        run_at=now - timedelta(minutes=3),
        status=ScheduledJob.Status.PENDING,
        attempts=5,
        last_error="Provider timed out after 10s (attempt 5 of 8).",
    ),
)
ScheduledJob.objects.update_or_create(
    key="preview-attempt-expiry-1",
    defaults=dict(
        kind=ScheduledJob.Kind.ATTEMPT_EXPIRY,
        run_at=now - timedelta(hours=2),
        status=ScheduledJob.Status.FAILED,
        attempts=8,
        last_error="Max attempts reached; the attempt row was already terminal.",
        completed_at=now - timedelta(hours=1),
    ),
)

# --- 6. KYC and flight-proof queues ------------------------------------------
waiting = make_user("kyc-waiting@example.com")
turned_down = make_user("kyc-rejected@example.com")
KycSubmission.objects.create(
    user=waiting,
    document_type=KycSubmission.DocumentType.PASSPORT,
    idempotency_key="preview-kyc-pending-0000000000",
    front_image_key="kyc/pending/front.jpg",
    selfie_image_key="kyc/pending/selfie.jpg",
    status=KycSubmission.Status.PENDING,
)
KycSubmission.objects.create(
    user=turned_down,
    document_type=KycSubmission.DocumentType.ID_CARD,
    idempotency_key="preview-kyc-rejected-000000000",
    front_image_key="kyc/rejected/front.jpg",
    back_image_key="kyc/rejected/back.jpg",
    status=KycSubmission.Status.REJECTED,
    rejection_reason="Document photo is cut off at the top; the MRZ is unreadable.",
    reviewed_at=now - timedelta(days=2),
)

JourneyLegProof.objects.create(
    leg=done.base.leg,
    bucket="proofs",
    object_key="proofs/pending/boarding-pass.jpg",
    kind="ticket",
    bytes=284_112,
    status=JourneyLegProof.Status.PENDING,
)
JourneyLegProof.objects.create(
    leg=hot.base.leg,
    bucket="proofs",
    object_key="proofs/rejected/screenshot.png",
    kind="ticket",
    bytes=91_004,
    status=JourneyLegProof.Status.REJECTED,
    rejection_reason="Screenshot shows a search result, not a booked ticket.",
    reviewer=hot.admin,
    reviewed_at=now - timedelta(days=1),
)
JourneyLegProof.objects.create(
    leg=old.base.leg,
    bucket="proofs",
    object_key="proofs/approved/boarding-pass.jpg",
    kind="ticket",
    bytes=310_889,
    status=JourneyLegProof.Status.APPROVED,
    reviewer=old.admin,
    reviewed_at=now - timedelta(days=3),
)

# --- 7. Outbox: one delivered, one failing -----------------------------------
OutboundMessage.objects.update_or_create(
    key="preview-outbox-ok",
    defaults=dict(
        kind=OutboundMessage.Kind.PAYMENT_SUCCEEDED,
        to_email="ok@example.invalid",
        status=OutboundMessage.Status.DISPATCHED,
        context={"deal_reference": "D-1042"},
        dispatched_at=now - timedelta(hours=3),
        transport_event_id="evt-outbox-ok",
    ),
)
OutboundMessage.objects.update_or_create(
    key="preview-outbox-failed",
    defaults=dict(
        kind=OutboundMessage.Kind.KYC_STATUS,
        to_email="bounce@example.invalid",
        status=OutboundMessage.Status.FAILED,
        attempts=10,
        last_error="SMTP 550 5.1.1 recipient rejected (relay refused).",
        next_attempt_at=now - timedelta(minutes=30),
    ),
)

# --- 8. A draft settings version alongside the active one --------------------
active = (
    BusinessSettingsVersion.objects.filter(status="active").order_by("-version").first()
)
if active:
    BusinessSettingsVersion.objects.get_or_create(
        version=active.version + 1,
        defaults=dict(
            status="draft",
            commission_rate_bps=2_000,
            pricing_version="v1",
            policy=dict(active.policy),
        ),
    )

print("orders", PaymentOrder.objects.count())
print("deals", Deal.objects.count())
print("disputes", Dispute.objects.count())
print("kyc", KycSubmission.objects.count())
print("proofs", JourneyLegProof.objects.count())
print("jobs", ScheduledJob.objects.count())
print("users", User.objects.count())
