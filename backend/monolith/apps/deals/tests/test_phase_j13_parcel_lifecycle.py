"""J1.3: real acceptance/handover plus historical and replay boundaries."""

from importlib import import_module

from django.apps import apps
from django.contrib.admin import AdminSite
from django.db import transaction
from django.test import RequestFactory, TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.financial_locks import lock_deal_lifecycle
from apps.deals import lifecycle
from apps.deals.activity import activity_state
from apps.deals.cancellation import CancellationError, cancel_funded_deal
from apps.deals.models import Deal, DealEvent
from apps.deals.services import cancel_pending_deal
from apps.finance.tests.factories import build_scenario
from apps.parcels.lifecycle import sync_request_status, with_lifecycle
from apps.parcels.admin import (
    DeliveryRequestAdmin,
    ParcelRequestAdmin,
    RequestStatusFilter,
)
from apps.parcels.models import DeliveryRequest, ParcelRequest

from .phase4_factories import (
    confirm_delivery,
    confirm_pickup,
    fund_scenario,
    record_recipient,
    release_delivery_code,
)


class ParcelLifecycleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from apps.finance.tests.test_phase4_concurrency import _seed_phase4_settings

        _seed_phase4_settings()
        import_module(
            "apps.core.migrations.0009_seed_boost_economics"
        ).seed_boost_economics(apps, None)
        cls.scenario = fund_scenario(APIClient(), prefix="j13")

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.scenario.sender)
        self.request_id = self.scenario.delivery_request.pk

    def assert_status(self, expected, *, stored=True):
        rows = ParcelRequest.objects.filter(pk=self.request_id)
        if stored:
            self.assertEqual(rows.get().status, expected)
        self.assertEqual(with_lifecycle(rows).get().lifecycle_status, expected)
        # The same annotation supports the multi-table child admin queryset.
        self.assertEqual(
            with_lifecycle(DeliveryRequest.objects.filter(pk=self.request_id))
            .get()
            .lifecycle_status,
            expected,
        )
        detail = self.client.get(f"/api/parcels/{self.request_id}")
        self.assertEqual(detail.status_code, 200, detail.data)
        self.assertEqual(detail.data["status"], expected)
        response = self.client.get("/api/parcels", {"status": expected})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn(self.request_id, [row["id"] for row in response.data])
        if expected != "matched":
            self.assertNotIn(
                self.request_id,
                [
                    row["id"]
                    for row in self.client.get(
                        "/api/parcels", {"status": "matched"}
                    ).data
                ],
            )

    def deliver(self):
        record_recipient(self.scenario)
        confirm_pickup(self.scenario)
        release_delivery_code(self.scenario)
        confirm_delivery(self.scenario)

    def test_real_progression_and_duplicate_events(self):
        stale = self.scenario.deal
        self.assert_status("matched")
        record_recipient(self.scenario)
        self.assert_status("matched")
        confirm_pickup(self.scenario)
        self.assert_status("in_transit")
        release_delivery_code(self.scenario)
        confirm_delivery(self.scenario)
        self.assert_status("delivered")
        self.assertEqual(activity_state(self.scenario.deal), "completed")
        with transaction.atomic():
            aggregate = lock_deal_lifecycle(self.scenario.deal.pk)
            before = DealEvent.objects.filter(deal=aggregate.deal).count()
            self.assertFalse(
                lifecycle.apply_pickup_confirmed(
                    aggregate, actor_id=self.scenario.traveler.pk
                ).changed
            )
            self.assertFalse(
                lifecycle.apply_delivery_confirmed(
                    aggregate, actor_id=self.scenario.traveler.pk
                ).changed
            )
            self.assertEqual(
                DealEvent.objects.filter(deal=aggregate.deal).count(), before
            )
            self.assert_status("delivered")
            lifecycle.apply_completed(
                aggregate,
                reason="protection_elapsed",
                at=aggregate.deal.protection_ends_at,
            )
            before = DealEvent.objects.filter(deal=aggregate.deal).count()
            self.assertFalse(
                lifecycle.apply_completed(
                    aggregate, reason="protection_elapsed"
                ).changed
            )
            self.assertEqual(
                DealEvent.objects.filter(deal=aggregate.deal).count(), before
            )
            updated = ParcelRequest.objects.get(pk=self.request_id).updated_at
            self.assertEqual(sync_request_status(aggregate.deal), 0)
            self.assertEqual(
                ParcelRequest.objects.get(pk=self.request_id).updated_at, updated
            )
        self.assert_status("completed")
        self.assertEqual(sync_request_status(stale), 0)

    def test_acceptance_release_and_rematch(self):
        scenario = build_scenario(prefix="j13-rematch")
        self.assertEqual(scenario.delivery_request.status, "open")
        old = scenario.accept()
        self.assertEqual(scenario.delivery_request.status, "matched")
        cancel_pending_deal(deal_id=old.pk, actor_id=scenario.sender.pk)
        scenario.delivery_request.refresh_from_db()
        self.assertEqual(scenario.delivery_request.status, "open")
        self.assertEqual(
            with_lifecycle(
                ParcelRequest.objects.filter(pk=scenario.delivery_request.pk)
            )
            .get()
            .lifecycle_status,
            "open",
        )
        # Same request can accept a subsequent offer; old events cannot own it.
        scenario.offer = None
        scenario.accept()
        self.assertNotEqual(old.pk, scenario.deal.pk)
        self.assertEqual(sync_request_status(old), 0)
        self.assertEqual(
            with_lifecycle(
                ParcelRequest.objects.filter(pk=scenario.delivery_request.pk)
            )
            .get()
            .lifecycle_status,
            "matched",
        )

    def test_funded_cancellation_and_replay(self):
        cancel_funded_deal(
            deal_id=self.scenario.deal.pk, actor_id=self.scenario.traveler.pk
        )
        self.assert_status("cancelled")
        with self.assertRaises(CancellationError):
            cancel_funded_deal(
                deal_id=self.scenario.deal.pk, actor_id=self.scenario.traveler.pk
            )
        self.assert_status("cancelled")
        self.assertEqual(activity_state(self.scenario.deal), "cancelled")

    def test_refund_precedes_delivery_and_completion(self):
        self.deliver()
        for target in (Deal.Status.REFUNDED, Deal.Status.PARTIALLY_REFUNDED):
            with self.subTest(target=target), transaction.atomic():
                aggregate = lock_deal_lifecycle(self.scenario.deal.pk)
                lifecycle.apply_dispute_resolved(
                    aggregate, status=target, reason="admin_resolution", dispute_id=1
                )
                self.assert_status("cancelled")
                self.assertEqual(activity_state(aggregate.deal), "cancelled")
                self.assertEqual(sync_request_status(aggregate.deal), 0)

    def test_dispute_retains_physical_progress_and_can_complete_without_handover(self):
        record_recipient(self.scenario)
        confirm_pickup(self.scenario)
        with transaction.atomic():
            aggregate = lock_deal_lifecycle(self.scenario.deal.pk)
            lifecycle.apply_disputed(
                aggregate, dispute_id=1, actor_id=self.scenario.sender.pk
            )
            self.assert_status("in_transit")
            lifecycle.apply_dispute_resolved(
                aggregate,
                status=Deal.Status.COMPLETED,
                reason="traveler_performed",
                dispute_id=1,
            )
        self.assertIsNone(self.scenario.deal.delivery_confirmed_at)
        self.assert_status("completed")

    def test_historical_projection_is_read_only_and_owner_scoped(self):
        self.deliver()
        ParcelRequest.objects.filter(pk=self.request_id).update(status="matched")
        self.assert_status("delivered", stored=False)
        self.assertEqual(
            ParcelRequest.objects.get(pk=self.request_id).status, "matched"
        )
        Deal.objects.filter(pk=self.scenario.deal.pk).update(status="disputed")
        self.assert_status("delivered", stored=False)
        Deal.objects.filter(pk=self.scenario.deal.pk).update(
            status="refunded", completed_at=timezone.now()
        )
        self.assert_status("cancelled", stored=False)
        self.client.force_authenticate(self.scenario.outsider)
        public = self.client.get(f"/api/parcels/{self.request_id}")
        self.assertEqual(public.status_code, 200)
        self.assertEqual(public.data["status"], "cancelled")
        self.assertNotIn("private_label", public.data["pickup_location"])
        self.assertNotIn("private_label", public.data["delivery_location"])
        self.assertEqual(self.client.get("/api/parcels").data, [])

    def test_historical_cancellation_with_handover_evidence_beats_missing_funding(self):
        self.deliver()
        ParcelRequest.objects.filter(pk=self.request_id).update(status="matched")
        Deal.objects.filter(pk=self.scenario.deal.pk).update(
            status="cancelled",
            funded_at=None,
            funded_scheduled_arrival_floor_at=None,
            arrival_confirmed_at=None,
        )
        self.assert_status("cancelled", stored=False)

    def test_projection_does_not_regress_or_rewrite_unmatched_rows(self):
        for state in ("in_transit", "delivered", "completed", "cancelled", "expired"):
            ParcelRequest.objects.filter(pk=self.request_id).update(status=state)
            self.assertEqual(sync_request_status(self.scenario.deal), 0)
            self.assert_status(state)
        for state in ("open", "awaiting_deposit", "expired", "cancelled"):
            request = DeliveryRequest.objects.create(
                sender=self.scenario.sender, kind="delivery", status=state
            )
            self.assertEqual(
                with_lifecycle(ParcelRequest.objects.filter(pk=request.pk))
                .get()
                .lifecycle_status,
                state,
            )

    def test_rollback_rolls_back_request_and_deal_together(self):
        record_recipient(self.scenario)
        with transaction.atomic():
            confirm_pickup(self.scenario)
            self.assert_status("in_transit")
            transaction.set_rollback(True)
        self.assert_status("matched")
        self.assertEqual(self.scenario.deal.status, "pickup_ready")

    def test_admin_filters_and_discovery_exclusion(self):
        self.deliver()
        ParcelRequest.objects.filter(pk=self.request_id).update(status="matched")
        request = RequestFactory().get("/", {"status": "delivered"})
        for model, admin_class in (
            (ParcelRequest, ParcelRequestAdmin),
            (DeliveryRequest, DeliveryRequestAdmin),
        ):
            model_admin = admin_class(model, AdminSite())
            rows = model_admin.get_queryset(request)
            filter_ = RequestStatusFilter(
                request, {"status": ["delivered"]}, model, model_admin
            )
            with self.assertNumQueries(1):
                self.assertEqual(
                    [row.pk for row in filter_.queryset(request, rows)],
                    [self.request_id],
                )
            self.assertEqual(
                model_admin.request_status(rows.get(pk=self.request_id)), "Delivered"
            )
        self.scenario.base.admin.is_superuser = True
        self.scenario.base.admin.save(update_fields=["is_superuser"])
        self.client.force_authenticate(self.scenario.base.admin)
        response = self.client.get("/api/admin/requests", {"status": "delivered"})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["results"][0]["status"], "delivered")
        self.client.force_authenticate(self.scenario.traveler)
        response = self.client.get("/api/parcels/open")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertNotIn(self.request_id, [row["id"] for row in response.data])
