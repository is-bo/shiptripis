from django.db.models import Q
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.generics import ListAPIView
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Notification, NotificationPreference
from .push import register_push_device, unregister_push_device
from .serializers import (
    NotificationPreferenceSerializer,
    NotificationSerializer,
    PushDeviceRegistrationSerializer,
    PushDeviceSerializer,
    PushDeviceUnregisterSerializer,
)


class _Pagination(PageNumberPagination):
    page_size = 30
    page_size_query_param = "page_size"
    max_page_size = 100


class NotificationListView(ListAPIView):
    """GET /api/notifications — paginated, newest first.

    Optional query params:
        ?unread=1   — only rows with read_at IS NULL
        ?channel=X  — filter by channel prefix (e.g. handover.*)
    """

    serializer_class = NotificationSerializer
    permission_classes = (IsAuthenticated,)
    pagination_class = _Pagination

    def get_queryset(self):
        qs = Notification.objects.filter(recipient=self.request.user)
        if self.request.query_params.get("unread") in ("1", "true", "yes"):
            qs = qs.filter(read_at__isnull=True)
        ch = self.request.query_params.get("channel")
        if ch:
            qs = qs.filter(Q(channel=ch) | Q(channel__startswith=f"{ch}."))
        return qs.order_by("-created_at")


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def mark_read(request: Request, pk: int) -> Response:
    """POST /api/notifications/<id>/read — idempotent."""
    try:
        n = Notification.objects.get(pk=pk, recipient=request.user)
    except Notification.DoesNotExist:
        return Response(status=status.HTTP_404_NOT_FOUND)
    if n.read_at is None:
        n.read_at = timezone.now()
        n.save(update_fields=("read_at",))
    return Response(NotificationSerializer(n).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def mark_all_read(request: Request) -> Response:
    """POST /api/notifications/read-all — flips every unread row for the user."""
    Notification.objects.filter(
        recipient=request.user, read_at__isnull=True
    ).update(read_at=timezone.now())
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def unread_count(request: Request) -> Response:
    """GET /api/notifications/unread-count — for badge rendering."""
    n = Notification.objects.filter(
        recipient=request.user, read_at__isnull=True
    ).count()
    return Response({"unread": n})


class PushDeviceRegistrationView(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> Response:
        serializer = PushDeviceRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        device = register_push_device(user=request.user, **serializer.validated_data)
        return Response(PushDeviceSerializer(device).data, status=status.HTTP_200_OK)


class PushDeviceUnregisterView(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> Response:
        serializer = PushDeviceUnregisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        unregister_push_device(
            user=request.user,
            installation_id=serializer.validated_data["installation_id"],
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class NotificationPreferenceView(APIView):
    permission_classes = (IsAuthenticated,)

    def _preference(self, request: Request) -> NotificationPreference:
        preference, _ = NotificationPreference.objects.get_or_create(user=request.user)
        return preference

    def get(self, request: Request) -> Response:
        return Response(
            NotificationPreferenceSerializer(self._preference(request)).data
        )

    def patch(self, request: Request) -> Response:
        preference = self._preference(request)
        serializer = NotificationPreferenceSerializer(
            preference,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
