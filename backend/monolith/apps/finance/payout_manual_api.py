"""Functional Finance commands, masked projections and no-cache evidence proxy."""

from django.http import HttpResponse
from rest_framework import serializers
from rest_framework.response import Response

from .models import Payout
from .payout_profile_api import ProfileView, StrictInput
from .payout_profiles import require_capabilities
from .payout_evidence import upload_evidence, read_evidence, CHEQUE_LABELS
from .payout_manual_profiles import reveal_profile, review_profile
from . import payout_manual


class UploadInput(StrictInput):
    image = serializers.FileField(write_only=True)


class EvidenceUploadView(ProfileView):
    purpose = "account_document"

    def post(self, request):
        data = UploadInput(data=request.data)
        data.is_valid(raise_exception=True)
        evidence = upload_evidence(
            actor=request.user,
            upload=data.validated_data["image"],
            purpose=self.purpose,
        )
        return Response(
            {"reference": str(evidence.public_reference), "labels": CHEQUE_LABELS},
            status=201,
        )


class ReceiptUploadView(EvidenceUploadView):
    purpose = "transfer_receipt"


class EvidenceReadView(ProfileView):
    def get(self, request, reference):
        body, mime = read_evidence(actor=request.user, reference=reference)
        response = HttpResponse(body, content_type=mime)
        response["Cache-Control"] = "no-store, private"
        response["X-Content-Type-Options"] = "nosniff"
        response["Content-Disposition"] = 'inline; filename="payout-evidence"'
        return response


class RevealView(ProfileView):
    def post(self, request, reference):
        data = StrictInput(data=request.data)
        data.is_valid(raise_exception=True)
        response = Response(reveal_profile(actor=request.user, reference=reference))
        response["Cache-Control"] = "no-store, private"
        return response


class ReviewInput(StrictInput):
    approve = serializers.BooleanField()
    accept_name_difference = serializers.BooleanField(default=False)


class ReviewView(ProfileView):
    def post(self, request, reference):
        data = ReviewInput(data=request.data)
        data.is_valid(raise_exception=True)
        review = review_profile(
            actor=request.user, reference=reference, **data.validated_data
        )
        return Response({"review": review.pk, "status": review.status})


def projection(payout):
    version = payout.active_instruction_version
    profile = version.dzd_profile_revision if version else None
    attempt = payout.attempts.order_by("-sequence").first()
    return {
        "reference": str(payout.public_reference),
        "state_version": payout.state_version,
        "status": payout.status,
        "eur_cents": payout.amount_eur_cents,
        "dzd_amount": payout.payout_amount_minor,
        "fx_rate_micros": payout.fx_rate_micros,
        "instruction_revision": attempt.sequence if attempt else None,
        "operator": attempt.operator_id if attempt else None,
        "committed_at": attempt.committed_at if attempt else None,
        "sent_at": payout.sent_at,
        "paid_at": payout.paid_at,
        "profile": str(profile.public_reference) if profile else None,
        "ccp_last_four": profile.ccp_last_four if profile else None,
        "rip_last_four": profile.rip_last_four if profile else None,
        "proof": str(profile.evidence.public_reference)
        if profile and profile.evidence_id
        else None,
        "holds": list(
            payout_manual.active_holds(payout).values(
                "id", "kind", "reason_code", "generation"
            )
        ),
        "timeline": list(
            payout.events.values(
                "sequence",
                "reason_code",
                "actor_id",
                "recorded_at",
                "evidence__public_reference",
            )
        ),
    }


class PrepareInput(StrictInput):
    expected_state_version = serializers.IntegerField(min_value=0)


class InstructionInput(StrictInput):
    sequence = serializers.IntegerField(min_value=1)


class ConfirmInput(InstructionInput):
    evidence_reference = serializers.UUIDField()
    settled = serializers.BooleanField(default=False)
    confirmed = serializers.BooleanField()


class ManualDetailView(ProfileView):
    def get(self, request, pk):
        require_capabilities(
            request.user,
            "view_payouts",
            "view_payout_sensitive",
            "view_payout_evidence",
        )
        response = Response(
            projection(
                Payout.objects.get(pk=pk, method="manual", payout_currency="DZD")
            )
        )
        response["Cache-Control"] = "no-store, private"
        return response

    def post(self, request, pk, action):
        commands = {
            "prepare": (PrepareInput, payout_manual.prepare),
            "begin": (InstructionInput, payout_manual.begin),
            "release": (InstructionInput, payout_manual.release),
            "confirm": (ConfirmInput, payout_manual.confirm),
        }
        serializer, command = commands[action]
        data = serializer(data=request.data)
        data.is_valid(raise_exception=True)
        result = command(actor=request.user, payout_id=pk, **data.validated_data)
        return Response(projection(result))
