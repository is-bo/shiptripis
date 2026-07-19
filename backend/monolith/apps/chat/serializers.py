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


class ChatThreadSerializer(serializers.Serializer):
    """One row in the Mailroom inbox: a paid match the viewer can chat on.

    Read-only projection. The view annotates `last_body` / `last_at` / `unread`
    and passes the viewer via context so we can name the *other* party. There
    is no thread table — a Match is the thread (see ChatMessage docstring)."""

    match_id = serializers.IntegerField(source="id", read_only=True)
    counterparty_id = serializers.SerializerMethodField()
    counterparty_name = serializers.SerializerMethodField()
    route = serializers.SerializerMethodField()
    status = serializers.CharField(read_only=True)
    last_message = serializers.CharField(source="last_body", read_only=True)
    last_message_at = serializers.DateTimeField(source="last_at", read_only=True)
    unread_count = serializers.IntegerField(source="unread", read_only=True)

    def _viewer_id(self) -> int:
        return self.context["viewer_id"]

    def _counterparty(self, obj):
        return obj.traveler if self._viewer_id() == obj.sender_id else obj.sender

    def get_counterparty_id(self, obj) -> int:
        return self._counterparty(obj).id

    def get_counterparty_name(self, obj) -> str:
        return self._counterparty(obj).full_name

    def get_route(self, obj) -> str:
        # Airport PK is the IATA code, so origin_id/destination_id are the
        # codes directly — no join needed.
        return f"{obj.parcel.origin_id} → {obj.parcel.destination_id}"
