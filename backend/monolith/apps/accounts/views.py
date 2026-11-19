import logging
from uuid import UUID

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from apps.notifications.models import OutboundMessage
from apps.notifications.outbox import cancel_message, enqueue_secret_message
from apps.notifications.push import unregister_push_device

from .apple import AppleAuthError, AppleAuthUnavailable, verify_identity_token
from .google import GoogleAuthError, GoogleAuthUnavailable, verify_id_token
from .models import EmailVerificationCode, OAuthIdentity, PasswordResetCode, User
from .sessions import end_all_sessions
from .serializers import (
    AppleSignInSerializer,
    GoogleSignInSerializer,
    MeSerializer,
    MeUpdateSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    SignInSerializer,
    SignUpSerializer,
    VerifyEmailSerializer,
)
from .social import SocialSignInRefused, sign_in_with_identity

logger = logging.getLogger(__name__)

#: The answer to a provider sign-in that cannot be checked right now (503):
#: the provider is not configured on this server, or could not be reached.
GOOGLE_SIGN_IN_UNAVAILABLE = "google_sign_in_unavailable"
APPLE_SIGN_IN_UNAVAILABLE = "apple_sign_in_unavailable"


def _tokens_for_user(user: User) -> dict[str, str]:
    refresh = RefreshToken.for_user(user)
    refresh["role"] = user.role
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


def _send_verify_email(user: User) -> None:
    """Issue a signup OTP and arm its PostgreSQL-backed email obligation."""
    code_row, code = EmailVerificationCode.issue(user)
    enqueue_secret_message(
        kind=OutboundMessage.Kind.EMAIL_VERIFICATION,
        key=f"email_verification:{code_row.pk}",
        to_email=user.email,
        recipient_user_id=user.pk,
        secret=code,
        secret_expires_at=code_row.expires_at,
    )


class SignUpView(APIView):
    permission_classes = (AllowAny,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "registration"

    @transaction.atomic
    def post(self, request: Request) -> Response:
        s = SignUpSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        user = s.save()
        _send_verify_email(user)
        return Response(
            {"user": MeSerializer(user).data, **_tokens_for_user(user)},
            status=status.HTTP_201_CREATED,
        )


class SignInView(APIView):
    permission_classes = (AllowAny,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "login"

    def post(self, request: Request) -> Response:
        s = SignInSerializer(data=request.data, context={"request": request})
        s.is_valid(raise_exception=True)
        user: User = s.validated_data["user"]
        return Response({"user": MeSerializer(user).data, **_tokens_for_user(user)})


class SignOutView(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> Response:
        token = request.data.get("refresh")
        if not token:
            return Response(
                {"detail": "Missing 'refresh' token."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            RefreshToken(token).blacklist()
        except TokenError:
            return Response(
                {"detail": "Invalid or expired refresh token."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        installation_id = request.data.get("installation_id")
        if installation_id:
            try:
                unregister_push_device(
                    user=request.user,
                    installation_id=UUID(str(installation_id)),
                )
            except (TypeError, ValueError):
                # Device cleanup metadata is best-effort and must never trap a
                # user in an account or weaken refresh-token validation.
                pass
            except Exception:
                logger.warning(
                    "push device cleanup failed during logout user_id=%s",
                    request.user.pk,
                )
        return Response(status=status.HTTP_205_RESET_CONTENT)


def _social_sign_in(*, provider: str, claims: dict, name, data: dict) -> Response:
    """Sign a verified provider identity in through the one rule (`social.py`)."""

    try:
        user = sign_in_with_identity(
            provider=provider,
            subject=claims.get("sub"),
            email=claims.get("email"),
            email_verified=claims.get("email_verified"),
            name=name,
            data=data,
        )
    except SocialSignInRefused as exc:
        return Response(exc.payload, status=exc.status)
    return Response({"user": MeSerializer(user).data, **_tokens_for_user(user)})


class GoogleSignInView(APIView):
    permission_classes = (AllowAny,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "google_signin"

    def post(self, request: Request) -> Response:
        s = GoogleSignInSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        try:
            claims = verify_id_token(s.validated_data["id_token"])
        except GoogleAuthError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_401_UNAUTHORIZED
            )
        except GoogleAuthUnavailable as exc:
            # Not configured, or Google could not be reached: the token was
            # never judged, so this is not a rejected credential.
            return Response(
                {"code": GOOGLE_SIGN_IN_UNAVAILABLE, "detail": str(exc)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return _social_sign_in(
            provider=OAuthIdentity.Provider.GOOGLE,
            claims=claims,
            name=claims.get("name"),
            data=s.validated_data,
        )


class AppleSignInView(APIView):
    """`POST /api/auth/oauth/apple`: Sign in with Apple from the iOS app."""

    permission_classes = (AllowAny,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "apple_signin"

    def post(self, request: Request) -> Response:
        s = AppleSignInSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        try:
            claims = verify_identity_token(
                s.validated_data["identity_token"], raw_nonce=s.validated_data["nonce"]
            )
        except AppleAuthError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_401_UNAUTHORIZED
            )
        except AppleAuthUnavailable as exc:
            return Response(
                {"code": APPLE_SIGN_IN_UNAVAILABLE, "detail": str(exc)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return _social_sign_in(
            provider=OAuthIdentity.Provider.APPLE,
            claims=claims,
            name=s.validated_data["full_name"],
            data=s.validated_data,
        )


class PasswordResetRequestView(APIView):
    """Always returns 202, even if email is unknown — prevents account enumeration."""

    permission_classes = (AllowAny,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "password_reset"

    @transaction.atomic
    def post(self, request: Request) -> Response:
        s = PasswordResetRequestSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        email = s.validated_data["email"].lower().strip()
        user = User.objects.filter(email__iexact=email).first()
        if user is not None:
            code_row, plaintext = PasswordResetCode.issue(user)
            enqueue_secret_message(
                kind=OutboundMessage.Kind.PASSWORD_RESET,
                key=f"password_reset:{code_row.pk}",
                to_email=user.email,
                recipient_user_id=user.pk,
                secret=plaintext,
                secret_expires_at=code_row.expires_at,
            )
        return Response(status=status.HTTP_202_ACCEPTED)


class PasswordResetConfirmView(APIView):
    permission_classes = (AllowAny,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "password_reset"

    def post(self, request: Request) -> Response:
        s = PasswordResetConfirmSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        email = s.validated_data["email"].lower().strip()
        code = s.validated_data["code"]
        new_password = s.validated_data["new_password"]

        with transaction.atomic():
            user = User.objects.select_for_update(no_key=True).filter(email__iexact=email).first()
            if user is None:
                return Response(
                    {"detail": "Invalid code."}, status=status.HTTP_400_BAD_REQUEST
                )

            active = (
                user.password_reset_codes.order_by("-created_at", "-pk")
                .first()
            )
            if active is None or not active.verify(code):
                return Response(
                    {"detail": "Invalid code."}, status=status.HTTP_400_BAD_REQUEST
                )

            # The code went to the address, so this proves the email (L18A,
            # item 5): the new password, the end of every older session and
            # the confirmed flag land together.
            user.set_password(new_password)
            user.is_email_verified = True
            user.save(update_fields=("password", "is_email_verified"))
            end_all_sessions(user)
            from apps.notifications.outbox import enqueue_message

            enqueue_message(
                kind=OutboundMessage.Kind.SECURITY_EVENT,
                key=f"security_event:password_reset:{active.pk}",
                to_email=user.email,
                recipient_user_id=user.pk,
                context={"event": "password_reset_completed"},
            )
        return Response(status=status.HTTP_204_NO_CONTENT)


class VerifyEmailView(APIView):
    """Confirm a signup email with the 6-digit OTP → is_email_verified=True.

    Uses the same invalid-code 400 for both unknown-email and wrong-code so
    the endpoint doesn't leak which emails exist. Idempotent: re-verifying an
    already-verified account with a still-valid code returns 204.
    """

    permission_classes = (AllowAny,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "email_verify"

    def post(self, request: Request) -> Response:
        s = VerifyEmailSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        email = s.validated_data["email"].lower().strip()
        code = s.validated_data["code"]

        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            return Response(
                {"detail": "Invalid code."}, status=status.HTTP_400_BAD_REQUEST
            )
        if user.is_email_verified:
            return Response(status=status.HTTP_204_NO_CONTENT)

        active = (
            user.email_verification_codes.filter(used_at__isnull=True)
            .order_by("-created_at")
            .first()
        )
        if active is None or not active.verify(code):
            return Response(
                {"detail": "Invalid code."}, status=status.HTTP_400_BAD_REQUEST
            )

        user.is_email_verified = True
        user.save(update_fields=("is_email_verified",))
        return Response(status=status.HTTP_204_NO_CONTENT)


class ResendVerifyEmailView(APIView):
    """Send the signed-in member a fresh email verification code (L18A).

    The sign-up code expires and has an attempt cap, and creating a delivery
    request needs a verified email, so a member must be able to ask again. The
    answer is always 204: a verified account is sent nothing; otherwise every
    unused code is retired (its pending email withdrawn) and a new one goes out
    through the same outbox path as sign-up. The member row is locked so two
    taps cannot leave two live codes.
    """

    permission_classes = (IsAuthenticated,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "email_verify_resend"

    def post(self, request: Request) -> Response:
        with transaction.atomic():
            user = User.objects.select_for_update().get(pk=request.user.pk)
            if user.is_email_verified:
                return Response(status=status.HTTP_204_NO_CONTENT)
            unused = list(
                user.email_verification_codes.filter(
                    used_at__isnull=True
                ).values_list("pk", flat=True)
            )
            if unused:
                EmailVerificationCode.objects.filter(pk__in=unused).update(
                    used_at=timezone.now()
                )
                for code_id in unused:
                    cancel_message(
                        key=f"email_verification:{code_id}",
                        reason="superseded by a new verification code",
                    )
            _send_verify_email(user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request: Request) -> Response:
        return Response(MeSerializer(request.user).data)

    def patch(self, request: Request) -> Response:
        serializer = MeUpdateSerializer(
            request.user,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(MeSerializer(request.user).data)
