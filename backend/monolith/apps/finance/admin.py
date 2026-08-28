"""Operations views over V1 money.

Everything financial is registered read-only. That is deliberate: an order's
money columns are derived from its attempts and refunds, the ledger is
append-only, and a payout may only be settled through
`complete_manual_payout`, which enforces the Phase 4 eligibility gate and
records the evidence the database constraint demands. An admin who could edit
these rows by hand could produce a state no service would ever create.

The one action offered is `requeue`, on a failed scheduled job — that is not a
money mutation, it is asking an idempotent handler to run again.
"""

from __future__ import annotations

from django.contrib import admin, messages
from django.utils import timezone

from .models import (
    GuestPaymentLink,
    LedgerEntry,
    LedgerTransaction,
    PaymentAttempt,
    PaymentOrder,
    PaymentProviderEvent,
    PaymentRefund,
    Payout,
    ScheduledJob,
    TravelerPayoutMethod,
)


class _ReadOnlyAdmin(admin.ModelAdmin):
    """No add, no change, no delete. Financial history is not editable."""

    def has_add_permission(self, request):  # noqa: ARG002
        return False

    def has_change_permission(self, request, obj=None):  # noqa: ARG002
        return False

    def has_delete_permission(self, request, obj=None):  # noqa: ARG002
        return False


class PaymentAttemptInline(admin.TabularInline):
    model = PaymentAttempt
    extra = 0
    can_delete = False
    fields = (
        "provider",
        "status",
        "amount_eur_cents",
        "payment_currency",
        "provider_amount_minor",
        "fx_rate_micros",
        "is_unapplied",
        "succeeded_at",
    )
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):  # noqa: ARG002
        return False


class PaymentRefundInline(admin.TabularInline):
    model = PaymentRefund
    extra = 0
    can_delete = False
    fields = (
        "amount_eur_cents",
        "provider",
        "reason",
        "status",
        "requires_manual_action",
        "succeeded_at",
    )
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):  # noqa: ARG002
        return False


@admin.register(PaymentOrder)
class PaymentOrderAdmin(_ReadOnlyAdmin):
    list_display = (
        "id",
        "purpose",
        "status",
        "owner",
        "amount_eur_cents",
        "credited_eur_cents",
        "paid_eur_cents",
        "refunded_eur_cents",
        "outstanding_display",
        "created_at",
    )
    list_filter = ("purpose", "status", "created_at")
    search_fields = ("public_reference", "owner__email", "deal__id")
    date_hierarchy = "created_at"
    inlines = (PaymentAttemptInline, PaymentRefundInline)
    readonly_fields = (
        "public_reference",
        "owner",
        "purpose",
        "currency",
        "amount_eur_cents",
        "credited_eur_cents",
        "paid_eur_cents",
        "refunded_eur_cents",
        "status",
        "delivery_request",
        "deal",
        "credit_source",
        "business_settings_version",
        "terms_snapshot",
        "paid_at",
        "cancelled_at",
        "created_at",
        "updated_at",
    )

    @admin.display(description="Outstanding")
    def outstanding_display(self, obj: PaymentOrder) -> int:
        return obj.outstanding_eur_cents


@admin.register(PaymentAttempt)
class PaymentAttemptAdmin(_ReadOnlyAdmin):
    list_display = (
        "id",
        "order",
        "provider",
        "status",
        "amount_eur_cents",
        "payment_currency",
        "provider_amount_minor",
        "is_unapplied",
        "created_at",
    )
    list_filter = ("provider", "status", "payment_currency", "is_unapplied")
    search_fields = ("provider_session_id", "provider_payment_id", "idempotency_key")
    date_hierarchy = "created_at"


@admin.register(PaymentProviderEvent)
class PaymentProviderEventAdmin(_ReadOnlyAdmin):
    list_display = (
        "id",
        "provider",
        "event_type",
        "processing_result",
        "processing_attempts",
        "next_retry_at",
        "signature_verified",
        "received_at",
    )
    list_filter = ("provider", "processing_result", "signature_verified")
    search_fields = (
        "provider_event_id",
        "event_type",
        "payload_fingerprint",
        "last_error_code",
        "last_error_message",
    )
    date_hierarchy = "received_at"


@admin.register(PaymentRefund)
class PaymentRefundAdmin(_ReadOnlyAdmin):
    list_display = (
        "id",
        "order",
        "amount_eur_cents",
        "provider",
        "reason",
        "status",
        "requires_manual_action",
        "next_retry_at",
        "created_at",
    )
    list_filter = ("provider", "status", "reason", "requires_manual_action")
    search_fields = (
        "provider_refund_id",
        "idempotency_key",
        "failure_code",
        "failure_message",
        "settlement_reference",
    )
    date_hierarchy = "created_at"


@admin.register(GuestPaymentLink)
class GuestPaymentLinkAdmin(_ReadOnlyAdmin):
    """Only the hash is stored, so nothing here can be turned back into a link."""

    list_display = ("id", "order", "label", "expires_at", "revoked_at", "consumed_at")
    list_filter = ("expires_at",)
    search_fields = ("order__public_reference",)
    readonly_fields = (
        "order",
        "token_hash",
        "created_by",
        "label",
        "expires_at",
        "revoked_at",
        "consumed_at",
        "created_at",
    )


class LedgerEntryInline(admin.TabularInline):
    model = LedgerEntry
    extra = 0
    can_delete = False
    fields = ("account", "amount_eur_cents", "user", "order", "deal", "note")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):  # noqa: ARG002
        return False


@admin.register(LedgerTransaction)
class LedgerTransactionAdmin(_ReadOnlyAdmin):
    list_display = ("id", "kind", "key", "reverses", "created_at")
    list_filter = ("kind", "created_at")
    search_fields = ("key", "note")
    date_hierarchy = "created_at"
    inlines = (LedgerEntryInline,)


@admin.register(LedgerEntry)
class LedgerEntryAdmin(_ReadOnlyAdmin):
    list_display = (
        "id",
        "transaction",
        "account",
        "amount_eur_cents",
        "user",
        "deal",
        "created_at",
    )
    list_filter = ("account", "created_at")
    search_fields = ("note",)
    date_hierarchy = "created_at"


@admin.register(Payout)
class PayoutAdmin(_ReadOnlyAdmin):
    """Read-only on purpose.

    A payout is settled through `POST /api/admin/payouts/<id>/complete`, which
    refuses unless Phase 4 has released it and which records the actor,
    reference, currency, amount and rate. Editing the row here would let an
    operator mark money as sent with no evidence, which the
    `fin_payout_paid_requires_evidence` constraint exists to prevent.
    """

    list_display = (
        "id",
        "deal",
        "traveler",
        "amount_eur_cents",
        "method",
        "status",
        "eligible_at",
        "paid_at",
    )
    list_filter = ("status", "method")
    search_fields = ("traveler__email", "reference", "provider_payout_id")
    date_hierarchy = "created_at"


@admin.register(TravelerPayoutMethod)
class TravelerPayoutMethodAdmin(_ReadOnlyAdmin):
    list_display = (
        "id",
        "traveler",
        "method",
        "payouts_enabled",
        "country_code",
        "is_default",
        "capability_checked_at",
    )
    list_filter = ("method", "payouts_enabled", "is_default")
    search_fields = ("traveler__email", "provider_account_id")


@admin.register(ScheduledJob)
class ScheduledJobAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "kind",
        "status",
        "run_at",
        "attempts",
        "last_result",
        "locked_by",
    )
    list_filter = ("kind", "status")
    search_fields = ("key", "last_error", "last_result")
    date_hierarchy = "run_at"
    readonly_fields = (
        "key",
        "kind",
        "payload",
        "attempts",
        "locked_at",
        "locked_by",
        "last_error",
        "last_result",
        "completed_at",
        "created_at",
        "updated_at",
    )
    actions = ("requeue_jobs",)

    def has_add_permission(self, request):  # noqa: ARG002
        return False

    def has_delete_permission(self, request, obj=None):  # noqa: ARG002
        return False

    @admin.action(description="Requeue selected jobs to run now")
    def requeue_jobs(self, request, queryset):
        """Ask an idempotent handler to run again. Not a money mutation."""

        updated = queryset.filter(
            status__in=(ScheduledJob.Status.FAILED, ScheduledJob.Status.RUNNING)
        ).update(
            status=ScheduledJob.Status.PENDING,
            run_at=timezone.now(),
            attempts=0,
            locked_at=None,
            locked_by="",
            completed_at=None,
            updated_at=timezone.now(),
        )
        self.message_user(
            request, f"Requeued {updated} job(s).", level=messages.INFO
        )
