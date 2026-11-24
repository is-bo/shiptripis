# P2: cities, not catalogue labels, on public and pre-funding route lines (2026-11-24)

Ismail's phone test of 2026-11-24: "The route should only show the cities ('Alger Paris', not 'Alger
Centre Alger Paris Paris')". Fix plan of 2026-11-24, package P2; owner decision Q1 = the wilaya.
Server only: no migration, no app change, no new wording. Nothing is deployed by this change.

## Cause

Every public route label was the catalogue's `Place.display_label`, `"<name> · <parent name>"`, and
a commune's parent is an administrative area, not a city: `Alger Centre · Alger`, `Paris · Paris`,
`Berlin, Stadt · Berlin, Stadt`. Both public builders used it (`apps/discovery/places.py`
`locality_block` and `apps/matching/find_travelers.py` `_stop`), and so did the `display_label` of
the place summaries a counterparty reads before funding.

## The rule

One function, `apps/locations/city_names.py` `city_name(place)`, the only home of the rule:

- **Algeria:** the wilaya, which is the commune's parent (`Alger Centre`, `Bab Ezzouar` → `Alger`;
  `Tamanghasset` → `Tamanrasset`).
- **Germany:** the name before the first comma (`Berlin, Stadt` → `Berlin`,
  `München, Landeshauptstadt` → `München`, `Halle (Saale), Stadt` → `Halle (Saale)`,
  `Erkrath, Fundort des Neanderthalers, Stadt` → `Erkrath`).
- **Spain:** a postposed article moves to the front, part by part around the slash of a bilingual
  name (`Coruña, A` → `A Coruña`, `Palmas de Gran Canaria, Las` → `Las Palmas de Gran Canaria`,
  `Alfàs del Pi, l'` → `l'Alfàs del Pi`, `Vila Joiosa, la/Villajoyosa` →
  `la Vila Joiosa/Villajoyosa`). `Alicante/Alacant` is unchanged.
- **France and anywhere else:** the commune's own name (`Paris`, `Lyon`).
- **An airport** reads as the city it serves. An unmapped airport names nothing (fails closed).

Run over the whole 2026 manifest, every one of the 55,297 localities gets a non-empty name. Two
details found on the way:

- Germany splits on the first comma, not on `", "`: one Destatis row is written without the space
  (`Ebstorf,Klosterflecken`).
- Spain moves only a closed set of articles (`El La Los Las el la les els Les Els L' l' A O As Os Es
  Sa Ses`, every form INE uses). Three INE names contain a real comma that is not an article
  (`Castell d'Aro, Platja d'Aro i s'Agaró`, `Cruïlles, Monells i Sant Sadurní de l'Heura`,
  `Saus, Camallera i Llampaies`); they stay whole.

## Where it applies

- `locality_block` `label`: request cards, Matches for you, usual routes on profile cards, the person
  page and the own profile preview, route alerts.
- Find Travelers and trip-card stops (`_stop` `label`); the IATA code still rides beside the city
  (`Alger` · `ALG`).
- `display_label` of the pre-funding counterparty summaries: compatible requests and journeys
  (`apps/matching/discovery.py`, both `place_summary` helpers), covered legs
  (`compatibility.py` `_public_place_summary`) and proposal origin and destination
  (`serializers.py`, now one `_proposal_place` helper instead of two copies).

The catalogue id stays in every payload (`place_id`, `matching_locality_id`): filters, the "post for
this route" pre-fill and matching identity need it. A trip card's pre-fill therefore shows "Alger"
and posts for Alger Centre, which is correct for matching.

Unchanged, on purpose: the staff console (`ops_serializers.py`, `console_discovery.py`), the place
picker (`geography_serializers.py`), the owner's own journey and request payloads
(`trips/serializers.py`, `parcels/serializers.py`) and the funded deal's route (`deals/route.py`).
`Place.display_label` itself is unchanged. Proposal snapshots written before the deploy keep their
old label; there are no real users, so no backfill.

No matching result changes: `city_name` only reads names. The matching code paths touched are the
three summary builders, the label line in `_stop`, and two fallback reads that now also join the
locality's parent (`Place.resolve_matching_locality` and `find_travelers._locality_of`,
`select_related("locality__parent")`).

## Query counts

`city_name` reads the place's parent (Algeria) and, for an airport, its served locality and that
locality's parent. Every public queryset already loads both (`_place_matching_prefetches` selects
`locality__parent`; the discovery querysets select `__parent`). One was missing: the proposal read
queryset (`apps/matching/views.py` `_match_read_queryset`) now selects
`pickup_place__parent`/`delivery_place__parent` and prefetches the served mappings, so a proposal list
with airport pickups costs no query per row (`test_the_trimmed_list_costs_no_extra_queries` still
holds at 4 or fewer).

## Tests

Added:

- `apps/locations/tests/test_city_names.py`: the rule on catalogue-shaped rows (every example above,
  the bilingual and real-comma Spanish names, `Ebstorf,Klosterflecken`), ALG → `Alger`, BER →
  `Berlin`, an unmapped airport → empty, no query when the parent and mapping are loaded, and
  `display_label` unchanged.
- `apps/discovery/tests/test_city_names.py`: on the canonical world given catalogue names and parents
  (`support.give_catalogue_names`), as guest and as member: an ALG → CDG journey card reads
  `["Alger", "Paris"]`, trips, requests, people, the person page, the own profile preview, route
  alerts and Matches name only `Alger`, `Paris` and `Jijel`; Find Travelers stops read
  `("Paris", "CDG"), ("Alger", "ALG"), ("Jijel", None)`; compatible requests and a proposal (detail
  and list) carry the city in `display_label`; the owner's journey detail, the place picker and the
  staff request serializer still read `Alger Centre · Alger` and `Paris · Paris`.
- `apps/discovery/tests/test_privacy.py`: the privacy world now has catalogue parents (with a
  distinctive department name), and every walk also checks that no public stop label contains
  ` · `, every label is one of the three cities, and no department, the commune behind the wilaya or
  an airport's own name appears anywhere.

The new discovery and privacy tests fail when the two builders are switched back to
`display_label` (12 failures), and pass with the rule.

Rewritten: `apps/matching/tests/test_phase_k7e_discovery_query_counts.py`. Three tests asserted the
old `"<name> · Region XX"` label as proof that the parent was still read:
`test_find_travelers_cost_is_flat_from_n_to_2n_journeys`,
`test_compatible_journeys_cost_is_flat_from_n_to_2n_journeys` and
`test_compatible_requests_cost_is_flat_from_n_to_2n_requests`. They now assert the city rule: French
stops read `Paris` and the Algerian ones read the parent (`Region DZ`, standing in for the wilaya), so
the parent join is still exercised on every Algerian stop. Query counts and their assertions are
unchanged. Reason: the label rule changed by owner decision (fix plan P2, Q1).

## Documentation

- `docs/GEOGRAPHY_CATALOGUE.md`: a "Public city names" section.
- `docs/WASSLA_DISCOVERY_PRO_SPEC.md` 4.2: trip-card stops are city names, rule in `city_names.py`.
- `apps/admin_helper/skill/knowledge/trips-and-matching.md`: the rule in one line;
  `INSTRUCTIONS.txt` regenerated with `python manage.py build_helper_instructions`.

## Deploy note

A server deploy alone shows the change on Ismail's current APK: the app prints the server's label as
it is. No app rebuild.
