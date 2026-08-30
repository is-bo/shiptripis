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

from apps.core.admin_display import TONE_ATTENTION, TONE_OK, flag, money, money_of, status

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
        "status_chip",
        "amount_display",
        "payment_currency",
        "provider_amount_minor",
        "fx_rate_micros",
        "unapplied_chip",
        "succeeded_at",
    )
    readonly_fields = fields
    status_chip = status("status", "Status")
    amount_display = money("amount_eur_cents", "Amount")
    unapplied_chip = flag(
        "is_unapplied", "Unapplied", true_text="Unapplied", false_text="Applied"
    )

    def has_add_permission(self, request, obj=None):  # noqa: ARG002
        return False


class PaymentRefundInline(admin.TabularInline):
    model = PaymentRefund
    extra = 0
    can_delete = False
    fields = (
        "amount_display",
        "provider",
        "reason",
        "status_chip",
        "manual_chip",
        "succeeded_at",
    )
    readonly_fields = fields
    amount_display = money("amount_eur_cents", "Refund amount", emphasis=True)
    status_chip = status("status", "Status")
    manual_chip = flag(
        "requires_manual_action", "Manual action",
        true_text="Required", false_text="Not needed",
    )

    def has_add_permission(self, request, obj=None):  # noqa: ARG002
        return False


@admin.register(PaymentOrder)
class PaymentOrderAdmin(_ReadOnlyAdmin):
    list_display = (
        "id",
        "purpose",
        "status_chip",
        "owner",
        "amount_display",
        "credited_display",
        "paid_display",
        "refunded_display",
        "outstanding_display",
        "created_at",
    )
    list_filter = ("purpose", "status", "created_at")
    list_select_related = ("owner",)
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

    status_chip = status("status", "Status")
    amount_display = money("amount_eur_cents", "Order total")
    credited_display = money("credited_eur_cents", "Credited")
    paid_display = money("paid_eur_cents", "Paid")
    refunded_display = money("refunded_eur_cents", "Refunded")
    # The number that decides whether anything still has to happen to this
    # order, so it is the one carrying weight on the row.
    outstanding_display = money_of(
        lambda obj: obj.outstanding_eur_cents, "Outstanding", emphasis=True
    )


@admin.register(PaymentAttempt)
class PaymentAttemptAdmin(_ReadOnlyAdmin):
    list_display = (
        "id",
        "order",
        "provider",
        "status_chip",
        "amount_display",
        "payment_currency",
        "provider_amount_minor",
        "unapplied_chip",
        "created_at",
    )
    status_chip = status("status", "Status")
    amount_display = money("amount_eur_cents", "Amount")
    unapplied_chip = flag(
        "is_unapplied", "Unapplied", true_text="Unapplied", false_text="Applied"
    )
    list_filter = ("provider", "status", "payment_currency", "is_unapplied")
    list_select_related = ("order",)
    search_fields = ("provider_session_id", "provider_payment_id", "idempotency_key")
    date_hierarchy = "created_at"


@admin.register(PaymentProviderEvent)
class PaymentProviderEventAdmin(_ReadOnlyAdmin):
    list_display = (
        "id",
        "provider",
        "event_type",
        "result_chip",
        "processing_attempts",
        "next_retry_at",
        "signature_chip",
        "received_at",
    )
    result_chip = status("processing_result", "Result")
    # Inverted on purpose: an unverified signature is the state that needs a
    # human, so it is the one wearing the alarm colour.
    signature_chip = flag(
        "signature_verified",
        "Signature",
        true_tone=TONE_OK,
        false_tone=TONE_ATTENTION,
        true_text="Verified",
        false_text="Unverified",
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
        "amount_display",
        "provider",
        "reason",
        "status_chip",
        "manual_chip",
        "next_retry_at",
        "created_at",
    )
    # A refund row's amount is money leaving the platform, so it is set as the
    # consequence of the row rather than as one column among nine.
    amount_display = money("amount_eur_cents", "Refund amount", emphasis=True)
    status_chip = status("status", "Status")
    manual_chip = flag(
        "requires_manual_action", "Manual action",
        true_text="Required", false_text="Not needed",
    )
    list_filter = ("provider", "status", "reason", "requires_manual_action")
    list_select_related = ("order",)
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
    fields = ("account", "amount_display", "user", "order", "deal", "note")
    readonly_fields = fields
    amount_display = money("amount_eur_cents", "Amount")

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
        "amount_display",
        "user",
        "deal",
        "created_at",
    )
    amount_display = money("amount_eur_cents", "Amount")
    list_filter = ("account", "created_at")
    list_select_related = ("transaction", "user", "deal")
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
        "amount_display",
        "method",
        "status_chip",
        "eligible_at",
        "paid_at",
    )
    amount_display = money("amount_eur_cents", "Payout amount", emphasis=True)
    status_chip = status("status", "Status")
    list_filter = ("status", "method")
    list_select_related = ("deal", "traveler")
    search_fields = ("traveler__email", "reference", "provider_payout_id")
    date_hierarchy = "created_at"


@admin.register(TravelerPayoutMethod)
class TravelerPayoutMethodAdmin(_ReadOnlyAdmin):
    list_display = (
        "id",
        "traveler",
        "method",
        "enabled_chip",
        "country_code",
        "is_default",
        "capability_checked_at",
    )
    enabled_chip = flag(
        "payouts_enabled",
        "Payouts",
        true_tone=TONE_OK,
        false_tone=TONE_ATTENTION,
        true_text="Enabled",
        false_text="Blocked",
    )
    list_filter = ("method", "payouts_enabled", "is_default")
    search_fields = ("traveler__email", "provider_account_id")


@admin.register(ScheduledJob)
class ScheduledJobAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "kind",
        "status_chip",
        "run_at",
        "attempt_budget",
        "last_result",
        "locked_by",
    )
    status_chip = status("status", "Status")
    list_filter = ("kind", "status")
    search_fields = ("key", "last_error", "last_result")
    date_hierarchy = "run_at"
    # Every column is read-only, `requeue_jobs` included in the docstring above
    # as the one mutation. `status`, `run_at` and `max_attempts` used to stay
    # editable on the change form, which quietly reopened the path the action
    # exists to replace: marking a `payout_release_check` job "succeeded" by
    # hand cancels a scheduled money action, and leaves no record that anyone
    # did. The action is now the only way to move a job, and it says what it
    # did in the message log.
    readonly_fields = (
        "key",
        "kind",
        "payload",
        "run_at",
        "status",
        "attempt_budget",
        "attempts",
        "max_attempts",
        "locked_at",
        "locked_by",
        "last_error",
        "last_result",
        "completed_at",
        "created_at",
        "updated_at",
    )
    actions = ("requeue_jobs",)

    @admin.display(description="Attempts", ordering="attempts")
    def attempt_budget(self, obj: ScheduledJob) -> str:
        """`5 / 8` is a position in a budget; `5` on its own is not."""

        return f"{obj.attempts} / {obj.max_attempts}"

    def has_add_permission(self, request):  # noqa: ARG002
        return False

    def has_change_permission(self, request, obj=None):  # noqa: ARG002
        # List level stays true, because the requeue action needs it. The
        # object page has nothing left to change, so it renders as a view and
        # does not offer a Save that would save nothing.
        return obj is None

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
