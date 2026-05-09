from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import OAuthIdentity, PasswordResetCode, User


@admin.register(User)
class ShipTripUserAdmin(UserAdmin):
    list_display = (
        "email",
        "full_name",
        "wilaya",
        "role",
        "is_phone_verified",
        "is_kyc_verified",
        "is_staff",
    )
    list_filter = ("role", "wilaya", "is_phone_verified", "is_kyc_verified", "is_staff")
    search_fields = ("email", "phone", "full_name", "username")
    ordering = ("email",)
    fieldsets = UserAdmin.fieldsets + (
        ("ShipTrip", {
            "fields": ("full_name", "phone", "wilaya", "role",
                       "is_phone_verified", "is_email_verified", "is_kyc_verified"),
        }),
    )


@admin.register(OAuthIdentity)
class OAuthIdentityAdmin(admin.ModelAdmin):
    list_display = ("user", "provider", "subject", "email_at_link", "created_at")
    list_filter = ("provider",)
    search_fields = ("user__email", "subject", "email_at_link")
    readonly_fields = ("created_at",)


@admin.register(PasswordResetCode)
class PasswordResetCodeAdmin(admin.ModelAdmin):
    list_display = ("user", "attempts", "expires_at", "used_at", "created_at")
    search_fields = ("user__email",)
    readonly_fields = ("code_hash", "created_at")
