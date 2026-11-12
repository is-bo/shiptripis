# Phase L2B: Discovery on Home (mobile)

Package L2B of the Wassla L-series. It puts the L2A discovery backend
(`docs/PHASE_L2A_DISCOVERY_CONTRACT.md`) on the phone. The server decides who and what is shown; the
client renders each card as it comes and never ranks, filters or matches on its own.

## What members get

| Where | What |
| --- | --- |
| Home, below the member's own content | **Matches for you** (a sender sees travelers for their open requests, a traveler sees parcels for their trips, at most 3 groups), a one-time **Be found on Wassla** card, **Trips leaving soon** or **Parcels looking for a traveler** with corridor chips, and a **People** row. |
| Browse trips, Browse requests, People | From, to and date filters, lazy paging on the server's `next_offset` only, a preview sheet with the spec 4.4 actions, and "I can carry this" on a matched card. |
| Person page | First name, trust summary, usual routes with an alert switch each, live trips or open parcels. No message button: chat begins inside a match. |
| Profile, Public profile | The opt-in switch, what is and is never shown, up to three usual routes, and the exact card others would see. Off by default. |
| Profile, Route alerts | List, add (trips or parcels, two cities) and remove. A followed person shows with their name. |
| Bell and push | `discovery.route_alert` opens Browse on the alert with the trip or request in focus; `discovery.traveler_interested` opens Find Travelers on that request with the trip in focus. |

## States

Every section reads on its own and shows skeleton, empty (with the next step), error (with retry) or
data. A section the server answers with `state: "disabled"` is absent (Listings) or a calm empty page
(Person, Public profile). Pull-to-refresh on Home re-reads every section. A section far below the
fold is not read until it is near the screen, so a cold start to Home still costs 7 requests (budget
8): the discovery reads that run at cold start are the matches only, asserted in
`test/k5_request_budget_test.dart`.

## Code map (all under `mobile/`)

- `lib/domain/public_discovery.dart`: the card and page models (allowlisted fields only).
- `lib/data/discovery_repository.dart`: the nine discovery calls.
- `lib/app/discovery_state.dart`: providers, paging `FeedController`, `OwnProfileController`,
  `AccountScopedValue.ofCurrentAccount`, `refreshDiscovery`.
- `lib/features/home/discovery_sections.dart`: the four Home sections.
- `lib/features/discovery/`: Browse, Person, Public profile, Alerts, previews and "I can carry this".
- `lib/features/common/traveler_candidate_card.dart`: the candidate card shared with Find Travelers.
- `lib/app/router.dart`: `/discover/trips|requests|people[/:id]`, `/profile/public`, `/profile/alerts`
  and the navigation helpers; a Browse link may carry a launch `from`/`to` corridor.

## Account isolation

A card read for one member is never shown to the next. Every discovery provider is keyed on the
signed-in account and answers "signed out" without a request when there is none; Riverpod keeps the
previous value while a dependency-driven rebuild loads, so screens read it through
`ofCurrentAccount`, which hides a value that belongs to the previous account.

## Removed

`JourneyRepository.searchPage`, `ParcelRepository.openFeedPage`, their page models and
`discoveryPageSize` (the two endpoints were removed in L2A), the client's handling of
`airport_filter_retired`, `PushRepository.unregisterDevice` (see the report: the server already
unregisters on sign-out), and `test/k6_discovery_paging_test.dart` (replaced by
`test/l2b_browse_test.dart`).

## Checks

`flutter analyze --no-pub --fatal-infos` clean. `flutter test`: 1,299 passed. New suites:
`l2b_discovery_repository_test`, `l2b_discovery_state_test`, `l2b_home_discovery_test`,
`l2b_browse_test`, `l2b_person_profile_alerts_test`, `l2b_deep_links_test`, `l2b_layout_test` (every
discovery screen on every device profile in English and Arabic: no overflow, last row clear of the
bottom), `l2b_localisation_test` (key parity, placeholders, nothing in English, `l10n_untranslated.json`
empty). Gate screenshots (360px, English and Arabic): `l2b-screenshots/` in the project Library.
