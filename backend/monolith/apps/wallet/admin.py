from __future__ import annotations

from django.contrib import admin

from .models import Hold, Wallet, WalletEntry, Withdrawal


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "currency", "created_at")
    list_filter = ("currency",)
    search_fields = ("user__email",)
    readonly_fields = ("user", "currency", "created_at", "updated_at")


@admin.register(WalletEntry)
class WalletEntryAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "wallet",
        "kind",
        "amount_minor",
        "currency",
        "source",
        "source_id",
        "created_at",
    )
    list_filter = ("kind", "currency", "source")
    search_fields = ("wallet__id", "key", "source_id")
    readonly_fields = (
        "wallet",
        "kind",
        "amount_minor",
        "currency",
        "key",
        "source",
        "source_id",
        "note",
        "created_at",
    )


@admin.register(Hold)
class HoldAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "wallet",
        "amount_minor",
        "currency",
        "source",
        "source_id",
        "status",
        "opened_at",
        "closed_at",
    )
    list_filter = ("status", "currency", "source")
    search_fields = ("wallet__id", "source_id")
    readonly_fields = (
        "wallet",
        "amount_minor",
        "currency",
        "source",
        "source_id",
        "status",
        "opened_at",
        "closed_at",
    )


@admin.register(Withdrawal)
class WithdrawalAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "wallet",
        "amount_minor",
        "currency",
        "destination",
        "status",
        "sent_at",
        "created_at",
    )
    list_filter = ("status", "currency", "destination")
    search_fields = ("user__email", "destination_ref")
    readonly_fields = (
        "wallet",
        "user",
        "amount_minor",
        "currency",
        "destination",
        "destination_ref",
        "created_at",
        "updated_at",
    )
    actions = ("mark_sent",)

    @admin.action(description="Mark selected withdrawals as sent")
    def mark_sent(self, request, queryset):
        from django.utils import timezone

        queryset.filter(status=Withdrawal.Status.REQUESTED).update(
            status=Withdrawal.Status.SENT, sent_at=timezone.now()
        )
