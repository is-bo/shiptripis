"""J9.1: a ban revokes every administrative entry point immediately."""

from django.contrib import admin
from django.test import Client, TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.accounts.models import User

from ..permissions import (
    AdminRole,
    assign_admin_roles,
    has_admin_access,
    has_admin_permission,
    has_all_admin_permissions,
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
                browser.force_login(user)
                api = APIClient()
                api.credentials(
                    HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(user)}"
                )

                self.assertTrue(has_admin_permission(user, "view_dashboard"))
                self.assertEqual(browser.get("/admin/").status_code, 200)
                self.assertEqual(api.get(api_url).status_code, 200)

                # The live session and JWT were established before the ban.
                User.objects.filter(pk=user.pk).update(is_banned=True)
                user.refresh_from_db()
                self.assertFalse(has_admin_access(user))
                self.assertFalse(has_admin_permission(user, "view_dashboard"))
                self.assertFalse(has_all_admin_permissions(user, "view_dashboard"))

                for url in ("/admin/", console_url):
                    response = browser.get(url)
                    self.assertIn(response.status_code, (302, 403))
                    self.assertNotIn(b"ShipTrip Operations dashboard", response.content)

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
