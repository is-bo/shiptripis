"""The email CTA reaches a real, one-use, account-bound browser contract."""

from unittest.mock import patch

import pytest
from django.test import Client, override_settings
from django.urls import resolve

from apps.accounts.models import User
from apps.admin_panel.models import AdminInvitation
from apps.admin_panel.services import create_admin_invitation
from apps.notifications.models import OutboundMessage
from apps.notifications.outbox import render_parts
from apps.admin_panel.tests.two_step_helpers import staff_login

URL = "/admin/invitations/accept?language=fr"


def invite(email="new-staff@example.invalid", language="fr"):
    actor = User.objects.create_superuser(
        username="inviter", email="owner@example.invalid", password=None
    )
    with override_settings(FRONTEND_BASE_URL="https://app.example.invalid"):
        return create_admin_invitation(
            actor=actor, email=email, role="support", communication_language=language
        )


@pytest.mark.django_db
@pytest.mark.parametrize("language", ["en", "fr", "ar"])
def test_invitation_cta_resolves_and_get_never_consumes_or_echoes_the_token(
    client, language
):
    row, token = invite(language=language)
    message = OutboundMessage.objects.get(key=f"admin_invitation:{row.pk}")
    _, text, _ = render_parts(message)
    assert f"?language={language}#token={token}" in text
    assert (
        resolve("/admin/invitations/accept").url_name == "admin-invitation-accept-page"
    )
    response = client.get(f"/admin/invitations/accept?language={language}")
    assert response.status_code == 200
    body = response.content.decode()
    assert token not in body
    assert f'lang="{language}"' in body
    assert 'dir="rtl"' in body if language == "ar" else 'dir="ltr"' in body
    assert response["Referrer-Policy"] == "no-referrer"
    assert "no-store" in response["Cache-Control"]
    assert "script-src 'nonce-" in response["Content-Security-Policy"]
    assert "history.replaceState" in body
    row.refresh_from_db()
    assert row.used_at is None


@pytest.mark.django_db
def test_browser_accepts_new_account_once_without_returning_credentials(client):
    row, token = invite()
    response = client.post(
        URL,
        {
            "token": token,
            "password": "Strong-invitation-482!",
            "full_name": "Operations Test",
        },
    )
    assert response.status_code == 200
    user = User.objects.get(email=row.email)
    assert user.is_staff and user.role == "admin"
    assert user.groups.filter(name="Support").exists()
    row.refresh_from_db()
    assert row.accepted_by == user and row.used_at
    assert token not in response.content.decode()
    assert "Strong-invitation-482!" not in response.content.decode()
    assert (
        client.post(
            URL, {"token": token, "password": "Strong-invitation-482!"}
        ).status_code
        == 400
    )


@pytest.mark.django_db
def test_existing_account_must_authenticate_and_keeps_its_password(client):
    existing = User.objects.create_user(
        username="existing",
        email="existing@example.invalid",
        password="Existing-secure-482!",
    )
    row, token = invite(email=existing.email)
    assert (
        client.post(URL, {"token": token, "password": "wrong-password"}).status_code
        == 400
    )
    row.refresh_from_db()
    assert row.used_at is None
    assert (
        client.post(
            URL, {"token": token, "password": "Existing-secure-482!"}
        ).status_code
        == 200
    )
    existing.refresh_from_db()
    assert existing.is_staff and existing.check_password("Existing-secure-482!")


@pytest.mark.django_db
def test_authenticated_other_account_cannot_accept_for_someone_else(client):
    existing = User.objects.create_user(
        username="invited",
        email="invited@example.invalid",
        password="Existing-secure-482!",
    )
    row, token = invite(email=existing.email)
    other = User.objects.create_user(
        username="other", email="other@example.invalid", password=None
    )
    staff_login(client, other)
    assert (
        client.post(
            URL, {"token": token, "password": "Existing-secure-482!"}
        ).status_code
        == 400
    )
    row.refresh_from_db()
    assert row.used_at is None
    other.refresh_from_db()
    assert not other.is_staff


@pytest.mark.django_db
def test_csrf_throttle_and_cache_failure_all_fail_closed():
    row, token = invite()
    assert (
        Client(enforce_csrf_checks=True)
        .post(URL, {"token": token, "password": "Strong-invitation-482!"})
        .status_code
        == 403
    )
    for decision, status in [(False, 429), (RuntimeError("private credential"), 503)]:
        with patch(
            "apps.admin_panel.invitation_web.ScopedRateThrottle.allow_request",
            **(
                {"side_effect": decision}
                if isinstance(decision, Exception)
                else {"return_value": decision}
            ),
        ):
            response = Client().post(
                URL, {"token": token, "password": "Strong-invitation-482!"}
            )
            assert response.status_code == status
            assert "private credential" not in response.content.decode()
    row.refresh_from_db()
    assert row.used_at is None


@pytest.mark.django_db
@pytest.mark.parametrize("state", ["revoked", "expired", "invalid"])
def test_invalid_capabilities_share_a_generic_failure(client, state):
    from django.utils import timezone
    from datetime import timedelta

    row, token = invite()
    if state == "revoked":
        AdminInvitation.objects.filter(pk=row.pk).update(revoked_at=timezone.now())
    elif state == "expired":
        # Preserve the owning model's created-before-expiry constraint.
        AdminInvitation.objects.filter(pk=row.pk).update(
            created_at=timezone.now() - timedelta(days=2),
            expires_at=timezone.now() - timedelta(days=1),
        )
    else:
        token = "unknown-private-invitation"
    response = client.post(URL, {"token": token, "password": "Strong-invitation-482!"})
    assert response.status_code == 400
    assert (
        "could not be accepted" not in response.content.decode()
    )  # explicit French, not header inference
    assert "L’invitation n’a pas pu être acceptée" in response.content.decode()
    assert not User.objects.filter(email=row.email).exists()
