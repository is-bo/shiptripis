"""L3A: a ticket decision names the ticket it is about.

A traveler with a flight and a ferry on one journey must be told which ticket
staff decided, in the email and in the push, in every launch language. Each
mode's copy is a whole sentence of its own, never a spliced noun.
"""

from __future__ import annotations

import json
from unittest.mock import patch
from uuid import uuid4

from django.test import TestCase, override_settings
from django.utils import translation

from apps.admin_panel.permissions import AdminRole, assign_admin_roles
from apps.admin_panel.services import review_flight_proof
from apps.core.channels import LEG_PROOF_STATUS_CHANGED
from apps.notifications import outbox
from apps.notifications.models import Notification, OutboundMessage, PushDevice
from apps.notifications.push import enqueue_fcm_for_event
from apps.notifications.tests.factories import push_device
from apps.trips.models import JourneyLegProof
from apps.trips.tests.sea_world import DRIVE, SEA, SeaWorld

from .test_push import _RedisRecorder, _user


def _render(mode: str, status: str, language: str = "en") -> tuple[str, str]:
    return outbox.render(
        OutboundMessage(
            kind=OutboundMessage.Kind.LEG_PROOF_STATUS,
            language=language,
            context={"status": status, "mode": mode, "journey_reference": "J-7"},
        )
    )


class TicketEmailCopyTests(TestCase):
    def test_the_email_names_the_ferry_ticket(self):
        subject, body = _render("SEA", "approved")

        assert subject == "Wassla ferry ticket update"
        assert "Your ferry ticket is approved" in body
        assert "The verified sea leg can be used for matching." in body
        assert "flight" not in body.lower()

        subject, body = _render("SEA", "action_required")
        assert "Your ferry ticket needs attention" in body

    def test_the_email_names_the_flight_ticket(self):
        subject, body = _render("FLIGHT", "approved")

        assert subject == "Wassla flight ticket update"
        assert "Your flight ticket is approved" in body
        assert "ferry" not in body.lower()

    def test_every_launch_language_has_its_own_ferry_copy(self):
        english, _ = _render("SEA", "approved")
        french, french_body = _render("SEA", "approved", "fr")
        arabic, _ = _render("SEA", "approved", "ar")

        assert french == "Mise à jour de votre billet de ferry Wassla"
        assert "Votre billet de ferry est approuvé" in french_body
        assert arabic not in (english, french)
        with translation.override("ar"):
            assert translation.gettext("Wassla ferry ticket update") == arabic


@override_settings(FCM_ENABLED=True, FCM_STREAM="notif:fcm")
class TicketPushCopyTests(TestCase):
    def push(self, payload: dict) -> list[dict]:
        recorder = _RedisRecorder()
        users = [_user(f"{language}-{uuid4().hex[:6]}@example.com", language) for language in ("en", "fr", "ar")]
        event_id = f"event-{uuid4().hex}"
        for user in users:
            push_device(
                user=user,
                installation_id=uuid4(),
                token=f"fcm-token-{uuid4().hex}",
                platform=PushDevice.Platform.ANDROID,
            )
            Notification.objects.create(
                recipient=user, channel=LEG_PROOF_STATUS_CHANGED, event_id=event_id, payload={}
            )
        with patch("apps.core.redis_bus.get_client", return_value=recorder):
            enqueue_fcm_for_event(
                channel=LEG_PROOF_STATUS_CHANGED,
                event_id=event_id,
                payload=payload,
                targets=[user.pk for user in users],
            )
        return [json.loads(entry[1]["payload"]) for entry in recorder.entries]

    def titles(self, payload: dict) -> set[str]:
        return {row["title"] for row in self.push(payload)}

    def test_the_push_names_the_ticket_in_every_language(self):
        assert self.titles({"mode": "SEA", "status": "approved"}) == {
            "Ferry ticket approved",
            "Billet de ferry approuvé",
            "تمت الموافقة على تذكرة العبّارة",
        }
        assert "Ferry ticket needs attention" in self.titles({"mode": "SEA", "status": "rejected"})
        assert "Flight ticket approved" in self.titles({"mode": "FLIGHT", "status": "approved"})

    def test_a_status_without_its_own_copy_stays_generic(self):
        assert "Ticket updated" in self.titles({"mode": "SEA", "status": "pending"})
        assert "Ticket updated" in self.titles({"status": "approved"})


class TicketReviewNotificationTests(SeaWorld, TestCase):
    def setUp(self):
        self.build_sea_world()
        self.set_sea_switch(True)
        self.traveler = self.person("l3a-copy-traveler@example.com")
        self.reviewer = self.person("l3a-copy-trust@example.com", verified=False)
        assign_admin_roles(self.reviewer, (AdminRole.TRUST,))
        journey = self.make_journey(
            self.traveler,
            [(SEA, self.marseille, self.algiers), (DRIVE, self.algiers, self.setif)],
            approve_tickets=False,
        )
        self.proof = self.ticket(journey.legs.get(mode=SEA), JourneyLegProof.Status.PENDING)

    def test_a_ferry_ticket_decision_tells_the_traveler_which_ticket(self):
        with patch("apps.core.redis_bus.publish_after_commit") as publish:
            review_flight_proof(
                actor=self.reviewer,
                proof_id=self.proof.pk,
                decision=JourneyLegProof.Status.REJECTED,
                reason="Wrong sailing date",
            )

        message = OutboundMessage.objects.get(kind=OutboundMessage.Kind.LEG_PROOF_STATUS)
        assert message.key == f"leg_proof_status:{self.proof.pk}:rejected"
        assert message.context["mode"] == SEA
        assert outbox.render(message)[0] == "Wassla ferry ticket update"
        channel, payload = publish.call_args.args
        assert channel == LEG_PROOF_STATUS_CHANGED
        assert (payload["mode"], payload["status"]) == (SEA, "rejected")
        assert publish.call_args.kwargs["targets"] == [self.traveler.pk]
