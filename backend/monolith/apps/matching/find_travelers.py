"""Phase J4 — the frozen Find Travelers contract.

`compatible-journeys` answers "which journeys pass hard compatibility, and what
would each cost". It is a correct diagnostic payload and a poor browse payload:
it repeats the sender's own request on every row, carries pricing vocabulary the
sender did not ask about, names no Traveler at all, and publishes detour and
carried-distance *bands* that are a straight zero on every canonical V1
candidate. A sender scanning that list is reading five facts about geometry and
none about the person who would carry their parcel.

This module is the browse answer. It is a **projection**, not a second matching
engine:

* Compatibility is decided only by `apps.matching.compatibility`.
* Order is decided only by `apps.matching.ranking`, through
  `apps.matching.discovery.compatible_journeys_for_request`.
* Every field here is derived from that verdict, from the published Journey
  schedule, or from the sender's own request. Nothing is recomputed, softened
  or second-guessed.

Two things it deliberately does *not* do.

**It never publishes distance.** Canonical V1 compatibility is locality
identity: `_canonical_candidate_anchors` matches a request endpoint to a route
node by immutable matching-locality ID and returns a detour of exactly zero. So
`pickup_detour_band`, `delivery_detour_band` and `total_added_distance_band` are
`under_5km` on every canonical candidate — a constant rendered as if it were a
measurement. Repeating it invites the sender to read "2 km away" into a model
that has no such concept. J4 drops the whole vocabulary; section 3 of the phase
brief forbids reintroducing it.

**It never publishes a score.** `ranking.factors` are documented in
`apps.matching.public_contract` as reversible into corridor geometry and the
ranking weights. Route fit here is a structural classification over facts the
sender can already see — which of the Traveler's own stops are their pickup and
drop-off — and it is computed from the covered-leg set, never from the score.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db.models import Avg, Count, Exists, OuterRef, Q
from django.utils import timezone

from apps.deals.models import Deal
from apps.locations.models import AirportLocalityMapping, Place
from apps.parcels.models import DeliveryRequest, ParcelRequest
from apps.ratings.models import Rating
from apps.trips.models import JourneyLeg

from .discovery import CandidateEvaluation
from .public_contract import public_compatibility_payload, public_pricing_payload


#: Frozen route-fit vocabulary. Ordered best first. See `classify_route_fit`.
ROUTE_FIT_EXCELLENT = "excellent"
ROUTE_FIT_GOOD = "good"
ROUTE_FIT_COMPATIBLE = "compatible"
ROUTE_FIT_VALUES: tuple[str, ...] = (
    ROUTE_FIT_EXCELLENT,
    ROUTE_FIT_GOOD,
    ROUTE_FIT_COMPATIBLE,
)

#: Frozen timing-fit vocabulary. Ordered best first. See `classify_timing_fit`.
TIMING_FIT_COMFORTABLE = "comfortable"
TIMING_FIT_FITS = "fits"
TIMING_FIT_VALUES: tuple[str, ...] = (TIMING_FIT_COMFORTABLE, TIMING_FIT_FITS)

#: A full day of margin between the carrying route's published arrival and the
#: sender's own deadline. Both numbers are already the sender's to see, so this
#: threshold discloses nothing new; it only saves them the subtraction.
COMFORTABLE_DEADLINE_SLACK = timedelta(hours=24)

#: Frozen sort vocabulary.
SORT_BEST_MATCH = "best_match"
SORT_SOONEST_DEPARTURE = "soonest_departure"
SORT_VALUES: tuple[str, ...] = (SORT_BEST_MATCH, SORT_SOONEST_DEPARTURE)

#: Frozen envelope states. All three are HTTP 200 — none of them is a failure,
#: and J5 must not render any of them as one.
STATE_RESULTS = "results"
STATE_NO_CANDIDATES = "no_candidates"
STATE_REQUEST_INELIGIBLE = "request_ineligible"

#: Frozen action vocabulary.
ACTION_VIEW_JOURNEY = "view_journey"
ACTION_PROPOSE_OFFER = "propose_offer"

#: Frozen rating states.
RATING_NEW = "new"
RATING_RATED = "rated"

#: A bounded first page. Four compact cards fill a 390x844 viewport (measured
#: against the real design system in `docs/PHASE_J4_FIND_TRAVELERS_CONTRACT.md`),
#: so ten rows is a couple of screens of scrolling before the next read.
DEFAULT_PAGE_SIZE = 10


@dataclass(frozen=True, slots=True)
class FindTravelersPage:
    state: str
    reason: str | None
    request_status: str | None
    sort: str
    limit: int
    offset: int
    total: int
    results: tuple[dict, ...]

    def as_dict(self, *, request_block: dict | None) -> dict:
        has_more = self.offset + len(self.results) < self.total
        payload: dict = {
            "state": self.state,
            "sort": self.sort,
            "page": {
                "limit": self.limit,
                "offset": self.offset,
                "total": self.total,
                "has_more": has_more,
                "next_offset": (self.offset + len(self.results)) if has_more else None,
            },
            "results": list(self.results),
        }
        if request_block is not None:
            payload["request"] = request_block
        if self.state == STATE_REQUEST_INELIGIBLE:
            payload["reason"] = self.reason
            payload["request_status"] = self.request_status
        return payload


# ---------------------------------------------------------------------------
# Fit classification
# ---------------------------------------------------------------------------


def classify_route_fit(
    *,
    covered_leg_positions: list[int],
    journey_leg_count: int,
) -> str:
    """How much of this Traveler's own trip is the Sender's route.

    The question the owner asked is "is this Traveler going my way", and the
    only honest structural answer V1 holds is *where on their trip the parcel
    joins and leaves*. Canonical matching resolves both endpoints to route
    nodes, so that is exactly what the covered-leg span records.

    * `excellent` — the parcel rides the whole published Journey. The Traveler's
      trip **is** the Sender's route; no part of it can change without the
      Sender already caring about it.
    * `good` — the parcel shares one end of the trip: picked up where the
      Traveler starts, or dropped where the Traveler finishes, but not both.
    * `compatible` — the Traveler passes through. Every hard gate is satisfied
      and neither endpoint is the Traveler's own origin or destination.

    All three are genuinely compatible; ShipTrip returns nothing that is not.
    The gradient describes commitment to the route, never physical closeness,
    and never a kilometre of anything.
    """

    if not covered_leg_positions or journey_leg_count <= 0:
        return ROUTE_FIT_COMPATIBLE
    starts_at_origin = covered_leg_positions[0] == 0
    ends_at_destination = covered_leg_positions[-1] == journey_leg_count - 1
    if starts_at_origin and ends_at_destination:
        return ROUTE_FIT_EXCELLENT
    if starts_at_origin or ends_at_destination:
        return ROUTE_FIT_GOOD
    return ROUTE_FIT_COMPATIBLE


def classify_timing_fit(
    *,
    arrives_at: datetime | None,
    deadline_at: datetime | None,
) -> str | None:
    """Margin between the published arrival and the Sender's own deadline.

    Deliberately computed from the covered legs' **published** `arrive_at`, not
    from `CompatibilityResult.delivery_at`. The latter is interpolated from a
    route position, and `public_contract` keeps it internal for that reason; on
    a canonical candidate the two are the same instant anyway, because every
    anchor lands on a whole node.

    A compatible candidate has already passed `delivery_before_deadline`. Where
    the published arrival is later than the interpolated one — possible only on
    a legacy mid-leg anchor — the gate, not this label, is authoritative, so the
    result floors at `fits` rather than contradicting it.
    """

    if arrives_at is None or deadline_at is None:
        return None
    if deadline_at - arrives_at >= COMFORTABLE_DEADLINE_SLACK:
        return TIMING_FIT_COMFORTABLE
    return TIMING_FIT_FITS


# ---------------------------------------------------------------------------
# Traveler trust signals
# ---------------------------------------------------------------------------


def first_name(full_name: str) -> str:
    """The Traveler's first name, and nothing after it.

    `JourneySerializer` already publishes `traveler_name` — the whole
    `full_name` — to any authenticated viewer of a discoverable journey, so this
    is a narrowing of an existing disclosure, not a new one. A browse row needs
    enough to address someone, not enough to look them up.

    A Traveler with no name on file resolves to an empty string. The local part
    of an email address is not a name and is never published as one.
    """

    cleaned = (full_name or "").strip()
    return cleaned.split()[0] if cleaned else ""


def _empty_trust() -> dict:
    return {
        "rating": {"state": RATING_NEW, "average": None, "count": 0},
        "completed_deliveries": 0,
    }


def traveler_trust_signals(traveler_ids: list[int], *, at: datetime) -> dict[int, dict]:
    """Rating and completed-delivery history for a bounded set of Travelers.

    Exactly two grouped queries, whatever the candidate count: both aggregates
    are keyed by the already-filtered Traveler IDs rather than correlated per
    row. A candidate list of one and a candidate list of forty cost the same.

    **Ratings respect the blind window.** `apps.ratings.services.is_revealed` is
    "the window frozen on the row has passed, or both sides have spoken"; both
    halves are expressible in SQL, so an unrevealed rating is excluded here
    exactly as it is excluded from the rating API. Only ratings written by a
    Sender are counted — those are the ones describing this person *as a
    Traveler*.
    """

    if not traveler_ids:
        return {}

    counterpart = Rating.objects.filter(deal_id=OuterRef("deal_id")).exclude(
        rater_role=OuterRef("rater_role")
    )
    rating_rows = (
        Rating.objects.filter(
            ratee_id__in=traveler_ids,
            rater_role=Rating.RaterRole.SENDER,
        )
        .annotate(counterpart_submitted=Exists(counterpart))
        .filter(Q(review_window_ends_at__lte=at) | Q(counterpart_submitted=True))
        .values("ratee_id")
        .annotate(average=Avg("score"), rated_count=Count("id"))
    )
    ratings = {
        row["ratee_id"]: (row["average"], row["rated_count"]) for row in rating_rows
    }

    # Completed delivery history, and only that. A published Journey, a sent
    # offer and a matched request are all things that have not happened yet.
    delivery_rows = (
        Deal.objects.filter(
            traveler_id__in=traveler_ids,
            status=Deal.Status.COMPLETED,
        )
        .values("traveler_id")
        .annotate(delivered=Count("id"))
    )
    deliveries = {row["traveler_id"]: row["delivered"] for row in delivery_rows}

    signals: dict[int, dict] = {}
    for traveler_id in traveler_ids:
        average, count = ratings.get(traveler_id, (None, 0))
        signals[traveler_id] = {
            "rating": (
                {"state": RATING_NEW, "average": None, "count": 0}
                if not count or average is None
                # One decimal. A Traveler with three ratings does not have a
                # reputation measured to four.
                else {
                    "state": RATING_RATED,
                    "average": round(float(average), 1),
                    "count": count,
                }
            ),
            "completed_deliveries": deliveries.get(traveler_id, 0),
        }
    return signals


# ---------------------------------------------------------------------------
# Route projection
# ---------------------------------------------------------------------------


def _isoformat(value) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else value


def _locality_of(place: Place | None) -> Place | None:
    """The canonical locality a route node resolves to, without a new query.

    `_matching_journey_queryset` already prefetches each leg place's active
    primary served mapping with `select_related("locality")`, so an airport's
    city is in memory by the time a candidate is projected. The fallback read
    exists only so a caller that assembled legs some other way still gets a
    correct answer instead of a blank stop.
    """

    if place is None:
        return None
    if place.place_type == Place.PlaceType.LOCALITY:
        return place if place.active else None
    prefetched = getattr(place, "_active_matching_mappings", None)
    if prefetched is not None:
        return prefetched[0].locality if prefetched else None
    mapping = (
        place.airport_mappings.filter(
            active=True,
            is_primary=True,
            relationship_type=AirportLocalityMapping.RelationshipType.SERVED,
            locality__active=True,
        )
        .select_related("locality")
        .first()
    )
    return mapping.locality if mapping else None


def _legacy_label(*locations) -> tuple[str, str | None]:
    """Coarse label and country from a pre-8C `Location`, or an empty answer.

    Every V1 journey is canonical, but a pre-8C journey that is still active
    carries `origin`/`destination` `Location` rows and no `Place` at all — and a
    route of unlabelled stops is the exact defect J1.2 spent a phase fixing. The
    fields used here are `public_label` and `city`, both already in
    `PUBLIC_LOCATION_SUMMARY_FIELDS`, so this is the same coarse disclosure the
    public serializer has always made and never the private label.
    """

    for location in locations:
        if location is None:
            continue
        label = (location.public_label or location.city or "").strip()
        if label:
            return label, location.country_code or None
    return "", None


def _stop(
    *,
    arriving_place: Place | None,
    departing_place: Place | None,
    arriving_location=None,
    departing_location=None,
    arrive_at,
    depart_at,
) -> dict:
    """One public stop on the carrying route.

    The spec's locked route UX is "airports are a facet of a stop": a node
    reads `Algiers · ALG`, never `Houari Boumediene`, because an airport and
    the city it serves are the same stop. So the label is the **locality** and
    the airport rides alongside it as an IATA code.

    Which airport: the one the parcel *arrives* on, if any, otherwise the one
    it leaves on. Both sides of a node resolve to the same matching locality by
    construction — that is the continuity rule — so this only ever chooses
    between two spellings of one place.

    Catalogue identity and label only. No coordinates: a `Place` summary has
    never carried them pre-funding, and a browse card is not the place to
    start.
    """

    locality = _locality_of(arriving_place) or _locality_of(departing_place)
    airport = next(
        (
            place
            for place in (arriving_place, departing_place)
            if place is not None and place.place_type == Place.PlaceType.AIRPORT
        ),
        None,
    )
    label = locality.display_label if locality else ""
    country_code = locality.country_id if locality else None
    if not label:
        label, country_code = _legacy_label(arriving_location, departing_location)
    return {
        "place_id": locality.pk if locality else None,
        "label": label,
        "country_code": country_code,
        "airport_iata": (airport.iata_code or None) if airport else None,
        "arrive_at": _isoformat(arrive_at),
        "depart_at": _isoformat(depart_at),
    }


def project_route(
    covered_legs: list[JourneyLeg],
    *,
    journey_leg_count: int,
    first_covered_position: int | None,
    last_covered_position: int | None,
) -> dict:
    """The carrying sub-route, ordered, with the surrounding trip acknowledged.

    Only the legs that carry this parcel are projected. The rest of the
    Traveler's itinerary is not secret — `GET /api/journeys/{id}` serves the
    whole published Journey to any authenticated user — but it is not the
    Sender's business on a browse row, and dumping it is what makes a card too
    tall to scan. `continues_before`/`continues_after` say the trip is longer
    without saying where, so J5 can draw the ellipsis the owner's sketch
    implies.
    """

    stops: list[dict] = []
    segments: list[dict] = []
    for index, leg in enumerate(covered_legs):
        previous = covered_legs[index - 1] if index else None
        stops.append(
            _stop(
                arriving_place=previous.destination_place if previous else None,
                departing_place=leg.origin_place,
                arriving_location=previous.destination if previous else None,
                departing_location=leg.origin,
                arrive_at=previous.arrive_at if previous else None,
                depart_at=leg.depart_at,
            )
        )
        segments.append(
            {
                "journey_leg_id": leg.pk,
                "mode": leg.mode,
                "depart_at": _isoformat(leg.depart_at),
                "arrive_at": _isoformat(leg.arrive_at),
            }
        )
    if covered_legs:
        last = covered_legs[-1]
        stops.append(
            _stop(
                arriving_place=last.destination_place,
                departing_place=None,
                arriving_location=last.destination,
                departing_location=None,
                arrive_at=last.arrive_at,
                depart_at=None,
            )
        )
    return {
        "stops": stops,
        "segments": segments,
        "continues_before": bool(first_covered_position),
        "continues_after": (
            last_covered_position is not None
            and journey_leg_count > 0
            and last_covered_position < journey_leg_count - 1
        ),
    }


def primary_mode(segments: list[dict]) -> str | None:
    """`FLIGHT` when any covered leg flies, otherwise the mode that is carrying.

    Not the longest leg and not the first: if this parcel gets on a plane, the
    plane is the fact that decides everything else about the trip — the proof,
    the customs, the schedule the Sender cannot influence.
    """

    modes = [segment.get("mode") for segment in segments if segment.get("mode")]
    if not modes:
        return None
    if JourneyLeg.Mode.FLIGHT in modes:
        return JourneyLeg.Mode.FLIGHT
    return modes[0]


# ---------------------------------------------------------------------------
# Match explanation
# ---------------------------------------------------------------------------


def match_reasons(
    *,
    route: dict,
    route_fit: str,
    timing_fit: str | None,
    arrives_at,
    deadline_at,
    weight_kg,
    has_flight_leg: bool,
) -> list[dict]:
    """"Why this trip fits", as codes the client localises.

    Every entry is backed by a gate that actually passed or by a published
    schedule value. There is no formula here and no score: a Sender is told what
    is true about the trip, not how ShipTrip arrived at the order.
    """

    stops = route.get("stops") or []
    reasons: list[dict] = []
    if stops:
        reasons.append({"code": "picks_up_in", "params": {"place": stops[0]["label"]}})
        reasons.append({"code": "arrives_in", "params": {"place": stops[-1]["label"]}})
    transfers = max(0, len(route.get("segments") or []) - 1)
    reasons.append(
        {"code": "direct_leg", "params": {}}
        if transfers == 0
        else {"code": "transfers", "params": {"count": transfers}}
    )
    if route_fit == ROUTE_FIT_EXCELLENT:
        reasons.append({"code": "whole_trip_matches", "params": {}})
    if timing_fit is not None and arrives_at and deadline_at:
        reasons.append(
            {
                "code": "arrives_before_deadline",
                "params": {"arrives_at": arrives_at, "deadline_at": deadline_at},
            }
        )
    if weight_kg is not None:
        reasons.append({"code": "has_room_for", "params": {"weight_kg": weight_kg}})
    # KYC is a hard gate, so this is true of every candidate in the list. It is
    # stated here, once, inside the explanation — not badged on every row, where
    # a universal truth reads as a distinction.
    reasons.append({"code": "identity_verified", "params": {}})
    if has_flight_leg:
        reasons.append({"code": "flight_proof_approved", "params": {}})
    return reasons


# ---------------------------------------------------------------------------
# Candidate projection
# ---------------------------------------------------------------------------


def _parse(value) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        return datetime.fromisoformat(value)
    return None


def candidate_payload(
    evaluation: CandidateEvaluation,
    *,
    trust: dict,
    public_compatibility: dict,
    public_pricing: dict | None,
) -> dict:
    """One browse row. Route and fit first, person second, money last.

    Everything a J5 card and the propose sheet behind it need, and nothing that
    would cost the sender a second request. The privacy allowlist *is* this
    function's shape: a field not built here cannot be published here.
    """

    journey = evaluation.journey
    traveler = journey.traveler
    legs = list(getattr(journey, "_matching_legs", ()) or ())
    # The leg *models* the verdict was computed over, not their public dicts.
    # A stop has to name the locality behind an airport, and that locality is
    # already in memory on the prefetched mapping — resolving it from a summary
    # dict would cost a query per stop to recover data the scan already read.
    covered_legs = list(evaluation.compatibility.covered_legs)
    covered_positions = [leg.position for leg in covered_legs]
    route = project_route(
        covered_legs,
        journey_leg_count=len(legs),
        first_covered_position=covered_positions[0] if covered_positions else None,
        last_covered_position=covered_positions[-1] if covered_positions else None,
    )
    arrival = covered_legs[-1].arrive_at if covered_legs else None
    departs_at = _isoformat(covered_legs[0].depart_at) if covered_legs else None
    arrives_at = _isoformat(arrival)
    deadline_at = evaluation.delivery_request.deadline_at
    route_fit = classify_route_fit(
        covered_leg_positions=covered_positions,
        journey_leg_count=len(legs),
    )
    timing_fit = classify_timing_fit(arrives_at=arrival, deadline_at=deadline_at)
    has_flight_leg = any(
        (segment.get("mode") or "") == JourneyLeg.Mode.FLIGHT
        for segment in route["segments"]
    )
    start_leg_id = public_compatibility.get("start_leg_id")
    end_leg_id = public_compatibility.get("end_leg_id")
    can_propose = start_leg_id is not None and end_leg_id is not None
    weight_kg = evaluation.delivery_request.actual_weight_kg

    return {
        "journey_id": journey.pk,
        "traveler": {
            "id": traveler.pk,
            "display_name": first_name(traveler.full_name),
            # No profile photo exists anywhere in the V1 data model. The field
            # is present and null so a J5 card can design for both shapes and
            # so landing photos later is not a contract change.
            "avatar_url": None,
            # True of every returned candidate: `traveler_kyc_current` is a hard
            # gate. Published because it is the authoritative answer, not
            # because it distinguishes one row from another — see
            # `match_reasons`.
            "identity_verified": True,
            **trust,
        },
        "route": route,
        "route_fit": route_fit,
        "timing_fit": timing_fit,
        "departs_at": departs_at,
        "arrives_at": arrives_at,
        "transfers": max(0, len(route["segments"]) - 1),
        "primary_mode": primary_mode(route["segments"]),
        "match_reasons": match_reasons(
            route=route,
            route_fit=route_fit,
            timing_fit=timing_fit,
            arrives_at=arrives_at,
            deadline_at=deadline_at.isoformat() if deadline_at else None,
            weight_kg=str(weight_kg) if weight_kg is not None else None,
            has_flight_leg=has_flight_leg,
        ),
        "caveats": list(public_compatibility.get("limitations") or []),
        # The propose sheet's own inputs. Deliberately four numbers and not the
        # whole pricing block: bands, precision tags, version strings and
        # adjustment flags are diagnostics, and a sheet that asks "how much are
        # you offering" renders none of them.
        "economics": (
            None
            if public_pricing is None
            else {
                "currency": public_pricing.get("currency", "EUR"),
                "minimum_reward_eur_cents": public_pricing.get(
                    "minimum_reward_eur_cents"
                ),
                "minimum_economics": public_pricing.get("minimum_economics"),
                "recommended_reward_eur_cents": public_pricing.get(
                    "recommended_reward_eur_cents"
                ),
                "recommended_economics": public_pricing.get("recommended_economics"),
            }
        ),
        # Echoed back unchanged by `POST /api/matches/propose`. A recomputed
        # range is refused with `invalid_leg_range`.
        "proposal": (
            {
                "journey_id": journey.pk,
                "start_leg_id": start_leg_id,
                "end_leg_id": end_leg_id,
            }
            if can_propose
            else None
        ),
        "actions": [
            {"code": ACTION_VIEW_JOURNEY, "available": True, "reason": None},
            {
                "code": ACTION_PROPOSE_OFFER,
                "available": can_propose,
                "reason": None if can_propose else "leg_range_unresolved",
            },
        ],
    }


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------


def request_block(delivery_request: DeliveryRequest, *, pricing: dict | None) -> dict:
    """The Sender's own request, sent once per page instead of once per row.

    `compatible-journeys` repeats this block on every candidate, which on a
    fifty-row answer is fifty copies of facts the Sender typed themselves.
    """

    quote = pricing or {}
    return {
        "id": delivery_request.pk,
        "actual_weight_kg": (
            str(delivery_request.actual_weight_kg)
            if delivery_request.actual_weight_kg is not None
            else None
        ),
        "volumetric_weight_kg": quote.get("volumetric_weight_kg"),
        "chargeable_weight_kg": quote.get("chargeable_weight_kg"),
        "ready_window_start": _isoformat(delivery_request.ready_window_start),
        "ready_window_end": _isoformat(delivery_request.ready_window_end),
        "deadline_at": _isoformat(delivery_request.deadline_at),
        # The Sender's own posted economics. Present for the propose sheet, not
        # for the browse row: a Sender already knows what they offered, and
        # repeating it on every card is the density the owner objected to.
        "chosen_reward_eur_cents": int(delivery_request.traveler_reward_eur_cents or 0),
        "boost_eur_cents": int(delivery_request.boost_eur_cents or 0),
        "total_offered_reward_eur_cents": (
            int(delivery_request.traveler_reward_eur_cents or 0)
            + int(delivery_request.boost_eur_cents or 0)
        ),
    }


def request_ineligibility(delivery_request: DeliveryRequest) -> str | None:
    """Why this request cannot be matched at all, or `None` when it can.

    Until J4 this was invisible. A cancelled request and a route nobody travels
    both produced an empty list, because every candidate simply failed the
    `request_active` gate one by one. They are different screens, and the server
    is the only party that can tell them apart.
    """

    status = delivery_request.status
    if status == ParcelRequest.Status.OPEN:
        return None
    if status == ParcelRequest.Status.AWAITING_DEPOSIT:
        return "awaiting_deposit"
    if status == ParcelRequest.Status.MATCHED:
        return "already_matched"
    if status in (ParcelRequest.Status.CANCELLED, ParcelRequest.Status.EXPIRED):
        return "closed"
    return "in_progress"


def find_travelers(
    *,
    delivery_request: DeliveryRequest,
    candidates: list[CandidateEvaluation],
    sort: str = SORT_BEST_MATCH,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
    at: datetime | None = None,
) -> tuple[FindTravelersPage, dict | None]:
    """Page and project an already-ranked candidate list.

    `candidates` arrives in ShipTrip's authoritative best-fit order from
    `compatible_journeys_for_request`. This function never re-filters it and
    never reorders it except for an explicit alternative sort.
    """

    at = at or timezone.now()
    reason = request_ineligibility(delivery_request)
    if reason is not None:
        return (
            FindTravelersPage(
                state=STATE_REQUEST_INELIGIBLE,
                reason=reason,
                request_status=delivery_request.status,
                sort=sort,
                limit=limit,
                offset=offset,
                total=0,
                results=(),
            ),
            None,
        )

    projections: list[tuple[CandidateEvaluation, dict, dict | None]] = []
    for evaluation in candidates:
        compatibility = public_compatibility_payload(evaluation.compatibility.as_dict())
        assert compatibility is not None
        pricing = public_pricing_payload(
            evaluation.pricing.as_dict() if evaluation.pricing else None,
            # The caller owns the request, so the detour-bearing recommendation
            # is about their own parcel and may be returned — the same rule
            # `compatible-journeys` applies.
            include_recommendation=True,
        )
        projections.append((evaluation, compatibility, pricing))

    # Weight figures are a property of the parcel, identical on every row, so
    # the first candidate's quote is as good as any for the shared block.
    block = request_block(
        delivery_request, pricing=projections[0][2] if projections else None
    )

    traveler_ids = list(
        dict.fromkeys(
            evaluation.journey.traveler_id for evaluation, _, _ in projections
        )
    )
    signals = traveler_trust_signals(traveler_ids, at=at)

    rows = [
        candidate_payload(
            evaluation,
            trust=signals.get(evaluation.journey.traveler_id) or _empty_trust(),
            public_compatibility=compatibility,
            public_pricing=pricing,
        )
        for evaluation, compatibility, pricing in projections
    ]

    if sort == SORT_SOONEST_DEPARTURE:
        # Stable and total: `journey_id` is the same last-resort tiebreak the
        # best-match order uses, so a page boundary can never duplicate or drop
        # a row. A leg with no published departure sorts last rather than
        # crashing the comparison.
        rows.sort(
            key=lambda row: (
                _parse(row.get("departs_at")) is None,
                _parse(row.get("departs_at")) or at,
                row["journey_id"],
            )
        )

    total = len(rows)
    window = tuple(rows[offset : offset + limit])
    return (
        FindTravelersPage(
            state=STATE_RESULTS if total else STATE_NO_CANDIDATES,
            reason=None,
            request_status=delivery_request.status,
            sort=sort,
            limit=limit,
            offset=offset,
            total=total,
            results=window,
        ),
        block,
    )
