"""Shared fixtures for the Phase 3 financial tests.

`build_scenario` produces the smallest world in which real money can move: one
sender, one KYC-approved traveler, one active single-leg DRIVE journey and one
V1 delivery request whose pickup and dropoff sit on that corridor. From there a
test can run the genuine negotiation path — sender proposes, traveler accepts —
and get a real Deal with real terms, rather than a hand-assembled row that no
service would ever produce.

Everything here goes through the production services. That is the point: a test
that fabricates a Deal directly would pass while the acceptance path silently
stopped creating a balance obligation.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from apps.accounts.models import User
from apps.core.models import BusinessSettingsVersion
from apps.deals.models import Deal
from apps.kyc.models import KycSubmission
from apps.locations.models import Location
from apps.matching.models import Offer
from apps.matching.v1_services import accept_offer, create_sender_offer
from apps.parcels.models import DeliveryRequest, ParcelRequest
from apps.trips.models import Journey, JourneyLeg

from apps.finance.models import PaymentAttempt, PaymentOrder
from apps.finance.policy import Phase3Policy, phase3_policy
from apps.finance.providers.mock import MOCK_WEBHOOK_SECRET


def make_user(email: str, *, is_staff: bool = False) -> User:
    return User.objects.create_user(
        username=email,
        email=email,
        password="Sup3rStrongPass!",
        full_name=email.split("@")[0],
        is_staff=is_staff,
    )


def make_location(
    label: str,
    latitude: str,
    longitude: str,
    *,
    owner: User | None = None,
    country_code: str = "DZ",
) -> Location:
    return Location.objects.create(
        kind=Location.Kind.MAP_POINT,
        normalized_label=f"normalized {label}",
        public_label=label,
        private_label=f"private address {label}",
        city=label,
        country_code=country_code,
        latitude=Decimal(latitude),
        longitude=Decimal(longitude),
        coarse_latitude=Decimal(latitude).quantize(Decimal("0.1")),
        coarse_longitude=Decimal(longitude).quantize(Decimal("0.1")),
        provider="fixture-provider",
        provider_place_id=f"place-{label}",
        owner=owner,
        created_by=owner,
    )


def approve_kyc(user: User, suffix: str) -> None:
    KycSubmission.objects.create(
        user=user,
        document_type=KycSubmission.DocumentType.PASSPORT,
        idempotency_key=f"{suffix:0<32}"[:32],
        front_image_key=f"kyc/{suffix}/front.jpg",
        status=KycSubmission.Status.APPROVED,
        reviewed_at=timezone.now(),
    )


@dataclass
class Scenario:
    sender: User
    traveler: User
    outsider: User
    admin: User
    journey: Journey
    leg: JourneyLeg
    delivery_request: DeliveryRequest
    policy: Phase3Policy

    #: Populated once `accept()` has run.
    offer: Offer | None = None
    deal: Deal | None = None

    def balance_order(self) -> PaymentOrder:
        assert self.deal is not None, "Call accept() first."
        return PaymentOrder.objects.get(
            deal=self.deal, purpose=PaymentOrder.Purpose.DEAL_BALANCE
        )

    def deposit_order(self) -> PaymentOrder | None:
        return (
            PaymentOrder.objects.filter(
                delivery_request=self.delivery_request,
                purpose=PaymentOrder.Purpose.POSTING_DEPOSIT,
            )
            .exclude(status=PaymentOrder.Status.CANCELLED)
            .first()
        )

    def propose(self, *, reward_eur_cents: int = 2_000) -> Offer:
        self.offer = create_sender_offer(
            sender=self.sender,
            delivery_request=self.delivery_request,
            journey=self.journey,
            start_leg_id=self.leg.pk,
            end_leg_id=self.leg.pk,
            traveler_reward_eur_cents=reward_eur_cents,
        )
        return self.offer

    def accept(self, *, reward_eur_cents: int = 2_000) -> Deal:
        if self.offer is None:
            self.propose(reward_eur_cents=reward_eur_cents)
        accepted = accept_offer(pending_offer=self.offer, actor=self.traveler)
        self.deal = accepted.deal
        self.delivery_request.refresh_from_db()
        return self.deal


def build_scenario(*, prefix: str = "fin", open_request: bool = True) -> Scenario:
    """One sender, one traveler, one corridor, one matchable request.

    `open_request=True` creates the request already published, which is what a
    test that only cares about the deal balance wants. A deposit test passes
    `False` and drives publication through a real payment instead.
    """

    at = timezone.now()
    sender = make_user(f"{prefix}-sender@example.com")
    traveler = make_user(f"{prefix}-traveler@example.com")
    outsider = make_user(f"{prefix}-outsider@example.com")
    admin = make_user(f"{prefix}-admin@example.com", is_staff=True)
    approve_kyc(traveler, f"{prefix}-traveler")

    origin = make_location(f"{prefix} origin", "36.700000", "4.000000")
    destination = make_location(f"{prefix} destination", "36.800000", "4.200000")
    pickup = make_location(
        f"{prefix} pickup", "36.705000", "4.010000", owner=sender
    )
    dropoff = make_location(
        f"{prefix} dropoff", "36.795000", "4.190000", owner=sender
    )

    journey = Journey.objects.create(
        traveler=traveler,
        start_location=origin,
        destination_location=destination,
        status=Journey.Status.ACTIVE,
        published_at=at,
    )
    leg = JourneyLeg.objects.create(
        journey=journey,
        position=0,
        mode=JourneyLeg.Mode.DRIVE,
        origin=origin,
        destination=destination,
        depart_at=at + timedelta(hours=2),
        arrive_at=at + timedelta(hours=8),
        capacity_kg=Decimal("20.00"),
        distance_meters=240_000,
    )
    delivery_request = DeliveryRequest.objects.create(
        sender=sender,
        kind=ParcelRequest.Kind.DELIVERY,
        schema_version=2,
        status=(
            ParcelRequest.Status.OPEN
            if open_request
            else ParcelRequest.Status.AWAITING_DEPOSIT
        ),
        pickup_location=pickup,
        delivery_location=dropoff,
        ready_window_start=at,
        ready_window_end=at + timedelta(hours=10),
        deadline_at=at + timedelta(hours=30),
        actual_weight_kg=Decimal("2.00"),
        length_cm=Decimal("20"),
        width_cm=Decimal("20"),
        height_cm=Decimal("20"),
        declared_value_eur_cents=10_000,
        traveler_reward_eur_cents=2_000,
        title="Phase 3 parcel",
        description="Safe test parcel",
        category=ParcelRequest.ItemType.DOCUMENTS,
        item_type=ParcelRequest.ItemType.DOCUMENTS,
        description_is_accurate=True,
        item_is_legal=True,
        no_prohibited_goods=True,
        declared_value_is_accurate=True,
        customs_responsibilities_understood=True,
    )
    return Scenario(
        sender=sender,
        traveler=traveler,
        outsider=outsider,
        admin=admin,
        journey=journey,
        leg=leg,
        delivery_request=delivery_request,
        policy=phase3_policy(),
    )


def active_settings() -> BusinessSettingsVersion:
    return BusinessSettingsVersion.objects.get(status="active")


# --- mock provider webhook helpers -------------------------------------------


def mock_event_body(
    *,
    event_id: str,
    outcome: str,
    session_id: str = "",
    payment_id: str = "",
    reference: str = "",
    amount: int | None = None,
    currency: str = "EUR",
    event_type: str = "checkout.updated",
    guest_email: str = "",
    failure_code: str = "",
) -> bytes:
    return json.dumps(
        {
            "id": event_id,
            "type": event_type,
            "outcome": outcome,
            "data": {
                "session_id": session_id,
                "payment_id": payment_id,
                "reference": reference,
                "amount": amount,
                "currency": currency,
                "guest_email": guest_email,
                "failure_code": failure_code,
            },
        },
        separators=(",", ":"),
    ).encode("utf-8")


def mock_signature(raw_body: bytes, *, secret: str = MOCK_WEBHOOK_SECRET) -> str:
    return hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()


def succeed_attempt(
    attempt: PaymentAttempt,
    *,
    event_id: str | None = None,
    amount_minor: int | None = None,
) -> bytes:
    """Build a signed mock 'paid' event for one attempt."""

    return mock_event_body(
        event_id=event_id or f"evt_{attempt.pk}_paid",
        outcome="succeeded",
        session_id=attempt.provider_session_id,
        payment_id=f"{attempt.provider_session_id}_pi",
        reference=str(attempt.order.public_reference),
        amount=(
            amount_minor
            if amount_minor is not None
            else int(attempt.provider_amount_minor)
        ),
        currency=attempt.payment_currency,
        event_type="checkout.paid",
    )


def open_mock_checkout(order: PaymentOrder, **kwargs) -> PaymentAttempt:
    """Start a real checkout on the test rail and return the attempt."""

    from apps.finance.services import start_checkout

    session = start_checkout(
        order_id=order.pk,
        provider="mock",
        actor_id=kwargs.pop("actor_id", order.owner_id),
        **kwargs,
    )
    return session.attempt


def deliver_mock_webhook(client, raw_body: bytes, *, signature: str | None = None):
    """POST a signed mock provider event through the real webhook endpoint.

    Deliberately the HTTP path, not a direct service call: signature
    verification, raw-body handling and the idempotency insert are part of what
    is under test.
    """

    from django.urls import reverse

    return client.post(
        reverse("finance-webhook-mock"),
        data=raw_body,
        content_type="application/json",
        HTTP_X_MOCK_SIGNATURE=(
            signature if signature is not None else mock_signature(raw_body)
        ),
    )


def pay_order_with_mock(client, order: PaymentOrder, **kwargs) -> PaymentAttempt:
    """Open a checkout and settle it through a signed provider event."""

    attempt = open_mock_checkout(order, **kwargs)
    response = deliver_mock_webhook(client, succeed_attempt(attempt))
    assert response.status_code == 200, response.content
    attempt.refresh_from_db()
    return attempt
