"""J9.1: a ban revokes every administrative entry point immediately."""

from django.contrib import admin
from django.test import Client, TestCase, override_settings
from rest_framework.test import APIClient

from apps.accounts.models import User

from ..permissions import (
    AdminRole,
    assign_admin_roles,
    has_admin_access,
    has_admin_permission,
    has_all_admin_permissions,
)
from apps.admin_panel.tests.two_step_helpers import staff_login


@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        },
    }
)
class BannedAdminAccessTests(TestCase):
    def test_ban_revokes_console_direct_urls_api_and_django_admin(self):
        cases = (
            (AdminRole.SUPER_ADMIN, "/admin/staff/", "/api/admin/roles"),
            (
                AdminRole.FINANCE,
                "/admin/finance/payments/",
                "/api/admin/payment-orders",
            ),
            (AdminRole.TRUST, "/admin/verification/kyc/", "/api/admin/kyc"),
        )
        for role, console_url, api_url in cases:
            with self.subTest(role=role):
                user = User.objects.create_user(
                    email=f"j91-{role}@example.test",
                    username=f"j91-{role}@example.test",
                    password="Strong-pass-123!",
                    full_name="J9.1 Admin",
                    is_staff=True,
                )
                assign_admin_roles(
                    user,
                    (role,),
                    elevate_super_admin=role == AdminRole.SUPER_ADMIN,
                )
                browser = Client()
                staff_login(browser, user)
                # Since L14 the staff API answers only inside a console session
                # past the second step; a bearer token opens no staff route.
                api = APIClient()
                staff_login(api, user)

                self.assertTrue(has_admin_permission(user, "view_dashboard"))
                self.assertEqual(browser.get("/admin/").status_code, 200)
                self.assertEqual(api.get(api_url).status_code, 200)

                # The live sessions were established before the ban.
                User.objects.filter(pk=user.pk).update(is_banned=True)
                user.refresh_from_db()
                self.assertFalse(has_admin_access(user))
                self.assertFalse(has_admin_permission(user, "view_dashboard"))
                self.assertFalse(has_all_admin_permissions(user, "view_dashboard"))

                for url in ("/admin/", console_url):
                    response = browser.get(url)
                    self.assertIn(response.status_code, (302, 403))
                    self.assertNotIn("Wassla Operations dashboard".encode("utf-8"), response.content)

                if role == AdminRole.FINANCE:
                    # This route uses the staff-only decorator rather than
                    # capability_required and must share the ban boundary.
                    self.assertIn(
                        browser.get("/admin/finance/dashboard/").status_code,
                        (302, 403),
                    )

                # The Django model admin and the staff-only technical route
                # cannot bypass the capability decorator.
                self.assertFalse(
                    admin.site.has_permission(type("R", (), {"user": user})())
                )
                if role == AdminRole.SUPER_ADMIN:
                    for url in ("/admin/technical/", "/admin/auth/group/"):
                        self.assertIn(browser.get(url).status_code, (302, 403))

                response = api.get(api_url)
                self.assertEqual(response.status_code, 403)
                self.assertNotIn("results", response.data)
