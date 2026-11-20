"""Reporting a chat message and blocking a person (store readiness, App Store 1.2).

Members report a message they received and block the other party from the
chat (`apps.chat.moderation`, `apps.accounts.blocks`). Staff decide reports in
the console, with an audited reason; a removed message is never shown to a
member again. A block closes the chat both ways and stops new proposals and
"I can carry this"; a funded delivery goes on.
"""

from __future__ import annotations

from datetime import timedelta

from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import UserBlock
from apps.admin_panel import worklist
from apps.admin_panel.models import AdminAuditLog
from apps.admin_panel.tests.two_step_helpers import staff_login
from apps.chat.models import ChatMessage, ChatMessageReport
from apps.core.tests.l10_world import DRIVE, AcceptanceWorld, api
from apps.discovery.tests.support import STATIC_STORES


@override_settings(STORAGES=STATIC_STORES)
class ReportAndBlockTests(AcceptanceWorld, TestCase):
    def setUp(self):
        cache.clear()
        self.build_acceptance_world()
        depart = self.now + timedelta(hours=4)
        self.journey = self.post_trip(
            [self.leg_payload(DRIVE, self.algiers, self.setif, depart, hours=3)]
        )
        self.publish(self.journey)
        leg = self.journey.legs.get()
        self.depart = depart
        parcel = self.open_parcel()
        self.deal = self.accept(self.propose(parcel, self.journey, leg, leg, 3_000))
        self.pay_balance(self.deal)
        self.match = self.deal.match

    def open_parcel(self):
        parcel = self.post_parcel(
            self.algiers,
            self.setif,
            ready_from=self.depart - timedelta(hours=2),
            ready_until=self.depart + timedelta(minutes=30),
            deliver_by=self.depart + timedelta(hours=12),
        )
        self.pay_deposit(parcel)
        return parcel

    def send(self, user, body="Hello"):
        return api(user).post(
            reverse("chat-messages", args=(self.match.pk,)),
            {"body": body},
            format="json",
        )

    def report(self, user, message_id, **body):
        return api(user).post(
            reverse("chat-message-report", args=(message_id,)),
            {"reason": "harassment", **body},
            format="json",
        )

    def eligibility(self, user):
        return (
            api(user)
            .get(reverse("matches-chat-eligibility", args=(self.match.pk,)))
            .data
        )

    def thread_row(self, user):
        rows = api(user).get(reverse("chat-threads")).data["results"]
        return next(row for row in rows if row["match_id"] == self.match.pk)

    def history(self, user):
        return (
            api(user)
            .get(reverse("chat-messages", args=(self.match.pk,)))
            .data["results"]
        )

    # -- reporting -------------------------------------------------------------

    def test_the_recipient_reports_a_message_once(self):
        message_id = self.send(self.traveler, "Pay me cash or else").data["id"]

        first = self.report(self.sender, message_id, note="Threatening me")
        again = self.report(self.sender, message_id, reason="spam")

        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.data["id"], first.data["id"])
        report = ChatMessageReport.objects.get()
        self.assertEqual(
            (report.reason, report.note, report.status),
            ("harassment", "Threatening me", "open"),
        )
        # Reporting alone does not block.
        self.assertFalse(UserBlock.objects.exists())

    def test_nobody_reports_their_own_message_or_one_they_cannot_read(self):
        message_id = self.send(self.traveler).data["id"]
        own = self.report(self.traveler, message_id)
        self.assertEqual(own.status_code, 400)
        self.assertEqual(own.data["code"], "report_own_message")
        stranger = self.person("stranger@example.com")
        self.assertEqual(self.report(stranger, message_id).status_code, 403)
        bad = self.report(self.sender, message_id, reason="boring")
        self.assertEqual(bad.status_code, 400)
        self.assertFalse(ChatMessageReport.objects.exists())

    # -- blocking --------------------------------------------------------------

    def test_report_and_block_closes_the_chat_both_ways_and_unblock_reopens_it(self):
        message_id = self.send(self.traveler).data["id"]
        self.assertEqual(
            self.report(self.sender, message_id, block=True).status_code, 201
        )
        self.assertTrue(
            UserBlock.objects.filter(
                blocker=self.sender, blocked=self.traveler
            ).exists()
        )

        for user in (self.traveler, self.sender):
            refused = self.send(user, "Still there?")
            self.assertEqual(refused.status_code, 403)
            self.assertEqual(refused.data["reason"], "blocked")
        self.assertEqual(ChatMessage.objects.count(), 1)

        self.assertEqual(
            self.eligibility(self.sender),
            {
                "eligible": False,
                "reason": "blocked",
                "match_id": self.match.pk,
                "blocked_by_me": True,
            },
        )
        self.assertFalse(self.eligibility(self.traveler)["blocked_by_me"])
        sender_row = self.thread_row(self.sender)
        self.assertEqual(
            (sender_row["can_send"], sender_row["blocked_by_me"]), (False, True)
        )
        traveler_row = self.thread_row(self.traveler)
        self.assertEqual(
            (traveler_row["can_send"], traveler_row["blocked_by_me"]), (False, False)
        )
        # The conversation stays readable to both.
        self.assertEqual(len(self.history(self.traveler)), 1)

        # Only the blocker can lift the block.
        api(self.traveler).delete(reverse("match-block", args=(self.match.pk,)))
        self.assertEqual(self.send(self.sender).status_code, 403)
        listed = api(self.sender).get(reverse("my-blocks")).data["results"]
        self.assertEqual([row["user_id"] for row in listed], [self.traveler.pk])
        self.assertEqual(
            api(self.sender)
            .delete(reverse("my-block", args=(self.traveler.pk,)))
            .status_code,
            204,
        )
        self.assertEqual(self.send(self.sender).status_code, 201)
        self.assertTrue(self.eligibility(self.traveler)["eligible"])

    def test_blocking_from_the_thread_is_idempotent_and_for_parties_only(self):
        url = reverse("match-block", args=(self.match.pk,))
        self.assertEqual(api(self.traveler).post(url).status_code, 204)
        self.assertEqual(api(self.traveler).post(url).status_code, 204)
        self.assertEqual(UserBlock.objects.count(), 1)
        stranger = self.person("stranger@example.com")
        self.assertEqual(api(stranger).post(url).status_code, 403)
        self.assertEqual(UserBlock.objects.count(), 1)

    def test_a_block_stops_i_can_carry_this(self):
        parcel = self.open_parcel()
        api(self.sender).post(reverse("match-block", args=(self.match.pk,)))
        refused = api(self.traveler).post(
            reverse("discovery-request-interest", args=(parcel.pk,)),
            {"journey_id": self.journey.pk},
            format="json",
        )
        self.assertEqual(refused.status_code, 403, refused.data)
        self.assertEqual(refused.data["code"], "party_blocked")

    def test_a_block_stops_proposing_countering_and_accepting(self):
        leg = self.journey.legs.get()
        pending = self.propose(self.open_parcel(), self.journey, leg, leg, 3_000)
        fresh = self.open_parcel()
        api(self.traveler).post(reverse("match-block", args=(self.match.pk,)))

        refused = api(self.sender).post(
            reverse("matches-propose-v1"),
            {
                "parcel_id": fresh.pk,
                "journey_id": self.journey.pk,
                "start_leg_id": leg.pk,
                "end_leg_id": leg.pk,
                "traveler_reward_eur_cents": 3_000,
            },
            format="json",
        )
        self.assertEqual(
            (refused.status_code, refused.data["code"]), (403, "party_blocked")
        )
        countered = api(self.traveler).post(
            reverse("offers-counter-v1", args=(pending["id"],)),
            {"traveler_reward_eur_cents": 3_500},
            format="json",
        )
        self.assertEqual(
            (countered.status_code, countered.data["code"]), (403, "party_blocked")
        )
        accepted = api(self.traveler).post(
            reverse("offers-accept", args=(pending["id"],)), {}, format="json"
        )
        self.assertEqual(
            (accepted.status_code, accepted.data["code"]), (403, "party_blocked")
        )

        # Lifting the block lets the pending offer be accepted again, and the
        # funded delivery was never touched.
        api(self.traveler).delete(reverse("match-block", args=(self.match.pk,)))
        self.accept(pending)
        self.deal.refresh_from_db()
        self.assertEqual(self.deal.status, "funded")

    def test_blocked_members_do_not_find_or_target_each_other(self):
        from apps.matching.discovery import (
            compatible_journeys_for_request,
            compatible_requests_for_journey,
            phase2_policy,
        )

        parcel = self.open_parcel()

        def journeys_for_parcel():
            return [
                row.journey.pk
                for row in compatible_journeys_for_request(
                    delivery_request=parcel, policy=phase2_policy()
                )
            ]

        def parcels_for_journey():
            return [
                row.delivery_request.pk
                for row in compatible_requests_for_journey(
                    journey=self.journey, policy=phase2_policy()
                )
            ]

        self.assertIn(self.journey.pk, journeys_for_parcel())
        self.assertIn(parcel.pk, parcels_for_journey())
        api(self.traveler).post(reverse("match-block", args=(self.match.pk,)))
        self.assertNotIn(self.journey.pk, journeys_for_parcel())
        self.assertNotIn(parcel.pk, parcels_for_journey())

        body = self.parcel_payload(
            self.algiers,
            self.setif,
            ready_from=self.depart - timedelta(hours=2),
            ready_until=self.depart + timedelta(minutes=30),
            deliver_by=self.depart + timedelta(hours=12),
        )
        targeted = api(self.sender).post(
            reverse("parcels-delivery-v1-create"),
            {**body, "target_traveler_id": self.traveler.pk},
            format="json",
        )
        self.assertEqual(targeted.status_code, 400)
        self.assertIn("target_traveler_id", targeted.data)

    # -- staff ---------------------------------------------------------------

    def console(self, user):
        client = Client()
        staff_login(client, user)
        return client

    def decide(self, client, message_id, action, reason="Abusive"):
        return client.post(
            reverse("admin_console:chat-report-detail", args=(message_id,)),
            {"action": action, f"{action}-reason": reason},
        )

    def test_staff_remove_a_reported_message_and_members_never_see_it_again(self):
        message_id = self.send(self.traveler, "Pay me cash or else").data["id"]
        self.report(self.sender, message_id)
        self.assertEqual(self._count("chat_reports"), 1)

        client = self.console(self.trust)
        queue = client.get(reverse("admin_console:chat-reports"), {"status": "open"})
        self.assertContains(queue, "Pay me cash or else")
        page = client.get(
            reverse("admin_console:chat-report-detail", args=(message_id,))
        )
        self.assertContains(page, "Remove the message")

        missing = self.decide(client, message_id, "remove", reason="")
        self.assertEqual(missing.status_code, 200)
        self.assertIsNone(ChatMessage.objects.get(pk=message_id).removed_at)

        self.assertEqual(self.decide(client, message_id, "remove").status_code, 302)
        message = ChatMessage.objects.get(pk=message_id)
        self.assertIsNotNone(message.removed_at)
        self.assertEqual(ChatMessageReport.objects.get().status, "actioned")
        audit = AdminAuditLog.objects.get(action="chat.message_removed")
        self.assertEqual(audit.reason, "Abusive")
        self.assertEqual(audit.actor, self.trust)
        self.assertEqual(audit.before["removed"], False)
        self.assertEqual(audit.after["removed"], True)
        self.assertEqual(audit.reference, self.deal.delivery_request.tracking_number)
        self.assertEqual(self._count("chat_reports"), 0)

        for user in (self.sender, self.traveler):
            row = self.history(user)[0]
            self.assertEqual((row["body"], row["removed"]), ("", True))
            thread = self.thread_row(user)
            self.assertEqual(
                (thread["last_message"], thread["last_message_removed"]), ("", True)
            )
        # The recipient's bell kept the event as published: the text leaves it too.
        inbox = api(self.sender).get(reverse("notification-list"), {"bucket": "all"})
        self.assertEqual(inbox.status_code, 200)
        self.assertNotIn("Pay me cash or else", str(inbox.data))

        self.assertEqual(self.decide(client, message_id, "restore").status_code, 302)
        self.assertEqual(self.history(self.sender)[0]["body"], "Pay me cash or else")

    def test_dismissing_keeps_the_message_and_a_no_op_is_refused(self):
        message_id = self.send(self.traveler, "Fine").data["id"]
        self.report(self.sender, message_id, reason="spam")
        client = self.console(self.trust)
        self.assertEqual(self.decide(client, message_id, "dismiss").status_code, 302)
        self.assertEqual(ChatMessageReport.objects.get().status, "dismissed")
        self.assertEqual(self.history(self.sender)[0]["body"], "Fine")
        again = self.decide(client, message_id, "dismiss")
        self.assertEqual(again.status_code, 200)
        self.assertEqual(
            AdminAuditLog.objects.filter(action="chat.reports_dismissed").count(), 1
        )

    def test_only_staff_who_moderate_chat_see_the_queue(self):
        message_id = self.send(self.traveler).data["id"]
        self.report(self.sender, message_id)
        client = self.console(self.ops)
        self.assertEqual(
            client.get(reverse("admin_console:chat-reports")).status_code, 403
        )
        self.assertEqual(self.decide(client, message_id, "remove").status_code, 403)
        self.assertIsNone(ChatMessage.objects.get(pk=message_id).removed_at)

    def test_a_message_nobody_reported_is_not_on_the_console(self):
        message_id = self.send(self.traveler).data["id"]
        client = self.console(self.trust)
        page = client.get(
            reverse("admin_console:chat-report-detail", args=(message_id,))
        )
        self.assertEqual(page.status_code, 404)

    def _count(self, code):
        item = next(i for i in worklist.work_items(self.trust) if i.code == code)
        return item.count
