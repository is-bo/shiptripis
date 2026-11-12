# L3A: Routes for everyone, backend (contract)

Package L3A of `docs/WASSLA_DISCOVERY_PRO_PLAN.md`, built against `docs/WASSLA_DISCOVERY_PRO_SPEC.md`
sections 5.1 to 5.7. Everything here is enforced by the server; the app renders what it is told.
Flight and road behaviour is unchanged for every existing input.

## 1. What exists after L3A

- **Sea legs.** `JourneyLeg.Mode.SEA` joins FLIGHT and DRIVE. A sea leg runs between two catalogue
  cities joined by an active `locations.SeaCrossing`, only while the "Sea legs" switch is on.
- **One ticket rule.** `apps/trips/proofs.py` is the only code that decides whether a leg needs a
  ticket and whether that need is met. Flight and sea legs need one; road legs do not.
- **Stop options.** Each stop of a route (node 0 to n) may accept pickup, drop-off, both or neither,
  with an optional handover window and a short note (`trips.JourneyStopDetail`).
- **What the traveler accepts.** `Journey.refused_categories` and `Journey.accepts_fragile`.
- **Secondary capacity.** Optional `capacity_volume_l` and `capacity_parcels` per leg, reserved on
  acceptance next to weight. The leg weight ceiling is now 20,000 kg (typo guard).
- **Pause.** The owner pauses and resumes their own live journey; staff pause and resume any journey
  that is not finished, with a reason and an audit row.

## 2. Schema (all additive)

| Table | Change |
| --- | --- |
| `locations_sea_crossing` | New. `origin_locality`, `destination_locality` (PROTECT), `distance_meters`, `is_active` (default false), timestamps. Unique per direction; the two ports differ; distance above 0. |
| `trips_journey_leg` | `mode` gains `SEA`. `capacity_volume_l` (int, null), `capacity_parcels` (smallint, null), both above 0 when set. A sea leg has no flight number (CHECK). |
| `trips_journey` | `refused_categories` (jsonb list, default `[]`), `accepts_fragile` (default true), `paused_at`, `paused_by_staff`, `pause_reason` (500). CHECK `journey_pause_consistent`: unpaused has no reason and no staff flag; an owner pause has no reason; a staff pause has a reason. |
| `trips_journey_stop_detail` | New. `journey`, `position`, `accepts_pickup`, `accepts_dropoff`, `handover_note` (280), `window_start`, `window_end`. Unique on journey and position; the window is both-or-neither and ends after it starts. |
| `deals_deal_leg_allocation` | `allocated_volume_l` (numeric 10,3, null), above 0 when set. |
| `notifications_outbound_message` | Kind `flight_proof_status` becomes `leg_proof_status`. |

Migrations: `locations/0007_l3a_sea_crossing`, `trips/0009_l3a_routes_for_everyone`,
`deals/0010_l3a_allocation_volume`, `notifications/0008_l3a_leg_proof_status_kind`. `schema.sql` is
regenerated in the same change.

## 3. Mode rules (`apps/trips/transport_rules.py`)

- **DRIVE:** unchanged. Same road network only (Algeria alone; France, Spain and Germany together;
  an undeclared country is its own island).
- **FLIGHT:** never refused by geography. Airport endpoints and the flight number stay serializer
  rules.
- **SEA:** the switch is on, both endpoints are active LOCALITY places, an active crossing joins them
  in this direction, and there is no flight number.

A refusal keeps `journey_leg_mode_unavailable`. A sea refusal adds `reason` and has no
`required_mode`; a road refusal is byte-identical to before (it names `required_mode`, has no
`reason`).

| `reason` | When |
| --- | --- |
| `sea_legs_disabled` | The switch is off, or the settings revision cannot be read (fails closed, logged). |
| `sea_endpoint_not_port_city` | An endpoint is not an active city, or is a city that is no endpoint of any crossing. |
| `sea_crossing_unavailable` | Both ends are port cities but no active crossing joins them this way. |

The rule runs on create, on edit and again on publication, so a switch turned off or a crossing
deactivated between draft and publish is caught.

A sea leg's distance is its crossing's `distance_meters`, frozen on the leg when it is written
(`route_provider="sea_crossing"`, `route_profile="sea"`, `route_metadata={"sea_crossing_id"}`).
The crossing distance is the catalogue great-circle distance, the same haversine a flight uses.

## 4. Ticket proof (`apps/trips/proofs.py`)

| Function | Answers |
| --- | --- |
| `leg_requires_proof(leg)` | Flight or sea. |
| `leg_proof_satisfied(leg)` / `journey_proof_gaps(legs)` | Python decisions. Reads the `has_approved_proof_value` annotation, then a `proofs` prefetch, then one query. |
| `proof_gap_exists()` | SQL twin for querysets (listings). |
| `proof_state_annotation()` / `leg_proof_state(leg)` | The payload's `proof_state`. |

Callers: publication (`validate_journey_verification_gates`), compatibility, the acceptance lock's
witnesses, listings, Find Travelers' reasons, journey payloads and the admin console. L6A's
professional exemption changes these functions only.

- Publication refuses with `flight_proof_not_approved` or `sea_proof_not_approved`, naming the first
  leg in route order without an approved ticket.
- `POST /api/journeys/<id>/legs/<leg>/proof` accepts flight and sea legs; a road leg is refused with
  `proof_not_required` (was `proof_only_for_flight`).
- Each journey leg in a payload has `proof_required` (bool) and `proof_state`: `not_required`,
  `missing`, `pending`, `approved`, `rejected`. Precedence is approved, then pending, then rejected,
  then missing, so a newer refusal never hides a proof that can still be approved.
- An edit that materially changes a ticket leg, or changes a leg's mode, sends its proof back for
  review (reason `ticket_leg_materially_changed`).
- Review: `review_flight_proof` (name and `review_flight_proofs` permission kept) now enqueues
  `leg_proof_status` with `mode` in the context and publishes `leg_proof.status_changed` with `mode`.
  Push and email copy name the ticket: "Flight ticket approved", "Ferry ticket needs attention",
  "Wassla ferry ticket update", in English, French and Arabic.

## 5. Sea crossings

- **Data:** `backend/monolith/apps/locations/data/sea_crossings.json`, version `2026-11-11`: 13 ports
  with reviewed coordinates and 38 rows (spec 5.3.1, both directions): the twelve listed lines active,
  the seven others inactive.
- **Seed:** `python manage.py seed_sea_crossings [--file PATH]`. A port must resolve to exactly one
  active catalogue city in its country, by name or active alternate name; anything else is reported
  and every crossing that uses it is skipped. Existing rows are never touched, so a re-run never
  re-activates a line staff switched off or rewrites a corrected distance. New rows take their distance
  from catalogue coordinates when both cities have them, otherwise from the file's coordinates. Each
  created row writes an audit row `sea_crossing.seeded` (no actor). The VPS `catalogue` step runs it
  after `import_geography`. On the real catalogue all 13 ports resolve (Algiers through its alternate
  name for Alger Centre) and the seed creates 38 rows, then 0 on a re-run.
- **Staff services** (`apps/locations/sea_crossings.py`, permission `manage_settings`, reason required,
  one audit row per change): `create_crossing` (inactive by default; a distance in km is required
  only when a city has no coordinates, at most 5,000 km), `activate_crossing`, `deactivate_crossing`
  (no-ops write nothing). There is no edit: a correction is a new crossing plus deactivating the wrong
  one. Codes: `sea_crossing_reason_required`, `sea_crossing_port_invalid`,
  `sea_crossing_ports_identical`, `sea_crossing_distance_required`, `sea_crossing_distance_invalid`,
  `sea_crossing_exists`, `sea_crossing_not_found`. The console screens are L3B.
- **Public list:** `GET /api/geography/sea-crossings` (anonymous, `Cache-Control: max-age=300`):

```json
{"enabled": false,
 "crossings": [{"origin": {"id": 1, "name": "Marseille", "display_label": "Marseille", "country_code": "FR"},
                "destination": {"id": 2, "name": "Algiers", "display_label": "Algiers", "country_code": "DZ"}}]}
```

Active rows only. `enabled` is the switch.

## 6. Journey write and read

The create body (`POST /api/journeys`) and edit body (`PATCH /api/journeys/<id>`) gain:

| Field | Rule |
| --- | --- |
| `legs[].capacity_volume_l` | Optional, 1 to 200,000 litres; null means not limited. |
| `legs[].capacity_parcels` | Optional, 1 to 10,000; null means not limited. |
| `legs[].capacity_kg` | Up to 20,000.00. |
| `stops` | Optional list (at most 21) of `{position, accepts_pickup=true, accepts_dropoff=true, handover_note="" (280), window_start=null, window_end=null}`. |
| `refused_categories` | Optional list of request item types; stored sorted and unique; refusing all five is refused. |
| `accepts_fragile` | Optional, default true. |

Stop refusals answer 400 with `code: journey_stop_invalid`, a `reason` and the offending stop index:
`stop_position_unknown`, `stop_position_duplicated`, `first_stop_dropoff_only`,
`last_stop_pickup_only`, `stop_window_incomplete`, `stop_window_invalid`, `stop_window_outside_stop`
(the window must fit between arriving at and leaving that stop). A stop left at its defaults is not
stored. An edit replaces the stop options as a whole.

Journey payloads gain:

- `stops`: every node with `position`, `place_id`, and what it *effectively* accepts (nothing is
  dropped off at the first stop or picked up at the last). The owner also gets `handover_note`,
  `window_start` and `window_end`; nobody else ever does.
- `refused_categories`, `accepts_fragile`.
- `pause` (owner only): `{paused, paused_at, paused_by_staff}`. The staff reason is never exposed.
- per leg: `capacity_volume_l`, `capacity_parcels`, `proof_required`, `proof_state`.

The handover note and window reach a sender only through a funded deal: `Deal.arrival_snapshot`
freezes `handover_stops` (the pickup and drop-off stops this deal uses, with role, position, note and
window) at funding, and the deal payload's `route.handover_stops` serves it to the deal's two parties.

## 7. Pause

| Call | Who | Result |
| --- | --- | --- |
| `POST /api/journeys/<id>/pause` | Owner, journey ACTIVE or IN_PROGRESS | 200 with the journey; idempotent. |
| `POST /api/journeys/<id>/resume` | Owner | 200; idempotent. A staff pause answers 409 `journey_paused_by_staff`. |
| `pause_journey(actor, journey_id, reason)` | Staff with `manage_journeys` | Also draft or awaiting-verification journeys. Takes over an owner pause. Audit `journey.paused`. |
| `resume_journey(actor, journey_id, reason)` | Staff with `manage_journeys` | Lifts a staff pause only (`journey_paused_by_owner` otherwise). Audit `journey.resumed`. |

Other codes: `journey_not_owned` (403), `journey_not_pausable` (409),
`journey_pause_reason_required`. A paused journey is out of every discovery surface (scans, Find
Travelers, Matches on both sides, listings, a non-owner's journey detail) through
`lifecycle.discoverable()`. New offers are refused with `journey_paused`; a pending offer stays
pending and cannot be accepted until the pause is lifted. Funded deals are untouched. Pause and
acceptance take the same journey row lock.

## 8. Matching

`MATCHING_VERSION = "v1-matching-2"`. New checks, in evaluation order:

| Check | Fails when |
| --- | --- |
| `journey_not_paused` | The journey is paused. |
| `item_accepted_by_traveler` | The request's category is refused, or it is fragile and the traveler takes no fragile items. Details: `category_accepted`, `fragile_accepted`. |
| `stop_services_allow_handover` | The pickup stop does not accept pickup or the drop-off stop does not accept drop-off. Details: `pickup_stop`, `dropoff_stop`. |
| `sea_legs_available` | Any sea leg of the journey has the switch off or no active crossing (whole journey, spec 5.3). |
| `sea_proofs_approved` | A sea leg has no approved ticket (`flight_proofs_approved` stays for flights). |
| `volume_available_on_every_leg` | A covered leg declares a volume and the request's L×W×H (litres, rounded up to 0.001) does not fit. A request without dimensions passes with the limitation `volume_unverified`. |
| `parcel_slots_available_on_every_leg` | A covered leg declares a parcel count and every slot is taken. |

Capacity rows add `capacity_volume_l`, `reserved_volume_l`, `capacity_parcels` and
`reserved_parcels` only for a leg that declares them; a leg without them reports exactly as before.
A sea leg prices on its crossing distance (`great_circle_sea_crossing`). A road leg between cities
without coordinates and with no stored distance prices at the distance floor
(`canonical_place_floor`) instead of failing the scan.

Acceptance re-checks everything under the existing locks: ticket witnesses for every flight and sea
leg, and weight, volume and parcel slots together from one aggregate. A volume or slot failure answers
`capacity_exceeded`. The allocation records `allocated_volume_l` when the request has dimensions.

The switch is read once per scan (`_attach_sea_switch`) and once per single evaluation; crossing state
and stop options come from leg annotations, so a sea journey adds no query per candidate.

Find Travelers: `primary_mode` is FLIGHT if any covered leg flies, else SEA if any sails, else the
first mode. `match_reasons` adds `sea_proof_approved` next to `flight_proof_approved`, each only for a
covered leg whose ticket is approved.

Listings (`listable_journeys(at, sea_legs_enabled)`): ticket gaps through `proof_gap_exists()`; a sea
leg with the switch off, or without an active crossing, hides the journey; a leg ahead that is full by
weight, volume or parcel slots hides it. A non-owner's journey detail answers 404 for the same closed
sea leg (`transport_rules.unavailable_sea_legs`, shared with compatibility).

## 9. Notifications

The Redis channel `flight_proof.status_changed` is now `leg_proof.status_changed` in Django
(`apps.core.channels.LEG_PROOF_STATUS_CHANGED`), the push matrix, the Go dispatcher list and the app
(channel mapping and live updates). The app's `proof_only_for_flight` mapping now reads
`proof_not_required`. No alias is kept: the app was never in production.

## 10. Tests

- `apps/trips/tests/test_l3a_routes.py`: mode matrix (every launch-country pair for road, flight and
  sea, switch off and on, crossing active, inactive and missing, airports, retired port, unreadable
  settings); API refusals and payloads; ticket states for publish and payload; stop validation; item
  rules; secondary capacity bounds; owner and staff pause with audit and DB constraint; crossing
  services, the public list and the seed command (including a re-run after staff changes and the
  shipped file's symmetry).
- `apps/matching/tests/test_l3a_matching.py`: the "done when" route through the API and the real
  ticket review; every span matched; distance per mode; Find Travelers naming the ferry; a Lille to
  Paris parcel allocating nothing on the sea leg; switch off and crossing deactivation closing scans,
  offers and listings (model and API); stop services and item rules through both the annotated scan
  and a direct evaluation; volume and parcel slots; pause on every surface; the handover note absent
  from every pre-funding payload and present in the funded route; flat query counts for the scan,
  Find Travelers and compatible requests; two concurrency races (last parcel slot, last litres) where
  exactly one acceptance wins.
- `apps/notifications/tests/test_l3a_ticket_copy.py`: email and push copy per mode and language, and
  the review path's outbox and channel payload.
- `apps/trips/tests/sea_world.py`: the shared fixture (launch countries, French and Spanish cities
  without coordinates, Marseille and Algiers lines, a switched-off Barcelona to Oran line).
