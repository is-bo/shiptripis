from rest_framework import serializers

from .models import ChatMessage, ChatMessageReport


class ChatMessageSerializer(serializers.ModelSerializer):
    """One message. A message staff removed keeps its place in the thread
    with `removed` true and an empty body: what it said never leaves the
    server again (`apps.chat.moderation`)."""

    sender_id = serializers.IntegerField(read_only=True)
    match_id = serializers.IntegerField(read_only=True)
    body = serializers.SerializerMethodField()
    removed = serializers.SerializerMethodField()

    class Meta:
        model = ChatMessage
        fields = (
            "id",
            "match_id",
            "sender_id",
            "body",
            "removed",
            "client_message_id",
            "created_at",
            "read_at",
        )
        read_only_fields = fields

    def get_body(self, obj) -> str:
        return "" if obj.removed_at is not None else obj.body

    def get_removed(self, obj) -> bool:
        return obj.removed_at is not None


class ChatReportSerializer(serializers.Serializer):
    """A member's report on a message they received, and whether to block."""

    reason = serializers.ChoiceField(choices=ChatMessageReport.Reason.choices)
    note = serializers.CharField(
        required=False, allow_blank=True, max_length=500, default=""
    )
    block = serializers.BooleanField(required=False, default=False)


class ChatSendSerializer(serializers.Serializer):
    """Validate an inbound message. `body` is trimmed; empty is rejected."""

    body = serializers.CharField(max_length=2000, trim_whitespace=True)
    client_message_id = serializers.UUIDField(required=False)


class ChatThreadSerializer(serializers.Serializer):
    """One row in the Mailroom inbox: a funded match the viewer can open.

    Read-only projection. The view annotates `last_body` / `last_at` / `unread`
    and passes the viewer via context so we can name the *other* party. There
    is no thread table — a Match is the thread (see ChatMessage docstring).

    A thread stays listed once its Deal is funded, including after the Deal
    closes, because a completed or cancelled delivery is exactly when someone
    needs to re-read what was agreed. `can_send` tells the client whether the
    composer should be live or the thread rendered read-only, so the client
    never has to infer that from a 402.
    """

    match_id = serializers.IntegerField(source="id", read_only=True)
    deal_id = serializers.SerializerMethodField()
    counterparty_id = serializers.SerializerMethodField()
    counterparty_name = serializers.SerializerMethodField()
    route = serializers.SerializerMethodField()
    status = serializers.CharField(read_only=True)
    can_send = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()
    last_message_removed = serializers.SerializerMethodField()
    counterparty_deleted = serializers.SerializerMethodField()
    blocked_by_me = serializers.BooleanField(source="blocked_by_viewer", read_only=True)
    last_message_at = serializers.DateTimeField(source="last_at", read_only=True)
    unread_count = serializers.IntegerField(source="unread", read_only=True)

    def get_deal_id(self, obj):
        deal = getattr(obj, "_prefetched_deal", None)
        return deal.id if deal is not None else None

    def get_can_send(self, obj) -> bool:
        # The view has already resolved this per row through the single
        # `chat_eligibility` helper; recomputing here would double the query
        # count for no benefit.
        return bool(getattr(obj, "_can_send", False))

    def _viewer_id(self) -> int:
        return self.context["viewer_id"]

    def _counterparty(self, obj):
        return obj.traveler if self._viewer_id() == obj.sender_id else obj.sender

    def get_counterparty_id(self, obj) -> int:
        return self._counterparty(obj).id

    def get_counterparty_name(self, obj) -> str:
        return self._counterparty(obj).full_name

    def get_counterparty_deleted(self, obj) -> bool:
        """The other member deleted their account; the app names them so."""

        return self._counterparty(obj).deleted_at is not None

    def get_last_message(self, obj) -> str | None:
        return "" if obj.last_removed else obj.last_body

    def get_last_message_removed(self, obj) -> bool:
        return bool(obj.last_removed)

    def get_route(self, obj) -> str:
        """Coarse route label.

        V1 requests carry city labels and may have no airport at all, so the
        airport codes are a fallback for legacy rows rather than the primary
        source. Deliberately coarse in both cases: the inbox is a list, and a
        street address has no business appearing in one.
        """
        parcel = obj.parcel
        start = parcel.pickup_city or parcel.origin_id or ""
        end = parcel.delivery_city or parcel.destination_id or ""
        if not start and not end:
            return ""
        return f"{start} → {end}"
