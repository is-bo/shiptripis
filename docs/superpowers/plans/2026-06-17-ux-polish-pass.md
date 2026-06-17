# UX Polish Pass Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the four genuine UX gaps the prior session left (verified against code, not the stale TASKS.md): bottom-nav unread badge, match-detail pull-to-refresh, real full names on cards, and a role-hydration boot gate.

**Architecture:** Mostly mobile (Flutter/Riverpod 3) reads of existing provider state plus one read-only Django serializer addition. No DB migration, no schema.sql change, no Go-read tables touched — so no `check-drift` impact and no Claude-B coordination. Each task is independently revertable.

**Tech Stack:** Flutter + Riverpod 3 (`Notifier`/`NotifierProvider`), Dio; Django REST Framework + pytest-style `APITestCase`.

## Global Constraints

- **Riverpod 3:** `Notifier` + `NotifierProvider`, never `StateNotifier`. (CLAUDE.md §7)
- **Bottom nav:** white pill, sun-yellow (`AppColors.sun`) accent only on the selected icon — no grey, no dark indicator. Badges are additive overlays and must not alter selected-icon styling. (CLAUDE.md §7)
- **Money:** integer DZD only (not touched here, but no float introductions anywhere).
- **Verification before "done":** `cd mobile && flutter analyze` warning-clean; Django `./manage.py test apps.matching apps.trips` green. Evidence > assertions. (CLAUDE.md §4)
- **Scope discipline:** do NOT touch the already-shipped counter-offer UI (`match_detail_screen.dart:82,211,250-313`), the in-screen notification polish, or the WS offer invalidation (`live_event_router.dart:177-186`). (CLAUDE.md §9)
- **No migration this pass.** If any change appears to need one, stop — it's out of scope.
- Commit message trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

### Task 1: Bottom-nav unread badge on the notifications tab

**Files:**
- Modify: `mobile/lib/features/shell/app_shell.dart` (`_BottomNav`, currently `:305-385`)

**Interfaces:**
- Consumes: `notificationsNotifierProvider` → `NotificationsState.unreadCount` (int), from `mobile/lib/core/ws/notifications_providers.dart`.
- Produces: nothing consumed by later tasks.

Notes for the implementer:
- `_BottomNav` is currently a `StatelessWidget`. The notifications icon is index `2` in `_icons` (`Icons.notifications_rounded`).
- Use `.select` so the nav rebuilds only when the count changes.
- Show the badge only when `i == 2 && !selected && unread > 0`. A badge on the tab you're already viewing is noise, so suppress it when that tab is selected.
- `9+` cap for counts over 9. Badge color: `AppColors.terracotta` (matches existing unread treatment in `notifications_screen.dart:57` and the inbox-tile unread dot at `:287`).

- [ ] **Step 1: Convert `_BottomNav` to a `ConsumerWidget`**

Change the class declaration and `build` signature:

```dart
class _BottomNav extends ConsumerWidget {
  const _BottomNav({required this.index, required this.onChange});
  final int index;
  final ValueChanged<int> onChange;

  static const _icons = [
    Icons.travel_explore_rounded,
    Icons.chat_bubble_rounded,
    Icons.notifications_rounded,
    Icons.person_rounded,
  ];

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final unread = ref.watch(
      notificationsNotifierProvider.select((s) => s.unreadCount),
    );
    // ...existing Container/Row below, unchanged except the icon cell...
  }
}
```

Add the import at the top of the file (with the other `core/` imports):

```dart
import '../../core/ws/notifications_providers.dart';
```

- [ ] **Step 2: Wrap the icon in a Stack with a badge for index 2**

Inside `List.generate`, replace the bare `Icon(...)` child with a badge-aware build. The existing `Icon` is:

```dart
child: Icon(
  _icons[i],
  size: 22,
  color: selected ? AppColors.ink : AppColors.inkMute,
),
```

Replace it with:

```dart
child: _NavIcon(
  icon: _icons[i],
  selected: selected,
  badgeCount: i == 2 && !selected ? unread : 0,
),
```

Add the `_NavIcon` widget below `_BottomNav` in the same file:

```dart
class _NavIcon extends StatelessWidget {
  const _NavIcon({
    required this.icon,
    required this.selected,
    required this.badgeCount,
  });
  final IconData icon;
  final bool selected;
  final int badgeCount;

  @override
  Widget build(BuildContext context) {
    final iconWidget = Icon(
      icon,
      size: 22,
      color: selected ? AppColors.ink : AppColors.inkMute,
    );
    if (badgeCount <= 0) return iconWidget;
    final label = badgeCount > 9 ? '9+' : '$badgeCount';
    return Stack(
      clipBehavior: Clip.none,
      children: [
        iconWidget,
        Positioned(
          top: -4,
          right: -6,
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 1),
            constraints: const BoxConstraints(minWidth: 16),
            decoration: BoxDecoration(
              color: AppColors.terracotta,
              borderRadius: BorderRadius.circular(AppRadius.pill),
              border: Border.all(color: Colors.white, width: 1.5),
            ),
            alignment: Alignment.center,
            child: Text(
              label,
              textAlign: TextAlign.center,
              style: const TextStyle(
                color: Colors.white,
                fontSize: 9,
                fontWeight: FontWeight.w700,
                height: 1.2,
              ),
            ),
          ),
        ),
      ],
    );
  }
}
```

- [ ] **Step 3: Analyze**

Run: `cd mobile && flutter analyze`
Expected: "No issues found!" (or warning-clean). Fix any analyzer complaint (e.g. unused import) before continuing.

- [ ] **Step 4: Manual smoke (document, don't assert blind)**

Because this is a pure read of `unreadCount`, a widget test is lower-value than a one-line reasoning check: the badge watches the same `unreadCount` the header pill (`notifications_screen.dart:49`) already renders, which WS prepends bump (`notifications_providers.dart:152-174`) and `markAllRead`/`markRead` clear (`:185-210`). Note in the commit body that the badge is driven by the same source as the verified header pill.

- [ ] **Step 5: Commit**

```bash
cd ~/ShipTrip
git add mobile/lib/features/shell/app_shell.dart
git commit -m "feat(mobile): unread badge on notifications nav tab

Overlay terracotta count badge on the notifications bottom-nav icon,
driven by notificationsNotifierProvider.unreadCount (same source as the
already-shipped header pill). Hidden when the tab is selected or count==0;
caps at 9+. Selected-icon styling unchanged per CLAUDE.md bottom-nav rule.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Pull-to-refresh on match_detail_screen (+ verify post-apply freshness)

**Files:**
- Modify: `mobile/lib/features/matching/match_detail_screen.dart` (`_refreshAll` at `:104-108`, `build`'s `data:` branch at `:137-159`)

**Interfaces:**
- Consumes: `matchDetailProvider(int)`, `offerListProvider(int)`, `chatEligibilityProvider(int)` from `mobile/lib/core/matching/matching_providers.dart` (all `FutureProvider.autoDispose.family`).
- Produces: nothing consumed by later tasks.

Notes:
- The body is a `ListView` returned from `_MatchBody.build` (`:213`). To make pull-to-refresh hold the spinner until data returns, the `onRefresh` must `await` the refetch.
- `_refreshAll()` (`:104-108`) is `void` (fire-and-forget). Add an async sibling that invalidates then awaits the `.future` of detail + offers.

- [ ] **Step 1: Add `_refreshAndWait` next to `_refreshAll`**

In `_MatchDetailScreenState`, directly below `_refreshAll` (`:104-108`), add:

```dart
Future<void> _refreshAndWait() async {
  ref.invalidate(matchDetailProvider(widget.matchId));
  ref.invalidate(offerListProvider(widget.matchId));
  ref.invalidate(chatEligibilityProvider(widget.matchId));
  // Hold the RefreshIndicator spinner until the two primary providers
  // have actually refetched (eligibility is best-effort, not awaited).
  await Future.wait([
    ref.read(matchDetailProvider(widget.matchId).future),
    ref.read(offerListProvider(widget.matchId).future),
  ]);
}
```

- [ ] **Step 2: Wrap the `data:` body in a `RefreshIndicator`**

In `build`, the inner `offersAsync.when(... data: (offers) => _MatchBody(...))` returns `_MatchBody`. Wrap that returned `_MatchBody` in a `RefreshIndicator`:

```dart
data: (offers) => RefreshIndicator(
  onRefresh: _refreshAndWait,
  color: AppColors.ink,
  child: _MatchBody(
    match: match,
    offers: offers,
    myId: myId,
    busy: _busy,
    counterOpen: _counterOpen,
    counterCtl: _counterCtl,
    onAccept: _doAccept,
    onDecline: _doDecline,
    onWithdraw: _doWithdraw,
    onCounterToggle: () => setState(() => _counterOpen = !_counterOpen),
    onCounterSubmit: _doCounter,
    onGoToPayment: (offerId) =>
        context.push('/payment/$offerId?match=${match.id}'),
  ),
),
```

- [ ] **Step 3: Ensure the ListView always scrolls (so pull works on short content)**

In `_MatchBody.build` (`:213`), the `ListView(` needs `physics: const AlwaysScrollableScrollPhysics(),`. Add that argument to the `ListView`:

```dart
return ListView(
  physics: const AlwaysScrollableScrollPhysics(),
  padding: const EdgeInsets.fromLTRB(16, 8, 16, 32),
  children: [
    // ...unchanged...
  ],
);
```

- [ ] **Step 4: Verify post-apply freshness (item #4) — trace, no code unless broken**

Trace the path: `find_parcels_screen.dart:155` calls `repo.apply(...)`, then `:175` `context.push('/match/${match.id}')`. `match_detail_screen` then `ref.watch`es `matchDetailProvider(matchId)` / `offerListProvider(matchId)`, which are `autoDispose.family` (`matching_providers.dart:31-39`) — first watch triggers a fresh GET. Therefore the just-created offer is fetched on mount; no stale cache.

Confirm by reasoning: the providers are auto-disposed when no longer watched (leaving match detail disposes them), so re-entering always refetches. **Only if** manual testing later shows a stale list, add `ref.invalidate(offerListProvider(widget.matchId))` in `initState` via `WidgetsBinding.instance.addPostFrameCallback`. Do not add speculative invalidation now. Record the trace conclusion in the commit body.

- [ ] **Step 5: Analyze**

Run: `cd mobile && flutter analyze`
Expected: warning-clean.

- [ ] **Step 6: Commit**

```bash
cd ~/ShipTrip
git add mobile/lib/features/matching/match_detail_screen.dart
git commit -m "feat(mobile): pull-to-refresh on match detail

Wrap the negotiation body in a RefreshIndicator whose onRefresh awaits a
real refetch of matchDetail + offerList (eligibility best-effort), so the
spinner holds until data returns. AlwaysScrollableScrollPhysics lets the
pull work on short content. WS-driven invalidation (live_event_router)
already covered live updates; this adds the manual affordance.

Post-apply (#4): verified no fix needed — matchDetail/offerList are
autoDispose.family, so navigating to /match/<id> after apply refetches.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Real full names — Django side (matching + trips serializers)

**Files:**
- Modify: `backend/monolith/apps/matching/serializers.py` (`MatchSerializer`, `:73-104`)
- Modify: `backend/monolith/apps/trips/serializers.py` (`TripSerializer`, `:71-95`)
- Test: `backend/monolith/apps/matching/tests/test_matching.py`
- Test: `backend/monolith/apps/trips/tests/` (existing trip tests; add a name assertion)

**Interfaces:**
- Produces (mobile Task 4 consumes these JSON keys):
  - `MatchSerializer` adds `sender_name: str` and `traveler_name: str` (full name; empty string if unset).
  - `TripSerializer` adds `traveler_name: str`.

Notes:
- Querysets already `select_related` the needed FKs: matching views at `:92,106,125` (`sender`, `traveler`); trip browse views at `:122-124,149` (`traveler`). **No N+1** — verify these lines still hold; do not remove them.
- `User.full_name` is a `CharField` (`apps/accounts/models.py:21`), never null; may be `""`. Return it raw — the mobile fallback handles empties.

- [ ] **Step 1: Write the failing test (matching)**

In `apps/matching/tests/test_matching.py`, add a test. The existing helpers `_user`, `_client`, `_make_delivery` and the apply/detail flow are already in the file (`_user` sets `full_name=f"User {suffix}"`). Find an existing test that creates a match and fetches detail (around `:100-104` / `:418`) for the exact URL names, then add:

```python
def test_match_detail_includes_full_names(self):
    sender = _user("namesender@example.com", "7")
    traveler = _user("nametraveler@example.com", "8")
    sender.full_name = "Amine Khelifi"
    sender.save(update_fields=["full_name"])
    traveler.full_name = "Yacine Bensalah"
    traveler.save(update_fields=["full_name"])
    parcel = _make_delivery(sender)
    trip = _trip(traveler)  # use the file's existing trip helper
    # traveler applies -> creates match. URL names are FLAT (no namespace):
    # the existing apply tests call reverse("matches-apply").
    r = _client(traveler).post(
        reverse("matches-apply"),
        {"parcel_id": parcel.id, "trip_id": trip.id},
        format="json",
    )
    assert r.status_code in (200, 201), r.data
    match_id = r.data["id"]
    detail = _client(sender).get(reverse("matches-detail", args=[match_id]))
    assert detail.status_code == 200
    assert detail.data["sender_name"] == "Amine Khelifi"
    assert detail.data["traveler_name"] == "Yacine Bensalah"
```

Verified url names (no `app_name` namespace anywhere): `matches-apply`,
`matches-detail`, `matches-list`. Confirm the file's trip-helper name (`_trip`
vs other) by reading the top of `test_matching.py` — the existing apply tests at
`:97,124,143,161` show the exact setup to copy.

- [ ] **Step 2: Run it — expect failure**

Run: `cd backend/monolith && python manage.py test apps.matching.tests.test_matching -k full_names -v 2`
Expected: FAIL — `KeyError: 'sender_name'` (field not yet in serializer).

- [ ] **Step 3: Add the fields to `MatchSerializer`**

In `apps/matching/serializers.py`, inside `MatchSerializer` (after the existing `sender_id`/`traveler_id` declarations at `:74-75`), add:

```python
    sender_name = serializers.SerializerMethodField()
    traveler_name = serializers.SerializerMethodField()
```

Add both to the `Meta.fields` tuple (insert after `"traveler_id",`):

```python
            "sender_name",
            "traveler_name",
```

Add the two methods to the class body (next to `get_latest_offer`):

```python
    def get_sender_name(self, obj: Match) -> str:
        return obj.sender.full_name

    def get_traveler_name(self, obj: Match) -> str:
        return obj.traveler.full_name
```

- [ ] **Step 4: Run the matching test — expect pass**

Run: `cd backend/monolith && python manage.py test apps.matching.tests.test_matching -k full_names -v 2`
Expected: PASS.

- [ ] **Step 5: Write the failing test (trips)**

Add the test to `apps/trips/tests/test_trips.py` (the dir exists). The sender-browse
endpoint is `reverse("trips-search")` (`TripSearchView`, `views.py:122`), which
returns a **bare list** (`Response(TripSerializer(qs, many=True).data)` — no
pagination envelope) and excludes the requester's own trips, so the browsing user
must differ from the trip's traveler. Read `test_trips.py` for the file's existing
user/trip helpers (it uses `self.client` and `reverse("trips-list-create")` for
creates, `reverse("airports-list")` for lists) and copy that setup:

```python
def test_trip_search_includes_traveler_name(self):
    # traveler with a known name posts an ACTIVE trip; a DIFFERENT user browses.
    traveler = <create via file helper>
    traveler.full_name = "Yacine Bensalah"
    traveler.save(update_fields=["full_name"])
    <create an ACTIVE trip owned by traveler, ALG->CDG, future departure>
    browser = <create a different user>
    r = _client(browser).get(reverse("trips-search"))
    assert r.status_code == 200
    assert isinstance(r.data, list)
    assert any(t["traveler_name"] == "Yacine Bensalah" for t in r.data)
```

Fill the `<...>` by copying the existing create-trip test's exact setup — do not
guess helper names; `trips-search` returns a bare list (confirmed), so `r.data` is
iterable directly.

- [ ] **Step 6: Run it — expect failure**

Run: `cd backend/monolith && python manage.py test apps.trips -k traveler_name -v 2`
Expected: FAIL — `KeyError: 'traveler_name'`.

- [ ] **Step 7: Add `traveler_name` to `TripSerializer`**

In `apps/trips/serializers.py`, `TripSerializer` already has `traveler_id = serializers.IntegerField(source="traveler.id", read_only=True)` (`:74`). Add below it:

```python
    traveler_name = serializers.CharField(source="traveler.full_name", read_only=True)
```

Add `"traveler_name",` to `Meta.fields` (after `"traveler_id",`).

- [ ] **Step 8: Run the trip test — expect pass**

Run: `cd backend/monolith && python manage.py test apps.trips -k traveler_name -v 2`
Expected: PASS.

- [ ] **Step 9: Full app suites + no-migration / no-drift check**

Run: `cd backend/monolith && python manage.py test apps.matching apps.trips -v 1`
Expected: all green.

Run: `cd backend/monolith && python manage.py makemigrations --check --dry-run`
Expected: "No changes detected" (these are read-only derived fields — if it wants a migration, something is wrong; stop and reassess).

- [ ] **Step 10: Commit**

```bash
cd ~/ShipTrip
git add backend/monolith/apps/matching/serializers.py \
        backend/monolith/apps/trips/serializers.py \
        backend/monolith/apps/matching/tests/test_matching.py \
        backend/monolith/apps/trips/tests/
git commit -m "feat(api): expose sender/traveler full names on match + trip serializers

MatchSerializer gains sender_name/traveler_name; TripSerializer gains
traveler_name. All read-only derived from User.full_name. Querysets already
select_related sender/traveler (matching views, trip browse views) so no
N+1. No migration, no schema.sql change, no Go-read table touched.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Real full names — mobile side (models + 4 render sites)

**Files:**
- Modify: `mobile/lib/core/matching/matching_repository.dart` (`MatchSummary`, `:163-208`)
- Modify: `mobile/lib/core/trips/trips_repository.dart` (`Trip`, `:31-66`)
- Modify: `mobile/lib/features/sender/request_detail_screen.dart` (`:398`, `:667`)
- Modify: `mobile/lib/features/sender/follow_package_screen.dart` (`:190`)
- Modify: `mobile/lib/features/sender/find_travelers_screen.dart` (`:183`)

**Interfaces:**
- Consumes (from Task 3): JSON keys `sender_name`, `traveler_name` on match responses; `traveler_name` on trip responses.
- Produces: `MatchSummary.travelerLabel()` / `MatchSummary.senderLabel()` and `Trip.travelerLabel` — the single fallback source.

- [ ] **Step 1: Add name fields + label helpers to `MatchSummary`**

In `matching_repository.dart`, add to the `MatchSummary` constructor params, the `fromJson`, and the fields. Constructor (add after `required this.travelerId,`):

```dart
    this.senderName,
    this.travelerName,
```

`fromJson` (add after `travelerId: j['traveler_id'] as int,`):

```dart
        senderName: j['sender_name'] as String?,
        travelerName: j['traveler_name'] as String?,
```

Fields (add after `final int travelerId;`):

```dart
  final String? senderName;
  final String? travelerName;

  /// Display label for the traveler — real name when set, else `Traveler #id`.
  String travelerLabel() {
    final n = travelerName?.trim();
    return (n != null && n.isNotEmpty) ? n : 'Traveler #$travelerId';
  }

  /// Display label for the sender — real name when set, else `Sender #id`.
  String senderLabel() {
    final n = senderName?.trim();
    return (n != null && n.isNotEmpty) ? n : 'Sender #$senderId';
  }
```

- [ ] **Step 2: Add name field + label to `Trip`**

In `trips_repository.dart`, `Trip` (`:31-66`). Constructor (after `required this.travelerId,`):

```dart
    this.travelerName,
```

`fromJson` (after `travelerId: j['traveler_id'] as int,`):

```dart
        travelerName: j['traveler_name'] as String?,
```

Fields (after `final int travelerId;`):

```dart
  final String? travelerName;

  /// Display label for the traveler — real name when set, else `Traveler #id`.
  String get travelerLabel {
    final n = travelerName?.trim();
    return (n != null && n.isNotEmpty) ? n : 'Traveler #$travelerId';
  }
```

- [ ] **Step 3: Update the 3 MatchSummary render sites**

`find` and replace `'Traveler #${match.travelerId}'` (and the `"..."` variant) with `match.travelerLabel()` at:

- `request_detail_screen.dart:398` — `Text('Traveler #${match.travelerId}', ...)` → `Text(match.travelerLabel(), ...)`
- `request_detail_screen.dart:667` — same change.
- `follow_package_screen.dart:190` — `Text("Traveler #${match.travelerId}", ...)` → `Text(match.travelerLabel(), ...)`

Keep the existing `style:` argument on each unchanged. Note: site `:183` of find_travelers is handled in Step 4 (it's a `Trip`, not a match). After editing, confirm zero remaining matches for the literal:

Run: `cd mobile && grep -rn "Traveler #\${match.travelerId}" lib`
Expected: no output.

- [ ] **Step 4: Update the find_travelers Trip render site**

`find_travelers_screen.dart:183` — `Text('Traveler #${trip.travelerId}', style: AppType.mono(11, color: AppColors.inkMute))`.

Replace with:

```dart
                Text(trip.travelerLabel,
                    style: AppType.body(11, color: AppColors.inkMute)),
```

(Switch `AppType.mono` → `AppType.body`: a real name shouldn't render in the monospace ID style. If `AppType.body` signature differs, match the call shape used elsewhere on that screen.)

- [ ] **Step 5: Confirm no stray literals remain**

Run: `cd mobile && grep -rn "Traveler #\$" lib`
Expected: no output (all four sites now use a label helper).

- [ ] **Step 6: Analyze**

Run: `cd mobile && flutter analyze`
Expected: warning-clean.

- [ ] **Step 7: Commit**

```bash
cd ~/ShipTrip
git add mobile/lib/core/matching/matching_repository.dart \
        mobile/lib/core/trips/trips_repository.dart \
        mobile/lib/features/sender/request_detail_screen.dart \
        mobile/lib/features/sender/follow_package_screen.dart \
        mobile/lib/features/sender/find_travelers_screen.dart
git commit -m "feat(mobile): render real traveler/sender names on cards

MatchSummary + Trip parse sender_name/traveler_name and expose
travelerLabel()/senderLabel() with a 'Traveler #id' fallback for unset
names (single source of fallback truth). Replaces 'Traveler #<id>' at all
four sites: request_detail (x2), follow_package, find_travelers.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Role-hydration boot gate (no first-frame role flip)

**Files:**
- Modify: `mobile/lib/core/state/role_provider.dart` (`RoleNotifier`, `:14-34`)
- Modify: `mobile/lib/core/auth/auth_notifier.dart` (`bootstrap`, `:55-71`)

**Interfaces:**
- Consumes: `AuthStorage.readRole()` (already exists, `auth_storage.dart:27`).
- Produces: `RoleNotifier.seed(AppRole)` — sets the role synchronously before the shell mounts.

Notes:
- The race: `RoleNotifier.build()` returns `AppRole.sender` then `_hydrate()` async-flips. Only `both` users are affected (`effectiveRoleProvider` server-locks pure roles). The shell mounts only after `AuthSignedIn`, so seeding the role *before* emitting `AuthSignedIn` removes the flip.
- `bootstrap()` is already `async` and already awaits a network `me()` call, so awaiting one secure-storage read is negligible.

- [ ] **Step 1: Add a `seed` method to `RoleNotifier`**

In `role_provider.dart`, add to `RoleNotifier` (after `set`, `:27-31`):

```dart
  /// Seed the role synchronously from an already-read storage value.
  /// Called from auth bootstrap BEFORE the shell mounts so a "both" user
  /// lands on the correct first frame (no async flip). Pure-role users
  /// ignore this — effectiveRoleProvider server-locks them.
  void seed(AppRole r) => state = r;
```

Leave `_hydrate()` in place as the fallback for flows that don't pass through bootstrap (e.g. hot reload).

- [ ] **Step 2: Read + seed the role in `bootstrap` before `AuthSignedIn`**

In `auth_notifier.dart`, the current `bootstrap` success branch (`:60-67`) is:

```dart
    state = const AuthLoading();
    try {
      final user = await _repo.me();
      state = AuthSignedIn(user);
    } catch (_) {
      await _storage.clear();
      state = const AuthSignedOut();
    }
```

Change the success path to seed the saved role before emitting `AuthSignedIn`:

```dart
    state = const AuthLoading();
    try {
      final user = await _repo.me();
      // Seed the saved UI role BEFORE the shell mounts so "both" users don't
      // see a first-frame flip (pure roles are server-locked downstream).
      final savedRole = await _storage.readRole();
      if (savedRole == 'traveler') {
        ref.read(roleProvider.notifier).seed(AppRole.traveler);
      } else if (savedRole == 'sender') {
        ref.read(roleProvider.notifier).seed(AppRole.sender);
      }
      state = AuthSignedIn(user);
    } catch (_) {
      await _storage.clear();
      state = const AuthSignedOut();
    }
```

Add the import at the top of `auth_notifier.dart` (with the other relative imports):

```dart
import '../state/role_provider.dart';
```

- [ ] **Step 3: Check for an import cycle**

`role_provider.dart` imports `auth/auth_notifier.dart` (for `authNotifierProvider`/`authStorageProvider`). Now `auth_notifier.dart` imports `state/role_provider.dart`. Dart allows mutual imports across files (no cycle error at the library level here since they're separate libraries referencing top-level symbols), but verify the analyzer is clean.

Run: `cd mobile && flutter analyze`
Expected: warning-clean, no import-cycle error. If the analyzer flags a problem, break it by reading the role string in bootstrap and passing it down without importing the provider — but first confirm there's an actual error; Dart does not forbid mutual file imports.

- [ ] **Step 4: Reason about correctness (document in commit)**

`roleProvider.notifier` is read inside `bootstrap`, which runs from `main.dart`'s post-frame callback (`main.dart:33`). Reading a `NotifierProvider`'s `.notifier` instantiates it if needed and calling `seed` sets state before `AuthSignedIn` flips the router to `/app`. The shell's `ref.watch(effectiveRoleProvider)` → for `both`, `ref.watch(roleProvider)` now reads the seeded value on first build. Pure-role users: `effectiveRoleProvider` returns the server role directly, unaffected.

- [ ] **Step 5: Commit**

```bash
cd ~/ShipTrip
git add mobile/lib/core/state/role_provider.dart \
        mobile/lib/core/auth/auth_notifier.dart
git commit -m "fix(mobile): seed saved role during bootstrap to kill first-frame flip

RoleNotifier.seed() lets auth bootstrap set the persisted UI role BEFORE
emitting AuthSignedIn (and thus before the shell mounts), so 'both' users
who last used Traveler no longer see a Sender frame flip to Traveler.
Folds into the existing bootstrap wait — no new splash/spinner. Pure-role
users unaffected (server-locked via effectiveRoleProvider).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Final verification + TASKS.md reconciliation

**Files:**
- Modify: `TASKS.md`

- [ ] **Step 1: Full mobile analyze**

Run: `cd mobile && flutter analyze`
Expected: warning-clean.

- [ ] **Step 2: Full Django suite for touched apps**

Run: `cd backend/monolith && python manage.py test apps.matching apps.trips -v 1`
Expected: green.

- [ ] **Step 3: Drift guard**

Run: `cd backend/monolith && python manage.py makemigrations --check --dry-run`
Expected: "No changes detected."

(If `task check-drift` is runnable locally, prefer it — but it requires the Go toolchain; the no-migration check above is the load-bearing one for this pass since no schema changed.)

- [ ] **Step 4: Update TASKS.md**

Move to **Done** (under Islam / Claude A) with date `2026-06-17` + the commit SHAs, and correct the board to record that the prior session had already shipped the counter-offer UI and the in-screen notification/WS-offer polish, so the staleness doesn't recur. Specifically:
- Mark done: notifications nav-tab badge; match-detail pull-to-refresh; real full names (matching + trips); role-hydration boot gate.
- Annotate under "Soon": counter-offer UI (#6) and WS offer invalidation (#3 in-app) and notification in-screen polish (#1) were **already implemented** by the prior session — remove or strike them with a note.

- [ ] **Step 5: Commit**

```bash
cd ~/ShipTrip
git add TASKS.md
git commit -m "tasks: log 2026-06-17 UX polish pass + reconcile stale board

Done: nav unread badge, match-detail pull-to-refresh, real full names
(matching + trips serializers + mobile), role-hydration boot gate.
Corrected the board: counter-offer UI and in-screen notification/WS-offer
polish were already shipped by the prior session.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 6: Confirm push cadence with the user**

Do NOT push to `origin/main` automatically. Surface the commit list and ask whether to push now or hold (the shared-remote push decision is the user's, per the spec's git note).

---

## Self-Review

**Spec coverage:**
- Spec §1 (nav badge) → Task 1. ✓
- Spec §2 (pull-to-refresh + #4 post-apply) → Task 2 (incl. verification step). ✓
- Spec §3 (real names: Django serializer w/ N+1 guard, mobile model + 4 sites, trip serializer) → Tasks 3 (Django incl. trips) + 4 (mobile incl. find_travelers Trip site). ✓
- Spec §4 (role boot gate, async-gate at boot, full-name decision) → Task 5. ✓
- Spec cross-cutting (flutter analyze, Django tests, no-drift, TASKS.md update, push cadence) → Task 6. ✓
- "Do not touch #6/#1/#3 done work" → encoded in Global Constraints + Task 1/2 commit notes. ✓

**Placeholder scan:** Tasks 3 Steps 1/5 intentionally instruct the implementer to copy exact `reverse()` names and result-shape from existing tests rather than hardcode possibly-wrong URL names — this is a *verification instruction with a concrete method*, not a vague "figure it out." The test bodies show the real assertions; only the url-name/envelope is deferred to a read, which is correct because guessing them would be worse. All other steps contain literal code.

**Type consistency:** `travelerLabel()` (method, MatchSummary) vs `travelerLabel` (getter, Trip) — intentionally different (method on the summary to mirror `senderLabel()`, getter on Trip which has only one). Both documented at definition. `seed(AppRole)` defined in Task 5 Step 1, consumed Step 2. JSON keys `sender_name`/`traveler_name` produced in Task 3, consumed in Task 4 — names match.

**Decision:** trip-serializer extension confirmed IN scope (Task 3 Steps 5-8, Task 4 Steps 2/4) per user approval.
