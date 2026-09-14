from django.db.models import Count, Q
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
        ?bucket=active|history|all — unresolved (default), resolved, or both
        ?unread=1   — only rows with read_at IS NULL
        ?channel=X  — filter by channel prefix (e.g. handover.*)
    """

    serializer_class = NotificationSerializer
    permission_classes = (IsAuthenticated,)
    pagination_class = _Pagination

    def get_queryset(self):
        from .resolution import resolved_notifications
        from rest_framework.exceptions import ValidationError
        qs = resolved_notifications(self.request.user)
        bucket = self.request.query_params.get("bucket", "active")
        if bucket not in ("active", "history", "all"):
            raise ValidationError({"bucket": "Use active, history or all."})
        if bucket != "all":
            qs = qs.filter(resolved=bucket == "history")
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
    from .resolution import resolved_notifications
    return Response(NotificationSerializer(resolved_notifications(request.user).get(pk=n.pk)).data)


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
    from .resolution import resolved_notifications
    active = resolved_notifications(request.user).filter(resolved=False)
    counts = active.aggregate(active=Count("pk"), unread_active=Count("pk", filter=Q(read_at__isnull=True)))
    # Keep the historical badge key for installed clients, with J1 semantics.
    return Response({"unread": counts["active"], **counts})


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
