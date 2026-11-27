"""N-D: credentials and privileges have named writers.

One function sets a password and ends every sign-in of the account
(`apps.accounts.sessions.set_password`); `session_epoch` has one writer
(`end_all_sessions`); every save of an existing user names its fields, the
technical admin's included, so a form or an instance read before a reset can
never write the old password hash or the old `session_epoch` back.
"""

from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient, APIRequestFactory

from apps.accounts.admin import ShipTripUserAdmin
from apps.accounts.models import PasswordResetCode
from apps.accounts.views import PasswordResetConfirmView
from apps.admin_panel.tests.two_step_helpers import staff_login

User = get_user_model()

SIGN_IN = reverse("auth-sign-in")
REFRESH = reverse("auth-refresh")
RESET = reverse("auth-password-reset-confirm")
OLD = "Old-password-123!"
NEW = "New-password-456!"

UNHASHED_STATIC = override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        },
    }
)


def _sign_in(email: str, password: str):
    return APIClient().post(SIGN_IN, {"email": email, "password": password}, format="json")


def _refresh(token: str):
    return APIClient().post(REFRESH, {"refresh": token}, format="json")


def _reset(user, password: str = NEW) -> None:
    """A completed password reset, through its own view, in this process."""

    _, code = PasswordResetCode.issue(user)
    request = APIRequestFactory().post(
        RESET, {"email": user.email, "code": code, "new_password": password}, format="json"
    )
    assert PasswordResetConfirmView.as_view()(request).status_code == 204


def _change_form(user, **changes) -> dict:
    """The technical admin's change form for ``user`` as an operator posts it."""

    joined = timezone.localtime(user.date_joined)
    data = {
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "email": user.email,
        "full_name": user.full_name,
        "phone": user.phone,
        "wilaya": user.wilaya,
        "role": user.role,
        "date_joined_0": joined.strftime("%Y-%m-%d"),
        "date_joined_1": joined.strftime("%H:%M:%S"),
        "last_login_0": "",
        "last_login_1": "",
    }
    for flag in (
        "is_active",
        "is_staff",
        "is_superuser",
        "is_phone_verified",
        "is_email_verified",
        "is_kyc_verified",
    ):
        if getattr(user, flag):
            data[flag] = "on"
    data.update(changes)
    return data


@UNHASHED_STATIC
class TechnicalAdminSaveTests(TestCase):
    def setUp(self):
        self.operator = User.objects.create_superuser(
            username="writer-ops@example.com",
            email="writer-ops@example.com",
            password="Sup3rStrong!",
        )
        staff_login(self.client, self.operator)
        self.member = User.objects.create_user(
            username="writer-member@example.com",
            email="writer-member@example.com",
            password=OLD,
            full_name="A Member",
        )

    def _post_change(self, data):
        return self.client.post(f"/admin/accounts/user/{self.member.pk}/change/", data)

    def test_a_form_read_before_a_reset_keeps_the_new_password_and_epoch(self):
        # N1 round 5, blocker 1: the change form loads the member, a reset
        # commits (new password, every sign-in ended, epoch moved), and only
        # then does the form save. A full-row save wrote the old hash and the
        # old epoch back: the old password worked again, the new one did not.
        before = _sign_in(self.member.email, OLD)
        assert before.status_code == 200
        real_get_object = ShipTripUserAdmin.get_object

        def read_then_reset(model_admin, request, object_id, from_field=None):
            obj = real_get_object(model_admin, request, object_id, from_field)
            if request.method == "POST":
                _reset(User.objects.get(pk=obj.pk))
            return obj

        with patch.object(ShipTripUserAdmin, "get_object", read_then_reset):
            response = self._post_change(_change_form(self.member, full_name="Renamed"))

        assert response.status_code == 302, response.content[:2000]
        self.member.refresh_from_db()
        assert self.member.full_name == "Renamed"
        assert self.member.session_epoch == 1
        after = _sign_in(self.member.email, NEW)
        assert after.status_code == 200
        assert _refresh(after.data["refresh"]).status_code == 200
        assert _sign_in(self.member.email, OLD).status_code == 400
        assert _refresh(before.data["refresh"]).status_code == 401
