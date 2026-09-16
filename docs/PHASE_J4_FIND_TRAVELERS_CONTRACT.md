# Phase J4 — Find Travelers contract, match explanation and discovery architecture

Freezes what a Sender is told about a Traveler before they propose, and what
Gemini J5 will render. No visual redesign ships here.

Starting main: `d27dbe051d65ac8c75ed3bf52c4b88913775c2e9`.
Branch: `claude/j4-find-travelers-contract`.

ShipTrip stayed in TEST throughout: `PAYMENTS_ENVIRONMENT=test`, Stripe TEST,
Chargily TEST, `PAYOUT_DZD_EXECUTION_ENABLED=false`. No money moved, no provider
object was created, and no LIVE operation was performed.

---

## 1. What was actually wrong

The owner's complaint was that the cards are too big and say too much. The audit
found a sharper version of the same thing: **the old endpoint answers a
different question from the one a browsing Sender is asking.**

`GET /api/matches/compatible-journeys` returns, per candidate:

* the Sender's own delivery request, in full — repeated on every row;
* the journey block, with its covered legs;
* the compatibility block, with **the same covered legs again**;
* a pricing diagnostic with distance bands, precision tags, version strings and
  adjustment flags;
* **no Traveler at all** — only `traveler_id`.

So the card the app could build from it showed a route line of stops, a leg
count, a detour band, a distance band and two prices, and named nobody. The
person who would be carrying the parcel was the one fact missing.

Two of those rows were worse than merely redundant.

**"Detour: Barely a detour"** and **"Matched distance: 300–750 km"** are
constants on a canonical candidate. Canonical V1 compatibility is locality
*identity*: `_canonical_candidate_anchors` matches a request endpoint to a route
node by immutable matching-locality ID and returns a detour of exactly zero, and
`evaluate_compatibility` then asserts `pickup_detour = delivery_detour =
added_distance = 0` for every canonical flow. Every candidate therefore reports
`under_5km` on all three bands. The app was rendering a constant as if it were a
measurement, and inviting the Sender to read proximity into a model that has no
concept of it.

J4 removes the whole vocabulary and replaces it with the question the owner
actually asked: **is this Traveler going my way?**

---

## 2. Authority — what J4 does and does not decide

| Concern | Owner | J4's role |
|---|---|---|
| Hard compatibility | `apps.matching.compatibility.evaluate_compatibility` | none — consumes the verdict |
| Ranking / result order | `apps.matching.ranking.rank_compatible_candidate`, applied by `apps.matching.discovery.compatible_journeys_for_request` | none — consumes the order |
| Pricing | `apps.matching.pricing` | none — narrows the projection |
| Pre-funding privacy | `apps.matching.public_contract` | re-projects through it, never around it |
| Route-fit label | **J4** (`apps.matching.find_travelers`) | new |
| Timing-fit label | **J4** | new |
| Match explanation | **J4** | new |
| Paging, sorting, envelope states | **J4** | new |

`apps/matching/find_travelers.py` is a projection module. It computes nothing
the matching engine did not already decide, and it never sees a score.

**Hard compatibility still happens before ranking, and ranking still cannot make
an incompatible Traveler appear.** `rank_compatible_candidate` raises if handed
a candidate that failed compatibility; `compatible_journeys_for_request` filters
to `compatibility.compatible` before it sorts. J4 changed neither.

---

## 3. Route fit

### Definition

Route fit describes **how much of the Traveler's own published trip is the
Sender's route** — not how physically close anything is.

Canonical matching resolves both request endpoints to *route nodes*: indices
into `[legs[0].origin_place, *[leg.destination_place for leg in legs]]`. The
covered-leg span between those two nodes is therefore an exact record of where
on the Traveler's trip the parcel joins and leaves. That span is the only input.

```
covered = compatibility.covered_legs      # positions, ordered
legs    = the journey's full leg list

starts_at_origin      = covered[0].position  == 0
ends_at_destination   = covered[-1].position == len(legs) - 1
```

| Classification | Rule | What it means |
|---|---|---|
| `excellent` | `starts_at_origin and ends_at_destination` | The parcel rides the whole published Journey. The Traveler's trip **is** the Sender's route. |
| `good` | exactly one of the two | The parcel shares one end of the trip — picked up where the Traveler starts, or dropped where they finish. |
| `compatible` | neither | The Traveler passes through. Every gate passed; neither endpoint is their own origin or destination. |

Implemented in `classify_route_fit`, which is a pure function of
`(covered_leg_positions, journey_leg_count)` and is unit-tested as such.

### Why this gradient is honest

All three are genuinely compatible — ShipTrip returns nothing that is not. What
differs is how much of the trip is *about* this parcel. On an `excellent`
candidate no part of the Traveler's itinerary can change without the Sender
already caring about it; on a `compatible` one the parcel is riding a middle
segment of somebody else's longer plan. That is a real difference in exposure,
and it is the one the data actually supports.

### What was rejected

The ranking engine has a factor literally named `route_fit`. It is **not** used,
for two reasons. First, it is `1000 - 1000 × added_distance / limit`, and
`added_distance` is a hard zero on every canonical candidate, so it is the
constant 1000 and discriminates nothing. Second, `public_contract` documents
ranking factors as reversible into corridor geometry and the ranking weights, so
publishing one would be a privacy regression as well as a useless one.

### Frozen vocabulary

`excellent` · `good` · `compatible`. Display strings in §12.

---

## 4. Route fit is not physical closeness — enforced, not promised

Section 3 of the phase brief forbids kilometre, radius, pin-proximity, detour
and corridor semantics. The contract carries none of them, and a test asserts
the *serialised payload* contains no substring matching `detour`, `radius`,
`distance`, `_km`, `proximity`, `nearby`, `latitude`, `longitude`, `coordinate`,
`polyline` or `corridor`. A future field that reintroduces any of those fails
the suite rather than shipping.

The copy follows the same rule: "Excellent route match", never "Very close".

---

## 5. Timing fit

Computed from the covered legs' **published** `arrive_at` against the Sender's
own `deadline_at`:

| Classification | Rule |
|---|---|
| `comfortable` | `deadline_at - arrives_at >= 24h` |
| `fits` | otherwise |
| `null` | no published arrival or no deadline |

Deliberately **not** computed from `CompatibilityResult.delivery_at`: that
instant is interpolated from a route position and `public_contract` keeps it
internal for exactly that reason. On a canonical candidate the two are the same
instant anyway, because every anchor lands on a whole node.

**This discloses nothing new.** Leg schedules are already published on every
covered leg and the deadline is the Sender's own field; the classification only
saves them the subtraction. A compatible candidate has already passed
`delivery_before_deadline`, so where a legacy mid-leg anchor makes the published
arrival later than the interpolated one, the result floors at `fits` rather than
contradicting the gate that let it through.

The card shows a date (`Flight · 18 Sep`). The timing-fit label belongs in the
match explanation, not as a second badge on a compact row.

---

## 6. Route projection

Each candidate exposes an ordered public route covering **only the carrying
sub-route**:

```json
"route": {
  "stops": [
    {"place_id": 1, "label": "Paris",   "country_code": "FR", "airport_iata": "CDG",
     "arrive_at": null,          "depart_at": "2026-09-18T01:15:02+00:00"},
    {"place_id": 3, "label": "Algiers", "country_code": "DZ", "airport_iata": "ALG",
     "arrive_at": "…T04:15:02+00:00", "depart_at": "…T05:15:02+00:00"},
    {"place_id": 4, "label": "Jijel",   "country_code": "DZ", "airport_iata": null,
     "arrive_at": "…T10:15:02+00:00", "depart_at": null}
  ],
  "segments": [
    {"journey_leg_id": 1, "mode": "FLIGHT", "depart_at": "…", "arrive_at": "…"},
    {"journey_leg_id": 2, "mode": "DRIVE",  "depart_at": "…", "arrive_at": "…"}
  ],
  "continues_before": false,
  "continues_after": false
}
```

Properties:

* **Ordered.** N segments, N+1 stops — exactly what a route line draws.
* **Canonical labels, city first.** The spec's locked route UX is *airports are
  a facet of a stop*: `Algiers · ALG`, never `Houari Boumediene`. A stop's
  `label` is therefore the **matching locality**, resolved through the mapping
  the discovery scan already prefetched, and the airport rides alongside as
  `airport_iata`. Both sides of a transfer node resolve to the same locality by
  the continuity rule, so this only ever chooses between two spellings of one
  place; the arriving airport wins.
* **Mode per segment**, `FLIGHT` / `DRIVE`.
* **Published schedule only.** First stop has no arrival, last has no departure.
* **No coordinates, no private point, no hidden metadata.** A stop is a
  catalogue id, a label, a country, an optional IATA code and two instants.

### Relevant route only

Only the legs that carry this parcel are projected. The rest of the itinerary is
not secret — `GET /api/journeys/{id}` serves the whole published Journey to any
authenticated user for a discoverable journey — but it is not the Sender's
business on a browse row, and dumping it is what makes a card too tall to scan.
`continues_before` / `continues_after` state *that* the trip is longer without
stating *where*, so J5 can draw an ellipsis.

### Multi-leg journeys

Tested end to end over the canonical world:

| Shape | Result |
|---|---|
| DRIVE only (Algiers → Jijel) | 1 segment, `transfers: 0`, `primary_mode: DRIVE`, `direct_leg` reason |
| FLIGHT → DRIVE (Paris → Algiers → Jijel) | 2 segments, `transfers: 1`, `primary_mode: FLIGHT` |
| DRIVE → FLIGHT → DRIVE (Jijel → Algiers → Paris → Lyon), parcel on the middle leg | 1 segment, both `continues_*` true, `route_fit: compatible` |

`primary_mode` is `FLIGHT` whenever any covered leg flies — not the longest leg
and not the first. If the parcel gets on a plane, the plane is the fact that
decides the proof, the customs and the schedule.

**Transport policy is untouched.** Algeria ↔ non-Algeria still crosses by
FLIGHT, Algeria domestic DRIVE and continental-Europe cross-border DRIVE remain
allowed, and there is still no ferry. J4 renders those routes; it does not
validate them.

---

## 7. Candidate identity

```json
"traveler": {
  "id": 2,
  "display_name": "Yacine",
  "avatar_url": null,
  "identity_verified": true,
  "rating": {"state": "new", "average": null, "count": 0},
  "completed_deliveries": 0
}
```

| Field | Source | Note |
|---|---|---|
| `display_name` | first token of `User.full_name` | A **narrowing**: `JourneySerializer.traveler_name` already publishes the whole name to any authenticated viewer of a discoverable journey. Empty when no name is on file — an email local part is never published as a name. |
| `avatar_url` | — | **Always null in V1.** No profile photo exists anywhere in the data model; the field is present so J5 can design both states and a later photo is not a contract change. The client already renders initials. |
| `identity_verified` | `traveler_kyc_current` gate | True of **every** returned candidate, because KYC is a hard gate. Published because it is the authoritative answer, not because it distinguishes rows — see §9 for why J5 should not badge it. |
| `rating` | `apps.ratings.Rating` | §7.1 |
| `completed_deliveries` | `Deal.status == COMPLETED` | §7.2 |

Not exposed, anywhere: surname, email, phone, wilaya, identity documents, KYC
state or evidence, payout setup, home or exact location, biography, or any
coordinate.

### 7.1 Rating

Aggregated over `Rating` rows where `ratee = traveler` **and
`rater_role = SENDER`** — the ratings that describe this person *as a Traveler*,
not ones they received as a Sender.

The blind window is respected in SQL. `ratings.services.is_revealed` is "the
window frozen on the row has passed, **or** both sides have spoken"; both halves
are expressible as a filter, so an unrevealed rating is excluded here exactly as
it is excluded from the rating API.

| Case | Contract |
|---|---|
| No revealed rating | `{"state": "new", "average": null, "count": 0}` |
| One | `{"state": "rated", "average": 3.0, "count": 1}` |
| Several | `{"state": "rated", "average": 4.5, "count": 2}` — one decimal |
| Written but still blind | counted as **new** until it reveals |

`5.0` is never fabricated for a new Traveler. The average is `null` and the UI
shows "New".

### 7.2 Completed deliveries — included

Counted from `Deal.status == COMPLETED` for that Traveler. Explicitly **not**
journey count, offer count or matched-request count; a test creates four
published journeys and asserts the count stays zero, and another flips a
completed Deal to `in_transit` and asserts it drops back.

Included rather than deferred because it is one grouped query for the whole
page (§10) and it is the single cheapest trust signal a marketplace has.

---

## 8. Boost

Three effects, documented separately because they are genuinely different.

| Effect | J4 answer |
|---|---|
| **Compatibility** | **None, ever.** `rank_compatible_candidate` raises if handed an incompatible candidate, and `boost.compatibility_override` is hard-coded `False`. A test gives an unroutable request a €1,000 Boost and asserts the result set stays empty — not merely shorter. |
| **Ranking** | On **Find Travelers, none** — and this is a finding, not a decision. `rank_compatible_candidate` reads the Boost from the *delivery request*, and on this screen every candidate shares one request, so the bonus is a constant added to every row. A test records the order, adds a Boost, and asserts the order is byte-identical. Boost's ranking effect is real but lives on the **traveller-facing** `compatible-requests` scan, where the requests differ. |
| **Display** | **Not shown on a Traveler card.** A "Boosted" badge on a Traveler would claim an effect that does not exist on this screen. The Sender's own Boost is in `request.boost_eur_cents` and `request.total_offered_reward_eur_cents`, for the propose sheet. |

No new ranking effect was invented.

---

## 9. What the Sender sees, and what they do not

### Request reward — envelope only

`request.chosen_reward_eur_cents`, `boost_eur_cents` and
`total_offered_reward_eur_cents` are sent **once per page**, not per row. The
Sender already knows what they offered; repeating it on every card is exactly
the density the owner objected to. The numbers exist so the propose sheet can
open without another request.

### Match explanation

```json
"match_reasons": [
  {"code": "picks_up_in",  "params": {"place": "Paris"}},
  {"code": "arrives_in",   "params": {"place": "Jijel"}},
  {"code": "transfers",    "params": {"count": 1}},
  {"code": "whole_trip_matches", "params": {}},
  {"code": "arrives_before_deadline",
   "params": {"arrives_at": "…", "deadline_at": "…"}},
  {"code": "has_room_for", "params": {"weight_kg": "2.00"}},
  {"code": "identity_verified", "params": {}},
  {"code": "flight_proof_approved", "params": {}}
]
```

Codes and parameters, never English from the server — the client localises. Every
entry is backed by a gate that passed or a published schedule value; there is no
formula and no score. `direct_leg` replaces `transfers` at zero transfers,
`whole_trip_matches` appears only on `excellent`, and `flight_proof_approved`
only when a covered leg flies.

`identity_verified` lives here, once, rather than as a per-card badge: it is true
of every row in the list, and a universal truth rendered as a badge reads as a
distinction.

### Authorized actions

```json
"actions": [
  {"code": "view_journey",  "available": true, "reason": null},
  {"code": "propose_offer", "available": true, "reason": "…"}
]
```

Server-authored. Flutter never infers availability from local status; a
`propose_offer` with no resolved leg range arrives `available: false` with
`reason: "leg_range_unresolved"`, and the decoder treats an action it has never
heard of as unavailable rather than assuming.

`view_journey` maps to the existing `GET /api/journeys/{id}`, which already
serves any authenticated user a discoverable journey with coarse locations and
redacted proofs.

### Caveats

`caveats` carries the matching verdict's own `limitations` codes. Empty on every
canonical candidate; present only where the verdict itself was qualified.

---

## 10. The endpoint

`GET /api/matches/find-travelers?parcel_id=&limit=&offset=&sort=`
Sender-only (`403` for anyone else), throttle scope `matching_discovery`.

`compatible-journeys` is **unchanged and still live**. The shipped J3 app keeps
using it; J5 switches to the new endpoint; retiring the old one is a later
phase's call. That is why J4 adds an endpoint rather than reshaping one.

### Envelope

```json
{
  "state": "results",
  "sort": "best_match",
  "page": {"limit": 10, "offset": 0, "total": 23,
           "has_more": true, "next_offset": 10},
  "request": { … once … },
  "results": [ … ]
}
```

### States — four presentations, not two

| `state` | HTTP | Meaning |
|---|---|---|
| `results` | 200 | at least one compatible Traveler |
| `no_candidates` | 200 | the request is live and matchable; nobody is going that way yet |
| `request_ineligible` | 200 | the request itself cannot be matched; carries `reason` and `request_status` |
| — | 4xx / 5xx | auth, ownership, settings outage, transport failure |

`request_ineligible` reasons: `awaiting_deposit`, `already_matched`, `closed`,
`in_progress`.

**This distinction did not exist before J4.** A cancelled request and a route
nobody travels both produced an empty list, because every candidate simply
failed the `request_active` gate one by one. The Sender was told "no travellers
yet" when the truth was "you have not paid the posting deposit". An ineligible
request also now short-circuits the scan entirely rather than evaluating every
candidate in order to reject all of them.

### Pagination

Offset paging over the authoritative ranked set.

* Default page **10**, capped at the active policy's `result_limit` (seeded
  **50**), which is also the size of the whole result set — paging slices the
  authoritative answer, it does not extend it.
* `candidate_scan_limit` (seeded **200**) still bounds the work.
* Ordering is total and deterministic: `(-score, added_distance, pickup_at,
  journey_id)` for best match, `(departs_at, journey_id)` for soonest. The
  `journey_id` tiebreak is what makes a page boundary safe.
* Tested: three 6-row pages over 15 candidates return 15 distinct rows, no
  duplicate and no gap; an offset past the end is an empty page, not an error;
  repeated identical reads return identical order.
* `next_offset` comes from the server. The client never computes one — a client
  that computes an offset can skip a row.

Before J4 the response was `{count, results}` with no page parameters and a
50-row ceiling in a single body.

### Sorting

| Value | Order |
|---|---|
| `best_match` (default) | ShipTrip's authoritative ranking, untouched |
| `soonest_departure` | earliest covered departure, `journey_id` tiebreak |

Both are applied **server-side**. Flutter never recreates the ranking. An
unrecognised `sort` is a `400`, not a silent reorder.

`soonest_departure` is shipped and tested because "I want it gone soon" is a
different question from "who fits best", and it is five lines of server-side
sort rather than client logic. Whether J5 surfaces a visible control is a J5
product call; the parameter exists either way.

### Filtering — deferred, with reasons

| Candidate filter | Decision |
|---|---|
| Travel date | **Deferred.** Already implied by the hard gates: `pickup_within_ready_window` and `delivery_before_deadline` mean every returned candidate is inside the Sender's own dates. A date filter could only narrow toward empty. |
| FLIGHT / DRIVE | **Deferred.** Mode is decided by geography — Algeria ↔ Europe must fly. A mode filter would be a no-op or an empty set on nearly every request. |
| Rating / deliveries | **Deferred.** With most V1 Travelers unrated, a rating filter mostly hides new Travelers from a marketplace that needs them. |
| Radius / distance | **Never.** No such semantics exist (§4). |

V1 ships with no filters. The default ranked list is the answer.

---

## 11. Staleness, and why a card is not a reservation

Discovery results are a snapshot. The world moves between the read and the tap,
and the **write path** is what notices — not the card.

`create_sender_offer` takes the request and journey rows under
`SELECT … FOR UPDATE`, re-checks `status == OPEN`, `journey.status in (ACTIVE,
IN_PROGRESS)`, ownership and the target-traveler restriction, locks the legs and
re-runs the full compatibility evaluation against the echoed
`start_leg_id`/`end_leg_id`. It fails closed with `journey_not_active`,
`request_not_open`, `capacity_exceeded`, `invalid_leg_range` or
`incompatible_candidate`.

Tested in J4: a candidate read, then the journey cancelled, then a propose →
`409 journey_not_active`. And a candidate read, then the request cancelled, then
a quote → `409 incompatible_candidate`.

Edge cases audited: a single relevant carrying leg; a multi-leg route; request
dates at a journey boundary; a journey whose early leg has elapsed but whose
later leg is still sellable (`trips.lifecycle.discoverable` keeps it, and that is
deliberate — a later leg remains inventory); a journey cancelled or expired after
results loaded (excluded on the next read, refused on write); capacity changed
between read and write (`capacity_exceeded`); a request that is no longer OPEN
(`request_ineligible`, and refused on write).

**The propose flow contract** is unchanged and now fully served by one row:
Traveler summary, ordered route, the frozen `proposal` leg range, the floor and
the recommendation with both economics blocks, and the Sender's own
chosen/Boost/total amounts from the envelope. J4 did not redesign the sheet.

---

## 12. Localization contract

Frozen semantics, EN/FR/AR all shipped (`l10n_untranslated.json` is empty):

| Key | EN |
|---|---|
| `findTravelersRouteFitExcellent` | Excellent route match |
| `findTravelersRouteFitGood` | Good route match |
| `findTravelersRouteFitCompatible` | Compatible route |
| `findTravelersTimingComfortable` | Arrives with time to spare |
| `findTravelersTimingFits` | Fits your delivery window |
| `findTravelersNewTraveller` | New |
| `findTravelersViewTrip` | View trip |
| `findTravelersWhyThisFits` | Why this trip fits |
| `findTravelersEmptyTitle` | No travellers going your way yet |
| `findTravelersEmptyBody` | Your request stays active. We'll tell you as soon as somebody posts a trip along your route. |
| `findTravelersIneligible*` | one per `reason` |
| `findTravelersStop` | `{city} · {iata}` |
| `findTravelersDirectLeg` / `findTravelersTransfers` | Carried in one leg / {count} transfers |
| `findTravelersPicksUpIn` / `findTravelersArrivesIn` | Picks up in {place} / Arrives in {place} |
| `findTravelersArrivesBeforeDeadline` | Arrives {arrival}, before your {deadline} deadline |
| `findTravelersHasRoomFor` | Has room for {weight} kg |
| `findTravelersIdentityVerified` / `findTravelersFlightProofApproved` | Identity verified / Flight ticket verified |
| `findTravelersDeliveries` | {count} deliveries (0/1/other) |
| `findTravelersSortBestMatch` / `findTravelersSortSoonest` | Best match / Soonest trip |
| `findTravelersTripContinues` | Trip continues |
| `findTravelersShowMore` | Show more travellers |

The empty-state copy says three things deliberately: nobody matches *yet*, the
request stays *active*, and ShipTrip will *tell them*. It never reads as a
failure.

---

## 13. Performance and size

Measured on PostgreSQL with `CaptureQueriesContext`, canonical fixtures.

| Candidates | Queries | Default page (10 rows) | Whole set, new | Whole set, `compatible-journeys` |
|---|---|---|---|---|
| 1 | **7** | 2.8 KB | 2.8 KB | 5.7 KB |
| 10 | **7** | 23.5 KB | 23.5 KB | 57.1 KB |
| 40 | **7** | 23.5 KB | 92.8 KB | 228.6 KB |

Flat at every volume, and the split is pinned by test: J1.2's five-query scan
plus **exactly two** grouped trust aggregates (revealed ratings, completed
deliveries), both keyed by the already-filtered Traveler IDs. No per-candidate
read exists; a third aggregate would fail the suite.

Two things shrink the wire:

* the request block and the weight figures are sent once, not per row;
* the pricing diagnostic is narrowed to the four numbers the propose sheet
  renders — bands, precision tags, version strings and adjustment flags are gone.

At 40 candidates the old endpoint ships **229 KB in one body**; the new default
page ships **24 KB**. About a tenth, and bounded rather than growing.

Route stops cost nothing extra: the locality behind an airport is already in
memory on the mapping `_matching_journey_queryset` prefetches, so resolving
`Algiers · ALG` needs no query. Projection reads the leg **models** the verdict
was computed over rather than their summary dicts, for exactly that reason.

---

## 14. Privacy allowlist

The candidate payload's shape **is** the allowlist — a field not built in
`candidate_payload` cannot be published.

**Allowed**

* `journey_id`
* traveler: `id`, first name, `avatar_url` (null), `identity_verified`, rating
  state/average/count, completed-delivery count
* route: ordered stops (catalogue id, locality label, country, optional IATA,
  published arrive/depart) and segments (leg id, mode, published schedule)
* `route_fit`, `timing_fit`, `departs_at`, `arrives_at`, `transfers`,
  `primary_mode`
* `match_reasons` codes and parameters, `caveats` codes
* `economics`: currency, minimum, recommendation, both economics blocks
* `proposal` leg range, `actions`
* envelope: the Sender's own request weights, windows, deadline and amounts

**Refused** — asserted against real values, not key names

exact pickup/dropoff, private coordinates, preferred meeting points, street or
address strings, email, phone, surname, KYC evidence or state, identity
documents, payout information, delivery or pickup codes, chat or deal data,
provider/payment references, ranking scores or factors, gate `checks` details,
`rejection_codes`, per-leg remaining capacity, and every detour/distance band.

Authorization: sender-only, `403` for a stranger **and** for the Traveler who
appears on the list; `401/403` anonymous.

---

## 15. J5 target card hierarchy

Reviewed in a browser against the real design system at 390 × 844 (both cards
built from the same tokens, `AppCard`, `AppAvatar`, `StatusPill` and `ModeChip`).

```
┌──────────────────────────────────────────────┐
│ (Y)  Yacine                          ★ 4.8   │   who
│                                              │
│ Paris · CDG  →  Algiers · ALG  →  Jijel      │   route
│                                              │
│ ✈ Flight · 18 Sep      ⊘ Excellent route match│  meta + fit
│                                              │
│ 12 deliveries                    View trip   │   history + action
└──────────────────────────────────────────────┘
```

The owner's sketch was right; two changes came out of the audit.

**The route goes horizontal.** The existing `RouteLine` is a vertical rail, and
it is right where the line *is* the screen — journey detail, funded route. On a
browse card three stacked nodes with timestamps cost about 120 dp to say what a
wrapping row says in about 40. J5 needs a compact inline route variant; the rail
stays where it belongs.

**Rating and identity swap weight.** `identity_verified` is true of every row, so
it is not a badge — it belongs in "Why this trip fits". The rating, which does
vary, takes the top-right position, and an unrated Traveler shows a quiet **New**
pill rather than a number.

Measured result at 390 × 844, default text scale:

| | Card height | Fully visible in one viewport |
|---|---|---|
| Today (J3) | ≈ 540 dp | **1**, plus a sliver of the second |
| Proposed | ≈ 155 dp | **4** |

The §31 target was three. No decorative map: the ordered leg line is the whole
graphic, because a map would imply geographic precision this model does not have.

Tap opens the trip. "Why this trip fits" belongs there, with the match reasons
and the timing-fit line, not on the row.

---

## 16. Exactly what J5 owns

J4 shipped the contract, the decoder, the repository call and the frozen
strings. `discovery_screen.dart` is **untouched** and still reads the old
endpoint, so the shipped app is unaffected.

Gemini J5 owns:

* the compact card visuals, spacing, typography and badges;
* the inline route component and its RTL/long-name behaviour;
* the four envelope states as four presentations;
* pagination UI against `page.next_offset`;
* the "Why this trip fits" surface after tap;
* the propose-sheet visual layout over the existing contract;
* rebuilding `discovery_screen.dart` against `findTravelers(...)` and
  `FindTravelersPage`.

---

## 17. Verification

**Backend** — 61 new tests in
`apps/matching/tests/test_phase_j4_find_travelers.py`, covering compatibility
authority and the Boost gate, route projection and multi-leg shapes, all three
route-fit classifications plus the pure function, timing fit, identity and every
rating edge case, lifecycle and staleness, paging and sorting, the match
explanation, authorization and the privacy allowlist, and the query/size bounds.
All pass.

**Regression** — `apps/matching`, `apps/deals`, `apps/parcels`, `apps/ratings`
and `apps/trips`: **526 passed, 34 skipped**. Ruff clean.
`makemigrations --check --dry-run`: **No changes detected** — no schema change,
no migration.

**Mobile** — 22 new tests in `test/phase_j4_test.dart` pinning the decoder
against a byte-for-byte copy of the server payload, the J1.2 double-pinning
pattern. Full suite **594 passed**. `flutter analyze`: no issues.
`flutter gen-l10n` regenerated; `l10n_untranslated.json` empty.

**Browser** — the card comparison in §15, rendered with the real design system.

---

## 18. Findings

**BLOCKER** — none.

**MAJOR** — none outstanding. Two were found and closed here: discovery
published detour and distance bands that are constants on every canonical
candidate, and an ineligible request was indistinguishable from an empty result
set.

**MINOR**

* `compatible-journeys` still serves the shipped app and still carries the
  constant bands and the duplicated request block. Retiring it is a later
  phase's call once J5 has switched.
* `avatar_url` is permanently null in V1. The field is contract-forward, not a
  feature.
* Boost has no ranking effect on Find Travelers (§8). That is current behaviour
  faithfully reported, not a defect J4 introduced, and it may be worth a product
  decision later.
* `apps/matching/tests/test_phase2_performance.py` still exercises the legacy
  `schema_version=2` request shape. The J4 cost tests cover the canonical shape;
  consolidating the two is out of this phase's scope.
