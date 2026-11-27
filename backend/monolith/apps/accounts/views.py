from collections.abc import Callable

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.settings import api_settings as jwt_settings
from rest_framework_simplejwt.tokens import RefreshToken, UntypedToken

from apps.notifications.models import OutboundMessage
from apps.notifications.outbox import cancel_message, enqueue_secret_message
from apps.notifications.serializers import PushDeviceUnregisterSerializer

from . import deletion, photos
from .apple import AppleAuthError, AppleAuthUnavailable, verify_identity_token
from .google import GoogleAuthError, GoogleAuthUnavailable, verify_id_token
from .models import EmailVerificationCode, OAuthIdentity, PasswordResetCode, User
from .sessions import SignInInterrupted, end_all_sessions, end_session, start_session
from .serializers import (
    AccountDeletionSerializer,
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

#: The answer to a provider sign-in that cannot be checked right now (503):
#: the provider is not configured on this server, or could not be reached.
GOOGLE_SIGN_IN_UNAVAILABLE = "google_sign_in_unavailable"
APPLE_SIGN_IN_UNAVAILABLE = "apple_sign_in_unavailable"
#: Every sign-in of the account ended twice while this one was being issued.
SIGN_IN_INTERRUPTED = "sign_in_interrupted"


def _tokens_for_user(user: User) -> dict[str, str]:
    refresh = RefreshToken.for_user(user)
    refresh["role"] = user.role
    # The sign-in these tokens belong to. Refresh rotation and the access
    # tokens copy it, so every token of the sign-in ends when it ends.
    refresh["sid"] = start_session(user).pk.hex
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


#: How many times a sign-in checks its credentials. A second check happens
#: only when every sign-in of the account ended between the first check and
#: the issue (`SignInInterrupted`); a third would need another end in that
#: same instant.
_SIGN_IN_CHECKS = 2


def _sign_in(identify: Callable[[], User]) -> Response:
    """Sign in the account whose credentials ``identify`` checks.

    A password reset, a Google claim or a deletion that commits between the
    check and the issue refuses the issue (`start_session`). The credentials
    are then checked again against the account as it is now: an old password
    no longer passes, and a provider identity that still owns the account
    does. ``identify`` raises its own refusal.
    """

    for _ in range(_SIGN_IN_CHECKS):
        user = identify()
        try:
            tokens = _tokens_for_user(user)
        except SignInInterrupted:
            continue
        return Response({"user": MeSerializer(user).data, **tokens})
    return Response(
        {
            "code": SIGN_IN_INTERRUPTED,
            "detail": "The account changed during sign-in. Try again.",
        },
        status=status.HTTP_409_CONFLICT,
    )


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
        def identify() -> User:
            s = SignInSerializer(data=request.data, context={"request": request})
            s.is_valid(raise_exception=True)
            return s.validated_data["user"]

        return _sign_in(identify)


class _AccessIfValid(JWTAuthentication):
    """The access token while it is valid; an expired or refused one is no
    answer rather than a 401, so the refresh token can prove the sign-in."""

    def authenticate(self, request):
        try:
            return super().authenticate(request)
        except AuthenticationFailed:
            return None


def _proven_sign_in(request: Request) -> tuple[User, str | None] | None:
    """The account and sign-in (``sid``) that ``request`` proves, if any.

    A valid access token proves its own sign-in, whatever refresh token comes
    with it: a concurrent refresh may have rotated the one the phone captured,
    and a refresh token of another account must not be touched. Without one,
    a refresh token proves its sign-in when it is signed by this server and
    unexpired, even if a refresh already rotated it: it still names the same
    sign-in, and all that it can do here is end it.
    """

    if request.user.is_authenticated:
        return request.user, request.auth.get("sid")
    token = request.data.get("refresh")
    if not isinstance(token, str) or not token:
        return None
    try:
        refresh = UntypedToken(token)
    except TokenError:
        return None
    if refresh.get(jwt_settings.TOKEN_TYPE_CLAIM) != RefreshToken.token_type:
        return None
    user = User.objects.filter(pk=refresh.get(jwt_settings.USER_ID_CLAIM)).first()
    if user is None:
        return None
    return user, refresh.get("sid")


class SignOutView(APIView):
    """End the sign-in the request proves, and every phone it registered.

    Signing out must not leave a phone receiving the account's notifications,
    so an expired access token or a refresh token rotated meanwhile still
    signs out (`_proven_sign_in`). Ending a sign-in that already ended ends
    nothing more and answers the same. Which installation, and its number,
    are best-effort extras that only order the sign-out against the phone's
    own registrations: a body without them still signs out.
    """

    authentication_classes = (_AccessIfValid,)
    permission_classes = (AllowAny,)

    def post(self, request: Request) -> Response:
        proven = _proven_sign_in(request)
        if proven is None:
            return Response(
                {"detail": "No valid access or refresh token."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        user, session_id = proven
        device = PushDeviceUnregisterSerializer(data=request.data)
        end_session(
            user,
            session_id,
            **(device.validated_data if device.is_valid() else {}),
        )
        return Response(status=status.HTTP_205_RESET_CONTENT)


def _social_sign_in(*, provider: str, claims: dict, name, data: dict) -> Response:
    """Sign a verified provider identity in through the one rule (`social.py`)."""

    def identify() -> User:
        return sign_in_with_identity(
            provider=provider,
            subject=claims.get("sub"),
            email=claims.get("email"),
            email_verified=claims.get("email_verified"),
            name=name,
            data=data,
        )

    try:
        return _sign_in(identify)
    except SocialSignInRefused as exc:
        return Response(exc.payload, status=exc.status)


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


class MePhotoView(APIView):
    """PUT    /api/me/photo — add or replace the member's photo (multipart, `photo`).
    DELETE /api/me/photo — remove it, or dismiss a "removed by Wassla" notice.

    The rule is `apps.accounts.photos`. PUT answers the member's own photo
    block (`GET /api/me` `photo`), takes the media-upload throttle and reads
    the body in memory only (`photos.PhotoUploadHandler`); DELETE answers 204,
    also when there was nothing to remove, and is never throttled: a member can
    always take their photo down.
    """

    permission_classes = (IsAuthenticated,)
    parser_classes = (MultiPartParser,)

    def get_throttles(self):
        if self.request.method == "PUT":
            self.throttle_scope = "media_upload"
            return [ScopedRateThrottle()]
        if self.request.method == "DELETE":
            return []
        return super().get_throttles()

    def put(self, request: Request) -> Response:
        request.upload_handlers = [photos.PhotoUploadHandler(request)]
        try:
            photo = photos.replace_photo(request.user, request.FILES.get("photo"))
        except photos.PhotoRefused as exc:
            return Response(exc.payload, status=exc.status)
        return Response(photos.own_view(photo))

    def delete(self, request: Request) -> Response:
        photos.remove_own_photo(request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class AccountDeletionView(APIView):
    """GET  /api/me/deletion — what stands before deleting the account.
    POST /api/me/deletion — delete it (`apps.accounts.deletion`).

    POST answers 204 once the account is deleted: every session has ended, so
    the app signs out locally. The password is checked, so the endpoint takes
    the sign-in throttle.
    """

    permission_classes = (IsAuthenticated,)

    def get_throttles(self):
        if self.request.method == "POST":
            self.throttle_scope = "login"
            return [ScopedRateThrottle()]
        return super().get_throttles()

    def get(self, request: Request) -> Response:
        result = deletion.check(request.user)
        return Response(
            {
                "blockers": list(result.blockers),
                "password_required": result.password_required,
                "apple_authorization_required": result.apple_authorization_required,
            }
        )

    def post(self, request: Request) -> Response:
        serializer = AccountDeletionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            deletion.delete_account(request.user, **serializer.validated_data)
        except deletion.AccountDeletionRefused as exc:
            return Response(exc.payload, status=exc.status)
        return Response(status=status.HTTP_204_NO_CONTENT)
