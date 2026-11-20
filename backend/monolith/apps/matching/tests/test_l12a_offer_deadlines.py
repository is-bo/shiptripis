"""L12A: a proposal has a response deadline, one reminder and a clean expiry.

Spec 17.1. The deadline is the time the offer is written plus
``marketplace.offers.response_hours`` (6), or the pickup time of that match if
it comes first; one reminder ``reminder_before_hours`` (1) before it, to the
person who must answer; at the deadline the offer expires for both, exactly as
a decline ends it, and nothing else moves. From the deadline on every answer
is refused with ``offer_expired``, whether or not the expiry job has run.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Event
from unittest.mock import patch

from django.db import close_old_connections, connections
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.admin_panel.models import AdminAuditLog
from apps.admin_panel.permissions import assign_admin_roles
from apps.boosts.models import BoostIntentEvent
from apps.core import channels
from apps.core.marketplace_policy import (
    InvalidMarketplacePolicy,
    MarketplacePolicy,
    marketplace_policy,
)
from apps.core.models import BusinessSettingsVersion
from apps.deals.models import Deal, DealEvent, DealLegAllocation
from apps.discovery.tests.support import STATIC_STORES, activate_marketplace
from apps.finance.jobs import HANDLERS, JobDeferred, PermanentJobError
from apps.finance.models import LedgerEntry, LedgerTransaction, PaymentOrder, ScheduledJob
from apps.matching import offer_deadlines
from apps.matching.models import Match, MatchEvent, Offer
from apps.matching.offer_deadlines import handle_offer_expiry, handle_response_reminder
from apps.matching.serializers import OfferSerializer
from apps.matching.v1_services import (
    OfferExpired,
    OfferNotPending,
    accept_offer,
    counter_offer,
)
from apps.notifications.models import Notification
from apps.notifications.push import _PUSH_SPECS, _STATUS_PUSH_COPY
from apps.parcels.models import DeliveryRequest, ParcelRequest
from apps.ratings.models import Rating
from apps.trips.models import JourneyLeg

from .test_phase8dr_offer_locks import REWARD_EUR_CENTS, CanonicalOfferFixture
from .test_v1_matching import _client
from apps.admin_panel.tests.two_step_helpers import staff_login

UNTOUCHED_MODELS = (
    Deal,
    DealEvent,
    DealLegAllocation,
    PaymentOrder,
    LedgerTransaction,
    LedgerEntry,
    BoostIntentEvent,
    Rating,
)


def _table_snapshot() -> dict:
    return {
        model.__name__: list(model.objects.order_by("pk").values())
        for model in UNTOUCHED_MODELS
    }


class DeadlineWorld(CanonicalOfferFixture):
    """The canonical CDG → ALG → Jijel world, with a movable departure."""

    def leave_in(self, delta: timedelta) -> None:
        """Move the trip (and the parcel's windows with it) to depart after ``delta``."""

        depart = timezone.now() + delta
        JourneyLeg.objects.filter(pk=self.flight_leg.pk).update(
            depart_at=depart, arrive_at=depart + timedelta(hours=3)
        )
        JourneyLeg.objects.filter(pk=self.drive_leg.pk).update(
            depart_at=depart + timedelta(hours=4), arrive_at=depart + timedelta(hours=9)
        )
        DeliveryRequest.objects.filter(pk=self.request.pk).update(
            ready_window_start=depart - timedelta(hours=1),
            ready_window_end=depart + timedelta(hours=1),
            deadline_at=depart + timedelta(hours=16),
        )
        self.request.refresh_from_db()

    @staticmethod
    def pickup_of(offer: Offer) -> datetime:
        return datetime.fromisoformat(offer.match.compatibility_snapshot["pickup_at"])

    @staticmethod
    def jobs(offer: Offer) -> dict[str, ScheduledJob]:
        return {
            job.kind: job
            for job in ScheduledJob.objects.filter(
                kind__in=(
                    ScheduledJob.Kind.OFFER_RESPONSE_REMINDER,
                    ScheduledJob.Kind.OFFER_EXPIRY,
                ),
                payload__offer_id=offer.pk,
            )
        }

    @staticmethod
    def lapse(offer: Offer) -> None:
        """Put the deadline in the past without running the expiry job."""

        Offer.objects.filter(pk=offer.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        offer.refresh_from_db()

    @staticmethod
    def payload(offer: Offer) -> dict:
        return {"offer_id": offer.pk, "expires_at": offer.expires_at.isoformat()}


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------


class OfferPolicyTests(SimpleTestCase):
    def test_the_defaults_are_six_hours_and_one_reminder_an_hour_before(self):
        policy = MarketplacePolicy.from_section(None)
        self.assertTrue(policy.offers.response_deadline_enabled)
        self.assertEqual(policy.offers.response_hours, 6)
        self.assertEqual(policy.offers.reminder_before_hours, 1)
        self.assertTrue(policy.discovery.trip_fit_alerts_enabled)
        self.assertEqual(policy.discovery.trip_fit_max_travelers, 30)
        self.assertEqual(policy.discovery.trip_fit_daily_cap, 5)

    def test_the_reminder_must_come_before_the_deadline_or_be_zero(self):
        for reminder in (6, 7):
            with self.subTest(reminder), self.assertRaises(InvalidMarketplacePolicy):
                MarketplacePolicy.from_section(
                    {"offers": {"response_hours": 6, "reminder_before_hours": reminder}}
                )
        policy = MarketplacePolicy.from_section(
            {"offers": {"response_hours": 1, "reminder_before_hours": 0}}
        )
        self.assertEqual(policy.offers.reminder_before_hours, 0)

    def test_the_bounds_and_the_unknown_keys_are_refused(self):
        for section in (
            {"offers": {"response_hours": 0}},
            {"offers": {"response_hours": 169}},
            {"offers": {"reminder_before_hours": -1}},
            {"offers": {"response_deadline_enabled": 1}},
            {"offers": {"expiry": 6}},
            {"discovery": {"trip_fit_max_travelers": 0}},
            {"discovery": {"trip_fit_daily_cap": 51}},
            {"discovery": {"trip_fit_alerts_enabled": "yes"}},
        ):
            with self.subTest(section), self.assertRaises(InvalidMarketplacePolicy):
                MarketplacePolicy.from_section(section)


# ---------------------------------------------------------------------------
# The deadline and its jobs
# ---------------------------------------------------------------------------


class DeadlineSetTests(DeadlineWorld, TestCase):
    def setUp(self):
        self.build_world()

    def test_a_proposal_waits_six_hours_with_a_reminder_an_hour_before(self):
        before = timezone.now()
        offer = self.propose()
        after = timezone.now()

        self.assertLessEqual(before + timedelta(hours=6), offer.expires_at)
        self.assertLessEqual(offer.expires_at, after + timedelta(hours=6))
        jobs = self.jobs(offer)
        stamp = offer.expires_at.isoformat()
        reminder = jobs[ScheduledJob.Kind.OFFER_RESPONSE_REMINDER]
        expiry = jobs[ScheduledJob.Kind.OFFER_EXPIRY]
        self.assertEqual(reminder.run_at, offer.expires_at - timedelta(hours=1))
        self.assertEqual(expiry.run_at, offer.expires_at)
        self.assertEqual(reminder.key, f"offer_response_reminder:{offer.pk}:{stamp}")
        self.assertEqual(expiry.key, f"offer_expiry:{offer.pk}:{stamp}")
        self.assertEqual(expiry.payload, {"offer_id": offer.pk, "expires_at": stamp})
        self.assertIn(reminder.kind, HANDLERS)
        self.assertIn(expiry.kind, HANDLERS)

    def test_a_counter_gets_its_own_deadline_from_when_it_is_sent(self):
        offer = self.propose()
        before = timezone.now()
        child = counter_offer(
            pending_offer=offer, actor=self.traveler, traveler_reward_eur_cents=3_400
        )

        self.assertLessEqual(before + timedelta(hours=6), child.expires_at)
        self.assertEqual(set(self.jobs(child)), {
            ScheduledJob.Kind.OFFER_RESPONSE_REMINDER,
            ScheduledJob.Kind.OFFER_EXPIRY,
        })

    def test_the_pickup_time_wins_when_it_comes_first_on_a_proposal(self):
        self.leave_in(timedelta(hours=3))

        offer = self.propose()

        self.assertEqual(offer.expires_at, self.pickup_of(offer))
        self.assertLess(offer.expires_at, timezone.now() + timedelta(hours=6))
        reminder = self.jobs(offer)[ScheduledJob.Kind.OFFER_RESPONSE_REMINDER]
        self.assertEqual(reminder.run_at, offer.expires_at - timedelta(hours=1))

    def test_the_pickup_time_wins_when_it_comes_first_on_a_counter(self):
        offer = self.propose()
        self.leave_in(timedelta(hours=2))

        child = counter_offer(
            pending_offer=offer, actor=self.traveler, traveler_reward_eur_cents=3_400
        )

        # The counter's own evaluation found the new pickup time.
        departure = JourneyLeg.objects.get(pk=self.flight_leg.pk).depart_at
        self.assertEqual(child.expires_at, departure)
        self.assertLess(child.expires_at, offer.expires_at)

    def test_no_reminder_when_the_deadline_is_closer_than_the_reminder_delay(self):
        self.leave_in(timedelta(minutes=50))

        offer = self.propose()

        self.assertEqual(set(self.jobs(offer)), {ScheduledJob.Kind.OFFER_EXPIRY})

    def test_no_reminder_when_the_reminder_is_zero(self):
        activate_marketplace({"offers": {"reminder_before_hours": 0}})

        offer = self.propose()

        self.assertIsNotNone(offer.expires_at)
        self.assertEqual(set(self.jobs(offer)), {ScheduledJob.Kind.OFFER_EXPIRY})

    def test_with_the_switch_off_neither_a_proposal_nor_a_counter_gets_a_deadline(self):
        activate_marketplace({"offers": {"response_deadline_enabled": False}})

        offer = self.propose()
        child = counter_offer(
            pending_offer=offer, actor=self.traveler, traveler_reward_eur_cents=3_400
        )

        self.assertIsNone(offer.expires_at)
        self.assertIsNone(child.expires_at)
        self.assertEqual(self.jobs(offer), {})
        self.assertEqual(self.jobs(child), {})

    def test_turning_the_switch_off_leaves_existing_deadlines_in_force(self):
        offer = self.propose()
        activate_marketplace({"offers": {"response_deadline_enabled": False}})
        Offer.objects.filter(pk=offer.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        offer.refresh_from_db()

        self.assertEqual(handle_offer_expiry(self.payload(offer)), "expired")
        with self.assertRaises(OfferExpired):
            accept_offer(pending_offer=offer, actor=self.traveler)

    def test_the_offer_payload_carries_the_deadline_and_who_must_answer(self):
        offer = self.propose()
        response = _client(self.traveler).get(
            reverse("matches-offers", args=[offer.match_id])
        )

        row = response.data[0]
        self.assertEqual(row["expires_at"], offer.expires_at.isoformat().replace("+00:00", "Z"))
        self.assertEqual(row["awaiting_party"], "traveler")
        self.assertEqual(row["awaiting_user_id"], self.traveler.pk)
        self.assertEqual(row["status"], "pending")


# ---------------------------------------------------------------------------
# Reminder
# ---------------------------------------------------------------------------


class ReminderTests(DeadlineWorld, TestCase):
    def setUp(self):
        self.build_world()
        self.offer = self.propose()

    def reminders(self):
        return Notification.objects.filter(channel=channels.OFFER_RESPONSE_REMINDER)

    def test_the_person_who_must_answer_is_reminded_once_even_on_a_replay(self):
        self.assertEqual(handle_response_reminder(self.payload(self.offer)), "notified")
        self.assertEqual(handle_response_reminder(self.payload(self.offer)), "notified")

        (row,) = self.reminders()
        self.assertEqual(row.recipient_id, self.traveler.pk)
        self.assertEqual(
            {key: row.payload[key] for key in ("match_id", "offer_id", "tracking_number")},
            {
                "match_id": self.offer.match_id,
                "offer_id": self.offer.pk,
                "tracking_number": self.request.tracking_number,
            },
        )
        # Ids and the tracking number only: no amount, no time, no place.
        self.assertEqual(
            set(row.payload),
            {
                "event_id",
                "ts",
                "targets",
                "match_id",
                "parcel_id",
                "journey_id",
                "offer_id",
                "tracking_number",
            },
        )

    def test_a_counter_reminds_the_sender(self):
        child = counter_offer(
            pending_offer=self.offer, actor=self.traveler, traveler_reward_eur_cents=3_400
        )

        handle_response_reminder(self.payload(child))

        self.assertEqual(
            list(self.reminders().values_list("recipient_id", flat=True)), [self.sender.pk]
        )

    def test_each_no_op_case_sends_nothing_even_run_twice(self):
        payload = self.payload(self.offer)
        cases = {
            "offer_gone": lambda: {**payload, "offer_id": self.offer.pk + 999},
            "deadline_changed": lambda: {
                **payload,
                "expires_at": (self.offer.expires_at + timedelta(minutes=1)).isoformat(),
            },
        }
        for expected, make in cases.items():
            with self.subTest(expected):
                self.assertEqual(handle_response_reminder(make()), expected)
                self.assertEqual(handle_response_reminder(make()), expected)

        self.lapse(self.offer)
        self.assertEqual(handle_response_reminder(self.payload(self.offer)), "deadline_passed")

        Offer.objects.filter(pk=self.offer.pk).update(status=Offer.Status.DECLINED)
        for _ in range(2):
            self.assertEqual(handle_response_reminder(self.payload(self.offer)), "not_pending")
        self.assertFalse(self.reminders().exists())

    def test_a_malformed_payload_is_a_permanent_failure(self):
        for payload in (
            {},
            {"offer_id": "1", "expires_at": self.offer.expires_at.isoformat()},
            {"offer_id": True, "expires_at": self.offer.expires_at.isoformat()},
            {"offer_id": self.offer.pk, "expires_at": "tomorrow"},
            {"offer_id": self.offer.pk, "expires_at": "2026-11-14T10:00:00"},
        ):
            with self.subTest(payload), self.assertRaises(PermanentJobError):
                handle_response_reminder(payload)


# ---------------------------------------------------------------------------
# Expiry
# ---------------------------------------------------------------------------


class ExpiryTests(DeadlineWorld, TestCase):
    def setUp(self):
        self.build_world()

    def test_expiry_ends_the_negotiation_exactly_as_a_decline_does(self):
        declined = self.propose()
        response = _client(self.traveler).post(reverse("offers-decline", args=[declined.pk]))
        self.assertEqual(response.status_code, 200)
        declined_match = Match.objects.get(pk=declined.match_id)
        request_after_decline = DeliveryRequest.objects.get(pk=self.request.pk).status

        offer = self.propose()  # the sender proposes again, then nobody answers
        self.lapse(offer)
        before = _table_snapshot()

        self.assertEqual(handle_offer_expiry(self.payload(offer)), "expired")

        offer.refresh_from_db()
        match = Match.objects.get(pk=offer.match_id)
        self.assertEqual(offer.status, Offer.Status.EXPIRED)
        self.assertIsNotNone(offer.responded_at)
        self.assertEqual(match.status, declined_match.status)
        self.assertEqual(match.status, Match.Status.CANCELLED)
        self.assertEqual(
            DeliveryRequest.objects.get(pk=self.request.pk).status, request_after_decline
        )
        self.assertEqual(request_after_decline, ParcelRequest.Status.OPEN)
        event = MatchEvent.objects.get(match=match, kind=MatchEvent.Kind.OFFER_EXPIRED)
        self.assertEqual(event.offer_id, offer.pk)
        self.assertIsNone(event.actor_id)
        # Expiry is neutral: nothing reserved, owed, paid or rated moves.
        self.assertEqual(_table_snapshot(), before)

    def test_both_people_are_told_once_on_offer_updated(self):
        offer = self.propose()
        self.lapse(offer)

        handle_offer_expiry(self.payload(offer))
        self.assertEqual(handle_offer_expiry(self.payload(offer)), "not_pending")

        rows = Notification.objects.filter(
            channel=channels.OFFER_UPDATED, payload__status="expired"
        )
        self.assertEqual(
            sorted(rows.values_list("recipient_id", flat=True)),
            sorted([self.sender.pk, self.traveler.pk]),
        )
        self.assertEqual(
            MatchEvent.objects.filter(kind=MatchEvent.Kind.OFFER_EXPIRED).count(), 1
        )

    def test_the_sender_may_propose_to_the_same_traveler_again(self):
        offer = self.propose()
        self.lapse(offer)
        handle_offer_expiry(self.payload(offer))

        again = self.propose()

        self.assertEqual(again.status, Offer.Status.PENDING)
        self.assertNotEqual(again.match_id, offer.match_id)

    def test_an_answered_offer_is_left_alone(self):
        offer = self.propose()
        accepted = accept_offer(pending_offer=offer, actor=self.traveler)
        self.lapse(offer)

        self.assertEqual(handle_offer_expiry(self.payload(offer)), "not_pending")
        offer.refresh_from_db()
        self.assertEqual(offer.status, Offer.Status.ACCEPTED)
        self.assertTrue(Deal.objects.filter(pk=accepted.deal.pk).exists())

    def test_a_job_claimed_before_the_deadline_waits_for_it(self):
        offer = self.propose()
        with self.assertRaises(JobDeferred):
            handle_offer_expiry(self.payload(offer))
        offer.refresh_from_db()
        self.assertEqual(offer.status, Offer.Status.PENDING)

    def test_the_status_copy_for_expired_exists_in_three_languages(self):
        copy = _STATUS_PUSH_COPY[(channels.OFFER_UPDATED, "expired")]
        self.assertEqual(set(copy), {"en", "fr", "ar"})
        category, _, _, reminder_copy = _PUSH_SPECS[channels.OFFER_RESPONSE_REMINDER]
        self.assertEqual(category, "marketplace")
        self.assertEqual(set(reminder_copy), {"en", "fr", "ar"})


# ---------------------------------------------------------------------------
# Refusal from the deadline on
# ---------------------------------------------------------------------------


class RefusalTests(DeadlineWorld, TestCase):
    def setUp(self):
        self.build_world()
        self.offer = self.propose()
        self.lapse(self.offer)

    def assert_expired(self, response):
        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(response.data["code"], "offer_expired")
        self.assertIn("expires_at", response.data)

    def test_accept_counter_and_decline_refuse_before_the_job_has_run(self):
        traveler = _client(self.traveler)
        self.assert_expired(traveler.post(reverse("offers-accept", args=[self.offer.pk]), {}))
        self.assert_expired(
            traveler.post(
                reverse("offers-counter-v1", args=[self.offer.pk]),
                {"traveler_reward_eur_cents": REWARD_EUR_CENTS + 100},
            )
        )
        self.assert_expired(traveler.post(reverse("offers-decline", args=[self.offer.pk])))
        self.offer.refresh_from_db()
        self.assertEqual(self.offer.status, Offer.Status.PENDING)
        self.assertFalse(Deal.objects.exists())

    def test_withdraw_and_cancel_refuse_too(self):
        sender = _client(self.sender)
        self.assert_expired(sender.post(reverse("offers-withdraw", args=[self.offer.pk])))
        self.assert_expired(sender.post(reverse("matches-cancel", args=[self.offer.match_id])))
        self.assertEqual(Match.objects.get(pk=self.offer.match_id).status, Match.Status.PENDING)

    def test_the_services_refuse_after_the_job_has_run_as_well(self):
        handle_offer_expiry(self.payload(self.offer))
        self.offer.refresh_from_db()

        for attempt in (
            lambda: accept_offer(pending_offer=self.offer, actor=self.traveler),
            lambda: counter_offer(
                pending_offer=self.offer,
                actor=self.traveler,
                traveler_reward_eur_cents=REWARD_EUR_CENTS + 100,
            ),
        ):
            with self.assertRaises(OfferExpired):
                attempt()
        self.assert_expired(
            _client(self.traveler).post(reverse("offers-decline", args=[self.offer.pk]))
        )

    def test_the_refusal_is_inside_the_lock(self):
        # The pre-check passes (the deadline is still ahead when it runs); the
        # deadline passes before the locked re-read, which must refuse.
        Offer.objects.filter(pk=self.offer.pk).update(
            expires_at=timezone.now() + timedelta(hours=1)
        )
        self.offer.refresh_from_db()
        real_now = timezone.now
        calls = {"n": 0}

        def later():
            calls["n"] += 1
            return real_now() + (timedelta(hours=2) if calls["n"] > 1 else timedelta(0))

        with patch("apps.matching.v1_services.timezone.now", later):
            with self.assertRaises(OfferExpired):
                accept_offer(pending_offer=self.offer, actor=self.traveler)
        self.assertFalse(Deal.objects.exists())

    def test_a_superseded_offer_still_says_not_pending_before_its_deadline(self):
        Offer.objects.filter(pk=self.offer.pk).update(
            status=Offer.Status.EXPIRED, expires_at=timezone.now() + timedelta(hours=1)
        )
        self.offer.refresh_from_db()
        with self.assertRaises(OfferNotPending):
            accept_offer(pending_offer=self.offer, actor=self.traveler)

    def test_the_payload_reads_expired_with_no_action_and_nobody_awaited(self):
        data = OfferSerializer(
            self.offer,
            context={"request": type("R", (), {"user": self.traveler})()},
        ).data
        self.assertEqual(data["status"], "expired")
        self.assertEqual(data["allowed_actions"], [])
        self.assertIsNone(data["awaiting_party"])
        self.assertIsNone(data["awaiting_user_id"])


# ---------------------------------------------------------------------------
# Acceptance racing expiry
# ---------------------------------------------------------------------------


class AcceptRacesExpiryTests(DeadlineWorld, TransactionTestCase):
    """Two real transactions on two connections: exactly one outcome."""

    reset_sequences = True

    def setUp(self):
        self.build_world()
        self.offer = self.propose()

    def _thread(self, fn):
        close_old_connections()
        try:
            return fn()
        except OfferExpired:
            return "offer_expired"
        finally:
            connections.close_all()

    def test_acceptance_holding_the_locks_wins_and_the_expiry_finds_nothing_to_do(self):
        # Acceptance takes its locks while the deadline is still ahead, then
        # the deadline passes while it holds them. Expiry must wait for it and
        # then find an accepted offer.
        Offer.objects.filter(pk=self.offer.pk).update(
            expires_at=timezone.now() + timedelta(seconds=2)
        )
        self.offer.refresh_from_db()
        holding, release = Event(), Event()
        original = Deal.objects.create

        def paused_create(*args, **kwargs):
            holding.set()
            assert release.wait(timeout=15), "acceptance was never released"
            return original(*args, **kwargs)

        with patch.object(Deal.objects, "create", paused_create):
            with ThreadPoolExecutor(max_workers=2) as pool:
                accepting = pool.submit(
                    self._thread,
                    lambda: accept_offer(pending_offer=self.offer, actor=self.traveler),
                )
                self.assertTrue(holding.wait(timeout=15))
                while timezone.now() <= self.offer.expires_at:
                    Event().wait(0.05)
                expiring = pool.submit(
                    self._thread, lambda: handle_offer_expiry(self.payload(self.offer))
                )
                Event().wait(0.5)
                self.assertFalse(expiring.done(), "expiry did not wait for the lock")
                release.set()
                accepted = accepting.result(timeout=20)
                expired = expiring.result(timeout=20)

        self.assertTrue(accepted.created)
        self.assertEqual(expired, "not_pending")
        self.offer.refresh_from_db()
        self.assertEqual(self.offer.status, Offer.Status.ACCEPTED)
        self.assertEqual(Deal.objects.count(), 1)
        self.assertFalse(MatchEvent.objects.filter(kind=MatchEvent.Kind.OFFER_EXPIRED).exists())

    def test_at_the_deadline_both_racing_leave_one_expired_offer_and_no_deal(self):
        self.lapse(self.offer)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(
                pool.map(
                    self._thread,
                    (
                        lambda: accept_offer(pending_offer=self.offer, actor=self.traveler),
                        lambda: handle_offer_expiry(self.payload(self.offer)),
                    ),
                )
            )

        self.assertEqual(results, ["offer_expired", "expired"])
        self.offer.refresh_from_db()
        self.assertEqual(self.offer.status, Offer.Status.EXPIRED)
        self.assertFalse(Deal.objects.exists())
        self.assertEqual(
            MatchEvent.objects.filter(kind=MatchEvent.Kind.OFFER_EXPIRED).count(), 1
        )


class ModuleShapeTests(SimpleTestCase):
    def test_the_new_lock_site_is_held_to_the_canonical_lock_mode(self):
        from apps.finance.tests.test_phase8df_lock_order import CANONICAL_LOCK_MODULES

        self.assertIn("apps/matching/offer_deadlines.py", CANONICAL_LOCK_MODULES)
        self.assertTrue(offer_deadlines.__doc__)


@override_settings(STORAGES=STATIC_STORES)
class ConsoleFormTests(TestCase):
    """The "Marketplace features" form carries both L12A groups."""

    def setUp(self):
        self.admin = User.objects.create_user(
            username="l12a-ops@example.com",
            email="l12a-ops@example.com",
            password="Sup3rStrongPass!",
            is_staff=True,
        )
        assign_admin_roles(self.admin, ["super_admin"])
        staff_login(self.client, self.admin)

    def _post(self, **fields):
        data = {
            "action": "marketplace",
            "listings_enabled": "on",
            "profiles_enabled": "on",
            "interest_daily_cap": "10",
            "trip_fit_alerts_enabled": "on",
            "trip_fit_max_travelers": "12",
            "trip_fit_daily_cap": "3",
            "traveler_pricing_enabled": "on",
            "max_price_per_kg_eur": "100.00",
            "max_min_price_eur": "500.00",
            "response_deadline_enabled": "on",
            "response_hours": "4",
            "reminder_before_hours": "2",
            "reason": "Shorter answers for same-day parcels",
            "confirm": "on",
        }
        data.update(fields)
        return self.client.post(reverse("admin_console:settings"), data)

    def test_the_page_shows_both_groups_with_the_defaults(self):
        body = self.client.get(reverse("admin_console:settings")).content.decode()
        for label in (
            "Give proposals a response deadline",
            "Hours to answer a proposal",
            "Tell travelers when a new parcel fits their trip",
        ):
            self.assertIn(label, body)
        self.assertIn('name="response_hours" value="6"', body)
        self.assertIn('name="reminder_before_hours" value="1"', body)
        self.assertIn('name="trip_fit_max_travelers" value="30"', body)

    def test_saving_writes_an_audited_revision_the_server_reads(self):
        response = self._post()

        self.assertEqual(response.status_code, 302)
        policy = marketplace_policy()
        self.assertEqual(policy.offers.response_hours, 4)
        self.assertEqual(policy.offers.reminder_before_hours, 2)
        self.assertEqual(policy.discovery.trip_fit_max_travelers, 12)
        self.assertEqual(policy.discovery.trip_fit_daily_cap, 3)
        audit = AdminAuditLog.objects.get(action="settings.version_created")
        self.assertEqual(audit.after["marketplace.offers.response_hours"], 4)
        self.assertIsNone(audit.before["marketplace.offers.response_hours"])

    def test_a_reminder_not_before_the_deadline_is_refused_on_the_form(self):
        before = BusinessSettingsVersion.objects.get(
            status=BusinessSettingsVersion.Status.ACTIVE
        ).version

        response = self._post(response_hours="2", reminder_before_hours="2")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "The reminder must come before the deadline")
        self.assertEqual(
            BusinessSettingsVersion.objects.get(
                status=BusinessSettingsVersion.Status.ACTIVE
            ).version,
            before,
        )
