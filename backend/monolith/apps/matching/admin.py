"""Django admin for matching."""

from __future__ import annotations

from django.contrib import admin

from .models import Match, MatchEvent, Offer


class OfferInline(admin.TabularInline):
    model = Offer
    extra = 0
    fields = (
        "id",
        "proposed_by",
        "proposer",
        "status",
        "base_amount_dzd",
        "base_fee_dzd",
        "commission_dzd",
        "total_dzd",
        "parent_offer",
        "created_at",
    )
    readonly_fields = fields
    show_change_link = True


class MatchEventInline(admin.TabularInline):
    model = MatchEvent
    extra = 0
    fields = ("id", "kind", "actor", "offer", "payload", "created_at")
    readonly_fields = fields
    show_change_link = False


@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    list_display = ("id", "parcel", "trip", "sender", "traveler", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("parcel__id", "trip__id", "sender__email", "traveler__email")
    readonly_fields = ("created_at", "updated_at")
    inlines = (OfferInline, MatchEventInline)


@admin.register(Offer)
class OfferAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "match",
        "proposed_by",
        "status",
        "base_amount_dzd",
        "commission_dzd",
        "total_dzd",
        "created_at",
    )
    list_filter = ("status", "proposed_by")
    search_fields = ("match__id", "proposer__email")
    readonly_fields = (
        "match",
        "parent_offer",
        "proposed_by",
        "proposer",
        "base_amount_dzd",
        "base_fee_dzd",
        "commission_dzd",
        "total_dzd",
        "created_at",
        "updated_at",
        "responded_at",
    )


@admin.register(MatchEvent)
class MatchEventAdmin(admin.ModelAdmin):
    list_display = ("id", "match", "kind", "actor", "offer", "created_at")
    list_filter = ("kind",)
    search_fields = ("match__id",)
    readonly_fields = ("match", "offer", "actor", "kind", "payload", "created_at")
