# N1: ask for notifications once on first open and recover from denial (2026-11-26)

Phone test 2, plan `docs/WASSLA_PHONE_TEST_2_PLAN.md` section 1.2, package N1 (Claude Sonnet, high).
App, plus a server change that Astra's review required (rounds 2 and 3): the device-registration path
orders every registration and sign-out of a phone, and a sign-in carries a session id (see
"Registration order"). One migration (`notifications.0009`, tables with no existing data) and the
regenerated `contracts/sql/schema.sql`. Nothing is deployed by this change.

## The decision

Until now the notification permission was asked only from Profile > Notifications. Ismail's decision
after the 2026-11-26 phone test: the app asks on its own, once, the first time it is opened, including
for a guest. The V1 specification (line 1155) and `docs/PUSH_NOTIFICATIONS_RUNBOOK.md` (Android, iOS,
and client configuration) now record that timing. The older "contextual from Profile only" rule, its
copy ("Wassla asks only when you choose Enable") and its test name are replaced.

## What changed

`core/push/push_coordinator.dart` owns the behavior; `main.dart` is unchanged, so the first frame is
not delayed (Firebase still starts after it, as in K5).

- **When it asks.** `_askOnFirstOpen` runs after a frame, never straight from an event. Every trigger
  (the end of the startup restore, a session change, a resume, any route change) only schedules a
  check for after the next frame. The check needs:
  - Firebase started and the first permission read settled;
  - the session resolved to a guest or a member, not the splash;
  - the app **resumed** (an `inactive` shade or system dialog does not count);
  - the top of the router stack neither the splash, a sign-in or other `/auth/` screen, nor the guest
    payment screen, and no notification still waiting to be opened. The prompt is not lost: it waits,
    and the next route change (sign-in closes, the opened screen replaces it) schedules the check again;
  - after that, one more frame is awaited, the conditions are checked again, the request is counted,
    and they are checked a last time with nothing between that check and the system call.
  A launch in the background asks when the app first comes forward.
- **Which statuses ask.** Only `notDetermined`, on both platforms. iOS `notDetermined` always asks: its
  status is exact, and a reinstall keeps the keychain but resets the permission, so history must not
  block it. Android 13+ reports a never-asked permission as `notDetermined` (the pinned plugin
  returns it when the app was never asked and no rationale is offered) and reports it again after the
  app was killed with its dialog open, so on Android it asks **only if this installation has made no
  request yet**. A requestable denial never asks on its own (round 3): on Android it is what an app
  that asked from Profile *before this build counted requests* reports after the upgrade, with no count
  to say so. `authorized`, `provisional` and `settingsRequired` never ask.
- **Installation history.** `TokenStore.readPushPermissionRequests / recordPushPermissionRequest /
  releasePushPermissionRequest` (key `push.permission_requests`) count the requests this installation
  made. The count is written before the system is asked, so a prompt interrupted by the app being
  killed counts as spent. It is **taken back** when the system was not reached: the person left the
  app between the write and the call, a sign-in opened, or the native call threw. Then the prompt stays
  pending for the next trigger; after two failed native calls in one run it stops asking on its own
  (Profile still asks on request). It belongs to the phone, not the account: logout and terminal clears
  leave it alone. Counter writes are serialized, so two at once never lose one.
- **One request at a time.** `requestPermission()` is single-flight: the first-open prompt, a resume
  and the Profile button join the request in flight instead of asking again.
- **No automatic retry.** After a dismissal or denial nothing asks on its own. Profile recovers. On
  Android the plugin reads a **first dialog swiped away** as `deniedPermanently` (nothing was denied, so
  no rationale is offered, and "asked before, no rationale" is permanent). One request on record with
  that reading is therefore shown as requestable and Profile keeps Enable (round 3). A real denial reads
  as requestable after one request and permanent after two. A second swipe-away reads as permanent:
  Android cannot tell it from two denials, so that case offers Settings (documented limit). iOS offers
  Settings after its first denial. Returning from Settings refreshes the permission on resume and
  registers the phone.
- **Waiting for the screen.** `RouteTransitionTracker` (a navigator observer, `app/route_transition_tracker.dart`)
  knows when a route is still sliding in or out. The router reports its new top the moment a route is
  popped, while the popped screen is on display for its exit animation; the prompt now waits for the
  animation to finish and for the frame after it, and checks again with the transition idle, so it never
  opens over a sign-in screen that is still leaving. The test asserts that at the instant of the fake
  system call the sign-in screen is no longer in the tree.
- **A durable count, a foreground press.** The automatic prompt asks only when its count reached the
  disk first; a write that fails skips the prompt (and counts toward the two-failure limit). A count
  written for a dialog that never opened (the app was killed in the short window between the write and
  the native call) stays counted, which is the safe side: Profile still asks. The Profile button
  rechecks that the app is in the foreground after its own count write and, if not, takes the count back
  and does not ask. Its count write failing never stops a person who pressed.
- **Firebase missing or failed.** `_messagingRestored` is never set, nothing is asked and no count is
  written, so the next launch that can ask still does. Launch is never blocked.
- **Registration.** Still gated on a signed-in session: a guest who grants is registered at sign-in.
- **Guests can recover.** Guest Profile has a Notifications row and `/profile/notifications` is a
  public location. For a guest the screen shows the phone's permission (with Enable or Open settings)
  and a note that account notifications come with signing in; it loads no account preferences and shows
  no "finishing setup" state. Granting as a guest reads "allowed on this phone, sign in and Wassla will
  start sending them here"; the device registers at sign-in.
- **Copy.** `pushPermissionBody` no longer says Wassla asks only when you choose Enable. New:
  `pushPermissionEnabledGuest`, `pushGuestSignInNote`. English, French and Modern Standard Arabic; the
  localizations are regenerated (`flutter gen-l10n`).

### Registration order (Astra rounds 2 to 5)

A registration already sent for account A could finish after A signed out or after B registered, and
the server then bound the phone to A and set it active. N1's automatic grant makes that reachable.
The server orders every registration and sign-out of one installation, and ties both to the sign-in
that made them:

- The app numbers each registration and each sign-out from one counter per installation
  (`TokenStore.nextPushBindingSequence`, key `push.binding_sequence`, kept through logout, only grows,
  holds no account data). The number is taken as late as possible, just before the request is sent.
  The installation ID is created once (`readOrCreateInstallationId` runs in the phone's write queue), so
  a startup registration and a token-refresh registration on a new phone share one UUID (round 3).
- `PushInstallationBinding` (table `notification_push_installation_binding`, migration
  `notifications.0009`) keeps the newest number per installation **with its operation, owner and token
  fingerprint, and the sign-in that sent it**. Registration and sign-out claim their number under a row
  lock in the same transaction as the device change. A registration numbered below the stored one is
  refused: `409 push_registration_superseded` with `current_sequence`. The same number again is an
  exact repeat only for the same operation, owner, sign-in and token, and is acknowledged without
  changing anything; any other use of the number is a collision and is refused (rounds 3 and 4). Round
  5: a repeat whose device is gone **or switched off** (the delivery feedback refused its token) is
  refused as superseded too, so the app's catch-up registers again with a higher number instead of
  reading the repeat as a live phone; the app also reads `active` from the receipt and leaves Retry when
  it is false.
- **A sign-in is a server row (round 4).** Every sign-in creates a `SignInSession` (table
  `accounts_sign_in_session`, migration `accounts.0008`), and every token of it carries its id as
  `sid`: the first pair and every pair a refresh rotates into. A refresh needs the sign-in to be live
  (`SessionRefreshToken`, the token class of `SessionTokenRefreshSerializer` on `/api/auth/refresh`: one
  more query per refresh), a push registration needs it to be live,
  and each device records the sign-in that registered it (`PushDevice.session`). Ending a sign-in is
  one write, under the account row lock that registration also takes first: a registration either
  commits before the end, and the end switches its device off, or runs after and is refused (`409
  push_session_ended`). There is no time comparison and nothing to miss: a rotated token, a token from
  the same second, an access token still in flight all name the same ended row.
- **Sign-out** (`end_session`) ends the sign-in the request proves and switches off every device that
  sign-in registered, on whatever installation and whether or not the body names one. Round 5: the
  phone sends its access token as it is, without refreshing it, and the refresh token it read before a
  concurrent refresh may have rotated it. A valid access token proves its own sign-in, whatever refresh
  token comes with it (one of another account is not touched: nothing is blacklisted any more, ending
  the sign-in already refuses every refresh token of it). An expired access token is no answer rather
  than a 401 (`_AccessIfValid`), and the refresh token then proves its sign-in when this server signed
  it and it is of the refresh type, even if a refresh already rotated it or it has expired
  (`_signed_claims` checks the signature, not the expiry): it still names the same sign-in, and all it
  can do here is end it. With neither, 401. Ending a sign-in that already ended
  answers 205 again. With an installation and a number it is also recorded in the
  installation's order, even before any device exists. A delayed sign-out of A cannot touch a binding a
  later sign-in made, and a sign-out numbered below a lost counter still ends its own devices.
- **A session the app lets go of is ended on the server too (round 5, verification).** The Sign-out
  button is not the only way the app drops a sign-in: when renewing it fails, `_AuthInterceptor` clears
  the credentials and reports the session expired. The sign-in may still be live on the server, with
  the phone switched on: the refresh token expired while the app went unopened (30 days), or a refresh
  rotated it and the answer never arrived. So `_endSession` then sends the sign-out itself,
  best-effort, with that refresh token alone (`_endSignInOnServer`): no bearer, since the stored
  credentials may already be those of a sign-in made since, and no installation or number, since
  ending the sign-in switches off all its devices and refuses its later registrations. A sign-in the
  server had already ended answers 205 as before. Only a request that never reaches the server
  (offline) leaves the phone on, which the best-effort contract below already states.
- **Ending every sign-in** (`end_all_sessions`: a completed password reset, Google sign-in on an
  account whose email was never confirmed, account deletion) ends every live sign-in row of the account
  and switches all of its devices off in one transaction under the same lock. It no longer blacklists
  the account's outstanding refresh tokens: SimpleJWT 5.3.1 never lists a rotated token there, which is
  the round-3 blocker, and the sign-in row covers every rotation. `PushAccountRevocation` and its
  issue-time check are gone.
- **A sign-in is issued under the same lock (round 5).** The password (or provider) check reads the
  account, and a reset, a Google claim or a deletion could commit before the sign-in row is created, so
  a request that passed the old password got a live sign-in after the end. `User.session_epoch` counts
  the account-wide ends: `end_all_sessions` moves it under the account lock, and `start_session`
  creates the row only if, under that lock, it still equals the value the credential check read
  (`SignInInterrupted` otherwise). The sign-in views then check the credentials once more against the
  account as it is now (`_sign_in`): an old password fails with the usual 400, a provider identity that
  still owns the account signs in, and a second end in that same instant answers `409
  sign_in_interrupted`, which the app shows with its generic recovery message.
- A token that names no sign-in, or one that never existed, cannot refresh or register. Migration
  `notifications.0009` deletes the push devices registered before sign-ins were recorded (they name
  none); the app registers again after its next sign-in, which every phone needs since its old tokens
  no longer refresh.
- The app ignores a result when a later attempt of this phone owns the state: the check is made before
  clearing the pending token or showing success or failure, so neither response order of two
  registrations can hide a failure or undo a success. If it was the latest and the server was ahead,
  the phone raises its counter to `current_sequence` and registers once more. Round 4: the check runs
  after **every** wait (the token lookup, the pending token, the installation ID, the number, the
  request, the pending-token write), so an older attempt whose token lookup finishes after a refresh
  never numbers itself, sends the obsolete token or reports a failure. A counter that cannot be raised
  during the catch-up leaves a failure that Retry and resume recover from, and the retry starts only if
  the attempt is still the newest for the same account.
- **Profile, round 4.** The button's request is put to the system only while Notifications is still the
  screen on top (`ModalRoute.isCurrent`, checked after the count write); Back pressed during the write
  takes the count back. On Android a request started from a requestable denial counts the system's
  earlier, uncounted request too (an app from before N1), so the count reads two and the next denial is
  the permanent one Android reports; the first-dismissal rule (one request from `notDetermined`, read as
  permanent) is unchanged. A guest who refused is told how to retry, without the in-app inbox promise,
  which only a member has (new string `pushPermissionDeniedRequestableGuest` in EN, FR and MSA).
- **Turning push off without signing out** (`.../unregister`, which the app does not call) changes
  nothing for an ended sign-in, not even the installation's order, and a numbered one below an
  operation already applied is refused as superseded instead of switching off the newer registration
  (round 5). A sign-out keeps switching its devices off however late it arrives, since it ends the
  sign-in.
- **On the phone, round 5.** Losing permission (a return from Settings) overtakes a registration still
  on its way, so a slow token lookup never registers or reports success afterwards. A token refresh
  overtakes the older attempt at once and sends the new token as Firebase handed it over; a keystore that
  refuses to keep the pending copy no longer stops the registration, and clearing that copy after a
  success is best-effort.
- **What a sign-out cannot reach yet (round 5, predates N1).** A push already queued in Redis carries
  the device tokens of the moment it was queued. The Go sender now asks the database, right before each
  send or retry, which of those devices are still switched on for the recipient with the same token
  (`DeviceRegistry`, `PostgresDevices` in `services/internal/notification/fcm_devices.go`), sends only
  to those, drops the entry when none is left and leaves it pending for the sweeper when the database
  cannot answer. The notification WebSocket is closed when the access token that opened it stops being
  valid (expiry plus the 30 s leeway, G2), and the Go validator now requires an expiry; the app
  reconnects with a fresh token, which only a live sign-in can get.
- `POST /api/notifications/devices` requires `binding_sequence`. Sign-out and `.../unregister` accept
  it as optional: the phone sends the sign-out even if the counter or the installation
  ID cannot be prepared.
- **Not done, by decision.** Astra round 2 blocker 1 asked for the *currently installed* app (which
  sends no `binding_sequence`) to keep registering and logging out. CLAUDE.md: the app has never been in
  production and there are no real users, so nothing is spent on old clients; the registration number
  stays required. The sign-out still works without one, and ends the device by session.

## Files

- App: `mobile/lib/core/push/push_coordinator.dart`, `mobile/lib/core/session/token_store.dart`,
  `mobile/lib/app/route_transition_tracker.dart` (new, wired into the router),
  `mobile/lib/data/repositories.dart` and `auth_repository.dart` (the number on both requests),
  `mobile/lib/core/api/api_client.dart` (round 5: the sign-out of a session the app lets go of),
  `mobile/lib/app/router.dart` (`/profile/notifications` is public),
  `mobile/lib/features/profile/profile_screen.dart` and `notification_settings_screen.dart` (guest),
  `mobile/lib/l10n/app_{en,fr,ar}.arb` and the regenerated `app_localizations*.dart`.
- Server: `apps/notifications/{models,push,views,serializers}.py`, migration `notifications.0009`,
  `apps/accounts/{models,sessions,locks,views,urls}.py` and migration `accounts.0008` (the sign-in row,
  the `sid` claim, the refresh check, sign-out, and in round 5 `User.session_epoch`),
  `backend/contracts/sql/schema.sql`. Go (round 5): `services/internal/notification/fcm.go` and
  `fcm_devices.go` (new), `services/cmd/notification/main.go`, `services/pkg/wsproto/wsproto.go`,
  `services/pkg/auth/jwt.go`.
- Docs: `docs/SHIPTRIP_V1_SPEC.md`, `docs/PUSH_NOTIFICATIONS_RUNBOOK.md`, this file,
  `docs/IMPLEMENTATION_STATUS.md`.
- Tests: `mobile/test/k5_cold_start_test.dart` (the first-open group, rewritten on a real mounted
  router), `mobile/test/n1_notification_recovery_test.dart` (new), `mobile/test/phase8fd_push_test.dart`,
  `mobile/test/k5_session_snapshot_test.dart`, `mobile/test/handover_isolation_test.dart` (the pinned
  storage-key list gains the two non-secret counters; the check now also sees keys written through the
  counter helper), `mobile/test/support/push_router.dart` (new), `mobile/test/support/fake_api.dart`;
  server: `apps/notifications/tests/test_push.py`, `apps/notifications/tests/factories.py` (new:
  `signed_in` and `push_device` make sign-ins and devices the way the app does),
  `apps/accounts/tests/test_l18a_sessions.py`, `apps/accounts/tests/test_store_account_deletion.py`,
  `apps/core/tests/test_l10_staff_and_accounts.py`, and the device fixtures of
  `apps/notifications/tests/test_l3a_ticket_copy.py` and
  `apps/admin_panel/tests/test_l6a_verification_inbox.py` (a device now needs its sign-in).
- Tests rewritten because the rule they pinned changed (stated here as plan 1.4 requires):
  - the two-denials-end-in-Settings test now says the system, not a count, decides (a denial and a
    dismissal keep Enable; a permanent refusal leads to Settings);
  - round 3: "Android 13+ asks on a fresh install that reads as denied" encoded the assumption that a
    requestable denial with no count is a never-asked install; it is now the opposite rule (an upgrade
    after a pre-N1 Profile denial is not asked) beside a fresh install reading `notDetermined`; the
    denial and restart tests start from `notDetermined`; "a refusal on iPhone" now really runs on iOS;
  - the two registration-retry tests had been changed from an HTTP 500 to a 400; both are back to 500
    (the app's write path sends no transport retries, so the fake clock never has to fire a timer);
  - `egs_guest_mode_test.dart` pinned `/profile/notifications` as not public; it is now public, so a
    guest can recover from a refusal;
  - the notification screen tests that load account preferences now run signed in, because a guest
    sees the permission controls only;
  - the first-open tests mount a real router, because the prompt waits for a painted screen;
  - round 4: "the Profile button pressed as the app leaves is not asked and not counted" starts from
    a requestable denial, which now counts the system's earlier request too: the count reads two while
    it is written and one after it is taken back (it read one and zero);
  - round 4: the account-deletion test asserted that the refresh token was blacklisted; the rule is that
    every sign-in ends, so it now asserts the sign-in row ended and the refresh is refused (401), and its
    neighbour uses a real sign-in instead of a token that names none;
  - round 4: "a token without a sign-in id ends the owner's binding" pinned a fallback that no longer
    exists; it is now "a token that names no sign-in cannot register"; the API tests that used
    `force_authenticate` (no token, no sign-in) now register with a real sign-in's bearer token;
  - round 5: `test_auth.py` "missing refresh returns 400" pinned that a sign-out needs a refresh token;
    a valid access token now proves its own sign-in, so it is "a valid access token signs out without a
    refresh token" (205, and the refresh is then refused);
  - round 5: "an acknowledged repeat changes nothing" acknowledged a repeat whose device was switched
    off; such a repeat is now refused as superseded (the device stays off, and the next number switches
    it back on);
  - round 5: the unregister test of `test_push.py` used number 2 twice, for another account's request
    and then the owner's; a reused number is now a collision for an unregister too (it honours the
    order), so the owner's request takes 3, as the app's counter would;
  - round 4: the K7 speed-budget test minted its refresh tokens with no sign-in (now refused) and
    counted the minting inside the measured queries; it mints through a real sign-in, outside the
    counted region as its docstring always said, and the `auth.restore` ceiling (8) is unchanged.

## Tests

Phone (`k5_cold_start_test.dart`, all on a real router unless noted): guest first then sign-in
(registers only at sign-in); sign out and in again and a second account (never asked again, newer
numbers); restart after a denial; a fresh Android install reading `notDetermined` is asked; **an
Android upgrade after a pre-N1 Profile denial (requestable, no count) is not asked**; a denial followed
by dismissals keeps Enable; two denials lead to Settings; **a first dialog swiped away (one request,
read as permanent) keeps Enable, survives a resume and a restart, and the button really asks again**;
Android `notDetermined` with a spent count is not asked again; an iPhone with kept history is asked
again; leaving the app (`paused` and `inactive`) while the count is being written keeps the prompt
pending, takes the count back and asks on return; **the Profile button pressed as the app leaves is not
asked and not counted (held count write)**; **an automatic prompt whose count cannot be written asks
nothing, and Profile still asks**; a failing native call is taken back and tried again, twice at most; an
iPhone refusal (run as iOS); a denial no dialog can follow; prior authorized and provisional grants;
return from Settings; a Firebase that never started (two causes); registration retry without a second
request (HTTP 500 first); startup, resume and Profile sharing one dialog; Profile asking first;
background launch; the splash not counting; the first frame before anything asks. **Which screen is on
top, read at the instant the fake system request starts:** Home after the splash; Home after a guest who
opened sign-in while Firebase was slow comes back, **with the sign-in screen no longer in the widget
tree** (the real app, ordinary 100 ms frames; the test fails if the transition wait is removed, checked
by mutation); the same on the stand-in router with the transition observed to be still running one frame
after the pop; the opened destination after a guest who arrived from a notification signs in; the guest
payment screen never.
`n1_notification_recovery_test.dart`: guest Profile shows the Notifications row and a refusal is
recoverable from it with no account preference request and no device registration; sign-out takes a
number above the registration it follows; a phone that fell behind the server catches up and
registers once more; a registration the server keeps refusing stops after one more try; **an older
request failing after a newer one registered does not undo it, and an older success after a newer
failure neither hides it nor consumes the pending token (both response orders)**; **a counter that
cannot be written still sends the sign-out (refresh token and installation ID, no number)**; **two
registrations starting together on a new phone share one installation ID (the real `TokenStore`
over mock secure storage)**.
Round 4 (each fails with its fix removed, checked by mutation): **an older token lookup finishing after
a refresh registration is never sent**; **an older lookup that finds no token does not report a failure
over a newer registration**; **a counter that cannot catch up leaves a failure Retry recovers from**;
**a catch-up overtaken by another account leaves that account's registration alone**; **Back pressed
while the request is being counted opens no dialog over the previous screen** (the real app, guest
route); **a guest who refused is not promised the inbox**; in `k5_cold_start_test.dart`, **the upgrade
denial asked again from Profile and denied leads to Settings**.
Round 5 (each fails with its fix removed, checked by mutation): **permission taken away during a token
lookup sends nothing**; **a refreshed token the keystore cannot keep is registered all the same**; **a
receipt that says the phone is off leaves Retry and the pending token**; **a guest whose push cannot
start (both causes) is not promised the inbox**. Round 5, verification (`phase8ff4_session_test.dart`,
each fails with its fix removed, checked by mutation): **a session whose renewal is refused is ended on
the server by its refresh token alone**, **a sign-in made the moment it ends never lends that sign-out
its bearer**, **a failing sign-out leaves the phone signed out all the same**.
`k5_session_snapshot_test.dart`: counters serialize, survive logout, never lower.
Server, round 4 (each fails with its fix removed): **an unnumbered sign-out before the first
registration refuses it** (blocker 1), **a sign-out that names no installation still switches its
devices off** (blocker 1), **a token stamped in the reset's own second is refused while a new sign-in in
that second registers** (blocker 2), **a real sign-in rotated twice, then a reset: the rotated refresh
is refused and its access token cannot register**, and the same after a sign-out
(`test_l18a_sessions.py`, blocker 3), **the same number from an older sign-in of the same person
collides, and the newer sign-in's sign-out still ends the device** (blocker 4), an acknowledged repeat
changes nothing, a sign-in cannot be ended through another account, a token naming no sign-in cannot
register.
Server, round 5 (each fails with its fix removed, checked by mutation): in `test_l18a_sessions.py`,
**an old password checked before a real reset gets no sign-in**, **a password checked before a real
Google claim gets no sign-in, and only the owner's sign-in is live**, **a Google sign-in overtaken by a
reset is checked again and signs in**, **an end before every check answers `sign_in_interrupted`**
(blocker 1); in `test_push.py`, the phone's own sign-out request with **an expired access token**, with
**a refresh token a concurrent refresh rotated**, with **both**, **a request proving no sign-in is
refused and changes nothing** (a refresh token signed with another key, expired or not, included),
**a repeated sign-out answers the same**, and the app's own sign-out after its session expired: **an
expired refresh token still ends its sign-in**, **a refresh token whose rotation was lost still ends
its sign-in** (blocker 2), **another account's
sign-out leaves this account able to refresh** (should-fix 1), **an unregister from an ended sign-in
leaves the order alone**, **a late unregister leaves the newer registration on** (should-fix 2), **a
repeat of a switched-off registration asks for a new number** (should-fix 8). Go: **a queued push none
of whose phones is still the recipient's is dropped**, **one is sent only to the phones still bound**,
**one whose phones cannot be checked stays pending**, the query names columns the committed schema has
(the query was also run against a migrated PostgreSQL 16 database: an active device with the same
token, another token, a switched-off device, an unknown id and another account each gave the right
answer); **a WebSocket closes when its token stops being valid**, **a token without expiry is
refused**.
Server (`test_push.py`, real bearer tokens of real sign-ins): a delayed registration after
sign-out, after a first-registration sign-out, after the next account registered (with and without a
sign-out), a delayed sign-out after a new registration, an exact repeat, collisions (same number with a
different token, account or operation), the number required to register, **A reg 1, B sign-out 4 first,
B reg 3, A sign-out 2 delayed: A's device ends and nothing of B's is active**, **a sign-out numbered below
a lost counter still ends its own device**, a sign-out with no number, another account's sign-out
changing nothing, a token with no `sid`, **a registration spanning a password reset is refused, a later
sign-in works, other accounts are unaffected**; the final owner and active flag asserted each time.

Checks, run from `mobile/`: `dart format --output=none --set-exit-if-changed lib test`,
`flutter analyze --fatal-infos`, `flutter test` (the whole suite). Server: `ruff check .`,
`makemigrations --check`, `pytest` against PostgreSQL 16, `task check-drift`'s dump compared with the
committed `schema.sql` (the `\restrict` nonce aside). Results are in the pull request.

## Screenshots

`docs/screenshots/n1/`, 360 px wide at 2x, English and Arabic, rendered with a throwaway golden rig (not
committed) with the bundled fonts.

- **Guest, through the real guest route** (the real app booted signed out, the Profile tab, the
  Notifications row, then the screen; the first-open prompt already answered by a fake system):
  `guest-profile-<lang>.png` (the new Notifications row), and
  `guest-notifications-<state>-<lang>.png` for `not-asked`, `denied-retry`, `denied-settings`,
  `granted` and (round 5) `push-failed`. Round 5 recaptured `denied-retry` from the round-5 code (the
  guest copy without the inbox promise) and added `push-failed` (Firebase could not start). These replace the earlier `granted-as-guest` pair, which was drawn with a member's screen
  and bypassed both guest gates.
- **Member** (unchanged screen, fixed coordinator state): `profile-notifications-<state>-<lang>.png`
  for `granted`, `denied-retry`, `denied-settings` and `not-asked`.

The first-open prompt itself is the operating system's own dialog: Wassla draws nothing for it, and it
cannot be captured on this machine.

## Not checked here

- No device or emulator on this machine: the real Android 13+ dialog and the real iOS dialog were not
  seen. The permission statuses were driven through a fake messaging layer. The Android plugin's
  `deniedPermanently` rule was read in the pinned `firebase_messaging` 16.6.0 source, not run.
- `FirebasePushMessaging` itself is unchanged and is not exercised by the tests.
- Whether the system dialog is covered by a screen transition on a real phone. Round 3 waits for the
  transition to finish in the widget tests; the real dialog was not seen.
- Windows left on purpose (documented in the runbook): a process killed between the count write and the
  native call counts a prompt that never appeared; a second swipe-away reads as a permanent denial; an
  access token outlives its sign-out for up to its own lifetime (5 minutes, plus the 30 s leeway) on the
  HTTP endpoints and on a WebSocket it opened, but can no longer refresh, register a phone or keep a
  socket open past that.
- Seen during the round-5 verification, outside N1 and left for a follow-up package: a renewal that
  fails on the network (not refused) also signs the member out on the phone, as before N1 (the app now
  at least ends that sign-in on the server when the network allows); and a ban ends none of the
  member's sign-ins and switches off none of their phones.
- 320 px right-to-left rendering of the guest screen was not captured (360 px was).
- No iOS or Android native config changed, so there is no platform config script to run for this
  package.

## Device checks still owed (human, real phones)

Android 13+ phone, fresh install of a configured release build:

1. Open the app as a guest: the system dialog appears once on the first usable screen, not on the
   splash. Deny it. Go to Profile > Notifications (guest Profile has the row): the notice offers
   Enable notifications and says to sign in for account notifications.
2. Tap Enable and swipe the dialog away without choosing: the screen still offers Enable (also after
   closing and reopening the app, and on a first dialog swiped away at launch). On a phone that already
   asked from Profile in an older build and was denied, install this build over it: no dialog at launch.
   Tap Enable and
   deny: the dialog appears again. After the system stops showing it the screen offers Open
   notification settings; turn them on and return: the screen reads allowed.
3. Kill and reopen the app: no dialog. Kill the app while the dialog is open, then reopen: no second
   dialog. Sign out and in as someone else: no dialog.
4. Open the app while holding the notification shade down, or from a notification as a guest: no dialog
   over sign-in or a half-opened screen.
5. Fresh install, allow at first open as a guest, then sign in: the screen shows registering and then
   enabled; the device appears for that account. Sign out, sign in as another account: the device
   belongs to the second account only, and is active.
6. Android 12 or older: no dialog at any point.
7. Sign-out cleanup is best-effort (V1 spec): signed out while offline, the server never hears of it,
   so the phone keeps receiving that account's notifications until the same phone signs in again (its
   registration replaces the binding) or the account resets its password. Check only that signing out
   online stops them, that a session the app reports as expired (online) stops them too, and that
   signing in again on the same phone moves them to the new sign-in.

iPhone, fresh install:

1. Open as a guest: the iOS dialog appears once. Allow, sign in, and confirm registration.
2. Reinstall (keychain kept): the dialog appears again, because the OS status is undetermined.
3. Deny, then Profile > Notifications offers Open notification settings; grant there and return.

## Handoff to later packages

N2 (ticket decision in the bell) shares the ARB files and generated localizations: rebase and
regenerate from the merged tip. O3 (enable and prove push) can now rely on a first-open prompt, but must
still verify registration for the signed-in test account.
