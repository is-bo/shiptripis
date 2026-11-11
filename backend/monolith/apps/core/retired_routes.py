"""Tombstones for retired API routes.

Each path below once served a pre-V1 contract: traveler-first matching, the
DZD price quote, the airport-based delivery form, or the retired
ProductRequest/Kaba flow. Their implementations are gone. The paths keep
answering ``410 Gone`` with a stable machine code, so a stale client receives
an explicit refusal rather than a 404 that reads like a typo, and nothing new
can be mounted on them by accident.

Mounted by ``config/urls.py``. Add a path here only when a route is retired;
never route live behaviour through this module.
"""

from __future__ import annotations

from django.urls import path
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView


class RetiredRouteView(APIView):
    """Answer the retired method with 410 and the route's own refusal code."""

    permission_classes = (IsAuthenticated,)
    code = ""
    detail = ""

    def _gone(self, request: Request, *args, **kwargs) -> Response:
        del request, args, kwargs
        return Response(
            {"code": self.code, "detail": self.detail},
            status=status.HTTP_410_GONE,
        )

    get = post = _gone


def _retired(route: str, *, method: str, code: str, detail: str, name: str):
    view = RetiredRouteView.as_view(
        code=code,
        detail=detail,
        http_method_names=[method, "options"],
    )
    return path(route, view, name=name)


_LEGACY_MATCHING = dict(
    method="post",
    code="legacy_matching_flow_retired",
    detail=(
        "Legacy traveler-first and DZD matching writes are retired. "
        "Use the Wassla V1 sender proposal endpoint."
    ),
)

urlpatterns = [
    _retired("matches/apply", name="matches-apply", **_LEGACY_MATCHING),
    _retired("matches/apply-to-trip", name="matches-apply-to-trip", **_LEGACY_MATCHING),
    _retired(
        "matches/<int:pk>/offers/counter",
        name="matches-offers-counter",
        **_LEGACY_MATCHING,
    ),
    _retired(
        "parcels/delivery",
        name="parcels-delivery-create",
        method="post",
        code="legacy_delivery_flow_retired",
        detail=(
            "Use POST /api/parcels/delivery/v1 with canonical Place IDs "
            "and EUR cents. Preferred Location IDs are optional."
        ),
    ),
    _retired(
        "parcels/quote/delivery",
        name="parcels-quote-delivery",
        method="get",
        code="legacy_dzd_quote_retired",
        detail="DZD pricing is not a Wassla V1 marketplace contract.",
    ),
    _retired(
        "parcels/product",
        name="parcels-product-create",
        method="post",
        code="product_request_retired",
        detail="ProductRequest creation is retired in Wassla V1.",
    ),
]
