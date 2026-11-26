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

### Registration order (Astra rounds 2 and 3)

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
  fingerprint**. Registration and sign-out claim their number under a row lock in the same transaction
  as the device change. A registration numbered below the stored one is refused: `409
  push_registration_superseded` with `current_sequence`. The same number again is accepted only as an
  exact repeat (same operation, owner and token); a collision (a different token, account or
  operation) is refused (round 3).
- **A sign-in has a session id.** Every access and refresh token pair carries `sid`, copied by
  rotation. A device records the `sid` it was registered under, and a sign-out ends only the device
  registered under its own sign-in, whatever number it carries. So a delayed sign-out of A still ends
  A's device after B signed out first and advanced the counter, and cannot touch a newer binding of
  someone else; and a sign-out sent with a number lower than the server's (a phone whose counter was
  lost) still ends its own device rather than being skipped. A token with no `sid` (issued before this
  change) falls back to ending the owner's active device. A sign-out that arrives before the
  registration it overtakes is recorded even though no device exists yet, so that registration is
  refused when it arrives.
- **Account-wide revocation.** A completed password reset, and Google sign-in on an account whose email was
  never confirmed (`end_all_sessions`), end every sign-in of the account. `deactivate_all_push_devices` locks the account row, records the time in
  `PushAccountRevocation` and deactivates the devices; a registration locks the same row and refuses a
  token issued before that time (`409 push_session_revoked`). A registration already underway when the
  reset happens therefore cannot reactivate the device afterwards. (Tokens are compared by `iat` in
  whole seconds, so a token issued in the same second as the revocation is refused too: the safe side.)
- The app ignores a result when a later attempt of this phone owns the state: the check is made before
  clearing the pending token or showing success or failure, so neither response order of two
  registrations can hide a failure or undo a success. If it was the latest and the server was ahead,
  the phone raises its counter to `current_sequence` and registers once more.
- `POST /api/notifications/devices` requires `binding_sequence`. Sign-out and `.../unregister` accept
  it as optional: the phone sends the refresh-token revocation even if the counter or the installation
  ID cannot be prepared.
- **Not done, by decision.** Astra round 2 blocker 1 asked for the *currently installed* app (which
  sends no `binding_sequence`) to keep registering and logging out. CLAUDE.md: the app has never been in
  production and there are no real users, so nothing is spent on old clients; the registration number
  stays required. The sign-out still works without one, and ends the device by session.

## Files

- App: `mobile/lib/core/push/push_coordinator.dart`, `mobile/lib/core/session/token_store.dart`,
  `mobile/lib/app/route_transition_tracker.dart` (new, wired into the router),
  `mobile/lib/data/repositories.dart` and `auth_repository.dart` (the number on both requests),
  `mobile/lib/app/router.dart` (`/profile/notifications` is public),
  `mobile/lib/features/profile/profile_screen.dart` and `notification_settings_screen.dart` (guest),
  `mobile/lib/l10n/app_{en,fr,ar}.arb` and the regenerated `app_localizations*.dart`.
- Server: `apps/notifications/{models,push,views,serializers}.py`, migration `0009`,
  `apps/accounts/views.py` (the `sid` claim and sign-out), `backend/contracts/sql/schema.sql`.
- Docs: `docs/SHIPTRIP_V1_SPEC.md`, `docs/PUSH_NOTIFICATIONS_RUNBOOK.md`, this file,
  `docs/IMPLEMENTATION_STATUS.md`.
- Tests: `mobile/test/k5_cold_start_test.dart` (the first-open group, rewritten on a real mounted
  router), `mobile/test/n1_notification_recovery_test.dart` (new), `mobile/test/phase8fd_push_test.dart`,
  `mobile/test/k5_session_snapshot_test.dart`, `mobile/test/handover_isolation_test.dart` (the pinned
  storage-key list gains the two non-secret counters; the check now also sees keys written through the
  counter helper), `mobile/test/support/push_router.dart` (new), `mobile/test/support/fake_api.dart`;
  server: `apps/notifications/tests/test_push.py`, `apps/accounts/tests/test_l18a_sessions.py`,
  `apps/core/tests/test_l10_staff_and_accounts.py`.
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
  - the first-open tests mount a real router, because the prompt waits for a painted screen.

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
`k5_session_snapshot_test.dart`: counters serialize, survive logout, never lower.
Server (`test_push.py`, real bearer tokens with `sid` and `iat`): a delayed registration after
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
  `guest-notifications-<state>-<lang>.png` for `not-asked`, `denied-retry`, `denied-settings` and
  `granted`. These replace the earlier `granted-as-guest` pair, which was drawn with a member's screen
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
  native call counts a prompt that never appeared; a second swipe-away reads as a permanent denial; a
  token issued in the same second as an account-wide revocation is refused.
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
   Sign out of an account while the app is offline, reconnect, and confirm the phone no longer receives
   that account's notifications. Tap Enable and
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

iPhone, fresh install:

1. Open as a guest: the iOS dialog appears once. Allow, sign in, and confirm registration.
2. Reinstall (keychain kept): the dialog appears again, because the OS status is undetermined.
3. Deny, then Profile > Notifications offers Open notification settings; grant there and return.

## Handoff to later packages

N2 (ticket decision in the bell) shares the ARB files and generated localizations: rebase and
regenerate from the merged tip. O3 (enable and prove push) can now rely on a first-open prompt, but must
still verify registration for the signed-in test account.
