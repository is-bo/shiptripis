from rest_framework import serializers

from .models import ChatMessage


class ChatMessageSerializer(serializers.ModelSerializer):
    sender_id = serializers.IntegerField(read_only=True)
    match_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = ChatMessage
        fields = (
            "id",
            "match_id",
            "sender_id",
            "body",
            "created_at",
            "read_at",
        )
        read_only_fields = fields


class ChatSendSerializer(serializers.Serializer):
    """Validate an inbound message. `body` is trimmed; empty is rejected."""

    body = serializers.CharField(max_length=2000, trim_whitespace=True)
