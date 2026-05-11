from __future__ import annotations

from rest_framework import serializers

from .models import HandoverCode


class HandoverCodeIssueRequestSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=HandoverCode.Kind.choices)


class HandoverCodeIssueResponseSerializer(serializers.Serializer):
    handover_id = serializers.IntegerField()
    code = serializers.CharField()
    kind = serializers.CharField()
    note = serializers.CharField(
        default="Save this code — it will not be shown again.",
    )


class HandoverCodeVerifyRequestSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=HandoverCode.Kind.choices)
    code = serializers.RegexField(regex=r"^\d{6}$")


class HandoverCodeSerializer(serializers.ModelSerializer):
    class Meta:
        model = HandoverCode
        fields = (
            "id",
            "match",
            "kind",
            "status",
            "attempts",
            "issued_to",
            "used_at",
            "used_by",
            "created_at",
        )
        read_only_fields = fields
