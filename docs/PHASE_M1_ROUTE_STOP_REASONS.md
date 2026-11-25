# M1: missing route stops get their own rejection reasons (2026-11-25)

Phone test 2, plan `docs/WASSLA_PHONE_TEST_2_PLAN.md` sections 1.6 and 1.7, package M1 (Claude Opus,
extra high). Server only: no migration, no Go change, no Dart change. Nothing is deployed by this change.

## The defect

Request 1 goes from Jijel (commune) to Paris. Journey 11 is one flight, ALG → CDG, leaving 26 Nov 21:37
and arriving 27 Nov 21:37 (UTC); the request is ready 24 Nov 21:18 to 30 Nov 21:18, with the same
deadline. ALG serves Algiers, so the journey's stops are `[Algiers, Paris]` and it never visits Jijel.
The verdict, not compatible, was right.

The reason was wrong. `evaluate_compatibility` found no pickup anchor, so there were zero ordered
pickup/drop-off pairs, and it recorded `pickup_before_delivery` failed with empty details. The same
branch covered a missing pickup, a missing drop-off, both missing and a genuinely reversed route. The
app groups `pickup_before_delivery` with the time gates and said "The dates don't line up", although
the dates fit.

## What the evaluator answers now

Every route outcome has its own answer. The new gates are `pickup_stop_on_route` and
`delivery_stop_on_route`, named like the existing gates (the condition that must hold).

| Situation | `rejection_codes` from the route step |
| --- | --- |
| A request city the matching catalogue cannot place (for example an airport with no active primary served locality) | none: the existing `canonical_geography_complete` is the whole answer |
| The journey has no stop in the pickup city | `pickup_stop_on_route` |
| The journey has no stop in the drop-off city | `delivery_stop_on_route` |
| Neither city is a stop | `pickup_stop_on_route`, `delivery_stop_on_route` |
| Both are stops, but no pickup stop comes before a drop-off stop | `pickup_before_delivery` |

`pickup_before_delivery` now fails only for a real order failure.

**Evaluation order.** The route step runs where it did: after the account, request, item and catalogue
gates, before stop services, ticket, time, capacity and distance. A route refusal returns at once, as
before, so a missing-stop or wrong-order refusal never carries a date code. A journey whose own airport
the catalogue cannot place still fails `journey_leg_sequence` first, unchanged.

**Internal record.** Every evaluation that reaches the route step records both stop gates in `checks`,
passed or failed, so staff see which end failed. A failed `pickup_before_delivery` now carries
`pickup_positions` and `delivery_positions` (the stops found for each city). `checks` and their details
stay internal: they are on the staff explanation and the Match/Offer/Deal snapshots, never on a
counterparty payload.

**Legacy flow.** The same classification applies to schema-2 requests and journeys. Anchor computation
is untouched (an exact node, or a projection onto a DRIVE leg's corridor), so a legacy place is missing
only when it is neither a node nor projectable onto any drive leg.

**Unchanged.** Anchor computation, alternate-pair selection for repeated stops (shortest pair first,
falling through to the next when timing fails), every hard gate, covered legs, positions, times,
distances, capacity and every price input.

## Public output

No projection change was needed. `public_compatibility_payload` already passes `rejection_codes`
through and drops `checks`, positions, detour metres and interpolated instants; the new codes are gate
names and carry no geometry. No serializer and no `find_travelers.py` change.

Where a party sees the new codes:

- `POST /api/matches/quote`, 409 `incompatible_candidate`: `rejection_codes` and
  `compatibility.rejection_codes` (the focused Find Travelers explanation);
- `POST /api/discovery/requests/{id}/interest` ("I can carry this"), 409 `incompatible_candidate`:
  `rejection_codes`;
- `POST /api/matches/propose`, `POST /api/offers/{id}/counter`, `POST /api/offers/{id}/accept`, 409
  `incompatible_candidate`: `rejection_codes`;
- staff: `GET /api/matches/explain` and the snapshots, with the gate details.

Find Travelers, Matches and the compatible-request lists only ever list compatible pairs, so they are
unchanged.

## Evidence that no accepted pair changed

A scratch pytest plugin (not committed) wrapped `evaluate_compatibility` and `evaluate_candidate` and
fingerprinted every top-level evaluation: verdict, rejection codes, gate list, covered leg positions,
pickup and delivery positions, pickup and delivery instants (relative to the first departure), detours,
added distance and duration, matched distance and method, distance components, remaining capacity,
limitations, and the full pricing quote with the listed price. It ran over `apps/matching`,
`apps/discovery`, `apps/deals`, `apps/trips`, `apps/parcels`, `apps/boosts`, `apps/ratings`,
`apps/notifications` and `apps/chat` on PostgreSQL, once on `main` and once on this branch, and the two
recordings were compared test by test.

Result, over the 637 existing tests that evaluate a pair:

| Measure | Result |
| --- | --- |
| Accepted evaluations compared | 3,884 |
| Identical verdict, codes, covered legs, positions, instants, detours, distances, capacity and limitations | 3,884 (all) |
| Difference in `checks` | only the two new passed rows, `pickup_stop_on_route` and `delivery_stop_on_route` |
| Priced evaluations compared | 3,844 |
| Identical quote and listed price | 3,844 (all) |
| Verdict changes, accepted or rejected | 0 |
| Rejected evaluations compared | 97; 87 keep their codes |
| `pickup_before_delivery` → `pickup_stop_on_route` | 6 |
| `pickup_before_delivery` → `delivery_stop_on_route` | 4 |
| `pickup_before_delivery` kept (real wrong order) | 10 |

Leg ids embedded in a limitation string (`leg_<id>_road_distance_unavailable_...`) were normalised before
comparing, because the new tests create rows earlier and shift database ids; covered legs were compared
by position for the same reason.

## Tests

Rewritten (the rule changed):

- `apps/matching/tests/test_phase8c_canonical.py`,
  `test_canonical_locality_identity_matches_and_different_ids_do_not`: asserted `pickup_before_delivery`
  for a request from a same-named twin Paris that is no stop of the journey. That is a missing pickup
  stop, so it now asserts exactly `("pickup_stop_on_route",)`.

Strengthened (same rule, exact codes):

- `test_phase_j7b_route_matching.py`: a different route (`("delivery_stop_on_route",)`), the reverse
  direction (exactly `("pickup_before_delivery",)`), the twin locality (`("pickup_stop_on_route",)`).
- `apps/discovery/tests/test_interest.py`: the incompatible-journey signal answers exactly
  `["pickup_stop_on_route"]`.

Unchanged and still passing: `test_phase2_matching.py`'s two `pickup_before_delivery` assertions (a
legacy reversed request and canonical reversed sub-routes). Both are real order failures.

New, at the incident clock (`INCIDENT_AT` = 24 Nov 2026 22:00 UTC, `timezone.now` patched):

- `test_phase8c_canonical.py` (evaluator): Jijel/Paris against ALG/CDG is exactly
  `pickup_stop_on_route`, with no order or date gate run and nothing public but the code; Algiers/Paris
  on the same dates is compatible with the flight as its only covered leg, its instants, its
  great-circle distance and a quote equal to `calculate_pricing_quote` on those inputs; drop-off
  missing; both missing; reversed order (internal positions, public code only); an unresolved airport
  on the request (`canonical_geography_complete` only) and on the journey (`journey_leg_sequence`);
  genuine ready-window and deadline failures, each alone; a real two-leg Jijel → Algiers → Paris
  journey covering both legs; repeated stops ALG → CDG → ALG → CDG keeping alternate-pair selection.
- `test_phase_j7b_route_matching.py` (`IncidentPairTests`, through the endpoints): the evaluator;
  Find Travelers (no candidates for Jijel, journey 11 found for Algiers); the quote 409 in exactly the
  allowlisted shape; a sender offer refused with `pickup_stop_on_route`, with and without a EUR 1,000
  Boost, and no offer written.
- `apps/discovery/tests/test_interest.py` (`IncidentInterestTests`): "I can carry this" refused with
  exactly `code`, `detail` and `rejection_codes: ["pickup_stop_on_route"]`, with and without Boost; no
  interest, no notification, no offer; the Algiers request on the same journey is a real signal.

## Docs

- Helper knowledge `trips-and-matching.md`: the matching section explains both stop gates with the
  Jijel example, narrows `pickup_before_delivery` to the order of stops, and says an uncatalogued city
  fails only `canonical_geography_complete`; the Find Travelers checklist names the codes.
  `INSTRUCTIONS.txt` regenerated with `manage.py build_helper_instructions`.

## Checks

Local, on this workstation (PostgreSQL through the embedded test cluster):

- `ruff check .`: clean. `makemigrations --check --dry-run`: no changes. `build_helper_instructions
  --check`: up to date.
- `apps/matching`, `apps/discovery`, `apps/deals`, `apps/trips`, `apps/parcels`, `apps/boosts`,
  `apps/ratings`, `apps/notifications`, `apps/chat` on this branch: 1,570 passed, 3 failed, all three in
  `apps/notifications/tests/test_v2_readiness.py` and none touching matching. Two
  (`test_every_literal_has_a_translation_and_placeholders_match`, a French `.po` file read in the
  Windows code page, and `test_cutoff_holds_old_rows_without_starving_new_obligations`, a clock tick)
  fail identically on `main` here. The third
  (`test_backlog_audit_is_read_only_and_review_is_explicit_and_audited`) passed on `main` and passes
  alone on this branch three times out of three; it ran while another full suite loaded the machine.
- The full suite is CI's.

## Handoff to M2

New public codes (stable):

| Code | Meaning | Suggested copy |
| --- | --- | --- |
| `pickup_stop_on_route` | The trip has no stop in the parcel's departure city. | "This trip does not pick up in the parcel's departure city." |
| `delivery_stop_on_route` | The trip has no stop in the parcel's delivery city. | "This trip does not stop in the parcel's delivery city." |
| `pickup_before_delivery` (narrowed) | The trip visits both cities, the delivery city first. | "This trip goes the other way." |

- Both stop codes arrive together when neither city is on the route; de-duplicate as today.
- None of the three is a date problem. Only `route_time_order_feasible`, `pickup_within_ready_window`
  and `delivery_before_deadline` are.
- An older server still sends the ambiguous `pickup_before_delivery` for every route failure. Copy for
  it must be true of both releases (plan M2: "The trip must visit the pickup city and then the delivery
  city.").
- Until M2 ships, today's app shows its generic line ("The trip and the parcel don't match.") for the
  two new codes, because it maps unknown codes to it. That is accurate, and no longer a date claim.
- M2 touches no `backend/` file: this package owns the codes.
