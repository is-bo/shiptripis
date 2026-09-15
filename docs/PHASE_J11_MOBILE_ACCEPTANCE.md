# J1.1 — Real-app acceptance closure and mobile reliability

Closes the regressions the owner hit after installing the J1 TEST APK. Every
change is Flutter-only: **no backend runtime code was altered and no Railway
deployment was performed**, so the J1 backend and CI evidence remains valid.

Starting main: `25cf5028d5a1a220f12ccd161495e54675a8ae69`.
Branch: `claude/j11-mobile-acceptance`.
Deployed TEST runtime throughout: `v1.0.0-rc.31+5ea3a4c` at
`https://shiptrip-production-f7f7.up.railway.app` (`/healthz` and `/readyz`
confirmed 200 with that release at the start of this phase).

## How this phase was verified

J1 was marked FAIL because its evidence was contract-level, not app-level. This
phase therefore ran **the real Flutter client**, not a stub.

There is no Android SDK, emulator or physical device on this workstation
(`flutter doctor`: "No devices available"; no `adb`, no build-tools). The app
was instead built for web in profile mode from the same `lib/` and driven in a
browser against a **local Django server running the same repository code** as
the deployed TEST runtime, with the payout surface configured to match the
deployed flags (`PAYOUT_PROFILES_ENABLED`, `STRIPE_CONNECT_ENABLED`,
`STRIPE_CONNECT_ALLOWED_COUNTRIES=FR`, `STRIPE_CONNECT_EXPECTED_MODE=test`,
`PAYOUT_DZD_EXECUTION_ENABLED=false`, and **no provider secret at all**, so
nothing in that harness could reach Stripe or Chargily). Sign-in, Home,
Deliveries, Chat, Profile and Payout methods were exercised by hand in that app.

The harness lives entirely in a scratch directory and is not part of the
repository. What it cannot cover is recorded under *Limitations* below.

## Reported symptom → root cause → fix

### 1. Payout methods: every action ended in an exclamation and "Refresh"

**Reproduced in the running app.** Tapping *Set up EUR payouts* produced
`409 stripe_connect_unavailable` from the server, and the app rendered a red
snackbar containing the single word **"Refresh"**.

**Root cause — the error copy, not the page.** `describeFailure` routes every
validation/conflict failure through `staleMessage`, whose fallback branch is
`l.staleRefreshAction` — the *label* of the Refresh action, "Refresh". None of
the six payout refusal codes was mapped, so `payout_profile_invalid`,
`payout_country_unsupported`, `stripe_connect_unavailable`,
`stripe_connect_provider_error`, `payout_setup_invalid` and
`payout_evidence_unavailable` all produced that same one-word message. Three
different failures were indistinguishable, which is why every action on the page
looked like the same generic error.

The page itself was **not** collapsing. Riverpod's `AsyncError.copyWithPrevious`
always carries the previous value forward, so a failed refresh keeps
`hasValue == true` and `AsyncView` keeps rendering the data. The whole-page
error state is only reachable when the *first* load fails.

**Fix.** All six codes now carry a sentence saying what happened and what to do,
in English, French and Arabic. Verified in the running app: the same 409 now
reads *"EUR payout setup is temporarily unavailable. Your details are unchanged
— please try again shortly."* The page stays usable and the button is not stuck.

Also fixed on that page: the EUR card's legal-country row was labelled **"Switch
role"** (it used `l.roleSwitchLabel`); it now reads "Country".

### 2. Preference selection — EUR only / DZD only / Both

**Verified working in the running app** against a correctly configured backend.
Each selection moved the radio, persisted, refreshed the cards and left the page
usable; *Both* confirmed with a "Done" snackbar. The J1 fix that re-reads fresh
revisions before submitting is what makes this hold — a PATCH replayed with a
stale revision returns `400 payout_profile_invalid`, which was verified directly
and is now legible rather than showing "Refresh".

### 3. Completed deliveries stayed on Sender Home

**Root cause — a backend lifecycle gap, consumed wrongly by the client.**
`ParcelRequest.status` is set to `matched` when a Deal is created and is **never
advanced again**: `IN_TRANSIT`, `DELIVERED` and `COMPLETED` exist as choices in
`apps/parcels/models.py` but no non-test code path ever assigns them. The only
assignments anywhere are `OPEN`, `MATCHED` and `CANCELLED`. The client treated
"not finished by its own status" as "still running", so every delivered shipment
stayed in Home's sender list for ever and never reached History. Home's
"In progress" list, which reads `activity=active`, was never implicated.

**Fix (client-side, using authoritative data).** The Deal is the authority: every
Deal row already carries the server-derived `activity_state` and its
`delivery_request_id`. A new `settledRequestIdsProvider` derives the set of
requests whose Deal the server no longer counts as active, and Home and
Deliveries read settlement from there instead of from the request's own status.
Nothing is inferred locally — the state comes from the server field.

**This does not repair the backend.** `ParcelRequest` still never advances, which
remains wrong for any consumer that reads it directly. Fixing the parcel
lifecycle transitions is a backend change to a product state machine and is
recorded below as **Requires Astra backend phase**.

Fixed alongside it: `historyDealsProvider` fetched only `activity=completed`
while the History filter accepted `completed || cancelled`, so **cancelled
deliveries were fetched by no provider at all** and were invisible everywhere.
It now fetches both buckets.

### 4. Delivery detail showed no route

**Root cause — a missing UI state, not a decoding failure.** The route decoder
and the timeline are correct; the existing I1B suite proves an ordered frozen
route renders. When `route` is null — which is legitimate for the seven
historical Deals funded before route snapshots existed — `_RouteSection`
returned `SizedBox.shrink()`. It rendered *nothing at all*, which is
indistinguishable from the app failing to draw a route the server did send.

**Fix.** The absent case is now explicit and distinguishes the two facts: a
funded delivery with no snapshot says the travel route was not recorded for that
delivery; an unfunded one says the route appears once the delivery is funded. No
route is fabricated and no live-Journey fallback was reintroduced.

### 5. "Open dispute" appeared after the window had closed

The deal screen's own CTA was already server-authoritative from J1. Two **other**
entry points were not:

- `cancel_screen.dart` offered "Open a dispute" purely from the refusal code
  `cancellation_not_available_after_pickup`, with no window check and no
  prior-dispute check.
- `dispute_open_screen.dart` re-implemented the window itself, comparing
  `protection_ends_at` against the **client clock**, and gated existing disputes
  on `isActive` — which is false for a *resolved* dispute, so the user could
  write up to 2000 characters and only then be refused at POST.

**Fix.** Both now read `available_actions` from the deal, which is the single
server rule covering party, window and prior dispute together. The protection
deadline is still displayed; it is no longer used to decide anything. The
existing refusal-code fallbacks that handle the POST race are kept.

### 6. "How was it?" lingered after rating

**Root cause — the J1 `state` field was never decoded.** `RatingState.fromJson`
read every other key and silently discarded `state`, so the UI kept inferring
from `can_rate` / `submitted` / `counterparty_submitted`. That inference cannot
express the real states: `expired` and `unavailable` collapsed into the same
thing, and `revealed` had no representation at all — when both sides had rated,
no branch matched and the user got the heading "Rating saved" with nothing under
it.

**Fix.** `RatingLifecycleState` decodes the server's `available`,
`submitted_waiting`, `revealed`, `expired` and `unavailable`; an older
deployment that omits the field parses as `unknown` and falls back to today's
boolean behaviour rather than losing the section. The rate action is offered
**only** in `available`. `submitted_waiting` and `expired` are passive states.
`revealed` renders the counterpart's rating, and the section now outlives
`window_open` so a revealed rating stays readable. The blind rule is enforced
twice: the counterpart's rating is exposed only when the server's state is
`revealed` *and* that rating's own `is_revealed` is true.

### 7. Chat: a sent message only appeared after leaving and reopening

**Root cause — resume and reconnect reconciled the wrong screen.**
`PushCoordinator._reconcileCurrentScope` read
`router.routerDelegate.currentConfiguration.uri`. Every in-app detail route is
reached with `pushNamed`, and go_router keeps the **base** uri across a push, so
while `/chat/thread/7` was on screen the reported location was still `/chat`.
That resolved to no resources, and `reconcileScope` only re-fires *collection*
resources, so `LiveResource.chat(7)` was never reconciled. A message that
arrived while the socket was down stayed invisible until the user popped and
reopened the thread — which rebuilds the autoDispose controller and reloads.
The same gap silently disabled resume/reconnect refresh for **every** pushed
detail route: deal, payment, dispute, match, journey.

**Fix.** The coordinator now resolves the matched location of the top route.

The optimistic send path itself was verified correct: the pending bubble is
inserted synchronously before the HTTP call, the UUID `client_message_id` is
generated and retained for retry, delivered messages are keyed by server id so
an echo cannot duplicate a row, and a failed send stays visible with a retry.
One real gap was fixed: the composer cleared unconditionally even when the
controller refused the message, so typed text could be destroyed with nothing on
screen. `canAcceptSend` now gates the clear.

### 8. Notifications: registration, badge and History

**Device registration is not broken; it is ungranted.** The client's
registration contract matches the server exactly — path, body keys, platform
enum, UUID installation id and bearer auth all line up. Registration is gated on
an already-granted OS permission, and the app requests that permission from
exactly one place: **Profile → Notifications**. On Android 13+ a fresh install
starts at *not determined*, so a reinstalled app never registers until the owner
grants it there. Signing out deactivates the device server-side, which explains
both inactive rows and their `last_seen_at` dates. The four Firebase client
variables **are** configured in the repository, so the J1 APK was capable of
push. This is an owner action, not a code defect, and it is the first item on
the acceptance checklist below. The deliberate "never prompt except from the
contextual action" rule in `PUSH_NOTIFICATIONS_RUNBOOK.md` was **not** overridden.

Fixed in this phase:

- `_restoreMessagingState` was unawaited **and** had no error handling. One
  exception left the permission at `unavailable` for the whole app run — which
  closes the registration gate permanently — and lost the cold-start
  notification tap with it. Each step now fails on its own terms, and the launch
  notification is read before registration is awaited so opening from a
  notification no longer waits on an HTTP round trip.
- The three I1A arrival channels (`deal.arrival_reported`,
  `deal.arrival_confirmed`, `deal.arrival_declined`) were missing from the
  client's live-event allowlist and were dropped outright, over both the socket
  and push. They are now accepted and reconcile the deal.
- The bell read the legacy `unread` key. It now reads the explicit `active`
  count, and "Mark all read" is gated on `unread_active` — the badge total does
  not justify that button, because a fully-read inbox can still be full of live
  actions.
- Four stale-badge paths: reading a chat thread, marking one notification read,
  marking all read, and opening from a push tap now all refresh the badge; the
  inbox list is refreshed alongside it, so a row that resolves on read leaves
  Active instead of sitting there styled unread.

## What did not change

No backend runtime code, no migration, no schema change, no deployment, no
provider configuration. Stripe stays TEST, Chargily stays TEST,
`PAYOUT_DZD_EXECUTION_ENABLED` stays false, and no real-money or LIVE operation
was performed. No J2 work was started.

## Limitations — what still needs the owner's device

The web harness runs the real Dart code but is not an Android device. These
items could not be closed here:

1. **Push end to end.** `firebase_messaging` and FCM device registration have no
   web equivalent in this build, so permission grant, token retrieval, the
   registration request, foreground receipt, background receipt, notification
   tap and deep link all require the phone.
2. **Realtime websocket behaviour.** The socket client uses `dart:io`, which
   does not run on web. Optimistic send, reconciliation, idempotent retry and
   after-id catch-up are covered by the automated suite; live two-device receipt
   is not demonstrated here.
3. **Seeded delivery fixtures.** The local database has no funded Deal, so Home's
   settled-request behaviour, the route states and the dispute/rating states were
   proven by the regression tests rather than by tapping through them. Building a
   full funded-delivery fixture would have required financial mutations this
   phase must not make.
4. **Android rendering and insets.** Bottom-nav overlap, gesture navigation, the
   home indicator and Arabic RTL on a real phone remain device checks; the
   existing safe-area suite covers them synthetically.

## Findings handed to the backend

**Requires Astra backend phase — `ParcelRequest` lifecycle never advances.**
`apps/parcels/models.py` declares `IN_TRANSIT`, `DELIVERED` and `COMPLETED`, and
no non-test code path assigns any of them; a request stops at `MATCHED` for the
life of the delivery. J1.1 works around this on the client by reading the Deal's
`activity_state`, which is authoritative — but any other consumer of
`ParcelRequest.status` is still reading a status that stopped being true at
funding. Advancing it belongs with the delivery state machine, not here.

## Tests

`mobile/test/phase_j11_acceptance_test.dart` pins each symptom to the server
fact that settles it: the settled-request rule and the two History buckets; every
rating state including the blind-reveal rule and the "never actionable once
submitted" rule; the dispute CTA following `available_actions`; both route-absent
states; the arrival channels reaching the deal; the badge reading `active` and
`unread_active`; and every payout refusal code rendering a real sentence instead
of "Refresh".

## Known bound on the Home fix

`settledRequestIdsProvider` reads the unfiltered deal list, which the repository
fetches one page at a time (20 rows). An account with more than twenty deals
could still show a settled shipment whose Deal falls outside page one. That is a
pagination bound, not a state bug, and it disappears once the backend advances
`ParcelRequest.status` properly.

## Owner acceptance checklist

Install the J1.1 APK **after uninstalling the previous QA build** — profile APKs
are signed with a per-run debug key, so an upgrade install fails with
`INSTALL_FAILED_UPDATE_INCOMPATIBLE`.

Report each line as **PASS** or **FAIL** with a screenshot.

1. **Turn notifications on first.** Profile → Notifications → *Enable
   notifications*, and accept the Android prompt. This is required: nothing else
   in the app asks for it, and no push can arrive until it is granted. Say what
   that screen shows you.
2. **Payout methods.** Profile → Payout methods. The page loads; selecting EUR
   only, DZD only and Both each sticks; nothing gets stuck spinning. If anything
   fails, it should now say *why* in a full sentence — screenshot that sentence.
3. **EUR Stripe TEST onboarding.** *Set up EUR payouts* opens Stripe's hosted
   TEST page; returning to ShipTrip updates the card. Use Stripe TEST data only.
4. **DZD setup.** *Set up DZD payouts* opens the form (first name, last name,
   CCP account, CCP key, RIP, crossed-cheque photo — and no NIP).
5. **Home.** A delivered delivery is no longer in the Home sending list, and it
   does appear under Deliveries → History.
6. **Route.** Open a funded delivery: stops, FLIGHT/DRIVE and times render. Open
   an old one: it should say the route was not recorded — not show a blank gap.
7. **Dispute and rating.** No "Open a dispute" on a delivery whose window has
   closed. After you rate, the prompt stops asking and shows "Rating saved".
8. **Push.** With the app closed, trigger a notification; tap it; check it opens
   the right screen and that the bell count changes.
9. **Chat.** Send a message: it must appear immediately. If a second account is
   available, confirm the other side receives it without reopening the thread.
