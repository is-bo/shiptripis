"""Flagged, owner-scoped profile API. Sensitive fields are write-only."""

from django.conf import settings
from django.core.exceptions import ValidationError as DomainError, PermissionDenied
from django.core.exceptions import ObjectDoesNotExist
from django.http import Http404
from django.utils.decorators import method_decorator
from django.views.decorators.debug import sensitive_post_parameters
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from .models import TravelerPayoutMethod, PayoutIdentityReviewAssignment
from .payout_accounts import (
    CountryUnsupported,
    allowed_countries,
    stripe_setup_projection,
)
from .payout_profiles import (
    set_preference,
    submit_dzd_profile,
    attest_identity,
    require_capabilities,
)


class ProfileThrottle(UserRateThrottle):
    rate = "20/min"
    scope = "payout_profiles"


class StrictInput(serializers.Serializer):
    def to_internal_value(self, data):
        if not isinstance(data, dict) or set(data) - set(self.fields):
            raise serializers.ValidationError(
                {"non_field_errors": ["Unexpected payout profile fields."]}
            )
        return super().to_internal_value(data)


class PreferenceInput(StrictInput):
    currency = serializers.ChoiceField(choices=["EUR", "DZD"])
    enabled = serializers.BooleanField()
    expected_revision = serializers.IntegerField(min_value=0)
    country = serializers.CharField(
        max_length=2, required=False, default="", allow_blank=True
    )
    consent_policy = serializers.CharField(max_length=64)


class DzdInput(StrictInput):
    expected_revision = serializers.IntegerField(min_value=0)
    first_name = serializers.CharField(max_length=160, write_only=True)
    last_name = serializers.CharField(max_length=160, write_only=True)
    ccp_number = serializers.CharField(max_length=100, write_only=True)
    ccp_key = serializers.CharField(max_length=100, write_only=True)
    rip = serializers.CharField(max_length=100, write_only=True)
    proof_reference = serializers.UUIDField(write_only=True)
    consent_policy = serializers.CharField(max_length=64)


class AttestationInput(StrictInput):
    given_name = serializers.CharField(max_length=160, write_only=True)
    family_name = serializers.CharField(max_length=160, write_only=True)
    aliases = serializers.ListField(
        child=serializers.ListField(
            child=serializers.CharField(max_length=160), min_length=2, max_length=2
        ),
        max_length=10,
        required=False,
        write_only=True,
    )


def method_projection(method):
    version = method.current_version
    profile = version.dzd_profile_revision if version else None
    return {
        "reference": str(method.public_reference),
        "currency": method.currency,
        "enabled": method.enabled,
        "status": method.status if method.enabled else "disabled",
        "revision": method.revision,
        "version": str(version.public_reference) if version else None,
        "profile": {
            "reference": str(profile.public_reference),
            "status": (
                profile.reviews.order_by("-pk").values_list("status", flat=True).first()
                or profile.status
            ),
            "ccp_last_four": profile.ccp_last_four,
            "rip_last_four": profile.rip_last_four,
            "submitted_at": profile.submitted_at,
        }
        if profile
        else None,
        # H2 replaces H1's placeholder with the real, single-authority
        # readiness projection. Statuses and safe reason codes only: no
        # requirement payload, no bank data, no account id, no hosted link.
        "stripe_setup": stripe_setup_projection(method)
        if method.currency == "EUR"
        else None,
    }


@method_decorator(sensitive_post_parameters("__ALL__"), name="dispatch")
class ProfileView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ProfileThrottle]

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store, private"
        return response

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not settings.PAYOUT_PROFILES_ENABLED:
            raise Http404

    def handle_exception(self, exc):
        from apps.core.storage import StorageNotConfigured
        from botocore.exceptions import BotoCoreError, ClientError

        if isinstance(exc, (StorageNotConfigured, BotoCoreError, ClientError)):
            return Response(
                {
                    "code": "payout_evidence_unavailable",
                    "detail": "Private payout evidence storage is unavailable.",
                },
                status=503,
            )
        if isinstance(exc, ObjectDoesNotExist):
            return Response({"detail": "Payout resource not found."}, status=404)
        if isinstance(exc, CountryUnsupported):
            # H2: an unsupported payout-account country is a distinct product
            # state, not a generic validation failure. The client can name what
            # is supported and offer the DZD manual rail instead of asking the
            # Traveler to guess. Nothing here suggests a residency they do not
            # have.
            return Response(
                {
                    "code": "payout_country_unsupported",
                    "detail": "Stripe EUR payouts are not available for this "
                    "account country.",
                    "supported_countries": list(allowed_countries()),
                    "alternative": {"currency": "DZD", "rail": "manual"},
                },
                status=400,
            )
        if isinstance(exc, DomainError):
            return Response(
                {
                    "code": "payout_profile_invalid",
                    "detail": "Profile validation or revision check failed.",
                },
                status=400,
            )
        return super().handle_exception(exc)


class PayoutMethodsView(ProfileView):
    def get(self, request):
        methods = (
            TravelerPayoutMethod.objects.filter(traveler=request.user)
            .select_related("current_version__dzd_profile_revision")
            .order_by("currency")
        )
        return Response(
            {
                "methods": [method_projection(m) for m in methods],
                "policy_version": "payout_profile_v1",
                "execution_enabled": False,
            }
        )

    def post(self, request):
        data = PreferenceInput(data=request.data)
        data.is_valid(raise_exception=True)
        return Response(
            method_projection(set_preference(actor=request.user, **data.validated_data))
        )


class DzdProfileView(ProfileView):
    def post(self, request):
        data = DzdInput(data=request.data)
        data.is_valid(raise_exception=True)
        return Response(
            method_projection(
                submit_dzd_profile(actor=request.user, **data.validated_data)
            ),
            status=201,
        )


class PayoutIdentityReviewView(ProfileView):
    def _assignment(self, request, reference):
        require_capabilities(request.user, "attest_payout_identity")
        assignment = PayoutIdentityReviewAssignment.objects.filter(
            public_reference=reference, reviewer=request.user, closed_at__isnull=True
        ).first()
        if not assignment:
            raise PermissionDenied("Assigned payout identity review required.")
        return assignment

    def get(self, request, reference):
        assignment = self._assignment(request, reference)
        # No generic KYC payload or payout bank data; H4 owns evidence proxy.
        return Response(
            {
                "reference": str(assignment.public_reference),
                "traveler_id": assignment.traveler_id,
                "kyc_submission_id": assignment.kyc_submission_id,
                "policy_version": "payout_profile_v1",
            }
        )

    def post(self, request, reference):
        self._assignment(request, reference)
        data = AttestationInput(data=request.data)
        data.is_valid(raise_exception=True)
        attestation = attest_identity(
            actor=request.user, assignment_reference=reference, **data.validated_data
        )
        return Response(
            {
                "reference": str(attestation.public_reference),
                "attested_at": attestation.attested_at,
            },
            status=201,
        )
