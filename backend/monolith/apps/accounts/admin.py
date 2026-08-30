"""Account operations.

Two things here are not stock Django. The booleans on the changelist are
rendered as worded chips rather than the default red/green icons, because on
this model the icons lie by convention: a red cross under IS BANNED means the
account is *fine*, and a red cross under IS KYC VERIFIED means it is not, and
the two are drawn identically. The chips carry the word and a tone that means
the same thing in every column of the admin.

The ban actions keep a confirmation step. They are bulk, they act on whoever
happens to be selected, and `is_active=False` logs a person out of an account
they may be mid-delivery on; a dropdown and one Go is not enough distance from
that.
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.template.response import TemplateResponse

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
        ("ShipTrip", {
            "fields": ("full_name", "phone", "wilaya", "role",
                       "is_phone_verified", "is_email_verified",
                       "is_kyc_verified", "is_banned"),
        }),
    )
    actions = ("ban_users", "unban_users")

    def _confirm(self, request, queryset, *, title, verb, consequence, apply):
        """Show who is affected, then act only on a deliberate second click."""

        if request.POST.get("st_confirm") == verb:
            count = apply(queryset)
            self.message_user(
                request, f"{verb.capitalize()}ned {count} account(s)."
            )
            return None
        return TemplateResponse(
            request,
            "admin/accounts/confirm_user_action.html",
            {
                **self.admin_site.each_context(request),
                "title": title,
                "verb": verb,
                "consequence": consequence,
                "accounts": queryset.order_by("email"),
                "count": queryset.count(),
                "action_name": f"{verb}_users",
                "opts": self.model._meta,
                "media": self.media,
            },
        )

    @admin.action(description="Ban selected users")
    def ban_users(self, request, queryset):
        return self._confirm(
            request,
            queryset,
            title="Ban these accounts?",
            verb="ban",
            consequence=(
                "Banning also deactivates the account, which signs the person "
                "out immediately — including out of a delivery already in "
                "progress. It does not cancel deals, move money or release a "
                "payout."
            ),
            apply=lambda qs: qs.update(is_banned=True, is_active=False),
        )

    @admin.action(description="Unban selected users")
    def unban_users(self, request, queryset):
        return self._confirm(
            request,
            queryset,
            title="Restore these accounts?",
            verb="unban",
            consequence="The account becomes active and can sign in again.",
            apply=lambda qs: qs.update(is_banned=False, is_active=True),
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
