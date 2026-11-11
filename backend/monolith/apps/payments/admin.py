"""Django admin for the legacy DZD payment history (view-only)."""

from __future__ import annotations

from django.contrib import admin

from apps.core.historical_admin import HistoricalRecordAdmin, HistoricalRecordInline

from .models import PaymentEvent, PaymentIntent, Refund


class PaymentEventInline(HistoricalRecordInline):
    model = PaymentEvent
    fields = ("id", "provider", "provider_event_id", "kind", "payload", "created_at")
    readonly_fields = fields
    show_change_link = False


class RefundInline(HistoricalRecordInline):
    model = Refund
    fields = (
        "id",
        "amount_minor",
        "currency",
        "provider",
        "provider_refund_id",
        "status",
        "reason",
        "succeeded_at",
        "created_at",
    )
    readonly_fields = fields
    show_change_link = True


@admin.register(PaymentIntent)
class PaymentIntentAdmin(HistoricalRecordAdmin):
    list_display = (
        "id",
        "offer",
        "payer",
        "provider",
        "amount_minor",
        "currency",
        "status",
        "created_at",
    )
    list_filter = ("status", "provider", "currency")
    search_fields = ("offer__id", "payer__email", "provider_intent_id")
    readonly_fields = (
        "offer",
        "payer",
        "provider",
        "provider_intent_id",
        "amount_minor",
        "currency",
        "client_idempotency_key",
        "failure_code",
        "failure_message",
        "succeeded_at",
        "refunded_at",
        "created_at",
        "updated_at",
    )
    inlines = (PaymentEventInline, RefundInline)


@admin.register(Refund)
class RefundAdmin(HistoricalRecordAdmin):
    list_display = (
        "id",
        "intent",
        "amount_minor",
        "currency",
        "provider",
        "status",
        "created_at",
    )
    list_filter = ("status", "provider")
    search_fields = ("intent__id", "provider_refund_id")
    readonly_fields = (
        "intent",
        "amount_minor",
        "currency",
        "provider",
        "provider_refund_id",
        "reason",
        "status",
        "succeeded_at",
        "created_at",
        "updated_at",
    )


@admin.register(PaymentEvent)
class PaymentEventAdmin(HistoricalRecordAdmin):
    list_display = ("id", "intent", "provider", "kind", "created_at")
    list_filter = ("provider", "kind")
    search_fields = ("intent__id", "provider_event_id")
    readonly_fields = (
        "intent",
        "provider",
        "provider_event_id",
        "kind",
        "payload",
        "created_at",
    )
