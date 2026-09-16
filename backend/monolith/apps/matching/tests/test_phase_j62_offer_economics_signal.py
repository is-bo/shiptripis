"""J6.2 — a Boost edit tells the Traveler's open offer to re-read its money.

J6.1 made a pending offer publish Boost-inclusive totals and made acceptance
refuse totals that no longer bind. What it left was the gap in between: the
sender changes their Boost, and a Traveler with the offer already open keeps
reading the old figure until they refresh or their accept is refused.

What is being defended:

**A hint, never a figure.** `offer.economics_changed` carries identifiers and
nothing else. The client re-reads the offer; the offer API stays the only place
a total comes from.

**Exactly the offers whose figures moved.** Pending V1 offers on pending matches
for the edited request. Not the sender who made the edit, not a countered,
declined, expired or accepted offer, not a Traveler on some other request.

**Neutral.** Resolved on arrival, so it never raises the bell badge, and
ineligible for push, so it never wakes a phone. One edit, one signal per open
offer; a no-op edit signals nothing and a refused edit signals nothing.

**The guard is still the guarantee.** Realtime is UX. An accept that echoes the
figures from before the edit is still refused `offer_economics_changed`, and the
re-read figures still accept.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.boosts.services import BoostError
from apps.deals.models import Deal
from apps.deals.tests.phase4_factories import enable_mock_rail
from apps.finance.tests.factories import build_scenario
from apps.matching.models import Offer
from apps.matching.tests.test_phase_j61_offer_boost_projection import (
    accept,
    client_for,
    confirmed,
    latest_offer,
    propose,
    set_boost,
)
from apps.notifications.models import Notification
from apps.notifications.push import _PUSH_SPECS

CHANNEL = "offer.economics_changed"


class OfferEconomicsSignalTests(TestCase):
    def setUp(self):
        self.redis = patch("apps.core.redis_bus.get_client").start()
        self.addCleanup(patch.stopall)

    def _signals(self):
        return list(Notification.objects.filter(channel=CHANNEL).order_by("pk"))

    def _edit(self, scenario, amount: int) -> list[Notification]:
        """Edit the Boost through commit; return the signals it produced."""

        before = {row.pk for row in self._signals()}
        with self.captureOnCommitCallbacks(execute=True):
            set_boost(scenario, amount)
        return [row for row in self._signals() if row.pk not in before]

    def _active_count(self, user) -> int:
        response = client_for(user).get(reverse("notification-unread-count"))
        assert response.status_code == 200, response.data
        return response.data["active"]

    def test_increase_decrease_and_removal_each_signal_the_traveler_once(self):
        scenario = build_scenario(prefix="j62s")
        set_boost(scenario, 500)
        proposed = propose(scenario, reward=2_000)
        match_id = proposed["match"]
        assert latest_offer(scenario.traveler, match_id)["traveler_total_minor"] == 2_500
        badge = self._active_count(scenario.traveler)

        # Each edit: one signal, to the Traveler only, identifiers only -- and
        # the offer API, re-read, is where the new figure comes from.
        for amount, traveler_total, boost_row in (
            (800, 2_800, 800),  # increase
            (300, 2_300, 300),  # decrease
            (0, 2_000, 0),  # removal
        ):
            self.redis.reset_mock()
            signals = self._edit(scenario, amount)
            assert [row.recipient_id for row in signals] == [scenario.traveler.pk]
            payload = signals[0].payload
            assert set(payload) == {"event_id", "ts", "targets", "match_id", "offer_id"}
            assert payload["match_id"] == match_id
            assert payload["offer_id"] == proposed["id"]
            assert payload["targets"] == [scenario.traveler.pk]
            # Relayed to the socket after commit, on its own channel.
            published = [call.args[0] for call in self.redis.return_value.publish.call_args_list]
            assert published == [CHANNEL]

            reread = latest_offer(scenario.traveler, match_id)
            assert reread["id"] == proposed["id"]
            assert reread["boost_terms_status"] == "provisional"
            assert reread["boost_amount_minor"] == boost_row
            assert reread["traveler_total_minor"] == traveler_total

        # Neutral: no badge movement, no push specification, nothing for the
        # sender who made the edits.
        assert self._active_count(scenario.traveler) == badge
        assert CHANNEL not in _PUSH_SPECS
        history = client_for(scenario.traveler).get(
            reverse("notification-list"), {"bucket": "history", "channel": CHANNEL}
        )
        assert history.data["count"] == 3
        assert not Notification.objects.filter(
            channel=CHANNEL, recipient=scenario.sender
        ).exists()

    def test_a_no_op_or_refused_edit_signals_nothing_and_nothing_before_commit(self):
        scenario = build_scenario(prefix="j62n")
        set_boost(scenario, 500)
        propose(scenario)

        assert self._edit(scenario, 500) == []

        with self.captureOnCommitCallbacks(execute=False) as pending:
            set_boost(scenario, 900)
            # The inbox obligation commits with the edit; the relay waits for it.
            self.redis.return_value.publish.assert_not_called()
        assert pending

        # A refused cut writes nothing, so it tells nobody anything.
        with patch(
            "apps.boosts.services._assert_deposit_still_covered",
            side_effect=BoostError("refused", code="boost_below_prepaid_deposit"),
        ):
            before = len(self._signals())
            with self.assertRaises(BoostError):
                set_boost(scenario, 100)
            assert len(self._signals()) == before

    def test_only_open_offers_on_this_request_are_signalled(self):
        enable_mock_rail()
        edited = build_scenario(prefix="j62e")
        elsewhere = build_scenario(prefix="j62o")
        propose(elsewhere)

        # A countered offer is history; the counter that replaced it is open.
        proposed = propose(edited)
        counter = client_for(edited.traveler).post(
            reverse("offers-counter-v1", args=[proposed["id"]]),
            {"traveler_reward_eur_cents": 2_400},
            format="json",
        )
        assert counter.status_code == 201, counter.data
        signals = self._edit(edited, 600)
        assert [row.payload["offer_id"] for row in signals] == [counter.data["id"]]
        assert [row.recipient_id for row in signals] == [edited.traveler.pk]
        assert not Notification.objects.filter(
            channel=CHANNEL, recipient=elsewhere.traveler
        ).exists()

        # An expired pending offer's figures bind nothing, so it is not told.
        open_offer = Offer.objects.filter(pk=counter.data["id"])
        expires_at = open_offer.get().expires_at
        open_offer.update(expires_at=timezone.now() - timedelta(minutes=1))
        assert self._edit(edited, 700) == []
        open_offer.update(expires_at=expires_at)

        # A declined offer is closed.
        declined = client_for(edited.sender).post(
            reverse("offers-decline", args=[counter.data["id"]]), format="json"
        )
        assert declined.status_code == 200, declined.data
        assert self._edit(edited, 800) == []

    def test_an_accepted_offer_is_frozen_and_never_signalled(self):
        enable_mock_rail()
        scenario = build_scenario(prefix="j62f")
        set_boost(scenario, 500)
        match_id = propose(scenario)["match"]
        shown = latest_offer(scenario.traveler, match_id)
        assert accept(scenario.traveler, shown["id"], **confirmed(shown)).status_code == 201

        before = len(self._signals())
        with self.assertRaises(BoostError):
            set_boost(scenario, 900)
        assert len(self._signals()) == before
        assert latest_offer(scenario.traveler, match_id)["boost_terms_status"] == "frozen"

    def test_the_stale_accept_guard_still_decides_whatever_the_signal_did(self):
        enable_mock_rail()
        scenario = build_scenario(prefix="j62g")
        set_boost(scenario, 500)
        match_id = propose(scenario)["match"]
        # The Traveler read €25.00 and tapped Accept before the signal landed.
        shown = latest_offer(scenario.traveler, match_id)
        assert shown["traveler_total_minor"] == 2_500

        assert len(self._edit(scenario, 800)) == 1
        refused = accept(scenario.traveler, shown["id"], **confirmed(shown))
        assert refused.status_code == 409, refused.data
        assert refused.data["code"] == "offer_economics_changed"
        assert not Deal.objects.exists()

        # The re-read the signal triggers is what the Traveler then accepts.
        reread = latest_offer(scenario.traveler, match_id)
        assert reread["traveler_total_minor"] == 2_800
        response = accept(scenario.traveler, reread["id"], **confirmed(reread))
        assert response.status_code == 201, response.data
        assert Deal.objects.get().terms.traveler_total_minor == 2_800
