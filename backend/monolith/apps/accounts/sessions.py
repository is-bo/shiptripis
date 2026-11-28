"""Sign-ins: starting one, ending one, and ending all of an account's (L18A, N1).

Every sign-in is a `SignInSession` row, and every token it issues names that
row in its ``sid`` claim, refresh rotation included. A refresh token of an
ended sign-in is refused (`SessionTokenRefreshSerializer`), and so is a push
registration made with any token of it (`apps.notifications.push`). Ending a
sign-in is therefore one write that no rotated or in-flight token can get
around.

The moment someone proves they own an account's email address (a completed
password reset, or Google sign-in on an account that never confirmed its
email), whoever held the account before may have been someone else: anyone can
sign up with another person's address. `end_all_sessions` leaves the prover
alone in it, including against a sign-in whose old password was checked just
before the end and whose session would otherwise be issued just after it. An access token already issued lives to its own expiry
(`JWT_ACCESS_TTL_SECONDS`), but it can no longer renew itself or switch a phone
on.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.tokens import RefreshToken, Token

from apps.notifications.push import (
    deactivate_all_push_devices,
    deactivate_session_push_devices,
)

from .locks import lock_account
from .models import SignInSession, User


class SignInInterrupted(Exception):
    """Every sign-in of the account ended after this one's credentials were checked."""


def start_session(user) -> SignInSession:
    """A new live sign-in of ``user``; its id goes into the tokens as ``sid``.

    ``user`` is the row as the credential check read it. A password reset, a
    Google claim or a deletion can commit between that check and this call,
    and the sign-in issued here would then outlive the end it missed. So the
    account's ``session_epoch`` is read again under the account lock, which
    `end_all_sessions` takes too: if it moved, the credentials were checked
    against an account that has since changed hands, and `SignInInterrupted`
    is raised instead of issuing anything.
    """

    with transaction.atomic():
        if lock_account(user).session_epoch != user.session_epoch:
            raise SignInInterrupted
        return SignInSession.objects.create(user=user)


def end_session(user, session_id) -> None:
    """End ``user``'s sign-in ``session_id`` and switch off its push devices.

    Every device the sign-in registered goes off, and a registration of the
    sign-in still on its way is refused when it arrives, because it finds the
    sign-in ended. A sign-in that is not live (ended already, or never
    issued to ``user``) writes nothing: its devices went off when it ended.
    So does an account deleted since ``user`` was read: its sign-ins ended
    with it.
    """

    with transaction.atomic():
        try:
            lock_account(user)
        except User.DoesNotExist:
            return
        session = SignInSession.live(user_id=user.pk, session_id=session_id)
        if session is None:
            return
        session.ended_at = timezone.now()
        session.save(update_fields=("ended_at",))
        deactivate_session_push_devices(session)


def end_all_sessions(user) -> None:
    """End every sign-in of ``user`` and switch off all of their push devices.

    The account's ``session_epoch`` moves on in the same transaction, and
    ``user`` carries the new count, so a sign-in whose credentials were
    checked before this end is refused (`start_session`), while one the
    caller issues after it, such as a Google claim's own, is not.
    """

    with transaction.atomic():
        epoch = lock_account(user).session_epoch + 1
        User.objects.filter(pk=user.pk).update(session_epoch=epoch)
        user.session_epoch = epoch
        SignInSession.objects.filter(user=user, ended_at__isnull=True).update(
            ended_at=timezone.now()
        )
        deactivate_all_push_devices(user=user)


def write_password(user, raw_password: str | None) -> None:
    """The one writer of a password; ``None`` makes it unusable.

    On an existing account the new hash is saved and every sign-in ends, in
    one transaction under the account lock (`end_all_sessions`): whoever held
    the old password keeps nothing, and the hash is written by name, so no
    other field goes with it. A new account, not saved yet, only gets the
    hash; its creator saves the row.
    """

    if raw_password is None:
        user.set_unusable_password()
    else:
        user.set_password(raw_password)
    if user.pk is None:
        return
    with transaction.atomic():
        end_all_sessions(user)
        user.save(update_fields=("password",))


class SessionRefreshToken(RefreshToken):
    """A refresh token whose blacklist entry is read under its sign-in's lock.

    Reading it checks the signature, the expiry, the type and the id only.
    Whether it may still be used is decided by `SessionTokenRefreshSerializer`,
    with the sign-in row locked: a blacklist read before that lock could miss
    a rotation of the same token that commits just ahead of it.
    """

    def verify(self) -> None:
        Token.verify(self)


class SessionTokenRefreshSerializer(TokenRefreshSerializer):
    """The refresh of a live sign-in, which survives a lost answer.

    Of one sign-in, two refresh tokens are accepted: the current one, and the
    one it was rotated from (``SignInSession.previous_refresh_jti``). A phone
    whose answer was lost still holds that older token and presents it again:
    it gets a fresh pair, and the sign-in does not change. Once the phone uses
    a token it was given, that token becomes the older one, and the one before
    is refused like any other blacklisted token. Liveness comes first: an
    ended sign-in refuses every token. The sign-in row stays locked until the
    pair is issued, so two refreshes of one token take turns.
    """

    token_class = SessionRefreshToken

    def validate(self, attrs):
        refresh = self.token_class(attrs["refresh"])
        presented = refresh[api_settings.JTI_CLAIM]
        with transaction.atomic():
            session = SignInSession.live(
                user_id=refresh.get(api_settings.USER_ID_CLAIM),
                session_id=refresh.get("sid"),
                lock=True,
            )
            if session is None:
                raise TokenError("This sign-in has ended.")
            try:
                refresh.check_blacklist()
            except TokenError:
                if presented != session.previous_refresh_jti:
                    raise
            else:
                session.previous_refresh_jti = presented
                session.save(update_fields=("previous_refresh_jti",))
            # SimpleJWT blacklists the token (a repeat's already is) and rotates it.
            return super().validate(attrs)
