from django.db import transaction
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from apps.notifications.models import OutboundMessage
from apps.notifications.outbox import enqueue_secret_message

from .google import GoogleAuthError, verify_id_token
from .models import EmailVerificationCode, OAuthIdentity, PasswordResetCode, User
from .serializers import (
    GoogleSignInSerializer,
    MeSerializer,
    MeUpdateSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    SignInSerializer,
    SignUpSerializer,
    VerifyEmailSerializer,
)


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
        return Response(status=status.HTTP_205_RESET_CONTENT)


class GoogleSignInView(APIView):
    permission_classes = (AllowAny,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "google_signin"

    def post(self, request: Request) -> Response:
        s = GoogleSignInSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        try:
            payload = verify_id_token(s.validated_data["id_token"])
        except GoogleAuthError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_401_UNAUTHORIZED
            )

        # Keep the policy at the view boundary as well as in the verifier. The
        # duplicate check protects against a future alternate verifier and
        # ensures an unverified claim can never link to an existing account.
        if payload.get("email_verified") is not True:
            return Response(
                {"detail": "Google account email is not verified."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        sub = payload["sub"]
        email = (payload.get("email") or "").lower().strip()
        name = payload.get("name") or email.split("@")[0]
        if not email:
            return Response(
                {"detail": "Google account has no verified email."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        identity = OAuthIdentity.objects.filter(
            provider=OAuthIdentity.Provider.GOOGLE, subject=sub
        ).first()

        if identity is not None:
            user = identity.user
        else:
            user = User.objects.filter(email__iexact=email).first()
            if user is None:
                user = User.objects.create(
                    username=email,
                    email=email,
                    full_name=name,
                    phone=s.validated_data.get("phone", ""),
                    wilaya=s.validated_data.get("wilaya", ""),
                    preferred_language=s.validated_data["preferred_language"],
                    is_email_verified=bool(payload.get("email_verified")),
                )
                user.set_unusable_password()
                user.save(update_fields=("password",))
            OAuthIdentity.objects.create(
                user=user,
                provider=OAuthIdentity.Provider.GOOGLE,
                subject=sub,
                email_at_link=email,
            )

        return Response({"user": MeSerializer(user).data, **_tokens_for_user(user)})


class PasswordResetRequestView(APIView):
    """Always returns 202, even if email is unknown — prevents account enumeration."""

    permission_classes = (AllowAny,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "password_reset"

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
            user = User.objects.select_for_update().filter(email__iexact=email).first()
            if user is None:
                return Response(
                    {"detail": "Invalid code."}, status=status.HTTP_400_BAD_REQUEST
                )

            active = (
                user.password_reset_codes.filter(used_at__isnull=True)
                .order_by("-created_at")
                .first()
            )
            if active is None or not active.verify(code):
                return Response(
                    {"detail": "Invalid code."}, status=status.HTTP_400_BAD_REQUEST
                )

            user.set_password(new_password)
            user.save(update_fields=("password",))
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
