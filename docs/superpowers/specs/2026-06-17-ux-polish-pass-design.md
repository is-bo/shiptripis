# UX Polish Pass — Design

**Date:** 2026-06-17
**Owner:** Claude A (Django + mobile)
**Status:** Approved design → ready for implementation plan

## Context

The previous Claude-A session left `TASKS.md` listing six "Soon" UX items. Reading
the current code (per CLAUDE.md §9 "read code, don't guess") shows the task board
is **stale** — most of those items were already built. This pass closes only the
genuine remaining gaps, verified against the code on 2026-06-17.

### Reconciliation: TASKS.md claim vs. actual code state

| TASKS.md item | Code reality | Real remaining gap |
|---|---|---|
| #1 Notifications polish (badge / clear error / spinner) | Header unread pill, `error: null` on refresh, and `RefreshIndicator` spinner all already present (`notifications_screen.dart`, `notifications_providers.dart`) | **Only** the bottom-nav tab badge is missing |
| #3 WS-driven live offer updates + pull-to-refresh | `live_event_router.dart:177-186` already invalidates `matchDetailProvider` + `offerListProvider` on `offer.created/updated/accepted` | **Only** pull-to-refresh on `match_detail_screen` |
| #4 Post-apply refresh | `matchDetailProvider`/`offerListProvider` are `autoDispose.family` → refetch on navigation | Verify only; likely already correct |
| #6 Sender counter-offer UI | **Already built** — `_doCounter` gated on `targetTravelerId != null` (`match_detail_screen.dart:82,211,250-313`), matches the "only when sender targeted a specific traveler" rule | **None** — do not rebuild |
| #5 Role hydration race | `role_provider.dart:16-25` returns `sender`, then async-hydrates the saved role | Real — boot-time gate |
| #2 Real traveler names | `MatchSerializer` carries no name; `User.full_name` exists; 4 mobile sites render `Traveler #<id>` | Real — backend serializer + mobile model + 4 render sites |

**In scope for this pass (the real gaps):**
1. Bottom-nav unread badge on the notifications tab
2. Pull-to-refresh on `match_detail_screen` (+ confirm post-apply refresh works)
3. Real full names on traveler/offer cards (Django serializer + mobile)
4. Role-hydration boot gate (no first-frame role flip for "both" users)

**Explicitly NOT in scope:** counter-offer UI (#6, done), in-screen notification
polish (#1, done), WS offer invalidation (#3, done). Chat and KYC are separate
workstreams with their own specs.

---

## 1. Bottom-nav unread badge

**Goal:** Show an unread count on the notifications icon (nav index 2) in
`_BottomNav` so users see pending items without opening the tab.

**Current state:** `app_shell.dart:305-385` `_BottomNav` is a `StatelessWidget`
rendering four plain icons. The unread count already lives in
`notificationsNotifierProvider` → `NotificationsState.unreadCount`, kept fresh by
WS prepends and `refresh()`.

**Design:**
- Convert `_BottomNav` to a `ConsumerWidget` (or wrap the notifications icon in a
  small `Consumer`) so it can `ref.watch(notificationsNotifierProvider
  .select((s) => s.unreadCount))`. Use `.select` so the nav only rebuilds when the
  count changes, not on every notification-state mutation.
- Render a badge **only on the notifications icon (index 2)** and **only when the
  tab is not selected** and count > 0 (a badge on the screen you're already
  looking at is noise). When count > 9, show `9+`.
- Visual: a small terracotta dot/pill at the top-right of the icon, consistent
  with the existing terracotta unread treatment (`notifications_screen.dart:57`,
  `_InboxTile` unread dot at `:287`). Respect the bottom-nav rule in CLAUDE.md §7
  (white pill, sun-yellow selected accent) — the badge is an additive overlay, it
  must not change the selected-icon styling.
- Implementation: wrap the notification `Icon` in a `Stack` with a `Positioned`
  badge. Keep it inside the existing `AnimatedContainer` cell so layout is unchanged.

**Boundary:** Pure read of existing provider state; no new state, no API. One file:
`app_shell.dart`.

**Done when:** posting a new offer (which prepends an unread item via WS) bumps the
badge while on the Home tab; opening Notifications and reading clears it; selecting
the Notifications tab hides the badge.

---

## 2. Pull-to-refresh on match_detail_screen

**Goal:** Let users manually refresh the negotiation screen; confirm the offer list
is fresh after a traveler applies.

**Current state:** `match_detail_screen.dart:213` body is a bare `ListView`. WS
events already invalidate the providers live (`live_event_router.dart`), and
`_refreshAll()` (`:104-108`) invalidates detail + offers + chat-eligibility on every
user action. There is no swipe-to-refresh affordance.

**Design:**
- Wrap the `data:` branch's `ListView` in a `RefreshIndicator` whose `onRefresh`
  invalidates the three providers and awaits their re-fetch, so the spinner shows
  until data actually returns. `_refreshAll()` is fire-and-forget (returns void);
  add an `async` variant `_refreshAndWait()` that invalidates then
  `await ref.read(matchDetailProvider(id).future)` + `offerListProvider(id).future`
  so `RefreshIndicator` dismisses on completion, not instantly.
- Use `color: AppColors.ink` to match the notifications screen's indicator.
- The `ListView` already exists; just ensure `physics:
  AlwaysScrollableScrollPhysics()` so pull works even when content is short.
- **Post-apply (#4) verification:** `match_detail` is reached via `context.push`
  after a traveler applies. Because `matchDetailProvider`/`offerListProvider` are
  `autoDispose.family`, navigating in performs a fresh fetch — the new offer should
  already appear. We will verify by tracing `find_parcels_screen` → apply → push,
  and only add a mount-time `ref.invalidate` if a stale cache is observed. No
  speculative code.

**Boundary:** One screen file (`match_detail_screen.dart`), plus the verification
trace. No backend, no provider signature change.

**Done when:** swiping down on the negotiation screen refetches and the spinner
holds until data returns; applying to a parcel then landing on match detail shows
the offer without a manual back-and-forth.

---

## 3. Real full names on traveler/offer cards

**Goal:** Replace `Traveler #<id>` with the counterparty's real name. Per decision:
show **full name** (`User.full_name`), falling back to `Traveler #<id>` only if
`full_name` is empty (defensive against unset names — cheap and avoids a blank).

**Current state:**
- Django: `MatchSerializer` (`apps/matching/serializers.py`) exposes
  `sender_id`/`traveler_id` but no names. `User.full_name` exists
  (`apps/accounts/models.py:21`).
- Mobile: `MatchSummary` (`matching_repository.dart:163-208`) carries ids only.
  Four sites render `Traveler #<id>`: `find_travelers_screen.dart:183`,
  `follow_package_screen.dart:190`, `request_detail_screen.dart:398` and `:667`.
  Note `find_travelers` renders from a **Trip** (`trip.travelerId`), not a Match —
  see below.

**Design — Django:**
- Add two read-only `SerializerMethodField`s to `MatchSerializer`: `sender_name`
  and `traveler_name`, each returning `obj.sender.full_name` / `obj.traveler.full_name`.
- **N+1 guard:** the match list/detail querysets must `select_related("sender",
  "traveler")` so adding names doesn't introduce a per-row query. Check
  `apps/matching/views.py` querysets and add `select_related` if missing. This is
  required, not optional — the matching list can return many rows.
- No migration (read-only derived fields). No schema.sql change. Not a Go-read
  table, so no Claude-B coordination needed.
- Add/extend a serializer test asserting `sender_name`/`traveler_name` appear and
  match `full_name`.

**Design — mobile:**
- `MatchSummary`: add `final String? senderName;` and `final String? travelerName;`,
  parsed from `j['sender_name']`/`j['traveler_name']` (nullable-safe).
- Add a tiny presentation helper, e.g. `String travelerLabel()` returning
  `travelerName?.trim().isNotEmpty == true ? travelerName! : 'Traveler #$travelerId'`
  (and a `senderLabel()` symmetric form). Keeps the fallback in one place.
- Update the 4 render sites to use the label.
- **`find_travelers_screen.dart:183` is the exception:** it renders a `Trip`'s
  `travelerId`, not a `MatchSummary`. To show a real name there, the **trip**
  serializer/model on the mobile side must carry `traveler_name`. Scope decision
  for the plan: either (a) extend the trip serializer the same way (preferred for
  consistency — senders browsing trips see real names), or (b) leave that one site
  as `#id` and note it. Recommendation: do (a) if the trip serializer is a
  low-risk add; the plan will confirm by reading the trip serializer/queryset.

**Boundary:** Django `matching` (and possibly `trips`) serializer + view querysets;
mobile `MatchSummary` model + 4 widget sites. Well-isolated; the label helper is the
single source of fallback truth.

**Done when:** offer/traveler/match cards show the real name; users with an empty
`full_name` still render `Traveler #<id>`; `flutter analyze` clean; Django matching
tests green including the new name assertion; no N+1 (verified by query count or
`select_related` presence).

---

## 4. Role-hydration boot gate

**Goal:** "Both"-role users must never see a first frame painted in the wrong role.

**Current state:** `RoleNotifier.build()` (`role_provider.dart:16-25`) returns
`AppRole.sender` immediately, then `_hydrate()` async-reads the saved role from
secure storage and flips state. For a `both` user who last used Traveler, the shell
can paint Sender for a frame, then flip. `effectiveRoleProvider` only defers to the
toggle for `both` users (pure roles are server-locked, unaffected).

The app has **no dedicated splash**: during `bootstrap()` the user sits on `/`
(onboarding) until `AuthSignedIn` flips and the shell mounts at `/app`. `bootstrap()`
already awaits a network `me()` call — ample time to also load the saved role.

**Design (async-gate at boot, per decision):**
- Pre-warm the saved role **before** `AuthSignedIn` is emitted, so the shell's first
  frame reads the correct value. Concretely:
  - `AuthStorage.readRole()` already exists. During `AuthNotifier.bootstrap()`,
    after a successful `me()` and before setting `AuthSignedIn`, read the saved role
    and seed it into `RoleNotifier` (e.g. a `RoleNotifier.hydrateFrom(String?)` or by
    having the role provider expose a synchronous seed the notifier can apply).
  - Cleanest seam: give `RoleNotifier` a `seed(AppRole)` method and call it from
    bootstrap once the role string is read; keep `_hydrate()` as the fallback for
    flows that don't pass through bootstrap (e.g. hot-reload). Because the shell only
    mounts after `AuthSignedIn`, the seed lands first.
- No new spinner, no new screen — the gate folds into the existing
  `AuthInitial`/`AuthLoading` window the user already waits through.
- Avoid a race: the role read must complete before `state = AuthSignedIn(user)`.
  Since bootstrap is already `async`, `await _storage.readRole()` is a natural,
  cheap addition.

**Trade-off surfaced:** This adds one secure-storage read (~sub-ms) to the bootstrap
path, which already does a network round-trip — negligible. The alternative
(shell-level splash gate) was rejected because it adds a transient spinner on every
shell mount; boot-gating is invisible.

**Boundary:** `auth_notifier.dart` (bootstrap) + `role_provider.dart` (seed method).
Pure-role users are unaffected (server-locked). No backend.

**Done when:** a `both` user who last used Traveler relaunches and the shell's first
painted frame is Traveler — no visible flip. Sender/pure-traveler users unchanged.

---

## Cross-cutting

- **Scope discipline (CLAUDE.md §9):** no unrelated refactors. Items #6/#1/#3 are
  already done and will not be touched.
- **Verification (CLAUDE.md §4 "evidence > assertions"):**
  - Mobile: `cd mobile && flutter analyze` warning-clean.
  - Django: `task test` (or `./manage.py test apps.matching`) green, incl. new
    name-serializer assertion and a query-count check / `select_related` presence.
  - No `check-drift` impact expected (no migration); will run `task check-drift` to
    confirm before commit.
- **TASKS.md update:** move the genuinely-completed items to **Done** with date +
  SHA, and correct the board to note that #6 and the in-screen parts of #1/#3 were
  already shipped by the prior session (so the staleness doesn't recur).
- **Git:** the prior 8 commits are already pushed to `origin/main`. New work is a
  series of small, independently-revertable commits. Branch-vs-main and push cadence
  for this pass will be confirmed with the user before pushing to the shared remote
  (the earlier decision only covered publishing the pre-existing commits).

## Out of scope / deferred

- KYC end-to-end wiring (separate spec).
- Chat end-to-end wiring (separate spec; `durable=` flag WIP stays local).
- KYC badge on traveler cards (TASKS.md already marks out of scope).
- Trip serializer name extension is *conditionally* in scope (item #3) — the plan
  decides based on reading the trip serializer.
