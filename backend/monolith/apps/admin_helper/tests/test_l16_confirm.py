"""Plan L16: a prepared change is decided on the console, by its admin, once."""

from __future__ import annotations

from datetime import timedelta
from unittest import mock

from django.contrib.sessions.backends.db import SessionStore
from django.core.cache import cache
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.admin_helper import keys, prepared
from apps.admin_helper.models import AdminHelperKey, PreparedAction
from apps.admin_panel import worklist
from apps.admin_panel.models import AdminAuditLog
from apps.admin_panel.permissions import AdminRole, assign_admin_roles
from apps.admin_panel.tests.two_step_helpers import staff_login
from apps.disputes.models import Dispute
from apps.disputes.services import set_dispute_status
from apps.finance.jobs import HANDLERS
from apps.finance.models import ScheduledJob
from apps.trips.models import Journey

from .l16_support import API, REASON, change_url, confirm, post_action, reject
from .test_l15_keys import PAGES, set_helper_policy
from .test_l16_api import past
from .world import bearer, build_world, change_key, make_staff, new_key


@override_settings(**PAGES)
class ConfirmTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.world = build_world(prefix="l16-confirm")
        cls.owner = make_staff("confirm-owner@example.test", AdminRole.SUPER_ADMIN)

    def setUp(self):
        cache.clear()
        self.console = Client()
        staff_login(self.console, self.owner)
        self.plain = change_key(self.owner)

    def prepare(self, action="journey.pause", target_type="journey", target_id=None, params=None, plain=None):
        response = post_action(plain or self.plain, action, target_type,
                               target_id or self.world.journey.pk, params)
        assert response.status_code == 201, response.json()
        return PreparedAction.objects.get(pk=response.json()["id"])

    def journey(self) -> Journey:
        return Journey.objects.get(pk=self.world.journey.pk)

    # --- confirming ---------------------------------------------------------------------

    def test_confirming_runs_it_once_as_the_admin(self):
        change = self.prepare()
        response = confirm(self.console, change, "Paused after the traveler's call.")
        assert response.status_code == 302 and response["Location"] == change_url(change)
        change.refresh_from_db()
        assert change.status == PreparedAction.Status.CONFIRMED
        assert change.outcome["reason"] == "Paused after the traveler's call."
        assert self.journey().paused_by_staff
        audit = AdminAuditLog.objects.get(action="journey.paused")
        assert audit.actor_id == self.owner.pk and audit.reason == "Paused after the traveler's call."
        again = confirm(self.console, change)
        assert again.status_code == 302
        assert AdminAuditLog.objects.filter(action="journey.paused").count() == 1
        page = self.console.get(change_url(change)).content.decode()
        assert "This change is already decided: confirmed." in page
        assert 'name="decision" value="confirm"' not in page

    def test_the_reason_is_the_admins_own_and_required(self):
        change = self.prepare()
        page = self.console.get(change_url(change)).content.decode()
        assert REASON.replace("'", "&#x27;") in page  # pre-filled, editable
        assert confirm(self.console, change, "").status_code == 200
        change.refresh_from_db()
        assert change.status == PreparedAction.Status.WAITING

    def test_another_admin_can_neither_see_nor_decide_it(self):
        change = self.prepare()
        other = make_staff("confirm-other@example.test", AdminRole.SUPER_ADMIN)
        client = Client()
        staff_login(client, other)
        assert client.get(change_url(change)).status_code == 404
        assert confirm(client, change).status_code == 404
        assert reject(client, change).status_code == 404
        change.refresh_from_db()
        assert change.status == PreparedAction.Status.WAITING and self.journey().paused_at is None

    def test_confirming_needs_a_session_past_the_second_step(self):
        change = self.prepare()
        client = Client()
        client.force_login(self.owner)  # signed in, second step not passed
        response = confirm(client, change)
        assert response.status_code == 302 and "two-step" in response["Location"]
        # The service itself refuses too, whatever route reaches it.
        request = RequestFactory().post("/")
        request.user = self.owner
        request.session = SessionStore()
        with self.assertRaises(prepared.NotDecidable):
            prepared.confirm(request=request, action_id=change.pk, reason=REASON)
        change.refresh_from_db()
        assert change.status == PreparedAction.Status.WAITING and self.journey().paused_at is None

    def test_an_expired_change_cannot_be_confirmed(self):
        change = self.prepare()
        past(change.pk)
        confirm(self.console, change)
        change.refresh_from_db()
        assert change.status == PreparedAction.Status.EXPIRED
        assert self.journey().paused_at is None

    def test_a_record_that_changed_since_is_this_no_longer_applies(self):
        dispute = self.world.dispute
        change = self.prepare("dispute.set_status", "dispute", dispute.pk, {"status": "under_review"})
        set_dispute_status(dispute_id=dispute.pk, status=Dispute.Status.AWAITING_EVIDENCE,
                           admin_actor_id=self.owner.pk, note="Asked for photos.")
        page = self.console.get(change_url(change)).content.decode()
        assert "This no longer applies: the record changed after the AI helper prepared this change." in page
        confirm(self.console, change)
        change.refresh_from_db()
        assert change.status == PreparedAction.Status.FAILED
        assert change.outcome["code"] == prepared.CHANGED
        assert Dispute.objects.get(pk=dispute.pk).status == Dispute.Status.AWAITING_EVIDENCE
        failed = AdminAuditLog.objects.get(action="ai_helper.action_failed")
        assert failed.metadata["prepared_action"] == str(change.pk)
        assert not AdminAuditLog.objects.filter(action="dispute.status_changed", metadata__via="ai_helper").exists()

    def test_a_state_the_console_no_longer_offers_is_this_no_longer_applies(self):
        change = self.prepare()
        from apps.trips.services import pause_journey

        pause_journey(actor=self.owner, journey_id=self.world.journey.pk, reason="Paused by hand.")
        confirm(self.console, change)
        change.refresh_from_db()
        assert change.status == PreparedAction.Status.FAILED
        assert change.outcome["message"] == "This no longer applies: this journey cannot be paused now."

    def test_a_resolution_whose_money_differs_now_is_refused(self):
        dispute = self.world.dispute
        change = self.prepare("dispute.resolve", "dispute", dispute.pk, {"resolution": "full_sender_refund"})
        page = self.console.get(change_url(change)).content.decode()
        assert "The settlement engine computed these amounts again when this page opened." in page
        assert "Back to the sender" in page
        prepared_preview = change.basis["preview"]
        moved = {**prepared_preview, "sender_refund_eur_cents": prepared_preview["sender_refund_eur_cents"] - 1}
        with mock.patch("apps.admin_helper.actions._preview", return_value=moved):
            confirm(self.console, change)
        change.refresh_from_db()
        assert change.status == PreparedAction.Status.FAILED and change.outcome["code"] == prepared.CHANGED
        assert Dispute.objects.get(pk=dispute.pk).status == Dispute.Status.OPEN

    def test_an_admin_whose_role_changed_cannot_confirm(self):
        ops = make_staff("confirm-ops@example.test", AdminRole.OPS)
        client = Client()
        staff_login(client, ops)
        change = self.prepare(plain=change_key(ops))
        assign_admin_roles(ops, (AdminRole.SUPPORT,))
        confirm(client, change)
        change.refresh_from_db()
        assert change.status == PreparedAction.Status.FAILED
        assert change.outcome["message"] == "This no longer applies: your role no longer allows this change."
        assert self.journey().paused_at is None

    def test_a_refusal_while_running_is_failed_and_leaves_nothing(self):
        from apps.admin_panel.staff_actions import StaffActionError

        change = self.prepare()
        with mock.patch("apps.trips.services.pause_journey",
                        side_effect=StaffActionError("journey_locked", "The journey is locked.")):
            confirm(self.console, change)
        change.refresh_from_db()
        assert change.status == PreparedAction.Status.FAILED
        assert change.outcome == {"code": "journey_locked", "reason": REASON,
                                  "message": "This no longer applies: the journey is locked."}
        assert self.journey().paused_at is None
        # The audit context ended with the failure: the next console action is plain.
        self.console.post(reverse("admin_console:note-add", args=("deal", self.world.deal.pk)), {"body": "Plain."})
        assert "via" not in AdminAuditLog.objects.get(action="admin_note.added").metadata

    def test_a_console_action_right_after_a_helper_one_carries_no_marker(self):
        change = self.prepare()
        confirm(self.console, change)
        assert AdminAuditLog.objects.get(action="journey.paused").metadata["via"] == "ai_helper"
        self.console.post(reverse("admin_console:journey-pause", args=(self.world.journey.pk, "resume")),
                          {"reason": "Lifted by hand."})
        resumed = AdminAuditLog.objects.get(action="journey.resumed")
        assert "via" not in resumed.metadata and "prepared_action" not in resumed.metadata

    # --- rejecting and expiring -------------------------------------------------------------

    def test_rejecting_needs_no_reason_and_runs_nothing(self):
        change = self.prepare()
        assert reject(self.console, change).status_code == 302
        change.refresh_from_db()
        assert change.status == PreparedAction.Status.REJECTED and change.decided_at is not None
        assert self.journey().paused_at is None
        audit = AdminAuditLog.objects.get(action="ai_helper.action_rejected")
        assert audit.metadata["prepared_action"] == str(change.pk)
        confirm(self.console, change)
        change.refresh_from_db()
        assert change.status == PreparedAction.Status.REJECTED

    def test_the_expiry_job_closes_a_change_nobody_confirmed(self):
        change = self.prepare()
        job = ScheduledJob.objects.get(kind=ScheduledJob.Kind.ADMIN_HELPER_ACTION_EXPIRY)
        handler = HANDLERS[ScheduledJob.Kind.ADMIN_HELPER_ACTION_EXPIRY]
        assert handler(job.payload) == "not_due"
        past(change.pk)
        assert handler(job.payload) == "expired"
        assert handler(job.payload) == "already_closed"
        change.refresh_from_db()
        assert change.status == PreparedAction.Status.EXPIRED
        assert change.outcome == {"code": "expired", "message": "Nobody confirmed it in time."}

    # --- keys ------------------------------------------------------------------------------------

    def key_row(self, plain) -> AdminHelperKey:
        return AdminHelperKey.objects.get(key_hash=keys.digest(plain))

    def test_a_key_stopped_early_expires_its_waiting_changes(self):
        change = self.prepare()
        keys.stop_key(actor=self.owner, key_id=self.key_row(self.plain).pk)
        change.refresh_from_db()
        assert change.status == PreparedAction.Status.EXPIRED and change.outcome["code"] == "key_stopped"
        stopped = AdminAuditLog.objects.get(action="ai_helper.key_stopped")
        assert stopped.metadata["changes_expired"] == 1

    def test_a_replaced_key_leaves_its_changes_for_the_console(self):
        change = self.prepare()
        change_key(self.owner)  # replaces the key that prepared it
        assert self.key_row(self.plain).revoked_reason == AdminHelperKey.StopReason.REPLACED
        confirm(self.console, change)
        change.refresh_from_db()
        assert change.status == PreparedAction.Status.CONFIRMED

    def test_a_two_step_reset_and_the_switch_expire_waiting_changes(self):
        from apps.admin_panel.two_step import reset

        trust = make_staff("confirm-trust@example.test", AdminRole.TRUST)
        change = self.prepare("review.dismiss_report", "review_report", self.world.rating.pk, plain=change_key(trust))
        reset(actor=self.owner, target=trust, reason="Lost phone.")
        change.refresh_from_db()
        assert change.status == PreparedAction.Status.EXPIRED

        mine = self.prepare()
        revision = set_helper_policy(enabled=False)
        mine.refresh_from_db()
        assert mine.status == PreparedAction.Status.EXPIRED
        audit = AdminAuditLog.objects.get(action=keys.SWITCHED_OFF_ACTION, target_id=str(revision.pk))
        assert audit.metadata["changes_expired"] == 1

    def test_with_the_switch_off_the_list_is_read_only(self):
        change = self.prepare()
        set_helper_policy(enabled=False)
        # Even a change still marked waiting (say, a switch-off racing its
        # creation) cannot be decided while the helper is off.
        PreparedAction.objects.filter(pk=change.pk).update(
            status=PreparedAction.Status.WAITING, decided_at=None, outcome={}
        )
        page = self.console.get(reverse("admin_console:ai-helper")).content.decode()
        assert "The list is read only." in page and "Review and confirm" not in page
        detail = self.console.get(change_url(change)).content.decode()
        assert 'name="decision"' not in detail
        assert "The AI helper is switched off, so nothing it prepared can be confirmed." in detail
        confirm(self.console, change)
        change.refresh_from_db()
        assert change.status == PreparedAction.Status.WAITING and self.journey().paused_at is None

    # --- the console pages -----------------------------------------------------------------------

    def test_the_page_shows_the_server_summary_the_record_and_the_helpers_reason(self):
        change = self.prepare("refund.request", "payment", self.world.payment.pk,
                              {"amount_eur_cents": 250, "refund_reason": "admin"})
        page = self.console.get(reverse("admin_console:ai-helper")).content.decode()
        assert 'id="st-helper-waiting"' in page
        assert change.summary in page
        assert "Written by the AI helper, check it" in page
        assert reverse("admin_console:payment-detail", args=(self.world.payment.pk,)) in page
        assert "Amount to refund" in page and "€2.50" in page
        detail = self.console.get(change_url(change))
        assert detail.status_code == 200 and "no-store" in detail["Cache-Control"]
        assert "Confirm" in detail.content.decode() and "Reject" in detail.content.decode()

    def test_the_work_list_counts_the_admins_own_waiting_changes(self):
        self.prepare()
        other = make_staff("confirm-worklist@example.test", AdminRole.SUPER_ADMIN)
        self.prepare("review.dismiss_report", "review_report", self.world.rating.pk, plain=change_key(other))
        item = worklist.work_item("helper_changes", self.owner)
        assert item.count == 1 and item.queue_type is None
        assert item.url == f"{reverse('admin_console:ai-helper')}#st-helper-waiting"
        overview = self.console.get(reverse("admin_console:overview")).content.decode()
        assert "Changes waiting for your confirmation" in overview
        assert "A change waits for your confirmation" in overview
        briefing = Client().get(API + "briefing", **bearer(new_key(self.owner))).json()
        assert [row["count"] for row in briefing["items"] if row["code"] == "helper_changes"] == [1]
        queue = Client().get(API + "queues/helper_changes", **bearer(new_key(self.owner))).json()
        assert queue["count_only"] is True and queue["rows"] is None

    def test_the_card_creates_a_change_key_and_shows_it_once_with_its_expiry(self):
        response = self.console.post(reverse("admin_console:ai-helper-create"), {"kind": "change"})
        assert response.status_code == 200
        page = response.content.decode()
        line = page.split('id="st-helper-line" translate="no">', 1)[1].split("</code>", 1)[0]
        assert line.startswith("/wassla http://testserver/api/admin/helper/v1 wslw_")
        assert "It is your change key" in page and "It works until" in page
        key = AdminHelperKey.objects.filter(admin=self.owner, kind="change", revoked_at__isnull=True).get()
        assert key.expires_at - key.created_at == timedelta(minutes=30)
        assert self.console.post(reverse("admin_console:ai-helper-create"), {"kind": "admin"}).status_code == 404

    def test_a_change_key_needs_a_fresh_code(self):
        stale = timezone.now() - timedelta(minutes=11)
        from apps.admin_panel.tests.two_step_helpers import verify_session

        verify_session(self.console, self.owner, at=stale)
        response = self.console.post(reverse("admin_console:ai-helper-create"), {"kind": "change"})
        assert response.status_code == 302 and "two-step" in response["Location"]
