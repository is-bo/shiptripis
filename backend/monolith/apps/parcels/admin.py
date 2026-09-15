from django.contrib import admin

from .models import DeliveryRequest, ParcelMedia, ParcelRequest, ProductRequest
from .lifecycle import with_lifecycle


class RequestStatusFilter(admin.SimpleListFilter):
    title = "status"
    parameter_name = "status"

    def lookups(self, request, model_admin):
        return ParcelRequest.Status.choices

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(lifecycle_status=self.value())
        return queryset


class RequestLifecycleAdminMixin:
    def get_queryset(self, request):
        return with_lifecycle(super().get_queryset(request))

    @admin.display(description="Status", ordering="lifecycle_status")
    def request_status(self, obj):
        return ParcelRequest.Status(obj.lifecycle_status).label


class ParcelMediaInline(admin.TabularInline):
    model = ParcelMedia
    extra = 0
    readonly_fields = ("created_at",)

    @staticmethod
    def _is_retired_product(obj):
        return obj is not None and obj.kind == ParcelRequest.Kind.PRODUCT

    def get_readonly_fields(self, request, obj=None):
        if self._is_retired_product(obj):
            return tuple(field.name for field in self.model._meta.fields)
        return super().get_readonly_fields(request, obj)

    def has_add_permission(self, request, obj=None):
        if self._is_retired_product(obj):
            return False
        return super().has_add_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        if self._is_retired_product(obj):
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if self._is_retired_product(obj):
            return False
        return super().has_delete_permission(request, obj)


@admin.register(ParcelRequest)
class ParcelRequestAdmin(RequestLifecycleAdminMixin, admin.ModelAdmin):
    list_display = (
        "id",
        "kind",
        "sender",
        "origin",
        "destination",
        "weight_kg",
        "request_status",
        "created_at",
    )
    list_filter = ("kind", RequestStatusFilter, "origin", "destination")
    search_fields = ("sender__email", "id")
    autocomplete_fields = ("sender", "origin", "destination")
    date_hierarchy = "created_at"
    inlines = [ParcelMediaInline]

    def has_add_permission(self, request):
        # Concrete DeliveryRequest creation remains available through its own
        # admin.  The polymorphic parent must never create a bare Product row.
        return False

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions

    def get_readonly_fields(self, request, obj=None):
        if obj is not None and obj.kind == ParcelRequest.Kind.PRODUCT:
            return tuple(field.name for field in self.model._meta.fields)
        return ()

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.kind == ParcelRequest.Kind.PRODUCT:
            return False
        return super().has_delete_permission(request, obj)


@admin.register(DeliveryRequest)
class DeliveryRequestAdmin(RequestLifecycleAdminMixin, admin.ModelAdmin):
    list_display = (
        "id",
        "sender",
        "schema_version",
        "origin",
        "destination",
        "pickup_location",
        "delivery_location",
        "base_amount_dzd",
        "traveler_reward_eur_cents",
        "request_status",
    )
    list_filter = ("schema_version", RequestStatusFilter)
    search_fields = ("sender__email", "title")
    autocomplete_fields = (
        "sender",
        "origin",
        "destination",
        "pickup_location",
        "delivery_location",
    )


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

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
