"""P3A, spec 21: staff remove a member's profile photo from the person page.

`moderate_profile_photos` only, granted where ID review is. A reason is
required, the member is shown it, and the removal writes `AdminAuditLog` with
actor, target, before, after and reason. The form names the photo version the
operator saw, so a photo the member replaced meanwhile is never removed.
"""

from __future__ import annotations

from unittest import mock

from django.contrib.auth.models import Group
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape

from apps.accounts.models import ProfilePhoto
from apps.accounts.photos import AUDIT_REMOVED, MODERATE_PERMISSION
from apps.admin_helper.tests.test_l15_keys import PAGES
from apps.admin_helper.tests.world import make_staff
from apps.admin_panel.models import AdminAuditLog
from apps.admin_panel.permissions import (
    ROLE_GROUP_NAMES,
    ROLE_PERMISSIONS,
    AdminRole,
    has_admin_permission,
)
from apps.admin_panel.tests.two_step_helpers import staff_login
from apps.core.storage import ObjectStore, make_key, storage_for

REASON = "P3A: the picture shows another person's ID card."


def give_photo(user, version="v-p3a-console") -> ProfilePhoto:
    return ProfilePhoto.objects.create(
        user=user,
        bucket=storage_for("media").require_bucket(),
        object_key=make_key("profile-photos", "jpg"),
        bytes=2048,
        version=version,
        uploaded_at=timezone.now(),
    )


@override_settings(**PAGES)
class PhotoRemovalTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from apps.accounts.models import User

        cls.member = User.objects.create_user(
            email="p3a-member@example.com",
            username="p3a-member@example.com",
            password="Pw-p3a-12345",
            full_name="Nadia Kaci",
        )
        cls.trust = make_staff("p3a-trust@example.test", AdminRole.TRUST)

    def setUp(self):
        self.photo = give_photo(self.member)
        self.client = Client()
        staff_login(self.client, self.trust)
        self.url = reverse("admin_console:user-photo-remove", args=(self.member.pk,))
        self.page = reverse("admin_console:user-detail", args=(self.member.pk,))
        deleter = mock.patch.object(ObjectStore, "delete")
        self.deleted = deleter.start()
        self.addCleanup(deleter.stop)

    def test_the_person_page_shows_the_photo_and_the_action(self):
        html = self.client.get(self.page).content.decode()
        assert 'class="st-person-avatar st-person-photo"' in html
        assert self.photo.object_key in html
        assert self.url in html and ">Remove photo<" in html
        assert "Shown to everyone" in html

    def test_the_form_shows_the_photo_and_carries_its_version(self):
        html = self.client.get(self.url).content.decode()
        assert self.photo.object_key in html
        assert f'value="{self.photo.version}"' in html
        assert "The member sees this reason" in html

    def test_removal_is_audited_and_the_member_sees_the_reason(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(self.url, {"version": self.photo.version, "reason": REASON})
        assert response.status_code == 302 and response["Location"] == self.page
        photo = ProfilePhoto.objects.get(user=self.member)
        assert photo.state == ProfilePhoto.State.REMOVED
        assert photo.removed_by == self.trust and photo.removed_reason == REASON
        self.deleted.assert_called_once_with(self.photo.object_key)
        entry = AdminAuditLog.objects.get(action=AUDIT_REMOVED)
        assert entry.actor == self.trust
        assert (entry.target_type, entry.target_id) == ("accounts.user", str(self.member.pk))
        assert entry.before == {"state": "active", "version": self.photo.version}
        assert entry.after == {"state": "removed", "version": self.photo.version}
        assert entry.reason == REASON
        # The after state on the person page, and on the person's Audit tab.
        html = self.client.get(self.page).content.decode()
        assert "Removed by Wassla" in html and escape(REASON) in html
        assert "st-person-photo" not in html and ">Remove photo<" not in html
        audit = self.client.get(self.page + "?tab=audit").content.decode()
        assert escape(REASON) in audit

    def test_a_reason_is_required(self):
        response = self.client.post(self.url, {"version": self.photo.version, "reason": "  "})
        assert response.status_code == 200
        assert ProfilePhoto.objects.get(user=self.member).state == ProfilePhoto.State.ACTIVE
        assert not AdminAuditLog.objects.filter(action=AUDIT_REMOVED).exists()

    def test_a_photo_replaced_after_the_page_opened_is_not_removed(self):
        ProfilePhoto.objects.filter(pk=self.photo.pk).update(version="v-p3a-newer")
        response = self.client.post(self.url, {"version": self.photo.version, "reason": REASON})
        assert response.status_code == 302 and response["Location"] == self.url
        photo = ProfilePhoto.objects.get(user=self.member)
        assert photo.state == ProfilePhoto.State.ACTIVE and photo.version == "v-p3a-newer"
        assert not AdminAuditLog.objects.filter(action=AUDIT_REMOVED).exists()
        self.deleted.assert_not_called()

    def test_without_the_permission_nothing_is_offered_or_allowed(self):
        for role in (AdminRole.OPS, AdminRole.SUPPORT, AdminRole.FINANCE):
            with self.subTest(role):
                staff = make_staff(f"p3a-{role}@example.test", role)
                client = Client()
                staff_login(client, staff)
                assert client.get(self.url).status_code == 403
                response = client.post(self.url, {"version": self.photo.version, "reason": REASON})
                assert response.status_code == 403
                page = client.get(self.page)
                if page.status_code == 200:
                    assert ">Remove photo<" not in page.content.decode()
        assert ProfilePhoto.objects.get(user=self.member).state == ProfilePhoto.State.ACTIVE

    def test_a_member_cannot_reach_the_console_action(self):
        client = Client()
        client.force_login(self.member)
        response = client.post(self.url, {"version": self.photo.version, "reason": REASON})
        assert response.status_code == 302 and "/login/" in response["Location"]
        assert ProfilePhoto.objects.get(user=self.member).state == ProfilePhoto.State.ACTIVE
        assert not AdminAuditLog.objects.exists()


class PermissionMatrixTests(TestCase):
    def test_photo_moderation_is_granted_exactly_where_id_review_is(self):
        reviewing = {role for role, codes in ROLE_PERMISSIONS.items() if "review_kyc" in codes}
        moderating = {role for role, codes in ROLE_PERMISSIONS.items() if MODERATE_PERMISSION in codes}
        assert moderating == reviewing == {AdminRole.TRUST, AdminRole.SUPER_ADMIN}
        # The migration seeded the same groups.
        seeded = set(
            Group.objects.filter(permissions__codename=MODERATE_PERMISSION).values_list(
                "name", flat=True
            )
        )
        assert {ROLE_GROUP_NAMES[role] for role in moderating} <= seeded
        trust = make_staff("p3a-matrix-trust@example.test", AdminRole.TRUST)
        ops = make_staff("p3a-matrix-ops@example.test", AdminRole.OPS)
        assert has_admin_permission(trust, MODERATE_PERMISSION)
        assert not has_admin_permission(ops, MODERATE_PERMISSION)
