"""How a helper call is authenticated, limited, checked and recorded (plan L15).

* **Authentication** reads ``Authorization: Bearer <key>`` and nothing else:
  no query parameter, no cookie, no session. It is installed on the helper's
  views only, and the helper's views accept nothing else, so a helper key
  opens no other route and a session or a member token opens no helper route.
* **Authority** is the admin's own at the moment of the call: the key's admin
  is loaded fresh by `resolve_key`, and each endpoint checks the permission of
  the console page it mirrors with `has_all_admin_permissions`.
* **Rate limit** per key, from the policy (`429 admin_helper_rate_limited`).
* **Every response** is ``Cache-Control: no-store``, and every call made with
  a valid key is recorded in `AdminHelperCall` once the response is built.
"""

from __future__ import annotations

import logging
import math

from django.utils import timezone
from rest_framework import exceptions, status
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.permissions import BasePermission
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle
from rest_framework.views import APIView

from apps.admin_panel.permissions import has_all_admin_permissions

from .calls import record_call
from .keys import KEY_INVALID_CODE, current_policy, resolve_key
from .models import AdminHelperKey
from .policy import admin_helper_policy

logger = logging.getLogger(__name__)

RATE_LIMITED_CODE = "admin_helper_rate_limited"
FORBIDDEN_CODE = "admin_helper_forbidden"
NOT_FOUND_CODE = "admin_helper_not_found"
BAD_REQUEST_CODE = "admin_helper_bad_request"


class HelperKeyInvalid(exceptions.AuthenticationFailed):
    default_code = KEY_INVALID_CODE
    default_detail = {
        "code": KEY_INVALID_CODE,
        "detail": "This key does not work. Create a new one on the AI helper card "
        "of the Wassla console.",
    }


class HelperKeyAuthentication(BaseAuthentication):
    """``Authorization: Bearer wslr_...`` only. Every refusal is the same 401."""

    keyword = b"bearer"

    def authenticate(self, request):
        header = get_authorization_header(request).split()
        if len(header) != 2 or header[0].lower() != self.keyword:
            raise HelperKeyInvalid()
        try:
            plain = header[1].decode("ascii")
        except UnicodeDecodeError:
            raise HelperKeyInvalid() from None
        policy = current_policy()
        key = resolve_key(plain, policy=policy)
        if key is None:
            raise HelperKeyInvalid()
        # Read once per call: the throttle and the guide use the same revision.
        request.helper_policy = policy
        return key.admin, key

    def authenticate_header(self, request):
        return 'Bearer realm="wassla-ai-helper"'


class HelperRateLimited(exceptions.Throttled):
    """``429 admin_helper_rate_limited``, with ``Retry-After`` in seconds."""

    def __init__(self, wait: float):
        exceptions.APIException.__init__(
            self,
            detail={
                "code": RATE_LIMITED_CODE,
                "detail": "Too many requests with this key. Wait one minute.",
            },
            code=RATE_LIMITED_CODE,
        )
        self.wait = math.ceil(wait)


class HelperKeyRequired(BasePermission):
    """Only a request the helper authentication accepted (defence in depth)."""

    def has_permission(self, request, view) -> bool:
        return isinstance(request.auth, AdminHelperKey)


class HelperKeyThrottle(BaseThrottle):
    """At most ``requests_per_minute`` calls per key in each clock minute.

    One counter per key and minute, created with ``add`` and raised with
    ``incr``, both atomic in the shared cache, so concurrent calls cannot slip
    past the limit together.
    """

    def __init__(self):
        self.wait_seconds = 0.0

    def allow_request(self, request, view) -> bool:
        from django.core.cache import cache

        key = request.auth
        if not isinstance(key, AdminHelperKey):
            return True
        policy = getattr(request, "helper_policy", None) or admin_helper_policy()
        now = timezone.now().timestamp()
        minute = int(now // 60)
        counter = f"admin_helper:rate:{key.pk}:{minute}"
        used = None
        for _attempt in range(2):
            cache.add(counter, 0, timeout=120)
            try:
                used = cache.incr(counter)
                break
            except ValueError:  # evicted between add and incr: add again
                continue
        if used is None:
            # The cache keeps losing the counter: refuse rather than not count.
            used = policy.requests_per_minute + 1
        if used > policy.requests_per_minute:
            self.wait_seconds = max(1.0, (minute + 1) * 60 - now)
            return False
        return True

    def wait(self):
        return self.wait_seconds


def refusal(code: str, detail: str, http_status: int) -> Response:
    return Response({"code": code, "detail": detail}, status=http_status)


def forbidden() -> Response:
    return refusal(
        FORBIDDEN_CODE,
        "Your role does not allow this. The console page it mirrors would refuse it too.",
        status.HTTP_403_FORBIDDEN,
    )


def not_found(what: str = "record") -> Response:
    return refusal(NOT_FOUND_CODE, f"No such {what}.", status.HTTP_404_NOT_FOUND)


def bad_request(detail: str) -> Response:
    return refusal(BAD_REQUEST_CODE, detail, status.HTTP_400_BAD_REQUEST)


def permitted(admin, gate: tuple[str, ...]) -> bool:
    """The fresh check (`has_all_admin_permissions`, which reloads the account)
    for any of the codes the mirrored console page accepts, as that page's
    `capability_required` does."""

    return any(has_all_admin_permissions(admin, code) for code in gate)


class HelperView(APIView):
    """The base of every helper endpoint. Read only in L15: GET (and HEAD)."""

    authentication_classes = (HelperKeyAuthentication,)
    permission_classes = (HelperKeyRequired,)
    throttle_classes = (HelperKeyThrottle,)
    #: JSON only, whatever ``Accept`` asks: the browsable page would print the
    #: admin's email in its header.
    renderer_classes = (JSONRenderer,)
    http_method_names = ("get", "head")

    def perform_content_negotiation(self, request, force=False):
        # Never a 406 before the key is checked: every caller gets JSON.
        return super().perform_content_negotiation(request, force=True)

    def throttled(self, request, wait):
        raise HelperRateLimited(wait)

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        response["Pragma"] = "no-cache"
        # The key authentication already accepted, if it ran: reading
        # ``request.auth`` here would run it again outside the error handling.
        key = getattr(request, "_auth", None)
        if isinstance(key, AdminHelperKey):
            record_call(key, method=request.method, path=request.path, status=response.status_code)
        return response

    def handle_exception(self, exc):
        # An authentication refusal never names why (unknown, expired, stopped,
        # switched off, no access): one code, one message.
        if isinstance(exc, exceptions.AuthenticationFailed) and not isinstance(
            exc, HelperKeyInvalid
        ):
            exc = HelperKeyInvalid()
        return super().handle_exception(exc)

