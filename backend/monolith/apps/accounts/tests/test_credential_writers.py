"""N-D: credentials and privileges have named writers.

One function sets a password and ends every sign-in of the account
(`apps.accounts.sessions.write_password`); `session_epoch` has one writer
(`end_all_sessions`); every save of an existing user names its fields, the
technical admin's included, so a form or an instance read before a reset can
never write the old password hash or the old `session_epoch` back.
"""

from __future__ import annotations

import ast
import os
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.db.models.signals import pre_save
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient, APIRequestFactory

from apps.accounts.admin import ShipTripUserAdmin
from apps.accounts.models import PasswordResetCode
from apps.accounts.social import sign_in_with_identity
from apps.accounts.views import PasswordResetConfirmView
from apps.admin_panel.permissions import AdminRole
from apps.admin_panel.services import accept_admin_invitation, create_admin_invitation
from apps.admin_panel.tests.two_step_helpers import staff_login
from apps.notifications.tests.factories import signed_in

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


@contextmanager
def another_field_changes_meanwhile(user):
    """Commit a change of a field nobody here writes (``is_kyc_verified``)
    just before the first save of ``user``: the latest moment another request
    could change the row. A save of the whole row writes the old value back."""

    pk = user.pk
    done = []

    def change(sender, instance, **kwargs):
        if instance.pk == pk and not done:
            done.append(True)
            User.objects.filter(pk=pk).update(is_kyc_verified=True)

    pre_save.connect(change, sender=User, weak=False)
    try:
        yield
    finally:
        pre_save.disconnect(change, sender=User)
    assert done, "the operation saved no user row"
    assert User.objects.get(pk=pk).is_kyc_verified is True, "the concurrent change was written over"


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

    def test_a_change_writes_only_what_the_form_changed(self):
        with another_field_changes_meanwhile(self.member):
            response = self._post_change(_change_form(self.member, full_name="Renamed"))

        assert response.status_code == 302
        self.member.refresh_from_db()
        assert self.member.full_name == "Renamed"

    def test_a_post_cannot_change_a_staff_right(self):
        # Decision D5: staff rights change only in the console, with a reason
        # and an audit row.
        role = Group.objects.create(name="Some role")
        data = _change_form(self.member, is_staff="on", is_superuser="on", groups=[role.pk])
        del data["is_active"]

        response = self._post_change(data)

        assert response.status_code == 302
        self.member.refresh_from_db()
        assert (self.member.is_staff, self.member.is_superuser, self.member.is_active) == (
            False,
            False,
            True,
        )
        assert not self.member.groups.exists()
        page = self.client.get(f"/admin/accounts/user/{self.member.pk}/change/").content.decode()
        assert "change on the staff page of the operations console" in page

    def test_the_password_form_ends_every_sign_in(self):
        before = signed_in(self.member)
        url = f"/admin/accounts/user/{self.member.pk}/password/"

        with another_field_changes_meanwhile(self.member):
            response = self.client.post(url, {"password1": NEW, "password2": NEW})

        assert response.status_code == 302
        assert _refresh(before["refresh"]).status_code == 401
        assert _sign_in(self.member.email, NEW).status_code == 200
        assert _sign_in(self.member.email, OLD).status_code == 400
        assert User.objects.get(pk=self.member.pk).session_epoch == 1

    def test_disabling_the_password_in_the_form_ends_every_sign_in(self):
        before = signed_in(self.member)
        url = f"/admin/accounts/user/{self.member.pk}/password/"

        response = self.client.post(url, {"usable_password": "false", "unset-password": "1"})

        assert response.status_code == 302
        assert _refresh(before["refresh"]).status_code == 401
        assert User.objects.get(pk=self.member.pk).has_usable_password() is False


class NamedFieldSaveTests(TestCase):
    """Each converted save, with another field changed meanwhile."""

    def _member(self, email="named-member@example.com", **fields):
        return User.objects.create_user(
            username=email, email=email, password=OLD, full_name="Named", **fields
        )

    def test_a_password_reset(self):
        member = self._member()
        before = signed_in(member)
        with another_field_changes_meanwhile(member):
            _reset(member)
        assert _refresh(before["refresh"]).status_code == 401
        assert User.objects.get(pk=member.pk).is_email_verified is True

    def test_an_account_deletion(self):
        member = self._member()
        session = signed_in(member)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {session['access']}")
        with another_field_changes_meanwhile(member):
            assert client.post("/api/me/deletion", {"password": OLD}, format="json").status_code == 204
        deleted = User.objects.get(pk=member.pk)
        assert deleted.is_active is False
        assert deleted.has_usable_password() is False
        assert _refresh(session["refresh"]).status_code == 401

    def test_a_provider_claim_of_an_unconfirmed_account(self):
        member = self._member()
        before = signed_in(member)
        with another_field_changes_meanwhile(member):
            sign_in_with_identity(
                provider="google",
                subject="sub-named",
                email=member.email,
                email_verified=True,
                name="Real Owner",
                data={"preferred_language": "fr"},
            )
        claimed = User.objects.get(pk=member.pk)
        assert claimed.full_name == "Real Owner"
        assert claimed.has_usable_password() is False
        assert _refresh(before["refresh"]).status_code == 401

    @patch("apps.notifications.outbox.enqueue_secret_message")
    def test_an_invitation_accepted_by_an_existing_account(self, _enqueue):
        owner = User.objects.create_superuser(
            username="named-owner@example.com", email="named-owner@example.com", password=OLD
        )
        member = self._member("named-invitee@example.com")
        _, token = create_admin_invitation(actor=owner, email=member.email, role=AdminRole.OPS)
        with another_field_changes_meanwhile(member):
            accept_admin_invitation(plaintext_token=token, authenticated_user=member)
        assert User.objects.get(pk=member.pk).is_staff is True

    def test_the_bootstrap_command_on_an_existing_account(self):
        member = self._member("named-bootstrap@example.com")
        env = {
            "SHIPTRIP_SUPER_ADMIN_EMAIL": member.email,
            "SHIPTRIP_SUPER_ADMIN_PASSWORD": "Bootstrap-pass-123!",
        }
        with patch.dict(os.environ, env), another_field_changes_meanwhile(member):
            call_command("bootstrap_super_admin", verbosity=0)
        boot = User.objects.get(pk=member.pk)
        assert boot.is_superuser is True
        assert boot.check_password(OLD), "a rerun never changes a live password"


#: The one place each credential is written.
_WRITERS = {"password": "apps/accounts/sessions.py", "session_epoch": "apps/accounts/sessions.py"}


def _production_files():
    root = Path(settings.BASE_DIR)
    for path in sorted(root.glob("apps/**/*.py")) + sorted(root.glob("config/**/*.py")):
        parts = path.relative_to(root).parts
        if "tests" in parts or "migrations" in parts:
            continue
        yield path.relative_to(root).as_posix(), ast.parse(path.read_text())


def _credential_writes(tree) -> set[str]:
    """Which of ``password`` and ``session_epoch`` this module writes."""

    written = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in ("set_password", "set_unusable_password"):
                written.add("password")
            if node.func.attr == "update":
                written |= {kw.arg for kw in node.keywords} & set(_WRITERS)
            for kw in node.keywords:
                if kw.arg == "update_fields":
                    written |= {
                        n.value for n in ast.walk(kw.value) if isinstance(n, ast.Constant)
                    } & set(_WRITERS)
        if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            written |= {
                t.attr for t in targets if isinstance(t, ast.Attribute)
            } & set(_WRITERS)
    return written


class CredentialWriterScanTests(SimpleTestCase):
    def test_password_and_session_epoch_are_written_only_by_their_writers(self):
        found = {
            (name, path)
            for path, tree in _production_files()
            for name in _credential_writes(tree)
            if _WRITERS[name] != path
        }
        assert found == set()

    def test_the_scan_sees_each_kind_of_write(self):
        for source in (
            "user.set_password(raw)",
            "user.set_unusable_password()",
            "User.objects.filter(pk=1).update(session_epoch=2)",
            "user.save(update_fields=('password', 'email'))",
            "user.session_epoch = 3",
        ):
            assert _credential_writes(ast.parse(source)), source
        assert _credential_writes(ast.parse("user.session_epoch == 3")) == set()
