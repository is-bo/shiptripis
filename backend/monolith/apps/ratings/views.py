"""HTTP API for Deal ratings.

    POST /api/deals/<id>/ratings     rate the counterparty, once
    GET  /api/deals/<id>/ratings     this Deal's rating state for the caller
    GET  /api/users/me/ratings       the revealed ratings I have received

Authorization is object-level and derived from the Deal. A party may read the
state and submit exactly one rating; staff may read everything; anyone else --
including the guest who paid the order and the parcel's recipient -- is refused
by `apps.ratings.services`, which reads the roles off the locked Deal row rather
than off the request.

Deal existence is not hidden here, unlike the handover routes: refusing a
non-party with 403 is what the specification asks for, and a rating endpoint
tells an attacker nothing a Deal id alone does not.
"""

from __future__ import annotations

import logging

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status as http
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.business_settings import NoActiveBusinessSettings
from apps.core.phase4_policy import InvalidPhase4Policy
from apps.deals.lifecycle import DealLifecycleError
from apps.deals.models import Deal

from .serializers import RatingSerializer, RatingSubmitSerializer
from .services import (
    NotAuthorized,
    RatingError,
    is_revealed,
    rating_state,
    received_ratings,
    submit_rating,
)

logger = logging.getLogger(__name__)

#: The failures this API knows how to speak about. Anything else is a bug and
#: must reach DRF's own handler rather than being reshaped into a rating error --
#: a blanket `except Exception` here would quietly turn a database failure into
#: a 500 that looks like a domain refusal.
MAPPED_FAILURES = (
    RatingError,
    DealLifecycleError,
    NoActiveBusinessSettings,
    InvalidPhase4Policy,
)


def _error_response(exc: Exception) -> Response:
    """Map a domain failure to its machine code and structured detail.

    Every branch is explicit, and an unrecognised exception becomes a generic
    `internal_error` with its message suppressed rather than echoed.
    """

    if isinstance(exc, NotAuthorized):
        status_code = http.HTTP_403_FORBIDDEN
    elif isinstance(exc, (RatingError, DealLifecycleError)):
        status_code = http.HTTP_409_CONFLICT
    elif isinstance(exc, (NoActiveBusinessSettings, InvalidPhase4Policy)):
        status_code = http.HTTP_503_SERVICE_UNAVAILABLE
    else:
        logger.error("Unmapped rating failure", exc_info=True)
        return Response(
            {
                "code": "internal_error",
                "detail": "The request could not be completed.",
            },
            status=http.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    payload = {"code": getattr(exc, "code", "rating_error"), "detail": str(exc)}
    details = getattr(exc, "details", None)
    if callable(details):
        payload.update(details())
    return Response(payload, status=status_code)


class DealRatingsView(APIView):
    """Read one Deal's rating state, or add the caller's own rating to it.

    Both verbs share a path, so they share a view: `ratings-list` and
    `ratings-submit` are two names for `deals/<id>/ratings`, and Django routes
    by path before it routes by method.
    """

    permission_classes = (IsAuthenticated,)

    def post(self, request: Request, pk: int) -> Response:
        """Submit the caller's rating of their counterparty, once.

        The body carries a score, tags and a comment. It cannot carry a role, a
        rater or a ratee: those are derived from the Deal inside the service,
        under the same lifecycle lock every other Phase 4 writer takes.
        """

        get_object_or_404(Deal, pk=pk)
        serializer = RatingSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            rating = submit_rating(
                deal_id=pk,
                actor_id=request.user.id,
                score=data["score"],
                tags=data.get("tags") or [],
                comment=data.get("comment", ""),
            )
        except MAPPED_FAILURES as exc:
            return _error_response(exc)
        return Response(
            RatingSerializer(rating).data, status=http.HTTP_201_CREATED
        )

    def get(self, request: Request, pk: int) -> Response:
        """This Deal's rating state, projected for the caller.

        Says whether the caller may still rate, when the review window closes,
        and which ratings the blind predicate lets them see -- their own always,
        the counterparty's only once both sides have spoken or the window has
        passed.
        """

        deal = get_object_or_404(Deal.objects.prefetch_related("ratings"), pk=pk)
        is_staff = bool(request.user.is_staff)
        if request.user.id not in (deal.sender_id, deal.traveler_id) and not is_staff:
            return _error_response(
                NotAuthorized("Only a party to this delivery may see its ratings.")
            )
        try:
            state = rating_state(
                deal=deal, viewer_id=request.user.id, is_staff=is_staff
            )
        except MAPPED_FAILURES as exc:
            return _error_response(exc)
        return Response(state)


class MyRatingsView(APIView):
    """Every rating the caller has received that is no longer blind.

    The queryset narrows with the predicate expressed in SQL; the predicate
    itself then filters what is actually returned. Both say the same thing, and
    the second one is the authority -- a rating is never listed because a
    `revealed_at` stamp exists, only because the rule says it is visible.
    """

    permission_classes = (IsAuthenticated,)

    def get(self, request: Request) -> Response:
        at = timezone.now()
        rows = [
            row
            for row in received_ratings(user_id=request.user.id, at=at)
            if is_revealed(row, deal=row.deal, at=at)
        ]
        return Response(
            RatingSerializer(rows, many=True, context={"at": at}).data
        )
