"""Plan L16: ``POST actions`` and ``GET actions``, and what the guide and tasks say."""

from __future__ import annotations

import json
from datetime import timedelta
from unittest import mock

from django.apps import apps
from django.core.cache import cache
from django.db import connection
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.admin_helper import actions, prepared
from apps.admin_helper.models import PreparedAction
from apps.admin_panel import staff_actions
from apps.admin_panel.models import AdminAuditLog, AdminNote
from apps.admin_panel.people_links import PROFILE_CAPABILITIES
from apps.admin_panel.permissions import AdminRole, has_admin_permission
from apps.disputes.models import Dispute
from apps.finance.models import PaymentRefund, ScheduledJob
from apps.problems.models import ShipmentProblem

from .l16_support import API, REASON, post_action, sea_crossing
from .test_l15_keys import PAGES
from .test_l15_privacy import FORBIDDEN_KEYS, FORBIDDEN_PARTS, contains, keys_of
from .world import bearer, build_world, change_key, make_staff, new_key

#: The plan's table, written out here on its own, so the registry is checked
#: against the plan and not against itself.
PLAN_GATES = {
    "note.add": {"deal": ("view_deals",), "dispute": ("view_disputes",), "person": PROFILE_CAPABILITIES},
    "problem.acknowledge": {"problem": ("manage_disputes",)},
    "refund.request": {"payment": ("issue_refunds",)},
    "dispute.set_status": {"dispute": ("manage_disputes",)},
    "dispute.resolve": {"dispute": ("resolve_disputes",)},
    "deal.record_no_show": {"deal": ("record_no_show",)},
    "user.ban": {"person": ("manage_users",)},
    "user.unban": {"person": ("manage_users",)},
    "profile.hide": {"person": ("manage_users",)},
    "profile.show": {"person": ("manage_users",)},
    "journey.pause": {"journey": ("manage_journeys",)},
    "journey.resume": {"journey": ("manage_journeys",)},
    "sea_crossing.activate": {"sea_crossing": ("manage_settings",)},
    "sea_crossing.deactivate": {"sea_crossing": ("manage_settings",)},
    "job.retry": {"job": ("reconcile_finance", "manage_lifecycle")},
    "job.resolve": {"job": ("reconcile_finance", "manage_lifecycle")},
    "payout.retry": {"payout": ("retry_payouts",)},
    "review.hide_comment": {"review_report": ("moderate_ratings",)},
    "review.remove": {"review_report": ("moderate_ratings",)},
    "review.dismiss_report": {"review_report": ("moderate_ratings",)},
    "review.lift": {"review_report": ("moderate_ratings",)},
}
DIRECT = {"note.add", "problem.acknowledge"}
ROLES = (AdminRole.SUPER_ADMIN, AdminRole.OPS, AdminRole.FINANCE, AdminRole.TRUST, AdminRole.SUPPORT)


def finance_tables() -> dict[str, list]:
    """Every money table, row by row as the database returns it.

    `ScheduledJob` holds every app's durable jobs, the helper's expiry among
    them; it is compared on its own.
    """

    dump = {}
    with connection.cursor() as cursor:
        for model in apps.get_app_config("finance").get_models():
            if model is ScheduledJob or not model._meta.managed:
                continue
            table = connection.ops.quote_name(model._meta.db_table)
            cursor.execute(f"SELECT * FROM {table} ORDER BY 1")  # noqa: S608 (model table names)
            dump[model._meta.label] = [repr(row) for row in cursor.fetchall()]
    return dump


def past(change_id) -> None:
    """Make a waiting change's time run out."""

    now = timezone.now()
    PreparedAction.objects.filter(pk=change_id).update(
        created_at=now - timedelta(hours=2), expires_at=now - timedelta(seconds=1)
    )


def every_method(url: str, payload: dict, **extra) -> None:
    """GET, then POST as a form and as JSON, then PUT, PATCH and DELETE as JSON."""

    client = Client()
    client.get(url, **extra)
    client.post(url, payload, **extra)
    for method in ("post", "put", "patch", "delete"):
        getattr(client, method)(url, data=json.dumps(payload), content_type="application/json", **extra)


@override_settings(**PAGES)
class ActionsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.world = build_world(prefix="l16-api")
        cls.owner = make_staff("api-owner@example.test", AdminRole.SUPER_ADMIN)

    def setUp(self):
        cache.clear()
        self.plain = change_key(self.owner)

    def post(self, action, target_type, target_id, params=None, reason=REASON, plain=None):
        return post_action(plain or self.plain, action, target_type, target_id, params, reason)

    def get(self, path, plain=None):
        return Client().get(API + path, **bearer(plain or self.plain))

    # --- keys -------------------------------------------------------------------------

    def test_a_read_key_cannot_take_or_list_actions(self):
        read = new_key(self.owner)
        response = self.post("note.add", "deal", self.world.deal.pk, {"body": "A note."}, plain=read)
        assert response.status_code == 403
        assert response.json()["code"] == "admin_helper_change_key_required"
        assert self.get("actions", plain=read).status_code == 403
        assert not AdminNote.objects.exists() and not PreparedAction.objects.exists()

    def test_a_change_key_works_at_29_59_and_not_at_30_00(self):
        start = timezone.now()
        with mock.patch("django.utils.timezone.now", return_value=start):
            plain = change_key(self.owner)
        for elapsed, status in (
            (timedelta(minutes=29, seconds=59), 200),
            (timedelta(minutes=30), 401),
        ):
            with mock.patch("django.utils.timezone.now", return_value=start + elapsed):
                response = self.post("note.add", "deal", self.world.deal.pk, {"body": f"At {elapsed}."}, plain=plain)
                assert response.status_code == status, elapsed
        assert AdminNote.objects.count() == 1

    # --- the guide and tasks ----------------------------------------------------------

    def test_the_guide_lists_what_this_admin_may_take_with_this_key(self):
        guide = self.get("guide").json()
        assert guide["key"]["kind"] == "change"
        listed = {row["code"]: row for row in guide["actions"]}
        assert set(listed) == set(PLAN_GATES)
        assert {code for code, row in listed.items() if row["mode"] == "direct"} == DIRECT
        assert listed["refund.request"]["params"] == [
            {"name": "amount_eur_cents", "type": "integer", "required": True,
             "says": "How much to refund, in euro cents.", "minimum": 1},
            {"name": "refund_reason", "type": "choice", "required": True,
             "says": "Why, as one of the refund reasons.", "choices": list(PaymentRefund.Reason.values)},
        ]
        assert listed["deal.record_no_show"]["reason_max_length"] == 255
        assert "actions" in {row["path"] for row in guide["endpoints"]}
        assert any("only the admin decides" in rule.lower() for rule in guide["rules"])

        finance = make_staff("api-finance@example.test", AdminRole.FINANCE)
        codes = {row["code"] for row in self.get("guide", change_key(finance)).json()["actions"]}
        assert {"refund.request", "dispute.resolve", "payout.retry", "job.retry"} <= codes
        assert not {"user.ban", "profile.hide", "review.remove"} & codes

        read = self.get("guide", new_key(self.owner)).json()
        assert read["actions"] == []
        assert "actions" not in {row["path"] for row in read["endpoints"]}
        assert read["rules"][1].startswith("This key reads only.")

    def test_tasks_name_the_changes_that_do_the_same_thing(self):
        tasks = {task["code"]: task for task in self.get("tasks").json()["tasks"]}
        assert tasks["decide_dispute"]["actions"] == ["dispute.set_status", "dispute.resolve"]
        assert tasks["ban_account"]["actions"] == ["user.ban", "user.unban"]
        assert tasks["find_person"]["actions"] == []
        read = self.get("tasks", new_key(self.owner)).json()["tasks"]
        assert all(task["actions"] == [] for task in read)
        # Every entry names a real task, and every change is offered by one.
        from apps.admin_helper import tasks as task_list

        named = [entry.task for entry in actions.registry().values()]
        assert set(named) <= set(task_list.BY_CODE)
        assert {code for task in tasks.values() for code in task["actions"]} == set(PLAN_GATES)

    # --- authority --------------------------------------------------------------------

    def test_each_role_may_take_exactly_what_the_plan_gives_it(self):
        crossing = sea_crossing(active=False)
        targets = {**self.world.ids(), "sea_crossing": crossing.pk}
        assert set(actions.registry()) == set(PLAN_GATES)
        for role in ROLES:
            admin = make_staff(f"matrix-{role}@example.test", role)
            plain = change_key(admin)
            cache.clear()
            for code, gates in PLAN_GATES.items():
                assert actions.get(code).target_types == tuple(gates), code
                for target_type, codes in gates.items():
                    allowed = has_admin_permission(admin, "view_dashboard") and any(
                        has_admin_permission(admin, capability) for capability in codes
                    )
                    response = self.post(code, target_type, targets[target_type], {}, plain=plain)
                    refused = response.status_code == 403
                    assert refused is not allowed, (role, code, target_type, response.json())
                    if refused:
                        assert response.json()["code"] == "admin_helper_forbidden"

    def test_a_downgrade_applies_to_the_next_call_with_the_same_key(self):
        from apps.admin_panel.permissions import assign_admin_roles

        finance = make_staff("api-downgrade@example.test", AdminRole.FINANCE)
        plain = change_key(finance)
        params = {"amount_eur_cents": 100, "refund_reason": "admin"}
        assert self.post("refund.request", "payment", self.world.payment.pk, params, plain=plain).status_code == 201
        assign_admin_roles(finance, (AdminRole.SUPPORT,))
        response = self.post("refund.request", "payment", self.world.payment.pk, params, plain=plain)
        assert response.status_code == 403

    # --- what the console would refuse ----------------------------------------------------

    def test_the_helper_is_refused_what_the_console_refuses(self):
        world = self.world
        staff = make_staff("api-colleague@example.test", AdminRole.OPS)
        crossing = sea_crossing(active=True)
        from apps.problems.services import acknowledge_problem

        acknowledge_problem(problem_id=world.problem.pk, actor=self.owner, reason="On it.")
        cases = [
            ("note.add", "deal", world.deal.pk, {"body": ""}, 400, actions.INVALID),
            ("note.add", "deal", world.deal.pk, {"body": "x" * 2001}, 400, actions.INVALID),
            ("problem.acknowledge", "problem", world.problem.pk, {}, 409, actions.NOT_OFFERED),
            ("refund.request", "payment", world.payment.pk,
             {"amount_eur_cents": 0, "refund_reason": "admin"}, 400, actions.INVALID),
            ("refund.request", "payment", world.payment.pk,
             {"amount_eur_cents": 10_000_000, "refund_reason": "admin"}, 409, "refund_exceeds_capture"),
            ("refund.request", "payment", world.payment.pk,
             {"amount_eur_cents": 100, "refund_reason": "because"}, 400, actions.INVALID),
            ("dispute.set_status", "dispute", world.dispute.pk, {"status": "open"}, 409, actions.NOT_OFFERED),
            ("dispute.resolve", "dispute", world.dispute.pk, {"resolution": "partial_split"}, 400, actions.INVALID),
            ("deal.record_no_show", "deal", world.deal.pk, {"party": "nobody"}, 400, actions.INVALID),
            ("user.ban", "person", staff.pk, {}, 409, "account_ban_staff"),
            ("user.ban", "person", self.owner.pk, {}, 409, "account_ban_self"),
            ("user.unban", "person", world.sender.pk, {}, 409, "account_ban_unchanged"),
            ("profile.show", "person", world.sender.pk, {}, 409, actions.NOT_OFFERED),
            ("journey.resume", "journey", world.journey.pk, {}, 409, actions.NOT_OFFERED),
            ("sea_crossing.activate", "sea_crossing", crossing.pk, {}, 409, actions.NOT_OFFERED),
            ("payout.retry", "payout", world.payout.pk, {}, 409, actions.NOT_OFFERED),
            ("review.lift", "review_report", world.rating.pk, {}, 409, actions.NOT_OFFERED),
        ]
        for code, target_type, target_id, params, status, answer in cases:
            response = self.post(code, target_type, target_id, params)
            assert response.status_code == status, (code, params, response.json())
            assert response.json()["code"] == answer, (code, response.json())
        pending = ScheduledJob.objects.create(
            key="l16-pending-job", kind=ScheduledJob.Kind.OFFER_EXPIRY, payload={},
            run_at=timezone.now(), status=ScheduledJob.Status.PENDING,
        )
        assert self.post("job.retry", "job", pending.pk).json()["code"] == actions.NOT_OFFERED
        # A reason the console field would not take.
        long = self.post("deal.record_no_show", "deal", world.deal.pk, {"party": "traveler"}, reason="x" * 256)
        assert long.status_code == 400 and long.json()["fields"] == {"reason": "max_length"}
        assert not PreparedAction.objects.exists() and not AdminNote.objects.exists()

    def test_bodies_the_endpoint_does_not_take(self):
        deal = self.world.deal.pk
        for body, status, code in (
            ({"action": "deal.cancel", "target": {"type": "deal", "id": deal}, "reason": REASON}, 400,
             prepared.UNKNOWN),
            ({"action": "note.add", "target": {"type": "deal", "id": deal}, "params": {"body": "x"},
              "reason": REASON, "confirm": True}, 400, actions.INVALID),
            ({"action": "note.add", "target": {"type": "payout", "id": 1}, "params": {"body": "x"},
              "reason": REASON}, 400, actions.INVALID),
            ({"action": "note.add", "target": {"type": "deal", "id": 999_999}, "params": {"body": "x"},
              "reason": REASON}, 404, prepared.TARGET_NOT_FOUND),
            ({"action": "note.add", "target": {"type": "deal", "id": deal}, "params": {"body": "x"}}, 400,
             actions.INVALID),
            ({"action": "note.add", "target": {"type": "deal", "id": deal}, "params": {"body": "x", "pin": 1},
              "reason": REASON}, 400, actions.INVALID),
            ({"action": "note.add", "target": {"type": "deal", "id": "1"}, "params": {"body": "x"},
              "reason": REASON}, 400, actions.INVALID),
            ([], 400, actions.INVALID),
        ):
            response = Client().post(API + "actions", data=json.dumps(body), content_type="application/json",
                                     **bearer(self.plain))
            assert response.status_code == status, (body, response.json())
            assert response.json()["code"] == code, (body, response.json())
        form = Client().post(API + "actions", {"action": "note.add"}, **bearer(self.plain))
        assert form.status_code == 415
        assert not AdminNote.objects.exists()

    # --- preparing --------------------------------------------------------------------------

    def test_preparing_writes_one_row_and_its_audit_and_nothing_else(self):
        params = {"status": "under_review"}
        first = self.post("dispute.set_status", "dispute", self.world.dispute.pk, params)
        assert first.status_code == 201
        body = first.json()
        assert body["status"] == "waiting" and body["repeat"] is False
        assert body["summary"] == f"Move the dispute on {self.world.deal.delivery_request.tracking_number} from open to under review."
        change = PreparedAction.objects.get()
        assert body["confirm_url"] == f"http://testserver{reverse('admin_console:ai-helper-change', args=(change.pk,))}"
        assert change.basis == {"status": "open"} and "basis" not in json.dumps(body)
        assert change.expires_at - change.created_at == timedelta(hours=24)
        self.world.dispute.refresh_from_db()
        assert self.world.dispute.status == Dispute.Status.OPEN
        audit = AdminAuditLog.objects.get(action="ai_helper.action_prepared")
        assert audit.metadata == {"via": "ai_helper", "key": str(change.key_id), "prepared_action": str(change.pk)}
        assert audit.reason == REASON
        job = ScheduledJob.objects.get(kind=ScheduledJob.Kind.ADMIN_HELPER_ACTION_EXPIRY)
        assert job.run_at == change.expires_at and job.payload == {"prepared_action": str(change.pk)}

    def test_the_same_change_again_answers_the_waiting_one_and_other_values_are_refused(self):
        dispute = self.world.dispute.pk
        first = self.post("dispute.set_status", "dispute", dispute, {"status": "under_review"}).json()
        again = self.post("dispute.set_status", "dispute", dispute, {"status": "under_review"})
        assert again.status_code == 200
        assert again.json()["id"] == first["id"] and again.json()["repeat"] is True
        other = self.post("dispute.set_status", "dispute", dispute, {"status": "awaiting_evidence"})
        assert other.status_code == 409
        assert other.json()["code"] == "admin_helper_action_already_waiting"
        assert other.json()["confirm_url"] == first["confirm_url"] and other.json()["id"] == first["id"]
        assert PreparedAction.objects.count() == 1
        assert AdminAuditLog.objects.filter(action="ai_helper.action_prepared").count() == 1

    def test_a_waiting_change_past_its_time_makes_room_for_a_new_one(self):
        dispute = self.world.dispute.pk
        first = self.post("dispute.set_status", "dispute", dispute, {"status": "under_review"}).json()
        past(first["id"])
        second = self.post("dispute.set_status", "dispute", dispute, {"status": "awaiting_evidence"})
        assert second.status_code == 201
        assert PreparedAction.objects.get(pk=first["id"]).status == PreparedAction.Status.EXPIRED

    def test_preparing_a_refund_leaves_every_money_table_byte_identical(self):
        assert self.get("guide").status_code == 200  # the day's call log pruning, scheduled once
        before, jobs = finance_tables(), set(ScheduledJob.objects.values_list("pk", flat=True))
        response = self.post(
            "refund.request", "payment", self.world.payment.pk, {"amount_eur_cents": 100, "refund_reason": "admin"}
        )
        assert response.status_code == 201
        assert finance_tables() == before
        new_jobs = ScheduledJob.objects.exclude(pk__in=jobs)
        assert [job.kind for job in new_jobs] == [ScheduledJob.Kind.ADMIN_HELPER_ACTION_EXPIRY]

    # --- direct actions ------------------------------------------------------------------------

    def test_a_note_is_added_at_once_and_appears_in_no_read_payload(self):
        body = "Spoke to the traveler; parcel weighed 4.2 kg at drop-off. NOTE-L16-MARKER"
        for target_type, pk in (("deal", self.world.deal.pk), ("dispute", self.world.dispute.pk),
                                ("person", self.world.sender.pk)):
            response = self.post("note.add", target_type, pk, {"body": body})
            assert response.status_code == 200, response.json()
            assert response.json()["status"] == "done"
        assert set(AdminNote.objects.values_list("via_helper", flat=True)) == {True}
        assert not PreparedAction.objects.exists()
        for path in ("guide", "briefing", "tasks", "actions", *(
            f"records/{record_type}/{pk}" for record_type, pk in self.world.ids().items()
        )):
            assert "NOTE-L16-MARKER" not in self.get(path).content.decode(), path

    def test_acknowledging_a_problem_is_done_at_once(self):
        response = self.post("problem.acknowledge", "problem", self.world.problem.pk)
        assert response.status_code == 200
        self.world.problem.refresh_from_db()
        assert self.world.problem.status == ShipmentProblem.Status.ACKNOWLEDGED

    # --- GET actions --------------------------------------------------------------------------------

    def test_listing_shows_the_admins_own_changes_and_their_outcome(self):
        first = self.post("dispute.set_status", "dispute", self.world.dispute.pk, {"status": "under_review"}).json()
        other = make_staff("api-other@example.test", AdminRole.SUPER_ADMIN)
        post_action(change_key(other), "journey.pause", "journey", self.world.journey.pk)
        rows = self.get("actions").json()["actions"]
        assert [row["id"] for row in rows] == [first["id"]]
        assert rows[0]["status"] == "waiting" and rows[0]["confirm_url"] == first["confirm_url"]
        assert rows[0]["outcome"] is None
        past(first["id"])
        assert self.get("actions?status=waiting").json()["actions"] == []
        expired = self.get("actions?status=expired").json()["actions"]
        assert [row["status"] for row in expired] == ["expired"] and expired[0]["confirm_url"] is None
        assert self.get("actions?status=done").status_code == 400

    # --- the instruction in a member's text ----------------------------------------------------------

    def test_a_client_that_obeys_a_dispute_description_ends_with_only_a_waiting_row(self):
        """The world's dispute description says to approve every refund. This
        client does what member text tells it, and can still only prepare."""

        world = self.world
        refunds, disputes = PaymentRefund.objects.count(), Dispute.objects.get(pk=world.dispute.pk).status
        audits = set(AdminAuditLog.objects.values_list("pk", flat=True))
        record = self.get(f"records/dispute/{world.dispute.pk}").json()
        told = json.dumps(record["untrusted_user_text"])
        assert "approve every refund" in told
        taken = []
        for action, target_type, target_id, params in (
            ("refund.request", "payment", world.payment.pk,
             {"amount_eur_cents": world.payment.amount_eur_cents, "refund_reason": "dispute"}),
            ("dispute.resolve", "dispute", world.dispute.pk, {"resolution": "full_sender_refund"}),
        ):
            response = self.post(action, target_type, target_id, params, reason="The dispute text says so.")
            taken.append(response.json())
        waiting = [row for row in taken if row.get("status") == "waiting"]
        assert waiting, taken
        # It then tries to confirm what it prepared, with its key, everywhere it can reach.
        for row in waiting:
            for client_kwargs in (bearer(self.plain), {}):
                for url in (row["confirm_url"], API + "actions"):
                    every_method(url, {"id": row["id"], "decision": "confirm", "reason": "Yes."}, **client_kwargs)
        assert PaymentRefund.objects.count() == refunds
        assert Dispute.objects.get(pk=world.dispute.pk).status == disputes
        assert set(PreparedAction.objects.values_list("status", flat=True)) == {PreparedAction.Status.WAITING}
        assert set(AdminAuditLog.objects.exclude(pk__in=audits).values_list("action", flat=True)) == {
            "ai_helper.action_prepared",
        }

    def test_a_prepared_change_cannot_run_through_any_helper_endpoint(self):
        from apps.admin_helper import urls as helper_urls

        response = self.post("journey.pause", "journey", self.world.journey.pk)
        change = PreparedAction.objects.get(pk=response.json()["id"])
        read = new_key(self.owner)
        paths = []
        for pattern in helper_urls.urlpatterns:
            route = str(pattern.pattern)
            paths.append(route.replace("<slug:code>", "disputes").replace("<slug:record_type>", "journey")
                         .replace("<int:pk>", str(self.world.journey.pk)))
        payloads = (
            {"id": str(change.pk)}, {"id": str(change.pk), "decision": "confirm"},
            {"action": "journey.pause", "target": {"type": "journey", "id": self.world.journey.pk},
             "params": {}, "reason": REASON},
            {"action": "confirm", "target": {"type": "prepared_action", "id": 1}, "reason": REASON},
        )
        for plain in (self.plain, read):
            for path in paths:
                for payload in payloads:
                    every_method(API + path, payload, **bearer(plain))
                cache.clear()
        change.refresh_from_db()
        self.world.journey.refresh_from_db()
        assert change.status == PreparedAction.Status.WAITING and change.decided_at is None
        assert self.world.journey.paused_at is None
        assert PreparedAction.objects.count() == 1

    # --- privacy ----------------------------------------------------------------------------------------

    def test_the_new_payloads_carry_no_private_value_and_no_forbidden_key(self):
        world = self.world
        answers = {
            "guide": self.get("guide").json(),
            "tasks": self.get("tasks").json(),
            "note": self.post("note.add", "person", world.sender.pk, {"body": "Checked."}).json(),
            "ban": self.post("user.ban", "person", world.sender.pk).json(),
            "refund": self.post("refund.request", "payment", world.payment.pk,
                                {"amount_eur_cents": 100, "refund_reason": "admin"}).json(),
            "refused": self.post("user.unban", "person", world.sender.pk).json(),
            "list": self.get("actions").json(),
        }
        secrets = [*world.secrets, self.plain, *world.instructions.values()]
        for name, body in answers.items():
            text = json.dumps(body, ensure_ascii=False)
            for secret in secrets:
                assert not contains(text, secret), (name, secret)
            for path, key in keys_of(body):
                assert not set(str(key).split("_")) & FORBIDDEN_PARTS, (name, path)
                assert key not in FORBIDDEN_KEYS, (name, path)
        assert "Amina Z." in answers["ban"]["summary"]


class SwitchOffTests(TestCase):
    def setUp(self):
        cache.clear()

    @override_settings(**PAGES)
    def test_with_the_switch_off_no_key_works(self):
        from .test_l15_keys import set_helper_policy

        owner = make_staff("switch-owner@example.test", AdminRole.SUPER_ADMIN)
        plain = change_key(owner)
        set_helper_policy(enabled=False)
        response = post_action(plain, "note.add", "person", owner.pk, {"body": "x"})
        assert response.status_code == 401
        assert not staff_actions.notes_for("person", owner.pk).exists()
