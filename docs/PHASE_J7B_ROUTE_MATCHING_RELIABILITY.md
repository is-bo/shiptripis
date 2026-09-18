# Phase J7B — Published request route and matching reliability

Status: implemented, TEST only. Stripe TEST, Chargily TEST,
`PAYOUT_DZD_EXECUTION_ENABLED` false, no LIVE provider activation and no
real-money operation.

Starting point: `9b2cde1` (J7A PASS). Branch
`claude/j7b-route-matching-reliability`. Backend **and** mobile change; no
schema change, no migration, no financial code touched.

The owner reported two core-flow defects on a real device:

1. After publishing a request and opening it, the route area was empty.
2. A Sender request and a Traveler Journey on the same route with compatible
   timing did not meet in Find Travelers.

They turned out **not** to share a root cause. The empty route is a mobile
defect; the missing match is a Journey write-contract defect on the server.
Both are fixed at the layer where they start.

---

## 1. Reproduction

Deterministic TEST data on real PostgreSQL (the embedded `test_pg` cluster),
driven through the **same endpoints the phone calls** — nothing written straight
into a status column:

| Actor | Step | Endpoint |
|---|---|---|
| Traveler B (KYC approved) | create Journey Algiers → Paris, one FLIGHT leg ALG → CDG, flight `AH1000`, capacity 10 kg | `POST /api/journeys` |
| reviewer | approve the flight proof | (proof row, as the admin queue does) |
| Traveler B | publish | `POST /api/journeys/<id>/publish` → `active` |
| Sender A | create request Algiers → Paris, 2.5 kg, ready window around the departure, deadline two days later, no meeting point | `POST /api/parcels/delivery/v1` → `awaiting_deposit` |
| Stripe TEST webhook path | settle the posting deposit | `reconcile_attempt(outcome="succeeded")` → request `open` |
| Sender A | open the request, then Find Travelers | `GET /api/parcels/<id>`, `GET /api/matches/find-travelers` |

Geography: localities Algiers (`Alger Centre` in the real ONS catalogue),
Paris and Jijel; airports ALG and CDG with their active primary `SERVED`
mappings to Algiers and Paris — the same policy the reviewed 2026 mapping file
seeds (`tools/geography/airport_locality_mappings_2026.json`).

Fixture IDs are per-test-database. The committed reproduction is
`OwnerScenarioTests` in
`backend/monolith/apps/matching/tests/test_phase_j7b_route_matching.py`.

### Where the candidate disappears

Each variant was traced through request detail → Journey detail → lifecycle →
`evaluate_compatibility` → `compatible_journeys_for_request` →
`compatible_requests_for_journey` → `GET /api/matches/find-travelers`.

| Variant | Journey lifecycle | Evaluator | Find Travelers |
|---|---|---|---|
| V1 baseline: leg arrival set, sender window contains departure | active, discoverable | **compatible** | **results**, Traveler B present |
| **V2: leg arrival left blank** (the app said "Optional") | active, discoverable | **refused** — `route_time_order_feasible`, `delivery_before_deadline` | Traveler B absent |
| V3: sender's ready window closes before B departs | active, discoverable | refused — `pickup_within_ready_window` | `no_candidates` |
| V4: request names airports ALG → CDG | active | compatible | results |
| V5: Journey Jijel → ALG → CDG, request Jijel → Paris | active | compatible (2 legs) | results |
| V5b: same Journey, request Algiers → Paris | active | compatible (flight leg only) | results |

V2 is a defect. V3 is the existing timing rule working as designed (§5).

**Limitation, stated plainly.** The owner's own records live in the deployed
TEST database. Railway exposes no read path to it from this environment — the
`Postgres` service has no TCP proxy and the Railway tooling has no remote
execution — and opening a public proxy on the database to look was not
something to do unasked. So which variant the owner's pair hit is **inferred**,
not observed. V2 is the one the app actively invited: the traveller route editor
labelled a leg's arrival *"Optional. It lets us check the next leg leaves in
time."*

---

## 2. Published-request route — root cause and fix

Traced create → `ParcelRequest` → canonical Place → serializer → mobile model →
widget:

| Stage | Finding |
|---|---|
| create | the form sends `pickup_place_id` / `delivery_place_id` (required) and `pickup_location_id` / `delivery_location_id` only when the sender set an optional meeting point |
| stored | `DeliveryRequest.pickup_place` / `delivery_place` — canonical, required for schema 3 by `parcels_delivery_v1_required` |
| serializer | `ParcelRequestSerializer` serves `pickup_place` / `delivery_place` (id, name, type, IATA, country, matching locality) at **every** status |
| mobile model | `DeliveryRequest.fromJson` parses them into `pickupPlace` / `deliveryPlace` correctly |
| **widget** | `request_detail_screen.dart` drew the route **only** from `pickupLocation` / `deliveryLocation` — the optional meeting points |

Classification **F**: stored, serialized and parsed correctly, then read from
the wrong field. Since Phase 8F-B made the map optional, most requests have no
meeting point, so the route card rendered empty. The Deliveries row and the
Home row had the same defect and showed a bare `→`. Journeys had the identical
bug and J1.2 fixed it with `endpointLabel`; requests never got it.

**Fix (mobile only).** `lib/features/requests/request_labels.dart` names a
request's route from its canonical places, falls back to a legacy row's coarse
location, and says **"Route not recorded"** (EN/FR/AR) when a historical row
genuinely has neither — it never reconstructs one. An airport endpoint reads as
the spec's locked stop form `Algiers · ALG` (the served city from
`matching_locality_name` plus the code the sender actually chose); a locality
never gains a code. The detail screen, the Deliveries row and the Home row all
use it. Meeting points, when present, are shown as detail rows inside the route
card instead of standing in for the route.

Why `Algiers · ALG` rather than the airport name: rendered at 320 pt, "Houari
Boumediene (ALG)" was cut to "Houari Bou…" and lost the code. That was found by
looking at the rendered screen, not by an assertion.

### Canonical place contract (request)

| Field | Present | Source |
|---|---|---|
| origin place | `pickup_place.id` | `DeliveryRequest.pickup_place` |
| destination place | `delivery_place.id` | `DeliveryRequest.delivery_place` |
| locality / city | `name`, `matching_locality_id`, `matching_locality_name` | `Place.resolve_matching_locality()` |
| country | `country_code` | `Place.country_id` |
| airport | `place_type = airport`, `iata_code` | only when the sender chose an airport |
| display label | `display_label` | catalogue |

Matching uses `matching_locality_id` equality, never a string. Coordinates,
radius, nearby and detour semantics were not reintroduced.

### Lifecycle and language

Pinned server-side: the route is served unchanged at `open`, `matched` (also via
a real accepted Deal), `in_transit`, `delivered`, `completed`, `cancelled` and
`expired`, and `Accept-Language: en | fr | ar` receive the byte-identical place
blocks. Pinned client-side: the detail screen draws the same route at all six
owner-facing statuses and in all three languages; Arabic reads
`Paris ← Algiers · ALG` with the start on the right.

---

## 3. Matching — root cause and fix

### The exact rule

`evaluate_compatibility` places a delivery at the arrival of the leg that ends at
the drop-off node (`_time_at_position(..., pickup=False)` →
`legs[node - 1].arrive_at`). With `arrive_at = NULL`:

* `delivery_at` is `None`;
* `route_time_order_feasible` (`pickup_at < delivery_at`) fails;
* `delivery_before_deadline` (`delivery_at <= deadline_at`) fails.

The evaluator is **right**: there is no instant to compare with the deadline,
and inventing one would fabricate compatibility.

### Why it was a defect anyway

The write contract disagreed with it. `JourneyLegInputSerializer.arrive_at` was
`required=False, allow_null=True`, publication accepted a NULL arrival, the
journey was listed `active` and `discoverable`, and the traveller app told the
traveller the field was optional. Nothing, anywhere, said the journey could
never be matched.

### Fix — at the write contract, not in matching

Following the brief's rule for this case ("if Journey creation produces invalid
leg structure, fix creation rather than weakening matching"):

* **Server write** — `apps/trips/serializers.py`: `arrive_at` is required and
  non-null on every leg, for create and edit alike (they share
  `JourneyRouteWriteSerializer`). The refusal is a field error on
  `legs[i].arrive_at`.
* **Server publication** — `apps/trips/services.py::_validate_leg_sequence`:
  a draft written before the rule is refused with the new code
  `journey_leg_arrival_required` (HTTP 409), so a legacy draft cannot reach
  senders.
* **Mobile** — the route editor marks arrival required, validates it
  (`journeyLegArriveRequired`), explains why (`journeyArriveHelp`: senders'
  deadlines are checked against it), and maps the new publish code to
  `journeyErrorLegArrivalRequired`, in EN/FR/AR.

`evaluate_compatibility`, discovery, ranking, Find Travelers, pricing, deposits,
Boost, ledger and payouts are **unchanged**. The DB column stays nullable for
historical rows. No migration.

### Existing data

* Read-time fallback: **not safe** — it would have to invent an arrival.
* Repair command: **not possible** — nothing on the row says when the traveller
  arrives.
* Existing *active* arrival-less Journeys therefore stay unmatchable until their
  departure passes and they expire. Active journeys are not editable (8F-A), so
  the traveller cancels and publishes again with arrival times. No data was
  mutated.

---

## 4. Compatibility audit (brief §7)

| Rule | Finding |
|---|---|
| origin / destination matching | canonical matching-locality equality; airports only through the active primary `SERVED` mapping — correct |
| leg coverage | ordered node anchors; contained and whole multi-leg ranges both correct |
| FLIGHT / DRIVE | write-time: FLIGHT legs must start/end at airports; publication re-checks road networks — correct |
| deadline / timing | inclusive `<=` at ready-start, ready-end and deadline; aware datetimes compared as instants — correct |
| departure / arrival order | strict `pickup_at < delivery_at`, correct because arrival must follow departure |
| **null schedule** | **the defect** (§3) |
| capacity / weight | `remaining >= weight` per covered leg, `DECIMAL` kg on both sides, active allocations subtracted — correct |
| request lifecycle | `request_ineligibility` reads the J1.3-persisted status — correct |
| Journey lifecycle | `discoverable` = active/in-progress with a future departure; a new journey is `active`, not expired — correct |
| KYC | `has_current_kyc_value` annotation — correct |
| self-match | excluded in the queryset and by `accounts_eligible` — correct |
| reservation / matched | active-Deal exclusion and `already_matched` — correct |
| deposit | `awaiting_deposit` → `request_ineligible` — correct |

### Place normalisation (brief §11)

Request and Journey creation both write canonical `Place` ids and both resolve
through `Place.resolve_matching_locality()`. The reviewed mapping file resolves
ALG → Algiers, CDG → Paris and ORY → Paris; the airports' physical communes
(Dar El Beida, Roissy-en-France, Orly) are `physical` mappings and never used
for matching. No
creation path picks an incompatible representation of the same place. Two
different communes (Algiers vs. Bab Ezzouar) remain incompatible, correctly —
neighbouring municipalities are not a V1 feature.

### Timezones (brief §9)

The request and Journey write bodies both send `toUtc().toIso8601String()`;
`TIME_ZONE = "UTC"`, `USE_TZ = True`. No UTC/local mismatch on the matching path.
One was found **off** it: the draft pricing quote
(`RequestRepository.quotePricingDraft`) sends `ready_window_end` and
`deadline_at` as naive local time, which the server reads as UTC — a 1–2 hour
shift in the quote's urgency input. Not fixed here: it is a pricing input, and
this phase does not touch pricing. Reported as MINOR.

---

## 5. What was deliberately not changed

**The ready-window rule.** The engine collects the parcel at the traveller's
departure from the pickup node, so that departure must fall inside the sender's
`[ready_window_start, ready_window_end]`. A sender whose "ready until" closes
before the traveller leaves is not matched even when the deadline is generous
(V3). That is the documented J4 gate, not an implementation defect, and the
brief forbids redesigning timing policy. Whether "ready until" should mean "the
last moment I can hand it over" rather than "the last moment the traveller may
depart" is a product decision, recorded as a finding.

---

## 6. Tests

### Backend — `apps/matching/tests/test_phase_j7b_route_matching.py`, 31 tests

| Case | Result |
|---|---|
| Owner scenario through the real endpoints | match at every stage; Find Travelers returns Traveler B with stops `Algiers · ALG → Paris · CDG` |
| Leg without arrival, key omitted and explicit `null` | **400** on `legs[0].arrive_at`, nothing written |
| Pre-rule draft without arrival | publish **409** `journey_leg_arrival_required` |
| Already-published arrival-less Journey | evaluator refuses on exactly `route_time_order_feasible` + `delivery_before_deadline`; still `discoverable` (what hid it) |
| Direct A → B | match |
| Contained B → C over A → B → C | match, covered = the one leg, `route_fit: good`, `continues_before` |
| Whole A → C over A → B → C | match, both legs, `route_fit: excellent` |
| Middle-node request over the J4 world | match |
| Request names airports | match |
| Different route / reverse direction / same-named twin locality | no match |
| Arrival one minute after deadline | no match, `delivery_before_deadline` only |
| Every timing boundary exactly equal | match (`<=` throughout) |
| Departure outside the ready window | no match, `pickup_within_ready_window` only (rule recorded) |
| Window posted at `+01:00` vs UTC | identical verdicts |
| 8.01 kg on an 8 kg leg / 8.00 kg exactly | no match / match |
| Capacity reserved by an accepted offer | subtracted; 6.5 kg no longer fits |
| Journey `pending_verification`, `draft`, `cancelled`, `expired` | `no_candidates` |
| New published Journey | `active`, discoverable |
| Awaiting deposit / already matched (real acceptance) | `request_ineligible` with the right `reason` |
| Sender's own Journey | excluded, `accounts_eligible` |
| Request detail route at 7 statuses, real Deal, 3 languages, list | canonical places every time |
| Find Travelers HTTP query count at 1 and 10 candidates | equal |

Mutation check: restoring the pre-J7B serializer and publication fails the two
arrival tests.

`apps/trips/tests/test_phase8fa_journey_editing.py`: seven leg payloads gained an
arrival and one test that cleared a drive leg's arrival now moves it instead —
its subject (a neighbouring drive edit leaves flight proof alone) is unchanged.

### Mobile — `test/phase_j7b_route_matching_test.dart`, 26 tests

Decoder keeps both places; labels from places with no meeting point; airport as
`Algiers · ALG`, a locality never gains a code, airport without a served city
keeps its own name; a meeting point never replaces the place; legacy coarse
fallback; historical row gets no route. Detail screen draws the route in EN, FR
and AR and at `open`, `matched`, `in_transit`, `delivered`, `completed`,
`cancelled`; meeting points appear as detail rows; a route-less row says "Route
not recorded". Deliveries (EN, and AR right-to-left) and Home rows name the
route. Route draft: missing arrival is invalid with its own message, present is
valid, before-departure keeps its message; the publish refusal maps to its copy.

Mutation checks: the pre-J7B detail screen fails all 12 detail-route widget
tests; the pre-J7B Deliveries and Home screens fail all 3 list-row tests.

`test/phase8fa_route_model_test.dart`: `RouteCopy` gained `arriveRequired`.

### Visual

The request detail was rendered to PNG on the throwaway golden rig (not
committed) at 320 × 640 in EN, FR and AR, with and without a meeting point, and
inspected. That is what caught the truncated airport name (§2).

---

## 7. Performance

`GET /api/matches/find-travelers`, PostgreSQL, `CaptureQueriesContext`:

| Candidates | HTTP call | `find_travelers` page | discovery scan |
|---|---|---|---|
| 1 | 9 | 7 | 5 |
| 10 | 9 | 7 | 5 |
| 40 | 9 | 7 | 5 |

Flat, identical to J4's 7-query page. No per-candidate query. J7B changed no
code on this path.

---

## 8. Findings

**BLOCKER** — none remaining. The matching BLOCKER is closed for every Journey
written from now on.

**MAJOR** — none remaining in code. Operational: any Journey already published
on TEST without leg arrivals stays unmatchable; the traveller must cancel it and
publish again.

**MINOR**

* The ready-window rule (§5) may not be what a sender means by "ready until" —
  product decision, not changed.
* The draft pricing quote sends naive local datetimes (§4) — pricing input, not
  changed.
* An arrival-less legacy Journey is refused with two indirect codes rather than
  one naming the missing arrival; new writes cannot produce one.
* A Latin-script meeting-point address inside an Arabic layout reorders its
  leading number ("Rue Didouche 12 Mourad") — pre-existing bidi behaviour, same
  in the creation review step.
* In French at 320 pt the request title wraps mid-word beside a long status pill
  ("Docu / ments") — pre-existing header layout.

---

## 9. Release

Branch CI, merge, TEST deployment, health checks and the TEST APK are recorded in
`docs/IMPLEMENTATION_STATUS.md`.

**Signed-in end-to-end on the deployed TEST service: not performed.** This
environment holds no TEST account credentials, and creating accounts is not
something to do on the owner's behalf. The equivalent was run against real
PostgreSQL through the same HTTP endpoints and the same deposit reconciliation
path (§1, `OwnerScenarioTests`). The deployed checks are unauthenticated reads
only; no row was created or modified on the deployed database.
