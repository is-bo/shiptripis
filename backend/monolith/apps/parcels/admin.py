from django.contrib import admin

from .models import DeliveryRequest, ParcelMedia, ParcelRequest, ProductRequest


class ParcelMediaInline(admin.TabularInline):
    model = ParcelMedia
    extra = 0
    readonly_fields = ("created_at",)


@admin.register(ParcelRequest)
class ParcelRequestAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "kind",
        "sender",
        "origin",
        "destination",
        "weight_kg",
        "status",
        "created_at",
    )
    list_filter = ("kind", "status", "origin", "destination")
    search_fields = ("sender__email", "id")
    autocomplete_fields = ("sender", "origin", "destination")
    date_hierarchy = "created_at"
    inlines = [ParcelMediaInline]


@admin.register(DeliveryRequest)
class DeliveryRequestAdmin(admin.ModelAdmin):
    list_display = ("id", "sender", "origin", "destination", "base_amount_dzd", "status")
    list_filter = ("status",)
    search_fields = ("sender__email",)
    autocomplete_fields = ("sender", "origin", "destination")


@admin.register(ProductRequest)
class ProductRequestAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "sender",
        "store_name",
        "product_price_dzd",
        "origin",
        "destination",
        "status",
    )
    list_filter = ("status",)
    search_fields = ("sender__email", "store_name", "product_url")
    autocomplete_fields = ("sender", "origin", "destination")
