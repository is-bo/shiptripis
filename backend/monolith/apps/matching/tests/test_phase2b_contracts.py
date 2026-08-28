"""Phase 2B API contract regressions.

Covers the five MAJOR findings and the serialization MINORs:

* quote is a narrow sender contract, not the admin explain payload
* domain failures carry machine codes and structured fields, never prose
* the server declares `awaiting_party` / `allowed_actions` per caller
* discovery candidates carry the leg IDs the next call requires
* Offer/Deal terms expose the agreed economics, not the business policy
* a V1 EUR offer carries no legacy DZD economics
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.db import connection
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import BusinessSettingsVersion
from apps.deals.models import Deal
from apps.kyc.models import KycSubmission
from apps.matching.models import Match, Offer
from apps.parcels.models import ParcelRequest
from apps.trips.models import Journey, JourneyLeg, JourneyLegProof

from .test_phase2_matching import _approve_kyc, _location, _request, _user


class _AuthedRequest:
    """Minimal serializer-context stand-in for a DRF request."""

    def __init__(self, user):
        self.user = user


class Phase2BContractTestCase(TestCase):
    """One DRIVE journey, one off-node request, sender-first negotiation."""

    def setUp(self):
        # Discovery is scope-throttled; a shared cache would make these
        # sequential API calls 429 rather than exercise the contract.
        cache.clear()
        self.at = timezone.now()
        self.sender = _user("p2b-contract-sender@example.com")
        self.traveler = _user("p2b-contract-traveler@example.com")
        self.outsider = _user("p2b-contract-outsider@example.com")
        self.admin = _user("p2b-contract-admin@example.com", is_staff=True)
        _approve_kyc(self.traveler, "p2b-contract-traveler")
        self.kyc = KycSubmission.objects.get(user=self.traveler)

        self.origin = _location("Route origin", "36.700000", "4.000000")
        self.midpoint = _location("Route midpoint", "36.750000", "4.100000")
        self.destination = _location("Route destination", "36.800000", "4.200000")
        self.pickup = _location(
            "Sender pickup",
            "36.705000",
            "4.010000",
            owner=self.sender,
        )
        self.dropoff = _location(
            "Sender dropoff",
            "36.795000",
            "4.190000",
            owner=self.sender,
        )

        self.journey = Journey.objects.create(
            traveler=self.traveler,
            start_location=self.origin,
            destination_location=self.destination,
            status=Journey.Status.ACTIVE,
            published_at=self.at,
        )
        self.first_leg = JourneyLeg.objects.create(
            journey=self.journey,
            position=0,
            mode=JourneyLeg.Mode.DRIVE,
            origin=self.origin,
            destination=self.midpoint,
            depart_at=self.at + timedelta(hours=2),
            arrive_at=self.at + timedelta(hours=5),
            capacity_kg=Decimal("20.00"),
            distance_meters=120_000,
        )
        self.second_leg = JourneyLeg.objects.create(
            journey=self.journey,
            position=1,
            mode=JourneyLeg.Mode.DRIVE,
            origin=self.midpoint,
            destination=self.destination,
            depart_at=self.at + timedelta(hours=6),
            arrive_at=self.at + timedelta(hours=9),
            capacity_kg=Decimal("20.00"),
            distance_meters=120_000,
        )
        self.delivery_request = _request(
            sender=self.sender,
            pickup=self.pickup,
            delivery=self.dropoff,
            ready_start=self.at,
            ready_end=self.at + timedelta(hours=10),
            deadline=self.at + timedelta(hours=20),
        )

    def client_for(self, user) -> APIClient:
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def candidate(self) -> dict:
        response = self.client_for(self.sender).get(
            reverse("matches-compatible-journeys-v1"),
            {"parcel_id": self.delivery_request.pk},
        )
        assert response.status_code == 200, response.data
        assert response.data["count"] == 1, response.data
        return response.data["results"][0]

    def propose(self, reward: int | None = None):
        candidate = self.candidate()
        return self.client_for(self.sender).post(
            reverse("matches-propose-v1"),
            {
                "parcel_id": self.delivery_request.pk,
                "journey_id": self.journey.pk,
                "start_leg_id": candidate["journey"]["start_leg_id"],
                "end_leg_id": candidate["journey"]["end_leg_id"],
                "traveler_reward_eur_cents": reward
                or candidate["pricing"]["recommended_reward_eur_cents"],
            },
            format="json",
        )


class Phase2BQuoteVersusExplainTests(Phase2BContractTestCase):
    """MAJOR-1: the public quote must not be the IsAdminUser explain payload."""

    def test_quote_is_narrow_and_explain_stays_admin_only(self):
        quote = self.client_for(self.sender).post(
            reverse("matches-quote-v1"),
            {"parcel_id": self.delivery_request.pk, "journey_id": self.journey.pk},
            format="json",
        )
        assert quote.status_code == 200, quote.data

        assert set(quote.data) == {
            "delivery_request",
            "journey",
            "compatibility",
            "pricing",
        }
        assert "ranking" not in quote.data
        for internal in ("checks", "distance_components", "capacity_remaining_by_leg"):
            assert internal not in quote.data["compatibility"]
        for internal in ("matched_distance_meters", "detour_adjustment_cents"):
            assert internal not in quote.data["pricing"]

        explain_url = reverse("matches-explain-v1")
        params = {
            "parcel_id": self.delivery_request.pk,
            "journey_id": self.journey.pk,
        }
        assert self.client_for(self.sender).get(explain_url, params).status_code == 403
        assert self.client_for(self.traveler).get(explain_url, params).status_code == 403
        assert APIClient().get(explain_url, params).status_code in (401, 403)

        explain = self.client_for(self.admin).get(explain_url, params)
        assert explain.status_code == 200, explain.data
        assert explain.data["compatibility"]["checks"]
        assert explain.data["compatibility"]["distance_components"]
        assert explain.data["compatibility"]["capacity_remaining_by_leg"]
        assert explain.data["compatibility"]["pickup_route_position"] is not None
        assert explain.data["pricing"]["matched_distance_meters"] > 0
        assert explain.data["ranking"]["factors"]["route_fit"]["weight"] == 30

    def test_a_traveler_cannot_quote_another_senders_request(self):
        response = self.client_for(self.traveler).post(
            reverse("matches-quote-v1"),
            {"parcel_id": self.delivery_request.pk, "journey_id": self.journey.pk},
            format="json",
        )

        assert response.status_code == 403
        assert response.data["code"] == "not_authorized"


class Phase2BStructuredErrorTests(Phase2BContractTestCase):
    """MAJOR-2 / MINOR-6: machine-readable failures, no prose parsing."""

    def test_below_minimum_reports_the_structured_minimum(self):
        response = self.propose(reward=1)

        assert response.status_code == 409, response.data
        assert response.data["code"] == "reward_below_minimum"
        minimum = response.data["minimum_reward_eur_cents"]
        assert isinstance(minimum, int) and minimum > 1
        assert self.candidate()["pricing"]["minimum_reward_eur_cents"] == minimum

    def test_journey_not_active_is_distinguishable_from_request_not_open(self):
        candidate = self.candidate()
        body = {
            "parcel_id": self.delivery_request.pk,
            "journey_id": self.journey.pk,
            "start_leg_id": candidate["journey"]["start_leg_id"],
            "end_leg_id": candidate["journey"]["end_leg_id"],
            "traveler_reward_eur_cents": candidate["pricing"][
                "recommended_reward_eur_cents"
            ],
        }

        Journey.objects.filter(pk=self.journey.pk).update(
            status=Journey.Status.CANCELLED
        )
        journey_error = self.client_for(self.sender).post(
            reverse("matches-propose-v1"), body, format="json"
        )
        Journey.objects.filter(pk=self.journey.pk).update(status=Journey.Status.ACTIVE)

        ParcelRequest.objects.filter(pk=self.delivery_request.pk).update(
            status=ParcelRequest.Status.CANCELLED
        )
        request_error = self.client_for(self.sender).post(
            reverse("matches-propose-v1"), body, format="json"
        )

        assert journey_error.status_code == 409, journey_error.data
        assert journey_error.data["code"] == "journey_not_active"
        assert request_error.status_code == 409, request_error.data
        assert request_error.data["code"] == "request_not_open"

    def test_offer_not_pending_is_distinct_after_a_counter(self):
        proposal = self.propose()
        assert proposal.status_code == 201, proposal.data
        counter = self.client_for(self.traveler).post(
            reverse("offers-counter-v1", args=[proposal.data["id"]]),
            {"traveler_reward_eur_cents": proposal.data["traveler_reward_minor"] + 100},
            format="json",
        )
        assert counter.status_code == 201, counter.data

        stale_accept = self.client_for(self.traveler).post(
            reverse("offers-accept", args=[proposal.data["id"]]), format="json"
        )

        assert stale_accept.status_code == 409, stale_accept.data
        assert stale_accept.data["code"] == "offer_not_pending"

    def test_revoked_kyc_and_flight_proof_surface_as_rejection_codes(self):
        proposal = self.propose()
        assert proposal.status_code == 201, proposal.data
        KycSubmission.objects.filter(pk=self.kyc.pk).update(
            status=KycSubmission.Status.EXPIRED
        )

        response = self.client_for(self.traveler).post(
            reverse("offers-accept", args=[proposal.data["id"]]), format="json"
        )

        assert response.status_code == 409, response.data
        assert response.data["code"] == "incompatible_candidate"
        assert "traveler_kyc_current" in response.data["rejection_codes"]

    def test_flight_proof_revocation_is_reported_by_code(self):
        JourneyLeg.objects.filter(pk=self.second_leg.pk).update(
            mode=JourneyLeg.Mode.FLIGHT
        )
        # A FLIGHT leg with no approved proof is exactly the revoked-proof
        # state at matching time. Flight legs additionally need trusted airport
        # coordinates, so this candidate is expected to be rejected; the point
        # is that the failing gates arrive as codes, not an English sentence.
        assert not JourneyLegProof.objects.filter(
            leg=self.second_leg, status=JourneyLegProof.Status.APPROVED
        ).exists()

        response = self.client_for(self.sender).post(
            reverse("matches-quote-v1"),
            {"parcel_id": self.delivery_request.pk, "journey_id": self.journey.pk},
            format="json",
        )

        assert response.status_code == 409, response.data
        assert response.data["code"] == "incompatible_candidate"
        assert "flight_proofs_approved" in response.data["rejection_codes"]
        assert (
            response.data["rejection_codes"]
            == response.data["compatibility"]["rejection_codes"]
        )

    def test_capacity_exceeded_names_the_journey_legs(self):
        proposal = self.propose()
        assert proposal.status_code == 201, proposal.data
        JourneyLeg.objects.filter(pk=self.second_leg.pk).update(
            capacity_kg=Decimal("0.10")
        )

        response = self.client_for(self.traveler).post(
            reverse("offers-accept", args=[proposal.data["id"]]), format="json"
        )

        assert response.status_code == 409, response.data
        assert response.data["code"] == "capacity_exceeded"
        assert self.second_leg.pk in response.data["journey_leg_ids"]

    def test_proposing_onto_a_full_leg_is_a_409_not_an_unhandled_500(self):
        """The propose/counter views used to let CapacityExceeded escape."""

        candidate = self.candidate()
        body = {
            "parcel_id": self.delivery_request.pk,
            "journey_id": self.journey.pk,
            "start_leg_id": candidate["journey"]["start_leg_id"],
            "end_leg_id": candidate["journey"]["end_leg_id"],
            "traveler_reward_eur_cents": candidate["pricing"][
                "recommended_reward_eur_cents"
            ],
        }
        JourneyLeg.objects.filter(pk=self.second_leg.pk).update(
            capacity_kg=Decimal("0.10")
        )

        response = self.client_for(self.sender).post(
            reverse("matches-propose-v1"), body, format="json"
        )

        assert response.status_code == 409, response.data
        assert response.data["code"] == "capacity_exceeded"
        assert self.second_leg.pk in response.data["journey_leg_ids"]

    def test_an_unmapped_failure_is_not_labelled_business_settings_unavailable(self):
        candidate = self.candidate()
        body = {
            "parcel_id": self.delivery_request.pk,
            "journey_id": self.journey.pk,
            "start_leg_id": candidate["journey"]["start_leg_id"],
            "end_leg_id": candidate["journey"]["end_leg_id"],
            "traveler_reward_eur_cents": candidate["pricing"][
                "recommended_reward_eur_cents"
            ],
        }
        from apps.matching import v1_views

        with patch.object(
            v1_views,
            "create_sender_offer",
            side_effect=ZeroDivisionError("internal detail that must not leak"),
        ):
            with self.assertRaises(ZeroDivisionError):
                self.client_for(self.sender).post(
                    reverse("matches-propose-v1"), body, format="json"
                )

        # An exception that does reach the mapper is reported generically.
        response = v1_views._domain_error_response(
            ZeroDivisionError("internal detail that must not leak")
        )
        assert response.status_code == 500
        assert response.data["code"] == "internal_error"
        assert "internal detail" not in response.data["detail"]

    def test_business_settings_outage_keeps_its_own_code(self):
        from apps.core.business_settings import NoActiveBusinessSettings
        from apps.matching import v1_views

        response = v1_views._domain_error_response(
            NoActiveBusinessSettings("No active business settings version exists.")
        )

        assert response.status_code == 503
        assert response.data["code"] == "business_settings_unavailable"


class Phase2BOfferActionTests(Phase2BContractTestCase):
    """MAJOR-3: the server, not the client, owns the negotiation state machine."""

    def offers_for(self, user, match_id: int) -> list:
        response = self.client_for(user).get(
            reverse("matches-offers", args=[match_id])
        )
        assert response.status_code == 200, response.data
        return response.data

    def test_sender_proposal_awaits_the_traveler(self):
        proposal = self.propose()
        assert proposal.status_code == 201, proposal.data
        match_id = proposal.data["match"]

        assert proposal.data["awaiting_party"] == "traveler"
        assert proposal.data["awaiting_user_id"] == self.traveler.id
        assert proposal.data["allowed_actions"] == ["withdraw"]

        traveler_view = self.offers_for(self.traveler, match_id)[0]
        assert traveler_view["awaiting_party"] == "traveler"
        assert traveler_view["allowed_actions"] == ["accept", "counter", "decline"]

    def test_a_counter_flips_the_awaiting_side(self):
        proposal = self.propose()
        counter = self.client_for(self.traveler).post(
            reverse("offers-counter-v1", args=[proposal.data["id"]]),
            {"traveler_reward_eur_cents": proposal.data["traveler_reward_minor"] + 100},
            format="json",
        )
        assert counter.status_code == 201, counter.data
        match_id = proposal.data["match"]

        assert counter.data["awaiting_party"] == "sender"
        assert counter.data["awaiting_user_id"] == self.sender.id
        assert counter.data["allowed_actions"] == ["withdraw"]

        sender_offers = {
            row["id"]: row for row in self.offers_for(self.sender, match_id)
        }
        assert sender_offers[counter.data["id"]]["allowed_actions"] == [
            "accept",
            "counter",
            "decline",
        ]
        # The superseded parent is terminal for everyone.
        parent = sender_offers[proposal.data["id"]]
        assert parent["status"] == Offer.Status.COUNTERED
        assert parent["allowed_actions"] == []
        assert parent["awaiting_party"] is None

    def test_terminal_and_stale_states_offer_no_actions(self):
        proposal = self.propose()
        match_id = proposal.data["match"]
        accepted = self.client_for(self.traveler).post(
            reverse("offers-accept", args=[proposal.data["id"]]), format="json"
        )
        assert accepted.status_code == 201, accepted.data

        for user in (self.sender, self.traveler):
            offer = self.offers_for(user, match_id)[0]
            assert offer["status"] == Offer.Status.ACCEPTED
            assert offer["allowed_actions"] == []
            assert offer["awaiting_party"] is None

    def test_allowed_actions_is_guidance_and_never_replaces_authorization(self):
        """A stale client that ignores the empty list still fails on the server."""

        proposal = self.propose()
        self.client_for(self.traveler).post(
            reverse("offers-accept", args=[proposal.data["id"]]), format="json"
        )

        late_decline = self.client_for(self.traveler).post(
            reverse("offers-decline", args=[proposal.data["id"]]), format="json"
        )
        late_withdraw = self.client_for(self.sender).post(
            reverse("offers-withdraw", args=[proposal.data["id"]]), format="json"
        )

        assert late_decline.status_code == 409
        assert late_withdraw.status_code == 409

    def test_a_competing_match_loses_accept_once_the_request_is_matched(self):
        """`accept` is withheld the moment the request stops being open."""

        second_traveler = _user("p2b-second-traveler@example.com")
        _approve_kyc(second_traveler, "p2b-second-traveler")
        second_journey = Journey.objects.create(
            traveler=second_traveler,
            start_location=self.origin,
            destination_location=self.destination,
            status=Journey.Status.ACTIVE,
            published_at=self.at,
        )
        for position, (origin, destination) in enumerate(
            ((self.origin, self.midpoint), (self.midpoint, self.destination))
        ):
            JourneyLeg.objects.create(
                journey=second_journey,
                position=position,
                mode=JourneyLeg.Mode.DRIVE,
                origin=origin,
                destination=destination,
                depart_at=self.at + timedelta(hours=2 + 4 * position),
                arrive_at=self.at + timedelta(hours=5 + 4 * position),
                capacity_kg=Decimal("20.00"),
                distance_meters=120_000,
            )
        candidates = self.client_for(self.sender).get(
            reverse("matches-compatible-journeys-v1"),
            {"parcel_id": self.delivery_request.pk},
        )
        assert candidates.data["count"] == 2, candidates.data
        proposals = []
        for candidate in candidates.data["results"]:
            response = self.client_for(self.sender).post(
                reverse("matches-propose-v1"),
                {
                    "parcel_id": self.delivery_request.pk,
                    "journey_id": candidate["journey"]["id"],
                    "start_leg_id": candidate["journey"]["start_leg_id"],
                    "end_leg_id": candidate["journey"]["end_leg_id"],
                    "traveler_reward_eur_cents": candidate["pricing"][
                        "recommended_reward_eur_cents"
                    ],
                },
                format="json",
            )
            assert response.status_code == 201, response.data
            proposals.append(response.data)

        winner = proposals[0]
        winning_traveler = Match.objects.get(pk=winner["match"]).traveler
        accepted = self.client_for(winning_traveler).post(
            reverse("offers-accept", args=[winner["id"]]), format="json"
        )
        assert accepted.status_code == 201, accepted.data

        loser = proposals[1]
        losing_traveler = Match.objects.get(pk=loser["match"]).traveler
        offer = self.offers_for(losing_traveler, loser["match"])[0]
        assert offer["allowed_actions"] == []


class Phase2BDiscoveryContractTests(Phase2BContractTestCase):
    """MAJOR-4: a candidate row carries what the next call needs."""

    def test_candidate_carries_endpoint_legs_and_a_safe_leg_summary(self):
        candidate = self.candidate()
        journey = candidate["journey"]

        assert journey["start_leg_id"] == self.first_leg.pk
        assert journey["end_leg_id"] == self.second_leg.pk
        assert [leg["journey_leg_id"] for leg in journey["covered_legs"]] == [
            self.first_leg.pk,
            self.second_leg.pk,
        ]
        first = journey["covered_legs"][0]
        assert first["mode"] == JourneyLeg.Mode.DRIVE
        assert first["origin"]["public_label"] == "Route origin"
        assert first["destination"]["public_label"] == "Route midpoint"
        assert first["depart_at"] == self.first_leg.depart_at.isoformat()
        assert first["arrive_at"] == self.first_leg.arrive_at.isoformat()
        assert "latitude" not in first["origin"]
        assert first["origin"]["coarse_latitude"] == "36.700000"

        # The IDs are directly usable: no GET /journeys/{id} in between.
        proposal = self.client_for(self.sender).post(
            reverse("matches-propose-v1"),
            {
                "parcel_id": self.delivery_request.pk,
                "journey_id": journey["id"],
                "start_leg_id": journey["start_leg_id"],
                "end_leg_id": journey["end_leg_id"],
                "traveler_reward_eur_cents": candidate["pricing"][
                    "recommended_reward_eur_cents"
                ],
            },
            format="json",
        )
        assert proposal.status_code == 201, proposal.data

    def test_the_richer_payload_does_not_add_queries_per_candidate(self):
        for index in range(4):
            other = _user(f"p2b-extra-traveler-{index}@example.com")
            _approve_kyc(other, f"p2b-extra-{index}")
            journey = Journey.objects.create(
                traveler=other,
                start_location=self.origin,
                destination_location=self.destination,
                status=Journey.Status.ACTIVE,
                published_at=self.at,
            )
            for position, (origin, destination) in enumerate(
                ((self.origin, self.midpoint), (self.midpoint, self.destination))
            ):
                JourneyLeg.objects.create(
                    journey=journey,
                    position=position,
                    mode=JourneyLeg.Mode.DRIVE,
                    origin=origin,
                    destination=destination,
                    depart_at=self.at + timedelta(hours=2 + 4 * position),
                    arrive_at=self.at + timedelta(hours=5 + 4 * position),
                    capacity_kg=Decimal("20.00"),
                    distance_meters=120_000,
                )

        client = self.client_for(self.sender)
        client.get(
            reverse("matches-compatible-journeys-v1"),
            {"parcel_id": self.delivery_request.pk},
        )
        with CaptureQueriesContext(connection) as queries:
            response = client.get(
                reverse("matches-compatible-journeys-v1"),
                {"parcel_id": self.delivery_request.pk},
            )

        assert response.status_code == 200, response.data
        assert response.data["count"] == 5
        # Discovery itself stays at its Phase 2 constant-query budget; the rest
        # is request/session/settings reads shared by every authenticated call.
        assert len(queries) <= 12, len(queries)


class Phase2BTermsSnapshotTests(Phase2BContractTestCase):
    """MAJOR-5 / MINOR-1: agreed economics out, business policy in."""

    def test_offer_terms_expose_agreed_economics_without_the_policy(self):
        proposal = self.propose()
        assert proposal.status_code == 201, proposal.data
        terms = proposal.data["terms_snapshot"]

        assert set(terms) == {
            "canonical_currency",
            "commission_rate_bps",
            "pricing_version",
            "business_settings_version",
            "pricing",
            "compatibility",
            "policy",
            "reservation",
        }
        assert terms["policy"] == {"reservation": {"payment_grace_seconds": 3_600}}
        assert terms["reservation"] == {"payment_grace_seconds": 3_600}
        assert "ranking" not in terms
        assert terms["pricing"]["minimum_reward_eur_cents"] > 0

        stored = Offer.objects.get(pk=proposal.data["id"]).terms_snapshot
        assert stored["policy"]["ranking"]["weights"]["route_fit"] == 30
        assert stored["policy"]["matching"]["candidate_scan_limit"]
        assert stored["ranking"]["factors"]

    def test_deal_terms_expose_agreed_economics_without_the_policy(self):
        proposal = self.propose()
        accepted = self.client_for(self.traveler).post(
            reverse("offers-accept", args=[proposal.data["id"]]), format="json"
        )
        assert accepted.status_code == 201, accepted.data

        detail = self.client_for(self.sender).get(
            reverse("deals-detail", args=[accepted.data["id"]])
        )
        assert detail.status_code == 200, detail.data
        policy_snapshot = detail.data["terms"]["policy_snapshot"]

        assert policy_snapshot["policy"] == {
            "reservation": {"payment_grace_seconds": 3_600}
        }
        assert "ranking" not in policy_snapshot
        assert detail.data["terms"]["traveler_reward_minor"] > 0

        stored = Deal.objects.get(pk=accepted.data["id"]).terms.policy_snapshot
        assert stored["policy"]["ranking"]["boost_points_per_weight"] == 25

    def test_a_v1_offer_carries_no_legacy_dzd_economics(self):
        proposal = self.propose()

        for field in (
            "base_amount_dzd",
            "base_fee_dzd",
            "commission_dzd",
            "total_dzd",
        ):
            assert field not in proposal.data
        assert proposal.data["currency"] == "EUR"
        assert proposal.data["economics_version"] == Offer.EconomicsVersion.V1_EUR

        # The database still records the structural zeroes for admin/history.
        offer = Offer.objects.get(pk=proposal.data["id"])
        assert offer.base_amount_dzd == 0
        assert offer.total_dzd == 0

    def test_a_legacy_offer_keeps_its_dzd_representation(self):
        from apps.matching.serializers import OfferSerializer

        match = Match.objects.create(
            parcel=self.delivery_request.parcelrequest_ptr,
            journey=self.journey,
            start_leg=self.first_leg,
            end_leg=self.second_leg,
            sender=self.sender,
            traveler=self.traveler,
            status=Match.Status.PENDING,
        )
        legacy = Offer.objects.create(
            match=match,
            proposed_by=Offer.ProposedBy.TRAVELER,
            proposer=self.traveler,
            economics_version=Offer.EconomicsVersion.LEGACY_DZD,
            currency=Offer.Currency.DZD,
            base_amount_dzd=4_000,
            base_fee_dzd=0,
            commission_dzd=1_000,
            total_dzd=5_000,
            status=Offer.Status.PENDING,
        )

        data = OfferSerializer(legacy, context={"match": match}).data

        assert data["base_amount_dzd"] == 4_000
        assert data["total_dzd"] == 5_000
        # A legacy chain has no V1 counter/accept path, so only decline stands.
        assert (
            OfferSerializer(
                legacy,
                context={"match": match, "request": _AuthedRequest(self.sender)},
            ).data["allowed_actions"]
            == ["decline"]
        )

    def test_match_publishes_a_distance_band_not_the_exact_carried_distance(self):
        proposal = self.propose()
        detail = self.client_for(self.sender).get(
            reverse("matches-detail", args=[proposal.data["match"]])
        )

        assert detail.status_code == 200, detail.data
        assert "matched_distance_meters" not in detail.data
        assert "ranking_snapshot" not in detail.data
        assert detail.data["matched_distance_band"]["label"]
        assert detail.data["compatibility_snapshot"]["compatible"] is True
        assert "checks" not in detail.data["compatibility_snapshot"]

        stored = Match.objects.get(pk=proposal.data["match"])
        assert stored.matched_distance_meters > 0
        assert stored.ranking_snapshot["factors"]


class Phase2BPublicContractUnitTests(TestCase):
    """Projection helpers must fail closed on unknown or malformed input."""

    def test_projections_reject_non_dict_snapshots(self):
        from apps.matching.public_contract import (
            public_compatibility_payload,
            public_pricing_payload,
            public_terms_snapshot,
        )

        assert public_compatibility_payload(None) is None
        assert public_compatibility_payload("nope") is None
        assert public_pricing_payload(None, include_recommendation=True) is None
        assert public_terms_snapshot([]) is None

    def test_a_legacy_snapshot_without_leg_summaries_still_projects(self):
        from apps.matching.public_contract import public_compatibility_payload

        payload = public_compatibility_payload(
            {
                "matching_version": "v1-matching-1",
                "compatible": True,
                "covered_leg_ids": [7, 8],
                "pickup_route_position": 0.4213,
                "pickup_detour_meters": 10_486,
                "matched_distance_meters": 240_000,
                "matched_distance_method": "provider_routed_partial_road_distance",
                "capacity_remaining_by_leg": [{"remaining_kg": "9.00"}],
            }
        )

        assert payload["start_leg_id"] == 7
        assert payload["end_leg_id"] == 8
        assert payload["covered_legs"] == []
        assert payload["estimated_pickup_window"] is None
        assert payload["pickup_detour_band"] == "5_15km"
        assert payload["matched_distance_precision"] == "routed"
        assert "pickup_route_position" not in payload
        assert "pickup_detour_meters" not in payload
        assert "capacity_remaining_by_leg" not in payload

    def test_detour_and_distance_buckets_are_stable(self):
        from apps.matching.public_contract import detour_band, distance_band

        assert detour_band(0) == "under_5km"
        assert detour_band(5_000) == "under_5km"
        assert detour_band(5_001) == "5_15km"
        assert detour_band(15_001) == "over_15km"
        assert detour_band(None) is None
        assert distance_band(100_000)["label"] == "under_100km"
        assert distance_band(100_001) == {
            "label": "100_300km",
            "min_meters": 100_001,
            "max_meters": 300_000,
        }
        assert distance_band(9_000_000)["label"] == "over_5000km"
        assert distance_band(None) is None

    def test_business_settings_are_seeded_for_these_assertions(self):
        assert BusinessSettingsVersion.objects.get(version=2).policy["reservation"][
            "payment_grace_seconds"
        ] == 3_600
