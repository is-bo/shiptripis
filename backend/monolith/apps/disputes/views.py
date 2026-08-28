"""HTTP API for V1 disputes.

    POST /api/deals/<id>/disputes                     open a dispute
    GET  /api/deals/<id>/disputes                     disputes on one delivery
    GET  /api/disputes/<id>                           one dispute (party or staff)
    POST /api/disputes/<id>/evidence                  add text, a photo or a video
    GET  /api/disputes/<id>/evidence/<id>/url         signed download, 5 minutes
    GET  /api/admin/disputes                          the review queue
    POST /api/admin/disputes/<id>/status              move between review states
    POST /api/admin/disputes/<id>/resolve             decide it and settle the money
    POST /api/admin/deals/<id>/no-show                record a reviewed no-show

Object-level authorization is Deal membership: a caller who is not a party to
the Deal receives a 404 rather than a 403, so dispute and Deal ids cannot be
probed for existence. The four operations surfaces are gated on named Django
permissions rather than on `is_staff`, because reading a party's evidence and
moving their money are different capabilities and are granted separately.

Nothing here decides anything. Every rule -- who may open a dispute and when,
what an evidence file must actually be, which split reconciles -- lives in
`apps.disputes.services`, and this layer maps its refusals onto status codes.
"""

from __future__ import annotations

import logging

from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import status as http
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.core.business_settings import NoActiveBusinessSettings
from apps.core.permissions import (
    CanRecordNoShow,
    CanResolveDisputes,
    CanViewDisputes,
)
from apps.core.phase4_policy import InvalidPhase4Policy
from apps.deals.cancellation import CancellationError, record_no_show
from apps.deals.lifecycle import DealLifecycleError
from apps.deals.models import Deal
from apps.finance.settlement import SettlementError

from .models import Dispute, DisputeEvidence
from .serializers import (
    AdminDisputeSerializer,
    DisputeEvidenceCreateSerializer,
    DisputeEvidenceSerializer,
    DisputeOpenSerializer,
    DisputeResolveSerializer,
    DisputeSerializer,
    DisputeStatusSerializer,
    NoShowSerializer,
)
from .services import (
    DisputeError,
    NotAuthorized,
    add_evidence,
    evidence_download_url,
    open_dispute,
    resolve_dispute,
    set_dispute_status,
    visible_disputes_for,
)

logger = logging.getLogger(__name__)

#: The failures this API knows how to speak about. Anything else is a bug and
#: must reach DRF's own handler rather than being reshaped into a dispute
#: error -- a blanket `except Exception` here would quietly turn a serializer
#: failure or a database error into a 500 that looks like a domain refusal.
MAPPED_FAILURES = (
    DisputeError,
    SettlementError,
    CancellationError,
    DealLifecycleError,
    NoActiveBusinessSettings,
    InvalidPhase4Policy,
)


def _dispute_error_response(exc: Exception) -> Response:
    """Map a domain failure to its machine code and structured detail.

    Every branch is explicit, and an unrecognised exception becomes a generic
    `internal_error` with its message suppressed rather than echoed.
    """

    if isinstance(exc, NotAuthorized):
        status_code = http.HTTP_403_FORBIDDEN
    elif isinstance(exc, DisputeError):
        status_code = http.HTTP_409_CONFLICT
    elif isinstance(exc, (SettlementError, CancellationError, DealLifecycleError)):
        status_code = http.HTTP_409_CONFLICT
    elif isinstance(exc, (NoActiveBusinessSettings, InvalidPhase4Policy)):
        status_code = http.HTTP_503_SERVICE_UNAVAILABLE
    else:
        logger.error("Unmapped dispute failure", exc_info=True)
        return Response(
            {
                "code": "internal_error",
                "detail": "The request could not be completed.",
            },
            status=http.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    payload = {"code": getattr(exc, "code", "dispute_error"), "detail": str(exc)}
    details = getattr(exc, "details", None)
    if callable(details):
        payload.update(details())
    return Response(payload, status=status_code)


def _party_deal(user_id: int, pk: int) -> Deal:
    """The Deal, if this caller is a party to it. A stranger gets a 404."""

    return get_object_or_404(
        Deal.objects.filter(Q(sender_id=user_id) | Q(traveler_id=user_id)),
        pk=pk,
    )


def _all_disputes():
    """Every dispute, for a caller whose authority is not Deal membership."""

    return Dispute.objects.select_related("deal").prefetch_related(
        "evidence", "events"
    )


def _may_view_disputes(user) -> bool:
    """Staff capability to read the dispute queue at all."""

    if getattr(user, "is_superuser", False):
        return True
    return bool(
        getattr(user, "is_staff", False) and user.has_perm("disputes.view_dispute")
    )


def _may_view_evidence(user) -> bool:
    """Staff capability to read a party's evidence files.

    Deliberately separate from `_may_view_disputes`: seeing that a dispute
    exists and opening the photographs somebody filed inside it are different
    jobs, and the permission model says so.
    """

    if getattr(user, "is_superuser", False):
        return True
    return bool(
        getattr(user, "is_staff", False)
        and user.has_perm("disputes.view_dispute_evidence")
    )


# --- party surface -----------------------------------------------------------


class DealDisputesView(APIView):
    """Open a dispute on a delivery, or list the ones already on it.

    Both verbs live on one view because they are one resource. A party may hold
    only one active dispute per Deal -- the database says so -- and opening a
    second time returns the first, so a client that retries a timed-out request
    gets its dispute rather than a conflict.
    """

    permission_classes = (IsAuthenticated,)

    def get(self, request: Request, pk: int) -> Response:
        _party_deal(request.user.id, pk)
        disputes = visible_disputes_for(request.user.id).filter(deal_id=pk)
        return Response(
            DisputeSerializer(
                disputes, many=True, context={"is_staff": False}
            ).data
        )

    def post(self, request: Request, pk: int) -> Response:
        _party_deal(request.user.id, pk)
        serializer = DisputeOpenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            dispute = open_dispute(
                deal_id=pk,
                actor_id=request.user.id,
                category=serializer.validated_data["category"],
                reason_text=serializer.validated_data["reason_text"],
            )
        except MAPPED_FAILURES as exc:
            return _dispute_error_response(exc)
        return Response(
            DisputeSerializer(
                visible_disputes_for(request.user.id).get(pk=dispute.pk),
                context={"is_staff": False},
            ).data,
            status=http.HTTP_201_CREATED,
        )


class DisputeDetailView(APIView):
    """One dispute, projected for whoever is asking.

    A party sees their dispute. A staff user holding `disputes.view_dispute`
    sees the captured evidence bundle as well. Anybody else is told the dispute
    does not exist.
    """

    permission_classes = (IsAuthenticated,)

    def get(self, request: Request, pk: int) -> Response:
        is_staff = _may_view_disputes(request.user)
        queryset = (
            _all_disputes() if is_staff else visible_disputes_for(request.user.id)
        )
        dispute = get_object_or_404(queryset, pk=pk)
        serializer_class = AdminDisputeSerializer if is_staff else DisputeSerializer
        return Response(
            serializer_class(dispute, context={"is_staff": is_staff}).data
        )


class DisputeEvidenceView(APIView):
    """Add one piece of evidence to a live dispute.

    Multipart, because photos and video are the point. The upload is checked
    against the administrator's policy and against its own leading bytes before
    it reaches the private bucket, and the response never names where it landed.
    """

    permission_classes = (IsAuthenticated,)
    parser_classes = (MultiPartParser, FormParser)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "dispute_evidence"

    def post(self, request: Request, pk: int) -> Response:
        serializer = DisputeEvidenceCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            evidence = add_evidence(
                dispute_id=pk,
                actor_id=request.user.id,
                kind=data["kind"],
                text=data.get("text", ""),
                upload=data.get("file"),
                is_staff=_may_view_evidence(request.user),
            )
        except Dispute.DoesNotExist:
            return Response(
                {"code": "dispute_not_found", "detail": "No such dispute."},
                status=http.HTTP_404_NOT_FOUND,
            )
        except MAPPED_FAILURES as exc:
            return _dispute_error_response(exc)
        return Response(
            DisputeEvidenceSerializer(evidence).data, status=http.HTTP_201_CREATED
        )


class DisputeEvidenceUrlView(APIView):
    """Issue a short-lived signed URL for one evidence file.

    The bucket is private and its keys are never serialized, so this is the only
    route to the bytes. The URL expires in minutes: long enough to open the
    file, short enough that a link forwarded to somebody else is already dead.
    """

    permission_classes = (IsAuthenticated,)

    def get(self, request: Request, pk: int, evidence_id: int) -> Response:
        evidence = get_object_or_404(
            DisputeEvidence.objects.all(), pk=evidence_id, dispute_id=pk
        )
        try:
            url = evidence_download_url(
                evidence_id=evidence.pk,
                actor_id=request.user.id,
                is_staff=_may_view_evidence(request.user),
            )
        except MAPPED_FAILURES as exc:
            return _dispute_error_response(exc)
        return Response(
            {
                "url": url,
                "kind": evidence.kind,
                "content_type": evidence.content_type,
            }
        )


# --- operations surface ------------------------------------------------------


class AdminDisputeListView(APIView):
    """The review queue, newest first, optionally narrowed to one status."""

    permission_classes = (CanViewDisputes,)

    def get(self, request: Request) -> Response:
        queryset = _all_disputes()
        if dispute_status := request.query_params.get("status"):
            queryset = queryset.filter(status=dispute_status)
        return Response(
            AdminDisputeSerializer(
                queryset[:100], many=True, context={"is_staff": True}
            ).data
        )


class AdminDisputeStatusView(APIView):
    """Move a live dispute between open, awaiting evidence and under review."""

    permission_classes = (CanViewDisputes,)

    def post(self, request: Request, pk: int) -> Response:
        serializer = DisputeStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            dispute = set_dispute_status(
                dispute_id=pk,
                status=serializer.validated_data["status"],
                admin_actor_id=request.user.id,
                note=serializer.validated_data.get("note", ""),
            )
        except Dispute.DoesNotExist:
            return Response(
                {"code": "dispute_not_found", "detail": "No such dispute."},
                status=http.HTTP_404_NOT_FOUND,
            )
        except MAPPED_FAILURES as exc:
            return _dispute_error_response(exc)
        return Response(
            AdminDisputeSerializer(
                _all_disputes().get(pk=dispute.pk), context={"is_staff": True}
            ).data
        )


class AdminDisputeResolveView(APIView):
    """Decide a dispute and settle its money.

    A separate permission from viewing the queue: reading a dispute and moving
    a sender's money back out of the platform are not the same authority.
    """

    permission_classes = (CanResolveDisputes,)

    def post(self, request: Request, pk: int) -> Response:
        serializer = DisputeResolveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            dispute = resolve_dispute(
                dispute_id=pk,
                admin_actor_id=request.user.id,
                resolution=data["resolution"],
                sender_refund_eur_cents=data.get("sender_refund_eur_cents"),
                traveler_payout_eur_cents=data.get("traveler_payout_eur_cents"),
                note=data.get("note", ""),
            )
        except Dispute.DoesNotExist:
            return Response(
                {"code": "dispute_not_found", "detail": "No such dispute."},
                status=http.HTTP_404_NOT_FOUND,
            )
        except MAPPED_FAILURES as exc:
            return _dispute_error_response(exc)
        return Response(
            AdminDisputeSerializer(
                _all_disputes().get(pk=dispute.pk), context={"is_staff": True}
            ).data
        )


class AdminDealNoShowView(APIView):
    """Record an admin-reviewed no-show, and settle it when it is the traveler's.

    Manual on purpose at launch: no heuristic decides who failed to appear. What
    the platform owns is the record -- who decided, when, about whom -- and the
    one financial consequence the specification names.
    """

    permission_classes = (CanRecordNoShow,)

    def post(self, request: Request, pk: int) -> Response:
        serializer = NoShowSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        get_object_or_404(Deal.objects.all(), pk=pk)
        try:
            result = record_no_show(
                deal_id=pk,
                party=data["party"],
                admin_actor_id=request.user.id,
                note=data.get("note", ""),
                refund_sender=data.get("refund_sender"),
            )
        except MAPPED_FAILURES as exc:
            return _dispute_error_response(exc)
        return Response(result)
