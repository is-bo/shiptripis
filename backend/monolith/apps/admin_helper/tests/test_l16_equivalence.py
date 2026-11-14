"""Plan L16: a change made through the helper is the console's own change.

For every registry entry, the same step is done twice from the same starting
point, rolled back in between: once on the console page an admin uses, once
by the helper (directly, or prepared and then confirmed on the console). The
two leave the same rows in every table and the same audit rows; only the
helper's audit rows carry ``{"via": "ai_helper", "key", "prepared_action"}``.
"""

from __future__ import annotations

import pytest
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.admin_helper import actions
from apps.admin_helper.models import PreparedAction
from apps.admin_panel import staff_actions
from apps.admin_panel.permissions import AdminRole
from apps.admin_panel.tests.two_step_helpers import staff_login
from apps.discovery.profiles import set_profile_hidden
from apps.ratings.moderation import decide
from apps.trips.services import pause_journey

from .l16_support import API, REASON, confirm, effect, post_action, sea_crossing
from .test_l15_keys import PAGES
from .world import build_world, change_key, make_staff

NOTE = "Called the traveler: the flight moved to 18:40, pickup unchanged."


@override_settings(**PAGES)
class SameAsTheConsoleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.world = build_world(prefix="l16-same")
        cls.owner = make_staff("same-owner@example.test", AdminRole.SUPER_ADMIN)

    def setUp(self):
        cache.clear()
        self.console = Client()
        staff_login(self.console, self.owner)
        self.key = change_key(self.owner)
        # The first call of the day schedules the call log's pruning: a row of
        # the helper's own, not of the action, so it is made before comparing.
        assert Client().get(API + "guide", HTTP_AUTHORIZATION=f"Bearer {self.key}").status_code == 200

    # --- the two ways ------------------------------------------------------------------

    def by_console(self, path: str, data: dict):
        def do():
            response = self.console.post(path, data)
            assert response.status_code in (200, 302), (path, response.status_code)
            if response.status_code == 200:
                body = response.content.decode()
                assert "errorlist" not in body, body[body.find("errorlist") - 400:][:900]

        return do

    def by_helper(self, action: str, target_type: str, target_id: int, params=None, reason=REASON):
        entry = actions.get(action)
        if entry.mode == actions.DIRECT:
            def do():
                response = post_action(self.key, action, target_type, target_id, params, reason)
                assert response.status_code == 200, response.json()

            return do
        response = post_action(self.key, action, target_type, target_id, params, reason)
        assert response.status_code == 201, response.json()
        prepared = PreparedAction.objects.get(pk=response.json()["id"])

        def do():
            response = confirm(self.console, prepared, reason)
            assert response.status_code == 302
            prepared.refresh_from_db()
            assert prepared.status == PreparedAction.Status.CONFIRMED, prepared.outcome

        self.prepared = prepared
        return do

    def assert_same(self, console_do, helper_do, *, helper_only=frozenset()):
        console = effect(console_do)
        helper = effect(helper_do)
        assert console["audit"], "The console step wrote no audit row."
        assert helper["counts"] == console["counts"]
        assert helper["audit"] == console["audit"]
        for label, rows in console["rows"].items():
            theirs = helper["rows"][label]
            if helper_only:
                theirs = [{k: v for k, v in row.items() if k not in helper_only} for row in theirs]
                rows = [{k: v for k, v in row.items() if k not in helper_only} for row in rows]
            assert theirs == rows, label
        prepared = getattr(self, "prepared", None)
        for metadata in console["metadata"]:
            assert "via" not in metadata, metadata
        for metadata in helper["metadata"]:
            assert metadata["via"] == "ai_helper", metadata
            assert metadata["key"] == str(self.key_row().pk)
            assert metadata["prepared_action"] == (str(prepared.pk) if prepared else None)
        return console, helper

    def key_row(self):
        from apps.admin_helper.keys import digest
        from apps.admin_helper.models import AdminHelperKey

        return AdminHelperKey.objects.get(key_hash=digest(self.key))

    # --- one test per registry entry ---------------------------------------------------

    def test_note_add(self):
        deal = self.world.deal
        console, helper = self.assert_same(
            self.by_console(reverse("admin_console:note-add", args=("deal", deal.pk)), {"body": NOTE}),
            # The helper's reason is the audit reason; the console uses the note itself.
            self.by_helper("note.add", "deal", deal.pk, {"body": NOTE}, reason=NOTE),
            helper_only={"via_helper"},
        )
        assert console["rows"]["admin_panel.AdminNote"][-1]["via_helper"] is False
        assert helper["rows"]["admin_panel.AdminNote"][-1]["via_helper"] is True

    def test_problem_acknowledge(self):
        problem = self.world.problem
        self.assert_same(
            self.by_console(
                reverse("admin_console:problem-detail", args=(problem.pk,)),
                {"action": "acknowledge", "acknowledge-reason": REASON},
            ),
            self.by_helper("problem.acknowledge", "problem", problem.pk),
        )

    def test_refund_request(self):
        payment = self.world.payment
        console, helper = self.assert_same(
            self.by_console(
                reverse("admin_console:refund-new", args=(payment.pk,)),
                {"amount_eur": "1.00", "reason": "admin", "confirm": "on"},
            ),
            self.by_helper(
                "refund.request", "payment", payment.pk,
                {"amount_eur_cents": 100, "refund_reason": "admin"},
            ),
        )
        assert console["counts"]["finance.PaymentRefund"] == 1
        # The console's audit reason stays the reason code; the admin's own
        # words are kept beside it (advisor, 2026-11-14).
        assert helper["metadata"][0]["confirmed_reason"] == REASON

    def test_dispute_set_status(self):
        dispute = self.world.dispute
        self.assert_same(
            self.by_console(
                reverse("admin_console:dispute-detail", args=(dispute.pk,)),
                {"action": "status", "status": "under_review", "note": REASON},
            ),
            self.by_helper("dispute.set_status", "dispute", dispute.pk, {"status": "under_review"}),
        )

    def test_dispute_resolve(self):
        dispute = self.world.dispute
        console, _helper = self.assert_same(
            self.by_console(
                reverse("admin_console:dispute-detail", args=(dispute.pk,)),
                {
                    "action": "confirm-resolution",
                    "resolution": "full_sender_refund",
                    "note": REASON,
                    "confirm_resolution": "yes",
                },
            ),
            self.by_helper("dispute.resolve", "dispute", dispute.pk, {"resolution": "full_sender_refund"}),
        )
        assert console["rows"]["disputes.Dispute"][-1]["status"] == "resolved"

    def test_deal_record_no_show(self):
        deal = self.world.deal
        self.assert_same(
            self.by_console(
                reverse("admin_console:deal-no-show", args=(deal.pk,)),
                {"party": "traveler", "note": REASON},
            ),
            self.by_helper("deal.record_no_show", "deal", deal.pk, {"party": "traveler"}),
        )

    def test_user_ban(self):
        person = self.world.sender
        self.assert_same(
            self.by_console(reverse("admin_console:user-ban", args=(person.pk,)), {"reason": REASON}),
            self.by_helper("user.ban", "person", person.pk),
        )

    def test_user_unban(self):
        person = self.world.sender
        staff_actions.set_account_ban(actor=self.owner, user_id=person.pk, banned=True, reason="Earlier ban.")
        self.assert_same(
            self.by_console(reverse("admin_console:user-ban", args=(person.pk,)), {"reason": REASON}),
            self.by_helper("user.unban", "person", person.pk),
        )

    def test_profile_hide(self):
        person = self.world.traveler
        self.assert_same(
            self.by_console(
                reverse("admin_console:user-profile-visibility", args=(person.pk,)), {"reason": REASON}
            ),
            self.by_helper("profile.hide", "person", person.pk),
        )

    def test_profile_show(self):
        person = self.world.traveler
        set_profile_hidden(user=person, actor=self.owner, hidden=True, reason="Earlier hide.")
        self.assert_same(
            self.by_console(
                reverse("admin_console:user-profile-visibility", args=(person.pk,)), {"reason": REASON}
            ),
            self.by_helper("profile.show", "person", person.pk),
        )

    def test_journey_pause(self):
        journey = self.world.journey
        self.assert_same(
            self.by_console(reverse("admin_console:journey-pause", args=(journey.pk, "pause")), {"reason": REASON}),
            self.by_helper("journey.pause", "journey", journey.pk),
        )

    def test_journey_resume(self):
        journey = self.world.journey
        pause_journey(actor=self.owner, journey_id=journey.pk, reason="Earlier pause.")
        self.assert_same(
            self.by_console(reverse("admin_console:journey-pause", args=(journey.pk, "resume")), {"reason": REASON}),
            self.by_helper("journey.resume", "journey", journey.pk),
        )

    def test_sea_crossing_activate(self):
        crossing = sea_crossing(active=False)
        self.assert_same(
            self.by_console(
                reverse("admin_console:sea-crossing-toggle", args=(crossing.pk, "activate")), {"reason": REASON}
            ),
            self.by_helper("sea_crossing.activate", "sea_crossing", crossing.pk),
        )

    def test_sea_crossing_deactivate(self):
        crossing = sea_crossing(active=True)
        self.assert_same(
            self.by_console(
                reverse("admin_console:sea-crossing-toggle", args=(crossing.pk, "deactivate")), {"reason": REASON}
            ),
            self.by_helper("sea_crossing.deactivate", "sea_crossing", crossing.pk),
        )

    def test_job_retry(self):
        job = self.world.job
        self.assert_same(
            self.by_console(reverse("admin_console:job-retry", args=(job.pk,)), {"reason": REASON, "confirm": "on"}),
            self.by_helper("job.retry", "job", job.pk),
        )

    def test_job_resolve(self):
        job = self.world.job
        self.assert_same(
            self.by_console(
                reverse("admin_console:job-resolve", args=(job.pk,)),
                {"resolution": "resolved", "reason": REASON, "confirm": "on"},
            ),
            self.by_helper("job.resolve", "job", job.pk, {"resolution": "resolved"}),
        )

    def review_console(self, decision: str):
        rating = self.world.rating
        return self.by_console(
            reverse("admin_console:review-detail", args=(rating.pk,)),
            {"action": decision, f"{decision}-reason": REASON},
        )

    def test_review_hide_comment(self):
        self.assert_same(
            self.review_console("hide_comment"),
            self.by_helper("review.hide_comment", "review_report", self.world.rating.pk),
        )

    def test_review_remove(self):
        self.assert_same(
            self.review_console("remove"),
            self.by_helper("review.remove", "review_report", self.world.rating.pk),
        )

    def test_review_dismiss_report(self):
        self.assert_same(
            self.review_console("dismiss"),
            self.by_helper("review.dismiss_report", "review_report", self.world.rating.pk),
        )

    def test_review_lift(self):
        decide(rating_id=self.world.rating.pk, actor=self.owner, action="hide_comment", reason="Earlier.")
        self.assert_same(
            self.review_console("lift"),
            self.by_helper("review.lift", "review_report", self.world.rating.pk),
        )

    def test_every_entry_is_compared(self):
        """``payout.retry`` is compared on a Stripe payout, in its own test below."""

        tested = {name.removeprefix("test_") for name in dir(self) if name.startswith("test_")}
        expected = {code.replace(".", "_") for code in actions.registry()} - {"payout_retry"}
        assert expected <= tested, expected - tested


# --- payout.retry, on a Stripe bank payout that failed ----------------------------------------


@pytest.mark.django_db
def test_payout_retry_is_the_console_retry(settings):
    from apps.finance.payout_reconciliation import reconcile_payout
    from apps.finance.tests.payout_execution_harness import (
        H3_SETTINGS,
        FakeConnect,
        authorise_auto_stripe,
        build_stripe_payout,
    )
    from apps.finance.payout_execution import execute_payout

    for name, value in {**H3_SETTINGS, **PAGES}.items():
        setattr(settings, name, value)
    cache.clear()
    authorise_auto_stripe(True)
    _scenario, payout, _account, _capture = build_stripe_payout(prefix="l16-payout")
    gateway = FakeConnect()
    for _ in range(2):
        execute_payout(payout.pk, gateway=gateway)
    gateway.payout_status = "failed"
    reconcile_payout(payout.pk, gateway=gateway)
    payout.refresh_from_db()
    assert payout.status == "failed"

    owner = make_staff("payout-owner@example.test", AdminRole.SUPER_ADMIN)
    console_client = Client()
    staff_login(console_client, owner)
    plain = change_key(owner)
    response = post_action(plain, "payout.retry", "payout", payout.pk)
    assert response.status_code == 201, response.json()
    prepared = PreparedAction.objects.get(pk=response.json()["id"])

    def by_console():
        reply = console_client.post(
            reverse("admin_console:payout-detail", args=(payout.pk,)),
            {"action": "retry_bank", "expected_state_version": payout.state_version},
        )
        assert reply.status_code == 302

    def by_helper():
        assert confirm(console_client, prepared).status_code == 302
        prepared.refresh_from_db()
        assert prepared.status == PreparedAction.Status.CONFIRMED, prepared.outcome

    console = effect(by_console)
    helper = effect(by_helper)
    assert console["audit"] and helper["counts"] == console["counts"]
    assert helper["audit"] == console["audit"]
    assert helper["rows"] == console["rows"]
    assert all(row["via"] == "ai_helper" for row in helper["metadata"])
    assert helper["metadata"][0]["confirmed_reason"] == REASON
    assert all("via" not in row for row in console["metadata"])
