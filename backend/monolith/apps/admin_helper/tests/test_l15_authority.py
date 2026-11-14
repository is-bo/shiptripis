"""Plan L15 authority: the helper answers exactly when the console page would.

For each role (and a staff account with no role), each record type, each
queue and each overall endpoint, the helper's answer (200 or 403) is compared
with the same admin's console page that it mirrors (200 or 403).
"""

from __future__ import annotations

from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.admin_helper.resources import REGISTRY
from apps.admin_panel import worklist
from apps.admin_panel.permissions import AdminRole
from apps.admin_panel.tests.two_step_helpers import staff_login

from .test_l15_keys import PAGES
from .world import bearer, build_world, make_staff, new_key

API = "/api/admin/helper/v1/"
ROLES = (
    AdminRole.OPS,
    AdminRole.SUPPORT,
    AdminRole.FINANCE,
    AdminRole.TRUST,
    AdminRole.SUPER_ADMIN,
    None,
)


@override_settings(**PAGES)
class AuthorityMatrixTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.world = build_world(prefix="l15-matrix")

    def setUp(self):
        cache.clear()

    def pair(self, role):
        admin = make_staff(f"matrix-{role or 'none'}@example.test", role)
        console = Client()
        staff_login(console, admin)
        return admin, console, new_key(admin)

    def allowed(self, console, url) -> bool:
        status = console.get(url).status_code
        assert status in (200, 403), (url, status)
        return status == 200

    def helper(self, plain, path) -> bool:
        status = Client().get(API + path, **bearer(plain)).status_code
        assert status in (200, 403), (path, status)
        return status == 200

    def test_records_answer_exactly_when_their_console_page_opens(self):
        answered = {}
        for role in ROLES:
            _admin, console, plain = self.pair(role)
            for record_type, pk in self.world.ids().items():
                resource = REGISTRY[record_type]
                obj = resource.queryset().get(pk=pk)
                page = resource.console_path(obj)
                helper = self.helper(plain, f"records/{record_type}/{pk}")
                assert helper == self.allowed(console, page), (role, record_type)
                answered[(role, record_type)] = helper
        # The matrix is not trivially all-yes or all-no.
        assert answered[(AdminRole.SUPER_ADMIN, "payout")] is True
        assert answered[(AdminRole.SUPPORT, "payout")] is False
        assert answered[(AdminRole.FINANCE, "review_report")] is False
        assert answered[(AdminRole.TRUST, "review_report")] is True
        assert not any(answered[(None, record_type)] for record_type in REGISTRY)

    @override_settings(PAYOUT_PROFILES_ENABLED=True)  # The payout method queue's page.
    def test_queues_answer_exactly_when_their_console_page_opens(self):
        for role in ROLES:
            admin, console, plain = self.pair(role)
            for queue in worklist.QUEUES:
                page = reverse(queue.route)
                helper = self.helper(plain, f"queues/{queue.code}")
                assert helper == self.allowed(console, page), (role, queue.code)

    def test_the_overall_endpoints_answer_exactly_when_the_overview_opens(self):
        for role in ROLES:
            _admin, console, plain = self.pair(role)
            overview = self.allowed(console, reverse("admin_console:overview"))
            for path in ("guide", "briefing", "tasks", f"search?q={self.world.sender.pk}"):
                assert self.helper(plain, path) == overview, (role, path)

    def test_a_role_downgrade_applies_to_the_next_call(self):
        from apps.admin_panel.permissions import assign_admin_roles

        admin, _console, plain = self.pair(AdminRole.TRUST)
        path = f"records/review_report/{self.world.rating.pk}"
        assert self.helper(plain, path) is True
        assign_admin_roles(admin, (AdminRole.SUPPORT,))
        assert self.helper(plain, path) is False
