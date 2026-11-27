# Brief MC: remove unused code in the app

**Builder:** Claude Opus, high effort.
**Branch:** new, from the tip of `main`, after the last app feature of `HANDOFF.md` 0.4 has
merged (P3B, F2, M2, A1, M3), so that the sweep runs once.
**Read first:** `CLAUDE.md`, the mobile rules included; `docs/handoff/builders/README.md`; the
plan (`docs/handoff/LOOP_END_PLAN.md`) sections 3.5 and 7.2;
`docs/WASSLA_L1_CLEANUP_INVENTORY.md` section 4, which is the method you repeat.

## 1. Your job

Remove what the app no longer uses: handling of old server shapes, members nothing reads, and
translation keys nothing shows. No screen and no behaviour changes.

## 2. Candidates (the planner's scan of `main` at `b4b838f`)

Paths are under `mobile/lib/`. About 40 lines carry a "legacy" marker:

- `domain/offer.dart` (7), `domain/deal.dart` (6), `features/deals/delivery_screen.dart` (5),
  `core/api/error_codes.dart` (3), and single lines elsewhere.
- `core/session/token_store.dart` had 5; S1 replaced that file.
- The refusal codes kept by package L1B: `product_request_retired`,
  `legacy_contract_not_supported`, `airport_filter_retired`. L2 and L3 removed their server
  side.
- Fields the server stopped sending in L2 and L3 (`legacy_trip_id`, `schema_version`,
  `is_legacy`): the lead gives you the lists from those pull requests.

No Dart file is unimported.

## 3. How

1. For each "legacy" marker: find what the server sends today (the serializer on `main`). Code
   that handles a shape the server cannot send goes. Code that handles a shape the server still
   sends is not legacy: correct the comment and keep the code.
2. **Identifier sweep**, as L1B did: a public member whose name occurs once in `lib` and nowhere
   in `test` is dead. Check framework overrides and generated code by hand.
3. **Translation keys:** every key of `app_en.arb` is searched in `lib` and `test`. An unused
   key leaves all three files (`app_en.arb`, `app_fr.arb`, `app_ar.arb`) together, and the
   generated localisations are regenerated.
4. `flutter analyze --fatal-infos` after each step.
5. `PushRepository.unregisterDevice` was kept in L1B as a gap. After N1 and S1, either something
   calls it or it goes.

## 4. What is not yours

Large screens are not split (plan section 7.5). No visual change. No change to the session core
or the member boundary.

## 5. Proof

- The whole app suite is green and the Android build is green in CI.
- The three translation files have the same keys.
- For each removed handler of a server shape: the serializer line that shows the server cannot
  send it.

## 6. Done when

1. The pull request lists what was removed: members, files, translation keys, with the count.
2. The status entry is written. A phase document is not needed.
3. Every CI check is green.
