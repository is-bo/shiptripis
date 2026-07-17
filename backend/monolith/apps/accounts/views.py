from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from apps.core import redis_bus

from .google import GoogleAuthError, verify_id_token
from .models import EmailVerificationCode, OAuthIdentity, PasswordResetCode, User
from .serializers import (
    GoogleSignInSerializer,
    MeSerializer,
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
    """Issue a signup-verification OTP and enqueue it onto the email stream."""
    _, code = EmailVerificationCode.issue(user)
    redis_bus.enqueue_email_after_commit(
        user.email,
        subject="Confirm your ShipTrip email",
        body=(
            f"Welcome to ShipTrip! Your email verification code is: {code}\n"
            "It expires in 15 minutes."
        ),
        kind="verify",
    )


class SignUpView(APIView):
    permission_classes = (AllowAny,)

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

    def post(self, request: Request) -> Response:
        s = GoogleSignInSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        try:
            payload = verify_id_token(s.validated_data["id_token"])
        except GoogleAuthError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_401_UNAUTHORIZED
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

    def post(self, request: Request) -> Response:
        s = PasswordResetRequestSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        email = s.validated_data["email"].lower().strip()
        user = User.objects.filter(email__iexact=email).first()
        if user is not None:
            _, plaintext = PasswordResetCode.issue(user)
            redis_bus.enqueue_email_after_commit(
                user.email,
                subject="ShipTrip password reset code",
                body=(
                    f"Your ShipTrip reset code is: {plaintext}\n"
                    "It expires in 15 minutes. If you did not request this, ignore."
                ),
                kind="reset",
            )
        return Response(status=status.HTTP_202_ACCEPTED)


class PasswordResetConfirmView(APIView):
    permission_classes = (AllowAny,)

    def post(self, request: Request) -> Response:
        s = PasswordResetConfirmSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        email = s.validated_data["email"].lower().strip()
        code = s.validated_data["code"]
        new_password = s.validated_data["new_password"]

        user = User.objects.filter(email__iexact=email).first()
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
        return Response(status=status.HTTP_204_NO_CONTENT)


class VerifyEmailView(APIView):
    """Confirm a signup email with the 6-digit OTP → is_email_verified=True.

    Uses the same invalid-code 400 for both unknown-email and wrong-code so
    the endpoint doesn't leak which emails exist. Idempotent: re-verifying an
    already-verified account with a still-valid code returns 204.
    """

    permission_classes = (AllowAny,)

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
