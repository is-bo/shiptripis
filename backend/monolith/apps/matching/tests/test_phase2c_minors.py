"""Phase 2C: the three MINOR findings left open by the Phase 2B re-review.

MINOR-1  decline/withdraw returned a bare `{"detail": ...}` while every other
         V1 negotiation route returned a machine code.
MINOR-2  `PUBLIC_DISTANCE_BANDS` was hard-coded while `pricing.distance_bands`
         is admin-versioned, so a commercial settings change could silently
         publish a finer carried-distance resolution than the privacy band
         admits.
MINOR-3  `covered_legs` was forwarded verbatim, so a field added to the
         internal leg summary would become public by default.
"""

from __future__ import annotations

import json
from copy import deepcopy

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from apps.core.business_settings import (
    activate_business_settings,
    get_active_business_settings,
)
from apps.core.models import BusinessSettingsVersion
from apps.matching.models import Match, Offer
from apps.matching.policy import (
    Phase2Policy,
    PricingBandsReduceLocationPrivacy,
    assert_pricing_bands_preserve_location_privacy,
)
from apps.matching.public_contract import (
    PUBLIC_DISTANCE_BAND_MAXIMA,
    PUBLIC_DISTANCE_BANDS,
    PUBLIC_LEG_SUMMARY_FIELDS,
    PUBLIC_LOCATION_SUMMARY_FIELDS,
    public_compatibility_payload,
    public_leg_summary,
)

from .test_phase2b_contracts import Phase2BContractTestCase


class DeclineWithdrawErrorEnvelopeTests(Phase2BContractTestCase):
    """MINOR-1: both routes speak the V1 structured-failure contract."""

    def setUp(self):
        super().setUp()
        response = self.propose()
        assert response.status_code == 201, response.data
        self.offer_id = response.data["id"]

    def _decline(self, user):
        return self.client_for(user).post(
            reverse("offers-decline", args=[self.offer_id])
        )

    def _withdraw(self, user):
        return self.client_for(user).post(
            reverse("offers-withdraw", args=[self.offer_id])
        )

    def test_declining_your_own_offer_is_a_coded_authorization_failure(self):
        response = self._decline(self.sender)

        assert response.status_code == 403
        assert response.data["code"] == "not_authorized"

    def test_a_stranger_declining_is_a_coded_authorization_failure(self):
        response = self._decline(self.outsider)

        assert response.status_code == 403
        assert response.data["code"] == "not_authorized"

    def test_a_non_proposer_withdrawing_is_a_coded_authorization_failure(self):
        response = self._withdraw(self.traveler)

        assert response.status_code == 403
        assert response.data["code"] == "not_authorized"

    def test_declining_a_withdrawn_offer_reports_offer_not_pending(self):
        assert self._withdraw(self.sender).status_code == 200

        response = self._decline(self.traveler)

        assert response.status_code == 409
        assert response.data["code"] == "offer_not_pending"
        assert response.data["offer_status"] == Offer.Status.WITHDRAWN

    def test_withdrawing_twice_reports_offer_not_pending(self):
        assert self._withdraw(self.sender).status_code == 200

        response = self._withdraw(self.sender)

        assert response.status_code == 409
        assert response.data["code"] == "offer_not_pending"
        assert response.data["offer_status"] == Offer.Status.WITHDRAWN

    def test_withdrawing_onto_a_cancelled_match_reports_match_not_pending(self):
        offer = Offer.objects.get(pk=self.offer_id)
        Match.objects.filter(pk=offer.match_id).update(status=Match.Status.CANCELLED)

        response = self._withdraw(self.sender)

        assert response.status_code == 409
        assert response.data["code"] == "match_not_pending"
        assert response.data["match_status"] == Match.Status.CANCELLED

    def test_no_v1_negotiation_route_answers_with_prose_only(self):
        """Every failure a client can reach carries `code`, never just `detail`."""

        failures = [
            self._decline(self.sender),
            self._decline(self.outsider),
            self._withdraw(self.traveler),
        ]
        assert self._withdraw(self.sender).status_code == 200
        failures.extend([self._withdraw(self.sender), self._decline(self.traveler)])

        for response in failures:
            assert response.status_code in (403, 409), response.data
            assert "code" in response.data, response.data
            assert isinstance(response.data["code"], str)


class PublicDistanceBandInvariantTests(TestCase):
    """MINOR-2: commercial pricing cannot narrow published location precision."""

    def _policy(self, distance_bands: list[dict]) -> dict:
        active = get_active_business_settings()
        policy = deepcopy(active.policy)
        policy["pricing"]["distance_bands"] = distance_bands
        return policy

    def test_the_published_ladder_is_derived_from_one_privacy_source(self):
        maxima = [maximum for maximum, _ in PUBLIC_DISTANCE_BANDS]

        assert maxima == [*PUBLIC_DISTANCE_BAND_MAXIMA, None]
        assert PUBLIC_DISTANCE_BANDS[0][1] == "under_100km"
        assert PUBLIC_DISTANCE_BANDS[-1][1] == "over_5000km"

    def test_the_seeded_active_settings_already_satisfy_the_invariant(self):
        active = get_active_business_settings()

        assert_pricing_bands_preserve_location_privacy(active.policy)
        Phase2Policy.from_settings(active)

    def test_finer_pricing_bands_are_refused(self):
        """A 25 km band would resolve carried distance 4x finer than published."""

        policy = self._policy(
            [
                {"max_meters": 25_000, "base_cents": 300},
                {"max_meters": 100_000, "base_cents": 400},
                {"max_meters": 300_000, "base_cents": 600},
                {"max_meters": None, "base_cents": 2_400},
            ]
        )

        with self.assertRaises(PricingBandsReduceLocationPrivacy) as caught:
            assert_pricing_bands_preserve_location_privacy(policy)

        assert caught.exception.code == "pricing_bands_reduce_location_privacy"
        assert caught.exception.details()["offending_max_meters"] == [25_000]

    def test_coarser_pricing_bands_stay_allowed(self):
        policy = self._policy(
            [
                {"max_meters": 300_000, "base_cents": 600},
                {"max_meters": None, "base_cents": 2_400},
            ]
        )

        assert_pricing_bands_preserve_location_privacy(policy)

    def test_a_single_open_pricing_band_stays_allowed(self):
        policy = self._policy([{"max_meters": None, "base_cents": 1_000}])

        assert_pricing_bands_preserve_location_privacy(policy)

    def test_activation_refuses_a_privacy_reducing_revision(self):
        candidate = BusinessSettingsVersion.objects.create(
            version=9_001,
            status=BusinessSettingsVersion.Status.DRAFT,
            commission_rate_bps=2_500,
            pricing_version="v1-privacy-regression",
            policy=self._policy(
                [
                    {"max_meters": 50_000, "base_cents": 350},
                    {"max_meters": 100_000, "base_cents": 400},
                    {"max_meters": None, "base_cents": 2_400},
                ]
            ),
        )

        with self.assertRaises(PricingBandsReduceLocationPrivacy):
            activate_business_settings(candidate)

        candidate.refresh_from_db()
        assert candidate.status == BusinessSettingsVersion.Status.DRAFT
        assert (
            get_active_business_settings().pricing_version != "v1-privacy-regression"
        )

    def test_reading_a_privacy_reducing_row_fails_closed(self):
        """A row inserted outside the service boundary must not start serving."""

        smuggled = BusinessSettingsVersion(
            version=9_002,
            status=BusinessSettingsVersion.Status.DRAFT,
            commission_rate_bps=2_500,
            pricing_version="v1-smuggled",
            policy=self._policy(
                [
                    {"max_meters": 10_000, "base_cents": 200},
                    {"max_meters": None, "base_cents": 2_400},
                ]
            ),
        )

        with self.assertRaises(PricingBandsReduceLocationPrivacy):
            Phase2Policy.from_settings(smuggled)


class CoveredLegAllowlistTests(Phase2BContractTestCase):
    """MINOR-3: the leg summary is an allowlist, not a pass-through."""

    def setUp(self):
        super().setUp()
        cache.clear()

    def test_the_leg_summary_is_key_level_allowlisted(self):
        leaked = {
            **{field: "value" for field in PUBLIC_LEG_SUMMARY_FIELDS},
            "internal_route_polyline": "abc123",
            "capacity_remaining_kg": "12.500",
            "origin": {
                **{field: "value" for field in PUBLIC_LOCATION_SUMMARY_FIELDS},
                "latitude": "36.755000",
                "longitude": "4.085000",
            },
            "destination": {"longitude": "4.190000"},
        }

        projected = public_leg_summary(leaked)

        assert set(projected) == set(PUBLIC_LEG_SUMMARY_FIELDS)
        assert set(projected["origin"]) == set(PUBLIC_LOCATION_SUMMARY_FIELDS)
        assert set(projected["destination"]) == set(PUBLIC_LOCATION_SUMMARY_FIELDS)
        text = json.dumps(projected)
        assert '"latitude"' not in text
        assert '"longitude"' not in text
        assert "internal_route_polyline" not in text
        assert "capacity_remaining_kg" not in text
        assert "4.085000" not in text
        assert "4.190000" not in text

    def test_a_new_internal_leg_field_does_not_escape_the_snapshot(self):
        """Simulate a later build adding a field to the internal leg summary."""

        internal = {
            "matching_version": "v1-matching-1",
            "compatible": True,
            "rejection_codes": [],
            "covered_leg_ids": [1],
            "covered_leg_positions": [0],
            "covered_legs": [
                {
                    "journey_leg_id": 1,
                    "position": 0,
                    "mode": "DRIVE",
                    "origin": {"id": 1, "city": "Algiers"},
                    "destination": {"id": 2, "city": "Jijel"},
                    "depart_at": "2026-08-25T10:00:00+00:00",
                    "arrive_at": "2026-08-25T13:00:00+00:00",
                    "pickup_route_position": 0.4173,
                    "leg_detour_meters": 812,
                }
            ],
            "matched_distance_meters": 120_000,
        }

        payload = public_compatibility_payload(internal)
        text = json.dumps(payload)

        assert set(payload["covered_legs"][0]) == set(PUBLIC_LEG_SUMMARY_FIELDS)
        assert "pickup_route_position" not in text
        assert "leg_detour_meters" not in text
        assert "0.4173" not in text
        assert "812" not in text

    def test_a_live_candidate_still_publishes_the_allowlisted_shape(self):
        candidate = self.candidate()
        legs = candidate["compatibility"]["covered_legs"]

        assert legs
        for leg in legs:
            assert set(leg) == set(PUBLIC_LEG_SUMMARY_FIELDS)
            assert set(leg["origin"]) == set(PUBLIC_LOCATION_SUMMARY_FIELDS)
            assert set(leg["destination"]) == set(PUBLIC_LOCATION_SUMMARY_FIELDS)

    def test_a_persisted_snapshot_is_filtered_by_the_same_rules(self):
        """An Offer written by an older build is projected on the way out."""

        response = self.propose()
        assert response.status_code == 201, response.data
        offer = Offer.objects.get(pk=response.data["id"])
        snapshot = deepcopy(offer.terms_snapshot)
        snapshot["compatibility"]["covered_legs"][0]["legacy_exact_detour_meters"] = 41
        Offer.objects.filter(pk=offer.pk).update(terms_snapshot=snapshot)

        detail = self.client_for(self.traveler).get(
            reverse("matches-offers", args=[offer.match_id])
        )

        assert detail.status_code == 200, detail.data
        text = json.dumps(detail.data, default=str)
        assert "legacy_exact_detour_meters" not in text

    def test_leg_windows_survive_the_projection(self):
        """The allowlist must not silently drop the published leg schedule."""

        candidate = self.candidate()
        compatibility = candidate["compatibility"]

        assert compatibility["estimated_pickup_window"]["start"] is not None
        assert compatibility["estimated_delivery_window"]["end"] is not None
        assert compatibility["covered_legs"][0]["depart_at"] is not None


class DeclineWithdrawTerminalSemanticsTests(Phase2BContractTestCase):
    """The coded envelope must not have changed the state machine."""

    def test_withdraw_still_cancels_the_match_and_reopens_the_request(self):
        response = self.propose()
        offer_id = response.data["id"]

        withdrawn = self.client_for(self.sender).post(
            reverse("offers-withdraw", args=[offer_id])
        )

        assert withdrawn.status_code == 200
        offer = Offer.objects.select_related("match").get(pk=offer_id)
        assert offer.status == Offer.Status.WITHDRAWN
        assert offer.match.status == Match.Status.CANCELLED
        self.delivery_request.refresh_from_db()
        assert self.delivery_request.status == "open"

    def test_decline_still_cancels_the_match(self):
        response = self.propose()
        offer_id = response.data["id"]

        declined = self.client_for(self.traveler).post(
            reverse("offers-decline", args=[offer_id])
        )

        assert declined.status_code == 200
        offer = Offer.objects.select_related("match").get(pk=offer_id)
        assert offer.status == Offer.Status.DECLINED
        assert offer.match.status == Match.Status.CANCELLED
