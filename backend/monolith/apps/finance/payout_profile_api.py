"""Flagged, owner-scoped profile API. Sensitive fields are write-only."""

from contextlib import nullcontext

from django.core.exceptions import ValidationError as DomainError, PermissionDenied
from django.core.exceptions import ObjectDoesNotExist
from django.db import connection, transaction
from django.utils.decorators import method_decorator
from django.views.decorators.debug import sensitive_post_parameters
from rest_framework import serializers
from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from apps.admin_panel.permissions import IsVerifiedStaff
from apps.admin_panel.staff_api import StaffSessionMixin
from apps.core.financial_locks import lock_payout_method_set

from .models import PayoutIdentityReviewAssignment
from .payout_accounts import (
    AccountCountryMismatch,
    ConnectUnavailable,
    CountryUnsupported,
    PreferenceChanged,
    SetupInProgress,
    account_country,
    standing_accounts,
    stripe_setup_projection,
)
from .payout_profiles import (
    EmailVerificationRequired,
    PayoutProfilesDisabled,
    TravelerRequired,
    _traveler,
    set_preference,
    submit_dzd_profile,
    attest_identity,
    require_capabilities,
    require_profiles,
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

    def validate(self, attrs):
        from .sensitive_data import postal_account

        try:
            attrs["ccp_number"], attrs["ccp_key"], attrs["rip"] = postal_account(
                ccp_number=attrs["ccp_number"], ccp_key=attrs["ccp_key"], rip=attrs["rip"]
            )
        except DomainError as exc:
            raise serializers.ValidationError(exc.message_dict) from None
        return attrs


class MobilePreferenceInput(StrictInput):
    preference = serializers.ChoiceField(choices=["eur_only", "dzd_only", "both"])
    eur_revision = serializers.IntegerField(min_value=0)
    dzd_revision = serializers.IntegerField(min_value=0)
    country = serializers.CharField(max_length=2, required=False, default="", allow_blank=True)
    consent_policy = serializers.ChoiceField(choices=["payout_profile_v1"])


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


class PayoutSetupMember(BasePermission):
    """The member payout-setup gate on every write, before the body is read.

    Listed after `IsAuthenticated` on every member setup view (`ProfileView`,
    `ConnectView`), so a write meets the refusal order the read model reports
    (`payout_mobile.setup_gate`): payout profiles switched off, then an
    account that cannot hold payout setup, then an unconfirmed email. The
    write asks the same question again of the User row it locks. Reads pass
    and report the same order in their payload.
    """

    def has_permission(self, request, view):
        if request.method not in SAFE_METHODS:
            _traveler(request.user)
        return True


def one_read():
    """One snapshot for a whole member read, so a commit between two of its
    queries cannot split the answer. A write builds its answer inside its own
    transaction, under the locks it holds, and so does a read made there.
    """

    from .control_plane.snapshot import consistent_read

    return nullcontext() if connection.in_atomic_block else consistent_read()


def setup_refusal(exc, user):
    """The stable answer to a refused member payout-setup call, or None.

    Every reason the read model gives as `unavailable_reason` refuses a direct
    write with the same code, so a client that skipped the read learns the same
    thing.
    """
    if isinstance(exc, AccountCountryMismatch):
        account = standing_accounts(user.pk).first()
        return Response(
            {
                "code": AccountCountryMismatch.code,
                "detail": "Your Stripe payout account was opened for another country.",
                "account_country": account_country(account) if account else None,
            },
            status=409,
        )
    if isinstance(exc, PreferenceChanged):
        return Response(
            {
                "code": PreferenceChanged.code,
                "detail": "Your payout preference changed. Refresh and try again.",
            },
            status=409,
        )
    if isinstance(exc, SetupInProgress):
        return Response(
            {
                "code": SetupInProgress.code,
                "detail": "Your Stripe payout account is being created. Continue the setup first.",
            },
            status=409,
        )
    if isinstance(exc, PayoutProfilesDisabled):
        return Response(
            {"code": PayoutProfilesDisabled.code, "detail": "Payout setup is not open yet."},
            status=409,
        )
    if isinstance(exc, TravelerRequired):
        return Response(
            {"code": TravelerRequired.code, "detail": "Payout setup needs a traveler account."},
            status=403,
        )
    if isinstance(exc, EmailVerificationRequired):
        return Response(
            {"code": EmailVerificationRequired.code, "detail": "Confirm your email address first."},
            status=403,
        )
    if isinstance(exc, ConnectUnavailable):
        return Response(
            {
                "code": ConnectUnavailable.code,
                "detail": "Stripe payout setup is not available yet.",
            },
            status=409,
        )
    if isinstance(exc, CountryUnsupported):
        from .payout_mobile import eur_refusal, setup_gate

        # H2: an unsupported payout-account country is a distinct product
        # state, not a generic validation failure. With no country open at all
        # the account country is not the reason, so the code says what is. The
        # client can name what is supported and offer the DZD manual rail
        # instead of asking the Traveler to guess. Nothing here suggests a
        # residency they do not have.
        gate = setup_gate(user)
        code = eur_refusal(gate)
        country_refused = code == CountryUnsupported.code
        # Set only when the refused country is the one the Traveler's Stripe
        # account was opened for, which no new declaration can change.
        return Response(
            {
                "code": code,
                "detail": "Stripe EUR payouts are not available for this account country."
                if country_refused
                else "Stripe EUR payouts are not available yet.",
                "supported_countries": list(gate.countries),
                "account_country": exc.country if exc.of_account else None,
                "alternative": {"currency": "DZD", "rail": "manual"},
            },
            status=400 if country_refused else 409,
        )
    return None


def method_projection(method, gate, mobile=None):
    """One method as the member sees it. `mobile` is the rail object the
    response already computed, so the method list and the summary carry one
    computation."""
    from .payout_mobile import eur_method, dzd_method
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
        "mobile": mobile if mobile is not None else (
            eur_method if method.currency == "EUR" else dzd_method)(method, gate),
    }


@method_decorator(sensitive_post_parameters("__ALL__"), name="dispatch")
class ProfileView(APIView):
    # Writing payout setup needs a confirmed email (L18A): a stranger who
    # opened the account under someone else's address must not leave a payout
    # method behind for the owner to inherit. The member gate asks it, in the
    # read model's order. Staff views set their own.
    permission_classes = [IsAuthenticated, PayoutSetupMember]
    throttle_classes = [ProfileThrottle]
    #: A member read that stays open with payout profiles switched off: the
    #: stored setup stays visible and the read itself says setup is closed.
    readable_when_disabled = False

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store, private"
        return response

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if request.method not in SAFE_METHODS or not self.readable_when_disabled:
            require_profiles()

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
        refusal = setup_refusal(exc, self.request.user)
        if refusal is not None:
            return refusal
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
    readable_when_disabled = True

    def get(self, request):
        from .payout_mobile import methods_for, payout_summary, setup_gate

        with one_read():
            gate = setup_gate(request.user)
            methods = list(methods_for(request.user))
            summary = payout_summary(request.user, methods, gate)
            rails = {"EUR": summary["eur"], "DZD": summary["dzd"]}
            body = {
                "methods": [method_projection(m, gate, rails[m.currency]) for m in methods],
                "policy_version": "payout_profile_v1",
                "execution_enabled": False,
                **summary,
            }
        return Response(body)

    @transaction.atomic
    def patch(self, request):
        from apps.accounts.models import User

        data = MobilePreferenceInput(data=request.data)
        data.is_valid(raise_exception=True)
        values = data.validated_data
        User.objects.select_for_update(no_key=True).get(pk=request.user.pk)
        # Take the method set funding takes before making either preference
        # change; rollback both when any revision/country check fails.
        current = lock_payout_method_set(request.user.pk)
        by_currency = {m.currency: m for m in current}
        for currency in ("EUR", "DZD"):
            method = by_currency.get(currency)
            enabled = values["preference"] in ("both", "eur_only" if currency == "EUR" else "dzd_only")
            # No country keeps the saved one. `set_preference` validates and
            # normalizes the EUR account country and stores none on DZD.
            country = values["country"] or (
                method.current_version.country if method and method.current_version else ""
            )
            set_preference(actor=request.user, currency=currency, enabled=enabled,
                           expected_revision=values[f"{currency.lower()}_revision"],
                           country=country, consent_policy=values["consent_policy"])
        # Read under the locks this write still holds.
        return self.get(request)

    @transaction.atomic
    def post(self, request):
        from .payout_mobile import setup_gate

        data = PreferenceInput(data=request.data)
        data.is_valid(raise_exception=True)
        method = set_preference(actor=request.user, **data.validated_data)
        return Response(method_projection(method, setup_gate(method.traveler)))


class DzdProfileView(ProfileView):
    readable_when_disabled = True

    def get(self, request):
        from .payout_mobile import methods_for, payout_summary, setup_gate

        with one_read():
            gate = setup_gate(request.user)
            methods = list(methods_for(request.user))
            method = next((m for m in methods if m.currency == "DZD"), None)
            summary = payout_summary(request.user, methods, gate)
            body = {"contract_version": summary["contract_version"],
                    "method": method_projection(method, gate, summary["dzd"]) if method else None,
                    "dzd": summary["dzd"], "setup": summary["setup"]}
        return Response(body)

    def post(self, request):
        from .payout_evidence import require_evidence_store
        from .payout_mobile import setup_gate

        # The read offers no DZD submission without the private store, so a
        # proof uploaded before it was switched off is refused the same way.
        require_evidence_store()
        data = DzdInput(data=request.data)
        data.is_valid(raise_exception=True)
        with transaction.atomic():
            method = submit_dzd_profile(actor=request.user, **data.validated_data)
            body = method_projection(method, setup_gate(method.traveler))
        return Response(body, status=201)


class PayoutIdentityReviewView(StaffSessionMixin, ProfileView):
    permission_classes = [IsVerifiedStaff]

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
