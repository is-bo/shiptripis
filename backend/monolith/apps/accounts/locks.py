"""The account row lock that orders sign-in changes against push registration."""

from __future__ import annotations

from django.contrib.auth import get_user_model


def lock_account(user):
    """Hold ``user``'s row until the caller's transaction ends, and return it.

    Starting a sign-in, a sign-out, ending every sign-in of the account and a
    push registration all take it first, so a registration either commits
    before the sign-in it names ends (and the end switches its device off) or
    sees that sign-in already ended and is refused, and a sign-in is either
    issued before an account-wide end (which then ends it) or sees the end.
    The returned row carries the account's current ``session_epoch``.
    """

    return (
        get_user_model()
        .objects.select_for_update()
        .only("pk", "session_epoch")
        .get(pk=user.pk)
    )
