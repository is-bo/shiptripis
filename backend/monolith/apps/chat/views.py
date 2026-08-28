"""Chat write + history endpoints (payment-gated 1:1 on a Match).

Django owns persistence. On send we:
  1. gate on `matching.services.chat_eligibility` (payment-gated — the same
     rule the pre-flight `chat-eligibility` endpoint returns);
  2. persist a `ChatMessage`;
  3. publish `chat.message.new` after commit with `targets=[other_member]`.

The Go chat-service subscribes to `chat.message.new` and fans the raw payload
to the recipient's live WebSocket. It never writes `chat_message` itself.
"""

from __future__ import annotations

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status as http
from rest_framework.generics import ListAPIView
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from django.db.models import Count, OuterRef, Q, Subquery

from apps.core import channels, redis_bus
from apps.matching.models import Match
from apps.matching.services import (
    REASON_NOT_A_PARTY,
    REASON_OK,
    chat_eligibility,
    chat_history_visible,
    is_party,
)

from .models import ChatMessage
from .serializers import (
    ChatMessageSerializer,
    ChatSendSerializer,
    ChatThreadSerializer,
)


class _Pagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200


class ChatMessagesView(ListAPIView, APIView):
    """GET  /api/matches/<id>/chat/messages — thread history, oldest first.
    POST /api/matches/<id>/chat/messages — send a message.
    """

    serializer_class = ChatMessageSerializer
    permission_classes = (IsAuthenticated,)
    pagination_class = _Pagination

    def get_queryset(self):
        match = get_object_or_404(
            Match.objects.select_related("parcel").only(
                "id",
                "sender_id",
                "traveler_id",
                "status",
                "journey_id",
                "parcel__kind",
            ),
            pk=self.kwargs["pk"],
        )
        if not is_party(match, self.request.user.id):
            # DRF turns this into a 403; parties only.
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("Not a party to this match.")

        # Reading is broader than sending: a closed or disputed delivery is
        # exactly when a party needs to re-read what was agreed. Sending stays
        # gated by `chat_eligibility` in `post`.
        visible, reason = chat_history_visible(match, self.request.user.id)
        if not visible:
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied(reason)
        return (
            ChatMessage.objects.filter(match_id=match.id)
            .select_related("sender")
            .order_by("created_at")
        )

    def list(self, request, *args, **kwargs):
        # Opening the thread marks the counterparty's messages as read, so the
        # Mailroom unread badge clears. Only the OTHER party's messages — a
        # user never "reads" their own. Idempotent; touches nothing already read.
        response = super().list(request, *args, **kwargs)
        ChatMessage.objects.filter(
            match_id=self.kwargs["pk"], read_at__isnull=True
        ).exclude(sender_id=request.user.id).update(read_at=timezone.now())
        return response

    def post(self, request: Request, pk: int) -> Response:
        match = get_object_or_404(
            Match.objects.select_related("parcel").only(
                "id",
                "sender_id",
                "traveler_id",
                "status",
                "journey_id",
                "parcel__kind",
            ),
            pk=pk,
        )
        eligible, reason = chat_eligibility(match, request.user.id)
        if not eligible:
            # not_a_party is an authorization failure (403); every other reason
            # is "the deal isn't ready for chat yet" (402 payment-required, with
            # the stable reason code so the client can render the right copy).
            code = (
                http.HTTP_403_FORBIDDEN
                if reason == REASON_NOT_A_PARTY
                else http.HTTP_402_PAYMENT_REQUIRED
            )
            return Response({"reason": reason, "match_id": match.id}, status=code)

        s = ChatSendSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        other_id = (
            match.traveler_id
            if request.user.id == match.sender_id
            else match.sender_id
        )

        with transaction.atomic():
            msg = ChatMessage.objects.create(
                match=match,
                sender=request.user,
                body=s.validated_data["body"],
            )
            redis_bus.publish_after_commit(
                channels.CHAT_MESSAGE_NEW,
                {
                    "message_id": msg.id,
                    "match_id": match.id,
                    "sender_id": request.user.id,
                    "body": msg.body,
                    "created_at": msg.created_at.isoformat(),
                },
                targets=[other_id],
            )

        return Response(
            ChatMessageSerializer(msg).data, status=http.HTTP_201_CREATED
        )


class ChatThreadsView(APIView):
    """GET /api/chat/threads — the viewer's Mailroom inbox.

    Returns every match the viewer may currently chat on (i.e. `chat_eligibility`
    is OK — accepted + paid, not closed), newest activity first, with the
    counterparty name, route, last-message snippet, and the viewer's unread
    count. Eligibility is checked per-row through the same `chat_eligibility`
    helper the send path uses, so the inbox never lists a thread the user can't
    actually open.
    """

    permission_classes = (IsAuthenticated,)

    def get(self, request: Request) -> Response:
        uid = request.user.id

        last_msg = ChatMessage.objects.filter(match_id=OuterRef("pk")).order_by(
            "-created_at"
        )
        matches = (
            Match.objects.filter(Q(sender_id=uid) | Q(traveler_id=uid))
            # `deal` is the V1 chat gate, so it is joined rather than looked up
            # per row — without it every inbox render costs one extra query per
            # match.
            .select_related("sender", "traveler", "parcel", "deal")
            .annotate(
                last_body=Subquery(last_msg.values("body")[:1]),
                last_at=Subquery(last_msg.values("created_at")[:1]),
                unread=Count(
                    "chat_messages",
                    filter=Q(chat_messages__read_at__isnull=True)
                    & ~Q(chat_messages__sender_id=uid),
                ),
            )
        )

        # Gate each candidate through the single source of truth. A thread is
        # listed when its history is visible — which outlives the Deal — and
        # carries `can_send` so the client knows whether to render a live
        # composer or a read-only thread.
        eligible = []
        for m in matches:
            if chat_history_visible(m, uid)[0] is not True:
                continue
            m._can_send = chat_eligibility(m, uid)[1] == REASON_OK
            m._prefetched_deal = getattr(m, "deal", None)
            eligible.append(m)
        # Most recent conversation first; matches with no messages yet sort by
        # match recency (last_at is null → fall back to created_at).
        eligible.sort(
            key=lambda m: m.last_at or m.created_at, reverse=True
        )

        data = ChatThreadSerializer(
            eligible, many=True, context={"viewer_id": uid}
        ).data
        return Response({"results": data})
