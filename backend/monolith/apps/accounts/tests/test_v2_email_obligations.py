"""Account capabilities and their durable email obligations must commit together."""

from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.accounts.models import EmailVerificationCode, PasswordResetCode, User
from apps.notifications.models import OutboundMessage, OutboundSecret


@pytest.mark.django_db
def test_signup_rolls_back_the_account_and_capability_if_outbox_creation_fails(client):
    with patch(
        "apps.accounts.views.enqueue_secret_message",
        side_effect=RuntimeError("outbox unavailable"),
    ):
        with pytest.raises(RuntimeError, match="outbox unavailable"):
            client.post(
                "/api/auth/sign-up",
                {
                    "full_name": "Local account",
                    "email": "signup@example.invalid",
                    "password": "Strong-account-482!",
                    "phone": "+213555123456",
                    "preferred_language": "ar",
                },
            )
    assert not User.objects.filter(email="signup@example.invalid").exists()
    assert not EmailVerificationCode.objects.exists()
    assert not OutboundMessage.objects.exists() and not OutboundSecret.objects.exists()


@pytest.mark.django_db
def test_reset_issuance_rolls_back_capability_if_outbox_creation_fails(client):
    user = User.objects.create_user(
        username="reset", email="reset@example.invalid", password=None
    )
    with patch(
        "apps.accounts.views.enqueue_secret_message",
        side_effect=RuntimeError("outbox unavailable"),
    ):
        with pytest.raises(RuntimeError, match="outbox unavailable"):
            client.post("/api/auth/password/reset/request", {"email": user.email})
    assert not PasswordResetCode.objects.filter(user=user).exists()
    assert not OutboundMessage.objects.exists() and not OutboundSecret.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize("same_timestamp", [False, True])
def test_successful_newer_reset_cannot_reactivate_an_older_unused_code(
    client, same_timestamp
):
    user = User.objects.create_user(
        username="reset", email="reset@example.invalid", password=None
    )
    with patch("apps.accounts.models.secrets.randbelow", side_effect=[123456, 654321]):
        _, old_code = PasswordResetCode.issue(user)
        _, new_code = PasswordResetCode.issue(user)
    if same_timestamp:
        PasswordResetCode.objects.filter(user=user).update(created_at=timezone.now())
    request = {"email": user.email, "new_password": "Strong-new-password-482!"}
    assert (
        client.post(
            "/api/auth/password/reset/confirm", {**request, "code": new_code}
        ).status_code
        == 204
    )
    assert (
        client.post(
            "/api/auth/password/reset/confirm", {**request, "code": old_code}
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/auth/password/reset/confirm", {**request, "code": new_code}
        ).status_code
        == 400
    )
    assert OutboundMessage.objects.filter(kind="security_event").count() == 1
