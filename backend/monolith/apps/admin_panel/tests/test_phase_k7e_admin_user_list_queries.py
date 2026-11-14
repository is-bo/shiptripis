"""Phase K7-E — `GET /api/admin/users` costs the same at N and 2N rows.

K7 package B measured 54 queries for one page: `AdminUserSerializer` called
`user_admin_roles()` per row, and its `user.groups.filter(...)` bypassed the
view's `prefetch_related("groups")`. The serializer now reads the prefetched
groups. These tests pin the flat count and that every row's `admin_roles` is
still exactly what `user_admin_roles()` answers for that user.
"""

from __future__ import annotations

from django.contrib.auth.models import Group
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APITestCase

from apps.admin_panel.tests.two_step_helpers import staff_login
from apps.accounts.models import User

from ..permissions import AdminRole, assign_admin_roles, user_admin_roles
from .test_phase6a_admin import make_user

ROLE_ROTATION = (
    (),
    (AdminRole.OPS,),
    (AdminRole.SUPPORT, AdminRole.FINANCE),
    (AdminRole.TRUST,),
)


class AdminUserListQueryCountTests(APITestCase):
    def setUp(self):
        self.actor = make_user("k7e-super@example.test", staff=True)
        assign_admin_roles(
            self.actor, (AdminRole.SUPER_ADMIN,), elevate_super_admin=True
        )
        # A group that is not a Phase 6A role must never surface as one.
        self.unrelated_group = Group.objects.create(name="K7-E newsletter")
        staff_login(self.client, self.actor)
        self.created = 0

    def grow_to(self, total: int) -> None:
        for index in range(self.created, total):
            roles = ROLE_ROTATION[index % len(ROLE_ROTATION)]
            user = make_user(f"k7e-user-{index}@example.test", staff=bool(roles))
            if roles:
                assign_admin_roles(user, roles)
            if index % 3 == 0:
                user.groups.add(self.unrelated_group)
        self.created = max(self.created, total)

    def measure(self) -> tuple[int, dict]:
        self.client.get("/api/admin/users")
        with CaptureQueriesContext(connection) as captured:
            response = self.client.get("/api/admin/users")
        self.assertEqual(response.status_code, 200, response.data)
        return len(captured.captured_queries), response.json()

    def test_page_cost_is_flat_from_n_to_2n_users(self):
        self.grow_to(8)
        n_queries, n_body = self.measure()
        self.assertEqual(n_body["count"], 9)

        self.grow_to(16)
        two_n_queries, two_n_body = self.measure()
        self.assertEqual(two_n_body["count"], 17)

        self.assertEqual(n_queries, two_n_queries)

    def test_admin_roles_match_the_authoritative_lookup_on_every_row(self):
        self.grow_to(12)
        _queries, body = self.measure()
        seen_roles = set()
        for row in body["results"]:
            expected = list(user_admin_roles(User.objects.get(pk=row["id"])))
            self.assertEqual(row["admin_roles"], expected, row["email"])
            seen_roles.add(tuple(expected))
        # The world really covers none, one, several and the super-admin case.
        self.assertIn((), seen_roles)
        self.assertIn((AdminRole.FINANCE, AdminRole.SUPPORT), seen_roles)
        self.assertIn((AdminRole.SUPER_ADMIN,), seen_roles)

    def test_detail_admin_roles_are_unchanged(self):
        self.grow_to(4)
        user = User.objects.get(email="k7e-user-2@example.test")
        response = self.client.get(f"/api/admin/users/{user.pk}")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            response.json()["admin_roles"], [AdminRole.FINANCE, AdminRole.SUPPORT]
        )
