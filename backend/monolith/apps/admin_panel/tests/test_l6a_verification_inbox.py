"""L6A: the staff verification inbox (spec 13).

One inbox with two tabs, ID and Tickets, under one header with counters; one
navigation entry with the total; one review screen for both kinds with three
decisions: approve, ask for a new upload, reject.
"""

from __future__ import annotations

import json
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import RequestFactory, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework.test import APIClient

from apps.admin_panel import verification_inbox as inbox
from apps.admin_panel.models import AdminAuditLog
from apps.admin_panel.permissions import has_admin_permission
from apps.admin_panel.services import (
    AdminReviewError,
    review_flight_proof,
    review_kyc_submission,
)
from apps.core.channels import KYC_STATUS_CHANGED, LEG_PROOF_STATUS_CHANGED
from apps.discovery.tests.support import STATIC_STORES
from apps.kyc.grpc_gen import kyc_pb2
from apps.kyc.grpc_server import KYCSubmissionServicer
from apps.kyc.models import KycSubmission
from apps.notifications import outbox
from apps.notifications.models import Notification, OutboundMessage, PushDevice
from apps.notifications.push import enqueue_fcm_for_event
from apps.notifications.tests.test_push import _RedisRecorder
from apps.notifications.tests.test_push import _user as _push_user
from apps.trips.models import Journey, JourneyLegProof
from apps.trips.proofs import STATE_REJECTED, leg_proof_satisfied, leg_proof_state
from apps.trips.tests.sea_world import FLIGHT, SEA

from .test_l3b_console import ConsoleWorld

ASK = inbox.RESUBMISSION_REQUESTED


class InboxWorld(ConsoleWorld):
    def build_inbox_world(self) -> None:
        self.build_console_world()
        self.set_sea_switch(True)
        self.applicants = [
            self.person(f"l6a-applicant-{index}@example.com", verified=False)
            for index in range(3)
        ]
        self.journey = self.make_journey(
            self.traveler,
            [(SEA, self.marseille, self.algiers), (FLIGHT, self.algiers, self.setif)],
            approve_tickets=False,
        )
        self.sea_leg, self.flight_leg = self.journey.legs.order_by("position")

    def submission(self, user, status=KycSubmission.Status.PENDING) -> KycSubmission:
        return KycSubmission.objects.create(
            user=user,
            document_type=KycSubmission.DocumentType.PASSPORT,
            idempotency_key=uuid4().hex,
            front_image_key=f"kyc/l6a/{uuid4().hex}.jpg",
            status=status,
        )

    def only(self, email: str, *codes: str):
        """A staff member holding exactly these capabilities, no role."""

        user = self.person(email, verified=False)
        user.is_staff = True
        user.save(update_fields=["is_staff"])
        user.user_permissions.add(
            *Permission.objects.filter(
                content_type__app_label="admin_panel", codename__in=codes
            )
        )
        return user

    def request_for(self, user):
        request = RequestFactory().get("/admin/")
        request.user = user
        return request


# ---------------------------------------------------------------------------
# Counters, navigation, tabs and landing
# ---------------------------------------------------------------------------


@override_settings(STORAGES=STATIC_STORES)
class InboxCountTests(InboxWorld, TestCase):
    def setUp(self):
        self.build_inbox_world()
        for applicant in self.applicants:
            self.submission(applicant)
        self.submission(self.applicants[0], KycSubmission.Status.REJECTED)
        self.ticket(self.sea_leg, JourneyLegProof.Status.PENDING)
        self.ticket(self.flight_leg, JourneyLegProof.Status.APPROVED)
        self.kyc_only = self.only("l6a-kyc-only@example.com", "view_dashboard", "view_kyc")
        self.tickets_only = self.only(
            "l6a-tickets-only@example.com", "view_dashboard", "view_flight_proofs"
        )

    def queue_rows(self, user, route: str) -> int:
        response = self.get(user, reverse(route), status=inbox.WAITING_STATUS)
        return self.body(response).count("data-row-link")

    def test_each_counter_and_the_total_equal_the_queues_own_rows_for_every_role(self):
        for user, expected in (
            (self.trust, {"id": 3, "tickets": 1}),
            (self.root, {"id": 3, "tickets": 1}),
            (self.kyc_only, {"id": 3}),
            (self.tickets_only, {"tickets": 1}),
            (self.support, {}),
            (self.ops, {}),
        ):
            with self.subTest(user.email):
                request = self.request_for(user)
                counts = inbox.waiting_counts(request)
                self.assertEqual(counts, expected)
                self.assertEqual(
                    inbox.waiting_total(request),
                    sum(expected.values()) if expected else None,
                )
                for tab in inbox.TABS:
                    if tab.key in counts:
                        self.assertEqual(self.queue_rows(user, tab.route), counts[tab.key])

    def test_the_navigation_has_one_verification_entry_with_the_total(self):
        body = self.body(self.get(self.trust, reverse("admin_console:overview")))

        self.assertNotIn("KYC review", body)
        self.assertNotIn(">Ticket proofs<", body)
        self.assertIn(
            '<span>Verification</span><span class="st-nav-count">4<span class="st-visually-hidden"> waiting</span></span>',
            body,
        )
        # Payout identity checks stay their own entry (a step of dinar payouts).
        self.assertIn("Payout identity checks", body)

    def test_the_navigation_total_falls_when_a_decision_is_saved(self):
        pending = KycSubmission.objects.filter(status="pending").first()
        review_kyc_submission(actor=self.trust, submission_id=pending.pk, decision="approved")

        body = self.body(self.get(self.trust, reverse("admin_console:overview")))

        self.assertIn('<span class="st-nav-count">3<span', body)

    def test_a_role_with_one_capability_sees_only_that_tab(self):
        body = self.body(self.get(self.kyc_only, reverse("admin_console:kyc-queue")))
        self.assertIn("><span>ID</span><b>3", body)
        self.assertNotIn("><span>Tickets</span>", body)

        body = self.body(self.get(self.tickets_only, reverse("admin_console:proof-queue")))
        self.assertIn("><span>Tickets</span><b>1", body)
        self.assertNotIn("><span>ID</span>", body)
        self.assertEqual(
            self.get(self.tickets_only, reverse("admin_console:kyc-queue")).status_code, 403
        )

    def test_a_role_with_neither_capability_cannot_open_the_inbox(self):
        self.client.force_login(self.ops)
        self.assertEqual(self.client.get(reverse("admin_console:verification")).status_code, 403)

    def test_the_tabs_open_exactly_what_they_count(self):
        body = self.body(self.get(self.trust, reverse("admin_console:proof-queue")))

        self.assertIn('href="/admin/verification/kyc/?status=pending"', body)
        self.assertIn('href="/admin/verification/flight-proofs/?status=pending"', body)
        self.assertIn('aria-current="page"><span>Tickets</span>', body)

    def test_opening_verification_lands_on_the_first_tab_with_work(self):
        landing = reverse("admin_console:verification")
        self.client.force_login(self.trust)
        self.assertRedirects(
            self.client.get(landing),
            "/admin/verification/kyc/?status=pending",
            fetch_redirect_response=False,
        )

        KycSubmission.objects.filter(status="pending").delete()
        self.assertRedirects(
            self.client.get(landing),
            "/admin/verification/flight-proofs/?status=pending",
            fetch_redirect_response=False,
        )

        JourneyLegProof.objects.filter(status="pending").delete()
        self.assertRedirects(
            self.client.get(landing),
            "/admin/verification/kyc/?status=pending",
            fetch_redirect_response=False,
        )

    def test_a_tickets_only_role_lands_on_tickets(self):
        self.client.force_login(self.tickets_only)
        self.assertRedirects(
            self.client.get(reverse("admin_console:verification")),
            "/admin/verification/flight-proofs/?status=pending",
            fetch_redirect_response=False,
        )

    def test_the_overview_keeps_one_work_item_per_tab_from_the_same_counts(self):
        body = self.body(self.get(self.trust, reverse("admin_console:overview")))

        self.assertIn("ID checks to review", body)
        self.assertIn("Tickets to review", body)
        self.assertNotIn("KYC submissions to review", body)

    def test_the_inbox_header_costs_one_query_per_visible_tab_whatever_reads_it(self):
        request = self.request_for(self.trust)
        # The user's permission cache is warm on every real console request
        # (the view's own guard reads it first), so it is not counted here.
        self.assertTrue(has_admin_permission(self.trust, "view_kyc"))
        with CaptureQueriesContext(connection) as queries:
            inbox.inbox_header(request, "id")
            inbox.waiting_total(request)
            inbox.landing_url(request)
            inbox.inbox_header(request, "tickets")
        self.assertEqual(len(queries.captured_queries), 2)

    def test_the_queue_page_costs_the_same_however_many_rows_wait(self):
        def cost() -> int:
            self.client.force_login(self.trust)
            url = reverse("admin_console:kyc-queue")
            with CaptureQueriesContext(connection) as queries:
                self.client.get(url, {"status": "pending"})
            return len(queries.captured_queries)

        before = cost()
        for index in range(4):
            self.submission(self.person(f"l6a-more-{index}@example.com", verified=False))
        self.assertEqual(cost(), before)


# ---------------------------------------------------------------------------
# The three decisions, for both kinds
# ---------------------------------------------------------------------------


@override_settings(STORAGES=STATIC_STORES)
class DecisionTests(InboxWorld, TestCase):
    def setUp(self):
        self.build_inbox_world()
        self.applicant = self.applicants[0]

    def decide_kyc(self, decision, reason=""):
        submission = self.submission(self.applicant)
        with patch("apps.core.redis_bus.publish_after_commit") as publish:
            review_kyc_submission(
                actor=self.trust, submission_id=submission.pk, decision=decision, reason=reason
            )
        submission.refresh_from_db()
        return submission, publish

    def decide_ticket(self, decision, reason="", leg=None):
        proof = self.ticket(leg or self.sea_leg, JourneyLegProof.Status.PENDING)
        with patch("apps.core.redis_bus.publish_after_commit") as publish:
            review_flight_proof(
                actor=self.trust, proof_id=proof.pk, decision=decision, reason=reason
            )
        proof.refresh_from_db()
        return proof, publish

    def audit(self, record) -> AdminAuditLog:
        meta = record._meta
        return AdminAuditLog.objects.get(
            target_type=f"{meta.app_label}.{meta.model_name}", target_id=str(record.pk)
        )

    def test_each_decision_writes_its_status_audit_and_notification_for_an_id(self):
        cases = (
            ("approved", "", "approved", "approved", "kyc.approved"),
            (ASK, "Photo is blurred", "rejected", "action_required", "kyc.rejected"),
            ("rejected", "Not a valid document", "rejected", "action_required", "kyc.rejected"),
        )
        for decision, reason, status, notified, action in cases:
            with self.subTest(decision):
                submission, publish = self.decide_kyc(decision, reason)

                self.assertEqual(submission.status, status)
                self.assertEqual(submission.rejection_reason, reason)
                audit = self.audit(submission)
                self.assertEqual(audit.action, action)
                self.assertEqual(audit.actor, self.trust)
                self.assertEqual(audit.reason, reason)
                self.assertEqual(audit.before["status"], "pending")
                self.assertEqual(audit.after["status"], status)
                self.assertEqual(audit.metadata, {"outcome": decision})
                message = OutboundMessage.objects.get(
                    key=f"kyc_status:{submission.pk}:{status}"
                )
                self.assertEqual(message.context["status"], notified)
                self.assertEqual(message.context["outcome"], decision)
                channel, payload = publish.call_args.args
                self.assertEqual(channel, KYC_STATUS_CHANGED)
                self.assertEqual((payload["status"], payload["outcome"]), (status, decision))
                self.assertEqual(publish.call_args.kwargs["targets"], [self.applicant.pk])

    def test_each_decision_writes_its_status_audit_and_notification_for_a_ticket(self):
        cases = (
            ("approved", "", "approved", "flight_proof.approved"),
            (ASK, "Wrong sailing date", "rejected", "flight_proof.rejected"),
            ("rejected", "Not a ticket", "rejected", "flight_proof.rejected"),
        )
        for decision, reason, status, action in cases:
            with self.subTest(decision):
                proof, publish = self.decide_ticket(decision, reason)

                self.assertEqual(proof.status, status)
                audit = self.audit(proof)
                self.assertEqual(audit.action, action)
                self.assertEqual(audit.reason, reason)
                self.assertEqual(audit.metadata, {"outcome": decision})
                message = OutboundMessage.objects.get(
                    key=f"leg_proof_status:{proof.pk}:{status}"
                )
                self.assertEqual(message.context["outcome"], decision)
                self.assertEqual(message.context["mode"], SEA)
                channel, payload = publish.call_args.args
                self.assertEqual(channel, LEG_PROOF_STATUS_CHANGED)
                self.assertEqual(payload["outcome"], decision)

    def test_asking_for_more_or_rejecting_needs_a_reason(self):
        for decision in (ASK, "rejected"):
            with self.subTest(decision):
                submission = self.submission(self.applicant)
                proof = self.ticket(self.sea_leg, JourneyLegProof.Status.PENDING)
                with self.assertRaises(AdminReviewError):
                    review_kyc_submission(
                        actor=self.trust, submission_id=submission.pk, decision=decision, reason="  "
                    )
                with self.assertRaises(AdminReviewError):
                    review_flight_proof(actor=self.trust, proof_id=proof.pk, decision=decision)
                submission.refresh_from_db()
                proof.refresh_from_db()
                self.assertEqual((submission.status, proof.status), ("pending", "pending"))

    def test_an_unknown_decision_is_refused(self):
        submission = self.submission(self.applicant)
        with self.assertRaises(AdminReviewError):
            review_kyc_submission(
                actor=self.trust, submission_id=submission.pk, decision="expired", reason="x"
            )

    def test_a_replay_of_the_same_decision_is_silent_and_a_different_one_is_refused(self):
        submission, _ = self.decide_kyc(ASK, "Blurred")

        # The same form posted twice: nothing new is written.
        review_kyc_submission(
            actor=self.trust, submission_id=submission.pk, decision=ASK, reason="Blurred"
        )
        self.assertEqual(AdminAuditLog.objects.filter(target_id=str(submission.pk), target_type="kyc.kycsubmission").count(), 1)
        # A second reviewer choosing "reject" on the same row is told it is
        # already decided, although both store the rejected status.
        with self.assertRaises(AdminReviewError):
            review_kyc_submission(
                actor=self.trust, submission_id=submission.pk, decision="rejected", reason="No"
            )
        proof, _ = self.decide_ticket("rejected", "No")
        with self.assertRaises(AdminReviewError):
            review_flight_proof(actor=self.trust, proof_id=proof.pk, decision=ASK, reason="Again")

    def test_asking_for_more_keeps_the_leg_unmatchable_and_approval_still_opens_it(self):
        proof, _ = self.decide_ticket(ASK, "Blurred", leg=self.flight_leg)
        self.flight_leg.refresh_from_db()

        self.assertFalse(leg_proof_satisfied(self.flight_leg))
        self.assertEqual(leg_proof_state(self.flight_leg), STATE_REJECTED)

        self.decide_ticket("approved", leg=self.flight_leg)
        self.flight_leg.refresh_from_db()
        self.assertTrue(leg_proof_satisfied(self.flight_leg))

    def test_the_api_takes_the_same_three_decisions(self):
        api = APIClient()
        api.force_authenticate(self.trust)
        submission = self.submission(self.applicant)
        url = reverse("admin-kyc-review", args=(submission.pk,))

        refused = api.post(url, {"decision": ASK}, format="json")
        self.assertEqual(refused.status_code, 400)
        self.assertIn("reason", refused.data)

        response = api.post(url, {"decision": ASK, "reason": "Blurred"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.audit(submission).metadata, {"outcome": ASK})


@override_settings(STORAGES=STATIC_STORES, S3_BUCKET_PROOF="shiptrip-proof-test")
class ResubmissionTests(InboxWorld, TestCase):
    def setUp(self):
        self.build_inbox_world()

    def test_an_applicant_can_submit_a_new_id_after_ask_for_more(self):
        applicant = self.applicants[0]
        first = self.submission(applicant)
        review_kyc_submission(
            actor=self.trust, submission_id=first.pk, decision=ASK, reason="Blurred"
        )
        servicer = KYCSubmissionServicer()

        response = servicer.RecordSubmission(
            kyc_pb2.RecordSubmissionRequest(
                user_id=applicant.pk,
                document_type=kyc_pb2.DOCUMENT_TYPE_PASSPORT,
                idempotency_key=uuid4().hex,
                front_image_key="kyc-docs/l6a/new-front.jpg",
            ),
            None,
        )

        self.assertTrue(response.created)
        again = KycSubmission.objects.get(pk=response.submission_id)
        self.assertEqual(again.status, "pending")
        self.assertEqual(inbox.waiting_counts(self.request_for(self.trust))["id"], 1)

    def test_a_traveler_can_upload_a_new_ticket_after_ask_for_more(self):
        from apps.trips.tests.test_phase8fa_journey_editing import PNG_2x2

        # A journey waits in verification until its tickets are approved; that
        # is where a traveler sends a ticket again.
        journey = self.make_journey(
            self.traveler,
            [(FLIGHT, self.algiers, self.setif)],
            approve_tickets=False,
            status=Journey.Status.PENDING_VERIFICATION,
        )
        leg = journey.legs.get()
        first = self.ticket(leg, JourneyLegProof.Status.PENDING)
        review_flight_proof(
            actor=self.trust, proof_id=first.pk, decision=ASK, reason="Blurred"
        )
        api = APIClient()
        api.force_authenticate(self.traveler)
        with patch("apps.trips.views.put_object"):
            response = api.post(
                reverse("journey-leg-proof-create", args=(journey.pk, leg.pk)),
                {
                    "kind": "boarding_pass",
                    "photo": SimpleUploadedFile("pass.png", PNG_2x2, content_type="image/png"),
                },
                format="multipart",
            )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(JourneyLegProof.objects.filter(leg=leg, status="pending").count(), 1)


# ---------------------------------------------------------------------------
# The one review screen
# ---------------------------------------------------------------------------


@override_settings(STORAGES=STATIC_STORES)
class ReviewScreenTests(InboxWorld, TestCase):
    def setUp(self):
        self.build_inbox_world()
        self.kyc = self.submission(self.applicants[0])
        self.proof = self.ticket(self.sea_leg, JourneyLegProof.Status.PENDING)
        self.kyc_url = reverse("admin_console:kyc-detail", args=(self.kyc.pk,))
        self.proof_url = reverse("admin_console:proof-detail", args=(self.proof.pk,))

    def test_both_kinds_offer_the_same_three_decisions(self):
        for url in (self.kyc_url, self.proof_url):
            with self.subTest(url):
                body = self.body(self.get(self.trust, url))
                self.assertIn('name="decision" value="approved"', body)
                self.assertIn('name="decision" value="resubmission_requested"', body)
                self.assertIn('name="decision" value="rejected"', body)
                self.assertIn("Ask for a new upload", body)
                self.assertIn("Reason, required unless you approve", body)
                self.assertIn(">Verification</a>", body)

    def test_ask_for_more_from_the_screen_needs_a_reason_and_then_reads_as_such(self):
        refused = self.post(
            self.trust,
            self.proof_url,
            {"decision": ASK, "reason": "", "confirm": "on"},
        )
        self.assertEqual(refused.status_code, 200)
        self.assertIn("Say what is wrong", refused.content.decode())
        self.proof.refresh_from_db()
        self.assertEqual(self.proof.status, "pending")

        saved = self.post(
            self.trust,
            self.proof_url,
            {"decision": ASK, "reason": "Wrong sailing date", "confirm": "on"},
        )
        self.assertEqual(saved.status_code, 302)
        self.proof.refresh_from_db()
        self.assertEqual(self.proof.status, "rejected")

        detail = self.body(self.get(self.trust, self.proof_url))
        self.assertIn("New upload requested", detail)
        self.assertIn("Already decided: <strong>new upload requested</strong>", detail)
        queue = self.body(
            self.get(self.trust, reverse("admin_console:proof-queue"), status="rejected")
        )
        self.assertIn("New upload requested", queue)

    def test_a_rejection_still_reads_as_rejected(self):
        self.post(
            self.trust,
            self.kyc_url,
            {"decision": "rejected", "reason": "Not a document", "confirm": "on"},
        )
        detail = self.body(self.get(self.trust, self.kyc_url))

        self.assertIn("Already decided: <strong>rejected</strong>", detail)
        self.assertNotIn("New upload requested", detail)

    def test_a_viewer_without_review_rights_sees_no_decision_buttons(self):
        viewer = self.only("l6a-viewer@example.com", "view_dashboard", "view_kyc")
        body = self.body(self.get(viewer, self.kyc_url))

        self.assertNotIn('value="resubmission_requested"', body)
        self.assertIn("cannot decide it", body)
        denied = self.post(
            viewer, self.kyc_url, {"decision": "approved", "confirm": "on"}
        )
        self.assertEqual(denied.status_code, 403)


# ---------------------------------------------------------------------------
# What the person reads: email and push, three languages
# ---------------------------------------------------------------------------


def _email(kind, language, **context):
    return outbox.render(
        OutboundMessage(kind=kind, language=language, context={"reason": "Blurred", **context})
    )


class ResubmissionCopyTests(TestCase):
    def test_the_id_email_asks_for_a_new_upload_in_every_language(self):
        expected = {
            "en": "We need a new upload of your identity document",
            "fr": "Nous avons besoin d’un nouvel envoi de votre pièce d’identité",
            "ar": "نحتاج إلى رفع جديد لوثيقة هويتك",
        }
        for language, heading in expected.items():
            with self.subTest(language):
                _subject, body = _email(
                    OutboundMessage.Kind.KYC_STATUS,
                    language,
                    status="action_required",
                    outcome=ASK,
                )
                self.assertIn(heading, body)
                self.assertIn("Blurred", body)
        _subject, rejected = _email(
            OutboundMessage.Kind.KYC_STATUS, "en", status="action_required", outcome="rejected"
        )
        self.assertIn("Your identity verification needs attention", rejected)
        self.assertNotIn("new upload", rejected)

    def test_the_ticket_email_names_the_ticket_and_asks_for_a_new_upload(self):
        expected = {
            ("FLIGHT", "en"): "We need a new upload of your flight ticket",
            ("SEA", "en"): "We need a new upload of your ferry ticket",
            ("FLIGHT", "fr"): "Nous avons besoin d’un nouvel envoi de votre billet d’avion",
            ("SEA", "fr"): "Nous avons besoin d’un nouvel envoi de votre billet de ferry",
            ("FLIGHT", "ar"): "نحتاج إلى رفع جديد لتذكرة الطيران الخاصة بك",
            ("SEA", "ar"): "نحتاج إلى رفع جديد لتذكرة العبّارة الخاصة بك",
        }
        for (mode, language), heading in expected.items():
            with self.subTest(f"{mode}-{language}"):
                _subject, body = _email(
                    OutboundMessage.Kind.LEG_PROOF_STATUS,
                    language,
                    status="action_required",
                    outcome=ASK,
                    mode=mode,
                    journey_reference="J-7",
                )
                self.assertIn(heading, body)
                self.assertIn("J-7", body)


@override_settings(FCM_ENABLED=True, FCM_STREAM="notif:fcm")
class ResubmissionPushTests(TestCase):
    def titles(self, channel, payload) -> set[str]:
        recorder = _RedisRecorder()
        users = [
            _push_user(f"l6a-{language}-{uuid4().hex[:6]}@example.com", language)
            for language in ("en", "fr", "ar")
        ]
        event_id = f"event-{uuid4().hex}"
        for user in users:
            PushDevice.objects.create(
                user=user,
                installation_id=uuid4(),
                token=f"fcm-token-{uuid4().hex}",
                platform=PushDevice.Platform.ANDROID,
            )
            Notification.objects.create(
                recipient=user, channel=channel, event_id=event_id, payload={}
            )
        with patch("apps.core.redis_bus.get_client", return_value=recorder):
            enqueue_fcm_for_event(
                channel=channel,
                event_id=event_id,
                payload=payload,
                targets=[user.pk for user in users],
            )
        return {json.loads(entry[1]["payload"])["title"] for entry in recorder.entries}

    def test_an_id_ask_for_more_push_says_we_need_a_new_upload(self):
        self.assertEqual(
            self.titles(KYC_STATUS_CHANGED, {"status": "rejected", "outcome": ASK}),
            {"We need a new upload", "Nous avons besoin d'un nouvel envoi", "نحتاج إلى رفع جديد"},
        )
        self.assertIn(
            "KYC needs attention",
            self.titles(KYC_STATUS_CHANGED, {"status": "rejected", "outcome": "rejected"}),
        )

    def test_a_ticket_ask_for_more_push_names_the_ticket(self):
        self.assertEqual(
            self.titles(LEG_PROOF_STATUS_CHANGED, {"status": "rejected", "outcome": ASK, "mode": SEA}),
            {
                "We need a new ferry ticket",
                "Nous avons besoin d'un nouveau billet de ferry",
                "نحتاج إلى تذكرة عبّارة جديدة",
            },
        )
        self.assertIn(
            "We need a new flight ticket",
            self.titles(LEG_PROOF_STATUS_CHANGED, {"status": "rejected", "outcome": ASK, "mode": FLIGHT}),
        )
        self.assertIn(
            "Flight ticket needs attention",
            self.titles(
                LEG_PROOF_STATUS_CHANGED, {"status": "rejected", "outcome": "rejected", "mode": FLIGHT}
            ),
        )

