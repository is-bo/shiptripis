# P2: cards show cities, detail pages show the catalogue place (2026-11-24)

Ismail's phone test of 2026-11-24: "The route should only show the cities ('Alger Paris', not 'Alger
Centre Alger Paris Paris')". Fix plan of 2026-11-24, package P2; owner decision Q1 = the wilaya.
Server only: no migration, no app change, no new wording. Nothing is deployed by this change.

## The owner's rule

**Cards show cities; detail pages show the catalogue place; the exact location only after funding.**
Ismail's ruling during the second-pass review, 2026-11-24:

- **Cards and list rows** name each place as a city, in every name field, with the catalogue ids
  kept. This covers:
  - Home and Browse trip and request cards;
  - people and profile cards, the person page and the own profile preview;
  - Find Travelers cards and stops;
  - route alerts and "Matches for you";
  - the compatible-request rows on a traveler's journey screen.
- **Detail pages** keep the full catalogue place, as before (`Houari Boumediene Airport · Alger`,
  `Lyon · Rhône`). That means journey detail and its legs, request detail, the negotiation screen's
  proposal, the schedule-change view and the sender's quote. The owner's own screens, the place
  picker, the staff console, the staff explain and every stored snapshot keep it too.
- Exact addresses and preferred map points stay hidden until funding, exactly as before.

## Cause

Every card label was the catalogue's `Place.display_label`, `"<name> · <parent name>"`. A commune's
parent is an administrative area, not a city: `Alger Centre · Alger`, `Paris · Paris`,
`Berlin, Stadt · Berlin, Stadt`.

## The rule for a city name

There is one module, `apps/locations/city_names.py`. It holds `city_name(place)`, and `card_place(place)`
for a place summary on a list row. `city_name` works like this:

- **Algeria:** the wilaya (`Alger Centre`, `Bab Ezzouar` → `Alger`; `Tamanghasset` → `Tamanrasset`).
  Only a parent the catalogue records as a `wilaya` counts. A commune without one names nothing: it
  does not fall back to its own name or a daïra's.
- **Germany:** the name before the first comma (`Berlin, Stadt` → `Berlin`,
  `München, Landeshauptstadt` → `München`, `Halle (Saale), Stadt` → `Halle (Saale)`,
  `Erkrath, Fundort des Neanderthalers, Stadt` → `Erkrath`). Destatis writes `", "` everywhere
  except one row without the space (`Ebstorf,Klosterflecken` → `Ebstorf`). That is why the split is on
  the comma itself.
- **Spain:** a postposed article moves to the front, part by part around the slash of a bilingual
  name. Examples: `Coruña, A` → `A Coruña`, `Palmas de Gran Canaria, Las` → `Las Palmas de Gran Canaria`,
  `Alfàs del Pi, l'` → `l'Alfàs del Pi`, and `Vila Joiosa, la/Villajoyosa` →
  `la Vila Joiosa/Villajoyosa`. `Alacant/Alicante` is unchanged.
  - Only INE's closed set of articles moves (`El La Los Las el la les els Les Els L' l' A O As Os Es Sa
    Ses`).
  - Three names contain a real comma that is not an article (`Saus, Camallera i Llampaies`). They stay
    whole.
- **France and anywhere else:** the commune's own name.
- **An airport** reads as the city it serves. An unmapped airport names nothing (fails closed).

Over the whole 2026 manifest, every one of the 55,297 localities gets a non-empty name. All 1,541
Algerian communes have a wilaya parent.

`card_place(place)` returns `{id, name, display_label, place_type, country_code, iata_code,
matching_locality_id}`. Both `name` and `display_label` are the city. It resolves the served locality
once and uses it for both the id and the name.

## Where it applies

- **`locality_block` `label`** (`apps/discovery/places.py`): request cards, "Matches for you" items,
  usual routes, route alerts.
- **Find Travelers and trip-card stops** (`apps/matching/find_travelers.py` `_stop`). The IATA code still
  rides beside the city (`Alger` · `ALG`). Only a stop with no catalogue place at all falls back to a
  legacy `Location` label. A catalogue stop that names no city stays unnamed.
- **Compatible-request rows** (`CandidateEvaluation.as_card_row`). These are served by
  `GET /api/matches/compatible-requests` and the traveler side of "Matches for you".
  - Every place is built with `card_place`: the request's pickup and delivery, the journey header and
    the covered legs.
  - Where an endpoint has a catalogue place, that place wins over a preferred map point.
  - The detour-bearing recommendation stays withheld, as before.

Unchanged on purpose:

- `as_public_dict` (the sender's quote) and `as_dict` (the staff explain).
- `compatibility._public_place_summary`, so stored snapshots keep the full label.
- The proposal serializer (`apps/matching/serializers.py`), which feeds the negotiation screen.
- The journey and request detail serializers, the schedule-change projection, the staff console, the
  picker and `deals/route.py`.
- `Place.display_label` itself.

No matching result changes. `city_name` only reads names, and matching identity is unchanged.

Two fallback reads now also join the locality's parent (`select_related("locality__parent")`):
`Place.resolve_matching_locality` and `find_travelers._locality_of`.

## Query counts

- Every card queryset already loads the parent and the served mappings with the locality's parent.
- New `_load_endpoint_mappings` in `apps/matching/discovery.py`. Before, a journey whose header named
  one Paris airport and whose first leg left from another (ORY and CDG) cost one mapping query per
  candidate. Now one batch query loads those headers' served mappings, using the same filter. The new
  test `test_compatible_journeys_cost_is_flat_with_a_header_airport_no_leg_uses` holds at 4 and at 8
  journeys. Without the batch load it measured 8 and then 12 queries.
- The proposal read queryset is unchanged from `main`. The extra mapping prefetches of the first
  version were removed along with the proposal change.

## Tests

### Added

**`apps/locations/tests/test_city_names.py`** covers the rule on catalogue-shaped rows:

- every example above;
- Algeria with no parent and with a daïra parent → empty;
- ALG → `Alger`, BER → `Berlin`, an unmapped airport → empty;
- `card_place` carries the city in both name fields and keeps the ids;
- no query runs when the parent and mapping are already loaded;
- `display_label` is unchanged.

**`apps/discovery/tests/test_city_names.py`** uses the canonical world given catalogue names and parents
(`support.give_catalogue_names`).

- Guest and member reads of trips, requests, people, the person page, the own preview, alerts and
  "Matches for you" name only `Alger`, `Paris` and `Jijel`. An ALG → CDG trip card reads
  `["Alger", "Paris"]`.
- Every card payload is also checked as JSON text. None of these may appear: the commune behind the
  wilaya, either airport's name, a department, the ` · ` separator, or the labels of the preferred
  points.
- Find Travelers stops read `("Paris","CDG"), ("Alger","ALG"), ("Jijel",None)`.
- Compatible-request rows, with preferred map points on both the request and the journey, carry the
  card place in `pickup`, in the journey header and in the covered legs.
- Detail pages keep the catalogue place:
  - the negotiation detail reads `Paris · Paris` and `Jijel · Jijel`;
  - a member's journey detail reads `Houari Boumediene Airport · Alger`;
  - the staff explain reads `Paris · Paris`;
  - the owner, the picker and staff read `Alger Centre · Alger`.

**`apps/discovery/tests/test_privacy.py`** now gives the privacy world catalogue parents. Every walk also
checks the stop labels, the department, the commune behind the wilaya and the airport names.

**`apps/matching/tests/test_phase_k7e_discovery_query_counts.py`** gains
`test_compatible_journeys_cost_is_flat_with_a_header_airport_no_leg_uses`.

The new card tests fail on the first version (`cf5b585`): its compatible-request rows took the
preferred point for `pickup`. The discovery and privacy tests fail when the builders are switched back
to `display_label`.

### Changed fixtures

- `CanonicalOfferFixture` (`apps/matching/tests/test_phase8dr_offer_locks.py`) has a new opt-in,
  `algerian_wilayas`. When it is on, each Algerian commune sits under a wilaya of the same name, as
  Jijel does in the real catalogue.
  - Why: under the verified-wilaya rule, a parentless Algerian commune names nothing.
  - Who turns it on: the worlds whose payloads name places on cards, `DiscoveryWorld` and
    `FindTravelersFixture`. Every existing assertion there (`Algiers`, `Jijel`) keeps its value.
  - Why not everywhere: worlds that pin owner-screen and deal-route labels or query budgets keep
    `main`'s parentless fixture, so their figures are unchanged.
- In the K7-E world, the Algerian region is tagged `wilaya`.

### Rewritten

These are in `apps/matching/tests/test_phase_k7e_discovery_query_counts.py`:

- `test_find_travelers_cost_is_flat_from_n_to_2n_journeys`
- `test_compatible_requests_cost_is_flat_from_n_to_2n_requests`

What changed and why:

- They asserted `"<name> · Region XX"` on what are list surfaces. They now assert the city: French
  stops read `Paris`, and Algerian ones read the wilaya stand-in `Region DZ`. The compatible-requests
  read now calls `as_card_row()`, which is what the endpoint serves.
- The query counts and their equality assertions are unchanged.
- Reason: the owner's rule (fix plan P2, Q1).
- `test_compatible_journeys_cost_is_flat_from_n_to_2n_journeys` is back to its `main` assertion,
  because that payload is not a list surface.

## Second-pass review (Astra, at `cf5b585`)

Outcomes under the owner's rule:

| Finding | Outcome |
| --- | --- |
| Blocker 1: a preferred map point wins over the catalogue place on pre-funding endpoints | **Fixed for list rows.** `as_card_row` builds every endpoint and covered leg from the catalogue place when there is one, and the test attaches preferred points to both the request and the journey. **Not applicable** to the proposal and the quote: they feed the negotiation screen and the propose sheet, which are detail pages and keep `main`'s payload. |
| Blocker 2: journey and request detail serve the full label to non-owners | **Not applicable under the owner's rule.** Detail pages show the catalogue place. Unchanged from `main`, and pinned by `test_a_members_journey_detail_keeps_the_catalogue_place`. |
| Blocker 3: `name` beside a city `display_label`; the mobile decoder falls back to `name` | **Fixed for list rows.** `card_place` puts the city in `name` and `display_label`, and the walker checks the whole JSON text. The proposal summary, a detail page, is back to `main` (full in both fields), so no field disagrees. No app change was needed, because the app shows the label it is given. |
| Should-fix: staff explain and stored snapshots lost the full label; old snapshots copied verbatim | **Fixed.** `as_dict` and `_public_place_summary` are back to `display_label`, and the city is applied only when `as_card_row` projects a list row, from the leg's `Place`. Stored snapshots are read only by the negotiation detail, which keeps the full label, so no list row reads a stored snapshot. |
| Should-fix: schedule-change sender projection shows raw airport names | **Not applicable under the owner's rule.** The schedule-change view is a detail page. Unchanged. |
| Should-fix: ORY header + CDG leg query growth | **Fixed.** `_load_endpoint_mappings` batch-loads the headers, and a new 4 → 8 test pins it flat. Without the fix it measured 8 → 12. |
| Should-fix: proposal list cost 5 vs 3 queries | **Resolved by removal.** The proposal stays on the detail rule, so `_match_read_queryset` is back to `main` and the extra prefetches are gone. |
| Should-fix: Algeria without a verified wilaya; stop fallback on a catalogue stop | **Fixed.** Only a `wilaya` parent counts, otherwise the name is empty (tests cover a parentless commune and a daïra parent). `_stop` falls back to a legacy label only when the stop has no catalogue place. |
| Nit: German delimiter wording | **Fixed.** The docstring and docs state the split is on the first comma and name the one row without a space. |
| Nit: Spanish bilingual spelling | **Fixed.** The test uses the municipality's `Alacant/Alicante`. |

## Documentation

- `docs/GEOGRAPHY_CATALOGUE.md`: the "Public city names" section, with the owner's rule.
- `docs/WASSLA_DISCOVERY_PRO_SPEC.md` 4.2: the place-naming rule ("cards show cities; detail pages show
  the catalogue place; exact location after funding").
- `apps/admin_helper/skill/knowledge/trips-and-matching.md`: the rule in one line. `INSTRUCTIONS.txt` was
  regenerated.

## Deploy note

A server deploy alone shows the change on Ismail's current APK, because the app prints the server's
labels as they are. No app rebuild is needed.
