from __future__ import annotations

from django.contrib import admin, messages

from .models import AdminAuditLog, AdminInvitation
from .services import revoke_admin_invitation


@admin.register(AdminInvitation)
class AdminInvitationAdmin(admin.ModelAdmin):
    list_display = (
        "email",
        "role",
        "invited_by",
        "expires_at",
        "used_at",
        "revoked_at",
        "created_at",
    )
    list_filter = ("role", "used_at", "revoked_at")
    search_fields = ("email", "invited_by__email", "accepted_by__email")
    readonly_fields = (
        "id",
        "email",
        "role",
        "token_hash",
        "invited_by",
        "expires_at",
        "used_at",
        "revoked_at",
        "accepted_by",
        "created_at",
    )
    actions = ("revoke_selected",)

    @admin.action(description="Revoke selected unused invitations")
    def revoke_selected(self, request, queryset):
        count = 0
        for invitation in queryset:
            was_active = invitation.is_active
            revoke_admin_invitation(actor=request.user, invitation_id=invitation.pk)
            if was_active:
                count += 1
        self.message_user(request, f"Revoked {count} invitation(s).", messages.SUCCESS)

    def has_add_permission(self, request):
        # Invitation creation must go through the service/API so plaintext
        # tokens are returned once and every action is audited.
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AdminAuditLog)
class AdminAuditLogAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "action",
        "actor",
        "target_type",
        "target_id",
        "reason",
        "reference",
    )
    list_filter = ("action", "target_type")
    search_fields = ("action", "target_id", "actor__email", "reason", "reference")
    readonly_fields = (
        "id",
        "actor",
        "action",
        "target_type",
        "target_id",
        "reason",
        "reference",
        "before",
        "after",
        "metadata",
        "created_at",
    )
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
