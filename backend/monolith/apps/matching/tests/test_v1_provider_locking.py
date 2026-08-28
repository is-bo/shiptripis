from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from importlib import import_module
from unittest.mock import patch

from django.conf import settings
from django.db import connection
from django.test import TransactionTestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.core.models import BusinessSettingsVersion
from apps.kyc.models import KycSubmission
from apps.locations.models import Location
from apps.matching.v1_services import accept_offer, counter_offer, create_sender_offer
from apps.parcels.models import DeliveryRequest, ParcelRequest
from apps.routing.testing import DeterministicFixtureRouteProvider
from apps.trips.models import Journey, JourneyLeg


class AtomicGuardRouteProvider(DeterministicFixtureRouteProvider):
    """A provider fake that turns route I/O under a transaction into a failure."""

    name = "atomic_guard"

    def directions(self, points, *, profile):
        if connection.in_atomic_block:
            raise AssertionError("Route-provider I/O occurred inside an atomic block.")
        return super().directions(points, profile=profile)


class V1ProviderLockBoundaryTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        # TransactionTestCase truncates tables between cases, so the
        # migration-seeded revision may be gone. Re-seed the *current* one —
        # acceptance now also needs the Phase 3 payment policy, exactly as
        # production has it.
        policy = import_module(
            "apps.core.migrations.0005_seed_phase3_payment_settings"
        ).PHASE3_POLICY
        if not BusinessSettingsVersion.objects.filter(
            status=BusinessSettingsVersion.Status.ACTIVE
        ).exists():
            BusinessSettingsVersion.objects.create(
                version=3,
                status=BusinessSettingsVersion.Status.ACTIVE,
                canonical_currency="EUR",
                commission_rate_bps=2500,
                pricing_version="v1-payments-1",
                policy=deepcopy(policy),
                activated_at=timezone.now(),
            )
        self.sender = User.objects.create_user(
            username="provider-lock-sender@example.com",
            email="provider-lock-sender@example.com",
            password="Sup3rStrongPass!",
        )
        self.traveler = User.objects.create_user(
            username="provider-lock-traveler@example.com",
            email="provider-lock-traveler@example.com",
            password="Sup3rStrongPass!",
        )
        KycSubmission.objects.create(
            user=self.traveler,
            document_type=KycSubmission.DocumentType.PASSPORT,
            idempotency_key="provider-lock-kyc-key-0000000000",
            front_image_key="kyc/provider-lock/front.jpg",
            status=KycSubmission.Status.APPROVED,
            reviewed_at=timezone.now(),
        )
        origin = self._location("Origin", "36.700000", "3.000000")
        destination = self._location("Destination", "36.800000", "3.000000")
        pickup = self._location("Pickup", "36.720000", "3.001000")
        delivery = self._location("Delivery", "36.780000", "3.001000")
        depart_at = timezone.now() + timedelta(days=2)
        self.journey = Journey.objects.create(
            traveler=self.traveler,
            start_location=origin,
            destination_location=destination,
            status=Journey.Status.ACTIVE,
            published_at=timezone.now(),
        )
        self.leg = JourneyLeg.objects.create(
            journey=self.journey,
            position=0,
            mode=JourneyLeg.Mode.DRIVE,
            origin=origin,
            destination=destination,
            depart_at=depart_at,
            arrive_at=depart_at + timedelta(hours=6),
            capacity_kg=Decimal("5.00"),
        )
        self.delivery_request = DeliveryRequest.objects.create(
            sender=self.sender,
            kind=ParcelRequest.Kind.DELIVERY,
            schema_version=2,
            pickup_location=pickup,
            delivery_location=delivery,
            ready_window_start=depart_at,
            ready_window_end=depart_at + timedelta(hours=2),
            deadline_at=depart_at + timedelta(hours=7),
            actual_weight_kg=Decimal("1.00"),
            length_cm=Decimal("20.00"),
            width_cm=Decimal("15.00"),
            height_cm=Decimal("10.00"),
            declared_value_eur_cents=10_000,
            traveler_reward_eur_cents=2_000,
            title="Provider lock boundary",
            description="Sealed documents",
            category=ParcelRequest.ItemType.DOCUMENTS,
            item_type=ParcelRequest.ItemType.DOCUMENTS,
            description_is_accurate=True,
            item_is_legal=True,
            no_prohibited_goods=True,
            declared_value_is_accurate=True,
            customs_responsibilities_understood=True,
            base_amount_dzd=None,
        )

    def _location(self, label: str, latitude: str, longitude: str) -> Location:
        return Location.objects.create(
            kind=Location.Kind.MAP_POINT,
            normalized_label=label,
            public_label=label,
            private_label=label,
            city=label,
            country_code="DZ",
            latitude=Decimal(latitude),
            longitude=Decimal(longitude),
            coarse_latitude=Decimal(latitude),
            coarse_longitude=Decimal(longitude),
            owner=self.sender if hasattr(self, "sender") else None,
            created_by=self.sender if hasattr(self, "sender") else None,
        )

    def test_route_provider_io_precedes_create_counter_and_accept_locks(self):
        provider = AtomicGuardRouteProvider()
        with patch(
            "apps.matching.v1_services.get_route_provider",
            return_value=provider,
        ) as provider_factory:
            proposal = create_sender_offer(
                sender=self.sender,
                delivery_request=self.delivery_request,
                journey=self.journey,
                start_leg_id=self.leg.pk,
                end_leg_id=self.leg.pk,
                traveler_reward_eur_cents=2_000,
            )
            calls_after_create = provider.call_counts["directions"]
            counter = counter_offer(
                pending_offer=proposal,
                actor=self.traveler,
                traveler_reward_eur_cents=2_200,
            )
            calls_after_counter = provider.call_counts["directions"]
            accepted = accept_offer(pending_offer=counter, actor=self.sender)

        self.assertGreater(calls_after_create, 0)
        self.assertGreater(calls_after_counter, calls_after_create)
        self.assertGreater(provider.call_counts["directions"], calls_after_counter)
        self.assertEqual(provider_factory.call_count, 3)
        for call in provider_factory.call_args_list:
            self.assertEqual(
                call.kwargs,
                {
                    "external_call_budget": (
                        settings.ROUTE_PROVIDER_MAX_EXTERNAL_CALLS_PER_MATCHING_REQUEST
                    )
                },
            )
        self.assertTrue(accepted.created)
