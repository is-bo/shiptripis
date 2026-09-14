from rest_framework import serializers

from .models import Notification, NotificationPreference, PushDevice


class NotificationSerializer(serializers.ModelSerializer):
    resolved = serializers.BooleanField(read_only=True, default=False)
    class Meta:
        model = Notification
        fields = (
            "id",
            "channel",
            "event_id",
            "payload",
            "read_at",
            "resolved",
            "created_at",
        )
        read_only_fields = fields


class PushDeviceRegistrationSerializer(serializers.Serializer):
    token = serializers.CharField(write_only=True, min_length=20, max_length=4096)
    installation_id = serializers.UUIDField()
    platform = serializers.ChoiceField(choices=PushDevice.Platform.choices)
    app_version = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=32,
        default="",
    )


class PushDeviceSerializer(serializers.ModelSerializer):
    """Safe device receipt; token and fingerprint are intentionally absent."""

    class Meta:
        model = PushDevice
        fields = (
            "id",
            "installation_id",
            "platform",
            "app_version",
            "active",
            "last_seen_at",
            "updated_at",
        )
        read_only_fields = fields


class PushDeviceUnregisterSerializer(serializers.Serializer):
    installation_id = serializers.UUIDField()


class NotificationPreferenceSerializer(serializers.ModelSerializer):
    essential_enabled = serializers.SerializerMethodField()

    class Meta:
        model = NotificationPreference
        fields = (
            "essential_enabled",
            "messages_enabled",
            "marketplace_enabled",
        )
        read_only_fields = ("essential_enabled",)

    def get_essential_enabled(self, _obj) -> bool:
        return True
