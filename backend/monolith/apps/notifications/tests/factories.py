"""Sign-ins and push devices for tests, made the way the app makes them."""

from __future__ import annotations

from uuid import uuid4

from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.sessions import start_session
from apps.accounts.views import _tokens_for_user

from ..models import PushDevice


def signed_in(user) -> dict:
    """A live sign-in of ``user``: its tokens and its id (the ``sid`` claim)."""

    tokens = _tokens_for_user(user)
    return {**tokens, "sid": RefreshToken(tokens["refresh"])["sid"]}


def push_device(user, **fields) -> PushDevice:
    """A device registered by a live sign-in of ``user``."""

    fields.setdefault("installation_id", uuid4())
    fields.setdefault("token", f"fcm-token-{uuid4().hex}")
    fields.setdefault("platform", PushDevice.Platform.ANDROID)
    fields.setdefault("binding_sequence", 1)
    fields.setdefault("session", start_session(user))
    return PushDevice.objects.create(user=user, **fields)
