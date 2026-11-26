from django.conf import settings
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.generics import ListAPIView
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .models import Notification, NotificationPreference
from .push import (
    PushBindingSuperseded,
    PushSessionRevoked,
    register_push_device,
    unregister_push_device,
)
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
        return qs.order_by("-created_at", "-id")


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


def _claim(request: Request, name: str, default):
    """A claim of the access token that authenticated ``request``.

    The sign-in id (``sid``) and issue time (``iat``) tie a push registration to
    the sign-in that made it. A request authenticated without a token (a test
    client) carries neither.
    """

    token = request.auth
    return default if token is None else token.get(name, default)


class PushDeviceRegistrationView(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> Response:
        serializer = PushDeviceRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            device = register_push_device(
                user=request.user,
                session_id=_claim(request, "sid", ""),
                token_issued_at=_claim(request, "iat", None),
                **serializer.validated_data,
            )
        except PushSessionRevoked:
            return Response(
                {
                    "code": "push_session_revoked",
                    "detail": "Every sign-in of this account was ended after this one began.",
                },
                status=status.HTTP_409_CONFLICT,
            )
        except PushBindingSuperseded as superseded:
            return Response(
                {
                    "code": "push_registration_superseded",
                    "detail": "A newer registration or sign-out of this phone was already applied.",
                    "current_sequence": superseded.current_sequence,
                },
                status=status.HTTP_409_CONFLICT,
            )
        return Response(PushDeviceSerializer(device).data, status=status.HTTP_200_OK)


class PushDeviceUnregisterView(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> Response:
        serializer = PushDeviceUnregisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        unregister_push_device(
            user=request.user,
            session_id=_claim(request, "sid", ""),
            **serializer.validated_data,
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


class SupportContactView(APIView):
    """`GET /api/support`: where a member writes for help (L18A).

    `{"email": <EMAIL_SUPPORT_ADDR>}`, the same server setting the emails print
    in their footer. The settings resolve a blank `EMAIL_SUPPORT_ADDR` to
    contact@wassla.eu (`config/settings/base.py`), so the answer always names
    an address, never `null`. Open to anyone and reading no credentials, so a
    stale token cannot break it.
    """

    authentication_classes = ()
    permission_classes = (AllowAny,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "support_contact"

    def get(self, request: Request) -> Response:
        return Response({"email": settings.EMAIL_SUPPORT_ADDR})
