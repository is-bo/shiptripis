"""Dormant H0 payout contracts. Provider execution belongs to H3/H4.

Imported by models.py so Django remains the only migration authority.
Financial history uses PROTECT; immutable rows reject ORM bulk mutation too.
PostgreSQL triggers installed by the constraint migration protect raw writes.
"""

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone


class FinancialMode(models.TextChoices):
    TEST = "test", "Test"
    LIVE = "live", "Live"
    LEGACY_UNKNOWN = "legacy_unknown", "Legacy unknown"


class ImmutableQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Financial history is immutable.")

    def delete(self):
        raise ValidationError("Financial history is immutable.")

    def bulk_update(self, *args, **kwargs):
        raise ValidationError("Financial history is immutable.")


class ImmutableRecord(models.Model):
    objects = ImmutableQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Financial history is immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Financial history is immutable.")


def protected(model, **kwargs):
    return models.ForeignKey(model, on_delete=models.PROTECT, **kwargs)


def optional(model, **kwargs):
    return protected(model, null=True, blank=True, **kwargs)


class StripePayoutAccount(models.Model):
    public_reference = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    traveler = protected(settings.AUTH_USER_MODEL)
    platform_id = models.CharField(max_length=255)
    provider_account_id = models.CharField(max_length=255)
    provider_mode = models.CharField(max_length=16, choices=FinancialMode.choices)
    declared_country = models.CharField(max_length=2)
    verified_country = models.CharField(max_length=2, blank=True)
    creation_operation_key = models.CharField(max_length=160, unique=True)
    status = models.CharField(max_length=24, default="setup_required")
    # H2: a safe machine reason for the current status. Never provider prose,
    # never a requirement's `errors[].reason`, which can quote what was typed.
    status_reason = models.CharField(max_length=64, blank=True)
    active = models.BooleanField(default=True)
    transfers_status = models.CharField(max_length=24, default="unrequested")
    payouts_enabled = models.BooleanField(default=False)
    details_submitted = models.BooleanField(default=False)
    requirement_codes = models.JSONField(default=list)
    # H2: `requirements.past_due` and `requirements.pending_verification` keys
    # and the deadline. Keys only; the projections stay code-shaped.
    past_due_codes = models.JSONField(default=list)
    pending_verification_codes = models.JSONField(default=list)
    requirements_deadline = models.DateTimeField(null=True, blank=True)
    disabled_reason = models.CharField(max_length=64, blank=True)
    # H2: the four controller values H0 selected, as the provider reports them.
    # Readiness compares against the expected hash rather than trusting that an
    # account this platform once created still has the configuration it asked
    # for.
    controller_summary = models.JSONField(default=dict)
    default_currency = models.CharField(max_length=3, blank=True)
    external_account_id = models.CharField(max_length=255, blank=True)
    eur_bank_present = models.BooleanField(default=False)
    readiness_checked_at = models.DateTimeField(null=True, blank=True)
    readiness_generation = models.PositiveBigIntegerField(default=0)
    payout_schedule_interval = models.CharField(max_length=16, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "finance_stripe_payout_account"
        constraints = [
            models.UniqueConstraint(
                fields=["platform_id", "provider_mode", "provider_account_id"],
                name="fin_stripe_account_identity",
            ),
            models.UniqueConstraint(
                fields=["traveler", "platform_id", "provider_mode"],
                condition=Q(active=True),
                name="fin_stripe_one_active_account",
            ),
            models.CheckConstraint(
                condition=Q(provider_mode__in=["test", "live"]),
                name="fin_stripe_account_known_mode",
            ),
        ]


class PayoutIdentityAttestation(ImmutableRecord):
    public_reference = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    traveler = protected(
        settings.AUTH_USER_MODEL, related_name="payout_identity_attestations"
    )
    kyc_submission = protected("kyc.KycSubmission")
    given_name_encrypted = models.TextField()
    family_name_encrypted = models.TextField()
    aliases_encrypted = models.TextField()
    script_metadata = models.CharField(max_length=64, blank=True)
    attested_by = protected(
        settings.AUTH_USER_MODEL, related_name="payout_attestations_made"
    )
    policy_version = models.CharField(max_length=64)
    attested_at = models.DateTimeField(default=timezone.now)
    supersedes = optional("self", related_name="successors")

    class Meta:
        db_table = "finance_payout_identity_attestation"


class PayoutIdentityRevocation(ImmutableRecord):
    attestation = models.OneToOneField(
        PayoutIdentityAttestation, on_delete=models.PROTECT, related_name="revocation"
    )
    actor = protected(settings.AUTH_USER_MODEL)
    reason_code = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "finance_payout_identity_revocation"


class PayoutIdentityReviewAssignment(models.Model):
    public_reference = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    traveler = protected(
        settings.AUTH_USER_MODEL, related_name="payout_identity_reviews"
    )
    reviewer = protected(
        settings.AUTH_USER_MODEL, related_name="assigned_payout_identity_reviews"
    )
    kyc_submission = protected("kyc.KycSubmission")
    assigned_by = protected(
        settings.AUTH_USER_MODEL, related_name="payout_identity_assignments_made"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True)

    class Meta:
        db_table = "finance_payout_identity_review_assignment"


class PayoutEvidence(ImmutableRecord):
    """Reference contract only. H1 has no upload/storage/proxy endpoint."""

    public_reference = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    owner = protected(settings.AUTH_USER_MODEL)
    purpose = models.CharField(
        max_length=24,
        choices=[
            (v, v) for v in ("account_document", "transfer_receipt", "return_evidence")
        ],
    )
    logical_store = models.CharField(max_length=24, default="payout", editable=False)
    object_key = models.CharField(max_length=512, blank=True)
    encryption_key_id = models.CharField(max_length=64, blank=True)
    digest = models.CharField(max_length=64, blank=True)
    mime_type = models.CharField(max_length=64, blank=True)
    size_bytes = models.PositiveBigIntegerField(null=True)
    upload_state = models.CharField(max_length=16, default="unconfigured")
    retention_class = models.CharField(max_length=32, default="payout_financial")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "finance_payout_evidence"
        constraints = [
            models.CheckConstraint(
                condition=Q(logical_store="payout"), name="fin_payout_evidence_store"
            )
        ]


class DzdPayoutProfileRevision(ImmutableRecord):
    public_reference = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    method = protected("finance.TravelerPayoutMethod", related_name="dzd_revisions")
    sequence = models.PositiveIntegerField()
    first_name_encrypted = models.TextField()
    last_name_encrypted = models.TextField()
    ccp_number_encrypted = models.TextField()
    ccp_key_encrypted = models.TextField()
    nip_encrypted = models.TextField()
    ccp_last_four = models.CharField(max_length=4)
    nip_last_four = models.CharField(max_length=4)
    account_fingerprint = models.CharField(max_length=64, db_index=True)
    evidence = optional(PayoutEvidence)
    identity_attestation = optional(PayoutIdentityAttestation)
    status = models.CharField(max_length=24, default="pending_review")
    submitted_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "finance_dzd_profile_revision"
        constraints = [
            models.UniqueConstraint(
                fields=["method", "sequence"], name="fin_dzd_profile_sequence"
            )
        ]


class PayoutProfileReview(ImmutableRecord):
    profile = protected(DzdPayoutProfileRevision, related_name="reviews")
    reviewer = protected(settings.AUTH_USER_MODEL)
    identity_attestation = protected(PayoutIdentityAttestation)
    status = models.CharField(
        max_length=24,
        choices=[(v, v) for v in ("approved", "rejected", "needs_attention")],
    )
    reason_code = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "finance_payout_profile_review"


class PayoutMethodVersion(ImmutableRecord):
    public_reference = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    method = protected("finance.TravelerPayoutMethod", related_name="versions")
    sequence = models.PositiveIntegerField()
    rail = models.CharField(max_length=20)
    currency = models.CharField(max_length=3)
    country = models.CharField(max_length=2, blank=True)
    stripe_account = optional(StripePayoutAccount)
    dzd_profile_revision = optional(DzdPayoutProfileRevision)
    policy_version = models.CharField(max_length=64)
    consent_at = models.DateTimeField()
    created_by = optional(settings.AUTH_USER_MODEL)
    source = models.CharField(max_length=32, default="traveler")
    content_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "finance_payout_method_version"
        constraints = [
            models.UniqueConstraint(
                fields=["method", "sequence"], name="fin_method_version_sequence"
            ),
            models.CheckConstraint(
                condition=Q(rail="manual", currency="DZD", stripe_account__isnull=True)
                | Q(
                    rail="stripe_transfer",
                    currency="EUR",
                    dzd_profile_revision__isnull=True,
                ),
                name="fin_method_version_pairing",
            ),
        ]


class PayoutAmountRevision(ImmutableRecord):
    payout = protected("finance.Payout", related_name="amount_revisions")
    revision = models.PositiveIntegerField()
    previous_amount_eur_cents = models.PositiveBigIntegerField()
    amount_eur_cents = models.PositiveBigIntegerField()
    previous_settlement_amount_minor = models.PositiveBigIntegerField(null=True)
    settlement_amount_minor = models.PositiveBigIntegerField(null=True)
    fx_rate_micros = models.PositiveBigIntegerField(null=True)
    fx_settings_version = optional("core.BusinessSettingsVersion")
    settlement_reference = models.CharField(max_length=160)
    ledger_transaction = optional("finance.LedgerTransaction")
    actor = optional(settings.AUTH_USER_MODEL)
    reason_code = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "finance_payout_amount_revision"
        constraints = [
            models.UniqueConstraint(
                fields=["payout", "revision"], name="fin_amount_revision_sequence"
            ),
            models.UniqueConstraint(
                fields=["payout", "settlement_reference"],
                name="fin_amount_revision_decision",
            ),
        ]


class PayoutInstructionAmendment(ImmutableRecord):
    payout = protected("finance.Payout", related_name="instruction_amendments")
    sequence = models.PositiveIntegerField()
    old_version = protected(PayoutMethodVersion, related_name="amendments_from")
    new_version = protected(PayoutMethodVersion, related_name="amendments_to")
    traveler = protected(settings.AUTH_USER_MODEL, related_name="payout_confirmations")
    confirmed_at = models.DateTimeField()
    reviewed_by = protected(
        settings.AUTH_USER_MODEL, related_name="payout_amendment_reviews"
    )
    reason_code = models.CharField(max_length=64)
    expected_state = models.CharField(max_length=16)
    expected_state_version = models.PositiveBigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "finance_payout_instruction_amendment"
        constraints = [
            models.UniqueConstraint(
                fields=["payout", "sequence"], name="fin_instruction_sequence"
            )
        ]


class PayoutInstructionConfirmation(ImmutableRecord):
    public_reference = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    payout = protected("finance.Payout", related_name="instruction_confirmations")
    new_version = protected(PayoutMethodVersion)
    traveler = protected(settings.AUTH_USER_MODEL)
    expected_state_version = models.PositiveBigIntegerField()
    confirmed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "finance_payout_instruction_confirmation"


class PayoutAttempt(models.Model):
    class Status(models.TextChoices):
        PREPARED = "prepared", "Prepared"
        DISPATCH_COMMITTED = "dispatch_committed", "Dispatch committed"
        UNKNOWN = "unknown", "Unknown"
        ACCEPTED = "accepted", "Accepted"
        SENT = "sent", "Sent"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        RETURNED = "returned", "Returned"
        CANCELLED = "cancelled", "Cancelled"

    payout = protected("finance.Payout", related_name="attempts")
    sequence = models.PositiveIntegerField()
    instruction_version = protected(PayoutMethodVersion)
    amount_revision = optional(PayoutAmountRevision)
    amount_eur_cents = models.PositiveBigIntegerField()
    currency = models.CharField(max_length=3)
    rail = models.CharField(max_length=20)
    provider_mode = models.CharField(max_length=16, choices=FinancialMode.choices)
    status = models.CharField(
        max_length=24, choices=Status.choices, default=Status.PREPARED
    )
    idempotency_key = models.CharField(max_length=160, unique=True)
    request_fingerprint = models.CharField(max_length=64)
    operator = optional(settings.AUTH_USER_MODEL)
    fencing_generation = models.PositiveBigIntegerField(default=0)
    committed_at = models.DateTimeField(null=True)
    result_at = models.DateTimeField(null=True)
    failure_code = models.CharField(max_length=64, blank=True)
    provider_request_id = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "finance_payout_attempt"
        constraints = [
            models.UniqueConstraint(
                fields=["payout"],
                condition=Q(status="prepared"),
                name="fin_payout_one_prepared_attempt",
            ),
            models.UniqueConstraint(
                fields=["payout", "sequence"], name="fin_payout_attempt_sequence"
            ),
            models.UniqueConstraint(
                fields=["payout"],
                condition=Q(
                    status__in=["dispatch_committed", "unknown", "accepted", "sent"]
                ),
                name="fin_payout_one_committed_attempt",
            ),
            models.CheckConstraint(
                condition=Q(amount_eur_cents__gt=0), name="fin_payout_attempt_positive"
            ),
            models.CheckConstraint(
                condition=Q(rail="manual", currency="DZD")
                | Q(rail="stripe_transfer", currency="EUR"),
                name="fin_payout_attempt_pairing",
            ),
            models.CheckConstraint(
                condition=Q(provider_mode__in=["test", "live"]),
                name="fin_payout_attempt_known_mode",
            ),
        ]


class PayoutProviderOperation(models.Model):
    public_reference = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    attempt = optional(PayoutAttempt, related_name="operations")
    method = optional("finance.TravelerPayoutMethod")
    kind = models.CharField(
        max_length=24,
        choices=[
            (v, v)
            for v in (
                "account_create",
                "transfer_create",
                "bank_payout_create",
                "transfer_reverse",
                "bank_payout_cancel",
            )
        ],
    )
    account_scope = models.CharField(max_length=255)
    provider_mode = models.CharField(max_length=16, choices=FinancialMode.choices)
    sequence = models.PositiveIntegerField()
    idempotency_key = models.CharField(max_length=160, unique=True)
    request_fingerprint = models.CharField(max_length=64)
    provider_object_id = models.CharField(max_length=255, blank=True)
    provider_request_id = models.CharField(max_length=255, blank=True)
    status = models.CharField(
        max_length=16,
        default="prepared",
        choices=[
            (v, v)
            for v in (
                "prepared",
                "committed",
                "unknown",
                "accepted",
                "failed",
                "reconciled",
            )
        ],
    )
    amount_minor = models.PositiveBigIntegerField(null=True)
    currency = models.CharField(max_length=3, blank=True)
    retry_after = models.DateTimeField(null=True)
    first_request_at = models.DateTimeField(null=True)
    last_request_at = models.DateTimeField(null=True)
    response_code = models.PositiveSmallIntegerField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "finance_payout_provider_operation"
        constraints = [
            models.UniqueConstraint(
                fields=["attempt", "sequence"],
                condition=Q(attempt__isnull=False),
                name="fin_payout_operation_sequence",
            ),
            models.UniqueConstraint(
                fields=["method", "sequence"],
                condition=Q(method__isnull=False),
                name="fin_account_operation_sequence",
            ),
            models.CheckConstraint(
                condition=Q(attempt__isnull=False, method__isnull=True)
                | Q(attempt__isnull=True, method__isnull=False, kind="account_create"),
                name="fin_payout_operation_owner",
            ),
            models.UniqueConstraint(
                fields=["kind", "account_scope", "provider_mode", "provider_object_id"],
                condition=~Q(provider_object_id=""),
                name="fin_payout_operation_identity",
            ),
            models.CheckConstraint(
                condition=Q(provider_mode__in=["test", "live"]),
                name="fin_payout_operation_known_mode",
            ),
        ]


class PayoutFundingAllocation(ImmutableRecord):
    allocation_key = models.CharField(max_length=160, unique=True)
    payout = protected("finance.Payout", related_name="funding_allocations")
    attempt = optional(PayoutAttempt)
    source_attempt = protected(
        "finance.PaymentAttempt", related_name="payout_allocations"
    )
    source_charge_id = models.CharField(max_length=255, blank=True)
    provider = models.CharField(max_length=16)
    provider_mode = models.CharField(max_length=16, choices=FinancialMode.choices)
    purpose = models.CharField(max_length=24)
    currency = models.CharField(max_length=3)
    amount_eur_cents = models.PositiveBigIntegerField()
    unavailable_reason = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "finance_payout_funding_allocation"
        constraints = [
            models.CheckConstraint(
                condition=Q(amount_eur_cents__gt=0),
                name="fin_payout_allocation_positive",
            )
        ]


class FinanceHold(models.Model):
    deal = optional("deals.Deal", related_name="finance_holds")
    payout = optional("finance.Payout", related_name="holds")
    account = optional(StripePayoutAccount, related_name="holds")
    source_attempt = optional("finance.PaymentAttempt", related_name="finance_holds")
    kind = models.CharField(
        max_length=24,
        choices=[
            (v, v)
            for v in (
                "dispute",
                "provider_dispute",
                "fraud",
                "refund",
                "compliance",
                "treasury",
                "manual",
            )
        ],
    )
    reason_code = models.CharField(max_length=64)
    source_reference = models.CharField(max_length=160)
    amount_exposure_eur_cents = models.PositiveBigIntegerField(null=True)
    opened_by = optional(settings.AUTH_USER_MODEL, related_name="finance_holds_opened")
    opened_at = models.DateTimeField(default=timezone.now)
    cleared_by = optional(
        settings.AUTH_USER_MODEL, related_name="finance_holds_cleared"
    )
    cleared_at = models.DateTimeField(null=True)
    generation = models.PositiveBigIntegerField(default=1)

    class Meta:
        db_table = "finance_hold"
        indexes = [
            models.Index(fields=["payout", "cleared_at"], name="fin_hold_active_payout")
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(
                        deal__isnull=False,
                        payout__isnull=True,
                        account__isnull=True,
                        source_attempt__isnull=True,
                    )
                    | Q(
                        deal__isnull=True,
                        payout__isnull=False,
                        account__isnull=True,
                        source_attempt__isnull=True,
                    )
                    | Q(
                        deal__isnull=True,
                        payout__isnull=True,
                        account__isnull=False,
                        source_attempt__isnull=True,
                    )
                    | Q(
                        deal__isnull=True,
                        payout__isnull=True,
                        account__isnull=True,
                        source_attempt__isnull=False,
                    )
                ),
                name="fin_hold_exactly_one_scope",
            )
        ]


class ProviderDispute(models.Model):
    provider = models.CharField(max_length=16)
    platform_id = models.CharField(max_length=255)
    provider_mode = models.CharField(max_length=16, choices=FinancialMode.choices)
    provider_object_id = models.CharField(max_length=255)
    source_attempt = optional("finance.PaymentAttempt")
    source_charge_id = models.CharField(max_length=255, blank=True)
    amount_minor = models.PositiveBigIntegerField()
    currency = models.CharField(max_length=3)
    canonical_amount_eur_cents = models.PositiveBigIntegerField(null=True)
    status = models.CharField(max_length=32)
    funds_withdrawn_reference = models.CharField(max_length=255, blank=True)
    funds_reinstated_reference = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "finance_provider_dispute"
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "provider",
                    "platform_id",
                    "provider_mode",
                    "provider_object_id",
                ],
                name="fin_provider_dispute_identity",
            )
        ]


class PayoutEvent(ImmutableRecord):
    event_uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    payout = protected("finance.Payout", related_name="events")
    sequence = models.PositiveBigIntegerField()
    previous_state = models.CharField(max_length=16, blank=True)
    new_state = models.CharField(max_length=16)
    reason_code = models.CharField(max_length=64)
    actor = optional(settings.AUTH_USER_MODEL)
    source = models.CharField(max_length=32, default="system")
    operation = optional(PayoutProviderOperation)
    evidence = optional(PayoutEvidence)
    ledger_transaction = optional("finance.LedgerTransaction")
    occurred_at = models.DateTimeField(default=timezone.now)
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "finance_payout_event"
        constraints = [
            models.UniqueConstraint(
                fields=["payout", "sequence"], name="fin_payout_event_sequence"
            )
        ]
