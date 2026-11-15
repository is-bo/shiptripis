"""L10 final acceptance: the product's target, an urgent parcel carried the same day.

Plan L10 item 2. Once on a flight with an approved ticket and once on a drive
with two stops, from discovery to an offer at the listed price, payment,
pickup, the progress reports, delivery with the recipient's code, protection
and payout. Also a traveler with a sea leg and a ticket, with the sea switch on
for the test. The flight run also follows the parcel's tracking number from the
request to the payout through every payload and email it appears in (spec 16).
"""

from __future__ import annotations

from datetime import timedelta

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from apps.deals.models import Deal
from apps.parcels.models import ParcelRequest

from .l10_world import DRIVE, FLIGHT, SEA, AcceptanceWorld, api, refusal_code


class SameDayDeliveryTests(AcceptanceWorld, TestCase):
    def setUp(self):
        cache.clear()
        self.build_acceptance_world()

    # -- the flight ---------------------------------------------------------

    def test_an_urgent_parcel_flies_the_same_day_with_an_approved_ticket(self):
        depart = self.now + timedelta(hours=3)
        journey = self.post_trip(
            [self.leg_payload(FLIGHT, self.alg, self.cdg, depart, hours=3)]
        )
        leg = journey.legs.get()

        # Without an approved ticket the trip cannot be published.
        refused = api(self.traveler).post(
            reverse("journeys-publish", args=(journey.pk,))
        )
        assert refused.status_code == 409, refused.data
        assert refusal_code(refused) == "flight_proof_not_approved", refused.data
        proof = self.upload_ticket(leg)
        pending = api(self.traveler).post(
            reverse("journeys-publish", args=(journey.pk,))
        )
        assert pending.status_code == 409, pending.data
        assert refusal_code(pending) == "flight_proof_not_approved", pending.data
        self.approve_ticket(proof)
        self.publish(journey)
        self.set_price(journey, 600, 1_200)
        journey.refresh_from_db()

        parcel = self.post_parcel(
            self.algiers,
            self.paris,
            ready_from=self.now + timedelta(hours=1),
            ready_until=self.now + timedelta(hours=3, minutes=30),
            deliver_by=self.now + timedelta(hours=10),
        )
        assert parcel.status == ParcelRequest.Status.AWAITING_DEPOSIT
        self.pay_deposit(parcel)
        assert parcel.status == ParcelRequest.Status.OPEN

        deal = self.carry(journey, parcel, leg, leg)

        # The same tracking number from the request to the payout.
        mine = api(self.sender).get(reverse("parcels-detail", args=(parcel.pk,)))
        assert mine.data["tracking_number"] == self.tracking
        emails = self.emails_for(deal)
        kinds = {message.kind for message in emails}
        # The mock rail sends no payment email; every email the deal sends,
        # the recipient's code included, names the number.
        for kind in (
            "pickup_confirmed",
            "delivery_code_released",
            "recipient_delivery_code",
            "delivery_confirmed",
            "protection_ending",
            "protection_ended",
            "rating_available",
            "payout_status",
        ):
            assert kind in kinds, (kind, kinds)
        for message in emails:
            assert message.context.get("tracking_number") == self.tracking, message.kind
        # No public discovery payload carries the number.
        assert self.tracking not in str(
            api(self.traveler).get(reverse("discovery-requests")).data
        )
        assert self.tracking not in str(
            api(self.sender).get(reverse("discovery-trips")).data
        )
        # Delivered before the sender's deadline, within ten hours of posting.
        parcel.refresh_from_db()
        assert deal.delivery_confirmed_at <= parcel.deadline_at
        assert deal.delivery_confirmed_at - self.now < timedelta(hours=10)

    # -- the drive with two stops -------------------------------------------

    def test_an_urgent_parcel_is_driven_the_same_day_from_a_middle_stop(self):
        depart = self.now + timedelta(hours=2)
        journey = self.post_trip(
            [
                self.leg_payload(DRIVE, self.algiers, self.setif, depart, hours=3),
                self.leg_payload(
                    DRIVE,
                    self.setif,
                    self.constantine,
                    depart + timedelta(hours=4),
                    hours=2,
                ),
            ],
            stops=[{"position": 1, "handover_note": "Petrol station at the exit"}],
        )
        first, second = journey.legs.order_by("position")
        self.publish(journey)
        self.set_price(journey, 400, 1_000)
        journey.refresh_from_db()

        # The parcel boards at the middle stop and rides the second leg.
        parcel = self.post_parcel(
            self.setif,
            self.constantine,
            ready_from=self.now + timedelta(hours=4),
            ready_until=self.now + timedelta(hours=6),
            deliver_by=self.now + timedelta(hours=12),
        )
        self.pay_deposit(parcel)
        deal = self.carry(journey, parcel, second, second)
        assert deal.status == Deal.Status.COMPLETED

    # -- the sea leg --------------------------------------------------------

    def test_a_sea_leg_with_a_ticket_carries_a_parcel_while_the_switch_is_on(self):
        refused = api(self.traveler).post(
            reverse("journeys-list-create"),
            {
                "start_place_id": self.marseille.pk,
                "destination_place_id": self.algiers.pk,
                "notes": "",
                "legs": [
                    {
                        **self.leg_payload(
                            SEA,
                            self.marseille,
                            self.algiers,
                            self.now + timedelta(hours=3),
                            hours=20,
                        ),
                        "position": 0,
                    }
                ],
            },
            format="json",
        )
        assert refused.status_code == 400, "sea legs ship off"

        self.set_sea_switch(True)
        depart = self.now + timedelta(hours=3)
        journey = self.post_trip(
            [self.leg_payload(SEA, self.marseille, self.algiers, depart, hours=20)]
        )
        leg = journey.legs.get()
        self.approve_ticket(self.upload_ticket(leg))
        self.publish(journey)
        self.set_price(journey, 300, 1_000)
        journey.refresh_from_db()

        parcel = self.post_parcel(
            self.marseille,
            self.algiers,
            ready_from=self.now + timedelta(hours=1),
            ready_until=self.now + timedelta(hours=3, minutes=30),
            deliver_by=self.now + timedelta(days=2),
        )
        self.pay_deposit(parcel)
        deal = self.carry(journey, parcel, leg, leg)
        assert deal.status == Deal.Status.COMPLETED
