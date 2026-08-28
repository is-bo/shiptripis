from __future__ import annotations

from rest_framework import serializers

from .models import AdminAuditLog, AdminInvitation
from .permissions import ROLE_CHOICES, normalize_role


class AdminInvitationCreateSerializer(serializers.Serializer):
    email = serializers.EmailField()
    role = serializers.ChoiceField(choices=ROLE_CHOICES)
    # API accepts hours so operators cannot accidentally create a multi-day
    # capability; the service still enforces a positive TTL.
    expires_in_hours = serializers.IntegerField(
        min_value=1, max_value=24 * 7, required=False, default=24
    )

    def validate_email(self, value):
        return value.strip().lower()

    def validate_role(self, value):
        return normalize_role(value)


class AdminInvitationSerializer(serializers.ModelSerializer):
    is_active = serializers.BooleanField(read_only=True)

    class Meta:
        model = AdminInvitation
        fields = (
            "id",
            "email",
            "role",
            "expires_at",
            "used_at",
            "revoked_at",
            "accepted_by",
            "invited_by",
            "created_at",
            "is_active",
        )
        read_only_fields = fields


class AdminInvitationAcceptSerializer(serializers.Serializer):
    token = serializers.CharField(trim_whitespace=True, write_only=True)
    password = serializers.CharField(
        write_only=True,
        min_length=8,
        trim_whitespace=False,
        required=False,
        allow_blank=False,
    )
    full_name = serializers.CharField(required=False, allow_blank=True, max_length=120)


class AdminRoleChangeSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=ROLE_CHOICES)

    def validate_role(self, value):
        return normalize_role(value)


class AdminAuditLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdminAuditLog
        fields = (
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
        read_only_fields = fields
