"""Handover code security: generation, storage, secrecy, attempts and replay.

These tests are the enforcement of two hard invariants from the specification,
and they are written adversarially rather than descriptively. A test that only
walks the happy path would pass against an implementation that also happened to
hand the traveler a delivery code, so most of what follows is an attempt to get
a code out of the system through a route that should not exist.
"""

from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.deals.models import Deal, DealEvent
from apps.deals.tests.phase4_factories import (
    confirm_pickup,
    freeze_at,
    fund_scenario,
    record_recipient,
    release_delivery_code,
    reveal_pickup_code,
)
from apps.handover import codes as code_lib
from apps.handover.models import DealHandoverCode, HandoverAttempt, HandoverCodeAccess
from apps.handover.services import (
    HandoverError,
    NotAuthorized,
    reveal_code,
    rotate_code,
    submit_code,
)
from apps.notifications.models import OutboundMessage


def client_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


# --- generation and storage ---------------------------------------------------


class CodeMaterialTests(TestCase):
    def test_generated_codes_use_the_unambiguous_alphabet_only(self):
        for _ in range(200):
            code = code_lib.generate_code(8)
            assert len(code) == 8
            assert set(code) <= set(code_lib.ALPHABET)
            # The four shapes people misread are absent by construction.
            assert not (set(code) & {"I", "L", "O", "U"})

    def test_generated_codes_do_not_repeat_in_a_realistic_sample(self):
        """A weak generator shows up here long before it shows up in production."""

        sample = {code_lib.generate_code(8) for _ in range(2_000)}
        assert len(sample) == 2_000

    def test_a_hash_is_bound_to_its_deal_and_kind(self):
        plaintext = "ABCD2345"
        base = code_lib.hash_code(deal_id=1, kind="pickup", code=plaintext)
        assert base != code_lib.hash_code(deal_id=2, kind="pickup", code=plaintext)
        assert base != code_lib.hash_code(deal_id=1, kind="delivery", code=plaintext)
        assert code_lib.code_matches(
            deal_id=1, kind="pickup", code=plaintext, code_hash=base
        )
        assert not code_lib.code_matches(
            deal_id=2, kind="pickup", code=plaintext, code_hash=base
        )

    def test_normalisation_folds_what_a_human_types(self):
        assert code_lib.normalize_code(" abcd-2345 ") == "ABCD2345"
        assert code_lib.normalize_code("ABCDI345") == "ABCD1345"
        assert code_lib.normalize_code("ABCDO345") == "ABCD0345"

    def test_normalisation_never_drops_an_unknown_character(self):
        """Dropping characters would shorten the effective search space."""

        assert code_lib.normalize_code("ABCD!345") == "ABCD!345"

    def test_a_seal_opens_only_for_its_own_deal_and_kind(self):
        sealed = code_lib.seal_code(deal_id=7, kind="delivery", code="ZZZZ9999")
        assert "ZZZZ9999" not in sealed
        assert (
            code_lib.unseal_code(deal_id=7, kind="delivery", sealed=sealed)
            == "ZZZZ9999"
        )
        with self.assertRaises(code_lib.SealError):
            code_lib.unseal_code(deal_id=8, kind="delivery", sealed=sealed)
        with self.assertRaises(code_lib.SealError):
            code_lib.unseal_code(deal_id=7, kind="pickup", sealed=sealed)

    def test_a_tampered_seal_is_refused_rather_than_decrypted(self):
        sealed = code_lib.seal_code(deal_id=7, kind="pickup", code="ZZZZ9999")
        tampered = sealed[:-4] + ("AAAA" if not sealed.endswith("AAAA") else "BBBB")
        with self.assertRaises(code_lib.SealError):
            code_lib.unseal_code(deal_id=7, kind="pickup", sealed=tampered)


# --- pickup -------------------------------------------------------------------


class PickupCodeTests(TestCase):
    def setUp(self):
        self.scenario = fund_scenario(self.client, prefix="hp")
        record_recipient(self.scenario)
        self.deal = self.scenario.deal

    def _row(self, kind=DealHandoverCode.Kind.PICKUP) -> DealHandoverCode:
        return DealHandoverCode.objects.filter(
            deal_id=self.deal.pk, kind=kind
        ).order_by("-pk").first()

    def test_funding_issues_exactly_one_live_pickup_code(self):
        rows = DealHandoverCode.objects.filter(
            deal_id=self.deal.pk, kind=DealHandoverCode.Kind.PICKUP
        )
        assert rows.count() == 1
        assert rows.first().status == DealHandoverCode.Status.ACTIVE

    def test_no_plaintext_is_stored_anywhere_on_the_row(self):
        plaintext = reveal_pickup_code(self.scenario)
        row = self._row()
        for value in (row.code_hash, row.sealed_code):
            assert plaintext not in value
        assert row.code_hash == code_lib.hash_code(
            deal_id=self.deal.pk,
            kind=DealHandoverCode.Kind.PICKUP,
            code=plaintext,
        )

    def test_the_sender_can_reveal_and_re_reveal_the_same_code(self):
        first = reveal_code(
            deal_id=self.deal.pk,
            kind=DealHandoverCode.Kind.PICKUP,
            actor_id=self.scenario.sender.pk,
        )
        second = reveal_code(
            deal_id=self.deal.pk,
            kind=DealHandoverCode.Kind.PICKUP,
            actor_id=self.scenario.sender.pk,
        )
        assert first.code == second.code
        assert HandoverCodeAccess.objects.filter(deal_id=self.deal.pk).count() == 2

    def test_the_traveler_cannot_reveal_the_pickup_code(self):
        with self.assertRaises(NotAuthorized):
            reveal_code(
                deal_id=self.deal.pk,
                kind=DealHandoverCode.Kind.PICKUP,
                actor_id=self.scenario.traveler.pk,
            )

    def test_a_stranger_gets_a_404_rather_than_a_403(self):
        response = client_for(self.scenario.outsider).get(
            reverse("handover-pickup-code", args=[self.deal.pk])
        )
        assert response.status_code == 404

    def test_the_pickup_code_does_not_exist_before_funding(self):
        unfunded = fund_scenario(self.client, prefix="hp-unfunded")
        # Roll the Deal back to the pre-funding state the API must refuse from.
        Deal.objects.filter(pk=unfunded.deal.pk).update(
            status=Deal.Status.PAYMENT_REQUIRED
        )
        with self.assertRaises(HandoverError) as caught:
            reveal_code(
                deal_id=unfunded.deal.pk,
                kind=DealHandoverCode.Kind.PICKUP,
                actor_id=unfunded.sender.pk,
            )
        assert caught.exception.code == "deal_not_funded"

    def test_a_correct_submission_confirms_pickup_and_starts_the_buffer(self):
        code = reveal_pickup_code(self.scenario)
        submit_code(
            deal_id=self.deal.pk,
            kind=DealHandoverCode.Kind.PICKUP,
            actor_id=self.scenario.traveler.pk,
            submitted_code=code,
        )
        deal = self.scenario.deal
        assert deal.status == Deal.Status.IN_TRANSIT
        assert deal.pickup_confirmed_at is not None
        assert deal.delivery_code_available_at == deal.pickup_confirmed_at + timedelta(
            minutes=30
        )
        assert self._row().status == DealHandoverCode.Status.USED

    def test_a_wrong_submission_is_rejected_uniformly_and_recorded(self):
        with self.assertRaises(HandoverError) as caught:
            submit_code(
                deal_id=self.deal.pk,
                kind=DealHandoverCode.Kind.PICKUP,
                actor_id=self.scenario.traveler.pk,
                submitted_code="0000000Z",
            )
        assert caught.exception.code == "handover_code_invalid"
        # The failed attempt survives the exception that was raised after it.
        assert HandoverAttempt.objects.filter(
            deal_id=self.deal.pk, result=HandoverAttempt.Result.MISMATCH
        ).count() == 1
        assert self._row().failed_attempts == 1

    def test_the_rejection_never_varies_with_how_wrong_the_guess_was(self):
        """No oracle: a near miss and a nonsense string answer identically."""

        code = reveal_pickup_code(self.scenario)
        near_miss = code[:-1] + ("0" if code[-1] != "0" else "1")
        messages = set()
        for candidate in (near_miss, "!", "Z" * 40):
            with self.assertRaises(HandoverError) as caught:
                submit_code(
                    deal_id=self.deal.pk,
                    kind=DealHandoverCode.Kind.PICKUP,
                    actor_id=self.scenario.traveler.pk,
                    submitted_code=candidate,
                )
            messages.add((caught.exception.code, str(caught.exception)))
        assert len(messages) == 1

    def test_only_the_traveler_may_submit(self):
        code = reveal_pickup_code(self.scenario)
        for actor in (self.scenario.sender, self.scenario.outsider):
            with self.assertRaises(NotAuthorized):
                submit_code(
                    deal_id=self.deal.pk,
                    kind=DealHandoverCode.Kind.PICKUP,
                    actor_id=actor.pk,
                    submitted_code=code,
                )

    def test_five_failures_lock_the_code_and_a_third_lockout_is_permanent(self):
        """Three lockouts retire the code, and only a rotation revives it.

        The per-hour sliding window (12) is deliberately tighter than three
        rounds of five failures, so a guesser cannot reach the permanent lock
        inside one hour. Ageing the attempt rows between rounds is what "came
        back the next day" means, and it is the only way to exercise the
        third lockout at all.
        """

        for lockout in range(1, 4):
            for _ in range(5):
                with self.assertRaises(HandoverError):
                    submit_code(
                        deal_id=self.deal.pk,
                        kind=DealHandoverCode.Kind.PICKUP,
                        actor_id=self.scenario.traveler.pk,
                        submitted_code="0000000Z",
                    )
            row = self._row()
            assert row.lockout_count == lockout, (lockout, row.lockout_count)
            if lockout < 3:
                assert row.status == DealHandoverCode.Status.ACTIVE
                assert row.locked_until is not None
                # Serve out the lockout, and let the sliding window elapse.
                DealHandoverCode.objects.filter(pk=row.pk).update(locked_until=None)
                HandoverAttempt.objects.filter(deal_id=self.deal.pk).update(
                    created_at=timezone.now() - timedelta(hours=2)
                )
        assert self._row().status == DealHandoverCode.Status.LOCKED

        # A permanently locked code refuses even a correct submission, and only
        # the sender issuing a new one puts the delivery back on track.
        rotated = rotate_code(
            deal_id=self.deal.pk,
            kind=DealHandoverCode.Kind.PICKUP,
            actor_id=self.scenario.sender.pk,
        )
        HandoverAttempt.objects.filter(deal_id=self.deal.pk).update(
            created_at=timezone.now() - timedelta(hours=2)
        )
        submit_code(
            deal_id=self.deal.pk,
            kind=DealHandoverCode.Kind.PICKUP,
            actor_id=self.scenario.traveler.pk,
            submitted_code=rotated.code,
        )
        assert self.scenario.deal.status == Deal.Status.IN_TRANSIT

    def test_a_locked_out_code_refuses_even_the_correct_value(self):
        code = reveal_pickup_code(self.scenario)
        for _ in range(5):
            with self.assertRaises(HandoverError):
                submit_code(
                    deal_id=self.deal.pk,
                    kind=DealHandoverCode.Kind.PICKUP,
                    actor_id=self.scenario.traveler.pk,
                    submitted_code="0000000Z",
                )
        with self.assertRaises(HandoverError) as caught:
            submit_code(
                deal_id=self.deal.pk,
                kind=DealHandoverCode.Kind.PICKUP,
                actor_id=self.scenario.traveler.pk,
                submitted_code=code,
            )
        assert caught.exception.code == "handover_code_locked"

    def test_the_sliding_window_bounds_attempts_independently_of_the_code(self):
        """Rotating past a lockout must not reset the per-deal attempt budget."""

        for _ in range(12):
            with self.assertRaises(HandoverError):
                submit_code(
                    deal_id=self.deal.pk,
                    kind=DealHandoverCode.Kind.PICKUP,
                    actor_id=self.scenario.traveler.pk,
                    submitted_code="0000000Z",
                )
            DealHandoverCode.objects.filter(deal_id=self.deal.pk).update(
                locked_until=None, status=DealHandoverCode.Status.ACTIVE
            )
        with self.assertRaises(HandoverError) as caught:
            submit_code(
                deal_id=self.deal.pk,
                kind=DealHandoverCode.Kind.PICKUP,
                actor_id=self.scenario.traveler.pk,
                submitted_code="0000000Z",
            )
        assert caught.exception.code == "handover_rate_limited"

    def test_a_replayed_submission_does_not_repeat_the_transition(self):
        code = reveal_pickup_code(self.scenario)
        submit_code(
            deal_id=self.deal.pk,
            kind=DealHandoverCode.Kind.PICKUP,
            actor_id=self.scenario.traveler.pk,
            submitted_code=code,
        )
        first_confirmed_at = self.scenario.deal.pickup_confirmed_at
        events = DealEvent.objects.filter(
            deal_id=self.deal.pk, kind=DealEvent.Kind.PICKUP_CONFIRMED
        ).count()

        with self.assertRaises(HandoverError) as caught:
            submit_code(
                deal_id=self.deal.pk,
                kind=DealHandoverCode.Kind.PICKUP,
                actor_id=self.scenario.traveler.pk,
                submitted_code=code,
            )
        assert caught.exception.code in {
            "pickup_already_confirmed",
            "code_not_available",
        }
        assert self.scenario.deal.pickup_confirmed_at == first_confirmed_at
        assert (
            DealEvent.objects.filter(
                deal_id=self.deal.pk, kind=DealEvent.Kind.PICKUP_CONFIRMED
            ).count()
            == events
        )

    def test_rotation_supersedes_the_previous_code(self):
        original = reveal_pickup_code(self.scenario)
        rotated = rotate_code(
            deal_id=self.deal.pk,
            kind=DealHandoverCode.Kind.PICKUP,
            actor_id=self.scenario.sender.pk,
        )
        assert rotated.code != original
        assert rotated.rotation == 2
        with self.assertRaises(HandoverError):
            submit_code(
                deal_id=self.deal.pk,
                kind=DealHandoverCode.Kind.PICKUP,
                actor_id=self.scenario.traveler.pk,
                submitted_code=original,
            )
        submit_code(
            deal_id=self.deal.pk,
            kind=DealHandoverCode.Kind.PICKUP,
            actor_id=self.scenario.traveler.pk,
            submitted_code=rotated.code,
        )
        assert self.scenario.deal.status == Deal.Status.IN_TRANSIT


# --- delivery -----------------------------------------------------------------


class DeliveryCodeTests(TestCase):
    def setUp(self):
        self.scenario = fund_scenario(self.client, prefix="hd")
        record_recipient(self.scenario)
        confirm_pickup(self.scenario)
        self.deal = self.scenario.deal

    def _delivery_row(self) -> DealHandoverCode:
        return DealHandoverCode.objects.get(
            deal_id=self.deal.pk, kind=DealHandoverCode.Kind.DELIVERY
        )

    def test_the_delivery_code_is_a_different_secret_from_the_pickup_code(self):
        pickup = DealHandoverCode.objects.get(
            deal_id=self.deal.pk, kind=DealHandoverCode.Kind.PICKUP
        )
        delivery = self._delivery_row()
        assert delivery.pk != pickup.pk
        assert delivery.code_hash != pickup.code_hash
        assert delivery.sealed_code != pickup.sealed_code
        plaintext = release_delivery_code(self.scenario)
        assert not code_lib.code_matches(
            deal_id=self.deal.pk,
            kind=DealHandoverCode.Kind.PICKUP,
            code=plaintext,
            code_hash=pickup.code_hash,
        )

    def test_it_is_created_buffered_with_a_stored_availability_instant(self):
        row = self._delivery_row()
        assert row.status == DealHandoverCode.Status.BUFFERED
        assert row.available_at == self.deal.delivery_code_available_at

    def test_the_sender_cannot_reveal_it_inside_the_safety_window(self):
        with freeze_at(self.deal.delivery_code_available_at - timedelta(seconds=1)):
            with self.assertRaises(HandoverError) as caught:
                reveal_code(
                    deal_id=self.deal.pk,
                    kind=DealHandoverCode.Kind.DELIVERY,
                    actor_id=self.scenario.sender.pk,
                )
        assert caught.exception.code == "delivery_code_buffer_open"

    def test_the_sender_cannot_rotate_around_the_safety_window(self):
        with freeze_at(self.deal.delivery_code_available_at - timedelta(seconds=1)):
            with self.assertRaises(HandoverError) as caught:
                rotate_code(
                    deal_id=self.deal.pk,
                    kind=DealHandoverCode.Kind.DELIVERY,
                    actor_id=self.scenario.sender.pk,
                )
        assert caught.exception.code == "delivery_code_buffer_open"

    def test_the_recipient_is_not_notified_inside_the_safety_window(self):
        with freeze_at(self.deal.delivery_code_available_at - timedelta(seconds=1)):
            assert not OutboundMessage.objects.filter(
                deal_id=self.deal.pk,
                kind=OutboundMessage.Kind.RECIPIENT_DELIVERY_CODE,
            ).exists()

    def test_the_release_job_refuses_to_run_early(self):
        from apps.handover.services import release_delivery_code as release

        with freeze_at(self.deal.delivery_code_available_at - timedelta(seconds=1)):
            with self.assertRaises(HandoverError) as caught:
                release(deal_id=self.deal.pk)
        assert caught.exception.code == "delivery_code_buffer_open"
        assert self._delivery_row().status == DealHandoverCode.Status.BUFFERED

    def test_exactly_at_the_boundary_the_code_releases_once(self):
        from apps.handover.services import release_delivery_code as release

        boundary = self.deal.delivery_code_available_at
        with freeze_at(boundary):
            assert release(deal_id=self.deal.pk) == "released"
        deal = self.scenario.deal
        assert deal.status == Deal.Status.DELIVERY_READY
        assert deal.delivery_code_released_at == boundary
        assert self._delivery_row().status == DealHandoverCode.Status.ACTIVE
        assert (
            OutboundMessage.objects.filter(
                deal_id=deal.pk, kind=OutboundMessage.Kind.RECIPIENT_DELIVERY_CODE
            ).count()
            == 1
        )

    def test_a_duplicate_release_changes_nothing(self):
        from apps.handover.services import release_delivery_code as release

        boundary = self.deal.delivery_code_available_at
        with freeze_at(boundary):
            release(deal_id=self.deal.pk)
        released_at = self.scenario.deal.delivery_code_released_at
        with freeze_at(boundary + timedelta(minutes=5)):
            assert release(deal_id=self.deal.pk) == "already_released"
        assert self.scenario.deal.delivery_code_released_at == released_at
        assert (
            OutboundMessage.objects.filter(
                deal_id=self.deal.pk,
                kind=OutboundMessage.Kind.RECIPIENT_DELIVERY_CODE,
            ).count()
            == 1
        )

    def test_the_sender_may_reveal_after_the_window_even_if_no_worker_ran(self):
        """A stopped worker delays the email, never the sender's own code."""

        with freeze_at(self.deal.delivery_code_available_at + timedelta(seconds=1)):
            revealed = reveal_code(
                deal_id=self.deal.pk,
                kind=DealHandoverCode.Kind.DELIVERY,
                actor_id=self.scenario.sender.pk,
            )
        assert revealed.code
        assert self.scenario.deal.status == Deal.Status.DELIVERY_READY
        assert OutboundMessage.objects.filter(
            deal_id=self.deal.pk, kind=OutboundMessage.Kind.RECIPIENT_DELIVERY_CODE
        ).exists()

    def test_the_traveler_can_never_reveal_the_delivery_code(self):
        release_delivery_code(self.scenario)
        with self.assertRaises(NotAuthorized):
            reveal_code(
                deal_id=self.deal.pk,
                kind=DealHandoverCode.Kind.DELIVERY,
                actor_id=self.scenario.traveler.pk,
            )
        with self.assertRaises(NotAuthorized):
            rotate_code(
                deal_id=self.deal.pk,
                kind=DealHandoverCode.Kind.DELIVERY,
                actor_id=self.scenario.traveler.pk,
            )

    def test_a_correct_delivery_submission_opens_the_protection_window(self):
        code = release_delivery_code(self.scenario)
        submit_code(
            deal_id=self.deal.pk,
            kind=DealHandoverCode.Kind.DELIVERY,
            actor_id=self.scenario.traveler.pk,
            submitted_code=code,
        )
        deal = self.scenario.deal
        assert deal.status == Deal.Status.PROTECTION_WINDOW
        assert deal.delivery_confirmed_at is not None
        assert deal.protection_ends_at == deal.delivery_confirmed_at + timedelta(
            hours=48
        )
        assert self._delivery_row().status == DealHandoverCode.Status.USED

    def test_delivery_cannot_be_confirmed_before_the_code_is_released(self):
        row = self._delivery_row()
        plaintext = code_lib.unseal_code(
            deal_id=self.deal.pk,
            kind=DealHandoverCode.Kind.DELIVERY,
            sealed=row.sealed_code,
        )
        with freeze_at(self.deal.delivery_code_available_at - timedelta(seconds=1)):
            with self.assertRaises(HandoverError) as caught:
                submit_code(
                    deal_id=self.deal.pk,
                    kind=DealHandoverCode.Kind.DELIVERY,
                    actor_id=self.scenario.traveler.pk,
                    submitted_code=plaintext,
                )
        assert caught.exception.code == "delivery_code_buffer_open"
        assert self.scenario.deal.delivery_confirmed_at is None

    def test_a_replayed_delivery_submission_does_not_repeat_the_transition(self):
        code = release_delivery_code(self.scenario)
        submit_code(
            deal_id=self.deal.pk,
            kind=DealHandoverCode.Kind.DELIVERY,
            actor_id=self.scenario.traveler.pk,
            submitted_code=code,
        )
        confirmed_at = self.scenario.deal.delivery_confirmed_at
        with self.assertRaises(HandoverError):
            submit_code(
                deal_id=self.deal.pk,
                kind=DealHandoverCode.Kind.DELIVERY,
                actor_id=self.scenario.traveler.pk,
                submitted_code=code,
            )
        assert self.scenario.deal.delivery_confirmed_at == confirmed_at

    def test_rotating_after_release_re_arms_the_recipient_under_a_new_key(self):
        first = release_delivery_code(self.scenario)
        with freeze_at(self.deal.delivery_code_available_at + timedelta(minutes=1)):
            rotated = rotate_code(
                deal_id=self.deal.pk,
                kind=DealHandoverCode.Kind.DELIVERY,
                actor_id=self.scenario.sender.pk,
            )
        assert rotated.code != first
        assert (
            OutboundMessage.objects.filter(
                deal_id=self.deal.pk,
                kind=OutboundMessage.Kind.RECIPIENT_DELIVERY_CODE,
            ).count()
            == 2
        )
        with self.assertRaises(HandoverError):
            submit_code(
                deal_id=self.deal.pk,
                kind=DealHandoverCode.Kind.DELIVERY,
                actor_id=self.scenario.traveler.pk,
                submitted_code=first,
            )


# --- the leak sweep -----------------------------------------------------------


class DeliveryCodeIsolationTests(TestCase):
    """Every surface a traveler can reach, checked for the delivery code.

    This is the test that would have caught the legacy defect: `apps.verification`
    published the plaintext to `targets=[sender_id, traveler_id]`, which put it
    in the traveler's WebSocket payload *and* in their database inbox row.
    """

    def setUp(self):
        self.scenario = fund_scenario(self.client, prefix="hleak")
        record_recipient(self.scenario)
        confirm_pickup(self.scenario)
        self.code = release_delivery_code(self.scenario)
        self.deal = self.scenario.deal
        self.traveler = client_for(self.scenario.traveler)

    def _assert_absent(self, response, surface: str):
        assert response.status_code in (200, 201, 400, 403, 404, 405, 409), (
            surface,
            response.status_code,
        )
        body = response.content.decode("utf-8", errors="replace")
        assert self.code not in body, f"{surface} leaked the delivery code"
        assert self.code.lower() not in body.lower(), f"{surface} leaked the code"

    def test_no_traveler_facing_endpoint_returns_the_delivery_code(self):
        surfaces = {
            "deal-detail": self.traveler.get(
                reverse("deals-detail", args=[self.deal.pk])
            ),
            "deal-list": self.traveler.get(reverse("deals-list")),
            "handover-state": self.traveler.get(
                reverse("handover-state", args=[self.deal.pk])
            ),
            "delivery-code-reveal": self.traveler.get(
                reverse("handover-delivery-code", args=[self.deal.pk])
            ),
            "delivery-code-rotate": self.traveler.post(
                reverse("handover-delivery-code-rotate", args=[self.deal.pk])
            ),
            "pickup-code-reveal": self.traveler.get(
                reverse("handover-pickup-code", args=[self.deal.pk])
            ),
            "notifications": self.traveler.get(reverse("notification-list")),
        }
        for surface, response in surfaces.items():
            self._assert_absent(response, surface)

    def test_a_failed_submission_response_does_not_echo_or_hint_at_the_code(self):
        # A near miss, guaranteed to differ. Building it as `code[:-1] + "0"`
        # silently submits the *correct* code one time in thirty-two, which is
        # a test that passes for the wrong reason far more often than it fails.
        near_miss = self.code[:-1] + ("1" if self.code[-1] == "0" else "0")
        assert near_miss != self.code
        response = self.traveler.post(
            reverse("handover-delivery-submit", args=[self.deal.pk]),
            {"code": near_miss},
            format="json",
        )
        assert response.status_code == 400
        self._assert_absent(response, "delivery-submit-failure")

    def test_the_code_is_absent_from_the_timeline_and_every_event_payload(self):
        from apps.core.models import PublishedEvent
        from apps.notifications.models import Notification

        for event in DealEvent.objects.filter(deal_id=self.deal.pk):
            assert self.code not in str(event.payload)
        for row in Notification.objects.all():
            assert self.code not in str(row.payload)
        # `PublishedEvent` stores only a hash, but assert the shape anyway.
        for row in PublishedEvent.objects.all():
            assert self.code not in row.payload_hash

    def test_the_durable_message_row_references_the_secret_rather_than_holding_it(self):
        message = OutboundMessage.objects.get(
            deal_id=self.deal.pk, kind=OutboundMessage.Kind.RECIPIENT_DELIVERY_CODE
        )
        assert self.code not in str(message.context)
        assert message.secret_ref.startswith("handover_code:")
        assert self.code not in message.secret_ref

    def test_the_traveler_sees_a_state_projection_that_says_so_explicitly(self):
        response = self.traveler.get(reverse("handover-state", args=[self.deal.pk]))
        assert response.status_code == 200
        assert response.data["traveler_can_view_delivery_code"] is False
        assert response.data["can_reveal_delivery_code"] is False
        assert response.data["can_submit_delivery_code"] is True


# --- state-machine security ---------------------------------------------------


class HandoverStateMachineTests(TestCase):
    def test_pickup_cannot_be_confirmed_before_a_recipient_exists(self):
        """Funded is not enough. Without a recipient the delivery code has
        nowhere to go, and finding that out after the parcel has changed hands
        is not a recoverable position."""

        scenario = fund_scenario(self.client, prefix="hsm")
        assert scenario.deal.status == Deal.Status.FUNDED
        code = reveal_pickup_code(scenario)
        with self.assertRaises(HandoverError) as caught:
            submit_code(
                deal_id=scenario.deal.pk,
                kind=DealHandoverCode.Kind.PICKUP,
                actor_id=scenario.traveler.pk,
                submitted_code=code,
            )
        assert caught.exception.code == "recipient_required"

    def test_delivery_cannot_be_confirmed_before_pickup(self):
        scenario = fund_scenario(self.client, prefix="hsm2")
        record_recipient(scenario)
        with self.assertRaises(HandoverError) as caught:
            submit_code(
                deal_id=scenario.deal.pk,
                kind=DealHandoverCode.Kind.DELIVERY,
                actor_id=scenario.traveler.pk,
                submitted_code="ABCD2345",
            )
        assert caught.exception.code == "pickup_not_confirmed"

    def test_a_delivery_code_does_not_exist_until_pickup_is_confirmed(self):
        scenario = fund_scenario(self.client, prefix="hsm3")
        record_recipient(scenario)
        assert not DealHandoverCode.objects.filter(
            deal_id=scenario.deal.pk, kind=DealHandoverCode.Kind.DELIVERY
        ).exists()

    def test_a_buffered_delivery_code_always_carries_its_availability_instant(self):
        """The database refuses the shape a forgetful bug would produce."""

        from django.db import IntegrityError, transaction

        scenario = fund_scenario(self.client, prefix="hsm4")
        record_recipient(scenario)
        confirm_pickup(scenario)
        row = DealHandoverCode.objects.get(
            deal_id=scenario.deal.pk, kind=DealHandoverCode.Kind.DELIVERY
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                DealHandoverCode.objects.filter(pk=row.pk).update(available_at=None)

    def test_pickup_and_delivery_deadlines_come_from_the_frozen_snapshot(self):
        """A settings change after funding cannot move a running Deal's clock."""

        from copy import deepcopy

        from apps.core.business_settings import get_active_business_settings
        from apps.core.models import BusinessSettingsVersion

        scenario = fund_scenario(self.client, prefix="hsm5")
        record_recipient(scenario)

        settings_version = get_active_business_settings()
        policy = deepcopy(settings_version.policy)
        policy["handover"]["delivery_code_buffer_seconds"] = 1
        policy["payments"]["payout"]["protection_window_seconds"] = 60
        BusinessSettingsVersion.objects.filter(pk=settings_version.pk).update(
            policy=policy
        )

        confirm_pickup(scenario)
        deal = scenario.deal
        assert deal.delivery_code_available_at - deal.pickup_confirmed_at == timedelta(
            minutes=30
        )

    def test_a_freshly_funded_deal_has_its_policy_and_pickup_instant_frozen(self):
        scenario = fund_scenario(self.client, prefix="hsm6")
        deal = scenario.deal
        assert deal.lifecycle_policy["delivery_code_buffer_seconds"] == 1_800
        assert deal.lifecycle_policy["protection_window_seconds"] == 172_800
        assert deal.lifecycle_policy["rating_review_window_seconds"] == 1_209_600
        assert deal.agreed_pickup_at is not None
        assert deal.agreed_pickup_at >= timezone.now() - timedelta(days=1)
