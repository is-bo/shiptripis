# K5 — Mobile Performance

Status: **in progress** — checkpoint 1 (Deal list projection, attention,
pagination, root rebuild, session snapshot). Remaining packages are listed at the
end so a later context can resume without re-deriving anything.

K5 started from exact `main` SHA `b5e33e4` (K4 released as
`v1.0.0-rc.49+89de1ec`) on branch `claude/k5-mobile-performance`.

## Measurement method

`mobile/test/k5_request_budget_test.dart` boots the real `ShipTripApp` (real
router, real `ApiClient` with its auth interceptor and retries) over an
in-process fake backend that emulates the production pagination contracts:
`/api/deals` DRF envelope 20 per page with `scope`, bare-array lists with
`X-Next-Page`/`X-Total-Count`. The world is one signed-in account with 25 Deals
(3 active, 22 completed). The socket is replaced by an idle connection. The test
counts every HTTP request per phase: cold start until Home is usable, each tab
tap, app resume, and a push-permission refresh (checking whether the
`MaterialApp` element is rebuilt).

## Baseline and result

| Scenario | Before | After |
| --- | ---: | ---: |
| Cold start → usable Home, requests | 26 | 6 |
| … of which per-Deal `/api/deals/{id}` detail reads | 19 | 0 |
| … `/api/deals` list reads | 2 (all + active, first page only) | 1 (`scope=current`, all pages) |
| Resume, requests | 7 | 5 |
| Resume, `/api/me` reads | 1 | 1 |
| Push permission refresh rebuilds `MaterialApp` | yes | no |
| Deals beyond the first 20 reachable in the UI | no | yes (current: all pages; history: lazy pages) |
| Own requests / journeys / matches beyond 100 rows reachable | no | yes (bounded: 10 pages × 100) |

## Confirmed defects

1. **Root rebuild (13.2).** `ShipTripApp.build` watched `pushCoordinatorProvider`,
   so every push-state change (permission refresh, token registration) rebuilt
   `MaterialApp.router`. Now `ref.listen` keeps the coordinator alive without
   rebuilding the root.
2. **Attention N+1 (13.3).** `attentionProvider` read `dealDetailProvider` for
   every active/recent Deal to learn five booleans. The list row now carries them
   (`attention`), computed by the exact functions that build the detail's
   `handover` and `ratings` blocks.
3. **First-page-only Deal list (correctness).** `/api/deals` is DRF-paginated at
   20; the app read only page 1, so any account with more than 20 Deals silently
   lost Deals from Home, Deliveries and attention.
4. **100-row cap on own requests, journeys and matches (latent correctness).**
   K4's bare-array pagination defaults to 100; the app read page 1 only.
5. **Duplicate Deal list reads (13.4).** "All" and "active" lists were fetched
   separately on the same screens; active is now derived from `current`.
6. **Unstable Deal ordering.** The list ordered by `-created_at` only; ties could
   duplicate or drop rows across pages. Now `-created_at, -pk`.
7. **Reopened requests hidden.** The client inferred "settled" requests from Deal
   history, so a request whose unfunded reservation lapsed (and reopened) was
   wrongly hidden. It now trusts the server's lifecycle status
   (`RequestStatus.isSettled`).
8. **Cold start blocked on `/api/me` (13.5/13.6).** A slow or offline network kept
   users on the restore screen. See the session snapshot below.

## Rejected / already good

- Notification socket: generation-guarded, exponential backoff with jitter
  capped at 32 s, stopped on background and sign-out — no change.
- Resume catch-up is already coalesced; exactly one `/api/me` per resume.
- Account-scoped providers are already keyed by account id; no cross-account
  leakage found in the providers inspected.

## Decisions

- **Backend projection, not a new endpoint.** `DealSummarySerializer.attention`
  (four handover capability flags + `can_rate`) reuses
  `handover_permissions`/`viewer_can_rate`; a parity test walks funded →
  pickup ready → in transit (buffered) → delivery ready → delivered → rated for
  both parties and asserts list == detail. The row carries booleans only, never
  code material. Query count is flat in the number of Deals (live codes and
  ratings are prefetched).
- **`scope=current|history`.** `current` = active Deals plus completed Deals
  whose review window is still open (a superset; the per-row flags decide what
  needs attention). `history` = everything not active. Unknown scope → 400.
  `page_size` is opt-in, max 100; the default stays 20 for older clients.
- **Current is read in full (bounded), history lazily.** Current is small by
  construction; history pages 20 at a time as the user scrolls Deliveries →
  History (`SliverList.builder`, prefetch 3 rows before the end, retry footer).
- **No keepAlive on Deal detail.** Financial and handover state must not be
  served stale; only list/history state is shared.
- **Session snapshot is presentation data only.** On sign-in/refresh the app
  stores a small account projection (id, name, email, phone, wilaya, role,
  language, verification flags, KYC status) in secure storage, bound to the
  current identity generation. Cold start with a refresh token and a snapshot
  shows the app immediately and confirms `/api/me` in the background; a network
  failure keeps the cached presentation and retries at 10/30/90 s; an auth
  rejection signs out and clears tokens and snapshot; a different account id
  replaces the account and bumps the generation. Every mutation and financial
  read still goes to the server. The snapshot is deleted on sign-out, expiry and
  any new sign-in.

## Backend API changes (additive)

- `GET /api/deals`: rows gain `attention`; optional `scope`, `page_size`;
  ordering tie-break on `pk`. Existing clients are unaffected.

## Tests (checkpoint 1)

- Backend: `apps/deals/tests/test_phase_k5_list_attention.py` (parity through the
  lifecycle for both parties, no code material, flat query count, scope
  partition, unknown scope, page size) with the K4 query-budget test — 11 passed;
  `apps/handover apps/ratings apps/deals` — 193 passed.
- Mobile: `k5_request_budget_test.dart` (cold start ≤ 8 requests with no Deal
  detail reads and one `scope=current` list read; attention from list flags;
  history lazy page 2; resume one `/api/me` within 6 requests; `MaterialApp`
  identical across a push-state change; no rows of a previous account after an
  account switch), `k5_list_paging_test.dart` (envelope and header pagination,
  `maxPages` bound, `isSettled`), `k5_session_snapshot_test.dart` (18 cases:
  immediate sign-in from snapshot, offline retry at 10 s, auth rejection clears
  tokens and snapshot, account-id change bumps generation, stale writes refused,
  timers inert after sign-out/dispose, snapshot key set has no secrets). The
  handover-isolation storage allow-list now includes the snapshot key. Full
  suite: 1005 passed; `flutter analyze` clean.
- Found, pre-existing: `SessionController._invalidateEverything` invalidates
  `roleContextProvider`, which depends on the session, so debug builds throw
  `CircularDependencyError` at the end of sign-out/expiry (release builds skip
  the check; sign-out still completes). Assigned to package B.

## Package A — cold start, offline start, push init (13.5)

Before `runApp`, `main` awaited, in order: `SystemChrome.setEnabledSystemUIMode`
(one platform call), `LocaleFormats.ensureInitialized` (in-memory date symbols;
must precede the first `DateFormat`), and `FirebasePushMessaging.initialize`
(`Firebase.initializeApp` + `setForegroundNotificationPresentationOptions`,
platform-channel work that paints nothing), then registered
`onBackgroundMessage`. Secure storage, session restore, `/api/me`, locale and
role context were already off the pre-frame path (provider builds, async).

- **Firebase now starts after the first frame.** `DeferredPushMessaging` is
  handed to the app unresolved; `startAfterFirstFrame` runs the same
  initialiser from a post-frame callback. It reports
  `PushAvailability.initializing`, each call waits for the real implementation,
  streams forward once it exists, and any failure resolves to
  `DisabledPushMessaging(initializationFailed)`. `onBackgroundMessage` is still
  registered on a successful start, in the same turn; it needs only the method
  channel, and the handle it persists is what wakes a terminated app.
- **Coordinator waits for readiness.** `_restoreMessagingState` awaits
  `ready`, adopts the resolved availability, then reads permission, the launch
  message and registers as before. The root still only `ref.listen`s.
  Notification settings show the neutral "not read yet" notice while
  initialising rather than "could not start".
- **Confirmed good, unchanged.** Offline launch without a snapshot holds the
  splash, which shows progress after 0.6 s and the offline copy plus Try again
  after 8 s; credentials are kept. With a snapshot the app opens. Role context
  is read from the keystore only (no round trip), server role wins, and the key
  is wiped on every credential clear, so it cannot leak across accounts.
- Tests: `k5_cold_start_test.dart` (5 cases).

## Package C — lists, images, JSON (13.9–13.11)

**Lists (13.9).** Audited every growing list; converted only where rows were
built eagerly and the list can grow. Appearance is unchanged: a layout probe
compared every visible row's position and size before and after, in English
and Arabic, and they matched.

| List | Before | Action |
| --- | --- | --- |
| Deliveries → own requests / journeys | `Column` of every row in one `SliverToBoxAdapter` (up to 1000 rows since checkpoint 1) | Converted: each section returns slivers (`SliverList.builder`) |
| Journey detail → compatible requests | `Column` of every candidate (server `result_limit` 50, max 100) | Converted: `ListView` → `CustomScrollView`, candidates `SliverList.builder` |
| Ratings received | `ListView(children:)` (lazy per element, but allocates every row widget) | Converted to `ListView.builder` |
| Deliveries → Deal history | lazy since checkpoint 1 | Left |
| Notifications, chat list, payouts, discovery results | already `ListView.builder/separated` | Left |
| Chat thread | `ListView.builder(reverse: true)` + anchoring | Left (anchoring untouched) |
| Home attention/active (`take(3)`), open negotiations, request's matches, journey legs, dispute evidence/events, saved places, offer history | bounded by product rules | Left bounded |

**Images (13.10).** Three rendered images in the app; all now decode at the
drawn width (`cacheWidth` = layout width × device pixel ratio, aspect kept, never
upscaled) via `design/components/images.dart`. In-memory decode only: no disk
cache or package was added, and uploads still send the original file.

| Image | Decoded before | Decoded after (411 dp @ 2.625) |
| --- | ---: | ---: |
| Request item photo (`Image.network`, 200 dp strip) | 2048×1536 = 12.6 MB (a 12 MP upload from an older client: 48.8 MB) | 974×731 = 2.8 MB (portrait: 5.1 MB) |
| Request form item preview (`Image.file`, 180 dp) | 2048×1536 = 12.6 MB | ≈ 2.8 MB |
| DZD cheque preview (`Image.file`, 180 dp) | 2400×1800 = 17.3 MB | ≈ 2.4 MB |

Known limit: `BoxFit.cover` into a ~2:1 strip slightly upscales only images
wider than ~2:1 (panoramas).

**JSON (13.11).** Dio 5.11's default `FusedTransformer` already decodes bodies
≥ 50 KiB in a background isolate; smaller bodies and every model `fromJson` run
on the UI isolate. `test/k5_json_decode_budget_test.dart` times both halves on
current API shapes (median of 80 runs after warm-up), scaled with the
Dio/Flutter reference of 50 KB ≈ 0.4 ms (Pixel 4) / 2.5 ms (Moto G4):

| Payload | Bytes | Decoded on | UI isolate, Pixel 4 est. | Moto G4 est. |
| --- | ---: | --- | ---: | ---: |
| Deals, 20 rows (the app's page size) | 67.6 k | isolate | 1.0 ms | 6.1 ms |
| Deals, 100 rows | 337.6 k | isolate | 5.2 ms | 32.7 ms |
| Own requests, 100 rows | 167.7 k | isolate | 2.5 ms | 15.7 ms |
| Notifications, 100 rows | 33.7 k | UI | 0.7 ms | 4.2 ms |
| Chat history, 200 messages | 51.5 k | isolate | 1.2 ms | 7.4 ms |

Decision: **isolate parsing rejected — measured.** Every page the app actually
reads (Deals 20, notifications 30, chat 50) stays under 8 ms even on the Moto G4
estimate. The only cases above it are unusual accounts on 2016-class hardware:
current Deals and own requests are read across all pages and mapped in one
synchronous pass, so ≥ ~25 current Deals or ≥ ~50 own requests would cross 8 ms
there. Revisit with `Isolate.run` around those two mappings if field data shows
such accounts.

## Package B — request lifetime (13.7, 13.8, 13.12–13.14)

Measured with the same harness (plus a 40 ms-latency variant for overlap) and
`mobile/test/k5_request_lifetime_test.dart`. Every new test failed on
checkpoint 1 before the change.

| Scenario | Before | After |
| --- | ---: | ---: |
| Deliveries History → Active → History (inside 1 min), requests | 1 | 0 |
| Opening the inbox, badge-count reads | 1 | 0 |
| Bell + "Mark all read" counts, reads per refresh | 2 | 1 |
| Profile refresh + two socket token probes at once, `/api/me` | 3 | 1 |
| Deal detail opened and left mid-read, GET cancelled | no | yes |
| Read superseded by a live event, GET cancelled | no | yes |
| Traveller search superseded or left, GET cancelled | no | yes |
| Profile refresh recomputes attention / rebuilds Deal rows | yes | no |
| Sign-out / session expiry in debug | `CircularDependencyError` | clean |
| Account B inherits account A's in-memory traveller role | yes | no |

- **Cancellation.** `cancelOnDispose(ref)` gives a read a Dio `CancelToken`
  cancelled by `ref.onDispose` (dispose or rebuild). `_liveRead` passes one to
  every projection read; detail/search providers in features use it too
  (cancellation quote, request pricing, Boost state, dispute, compatible
  requests, inbox page). Riverpod has already dropped that read by then, so no
  error state is shown. Writes never get one. `FindTravelersController` cancels
  a superseded sort/refresh/page and everything on dispose, and no longer
  notifies after dispose. Checkout/payment polling was left to package D.
- **Sharing.** `ApiClient.getObject(share: true)` joins an identical read in
  flight, keyed by identity generation, a write epoch (moved at the start and
  end of every write) and path + query. Each caller gets its own copy, can leave
  on its own token, and the read is cancelled only when all have left; failures
  are never remembered. Only `/api/me` opts in; `refreshAccount` reads `fresh`
  (a live KYC event lands there and must not join an older read). The two badge
  providers now project one `_badgeCountsQuery`. Rejected: active Deals (already
  one provider), payout methods (one provider; the imperative pre-mutation reads
  need current revisions), catalogs (one consumer each).
- **Lifetime.** Only finished Deal history is kept, one minute after its last
  viewer and never past the sign-in that read it. No keepAlive on any detail,
  amount, allowed action, KYC or handover state. Tab switches already cost 0.
- **Granularity.** `attentionProvider`, Deliveries, Home "in progress" and the
  Deal screen watch the account id, not the whole account.
- **Role bug.** `_invalidateEverything` is gone. `RoleContextController` keys
  its remembered choice to the `AccountSession`, so any new sign-in starts from
  what that sign-in stored. Invalidating it had never reset that choice, because
  Riverpod 3 keeps the notifier instance across an invalidate.

## Package D — resume, sockets, badge, checkout polling (13.15–13.18)

- **Resume.** The five resume reads (`/api/me`, chat threads, matches,
  `deals?scope=current`, parcels) are all needed: sockets are closed while the
  app is hidden, so no live event covers them. Two phone-lifecycle defects were
  fixed. A trip to the notification shade, app switcher or a system dialog
  (`inactive` only) used to tear both sockets down, redial them and send five
  catch-up reads; it now does nothing. A real return passes through `hidden`,
  which reset the away timer, so `/api/me` was never re-read on resume; it is now
  read once. The first `resumed` at launch no longer adds a second `/api/me` next
  to session restore.
- **Sockets.** `/ws/notifications` and `/ws/chat` are both owned by
  `NotificationSocket`. Login, logout, account switch, background and rapid
  background/foreground ×6 each leave exactly one socket per endpoint and no
  stray timers (tested). Fixed: backoff used to reset on every successful
  handshake, so a server that accepted and then dropped was redialled every
  0.5–1 s with a catch-up each time; it now resets only after 30 s of uptime.
  Fixed: no client liveness check, so a half-open socket after a network change
  could lose events for minutes; the client now pings every 20 s. No SSE.
- **Badge.** The bell and "Mark all read" share one `/unread-count` read
  (packages B and D fixed this independently; B's `badgeCounts()` was kept at
  integration). Counts stay exact and reset on read.
- **Checkout polling.** Stripe/Chargily checkout: stops on paid, part-paid,
  failed, cancelled; an orphaned timer that could fire after the screen closed
  is gone; a second loop (back out and pay again mid-read, or resume mid-read)
  can no longer start, and `onSettled` fires once; cadence
  3,3,5,5,10,10,20,20,20 s. Guest-link sheet: a return mid-read no longer starts
  a second loop; 3→20 s, 10-minute budget. Both now pause while the app is in
  the background (the payer is usually on the payment page) and read at once on
  return. The client still never decides success; only the server order status
  does.
- **Fixed in review (was recorded as not fixed):** a checkout read for a
  previous order reference is no longer joined or applied after the reference
  changes.
- **Tests.** `k5_realtime_test.dart` (8), `k5_polling_test.dart` (6), one more
  resume case in `k5_request_budget_test.dart`; all but the socket-backoff test
  fail on the previous code. The 20 s ping lives in `_connectIO` and is not
  unit-testable; it needs a device check.

## Package D review fixes

A return from the shade now redials a socket waiting out its backoff (live
sockets untouched); socket uptime is measured on a monotonic clock. Checkout and
guest-link reads sent before the app was hidden are not adopted on return (one
fresh read follows; `onSettled` still fires once); a checkout read is never
joined or applied across an order-reference change; an unreadable order answer
counts as a failed read, so the schedule ends in "Check again". The first
`resumed` after a launch in an unknown lifecycle state reads `/api/me` unless
the session read the account in the last 30 s. Tests: 1 socket, 2 resume, 3
checkout, 1 guest sheet.

## Review fixes

- **`scope=current` uses the inbox's rating predicate.** It was "active, or
  completed with an open or unknown window", which dropped a Deal partially
  refunded after delivery (activity `cancelled`, still ratable) and kept a
  pre-column completed Deal forever. It is now "active, or
  `review_window_open_q`" over `with_review_deadline` — the same helper the
  inbox's rating actions now use. `current` and `history` can overlap for a
  partially refunded Deal in its window; the app shows it once (Active filters
  by `activity_state`, History reads history pages).
- **History grace period.** The reported leak (a live event rebuilding unviewed
  history, which then never hears `onCancel`) does not happen on Riverpod
  3.4.2: invalidating an inactive element disposes it instead of rebuilding
  it. A test now pins this: unviewed history is released, not re-read, and a
  fresh one still ends its grace period. No code change.
- **Session.** Sign-out invalidates the login in the tap's own turn again, and
  the snapshot delete is serialized with credential writes, so a queued
  snapshot write can neither land after it nor be accepted. A launch
  confirmation that lost the race to another request's session end
  (`cancelled`, or the identity already moved) no longer clears the tokens
  itself, so the "session expired" message survives. Sign-in paths remember
  the snapshot under the identity they captured.
- **Paging.** `getAllPages` keeps the first copy of a row repeated across pages
  by an insert between reads (rows with an `id` only).
- **Deal list query budget.** Back to its K4 budget (≤ 4): the `ratings`
  prefetch became per-role `Exists` annotations read by `viewer_can_rate`.
- **Tests.** Three backend tests in `test_phase_k5_list_attention.py` (not yet
  run here); Flutter: 2 paging, 4 session/snapshot, 1 history; every new
  Flutter test except the history one fails on the previous code.

## Resume here

All four packages are integrated on `claude/k5-mobile-performance`
(A `0a42245`, C `c83f696`, B `b2760b2`, D `740c50d`, plus a test fix
`e5fe0fb`). `flutter analyze` is clean and all `test/k5_*` pass together (80).
Still to do: full Flutter suite on the integrated tree; full Django PG suite
(a restart was running at session end — it was cut off once at 79% and the
cluster needed a fresh `SHIPTRIP_TEST_PGDATA`); independent Opus review of
`b5e33e4..HEAD` (was launched; re-run if no result is recorded here); then PR,
CI, merge, Railway TEST release `v1.0.0-rc.50+<sha>`, `/healthz`, `/readyz`,
smoke, cleanup of the four `.claude/worktrees/agent-*` worktrees and their
branches, the K5 phase report. Then K6 (persistent Redis cutover is mandatory)
and K7, then the K-Series Master Report. Ruff check passes; no migrations
missing.

## Remaining K5 work

Delegated as bounded packages, each reviewed before integration:

- **A. Cold start / offline startup / push init (13.5).** Defer Firebase/push
  initialisation until after the first frame without losing background-message
  registration; offline start never hangs; clear offline/stale indication with
  authority actions disabled.
- **B. Request cancellation / duplicates / provider lifetime (13.7, 13.8, 13.12–13.14).**
  Cancel abandoned GETs on provider disposal (never mutations); in-flight
  coalescing for `/api/me`, unread count, payout account, catalogs; short
  keepAlive only for list-type presentation data; generation guards intact.
- **C. Lists / images / JSON (13.9–13.11).** Virtualise growing lists
  (notifications, chat, payouts, discovery results); decode-size remote
  thumbnails; measure JSON decode cost before any isolate work.
- **D. Resume / sockets / badge / polling (13.15–13.18).** Selective resume
  refresh, socket lifecycle on logout/account switch/token refresh, unread-badge
  refresh driven by events, checkout polling bounded and cancelled.
- Then: full Flutter and Django suites, Ruff, migrations and drift checks,
  independent review of the whole K5 diff, PR, CI, merge, Railway TEST release.
