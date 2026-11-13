"""`GET` and `POST /api/deals/<id>/problems` (spec 12, plan L9A)."""

from __future__ import annotations

from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import status as http
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.deals.models import Deal

from .services import ProblemError, problem_row, problems_view, report_problem


class DealProblemsView(APIView):
    """A delivery's problem reports, and reporting a new one.

    Both parties read every report on their delivery. Only a party can report,
    and the no-show kinds only by the person left waiting, inside the window
    the read describes.
    """

    permission_classes = (IsAuthenticated,)

    def _deal(self, request: Request, pk: int) -> Deal:
        return get_object_or_404(
            Deal.objects.select_related("delivery_request").filter(
                Q(sender_id=request.user.pk) | Q(traveler_id=request.user.pk)
            ),
            pk=pk,
        )

    def get(self, request: Request, pk: int) -> Response:
        return Response(problems_view(self._deal(request, pk), viewer=request.user))

    def post(self, request: Request, pk: int) -> Response:
        self._deal(request, pk)
        kind = request.data.get("kind")
        note = request.data.get("note", "")
        if not isinstance(kind, str) or not isinstance(note, str):
            return Response(
                {"code": "invalid_request", "detail": "kind and note must be text."},
                status=http.HTTP_400_BAD_REQUEST,
            )
        try:
            result = report_problem(
                deal_id=pk, actor=request.user, kind=kind, note=note
            )
        except ProblemError as exc:
            return Response(exc.as_payload(), status=exc.http_status)
        return Response(
            {
                "problem": problem_row(result.problem, viewer_id=request.user.pk),
                "created": result.created,
            },
            status=http.HTTP_201_CREATED if result.created else http.HTTP_200_OK,
        )
