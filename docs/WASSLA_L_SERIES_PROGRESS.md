# Wassla L-Series Progress

The shared record for every agent working on `feature/discovery-professional-delivery`.
Rules for this file: `docs/WASSLA_DISCOVERY_PRO_PLAN.md` section 1.8. In short:

- **Read this file first**, the board and every handoff block above your package.
- **The board is edited only by the orchestrator**, on the integration branch.
- **Each agent fills in only its own handoff block**, inside its own pull request.
- Statuses: `not_started`, `in_progress`, `in_review`, `changes_requested`, `merged`, `blocked`.

When Ismail says "start", the orchestrator follows plan section 1.0: resume anything unfinished,
otherwise take the first `not_started` package whose dependencies are all `merged`.

## Board

| Package | What | Model | Effort | Status | Branch | Pull request | Merge commit | Phase doc |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| L0 | Spec and plan | | | merged | | | see git log for `docs/WASSLA_DISCOVERY_PRO_PLAN.md` | |
| L1A | Backend cleanup, including Railway removal | Opus | high | merged | `claude/project-thread-po89ml` | #22 | `345849b` | `docs/PHASE_L1A_BACKEND_CLEANUP.md` |
| L1B | Mobile and docs cleanup | Sonnet | medium | merged | `claude/project-thread-y61pdg` | #23 | `ae412a3` | |
| L2A | Discovery backend and marketplace policy | Opus | high | merged | `claude/project-thread-jms2kh` | #24 | `46682bc` | `docs/PHASE_L2A_DISCOVERY_CONTRACT.md` |
| L2B | Discovery on Home (mobile) | Sonnet | high | not_started | | | | |
| L3A | Routes for everyone, backend | Opus | xhigh | not_started | | | | |
| L3B | Routes for everyone, mobile and admin screens | Sonnet | high | not_started | | | | |
| L4A | Traveler pricing, backend | Opus | high | not_started | | | | |
| L4B | Traveler pricing, mobile | Sonnet | medium | not_started | | | | |
| L5A | Progress updates and reminders, backend | Sonnet | medium | not_started | | | | |
| L5B | Progress updates and reminders, mobile | Sonnet | medium | not_started | | | | |
| L6A | Professional profile, verification, admin inbox, proof skip | Opus | high | not_started | | | | |
| L6B | Professional Mode, mobile | Sonnet | medium | not_started | | | | |
| L7A | Manifest, backend projections | Sonnet | medium | not_started | | | | |
| L7B | Manifest dashboard, mobile | Sonnet | high | not_started | | | | |
| L8A | Custody, courier handoff, recipient confirmation | Opus | xhigh | not_started | | | | |
| L8B | Custody and handoff, mobile | Sonnet | high | not_started | | | | |
| L9A | Problems and route changes, backend | Opus | high | not_started | | | | |
| L9B | Problems and route changes, mobile | Sonnet | medium | not_started | | | | |
| L10 | Final acceptance | Opus | high | not_started | | | | |

**Next package:** L2B (Sonnet, high). L3A (Opus, xhigh) is also unblocked; section 3 order puts L2B first.

**Carry-over:** `PushRepository.unregisterDevice` (mobile) has no caller. Sign-out should unregister the push installation, so whichever package touches sign-out or push wires it up (it was kept on purpose in L1B).

## Handoff notes

One block per package, written by that package's agent in its pull request. Keep each block short and
factual. Use exactly these headings.

### L1A. Backend cleanup, including Railway removal

- Contract as built (names that differ from the plan): no tombstones. Every removed route answers
  404, including the six paths the plan listed for 410. The Railway launcher is now `infra/vps/launcher.py` (`run()`, no `main()`), the internal
  gateway config `infra/vps/gateway.Caddyfile`, the Go entrypoint `backend/services/entrypoint.sh`.
  Legacy history admins use `apps/core/historical_admin.py` (view-only). Full list:
  `docs/WASSLA_L1_CLEANUP_INVENTORY.md`.
- Left for a later package: L1B removes the mobile `compatibleJourneys()` and `airports()`
  repository methods (no callers, routes now 404) and can drop the app's mapping of the six removed
  channel names (`trip.created`, `trip.updated`, `trip.cancelled`, `match.created`,
  `handover.confirmed`, `handover.code_issued`): Ismail confirmed there are no real users, so no
  stored inbox row carries them. It may also delete the client's handling of the retired refusal
  codes `legacy_matching_flow_retired`, `legacy_delivery_flow_retired`, `legacy_dzd_quote_retired`,
  `legacy_trip_flow_retired`, `legacy_trip_search_retired` and `legacy_payment_retired`: no server
  code sends them any more. Keep `product_request_retired`, `legacy_contract_not_supported` and
  `airport_filter_retired`: live server code still sends them.
  `journeys/search` and open-requests stay until L2B. Ismail answered the three open questions (no
  real users, no legacy data): `infra/vps/MIGRATION.md` is deleted. Legacy tables and the
  `schema_version` 1/2 branches stay because removing them needs a narrowing migration (rule 1.5.5);
  inventory section 3 lists them as a follow-up candidate.
- Switches added and their defaults: none. Removed: `SHIPTRIP_EMBEDDED_REDIS`,
  `PAYMENTS_MOCK_WEBHOOK_ENABLED`, `PAYMENTS_LEGACY_MUTATIONS_ENABLED` (no reader left).
- Deviations from the plan (what, why, approved by): branch is `claude/project-thread-po89ml`, not
  an `l/l1a-...` name, because the session's harness fixes the branch (not approved by Ismail; the
  PR target is still `feature/discovery-professional-delivery`). `apps/matching/views.py` cancel,
  decline and withdraw now lock with `select_for_update(no_key=True)` and the module joined the
  lock-order gate; the gate's stated reason for leaving it out was the legacy classes L1A deleted.
  Lock strength only, no result change; accepted by the orchestrator. The plan's 410 tombstone
  module was built and then removed: Ismail confirmed the app was never released and has no real
  users, and the orchestrator asked for 404 on all six paths. Legacy admins made
  view-only and the withdrawal "mark sent" action removed (plan: admin registrations for removed
  surfaces are in scope; the tables stay readable).
- Tests (before and after counts): Django 2,529 passed / 34 skipped (2,563) before;
  2,438 passed / 0 skipped after (138 IDs removed, of which 34 were skipped and 5 are renames; 13 added).
  Go 199 top-level tests before and after. VPS unit 29 before and after. Removed tests are listed in
  inventory section 1.10.
- Known limits: Flutter could not run in this environment (CI runs it; only two Dart test fixture
  strings changed). The VPS image build and all nine container integration groups passed locally.

### L1B. Mobile and docs cleanup

- Contract as built (names that differ from the plan): no contract change. Removed from the client:
  `compatibleJourneys()`, `airports()`, `Airport`, `uploadPhoto`, `cancelMatch`, `unreadActiveCount`,
  `retiredHistory`, the six removed channel names (including the `NotificationChannel` values
  `matchCreated`, `tripCreated`, `tripUpdated`, `tripCancelled`, `handoverConfirmed`), the six retired
  refusal codes, `wilayas.dart`, ~45 unused getters/helpers and 202 unused ARB keys (EN, AR, FR).
  The full list is `docs/WASSLA_L1_CLEANUP_INVENTORY.md` section 4.
- Left for a later package: `JourneyRepository.searchPage` and `RequestRepository`/`MatchingRepository`
  `openFeedPage` stay until L2B replaces them (plan). `PushRepository.unregisterDevice` has no caller;
  sign-out ought to unregister the push installation, so whichever package touches sign-out/push
  should wire it (not deleted on purpose). Later packages re-add ARB keys they need.
- Switches added and their defaults: none.
- Deviations from the plan (what, why, approved by): branch is the harness name
  `claude/project-thread-y61pdg`; PR targets `feature/discovery-professional-delivery`. Four test
  fixtures moved off removed channel/code names. Chat controller's write-only `_backgroundError` field
  was removed with its unused getter (the failure path still swallows the error, as before).
- Tests (before and after counts): Flutter 1,079 passed before, 1,083 after (4 added in
  `legacy_removal_test.dart`). `flutter analyze --fatal-infos` clean before and after. No golden
  file changed.
- Known limits: no screenshots taken (no visual change, and no widget touched). The unused-member
  sweep is name-based, so a member used only through dynamic access would be missed; analyze and the
  suite found none.

### L2A. Discovery backend and marketplace policy

- Contract as built (names that differ from the plan): `docs/PHASE_L2A_DISCOVERY_CONTRACT.md`.
  Usual routes are a child table `PublicProfileRoute` (max 3, position kept) rather than a field, so
  each end is a foreign key to a catalogue locality. The profile's public id is a uuid
  (`PublicProfile.public_id`). `role` on People is the viewer's role (a sender sees travelers). Place
  filters accept any place id, including an airport, and resolve it to its matching locality. The trip
  card's `capacity_band` (`under_5kg`, `5_to_10kg`, `10_to_20kg`, `20kg_plus`) is the smallest free
  weight across the legs still ahead; the spec's "existing public band" did not exist, and a journey
  with a full leg ahead is not listed. The fan-out uses a `ScheduledJob` kind
  `discovery_route_alerts` (choices-only migration `finance/0027`). `trust_signals(user_ids, side=)`
  replaces `traveler_trust_signals` in `apps/matching/find_travelers.py` (same J4 result for travelers).
- Left for a later package: L2B removes the mobile `searchPage`/`openFeedPage` callers of the two
  removed endpoints and the client's handling of `airport_filter_retired` (no server code sends it
  now), and maps `discovery.route_alert` and `discovery.traveler_interested`. L3A moves the
  "flight leg needs an approved ticket" check in `apps/discovery/listings.py:listable_journeys` into
  `proofs.py` (it then covers sea legs) and adds "not paused" to the listing and to
  `matches.traveler_matches`; if pause must re-notify alerts on resume, the job key needs a suffix.
  L4A adds the listed price to the trip card; L6A adds the pro badge and business name.
- Switches added and their defaults: the whole `marketplace` section of spec 2.1 (defaults in the
  contract, section 1); L2A reads `discovery.listings_enabled` (on), `discovery.profiles_enabled` (on)
  and `discovery.interest_daily_cap` (10).
- Deviations from the plan (what, why, approved by): branch is the harness name
  `claude/project-thread-jms2kh`; PR targets `feature/discovery-professional-delivery`. The interest
  cap is a rolling 24 hours and answers 429 (no calendar day is fair across Paris and Algiers). An
  opted-out or hidden member is absent from People, the person page and person alerts, while their
  published trips and requests stay in Listings (spec 4.3: the profile is opt-in, listings are not); a
  banned member is absent everywhere. Discovery reuses the `matching_discovery` throttle scope, so no
  new setting. Reported to the orchestrator with the PR; not reviewed by Ismail.
- Tests (before and after counts): Django 2,438 passed / 0 skipped before; 2,539 passed / 0 skipped
  after (13 removed with the two endpoints; 114 added: 113 in `apps/discovery/tests`, 1 in
  `apps/parcels`; the posting-deposit and J6.4 person-page tests gained assertions for the fan-out
  job and the Discovery tab). Go unchanged and green (`go test -race ./...`).
- Known limits: Matches costs 11 queries per group and has at most 3 groups (bounded, not flat in
  groups). No mobile change in this package, so nothing on Home uses these endpoints until L2B.

### L2B. Discovery on Home (mobile)

- Contract as built (names that differ from the plan): `docs/PHASE_L2B_DISCOVERY_HOME.md`. Routes
  `/discover/trips`, `/discover/requests`, `/discover/people[/:id]`, `/profile/public`,
  `/profile/alerts`; a Browse link takes `from`/`to` (a launch corridor), `alert` and `focus`. The
  traveler-interested push and inbox row open `/requests/<id>/discovery?journey=<jid>`. Domain models
  in `lib/domain/public_discovery.dart`, calls in `lib/data/discovery_repository.dart`, state in
  `lib/app/discovery_state.dart`. Removed: `searchPage`, `openFeedPage`, `JourneySearchPage`,
  `OpenRequestPage`, `discoveryPageSize`, the `airport_filter_retired` handling, and
  `PushRepository.unregisterDevice`.
- Left for a later package: L3B adds sea legs to the trip card (mode icons already come from the
  card's `legs`); L4B adds the listed price to the trip card and preview; L6B the pro badge and business
  name.
- Switches added and their defaults: none. Tier switches are read from the server's `state`.
- Deviations from the plan (what, why, approved by): carry-over `unregisterDevice` was removed rather
  than wired: sign-out already unregisters server-side, so a client call would be a second, failing
  path after the token is gone. Home pull-to-refresh now uses always-scrollable physics so it works on a
  quiet Home. Role-switcher label ellipsises (a 5.9px overflow at 360px). Profile rows with a value
  (language, appearance) share the row 3:2 and wrap instead of overflowing at 320dp and 1.6x text
  (existing code, fixed at the coordinator's request). Reported to the orchestrator
  with the PR; not reviewed by Ismail.
- Judgment calls: corridor chips are the six launch pairs between France, Spain, Germany and Algeria;
  the People row is unfiltered and titled by the viewer's role; previews are bottom sheets; an alert
  deep link resolves through the alerts list plus Browse focus (there is no single-item endpoint);
  focus on Find Travelers pages client-side and quotes for the server's reason; "I can carry this" is
  on a matched traveler card and its preview; a per-usual-route alert switch on the person page; the
  opt-in card hides silently if its read fails; sections follow the member's own content; "See all"
  reused instead of a new label; dates in Arabic use the app's existing formatter (Arabic-Indic digits
  in dates, Latin digits in counts and money), unchanged.
- Tests (before and after counts): Flutter 1,087 passed before, 1,303 after (`k6_discovery_paging_test`
  replaced; eight new `l2b_*` suites). Analyzer clean with `--fatal-infos`.
- Known limits: Home reads Matches at cold start (one request, in the 8-request budget); the trips,
  people and opt-in reads wait until scrolled near. Gate screenshots are rendered from the widget tree
  with the real fonts (EN and AR, 360px), not a device.

### L3A. Routes for everyone, backend

- Contract as built (names that differ from the plan):
- Left for a later package:
- Switches added and their defaults:
- Deviations from the plan (what, why, approved by):
- Tests (before and after counts):
- Known limits:

### L3B. Routes for everyone, mobile and admin screens

- Contract as built (names that differ from the plan):
- Left for a later package:
- Switches added and their defaults:
- Deviations from the plan (what, why, approved by):
- Tests (before and after counts):
- Known limits:

### L4A. Traveler pricing, backend

- Contract as built (names that differ from the plan):
- Left for a later package:
- Switches added and their defaults:
- Deviations from the plan (what, why, approved by):
- Tests (before and after counts):
- Known limits:

### L4B. Traveler pricing, mobile

- Contract as built (names that differ from the plan):
- Left for a later package:
- Switches added and their defaults:
- Deviations from the plan (what, why, approved by):
- Tests (before and after counts):
- Known limits:

### L5A. Progress updates and reminders, backend

- Contract as built (names that differ from the plan):
- Left for a later package:
- Switches added and their defaults:
- Deviations from the plan (what, why, approved by):
- Tests (before and after counts):
- Known limits:

### L5B. Progress updates and reminders, mobile

- Contract as built (names that differ from the plan):
- Left for a later package:
- Switches added and their defaults:
- Deviations from the plan (what, why, approved by):
- Tests (before and after counts):
- Known limits:

### L6A. Professional profile, verification, admin inbox, proof skip

- Contract as built (names that differ from the plan):
- Left for a later package:
- Switches added and their defaults:
- Deviations from the plan (what, why, approved by):
- Tests (before and after counts):
- Known limits:

### L6B. Professional Mode, mobile

- Contract as built (names that differ from the plan):
- Left for a later package:
- Switches added and their defaults:
- Deviations from the plan (what, why, approved by):
- Tests (before and after counts):
- Known limits:

### L7A. Manifest, backend projections

- Contract as built (names that differ from the plan):
- Left for a later package:
- Switches added and their defaults:
- Deviations from the plan (what, why, approved by):
- Tests (before and after counts):
- Known limits:

### L7B. Manifest dashboard, mobile

- Contract as built (names that differ from the plan):
- Left for a later package:
- Switches added and their defaults:
- Deviations from the plan (what, why, approved by):
- Tests (before and after counts):
- Known limits:

### L8A. Custody, courier handoff, recipient confirmation

- Contract as built (names that differ from the plan):
- Left for a later package:
- Switches added and their defaults:
- Deviations from the plan (what, why, approved by):
- Tests (before and after counts):
- Known limits:

### L8B. Custody and handoff, mobile

- Contract as built (names that differ from the plan):
- Left for a later package:
- Switches added and their defaults:
- Deviations from the plan (what, why, approved by):
- Tests (before and after counts):
- Known limits:

### L9A. Problems and route changes, backend

- Contract as built (names that differ from the plan):
- Left for a later package:
- Switches added and their defaults:
- Deviations from the plan (what, why, approved by):
- Tests (before and after counts):
- Known limits:

### L9B. Problems and route changes, mobile

- Contract as built (names that differ from the plan):
- Left for a later package:
- Switches added and their defaults:
- Deviations from the plan (what, why, approved by):
- Tests (before and after counts):
- Known limits:

### L10. Final acceptance

- Contract as built (names that differ from the plan):
- Left for a later package:
- Switches added and their defaults:
- Deviations from the plan (what, why, approved by):
- Tests (before and after counts):
- Known limits:

## Questions for Ismail

| Asked | Question | Answer |
| --- | --- | --- |
| 2026-11-11 | Which sea crossings? | Research the popular routes and add them. Done: spec 5.3.1. |
| 2026-11-11 | Remove Railway files? | Yes. They do not stay on this branch. In L1A. |
| 2026-11-11 | Is a declined schedule change a traveler-caused cancellation? | Yes. |
| 2026-11-11 | Keep "I can carry this"? | Yes. |

## Change log for the plan and spec

| Date | Change |
| --- | --- |
| 2026-11-10 | Spec and plan first written. |
| 2026-11-11 | Added effort per package, the start runbook (plan 1.0), this progress file (plan 1.8), the agent brief (plan 1.9), the researched sea crossings (spec 5.3.1), Railway removal in L1A, and Ismail's answers. |
