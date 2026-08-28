from __future__ import annotations

from datetime import timedelta

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


class Phase1LegacyPreservationMigrationTests(TransactionTestCase):
    """Prove the additive Phase 1 expansion preserves and reverses legacy rows."""

    migrate_from = [
        ("deals", None),
        ("matching", "0002_alter_matchevent_kind"),
        ("parcels", "0002_parcel_target_traveler"),
        ("trips", "0003_tripmedia"),
        ("locations", None),
        ("core", "0001_initial"),
        ("accounts", "0004_emailverificationcode"),
    ]
    migrate_to = [
        (
            "deals",
            "0002_remove_dealtermssnapshot_deals_terms_new_currency_eur_and_more",
        ),
        ("matching", "0005_remove_offer_offer_economics_consistent_and_more"),
        ("parcels", "0004_deliveryrequest_parcels_delivery_v1_no_dzd"),
        ("trips", "0004_journey_journeyleg_journeylegproof"),
        ("locations", "0002_remove_location_locations_provider_place_uniq_and_more"),
        ("core", "0003_seed_v1_business_settings"),
        ("accounts", "0004_emailverificationcode"),
    ]

    def _migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.migrate(targets)
        state_targets = [target for target in targets if target[1] is not None]
        return executor.loader.project_state(state_targets).apps

    def setUp(self):
        super().setUp()
        # Migration tests deliberately move the shared test database backwards.
        # Remember every current leaf so the cleanup below can restore the
        # schema for tests collected after this class, including migrations
        # added after Phase 1.
        self.latest_targets = MigrationExecutor(connection).loader.graph.leaf_nodes()
        # Register the restore *before* moving backwards. `tearDown` does not
        # run when `setUp` raises, and a half-migrated shared database breaks
        # every TransactionTestCase collected after this class with a bare
        # "no such table". A cleanup runs either way, and it runs before
        # Django's own `_post_teardown` flush, which needs the full schema.
        self.addCleanup(self._migrate, self.latest_targets)
        old_apps = self._migrate(self.migrate_from)
        User = old_apps.get_model("accounts", "User")
        Airport = old_apps.get_model("trips", "Airport")
        Trip = old_apps.get_model("trips", "Trip")
        DeliveryRequest = old_apps.get_model("parcels", "DeliveryRequest")
        ProductRequest = old_apps.get_model("parcels", "ProductRequest")
        Match = old_apps.get_model("matching", "Match")
        Offer = old_apps.get_model("matching", "Offer")

        sender = User.objects.create(
            username="migration-sender@example.com",
            email="migration-sender@example.com",
            full_name="Migration Sender",
            password="!",
        )
        traveler = User.objects.create(
            username="migration-traveler@example.com",
            email="migration-traveler@example.com",
            full_name="Migration Traveler",
            password="!",
        )
        alg, _ = Airport.objects.get_or_create(
            iata="ALG",
            defaults={
                "city": "Algiers",
                "name": "Houari Boumediene",
                "country": "DZ",
            },
        )
        cdg, _ = Airport.objects.get_or_create(
            iata="CDG",
            defaults={
                "city": "Paris",
                "name": "Charles de Gaulle",
                "country": "FR",
            },
        )
        trip = Trip.objects.create(
            traveler=traveler,
            origin=alg,
            destination=cdg,
            departure_at=timezone.now() + timedelta(days=3),
            capacity_kg=12,
            flight_number="AH1000",
        )
        delivery = DeliveryRequest.objects.create(
            sender=sender,
            kind="delivery",
            origin=alg,
            destination=cdg,
            weight_kg=2,
            item_type="documents",
            base_amount_dzd=4_000,
        )
        product = ProductRequest.objects.create(
            sender=sender,
            kind="product",
            origin=cdg,
            destination=alg,
            weight_kg=1,
            item_type="electronics",
            product_price_dzd=25_000,
        )
        match = Match.objects.create(
            parcel=delivery,
            trip=trip,
            sender=sender,
            traveler=traveler,
        )
        # `economics_version` and `currency` do not exist yet at
        # matching.0002 — Phase 1 adds them in matching.0003 with the legacy
        # defaults. Setting them here would be testing the new schema against
        # the old one; the forward assertions below check the backfill instead.
        offer = Offer.objects.create(
            match=match,
            proposed_by="traveler",
            proposer=traveler,
            base_amount_dzd=4_000,
            commission_dzd=1_000,
            total_dzd=5_000,
        )
        self.legacy = {
            "trip": trip.pk,
            "delivery": delivery.pk,
            "product": product.pk,
            "offer": offer.pk,
        }

    def test_forward_and_reverse_preserve_legacy_identity_and_economics(self):
        new_apps = self._migrate(self.migrate_to)
        Trip = new_apps.get_model("trips", "Trip")
        Journey = new_apps.get_model("trips", "Journey")
        DeliveryRequest = new_apps.get_model("parcels", "DeliveryRequest")
        ProductRequest = new_apps.get_model("parcels", "ProductRequest")
        Offer = new_apps.get_model("matching", "Offer")
        Deal = new_apps.get_model("deals", "Deal")

        trip = Trip.objects.get(pk=self.legacy["trip"])
        delivery = DeliveryRequest.objects.get(pk=self.legacy["delivery"])
        product = ProductRequest.objects.get(pk=self.legacy["product"])
        offer = Offer.objects.get(pk=self.legacy["offer"])
        self.assertEqual((trip.origin_id, trip.destination_id), ("ALG", "CDG"))
        self.assertEqual(delivery.base_amount_dzd, 4_000)
        self.assertEqual(delivery.schema_version, 1)
        self.assertEqual(product.product_price_dzd, 25_000)
        self.assertEqual(offer.economics_version, "legacy_dzd")
        self.assertEqual(offer.currency, "DZD")
        self.assertEqual(offer.total_dzd, 5_000)
        self.assertEqual(Journey.objects.count(), 0)
        self.assertEqual(Deal.objects.count(), 0)

        old_apps = self._migrate(self.migrate_from)
        OldTrip = old_apps.get_model("trips", "Trip")
        OldDelivery = old_apps.get_model("parcels", "DeliveryRequest")
        OldProduct = old_apps.get_model("parcels", "ProductRequest")
        OldOffer = old_apps.get_model("matching", "Offer")
        self.assertEqual(
            (
                OldTrip.objects.get(pk=self.legacy["trip"]).origin_id,
                OldTrip.objects.get(pk=self.legacy["trip"]).destination_id,
            ),
            ("ALG", "CDG"),
        )
        self.assertEqual(
            OldDelivery.objects.get(pk=self.legacy["delivery"]).base_amount_dzd,
            4_000,
        )
        self.assertEqual(
            OldProduct.objects.get(pk=self.legacy["product"]).product_price_dzd,
            25_000,
        )
        self.assertEqual(
            OldOffer.objects.get(pk=self.legacy["offer"]).total_dzd,
            5_000,
        )
