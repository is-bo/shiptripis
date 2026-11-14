"""Plan L15: how the helper API authenticates, limits, records and answers."""

from __future__ import annotations

import uuid
from datetime import timedelta
from unittest import mock

from django.core.cache import cache
from django.db import connection
from django.test import Client, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import URLPattern, URLResolver, get_resolver, reverse
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import User
from apps.admin_helper import calls, tasks, urls as helper_urls
from apps.admin_helper.keys import KEY_INVALID_CODE
from apps.admin_helper.models import AdminHelperCall, AdminHelperKey
from apps.admin_panel import console_urls, worklist
from apps.admin_panel.permissions import ADMIN_PERMISSION_CODES, AdminRole, assign_admin_roles
from apps.admin_panel.staff_api import HELPER_API_ROUTES, OPEN_STAFF_API_ROUTES
from apps.admin_panel.tests.two_step_helpers import staff_login
from apps.finance.jobs import HANDLERS
from apps.finance.models import PaymentRefund, ScheduledJob

from .test_l15_keys import PAGES, set_helper_policy
from .world import bearer, build_world, make_staff, new_key

API = "/api/admin/helper/v1/"


def failed_job(index: int, *, hours_ago: int = 2) -> ScheduledJob:
    moment = timezone.now() - timedelta(hours=hours_ago, minutes=index)
    return ScheduledJob.objects.create(
        key=f"l15-failed-{uuid.uuid4().hex}",
        kind=ScheduledJob.Kind.OFFER_EXPIRY,
        payload={},
        run_at=moment,
        status=ScheduledJob.Status.FAILED,
        last_error_code="boom",
        completed_at=moment,
    )


class AuthenticationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.owner = make_staff("auth-owner@example.test", AdminRole.SUPER_ADMIN)
        self.plain = new_key(self.owner)
        self.client = Client()

    def assert_refused(self, response):
        assert response.status_code == 401, response.status_code
        assert response.json() == {
            "code": KEY_INVALID_CODE,
            "detail": "This key does not work. Create a new one on the AI helper card "
            "of the Wassla console.",
        }
        assert response["WWW-Authenticate"] == 'Bearer realm="wassla-ai-helper"'
        assert "no-store" in response["Cache-Control"]

    def test_only_the_authorization_header_carries_a_key(self):
        guide = API + "guide"
        assert self.client.get(guide, **bearer(self.plain)).status_code == 200
        self.assert_refused(self.client.get(guide))
        self.assert_refused(self.client.get(f"{guide}?key={self.plain}"))
        self.assert_refused(self.client.get(f"{guide}?access_token={self.plain}"))
        self.client.cookies["key"] = self.plain
        self.assert_refused(self.client.get(guide))
        for header in (
            f"Token {self.plain}",
            f"Bearer  {self.plain} extra",
            f"Bearer {self.plain[:-1]}",
            f"Bearer {self.plain}x",
            f"Bearer wslw_{self.plain[5:]}",
            "Bearer ",
            "Bearer é",
        ):
            self.assert_refused(Client().get(guide, HTTP_AUTHORIZATION=header))

    def test_a_console_session_or_a_member_token_is_refused(self):
        session = Client()
        staff_login(session, self.owner)
        token = f"Bearer {RefreshToken.for_user(self.owner).access_token}"
        for name in ("guide", "briefing", "tasks", "queues/jobs", "search?q=1"):
            self.assert_refused(session.get(API + name))
            self.assert_refused(Client().get(API + name, HTTP_AUTHORIZATION=token))

    def test_every_route_is_read_only(self):
        for method in ("post", "put", "patch", "delete", "options"):
            response = getattr(self.client, method)(API + "guide", **bearer(self.plain))
            assert response.status_code == 405, method

    def test_every_answer_is_json_whatever_accept_asks(self):
        # The browsable page would print the admin's email in its header, and
        # an unmatched Accept must not turn the 401 into something else.
        for accept in ("text/html", "application/xml", "*/*"):
            response = self.client.get(API + "guide", HTTP_ACCEPT=accept, **bearer(self.plain))
            assert response.status_code == 200, accept
            assert response["Content-Type"] == "application/json", accept
            assert self.owner.email not in response.content.decode(), accept
            self.assert_refused(self.client.get(API + "guide", HTTP_ACCEPT=accept))
            self.assert_refused(
                self.client.get(API + "guide", HTTP_ACCEPT=accept, HTTP_AUTHORIZATION="Bearer x")
            )

    def test_every_answer_is_no_store(self):
        for path in ("guide", "queues/nope", "records/nope/1", "search?q=%21"):
            response = self.client.get(API + path, **bearer(self.plain))
            assert response["Cache-Control"] == "no-store", path
            assert response["Pragma"] == "no-cache"

    def test_rights_are_read_on_every_call(self):
        finance = make_staff("auth-finance@example.test", AdminRole.FINANCE)
        plain = new_key(finance)
        record = API + "queues/refunds"
        assert self.client.get(record, **bearer(plain)).status_code == 200
        assign_admin_roles(finance, (AdminRole.SUPPORT,))
        assert self.client.get(record, **bearer(plain)).status_code == 403
        assign_admin_roles(finance, (AdminRole.FINANCE,))
        assert self.client.get(record, **bearer(plain)).status_code == 200
        for change in ({"is_banned": True}, {"is_active": False}, {"is_staff": False}):
            User.objects.filter(pk=finance.pk).update(**change)
            assert self.client.get(record, **bearer(plain)).status_code == 401, change
            User.objects.filter(pk=finance.pk).update(is_banned=False, is_active=True, is_staff=True)
            assert self.client.get(record, **bearer(plain)).status_code == 200


def _routes():
    def walk(patterns, base=""):
        for pattern in patterns:
            if isinstance(pattern, URLResolver):
                yield from walk(pattern.url_patterns, base + str(pattern.pattern))
            elif isinstance(pattern, URLPattern):
                yield base + str(pattern.pattern), pattern

    yield from walk(get_resolver().url_patterns)


@override_settings(**PAGES)
class KeyOpensNothingElseTests(TestCase):
    def setUp(self):
        cache.clear()
        self.owner = make_staff("else-owner@example.test", AdminRole.SUPER_ADMIN)
        self.plain = new_key(self.owner)

    def sample(self):
        """One route per API family (`api/<family>`) and per staff area, without arguments."""

        families = {}
        for route, pattern in _routes():
            if not route.startswith("api/") or route.startswith("api/admin/helper/"):
                continue
            if "<" in route or "(?P" in route:
                continue
            parts = route.split("/")
            family = "/".join(parts[:3]) if parts[1] == "admin" else parts[1]
            families.setdefault(family, "/" + route)
        return families

    def test_a_helper_key_adds_nothing_to_any_other_api_family(self):
        sample = self.sample()
        assert len(sample) > 15, sample
        for family, path in sample.items():
            anonymous = Client().get(path).status_code
            with_key = Client().get(path, **bearer(self.plain)).status_code
            assert with_key in (401, 403) or with_key == anonymous, (family, path, with_key)
            assert with_key != 200 or anonymous == 200, (family, path)

    def test_a_helper_key_opens_no_console_page(self):
        for path in ("/admin/", reverse("admin_console:ai-helper"), "/admin/accounts/user/"):
            anonymous = Client().get(path)
            response = Client().get(path, **bearer(self.plain))
            assert response.status_code == anonymous.status_code == 302, path
            assert response["Location"] == anonymous["Location"]


class RateLimitTests(TestCase):
    def setUp(self):
        cache.clear()
        set_helper_policy(requests_per_minute=10)
        self.admin = make_staff("rate-admin@example.test", AdminRole.OPS)

    def test_a_key_is_limited_per_minute_and_others_are_not(self):
        first, second = new_key(self.admin), new_key(make_staff("rate-b@example.test", AdminRole.OPS))
        moment = timezone.now().replace(second=5)
        with mock.patch("django.utils.timezone.now", return_value=moment):
            for _ in range(10):
                assert Client().get(API + "guide", **bearer(first)).status_code == 200
            limited = Client().get(API + "guide", **bearer(first))
            assert limited.status_code == 429
            assert limited.json() == {
                "code": "admin_helper_rate_limited",
                "detail": "Too many requests with this key. Wait one minute.",
            }
            assert int(limited["Retry-After"]) == 55
            assert Client().get(API + "guide", **bearer(second)).status_code == 200
        with mock.patch("django.utils.timezone.now", return_value=moment + timedelta(minutes=1)):
            assert Client().get(API + "guide", **bearer(first)).status_code == 200
        statuses = list(
            AdminHelperCall.objects.filter(key__key_hash__isnull=False, status=429).values_list(
                "status", flat=True
            )
        )
        assert statuses == [429]


class CallLogTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = make_staff("log-admin@example.test", AdminRole.OPS)
        self.plain = new_key(self.admin)

    def test_each_call_is_recorded_without_its_query_string(self):
        Client().get(API + "search?q=secret+words", **bearer(self.plain))
        Client().get(API + "records/deal/999999", **bearer(self.plain))
        Client().get(API + "guide")
        rows = list(AdminHelperCall.objects.order_by("at", "pk").values("method", "path", "status"))
        assert rows == [
            {"method": "GET", "path": "/api/admin/helper/v1/search", "status": 400},
            {"method": "GET", "path": "/api/admin/helper/v1/records/deal/999999", "status": 404},
        ]
        key = AdminHelperKey.objects.get(admin=self.admin)
        assert key.use_count == 2 and key.last_used_at is not None

    def test_each_day_with_calls_has_its_prune_job(self):
        Client().get(API + "guide", **bearer(self.plain))
        Client().get(API + "guide", **bearer(self.plain))
        day = timezone.now().date()
        job = ScheduledJob.objects.get(kind=ScheduledJob.Kind.ADMIN_HELPER_CALL_PRUNE)
        assert job.key == f"admin_helper_call_prune:{day.isoformat()}"
        assert job.run_at.date() == day + timedelta(days=31)
        assert job.kind in HANDLERS

    def test_pruning_removes_calls_older_than_30_days_only(self):
        key = AdminHelperKey.objects.get(admin=self.admin)
        now = timezone.now()
        old = AdminHelperCall.objects.create(key=key, method="GET", path="/x", status=200, at=now - timedelta(days=31))
        kept = AdminHelperCall.objects.create(key=key, method="GET", path="/y", status=200, at=now - timedelta(days=29))
        assert HANDLERS[ScheduledJob.Kind.ADMIN_HELPER_CALL_PRUNE]({"day": "x"}) == "deleted=1"
        assert not AdminHelperCall.objects.filter(pk=old.pk).exists()
        assert AdminHelperCall.objects.filter(pk=kept.pk).exists()
        assert calls.prune_calls(now=now + timedelta(days=2)) == 1


class AnswerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.world = build_world(prefix="l15-answers")

    def setUp(self):
        cache.clear()
        self.owner = make_staff("answer-owner@example.test", AdminRole.SUPER_ADMIN)
        self.plain = new_key(self.owner)

    def get(self, path, admin_plain=None):
        return Client().get(API + path, **bearer(admin_plain or self.plain))

    def test_unknown_things_are_404_and_bad_input_400(self):
        assert self.get("queues/nope").json()["code"] == "admin_helper_not_found"
        assert self.get("records/nope/1").status_code == 404
        assert self.get("records/deal/999999").status_code == 404
        for bad in ("limit=0", "limit=26", "limit=abc", "cursor=%%%", "cursor=WyJ4IiwxXQ"):
            response = self.get(f"queues/jobs?{bad}")
            assert response.status_code == 400, bad
            assert response.json()["code"] == "admin_helper_bad_request"
        for bad in ("", "Amina", "a@b.c", "1" * 13, "x" * 65):
            assert self.get(f"search?q={bad}").status_code == 400, bad

    def test_a_role_lost_during_a_queue_call_is_403(self):
        with mock.patch.object(worklist, "work_item", return_value=None):
            response = self.get("queues/jobs")
        assert response.status_code == 403
        assert response.json()["code"] == "admin_helper_forbidden"

    def test_the_gate_comes_before_the_lookup(self):
        support = make_staff("answer-support@example.test", AdminRole.SUPPORT)
        plain = new_key(support)
        for path in ("records/payment/999999", f"records/payment/{self.world.payment.pk}"):
            response = self.get(path, plain)
            assert response.status_code == 403, path
            assert response.json()["code"] == "admin_helper_forbidden"

    def test_search_answers_typed_links_only_for_what_the_admin_may_open(self):
        world = self.world
        body = self.get(f"search?q={world.request.tracking_number.lower()}").json()
        assert body["looked_for"] == "tracking_number"
        assert [(link["type"], link["id"]) for link in body["results"]] == [
            ("request", world.request.pk),
            ("deal", world.deal.pk),
        ]
        payout = self.get(f"search?q={world.payout.public_reference}").json()
        assert [link["type"] for link in payout["results"]] == ["payout"]
        support = new_key(make_staff("answer-support2@example.test", AdminRole.SUPPORT))
        hidden = self.get(f"search?q={world.payment.order.public_reference}", support).json()
        assert hidden == {"looked_for": "reference", "results": []}
        nobody = self.get("search?q=WSL-2222XXXX").json()
        assert nobody["results"] == []

    def test_links_to_a_record_the_admin_may_not_open_say_nothing(self):
        trust = new_key(make_staff("answer-trust@example.test", AdminRole.TRUST))
        dispute = self.get(f"records/dispute/{self.world.dispute.pk}", trust).json()
        assert dispute["deal"]["record"] is not None  # Trust sees deals.
        refund = Client().get(
            API + f"records/deal/{self.world.deal.pk}", **bearer(trust)
        ).json()
        assert refund["payout"] == {
            "type": "payout",
            "id": self.world.payout.pk,
            "label": None,
            "console_url": None,
            "record": None,
        }

    def test_queues_page_oldest_first_with_an_opaque_cursor(self):
        for index in range(29):
            failed_job(index)
        seen, cursor, pages = [], None, 0
        while True:
            body = self.get("queues/jobs?limit=25" + (f"&cursor={cursor}" if cursor else "")).json()
            assert body["count"] == 30
            seen.extend(row["id"] for row in body["rows"])
            pages += 1
            cursor = body["next_cursor"]
            if cursor is None:
                break
        assert pages == 2 and len(seen) == len(set(seen)) == 30
        waits = [
            ScheduledJob.objects.get(pk=pk).completed_at for pk in seen
        ]
        assert waits == sorted(waits)

    def test_the_guide_names_what_this_admin_may_read(self):
        support = new_key(make_staff("answer-support3@example.test", AdminRole.SUPPORT))
        guide = self.get("guide", support).json()
        assert guide["actions"] == []
        assert guide["roles"] == ["Support"]
        assert guide["key"]["kind"] == "read" and 0 < guide["key"]["minutes_left"] <= 480
        assert guide["api"] == "http://testserver/api/admin/helper/v1/"
        readable = {row["type"] for row in guide["may_read"]["records"]}
        assert readable == {"person", "request", "journey", "deal", "dispute", "problem"}
        queues = {row["code"]: row["count_only"] for row in guide["may_read"]["queues"]}
        # L16 adds "Changes waiting for your confirmation" to every work list:
        # the admin's own, a count and a link only.
        assert queues == {"disputes": False, "problems": False, "helper_changes": True}
        assert len(guide["rules"]) >= 5


class BriefingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.world = build_world(prefix="l15-brief")

    def setUp(self):
        cache.clear()

    @override_settings(**PAGES)
    def test_the_briefing_equals_the_overview_item_by_item(self):
        for role in (AdminRole.OPS, AdminRole.SUPPORT, AdminRole.FINANCE, AdminRole.TRUST, AdminRole.SUPER_ADMIN):
            admin = make_staff(f"brief-{role}@example.test", role)
            console = Client()
            staff_login(console, admin)
            overview = console.get(reverse("admin_console:overview"))
            rows = overview.context["attention"]
            body = Client().get(API + "briefing", **bearer(new_key(admin))).json()
            assert [(item["code"], item["count"]) for item in body["items"]] == [
                (row["code"], row["count"]) for row in rows if row["count"]
            ], role
            assert [item["code"] for item in body["clear"]] == [
                row["code"] for row in rows if not row["count"]
            ], role
            assert all(item["severity"] in ("urgent", "today") for item in body["items"])

    def test_raised_work_is_ordered_by_the_server(self):
        owner = make_staff("brief-owner@example.test", AdminRole.SUPER_ADMIN)
        body = Client().get(API + "briefing", **bearer(new_key(owner))).json()
        ranks = [worklist.SEVERITY_RANK[item["severity"]] for item in body["items"]]
        assert ranks == sorted(ranks)
        urgent = [item for item in body["items"] if item["severity"] == "urgent" and item["oldest_waiting_minutes"] is not None]
        waits = [item["oldest_waiting_minutes"] for item in urgent]
        assert waits == sorted(waits, reverse=True)
        assert body["system"]["jobs"]["failed_unresolved"] == 1
        assert {row["name"] for row in body["system"]["providers"]} >= {"Email"}

    def test_severity_is_a_fixed_rule(self):
        severity = worklist.Severity(worklist.TODAY, urgent_after=timedelta(hours=2))
        now = timezone.now()
        assert severity.level(0, None, now) == worklist.INFO
        assert severity.level(1, now - timedelta(hours=2), now) == worklist.TODAY
        assert severity.level(1, now - timedelta(hours=2, seconds=1), now) == worklist.URGENT
        assert {queue.code for queue in worklist.QUEUES} == set(worklist.CODES)


class QueryCountTests(TestCase):
    def setUp(self):
        cache.clear()
        self.owner = make_staff("count-owner@example.test", AdminRole.SUPER_ADMIN)
        self.finance = make_staff("count-finance@example.test", AdminRole.FINANCE)

    def count(self, plain, path) -> int:
        with CaptureQueriesContext(connection) as queries:
            response = Client().get(API + path, **bearer(plain))
        assert response.status_code == 200, response.content
        return len(queries.captured_queries)

    def refunds(self, attempt, how_many):
        for _ in range(how_many):
            PaymentRefund.objects.create(
                order=attempt.order,
                attempt=attempt,
                amount_eur_cents=1,
                provider=attempt.provider,
                idempotency_key=f"l15-count-{uuid.uuid4().hex}",
                reason=PaymentRefund.Reason.ADMIN,
                status=PaymentRefund.Status.PENDING,
                requires_manual_action=True,
                requested_by=self.finance,
            )

    def test_briefing_and_queues_cost_the_same_at_1_and_25_rows(self):
        world = build_world(prefix="l15-count")
        owner, finance = new_key(self.owner), new_key(self.finance)
        # Warm the per-process caches (content types, settings) first.
        self.count(owner, "briefing")
        self.count(finance, "queues/refunds")
        one = {
            "briefing": self.count(owner, "briefing"),
            "jobs": self.count(owner, "queues/jobs"),
            "refunds": self.count(finance, "queues/refunds"),
        }
        for index in range(24):
            failed_job(index)
        self.refunds(world.payment, 24)
        assert len(Client().get(API + "queues/refunds", **bearer(finance)).json()["rows"]) == 25
        twenty_five = {
            "briefing": self.count(owner, "briefing"),
            "jobs": self.count(owner, "queues/jobs"),
            "refunds": self.count(finance, "queues/refunds"),
        }
        assert one == twenty_five, (one, twenty_five)
        # The fixed cost, so a change that adds queries is a decision.
        assert twenty_five["briefing"] <= 40, twenty_five
        assert twenty_five["jobs"] <= 20 and twenty_five["refunds"] <= 22, twenty_five


class TaskCoverageTests(TestCase):
    def test_every_console_route_has_a_task_or_a_reason(self):
        routes = {pattern.name for pattern in console_urls.urlpatterns}
        covered = [name for task in tasks.TASKS for name in task.covers]
        assert len(covered) == len(set(covered)), "A console route is in two tasks."
        assert not set(covered) & set(tasks.NO_TASK)
        assert set(covered) | set(tasks.NO_TASK) == routes, (
            routes - set(covered) - set(tasks.NO_TASK),
            set(covered) | set(tasks.NO_TASK) - routes,
        )

    def test_each_task_starts_on_a_console_page_with_real_capabilities(self):
        codes = [task.code for task in tasks.TASKS]
        assert len(codes) == len(set(codes))
        for task in tasks.TASKS:
            assert task.route.startswith("admin_console:"), task.code
            reverse(task.route)
            assert task.permission and set(task.permission) <= set(ADMIN_PERMISSION_CODES), task.code
            # L16: the helper changes name their task (`actions.Action.task`);
            # a task no longer carries an action code of its own.
            assert task.asks and task.steps, task.code

    def test_the_answer_lists_only_what_the_role_may_do(self):
        cache.clear()
        support = make_staff("tasks-support@example.test", AdminRole.SUPPORT)
        body = Client().get(API + "tasks", **bearer(new_key(support))).json()
        listed = {task["code"] for task in body["tasks"]}
        assert {"see_my_work", "find_person", "follow_delivery", "decide_dispute"} <= listed
        assert not listed & {"settle_refund", "manage_staff", "change_settings", "export_finance"}
        assert all(task["console_url"].startswith("http://testserver/admin/") for task in body["tasks"])


class RouteInventoryTests(TestCase):
    def test_the_helper_routes_are_the_open_staff_routes_l14_names(self):
        names = {pattern.name for pattern in helper_urls.urlpatterns}
        assert names == HELPER_API_ROUTES
        assert HELPER_API_ROUTES <= OPEN_STAFF_API_ROUTES
        assert OPEN_STAFF_API_ROUTES - HELPER_API_ROUTES == {"admin-invitation-accept"}
        for route, pattern in _routes():
            if pattern.name in HELPER_API_ROUTES:
                assert route.startswith("api/admin/helper/v1/"), route
