"""Ending everything an account is signed in with (L18A, plan L18A item 5).

The moment someone proves they own an account's email address (a completed
password reset, or Google sign-in on an account that never confirmed its
email), whoever held the account before may have been someone else: anyone can
sign up with another person's address. `end_all_sessions` leaves the prover
alone in it. An access token already issued lives to its own expiry
(`JWT_ACCESS_TTL_SECONDS`); everything that could renew it is gone.
"""

from __future__ import annotations

from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)

from apps.notifications.push import deactivate_all_push_devices


def end_all_sessions(user) -> None:
    """Revoke every refresh token of ``user`` and switch off their push devices."""

    revoked = OutstandingToken.objects.filter(user=user).exclude(
        blacklistedtoken__isnull=False
    )
    BlacklistedToken.objects.bulk_create(
        [BlacklistedToken(token=token) for token in revoked],
        ignore_conflicts=True,
    )
    deactivate_all_push_devices(user=user)
