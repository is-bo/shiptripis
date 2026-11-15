"""L10 final acceptance: the marketplace scenarios added on 2026-11-12.

Plan L10 item 2: a proposal that expires after its reminder, and one that
expires at the pickup time because that came first (spec 17); a trip-fit
alert leading to "I can carry this" and a proposal (spec 17.2); a no-show
report recorded by staff (spec 12); a review reported, its comment hidden, the
rating removed, and the average changing (spec 18). People act through the
API, staff through the console, time through `freeze_at`.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.db.models import Sum
from django.urls import reverse

from apps.admin_panel.models import AdminAuditLog
from apps.admin_panel.tests.two_step_helpers import staff_login
from apps.core import channels
from apps.deals.models import Deal
from apps.discovery.tests.support import STATIC_STORES
from apps.deals.tests.phase4_factories import freeze_at
from apps.finance.jobs import run_due_jobs
from apps.finance.models import PaymentRefund
from apps.matching.models import Offer
from apps.notifications.models import Notification
from apps.problems.models import ShipmentProblem

from .l10_world import DRIVE, FLIGHT, AcceptanceWorld, api, refusal_code


@override_settings(STORAGES=STATIC_STORES)
class MarketplaceAcceptanceTests(AcceptanceWorld, TestCase):
    def setUp(self):
        cache.clear()
        self.build_acceptance_world()

    def flight(self, depart: datetime):
        journey = self.post_trip(
            [self.leg_payload(FLIGHT, self.alg, self.cdg, depart, hours=3)]
        )
        self.approve_ticket(self.upload_ticket(journey.legs.get()))
        self.publish(journey)
        self.set_price(journey, 600, 1_200)
        journey.refresh_from_db()
        return journey

    def open_parcel(self, depart: datetime, *, origin=None, destination=None):
        parcel = self.post_parcel(
            origin or self.algiers,
            destination or self.paris,
            ready_from=depart - timedelta(hours=2),
            ready_until=depart + timedelta(minutes=30),
            deliver_by=depart + timedelta(hours=12),
        )
        self.pay_deposit(parcel)
        return parcel

    def notified(self, user, channel: str):
        return Notification.objects.filter(recipient=user, channel=channel)

    # -- proposal deadlines -------------------------------------------------

    def test_a_proposal_expires_six_hours_later_after_one_reminder(self):
        depart = self.now + timedelta(hours=20)
        journey = self.flight(depart)
        leg = journey.legs.get()
        parcel = self.open_parcel(depart)
        sent = self.now
        with freeze_at(sent):
            offer = self.propose(parcel, journey, leg, leg, 3_000)
        expires_at = datetime.fromisoformat(offer["expires_at"].replace("Z", "+00:00"))
        assert expires_at == sent + timedelta(hours=6)

        with freeze_at(expires_at - timedelta(minutes=61)):
            run_due_jobs(limit=50)
        assert not self.notified(
            self.traveler, channels.OFFER_RESPONSE_REMINDER
        ).exists()
        with freeze_at(expires_at - timedelta(minutes=59)):
            run_due_jobs(limit=50)
        reminder = self.notified(self.traveler, channels.OFFER_RESPONSE_REMINDER).get()
        assert reminder.payload["tracking_number"] == self.tracking

        with freeze_at(expires_at + timedelta(seconds=1)):
            run_due_jobs(limit=50)
            refused = api(self.traveler).post(
                reverse("offers-accept", args=(offer["id"],)), {}, format="json"
            )
        assert (
            refused.status_code == 409 and refused.data["code"] == "offer_expired"
        ), refused.data
        assert Offer.objects.get(pk=offer["id"]).status == Offer.Status.EXPIRED
        assert not Deal.objects.exists()
        # Expiry leaves no mark: the sender may propose to the same trip again.
        with freeze_at(expires_at + timedelta(minutes=5)):
            again = self.propose(parcel, journey, leg, leg, 3_000)
        assert again["status"] == Offer.Status.PENDING

    def test_a_proposal_expires_at_the_pickup_time_when_that_comes_first(self):
        depart = self.now + timedelta(hours=3)
        journey = self.flight(depart)
        leg = journey.legs.get()
        parcel = self.open_parcel(depart)
        offer = self.propose(parcel, journey, leg, leg, 3_000)
        expires_at = datetime.fromisoformat(offer["expires_at"].replace("Z", "+00:00"))
        assert expires_at == leg.depart_at, (expires_at, leg.depart_at)

        # The pickup time leaves room for the reminder an hour before.
        with freeze_at(expires_at - timedelta(minutes=59)):
            run_due_jobs(limit=50)
        with freeze_at(expires_at + timedelta(seconds=1)):
            run_due_jobs(limit=50)
        assert Offer.objects.get(pk=offer["id"]).status == Offer.Status.EXPIRED
        # Both people hear that it expired; the traveler was reminded once.
        for person in (self.sender, self.traveler):
            assert (
                self.notified(person, channels.OFFER_UPDATED)
                .filter(payload__status="expired")
                .exists()
            )
        assert (
            self.notified(self.traveler, channels.OFFER_RESPONSE_REMINDER).count() == 1
        )

    # -- trip-fit alert, "I can carry this", proposal -----------------------

    def test_a_trip_fit_alert_leads_to_i_can_carry_this_and_a_proposal(self):
        depart = self.now + timedelta(hours=8)
        journey = self.flight(depart)
        leg = journey.legs.get()
        parcel = self.open_parcel(depart)
        run_due_jobs(limit=50)

        (alert,) = self.notified(self.traveler, channels.DISCOVERY_REQUEST_FITS_TRIP)
        assert alert.payload["request_id"] == parcel.pk
        assert alert.payload["journey_id"] == journey.pk
        bell = api(self.traveler).get(reverse("notification-list"))
        assert bell.status_code == 200 and str(parcel.pk) in str(bell.data)
        # The public preview the alert opens names no tracking number.
        preview = api(self.traveler).get(reverse("discovery-requests"))
        assert any(row["request_id"] == parcel.pk for row in preview.data["results"])
        assert self.tracking not in str(preview.data)

        interest = api(self.traveler).post(
            reverse("discovery-request-interest", args=(parcel.pk,)),
            {"journey_id": journey.pk},
            format="json",
        )
        assert interest.status_code in (200, 201), interest.data
        told = self.notified(self.sender, channels.DISCOVERY_TRAVELER_INTERESTED).get()
        assert told.payload["journey_id"] == journey.pk
        assert (
            not Offer.objects.exists()
        ), "interest is not an offer: the sender proposes first"

        offer = self.propose(parcel, journey, leg, leg, 3_000)
        assert offer["status"] == Offer.Status.PENDING
        deal = self.accept(offer)
        assert deal.status == Deal.Status.PAYMENT_REQUIRED

    # -- a no-show recorded by staff ----------------------------------------

    def test_staff_record_a_traveler_no_show_and_the_sender_is_refunded(self):
        depart = self.now + timedelta(hours=4)
        journey = self.post_trip(
            [self.leg_payload(DRIVE, self.algiers, self.setif, depart, hours=3)]
        )
        self.publish(journey)
        leg = journey.legs.get()
        parcel = self.open_parcel(depart, destination=self.setif)
        deal = self.accept(self.propose(parcel, journey, leg, leg, 3_000))
        self.pay_balance(deal)
        self.set_recipient(deal)
        deal.refresh_from_db()

        too_early = api(self.sender).post(
            reverse("deal-problems", args=(deal.pk,)),
            {"kind": "traveler_no_show", "note": ""},
            format="json",
        )
        assert too_early.status_code == 409, too_early.data
        assert refusal_code(too_early) == "no_show_report_not_allowed", too_early.data
        with freeze_at(deal.agreed_pickup_at + timedelta(hours=1)):
            reported = api(self.sender).post(
                reverse("deal-problems", args=(deal.pk,)),
                {"kind": "traveler_no_show", "note": "Waited an hour at the stop."},
                format="json",
            )
            assert reported.status_code == 201, reported.data
            staff_login(self.client, self.trust)
            page = reverse("admin_console:deal-no-show", args=(deal.pk,))
            assert self.client.get(page, {"party": "traveler"}).status_code == 200
            recorded = self.client.post(
                page, {"party": "traveler", "note": "Confirmed by phone"}
            )
        assert recorded.status_code == 302, recorded.content[:500]
        deal.refresh_from_db()
        assert deal.no_show_party == "traveler"
        assert deal.status == Deal.Status.REFUNDED, deal.status
        audit = AdminAuditLog.objects.get(action="deal.no_show_recorded")
        assert audit.actor == self.trust
        problem = ShipmentProblem.objects.get(deal=deal)
        assert (
            problem.status == ShipmentProblem.Status.CLOSED
            and problem.closed_by_audit_id == audit.pk
        )
        # A traveler no-show gives the sender everything back: the cash paid
        # on the deal and the posting deposit that was credited to it.
        on_deal = PaymentRefund.objects.filter(order__deal=deal).aggregate(
            n=Sum("amount_eur_cents")
        )["n"]
        everything = PaymentRefund.objects.filter(order__owner=self.sender).aggregate(
            n=Sum("amount_eur_cents")
        )["n"]
        assert on_deal and everything == deal.terms.sender_total_minor, (
            on_deal,
            everything,
            deal.terms.sender_total_minor,
        )

    # -- a review reported, hidden, removed ---------------------------------

    def rate(self, deal: Deal, rater, score: int, comment: str) -> None:
        with freeze_at(deal.protection_ends_at + timedelta(hours=1)):
            response = api(rater).post(
                reverse("ratings-submit", args=(deal.pk,)),
                {"score": score, "tags": [], "comment": comment},
                format="json",
            )
        assert response.status_code == 201, response.data

    def summary(self) -> dict:
        response = api(self.traveler).get(reverse("ratings-mine-summary"))
        assert response.status_code == 200, response.data
        return response.data

    def test_a_reported_review_is_hidden_then_removed_and_the_average_changes(self):
        depart = self.now + timedelta(hours=3)
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
            ]
        )
        self.publish(journey)
        self.set_price(journey, 400, 1_000)
        journey.refresh_from_db()
        first, second = journey.legs.order_by("position")
        deals = []
        for origin, destination, leg in (
            (self.algiers, self.setif, first),
            (self.setif, self.constantine, second),
        ):
            parcel = self.post_parcel(
                origin,
                destination,
                ready_from=leg.depart_at - timedelta(hours=1),
                ready_until=leg.depart_at + timedelta(minutes=30),
                deliver_by=leg.arrive_at + timedelta(hours=6),
            )
            self.pay_deposit(parcel)
            deals.append(self.carry(journey, parcel, leg, leg))
        good, bad = deals
        self.rate(good, self.sender, 5, "On time and careful.")
        self.rate(good, self.traveler, 5, "Clear instructions.")
        self.rate(bad, self.sender, 1, "Rude words here.")
        self.rate(bad, self.traveler, 5, "Fine.")
        assert self.summary() == {"state": "rated", "average": 3.0, "count": 2}

        reviews = api(self.sender).get(
            reverse("discovery-trip-reviews", args=(journey.pk,))
        )
        assert reviews.status_code == 200, reviews.data
        rude = next(r for r in reviews.data["results"] if r["score"] == 1)
        assert rude["comment"] == "Rude words here."

        reported = api(self.traveler).post(
            reverse("ratings-report", args=(rude["id"],)),
            {"reason": "offensive", "note": "Insults"},
            format="json",
        )
        assert reported.status_code == 201, reported.data

        staff_login(self.client, self.trust)
        page = reverse("admin_console:review-detail", args=(rude["id"],))
        hidden = self.client.post(
            page, {"action": "hide_comment", "hide_comment-reason": "Insults"}
        )
        assert hidden.status_code == 302, hidden.content[:500]
        after_hide = (
            api(self.sender)
            .get(reverse("discovery-trip-reviews", args=(journey.pk,)))
            .data
        )
        row = next(r for r in after_hide["results"] if r["id"] == rude["id"])
        assert row["comment"] is None and row["comment_removed"] is True
        assert self.summary()["average"] == 3.0, "a hidden comment still counts"

        removed = self.client.post(
            page, {"action": "remove", "remove-reason": "Insults"}
        )
        assert removed.status_code == 302, removed.content[:500]
        assert self.summary() == {"state": "rated", "average": 5.0, "count": 1}
        after_remove = (
            api(self.sender)
            .get(reverse("discovery-trip-reviews", args=(journey.pk,)))
            .data
        )
        assert rude["id"] not in [r["id"] for r in after_remove["results"]]
        actions = list(
            AdminAuditLog.objects.filter(action__startswith="rating.").values_list(
                "action", flat=True
            )
        )
        assert sorted(actions) == ["rating.comment_hidden", "rating.removed"]
