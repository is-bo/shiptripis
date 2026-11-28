"""A member's whole name goes to the member and to staff; everyone else gets the first name.

Spec 4.2 forbids a last name on any public surface. Where the specification is
silent (journey detail, a proposal's parties, chat, the blocked list, the
recipient's email), the rule of package PV holds: the first name only, for the
other party before and after funding alike, and for a guest.
"""

from __future__ import annotations

from datetime import timedelta

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.core.tests.l10_world import DRIVE, AcceptanceWorld, api
from apps.discovery.tests.support import STATIC_STORES
from apps.notifications.models import OutboundMessage

TRAVELER = "Yacine Bensalah"
SENDER = "Samira Haddadine"


@override_settings(STORAGES=STATIC_STORES)
class MemberNamesByAudienceTests(AcceptanceWorld, TestCase):
    def setUp(self):
        cache.clear()
        self.build_acceptance_world()
        assert (self.traveler.full_name, self.sender.full_name) == (TRAVELER, SENDER)
        depart = self.now + timedelta(hours=4)
        self.journey = self.post_trip(
            [self.leg_payload(DRIVE, self.algiers, self.setif, depart, hours=3)]
        )
        self.publish(self.journey)
        leg = self.journey.legs.get()
        self.parcel = self.post_parcel(
            self.algiers,
            self.setif,
            ready_from=depart - timedelta(hours=2),
            ready_until=depart + timedelta(minutes=30),
            deliver_by=depart + timedelta(hours=12),
        )
        self.pay_deposit(self.parcel)
        self.offer = self.propose(self.parcel, self.journey, leg, leg, 3_000)
        self.match_id = self.offer["match"]

    def fund(self):
        deal = self.accept(self.offer)
        self.pay_balance(deal)
        return deal

    def get(self, user, name, *args):
        client = api(user) if user is not None else APIClient()
        return client.get(reverse(name, args=args))

    # -- journey detail: `traveler_name` ------------------------------------

    def journey_name(self, user):
        response = self.get(user, "journeys-detail", self.journey.pk)
        return response.data["traveler_name"] if response.status_code == 200 else response.status_code

    def test_journey_detail_names_the_traveler_by_audience(self):
        before = {
            "owner": self.journey_name(self.traveler),
            "other party": self.journey_name(self.sender),
            "staff": self.journey_name(self.ops),
            "guest": self.journey_name(None),
        }
        assert before == {
            "owner": TRAVELER,
            "other party": "Yacine",
            "staff": TRAVELER,
            "guest": 401,
        }
        self.fund()
        assert self.journey_name(self.sender) == "Yacine"

    def test_the_journey_list_names_its_owner_whole(self):
        rows = self.get(self.traveler, "journeys-list-create").data
        rows = rows["results"] if isinstance(rows, dict) else rows
        assert {row["traveler_name"] for row in rows} == {TRAVELER}

    # -- a proposal: `sender_name` and `traveler_name` -----------------------

    def match_names(self, user, name="matches-detail"):
        args = (self.match_id,) if name == "matches-detail" else ()
        response = self.get(user, name, *args)
        if response.status_code != 200:
            return response.status_code
        data = response.data
        if name == "matches-list":
            rows = data["results"] if isinstance(data, dict) else data
            data = next(row for row in rows if row["id"] == self.match_id)
        return data["sender_name"], data["traveler_name"]

    def test_a_proposal_names_each_party_by_audience(self):
        for stage in ("before funding", "after funding"):
            if stage == "after funding":
                self.fund()
            for endpoint in ("matches-detail", "matches-list"):
                with self.subTest(stage=stage, endpoint=endpoint):
                    assert self.match_names(self.sender, endpoint) == (SENDER, "Yacine")
                    assert self.match_names(self.traveler, endpoint) == ("Samira", TRAVELER)
                    assert self.match_names(None, endpoint) == 401
        # Staff are not a party and read proposals in the console instead.
        assert self.match_names(self.ops) == 403

    # -- chat: `counterparty_name`, and the blocked list's `name` -------------

    def counterparty(self, user):
        rows = self.get(user, "chat-threads").data["results"]
        return next(row for row in rows if row["match_id"] == self.match_id)["counterparty_name"]

    def test_chat_names_the_other_party_by_first_name(self):
        self.fund()
        assert self.counterparty(self.sender) == "Yacine"
        assert self.counterparty(self.traveler) == "Samira"
        assert self.get(None, "chat-threads").status_code == 401

    def test_the_blocked_list_names_the_blocked_member_by_first_name(self):
        self.fund()
        response = api(self.sender).post(reverse("match-block", args=(self.match_id,)))
        assert response.status_code in (200, 201, 204), response.data
        rows = self.get(self.sender, "my-blocks").data["results"]
        assert [row["name"] for row in rows] == ["Yacine"]

    # -- the recipient's email: `sender_name` --------------------------------

    def test_the_recipient_is_told_the_senders_first_name(self):
        deal = self.fund()
        self.set_recipient(deal)
        self.pick_up(deal)
        self.deliver(deal)
        (email,) = [
            message
            for message in self.emails_for(deal)
            if message.kind == OutboundMessage.Kind.RECIPIENT_DELIVERY_CODE
        ]
        assert email.context["sender_name"] == "Samira"
        assert email.context["recipient_name"] == "Amina Recipient"
