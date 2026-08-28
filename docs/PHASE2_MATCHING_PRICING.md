# ShipTrip V1 Phase 2: matching and pricing

This is the backend/API handoff for the later mobile phase. Phase 2 adds
matching, explainable pricing, ranking, and pre-payment capacity reservations.
It does **not** add payment processing, payouts, handover codes, disputes,
ratings, or paid boost purchases.

Phase 2B revised the **read** contract after an independent review. The domain
engine (compatibility, pricing, ranking, concurrency) is unchanged; what a party
is allowed to *see* is not. Read
[Public and internal representations](#public-and-internal-representations)
before consuming any matching payload — the shapes below are the ones the
Phase 5 client must build against.

## Architecture

The flow is intentionally split into four layers:

1. `routing` supplies provider-neutral geocoding, reverse geocoding, directions,
   road distance/duration, and corridor data. Provider results are validated,
namespaced, cached, and bounded by a per-request external-call budget, including
offer preflight as well as discovery.
2. `matching.compatibility` finds ordered pickup/delivery anchors across Journey
   legs and applies hard gates. It returns covered leg IDs, time/capacity state,
   detours, matched distance, limitations, and rejection codes.
3. `matching.pricing` and `matching.ranking` run only after compatibility. They
   consume one immutable `BusinessSettingsVersion` and produce explainable
   snapshots.
4. `matching.v1_services` owns sender-first negotiation and transactional
   acceptance. `deals` owns the persistent pending-payment allocation lifecycle.

Compatibility is server-authoritative. Boost is a ranking input only and can
never change a failed hard gate.

## Route provider and fallback

Configuration:

- `ROUTE_PROVIDER_CLASS`
- `ROUTE_PROVIDER_OPTIONS`
- `ROUTE_PROVIDER_CACHE_URL`
- `ROUTE_PROVIDER_CACHE_NAMESPACE`
- `ROUTE_PROVIDER_CACHE_TTL_SECONDS`
- `ROUTE_PROVIDER_MAX_EXTERNAL_CALLS_PER_MATCHING_REQUEST`

`GET /api/routes/provider-status` reports configured capabilities or a stable
unavailable response. Automated tests use `DeterministicFixtureRouteProvider`;
it must not be configured as a production source. Provider coordinates, route
sizes, durations, profiles, metadata, corridor endpoints, and every requested
via-point in route order are validated before caching or persistence.

Journey creation snapshots routed DRIVE distance, duration, provider/profile,
capture time, polyline, and corridor when the provider succeeds. If it is
unavailable, the domain record remains valid without fabricated route data.
Matching may use a straight-line/corridor fallback only when the active policy
explicitly enables it; the result is labelled in `limitations` and never
presented as routed-road precision.

Cache keys include provider, operation, inputs, profile, and the operator-set
namespace. Bump the namespace whenever provider/configuration/dataset semantics
change. Cache is never authoritative for capacity, Deal state, or reservation
expiry.

## PostGIS decision

PostGIS was not enabled in this change. The linked Railway production database
uses the standard PostgreSQL service image; Railway documents PostGIS as a
separate template/deployment choice. Enabling an extension blindly would make
the migration depend on infrastructure that is not present and has not been
rehearsed. See [Railway PostgreSQL](https://docs.railway.com/databases/postgresql).

The intermediate design keeps decimal WGS84 coordinates and provider-neutral
route snapshots outside business rules. Spatial projection is bounded and
explicitly approximate. A future migration can add `geography(Point, 4326)`,
route geometry, and GiST indexes, backfill from validated Location coordinates,
dual-read during rehearsal, then remove the fallback. Before marketplace scale,
that migration should also replace the bounded Python spatial scan with coarse
SQL/PostGIS narrowing and keyset pagination.

## Trusted airport coordinates

No legacy airport coordinates were invented or backfilled. FLIGHT compatibility
requires both endpoints to be trusted airport Locations with a non-empty dataset
version, and only covered FLIGHT legs require approved proof/trusted coordinates.

Operations must review a CSV with `iata,latitude,longitude`, then run:

```text
python manage.py import_trusted_airports reviewed-airports.csv --dataset-version <immutable-version>
```

The import is transactional, capped at 10,000 rows, rejects unknown IATA codes,
and creates immutable server-trusted airport Locations. Selecting and approving
the production dataset remains an external launch prerequisite.

## Compatibility and distance

A request may cover any feasible ordered sub-route, including FLIGHT-only,
DRIVE-only, or mixed legs. Repeated/multiple anchors are evaluated in a stable
order until a hard-compatible pair is found. Covered legs are explicit.

Hard gates include request/Journey status, account eligibility, current traveler
KYC, targeted-traveler rules, item safety, absence of an active Deal, connected
leg order, Journey-wide FLIGHT proof approval, covered-FLIGHT coordinate trust,
ready/deadline feasibility, DRIVE detour limits, and remaining capacity on every
covered leg.

For DRIVE endpoints near a corridor, routed deltas are preferred for pickup,
drop-off, total added distance, and duration. Prefix timing excludes travel
which occurs after the pickup/drop-off event. Detour distance remains a
feasibility and recommendation input; it is not added to matched distance.
Matched distance prices only the route while the parcel is carried:

- FLIGHT: great-circle distance over trusted coordinates.
- DRIVE: stored/provider routed distance between actual carried endpoints.
- Mixed: sum of the covered components.

When routed distance is unavailable and policy permits fallback, the component
uses an explicitly labelled great-circle estimate.

## Pricing and ranking

EUR cents are canonical and all money arithmetic is integer/Decimal based.

```text
volumetric kg = length_cm * width_cm * height_cm / 5000
chargeable kg = ceil(max(actual kg, volumetric kg) / 0.5) * 0.5
minimum = max(global floor, distance-band base + chargeable kg * weight rate)
recommended = round-up(minimum * 1.20 + detour + urgency, EUR 0.50)
```

Seeded version 2 settings contain the requested €4/€6/€9/€12/€16/€20/€24
distance bands, €7 floor, €2.50/kg rate, 0.5kg increment, 1.20 recommendation
multiplier, €0.50 rounding, and 25% commission. The migration refuses to
activate a conflicting pre-existing version 2.

Commission is added on top using ceiling integer-cent rounding; it never reduces
the traveler reward. Offer and Deal terms snapshot the settings version, policy,
pricing components, compatibility, ranking, commission, and reservation grace.
Match compatibility/ranking snapshots and Offer/Deal economic snapshots are
immutable.

Ranking is deterministic and explainable: route fit, detour, time fit,
verification, freshness, neutral placeholders for unavailable reputation data,
and the sender request boost hook. There is no boost purchase/activation API.

## Capacity and reservation lifecycle

Acceptance locks in a deterministic request → matches → offer → Journey → all
Journey legs order. Route-provider work is completed first, outside the atomic
section; the locked revalidation can only replay those frozen outcomes and
fails closed if the route inputs changed. Acceptance locks deterministic
current KYC and Journey-wide flight-proof witnesses, followed by both account
rows, so eligibility cannot be revoked between validation and Deal commit. It
then recomputes active allocations per covered leg and atomically creates the
Deal, terms, events, and all leg allocations. Failure on one leg rolls back
everything. PostgreSQL—not Redis—is the capacity authority.

Pending-payment allocations expire after the settings-snapshotted grace period
(default one hour). Release is idempotent, reopens the request, updates Match and
Deal state, and appends audit events. The combined Railway process starts the
database-backed releaser; a separate worker may instead run:

```text
python manage.py run_reservation_releaser --interval 60 --batch-size 100
```

`POST /api/deals/{id}/cancel` permits a Deal party to cancel only before
funding. Journey cancellation releases pending-payment reservations but rejects
funded/operational Deals because refund semantics belong to a later phase.

## Public and internal representations

### Why the split exists

Quantising a Location to 0.1 degrees is not sufficient on its own. Phase 2
returned the full internal compatibility explanation to ordinary users, and
several of its fields are deterministic functions of the counterparty's exact
coordinates. Against a corridor the counterparty already owns, the pickup
address was reconstructable to **one metre**:

| Field | Why it leaks |
|---|---|
| `pickup_route_position` / `delivery_route_position` | Full-precision progress along a known corridor; multiplied by corridor length it is the along-route offset in metres. |
| `pickup_detour_meters` / `delivery_detour_meters` | On the spatial-fallback path this is exactly twice the perpendicular offset from the corridor. Position plus offset gives two candidate points, and the coarse cell eliminates the mirror. |
| `distance_components[].distance_meters` with `partial_start`/`partial_end` | Routed distance measured *from* the exact private endpoint: a precise circle around a known node. |
| `pickup_at` / `delivery_at` | Interpolated from the route position. At second resolution on a multi-hour leg, one second is a couple of metres. |
| `checks[].details` | Repeats the positions and the raw detour metres. |
| `capacity_remaining_by_leg` | Not geometry, but discloses the traveler's total capacity and other senders' reservations. |
| `ranking.factors` | `route_fit` and `detour` are linear in added distance (about 30 m per point), `time_fit` is linear in delivery time; the payload also carries the ranking weights and boost parameters. |
| `pricing.matched_distance_meters`, `pricing.detour_adjustment_cents` | The first is measured from the private endpoint; the second resolves the corridor offset to about 40 m at the seeded 25 cents/km rate. |

The severe path was `GET /matches/compatible-requests`: one journey, up to
`result_limit` unrelated senders, repeatable at the discovery throttle.

### The two representations

`apps/matching/public_contract.py` is the single boundary. Every projection
takes a plain dictionary, so a snapshot persisted by an older build is filtered
by exactly the same rules as a freshly computed one, and a key that is missing
is treated as absent rather than safe.

| | Internal / audit | Public / pre-funding |
|---|---|---|
| Builder | `CompatibilityResult.as_dict()`, `PricingQuote.as_dict()`, `rank_compatible_candidate()`, `BusinessSettingsVersion.policy` | `public_compatibility_payload()`, `public_pricing_payload()`, `public_terms_snapshot()` |
| Stored on | `Match.compatibility_snapshot`, `Match.ranking_snapshot`, `Offer.terms_snapshot`, `DealTermsSnapshot.policy_snapshot` | not stored — projected at serialization time |
| Served by | `GET /matches/explain` (`IsAdminUser`), Django admin | every party-facing endpoint |

**Storage is unchanged.** Reproducibility, audit and dispute evidence still have
the full internal snapshot on the row. Only serialization was narrowed.

### Public compatibility payload

```json
{
  "matching_version": "v1-matching-1",
  "compatible": true,
  "rejection_codes": [],
  "start_leg_id": 41,
  "end_leg_id": 42,
  "covered_leg_ids": [41, 42],
  "covered_leg_positions": [0, 1],
  "covered_legs": [
    {
      "journey_leg_id": 41,
      "position": 0,
      "mode": "FLIGHT",
      "origin": { "public_label": "Paris, FR", "coarse_latitude": "48.9", "...": "..." },
      "destination": { "public_label": "Algiers, DZ", "...": "..." },
      "depart_at": "...",
      "arrive_at": "..."
    }
  ],
  "estimated_pickup_window": { "start": "...", "end": "..." },
  "estimated_delivery_window": { "start": "...", "end": "..." },
  "matched_distance_band": { "label": "100_300km", "min_meters": 100001, "max_meters": 300000 },
  "matched_distance_precision": "routed",
  "pickup_detour_band": "under_5km",
  "delivery_detour_band": "5_15km",
  "total_added_distance_band": "5_15km",
  "capacity_available_on_every_covered_leg": true,
  "limitations": [],
  "route_provider": "..."
}
```

Rules that produced it:

- **Detour** is bucketed: `under_5km`, `5_15km`, `over_15km`. The finest bucket
  is wider than the coarse cell is deep, so a band cannot narrow a candidate
  below city precision.
- **Carried distance** is bucketed on the seeded pricing distance-band
  thresholds (minimum width 100 km), so the label states nothing that
  `distance_band_base_cents` does not already state.
- **Timing** is the covered legs' own published schedule, never the interpolated
  instant. The counterparty learns "pickup happens during leg 0, which runs
  14:00–18:00", which describes the Journey rather than where on it the parcel
  joins. Precise pickup/delivery timing unlocks with the exact address after
  funding.
- **Distance method** collapses to `routed` / `estimated` / `mixed` /
  `unavailable`; the raw method name distinguished partial (private-endpoint)
  routing from whole-leg routing.
- **Capacity** is one boolean. Numbers stay internal.
- **Ranking** is omitted entirely in both directions.

### Public pricing payload and the recommendation rule

The public pricing payload keeps every field the spec requires a user to see —
weights, distance-band base, weight component, global floor, minimum reward,
commission, and the pre-computed economics triples — and drops
`matched_distance_meters`, `matched_distance_method`,
`detour_adjustment_cents` and `urgency_adjustment_cents`. Whether an adjustment
applied is reported as `detour_adjustment_applied` /
`urgency_adjustment_applied`.

`minimum_reward_eur_cents` is `max(global floor, distance-band base + weight
component)`. It contains no detour and no urgency term, so it is geometry-free
and is published in **both** directions.

`recommended_reward_eur_cents` does embed the detour adjustment. Even at its
EUR 0.50 rounding that leaves a bounded residual — roughly 2 km, perpendicular
to the corridor, with no along-route component at all. It is therefore returned
**only to the request owner**:

| Surface | Caller | Recommendation |
|---|---|---|
| `GET /matches/compatible-journeys` | request sender | yes — the detour is about the sender's own parcel |
| `POST /matches/quote` | request sender | yes |
| `GET /matches/compatible-requests` | journey traveler | **no** — bulk-harvest surface, and the traveler cannot propose a price anyway |
| Offer / Deal terms snapshots | either party | **no** — the recommendation is discovery guidance, not a term of the deal |

This is the accepted, documented residual. It is spec-mandated (§"Recommended
traveler reward" requires showing the recommendation) and it is confined to the
one direction where the viewer already knows the private point.

### Public terms snapshot

`Offer.terms_snapshot` and `DealTermsSnapshot.policy_snapshot` are stored whole
and serialized as:

```json
{
  "canonical_currency": "EUR",
  "commission_rate_bps": 2500,
  "pricing_version": "v1-matching-pricing-1",
  "business_settings_version": 2,
  "pricing": { "…public pricing payload, no recommendation…" },
  "compatibility": { "…public compatibility payload…" },
  "policy": { "reservation": { "payment_grace_seconds": 3600 } },
  "reservation": { "payment_grace_seconds": 3600 }
}
```

Ranking weights, `boost_points_per_weight`, `max_boost_points`, detour and
duration limits, and the candidate scan/result caps are removed: publishing them
tells a sender exactly how to game ranking. `payment_grace_seconds` stays
because it is a term of the user's own reservation.

### Related redactions

- `MatchSerializer` publishes `matched_distance_band` instead of
  `matched_distance_meters`, and no longer serializes `ranking_snapshot`.
- `JourneyLegSerializer` publishes `distance_band` instead of
  `distance_meters` and drops `route_duration_seconds` for non-owners. Both are
  measured between the leg's exact endpoints and would narrow one coarse
  endpoint to an arc around the other. The owner still sees both.
- A V1 EUR Offer no longer serializes `base_amount_dzd`, `base_fee_dzd`,
  `commission_dzd` or `total_dzd`. They are structural NOT NULL zeroes that read
  as a real DZD price. Legacy offers keep them; the database and admin keep them
  in every case.

### Testing the inference, not the key names

`apps/matching/tests/test_phase2b_privacy.py` places pickup **off** the corridor
with known exact coordinates and runs the real attack: it enumerates candidate
points across the published coarse cell and keeps those consistent with every
published value. The public payload leaves a diffuse, multi-kilometre candidate
set. The same solver is then pointed at the admin explain payload as a control
and collapses it to a few hundred metres — so a regression that re-publishes a
route position or an exact detour fails the suite instead of passing a vacuous
"key not present" assertion.

## Structured domain failures

Clients never parse English. Every failure carries a machine `code`; `detail` is
presentation text only, and some codes add structured fields.

| Code | Status | Extra fields |
|---|---|---|
| `not_authorized` | 403 | |
| `invalid_leg_range` | 400 | |
| `request_not_open` | 409 | `rejection_codes` when a gate produced it |
| `request_already_matched` | 409 | `rejection_codes` |
| `journey_not_active` | 409 | `rejection_codes` |
| `offer_not_pending` | 409 | |
| `match_not_pending` | 409 | |
| `match_leg_range_missing` | 409 | |
| `offer_economics_missing` | 409 | |
| `legacy_contract_not_supported` | 409 | |
| `product_request_retired` | 409 / 410 | |
| `request_weight_invalid` | 409 | |
| `invalid_reservation_grace` | 409 | |
| `route_preflight_missing` | 409 | |
| `route_inputs_changed` | 409 | |
| `incompatible_candidate` | 409 | `rejection_codes` |
| `reward_below_minimum` | 409 | `minimum_reward_eur_cents` |
| `capacity_exceeded` | 409 | `journey_leg_ids` |
| `constraint_conflict` | 409 | |
| `business_settings_unavailable` | 503 | |
| `invalid_phase2_policy` | 503 | |
| `pricing_error` | 409 | |
| `internal_error` | 500 | |

`rejection_codes` are compatibility gate names. Revoked traveler KYC arrives as
`traveler_kyc_current`; a missing or withdrawn flight proof as
`flight_proofs_approved`. Three gates additionally get their own top-level code
so the common cases need no array inspection: `journey_active` →
`journey_not_active`, `request_active` → `request_not_open`,
`request_has_no_active_deal` → `request_already_matched`.

An unrecognised exception is reported as `internal_error` / 500 with a fixed
message. It is never labelled `business_settings_unavailable`, and its text is
never echoed to the caller.

## Server-declared negotiation actions

`OfferSerializer` computes, for the authenticated caller:

- `awaiting_party` — `"sender"`, `"traveler"`, or `null` once terminal
- `awaiting_user_id` — the user the negotiation is waiting on
- `allowed_actions` — a subset of `accept`, `counter`, `decline`, `withdraw`

The proposer gets `["withdraw"]`; the other party gets
`["accept", "counter", "decline"]`. `accept` and `counter` are withheld on a
legacy DZD chain, `accept` is withheld once the delivery request stops being
`OPEN` (a competing Match won), and everything is withheld once the Offer or the
Match leaves `PENDING` or the parcel is a retired ProductRequest.

This is **UX guidance, not authorization**. Every mutation re-checks the same
rules under row locks and still fails transactionally on stale state — a client
that ignores an empty `allowed_actions` gets a 409, not a side effect.

## Discovery contract

A candidate row carries what the next call needs, so rendering a mixed journey
costs no extra request:

- `journey.start_leg_id` / `journey.end_leg_id` — pass straight to
  `POST /matches/propose`; no inference from `covered_leg_ids` and no
  `GET /journeys/{id}` per candidate.
- `journey.covered_legs` — per leg: id, position, mode, coarse origin and
  destination, and the published depart/arrive times.
- `delivery_request.sender_proposed_reward_eur_cents` — the sender's posted
  intent. It is **not** an agreed price and never feeds pricing, ranking or
  settlement; `Offer.traveler_reward_minor` is the only authoritative reward.
  The database column keeps its historical name for audit continuity.

The covered legs and their endpoint Locations are already prefetched by
discovery, so the richer payload costs **zero** additional queries at any
candidate volume (regression: `test_public_serialization_adds_no_query_per_candidate`).

## Negotiation terminal states

A declined and a withdrawn negotiation are one user-visible outcome, so both now
terminate the Match as `CANCELLED`. `EXPIRED` is reserved for system-driven
endings — superseded by a competing acceptance, or a lapsed reservation. Who
ended it remains recorded on the `MatchEvent` (`offer_declined` vs
`offer_withdrawn`) and on the Offer's own status, so no history is lost.

## APIs

All paths are under `/api` and require authentication unless noted by the
existing account contract.

| Method and path | Authorization | Purpose |
|---|---|---|
| `GET /routes/provider-status` | authenticated | Provider availability/capabilities; never exposes credentials. |
| `GET /matches/compatible-journeys?parcel_id=` | request sender | Ranked compatible Journeys with coarse counterpart locations. |
| `GET /matches/compatible-requests?journey_id=` | Journey traveler | Ranked compatible open requests, including targeted requests only for that traveler. |
| `POST /matches/quote` | request sender | Candidate compatibility plus minimum/recommended EUR quote. Body: `parcel_id`, `journey_id`. |
| `GET /matches/explain?parcel_id=&journey_id=` | admin | Internal checks, rejection codes, covered legs, capacity, pricing, and ranking; exact/private provider data is still excluded. |
| `POST /matches/propose` | request sender | Sender-first Offer. Requires parcel/Journey/start/end leg IDs and reward cents; rejects below minimum. |
| `POST /offers/{id}/counter` | non-proposing party | Immutable counteroffer subject to the same server floor. |
| `POST /offers/{id}/accept` | non-proposing party | Capacity-safe acceptance and pending-payment Deal creation. |
| `POST /deals/{id}/cancel` | Deal party | Idempotent pre-funding cancellation/release. |
| `POST /journeys/{id}/cancel` | Journey owner | Cancels only when no funded/operational Deal exists. |

Discovery is bounded by versioned `candidate_scan_limit` and `result_limit` and
rate-limited by `DRF_MATCHING_DISCOVERY_THROTTLE_RATE`. Exact locations,
addresses, route geometry, provider place IDs/metadata, proofs, and recipient
data are never included in candidate or explanation payloads. Existing funded
Deal privacy rules remain the only exact-location reveal boundary.

## Performance and indexes

Phase 2 adds/uses indexes for active Journey publication, Journey leg order and
time, request ready windows/route/boost expiry, active Deal lookup, Journey Deal
status, matching version/status, and allocation status/expiry/leg state. ORM
queries use `select_related`, annotated `Exists`/`Sum`, and prefetched legs to
avoid per-candidate database queries.

The current non-PostGIS feed deliberately scans at most 200 SQL-prefiltered
candidates and returns at most 50. This protects the service but is best-effort:
at high density, a spatially valid candidate beyond the scan cap can be omitted.
That limitation must remain visible in operational planning and is the principal
reason for the PostGIS/keyset phase before broad marketplace scale.

The repeatable regression fixture showed exactly three database queries in both
discovery directions at 3 and 24 candidates. Exact-node discovery made zero
directions calls. Twenty-four identical off-route candidates shared cache
entries and consumed exactly nine provider calls within a nine-call budget.

On the local PostgreSQL 16 verification database, 60 warmed service-level
samples over 24 candidates measured:

| Discovery direction | p50 | p95 |
|---|---:|---:|
| request → Journeys | 23.81 ms | 29.39 ms |
| Journey → requests | 20.41 ms | 24.35 ms |

These are developer-machine regression evidence, not production SLOs.
`EXPLAIN` confirmed the active-Journey predicate uses
`journey_status_published_idx`, ordered leg lookup uses
`journey_leg_unique_position`, and active allocation aggregation uses
`deals_leg_status_idx`. Refresh the counts, timings, and plans whenever scan
limits, indexes, data distribution, or provider behavior changes.

## Rollback and recovery

- Schema changes are additive. Django remains migration authority.
- Reversing settings migration 0004 retires version 2 and reactivates version 1;
  it never deletes auditable economic history. Forward reapplication validates
  immutable version 2 values before activation.
- Reservation release is repeatable and database-backed. Do not manually delete
  Deal/allocation/event rows.
- Route-provider rollout can be disabled by clearing `ROUTE_PROVIDER_CLASS`;
  bump the cache namespace on any semantic change.
- Do not reverse migrations that are referenced by live Offers/Deals without a
  rehearsed maintenance window and backup.

## Explicitly deferred

Stripe/Chargily checkout and FX, guest payer, deposits, provider webhooks and
refunds, traveler payouts, pickup/delivery code lifecycle, delayed code release,
48-hour protection, disputes, ratings, paid boost purchasing, final admin UI,
and Flutter redesign are not implemented in Phase 2.
