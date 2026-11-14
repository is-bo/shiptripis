"""Mark a test client's console session as past the staff second step (L14).

Plan L14: tests that are not about two-step sign-in use this, and no test turns
the gate off. It writes the same session value `two_step.mark_verified` writes,
in-process, so it needs database access and the client's own session; nothing
outside the process can do the same (the load probe in `backend/loadtest`
imports it for its console client, for the same reason).
"""

from __future__ import annotations

from django.utils import timezone

from apps.admin_panel.two_step import SESSION_KEY


def verified_session_value(user, *, at=None) -> dict:
    """The value `two_step.mark_verified` stores, for a session built in-process."""

    moment = at or timezone.now()
    return {"user": user.pk, "at": int(moment.timestamp())}


def verify_session(client, user, *, at=None) -> None:
    """Record that ``user`` passed the second step in ``client``'s session."""

    session = client.session
    session[SESSION_KEY] = verified_session_value(user, at=at)
    session.save()


def staff_login(client, user) -> None:
    """Sign ``user`` in to ``client`` and pass the second step.

    An `APIClient` forced to another user would skip the session altogether,
    so that is undone first.
    """

    if hasattr(client, "force_authenticate"):
        client.force_authenticate(None)
    client.force_login(user)
    verify_session(client, user)
