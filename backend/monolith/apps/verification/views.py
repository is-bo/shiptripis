"""Handover code endpoints — issue + verify."""

from __future__ import annotations

from rest_framework import generics, status
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.matching.models import Match
from apps.parcels.models import ParcelRequest

from .models import HandoverCode
from .serializers import (
    HandoverCodeIssueRequestSerializer,
    HandoverCodeIssueResponseSerializer,
    HandoverCodeSerializer,
    HandoverCodeVerifyRequestSerializer,
)
from .services import (
    CodeInvalid,
    CodeNotActive,
    get_active_code,
    issue_code,
    verify_code,
)


class V1HandoverUnavailable(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = (
        "V1 Deal handover is not available until the Phase 2 funded handover "
        "state machine is implemented."
    )
    default_code = "v1_deal_handover_not_available"


class ProductHandoverRetired(APIException):
    status_code = status.HTTP_410_GONE
    default_detail = "ProductRequest/Kaba handover is retired in ShipTrip V1."
    default_code = "product_request_retired"


def _get_match_for_party(match_id: int, user) -> Match:
    match = (
        Match.objects.select_related("sender", "traveler", "parcel")
        .filter(id=match_id)
        .first()
    )
    if match is None:
        raise ValidationError({"match": "Not found."})
    if user not in (match.sender, match.traveler):
        raise PermissionDenied("Only the match parties can use this endpoint.")
    if match.parcel.kind == ParcelRequest.Kind.PRODUCT:
        raise ProductHandoverRetired()
    if match.journey_id is not None:
        raise V1HandoverUnavailable()
    return match


class HandoverIssueView(APIView):
    """Sender issues a code.

    PICKUP   — issued by sender (shown to sender; given to traveler verbally)
    DELIVERY — issued by recipient/sender (shown to sender; given to recipient,
               who reads it to the traveler at delivery)
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, match_id: int):
        req = HandoverCodeIssueRequestSerializer(data=request.data)
        req.is_valid(raise_exception=True)
        kind = req.validated_data["kind"]

        match = _get_match_for_party(match_id, request.user)
        if request.user != match.sender:
            raise PermissionDenied("Only the sender can issue handover codes.")

        if kind == HandoverCode.Kind.PICKUP and match.status != Match.Status.ACCEPTED:
            raise ValidationError(
                {"kind": "Pickup codes only available while match is accepted."}
            )
        if kind == HandoverCode.Kind.DELIVERY and match.status != Match.Status.IN_TRANSIT:
            raise ValidationError(
                {"kind": "Delivery codes only available while match is in_transit."}
            )

        issued = issue_code(match=match, kind=kind, issued_to=request.user)
        out = HandoverCodeIssueResponseSerializer(
            {
                "handover_id": issued.handover_id,
                "code": issued.code,
                "kind": kind,
            }
        )
        return Response(out.data, status=status.HTTP_201_CREATED)


class HandoverVerifyView(APIView):
    """Traveler enters the code to advance the match."""

    permission_classes = [IsAuthenticated]

    def post(self, request, match_id: int):
        req = HandoverCodeVerifyRequestSerializer(data=request.data)
        req.is_valid(raise_exception=True)

        match = _get_match_for_party(match_id, request.user)
        if request.user != match.traveler:
            raise PermissionDenied("Only the traveler can verify handover codes.")

        try:
            row = verify_code(
                match=match,
                kind=req.validated_data["kind"],
                submitted_code=req.validated_data["code"],
                used_by=request.user,
            )
        except CodeInvalid as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST
            )
        except CodeNotActive as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_409_CONFLICT
            )
        except ValueError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_409_CONFLICT
            )

        return Response(HandoverCodeSerializer(row).data, status=status.HTTP_200_OK)


class HandoverActiveCodeView(APIView):
    """GET the active code metadata for (match, kind) without rotating.

    The sender's app uses this to know whether to show the "view pickup code"
    button after payment — the actual plaintext was delivered once via the
    `handover.code_issued` WS event and is cached client-side. Returns 404 if
    no active code exists (e.g. pickup already used; traveler picked up).
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, match_id: int):
        match = _get_match_for_party(match_id, request.user)
        kind = request.query_params.get("kind", HandoverCode.Kind.PICKUP)
        if kind not in dict(HandoverCode.Kind.choices):
            raise ValidationError({"kind": f"Unknown kind '{kind}'."})

        # Sender sees the pickup code, traveler sees the delivery code.
        row = get_active_code(match=match, kind=kind, viewer=request.user)
        if row is None:
            return Response({"detail": "No active code."}, status=status.HTTP_404_NOT_FOUND)
        return Response(HandoverCodeSerializer(row).data)


class HandoverListView(generics.ListAPIView):
    """List codes for a match — visible to the match parties."""

    serializer_class = HandoverCodeSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        match_id = self.kwargs["match_id"]
        match = _get_match_for_party(match_id, self.request.user)
        return HandoverCode.objects.filter(match=match)
