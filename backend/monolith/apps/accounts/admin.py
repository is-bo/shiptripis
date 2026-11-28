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
read only and says where to change it. Staff rights are read only the same way
(decision D5): the staff and Super Admin flags, the role groups and "active".

A change saves only the fields the form changed, and a password goes through
the one password writer (`apps.accounts.sessions.write_password`), so a form
opened before a password reset cannot write the old hash or `session_epoch`
back over it (N1, N-D).
"""

from django.contrib import admin
from django.contrib.admin.forms import AdminPasswordChangeForm as SiteOwnPasswordForm
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import AdminPasswordChangeForm

from apps.core.admin_display import TONE_BAD, TONE_INFO, TONE_MUTE, TONE_OK, flag

from .models import OAuthIdentity, PasswordResetCode, User
from .sessions import write_password


class _WritesPassword:
    """Saves one of Django's password forms through the one password writer:
    every sign-in of the account ends with the change, and no other field of
    the row is written. Django's password forms all save through this hook."""

    def set_password_and_save(self, user, password_field_name="password1", commit=True):
        usable = self.cleaned_data.get("set_usable_password", True)
        write_password(user, self.cleaned_data[password_field_name] if usable else None)
        return user


class _PasswordForm(_WritesPassword, AdminPasswordChangeForm):
    """A member's password, set by an operator."""


class OwnPasswordForm(_WritesPassword, SiteOwnPasswordForm):
    """An operator's own password, changed with the old one
    (`apps.admin_panel.admin_site`)."""


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
                       "is_kyc_verified", "ban_state", "staff_rights"),
        }),
    )
    readonly_fields = (
        "ban_state",
        "staff_rights",
        "is_active",
        "is_staff",
        "is_superuser",
        "groups",
    )
    change_password_form = _PasswordForm

    def save_model(self, request, obj, form, change):
        if not change:
            super().save_model(request, obj, form, change)
            return
        # Only what the operator changed: the rest of the row may have moved
        # since the form was read (a reset, a role change in the console).
        columns = {field.name for field in obj._meta.concrete_fields}
        columns -= {"password", "session_epoch"}
        obj.save(update_fields=[name for name in form.changed_data if name in columns])

    @admin.display(description="Staff rights")
    def staff_rights(self, obj):
        return (
            "Staff access, roles and the Super Admin flag change on the staff page of the "
            "operations console, with a reason; a member's account is closed by deleting it."
        )

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
