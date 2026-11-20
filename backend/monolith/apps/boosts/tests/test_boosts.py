"""The Boost rule that outranks every other: it never creates compatibility.

A boost changes where a compatible request appears in a list. It never makes an
incompatible request compatible: ranking refuses a candidate that failed hard
compatibility, whatever the request's Boost. The J2 reward Boost itself is
covered by `test_j2_boost.py`.
"""

from __future__ import annotations

from django.test import TestCase

from apps.boosts.services import set_boost_intent
from apps.finance.tests.factories import build_scenario
from apps.matching.compatibility import CompatibilityResult
from apps.matching.policy import Phase2Policy
from apps.matching.ranking import rank_compatible_candidate


class BoostCompatibilityInvariantTests(TestCase):
    def test_ranking_raises_on_incompatible_candidate_regardless_of_boost(self):
        """Compatibility must pass before ranking; no boost can bypass it."""

        scenario = build_scenario(prefix="bci1")
        policy = Phase2Policy.from_settings(scenario.policy.settings_version)
        set_boost_intent(
            delivery_request_id=scenario.delivery_request.pk,
            actor_id=scenario.sender.pk,
            amount_eur_cents=5_000,
        )
        scenario.delivery_request.refresh_from_db()
        assert scenario.delivery_request.is_ranking_boost_active() is True

        incompatible = CompatibilityResult(
            compatible=False,
            rejection_codes=("route_detour_exceeded",),
            checks=(),
            covered_legs=(),
            pickup_position=None,
            delivery_position=None,
            pickup_at=None,
            delivery_at=None,
            pickup_added_duration_seconds=None,
            pickup_detour_meters=0,
            delivery_detour_meters=0,
            added_distance_meters=0,
            added_duration_seconds=None,
            matched_distance_meters=None,
            matched_distance_method="unavailable",
            distance_components=(),
            capacity_remaining_by_leg=(),
            limitations=(),
            route_provider=None,
        )

        with self.assertRaises(ValueError) as caught:
            rank_compatible_candidate(
                compatibility=incompatible,
                delivery_request=scenario.delivery_request,
                policy=policy,
            )
        assert "Hard compatibility must pass before ranking." in str(caught.exception)
