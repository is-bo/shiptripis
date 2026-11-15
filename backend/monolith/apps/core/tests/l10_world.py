"""L10 final acceptance: one world in which a parcel goes from a request to a payout.

Every step a person takes goes through the HTTP API they use, with the client
they would use; only what a person cannot do from the app is done the way the
platform does it: staff decisions through the console's own service, durable
jobs through `run_due_jobs`, and the passage of time with `freeze_at` (the
clock every service reads). No row is written by hand to move a deal on.

The geography is L3A's test world (`SeaWorld`): the launch countries, the two
airports, the Algerian cities with coordinates and the Marseille ferry line.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models import Sum
from django.urls import reverse
from rest_framework.test import APIClient

from apps.admin_panel.permissions import assign_admin_roles
from apps.admin_panel.services import review_flight_proof
from apps.deals.models import Deal
from apps.deals.tests.phase4_factories import enable_mock_rail, freeze_at
from apps.finance.jobs import run_due_jobs
from apps.finance.models import LedgerAccount, LedgerEntry, PaymentOrder, Payout
from apps.finance.services import complete_manual_payout
from apps.finance.tests.factories import pay_order_with_mock
from apps.handover.models import DealHandoverCode
from apps.notifications.models import OutboundMessage
from apps.parcels.models import DeliveryRequest, ParcelMedia
from apps.trips.models import Journey, JourneyLeg, JourneyLegProgress
from apps.trips.tests.sea_world import DRIVE, FLIGHT, SEA, SeaWorld

__all__ = ["AcceptanceWorld", "DRIVE", "FLIGHT", "SEA", "api"]


def refusal_code(response) -> str | None:
    code = response.data.get("code") if hasattr(response.data, "get") else None
    return code[0] if isinstance(code, list) else code


def api(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


class AcceptanceWorld(SeaWorld):
    """People, trips and parcels for the L10 scenarios, driven through the API."""

    def build_acceptance_world(self) -> None:
        self.build_sea_world()
        enable_mock_rail()
        self.traveler = self.person("l10-traveler@example.com")
        self.traveler.full_name = "Yacine Bensalah"
        self.traveler.save(update_fields=["full_name"])
        self.sender = self.person("l10-sender@example.com")
        self.sender.full_name = "Samira Haddadine"
        self.sender.is_email_verified = True
        self.sender.save(update_fields=["full_name", "is_email_verified"])
        self.trust = self.staff("l10-trust@example.com", "trust_verification")
        self.finance = self.staff("l10-finance@example.com", "finance")
        self.ops = self.staff("l10-ops@example.com", "ops")

    def staff(self, email: str, role: str):
        user = self.person(email, verified=False)
        user.is_staff = True
        user.save(update_fields=["is_staff"])
        assign_admin_roles(user, [role])
        return user

    # -- the traveler -------------------------------------------------------

    def leg_payload(
        self, mode, origin, destination, depart, hours: int = 2, **extra
    ) -> dict:
        leg = {
            "mode": mode,
            "origin_place_id": origin.pk,
            "destination_place_id": destination.pk,
            "depart_at": depart.isoformat(),
            "arrive_at": (depart + timedelta(hours=hours)).isoformat(),
            "capacity_kg": "10.00",
        }
        if mode == FLIGHT:
            leg["flight_number"] = "AH1006"
        leg.update(extra)
        return leg

    def post_trip(self, legs: list[dict], **extra) -> Journey:
        for position, leg in enumerate(legs):
            leg["position"] = position
        payload = {
            "start_place_id": legs[0]["origin_place_id"],
            "destination_place_id": legs[-1]["destination_place_id"],
            "notes": "",
            "legs": legs,
            **extra,
        }
        response = api(self.traveler).post(
            reverse("journeys-list-create"), payload, format="json"
        )
        assert response.status_code == 201, response.data
        return Journey.objects.get(pk=response.data["id"])

    def publish(self, journey: Journey) -> None:
        response = api(journey.traveler).post(
            reverse("journeys-publish", args=(journey.pk,))
        )
        assert response.status_code == 200, response.data
        journey.refresh_from_db()
        assert journey.status == Journey.Status.ACTIVE, journey.status

    def upload_ticket(self, leg: JourneyLeg) -> int:
        upload = SimpleUploadedFile(
            "ticket.jpg", b"l10-ticket", content_type="image/jpeg"
        )
        with (
            patch("apps.trips.views.image_bytes_match_extension", return_value=True),
            patch("apps.trips.views.put_object"),
        ):
            response = api(leg.journey.traveler).post(
                reverse("journey-leg-proof-create", args=(leg.journey_id, leg.pk)),
                {"photo": upload, "kind": "ticket"},
                format="multipart",
            )
        assert response.status_code == 201, response.data
        return response.data["id"]

    def approve_ticket(self, proof_id: int) -> None:
        review_flight_proof(actor=self.trust, proof_id=proof_id, decision="approved")

    def set_price(self, journey: Journey, per_kg: int, minimum: int) -> None:
        response = api(journey.traveler).patch(
            reverse("journeys-pricing", args=(journey.pk,)),
            {"price_per_kg_eur_cents": per_kg, "min_price_eur_cents": minimum},
            format="json",
        )
        assert response.status_code == 200, response.data

    # -- the sender ---------------------------------------------------------

    def post_parcel(
        self, origin, destination, *, ready_from, ready_until, deliver_by, weight="2.00"
    ) -> DeliveryRequest:
        photo = ParcelMedia.objects.create(
            parcel=None,
            uploaded_by=self.sender,
            purpose=ParcelMedia.Purpose.ITEM_PHOTO,
            bucket="shiptrip-parcel-test",
            object_key=f"parcels/staged/{self.sender.pk}/{uuid4().hex}.jpg",
            content_type="image/jpeg",
            bytes=2048,
        )
        response = api(self.sender).post(
            reverse("parcels-delivery-v1-create"),
            {
                "pickup_place_id": origin.pk,
                "delivery_place_id": destination.pk,
                "ready_window_start": ready_from.isoformat(),
                "ready_window_end": ready_until.isoformat(),
                "deadline_at": deliver_by.isoformat(),
                "actual_weight_kg": weight,
                "length_cm": "20",
                "width_cm": "15",
                "height_cm": "10",
                "declared_value_eur_cents": 10_000,
                "sender_proposed_reward_eur_cents": 1_500,
                "title": "Urgent documents",
                "description": "A sealed folder needed today.",
                "category": "documents",
                "handling_notes": "",
                "fragile": False,
                "description_is_accurate": True,
                "item_is_legal": True,
                "no_prohibited_goods": True,
                "declared_value_is_accurate": True,
                "customs_responsibilities_understood": True,
                "item_photo_media_id": photo.pk,
            },
            format="json",
        )
        assert response.status_code == 201, response.data
        parcel = DeliveryRequest.objects.get(pk=response.data["id"])
        self.tracking = response.data["tracking_number"]
        assert self.tracking and self.tracking == parcel.tracking_number
        return parcel

    def pay_deposit(self, parcel: DeliveryRequest) -> None:
        order = PaymentOrder.objects.get(
            delivery_request=parcel, purpose=PaymentOrder.Purpose.POSTING_DEPOSIT
        )
        pay_order_with_mock(APIClient(), order)
        parcel.refresh_from_db()

    def propose(self, parcel, journey, first_leg, last_leg, reward: int) -> dict:
        response = api(self.sender).post(
            reverse("matches-propose-v1"),
            {
                "parcel_id": parcel.pk,
                "journey_id": journey.pk,
                "start_leg_id": first_leg.pk,
                "end_leg_id": last_leg.pk,
                "traveler_reward_eur_cents": reward,
            },
            format="json",
        )
        assert response.status_code == 201, response.data
        return response.data

    def accept(self, offer: dict) -> Deal:
        response = api(self.traveler).post(
            reverse("offers-accept", args=(offer["id"],)), {}, format="json"
        )
        assert response.status_code in (200, 201), response.data
        return Deal.objects.get(pk=response.data["id"])

    def pay_balance(self, deal: Deal) -> None:
        response = api(self.sender).get(
            reverse("finance-deal-payment", args=(deal.pk,))
        )
        assert response.status_code == 200, response.data
        order = PaymentOrder.objects.get(
            deal=deal, purpose=PaymentOrder.Purpose.DEAL_BALANCE
        )
        pay_order_with_mock(APIClient(), order)
        deal.refresh_from_db()
        assert deal.status == Deal.Status.FUNDED, deal.status

    # -- the handover -------------------------------------------------------

    def set_recipient(self, deal: Deal) -> None:
        response = api(self.sender).put(
            reverse("deals-recipient", args=(deal.pk,)),
            {
                "full_name": "Amina Recipient",
                "email": "l10-recipient@example.invalid",
                "phone": "+213555000111",
            },
            format="json",
        )
        assert response.status_code in (200, 201), response.data
        deal.refresh_from_db()
        assert deal.status == Deal.Status.PICKUP_READY, deal.status

    def pick_up(self, deal: Deal) -> None:
        code = api(self.sender).get(reverse("handover-pickup-code", args=(deal.pk,)))
        assert code.status_code == 200, code.data
        response = api(self.traveler).post(
            reverse("handover-pickup-submit", args=(deal.pk,)),
            {"code": code.data["code"]},
            format="json",
        )
        assert response.status_code == 200, response.data
        deal.refresh_from_db()
        assert deal.status == Deal.Status.IN_TRANSIT, deal.status

    def report(self, leg: JourneyLeg, kind: str, *, at) -> None:
        with freeze_at(at):
            response = api(self.traveler).post(
                reverse("journey-leg-progress", args=(leg.journey_id, leg.pk)),
                {"kind": kind},
                format="json",
            )
        assert response.status_code in (200, 201), response.data

    def deliver(self, deal: Deal, *, at=None) -> str:
        """Release the code when the 30 minutes are up, then the recipient reads it out.

        ``at`` is when the traveler reaches the recipient; it is never before
        the code's own release instant.
        """

        deal.refresh_from_db()
        assert deal.delivery_code_available_at - deal.pickup_confirmed_at == timedelta(
            minutes=30
        )
        at = max(
            at or deal.delivery_code_available_at, deal.delivery_code_available_at
        ) + timedelta(seconds=1)
        url = reverse("handover-delivery-code", args=(deal.pk,))
        traveler_try = api(self.traveler).get(url)
        assert traveler_try.status_code == 403, traveler_try.data
        assert refusal_code(traveler_try) == "not_authorized", traveler_try.data
        # One second before the 30 minutes are up the code is still locked,
        # even after the release job has run.
        with freeze_at(deal.delivery_code_available_at - timedelta(seconds=1)):
            run_due_jobs(limit=50)
            early = api(self.sender).get(url)
        assert early.status_code == 409, early.data
        assert refusal_code(early) == "delivery_code_buffer_open", early.data
        with freeze_at(at):
            run_due_jobs(limit=50)
            code = api(self.sender).get(
                reverse("handover-delivery-code", args=(deal.pk,))
            )
            assert code.status_code == 200, code.data
            assert (
                api(self.traveler)
                .get(reverse("handover-delivery-code", args=(deal.pk,)))
                .status_code
                == 403
            )
            response = api(self.traveler).post(
                reverse("handover-delivery-submit", args=(deal.pk,)),
                {"code": code.data["code"]},
                format="json",
            )
        assert response.status_code == 200, response.data
        deal.refresh_from_db()
        assert deal.status == Deal.Status.PROTECTION_WINDOW, deal.status
        assert DealHandoverCode.objects.filter(deal=deal).exists()
        return code.data["code"]

    def emails_for(self, deal: Deal) -> list[OutboundMessage]:
        return list(OutboundMessage.objects.filter(deal=deal).order_by("pk"))

    # -- the whole journey of one parcel ------------------------------------

    def carry(self, journey, parcel, first_leg, last_leg) -> Deal:
        """Discovery, the listed price, payment, handover, protection, payout."""

        legs = list(journey.legs.order_by("position"))
        tracking = parcel.tracking_number

        # Discovery: the trip is on Home with its price, and Find Travelers
        # names the listed price for this parcel.
        listing = api(self.sender).get(reverse("discovery-trips"))
        assert listing.status_code == 200, listing.data
        row = next(r for r in listing.data["results"] if r["journey_id"] == journey.pk)
        assert row["price"]["price_per_kg_eur_cents"] == journey.price_per_kg_eur_cents
        found = api(self.sender).get(
            reverse("matches-find-travelers-v1"), {"parcel_id": parcel.pk}
        )
        assert found.status_code == 200, found.data
        rows = [r for r in found.data["results"] if r["journey_id"] == journey.pk]
        if not rows:
            from apps.matching.discovery import explain_candidate

            raise AssertionError(
                explain_candidate(delivery_request_id=parcel.pk, journey_id=journey.pk)
            )
        candidate = rows[0]
        listed = candidate["economics"]["listed"]
        assert (
            listed["reward_eur_cents"]
            >= candidate["economics"]["minimum_reward_eur_cents"]
        )

        # The sender proposes first, at the listed price; the traveler accepts.
        offer = self.propose(
            parcel, journey, first_leg, last_leg, listed["reward_eur_cents"]
        )
        assert offer["tracking_number"] == tracking
        deal = self.accept(offer)
        assert deal.terms.traveler_reward_minor == listed["reward_eur_cents"]

        # Exact places stay hidden until the deal is funded.
        self.pay_balance(deal)
        detail = api(self.traveler).get(reverse("deals-detail", args=(deal.pk,)))
        assert detail.status_code == 200 and detail.data["tracking_number"] == tracking

        # Handover: the sender's pickup code, the traveler's reports.
        self.set_recipient(deal)
        self.pick_up(deal)
        last = legs.index(last_leg)
        for leg in legs[: last + 1]:  # reports follow the trip's order
            self.report(
                leg,
                JourneyLegProgress.Kind.DEPARTED,
                at=leg.depart_at + timedelta(minutes=5),
            )
            self.report(
                leg,
                JourneyLegProgress.Kind.ARRIVED,
                at=leg.arrive_at + timedelta(minutes=5),
            )
        deal.refresh_from_db()
        assert (
            deal.status == Deal.Status.IN_TRANSIT
        ), "a progress report never moves a deal"
        timeline = api(self.sender).get(reverse("deals-detail", args=(deal.pk,))).data
        assert timeline["status"] == Deal.Status.IN_TRANSIT

        # The recipient's code; the traveler can never read it.
        self.deliver(deal, at=last_leg.arrive_at + timedelta(minutes=20))

        # Protection: 48 hours, then the payout becomes payable once.
        payout = Payout.objects.get(deal=deal)
        assert payout.status == Payout.Status.NOT_ELIGIBLE
        deal.refresh_from_db()
        assert deal.protection_ends_at - deal.delivery_confirmed_at == timedelta(
            hours=48
        )
        with freeze_at(deal.protection_ends_at - timedelta(seconds=1)):
            run_due_jobs(limit=50)
        payout.refresh_from_db()
        assert payout.status == Payout.Status.NOT_ELIGIBLE
        with freeze_at(deal.protection_ends_at + timedelta(seconds=1)):
            run_due_jobs(limit=50)
        payout.refresh_from_db()
        assert payout.status == Payout.Status.ELIGIBLE, payout.status
        assert payout.amount_eur_cents == listed["reward_eur_cents"]

        # Finance settles once the payout is due, never during protection.
        with freeze_at(deal.protection_ends_at + timedelta(seconds=2)):
            paid = complete_manual_payout(
                payout_id=payout.pk,
                admin_actor_id=self.finance.pk,
                payout_currency="EUR",
                payout_amount_minor=payout.amount_eur_cents,
                reference=f"L10-{deal.pk}",
            )
        assert paid.status == Payout.Status.PAID
        assert paid.paid_at > deal.protection_ends_at, (
            paid.paid_at,
            deal.protection_ends_at,
        )
        mine = api(self.traveler).get(reverse("finance-payouts"))
        assert mine.status_code == 200, mine.data
        assert tracking in str(mine.data)
        # Every cent is accounted for: what the deal held and what the
        # traveler was owed are both discharged, and Wassla kept its fee.
        balances = {
            row["account"]: row["n"]
            for row in LedgerEntry.objects.filter(deal_id=deal.pk)
            .values("account")
            .annotate(n=Sum("amount_eur_cents"))
        }
        assert balances.get(LedgerAccount.DEAL_FUNDS, 0) == 0, balances
        assert balances.get(LedgerAccount.TRAVELER_PAYABLE, 0) == 0, balances
        assert (
            balances.get(LedgerAccount.PLATFORM_COMMISSION)
            == -deal.terms.platform_fee_minor
        ), balances
        deal.refresh_from_db()
        return deal
