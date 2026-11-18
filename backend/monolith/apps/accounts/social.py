"""The one rule for signing in with Google or Apple (plan EGS, decision 12).

A provider's verifier (`google.py`, `apple.py`) proves who a token belongs to.
This module decides which account that person gets, the same way for every
provider:

1. The identity already linked to ``(provider, subject)`` signs in to its own
   account.
2. Otherwise the provider's verified email decides. The account with that
   email is linked; one that never confirmed its email is first claimed by the
   prover (L18A). Without such an account a new one is opened, with an
   unusable password and the email confirmed.
3. An account that is switched off, banned or disabled, is refused with
   ``account_disabled`` before any token is issued, on both paths.

No name from the provider means an empty name (decision 13): the local part of
an email address is not a name (`apps.matching.find_travelers.first_name`). An
account whose name is still empty takes the provider's name when a later
sign-in brings one; a name that is set is never overwritten
(`User.fill_blank_name`, the same set-once rule as `PATCH /api/me`).

A token without an email still signs in to an identity already linked; it
cannot link or open an account (`email_missing`), and an email the provider
has not verified cannot either (`email_not_verified`).

Two first sign-ins can race on the two unique constraints this writes,
`User.email` and `OAuthIdentity(provider, subject)`. The attempt that loses is
rolled back whole and run again, so it reads the row that won instead of
answering 500.
"""

from __future__ import annotations

from django.db import IntegrityError, transaction
from rest_framework import status

from .models import OAuthIdentity, User
from .sessions import end_all_sessions

#: Stable refusal codes, sent with a `detail` the app may show.
ACCOUNT_DISABLED = "account_disabled"
EMAIL_NOT_VERIFIED = "email_not_verified"
EMAIL_MISSING = "email_missing"
IDENTITY_INVALID = "identity_invalid"

#: Each attempt can lose at most one race per unique constraint it writes
#: (`User.email`, then `OAuthIdentity`); the attempt after both losses reads
#: two committed winners and cannot lose again.
_ATTEMPTS = 3

_SUBJECT_MAX_LENGTH = OAuthIdentity._meta.get_field("subject").max_length
_NAME_MAX_LENGTH = User._meta.get_field("full_name").max_length


class SocialSignInRefused(Exception):
    """The person cannot be signed in. `status` and `payload` are the answer."""

    def __init__(self, status_code: int, code: str, detail: str):
        super().__init__(detail)
        self.status = status_code
        self.payload = {"code": code, "detail": detail}


def sign_in_with_identity(
    *,
    provider: str,
    subject,
    email,
    email_verified,
    name,
    data: dict,
) -> User:
    """The account this provider identity signs in to, linked or opened as needed.

    ``email_verified`` must be the boolean ``True`` for the email to link or
    open an account; the verifiers already refuse anything else. ``data`` is
    the sign-in body: ``preferred_language``, and optionally ``phone`` and
    ``wilaya``, used only for a new or claimed account. Raises
    `SocialSignInRefused`.
    """

    label = OAuthIdentity.Provider(provider).label
    if not isinstance(subject, str) or not subject or len(subject) > _SUBJECT_MAX_LENGTH:
        raise SocialSignInRefused(
            status.HTTP_401_UNAUTHORIZED,
            IDENTITY_INVALID,
            f"The {label} account could not be identified.",
        )
    email = email.strip().lower() if isinstance(email, str) else ""
    name = name.strip()[:_NAME_MAX_LENGTH] if isinstance(name, str) else ""

    attempt = 1
    while True:
        try:
            with transaction.atomic():
                return _sign_in_once(
                    provider=provider,
                    label=label,
                    subject=subject,
                    email=email,
                    email_verified=email_verified,
                    name=name,
                    data=data,
                )
        except IntegrityError:
            # A concurrent sign-in committed the account or the identity this
            # attempt was inserting. Everything this attempt wrote is gone;
            # the next one reads the winner.
            if attempt == _ATTEMPTS:
                raise
            attempt += 1


def _sign_in_once(
    *,
    provider: str,
    label: str,
    subject: str,
    email: str,
    email_verified,
    name: str,
    data: dict,
) -> User:
    identity = _linked_identity(provider=provider, subject=subject)
    if identity is not None:
        _refuse_if_switched_off(identity.user)
        identity.user.fill_blank_name(name)
        return identity.user

    if not email:
        raise SocialSignInRefused(
            status.HTTP_400_BAD_REQUEST,
            EMAIL_MISSING,
            f"{label} account has no verified email.",
        )
    if email_verified is not True:
        raise SocialSignInRefused(
            status.HTTP_401_UNAUTHORIZED,
            EMAIL_NOT_VERIFIED,
            f"{label} account email is not verified.",
        )

    user = _locked_account(email=email)
    if user is None:
        user = _open_account(email=email, name=name, data=data)
    else:
        _refuse_if_switched_off(user)
        if user.is_email_verified:
            user.fill_blank_name(name)
        else:
            _claim_unconfirmed_account(user, name=name, data=data)
    OAuthIdentity.objects.create(
        user=user,
        provider=provider,
        subject=subject,
        email_at_link=email,
    )
    return user


def _linked_identity(*, provider: str, subject: str) -> OAuthIdentity | None:
    return (
        OAuthIdentity.objects.select_related("user")
        .filter(provider=provider, subject=subject)
        .first()
    )


def _locked_account(*, email: str) -> User | None:
    """The account with this email, locked so that a claim and a concurrent
    sign-in or password reset on it serialize."""

    return User.objects.select_for_update().filter(email__iexact=email).first()


def _refuse_if_switched_off(user: User) -> None:
    if not user.is_active or user.is_banned:
        raise SocialSignInRefused(
            status.HTTP_403_FORBIDDEN, ACCOUNT_DISABLED, "This account is disabled."
        )


def _open_account(*, email: str, name: str, data: dict) -> User:
    """A new account for a verified provider email; nobody can use its password."""

    user = User(
        username=email,
        email=email,
        full_name=name,
        phone=data.get("phone", ""),
        wilaya=data.get("wilaya", ""),
        preferred_language=data["preferred_language"],
        is_email_verified=True,
    )
    user.set_unusable_password()
    user.save()
    return user


def _claim_unconfirmed_account(user: User, *, name: str, data: dict) -> None:
    """Hand an unconfirmed account to the provider owner of its email (L18A, item 5).

    The provider has just proved who owns the address; nobody ever proved that
    the person who opened the account did, and anyone can sign up with someone
    else's email. So the prover gets the account as if it were new: the
    password stops working, every session and push device ends, and what the
    unproven person typed is replaced (the name from the provider; phone,
    wilaya and language from this sign-in; the phone flag cleared). The owner
    can set a password again through the reset email.
    """

    end_all_sessions(user)
    user.set_unusable_password()
    user.full_name = name
    user.phone = data.get("phone", "")
    user.wilaya = data.get("wilaya", "")
    user.preferred_language = data["preferred_language"]
    user.is_phone_verified = False
    user.is_email_verified = True
    user.save(
        update_fields=(
            "password",
            "full_name",
            "phone",
            "wilaya",
            "preferred_language",
            "is_phone_verified",
            "is_email_verified",
        )
    )
