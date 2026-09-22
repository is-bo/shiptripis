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
