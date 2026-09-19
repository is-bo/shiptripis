"""J9.3 Admin disabled-feature and Finance snapshot failure states."""

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.admin_panel.permissions import AdminRole, assign_admin_roles
from apps.finance.control_plane import snapshot


STATIC_STORES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


def _admin(role, suffix):
    user = User.objects.create_user(
        username=f"j93-{suffix}@example.test",
        email=f"j93-{suffix}@example.test",
        password="Strong-pass-123!",
        full_name=f"J9.3 {suffix}",
        is_staff=True,
    )
    assign_admin_roles(
        user,
        (role,),
        elevate_super_admin=role == AdminRole.SUPER_ADMIN,
    )
    return user


@override_settings(STORAGES=STATIC_STORES)
class PayoutReviewFeatureFlagTests(TestCase):
    def _get(self, user, url):
        client = Client()
        client.force_login(user)
        return client.get(url)

    @override_settings(PAYOUT_PROFILES_ENABLED=True)
    def test_finance_and_super_open_the_enabled_review_queue(self):
        url = reverse("admin_console:payout-reviews")
        for role, suffix in (
            (AdminRole.FINANCE, "finance-enabled"),
            (AdminRole.SUPER_ADMIN, "super-enabled"),
        ):
            with self.subTest(role=role):
                response = self._get(_admin(role, suffix), url)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Payout method reviews")

    @override_settings(PAYOUT_PROFILES_ENABLED=False)
    def test_authorized_disabled_queue_and_detail_are_configuration_unavailable(self):
        for role, suffix in (
            (AdminRole.FINANCE, "finance-disabled"),
            (AdminRole.SUPER_ADMIN, "super-disabled"),
        ):
            operator = _admin(role, suffix)
            for url in (
                reverse("admin_console:payout-reviews"),
                reverse("admin_console:payout-review-detail", args=(uuid4(),)),
                reverse("admin_console:payout-review-evidence", args=(uuid4(),)),
            ):
                with self.subTest(role=role, url=url):
                    response = self._get(operator, url)
                    self.assertEqual(response.status_code, 503)
                    self.assertContains(
                        response,
                        "This deployment has payout profiles disabled",
                        status_code=503,
                    )
                    self.assertNotContains(response, "permission", status_code=503)

    @override_settings(PAYOUT_PROFILES_ENABLED=False)
    def test_unauthorized_role_is_still_denied_when_feature_is_disabled(self):
        response = self._get(
            _admin(AdminRole.SUPPORT, "support-disabled"),
            reverse("admin_console:payout-reviews"),
        )
        self.assertEqual(response.status_code, 403)


@override_settings(
    STORAGES=STATIC_STORES,
    FINANCE_DASHBOARD_ENABLED=True,
)
class FinanceSnapshotUnavailableTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.client.force_login(_admin(AdminRole.FINANCE, "finance-snapshot"))

    def _dashboard_with(self, connection_state):
        with patch.object(snapshot, "connection", connection_state):
            return self.client.get(reverse("admin_console:finance-dashboard"))

    def test_non_postgres_renders_controlled_unavailable_state(self):
        response = self._dashboard_with(
            SimpleNamespace(vendor="sqlite", in_atomic_block=False)
        )

        self.assertEqual(response.status_code, 503)
        self.assertContains(
            response, "Finance snapshot is temporarily unavailable", status_code=503
        )
        self.assertTrue(response.context["unavailable"])
        self.assertNotIn("as_of", response.context)

    def test_postgres_atomic_context_renders_controlled_unavailable_state(self):
        response = self._dashboard_with(
            SimpleNamespace(vendor="postgresql", in_atomic_block=True)
        )

        self.assertEqual(response.status_code, 503)
        self.assertTrue(response.context["unavailable"])

    def test_control_plane_api_returns_explicit_503_instead_of_runtime_error(self):
        with patch.object(
            snapshot,
            "connection",
            SimpleNamespace(vendor="sqlite", in_atomic_block=False),
        ):
            response = self.client.get(
                reverse("admin_console:finance-control-plane"),
                {"mode": "test"},
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json()["code"], "finance_snapshot_temporarily_unavailable"
        )


class FinancePostgresSnapshotContractTests(SimpleTestCase):
    def test_standalone_postgres_still_sets_repeatable_read_and_timeout(self):
        cursor = SimpleNamespace(execute=Mock())
        connection = SimpleNamespace(
            vendor="postgresql",
            in_atomic_block=False,
            cursor=lambda: nullcontext(cursor),
        )
        transactions = SimpleNamespace(atomic=lambda: nullcontext())

        with (
            patch.object(snapshot, "connection", connection),
            patch.object(snapshot, "transaction", transactions),
            snapshot.consistent_read(),
        ):
            pass

        self.assertEqual(
            [call.args[0] for call in cursor.execute.call_args_list],
            [
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY",
                "SET LOCAL statement_timeout = '10s'",
            ],
        )
