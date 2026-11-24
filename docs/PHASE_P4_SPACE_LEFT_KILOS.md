# P4: space left shows real kilos (2026-11-24)

Ismail's phone test, 2026-11-24: a trip card showed "10-20 kg left" and he asked why it does not
show the space left. Finding: the band was the design (spec 4.2), not a bug. Owner decision Q2: show
the real kilos. Nothing is deployed by this change.

## What changed

- `apps/discovery/listings.py`: `trip_card` publishes `free_weight_kg`, an integer: the smallest free
  weight on the legs still ahead, in whole kilos rounded down (0 means under one kilo). The
  `CAPACITY_*` constants and `capacity_band()` are removed, with no field kept beside the new one.
- Why the band's privacy reason no longer holds: the declared capacity per leg is already readable by
  any signed-in member through `GET /api/journeys/{id}`, and matching checks the real capacity on the
  server anyway.
- App: `CapacityBand` is gone from `lib/domain/public_discovery.dart`; `TripCard.freeWeightKg` is a
  nullable int (null when the server sent none, so no space line is drawn).
- The card reads "14 kg left" (`tripSpaceLeft`); the preview sheet keeps its "Space left" label and
  its value reads "14 kg" (`tripSpaceKg`), so "left" is never said twice. Under one kilo the card
  reads "Less than 1 kg left" and the sheet value "Less than 1 kg" (`tripSpaceLeftUnderOne`,
  `tripSpaceKgUnderOne`). The four `tripCapacity*` keys are removed.
- French: "Il reste 14 kg" / "14 kg" / "Moins de 1 kg". Arabic is Modern Standard Arabic, worded so
  that no number agreement is needed: "المساحة المتبقية: 14 كغ" / "14 كغ" / "أقل من 1 كغ".
- Docs: spec 4.2 (trip card line), the L-series board note, and the admin helper's note in
  `trips-and-matching.md`, with `INSTRUCTIONS.txt` regenerated.

## Tests

- Rewritten (reason: Ismail's decision Q2): in `apps/discovery/tests/test_listings.py`,
  `test_a_published_proven_journey_is_listed_with_its_card` (band `5_to_10kg` is now 8),
  `test_a_journey_with_a_full_leg_ahead_is_not_listed` (after a 2 kg reservation the card says 6) and
  `test_the_capacity_band_is_the_smallest_free_weight_ahead`, which became
  `test_the_free_weight_is_the_smallest_whole_kilo_ahead` (smallest leg decides, 7.99 rounds down to
  7, a leg that has already left is ignored). New: `test_under_one_kilo_free_is_published_as_zero`.
- Flutter: `test/p4_space_left_test.dart` (card and sheet in English, French and Arabic, 0 kg, no
  figure); `l2b_browse_test.dart` and `l2b_discovery_repository_test.dart` follow the new field;
  the shared `tripCardFixture` now carries `free_weight_kg`.
