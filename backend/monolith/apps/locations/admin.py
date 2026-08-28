from django.contrib import admin

from .models import Location


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "kind",
        "public_label",
        "city",
        "country_code",
        "owner",
        "created_at",
    )
    list_filter = ("kind", "country_code", "precision", "provider")
    search_fields = (
        "public_label",
        "private_label",
        "normalized_label",
        "city",
        "provider_place_id",
        "airport__iata",
        "owner__email",
    )
    autocomplete_fields = ("airport", "created_by", "owner")
    ordering = ("-created_at",)

    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in self.model._meta.fields)

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False
