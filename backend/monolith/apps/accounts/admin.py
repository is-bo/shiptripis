"""Account operations.

The booleans on the changelist are rendered as worded chips rather than the
default red/green icons, because on this model the icons lie by convention: a
red cross under IS BANNED means the account is *fine*, and a red cross under IS
KYC VERIFIED means it is not, and the two are drawn identically. The chips
carry the word and a tone that means the same thing in every column of the
admin.

There is no ban here (plan L16). Banning and restoring an account happen on the
person page of the operations console, with a required reason and an audit row
(`apps.admin_panel.staff_actions.set_account_ban`); this admin shows the flag
read only and says where to change it.
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from apps.core.admin_display import TONE_BAD, TONE_INFO, TONE_MUTE, TONE_OK, flag

from .models import OAuthIdentity, PasswordResetCode, User


@admin.register(User)
class ShipTripUserAdmin(UserAdmin):
    list_display = (
        "email",
        "full_name",
        "wilaya",
        "role",
        "phone_chip",
        "kyc_chip",
        "banned_chip",
        "staff_chip",
    )
    #: `True` is not the alarming value on every one of these — an unverified
    #: identity is what an operator should notice, and a banned account is.
    phone_chip = flag(
        "is_phone_verified", "Phone", true_tone=TONE_OK, false_tone=TONE_MUTE
    )
    kyc_chip = flag(
        "is_kyc_verified", "KYC", true_tone=TONE_OK, false_tone=TONE_MUTE
    )
    banned_chip = flag("is_banned", "Banned", true_tone=TONE_BAD, false_tone=TONE_MUTE)
    staff_chip = flag("is_staff", "Staff", true_tone=TONE_INFO, false_tone=TONE_MUTE)
    list_filter = (
        "role",
        "wilaya",
        "is_phone_verified",
        "is_kyc_verified",
        "is_banned",
        "is_staff",
    )
    search_fields = ("email", "phone", "full_name", "username")
    ordering = ("email",)
    fieldsets = UserAdmin.fieldsets + (
        ("Wassla", {
            "fields": ("full_name", "phone", "wilaya", "role",
                       "is_phone_verified", "is_email_verified",
                       "is_kyc_verified", "ban_state"),
        }),
    )
    readonly_fields = ("ban_state",)

    @admin.display(description="Ban")
    def ban_state(self, obj):
        state = "Banned" if obj.is_banned else "Not banned"
        return (
            f"{state}. Ban or restore an account on its person page in the operations "
            "console, with a reason."
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
