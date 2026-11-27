"""Sign-ins: starting one, ending one, and ending all of an account's (L18A, N1).

Every sign-in is a `SignInSession` row, and every token it issues names that
row in its ``sid`` claim, refresh rotation included. A refresh token of an
ended sign-in is refused (`SessionRefreshToken`), and so is a push
registration made with any token of it (`apps.notifications.push`). Ending a
sign-in is therefore one write that no rotated or in-flight token can get
around.

The moment someone proves they own an account's email address (a completed
password reset, or Google sign-in on an account that never confirmed its
email), whoever held the account before may have been someone else: anyone can
sign up with another person's address. `end_all_sessions` leaves the prover
alone in it. An access token already issued lives to its own expiry
(`JWT_ACCESS_TTL_SECONDS`), but it can no longer renew itself or switch a phone
on.
"""

from __future__ import annotations

from uuid import UUID

from django.db import transaction
from django.utils import timezone
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.tokens import RefreshToken

from apps.notifications.push import (
    deactivate_all_push_devices,
    deactivate_session_push_devices,
)

from .locks import lock_account
from .models import SignInSession


def start_session(user) -> SignInSession:
    """A new live sign-in of ``user``; its id goes into the tokens as ``sid``."""

    return SignInSession.objects.create(user=user)


def end_session(
    user,
    session_id,
    *,
    installation_id: UUID | None = None,
    binding_sequence: int | None = None,
) -> None:
    """End ``user``'s sign-in ``session_id`` and switch off its push devices.

    Every device the sign-in registered goes off, whichever installation the
    sign-out names or fails to name, and a registration of the sign-in still
    on its way is refused when it arrives, because it finds the sign-in ended.
    With ``installation_id`` and ``binding_sequence`` the sign-out is also
    recorded in the installation's order (`PushInstallationBinding`). Ending
    a sign-in that already ended, or one of another account, ends nothing.
    """

    with transaction.atomic():
        lock_account(user)
        session = SignInSession.live(user_id=user.pk, session_id=session_id)
        if session is not None:
            session.ended_at = timezone.now()
            session.save(update_fields=("ended_at",))
        deactivate_session_push_devices(
            user=user,
            session_id=session.pk if session is not None else None,
            installation_id=installation_id,
            binding_sequence=binding_sequence,
        )


def end_all_sessions(user) -> None:
    """End every sign-in of ``user`` and switch off all of their push devices."""

    with transaction.atomic():
        lock_account(user)
        SignInSession.objects.filter(user=user, ended_at__isnull=True).update(
            ended_at=timezone.now()
        )
        deactivate_all_push_devices(user=user)


class SessionRefreshToken(RefreshToken):
    """A refresh token that is valid only while its sign-in is live.

    SimpleJWT checks the token's own blacklist entry only, and a token it
    rotated is not on the account's outstanding list, so ending a sign-in by
    blacklisting its tokens missed every rotated one. The sign-in row is the
    one thing every rotation of it shares.
    """

    def verify(self) -> None:
        super().verify()
        if (
            SignInSession.live(
                user_id=self.get(api_settings.USER_ID_CLAIM),
                session_id=self.get("sid"),
            )
            is None
        ):
            raise TokenError("This sign-in has ended.")


class SessionTokenRefreshSerializer(TokenRefreshSerializer):
    """The refresh, for a sign-in that is still live (`SessionRefreshToken`)."""

    token_class = SessionRefreshToken
