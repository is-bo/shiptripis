# N1: ask for notifications once on first open and recover from denial (2026-11-26)

Phone test 2, plan `docs/WASSLA_PHONE_TEST_2_PLAN.md` section 1.2, package N1 (Claude Sonnet, high).
App, plus one server change that Astra's review required (round 2): the device-registration path now
refuses a registration that a later registration or sign-out overtook (see "Registration order").
One migration (`notifications.0009`, a table with no existing data) and the regenerated
`contracts/sql/schema.sql`. Nothing is deployed by this change.

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
- **Which statuses ask.** iOS `notDetermined` always asks: its status is exact, and a reinstall keeps
  the keychain but resets the permission, so history must not block it. Android 13+ reports a
  never-asked permission as `deniedRequestable` or `notDetermined`, and reports the same again after
  the app was killed with its dialog open (the pinned plugin writes its own history only in the result
  callback), so on Android either status asks **only if this installation has made no request yet**.
  `authorized`, `provisional` and `settingsRequired` never ask.
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
- **No automatic retry.** After a dismissal or denial nothing asks on its own. Profile recovers, and
  **the system decides when Settings is the only way**: the pinned `firebase_messaging` 16.6 reports
  `deniedPermanently` (shown as Open settings) only after a denial with no rationale left, and keeps a
  dismissal requestable. The earlier "second request means Settings" count rule is removed, because it
  replaced Enable with Open settings after a mere dismissal. iOS offers Settings after its first
  denial. Returning from Settings refreshes the permission on resume and registers the phone.
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

### Registration order (Astra round 2, finding 1)

A registration already sent for account A could finish after A signed out or after B registered, and
the server then bound the phone to A and set it active. N1's automatic grant makes that reachable.
The server now orders every registration and sign-out of one installation:

- The app numbers each registration and each sign-out from one counter per installation
  (`TokenStore.nextPushBindingSequence`, key `push.binding_sequence`, kept through logout, only grows,
  holds no account data). The number is taken as late as possible, just before the request is sent.
- `PushInstallationBinding` (table `notification_push_installation_binding`, migration
  `notifications.0009`) keeps the newest number per installation. Registration and sign-out claim their
  number under a row lock in the same transaction as the device change. A number below the stored one
  is refused: registration answers `409 push_registration_superseded` (with `current_sequence`), a
  late sign-out changes nothing. The same number again is idempotent. A sign-out that arrives before
  the registration it overtakes is recorded even though no device exists yet, so that registration is
  refused when it arrives.
- The app ignores a refused registration when a later attempt of this phone owns the state. If it was
  the latest, the phone's own counter was behind (lost storage): it raises its counter to
  `current_sequence` and registers once more.
- `POST /api/notifications/devices`, `.../unregister` and `POST /api/auth/sign-out` now require
  `binding_sequence` (a positive integer); sign-out stays best-effort and leaves the device alone when
  the number is missing.

## Files

- App: `mobile/lib/core/push/push_coordinator.dart`, `mobile/lib/core/session/token_store.dart`,
  `mobile/lib/data/repositories.dart` and `auth_repository.dart` (the number on both requests),
  `mobile/lib/app/router.dart` (`/profile/notifications` is public),
  `mobile/lib/features/profile/profile_screen.dart` and `notification_settings_screen.dart` (guest),
  `mobile/lib/l10n/app_{en,fr,ar}.arb` and the regenerated `app_localizations*.dart`.
- Server: `apps/notifications/{models,push,views,serializers}.py`, migration `0009`,
  `apps/accounts/views.py` (sign-out), `backend/contracts/sql/schema.sql`.
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
  - `egs_guest_mode_test.dart` pinned `/profile/notifications` as not public; it is now public, so a
    guest can recover from a refusal;
  - the notification screen tests that load account preferences now run signed in, because a guest
    sees the permission controls only;
  - the first-open tests mount a real router, because the prompt waits for a painted screen.

## Tests

Phone (`k5_cold_start_test.dart`, all on a real router unless noted): guest first then sign-in
(registers only at sign-in); sign out and in again and a second account (never asked again, newer
numbers); restart after a denial; Android 13+ fresh install reading as denied; a denial and a dismissal
keep Enable; a permanent refusal leads to Settings; Android `notDetermined` with a spent count is not
asked again; an iPhone with kept history is asked again; leaving the app (`paused` and `inactive`)
while the count is being written keeps the prompt pending, takes the count back and asks on return;
a failing native call is taken back and tried again, twice at most; an iPhone refusal; a denial no dialog
can follow; prior authorized and provisional grants; return from Settings; a Firebase that never started
(two causes); registration retry without a second request; startup, resume and Profile sharing one
dialog; Profile asking first; background launch; the splash not counting; the first frame before
anything asks. **Which screen is on top, read at the instant the fake system request starts:** Home
after the splash; Home (not sign-in) after a guest who opened sign-in while Firebase was slow comes
back; the opened destination after a guest who arrived from a notification signs in; the guest payment
screen never.
`n1_notification_recovery_test.dart`: guest Profile shows the Notifications row and a refusal is
recoverable from it with no account preference request and no device registration; sign-out takes a
number above the registration it follows; a phone that fell behind the server catches up and
registers once more; a registration the server keeps refusing stops after one more try.
`k5_session_snapshot_test.dart`: counters serialize, survive logout, never lower.
Server (`test_push.py`): a delayed registration after sign-out, after a first-registration sign-out,
after the next account registered (with and without a sign-out), a delayed sign-out after a new
registration, an idempotent repeat, a missing number (400; sign-out leaves the device alone), the final
owner and active flag asserted each time.

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
- Whether the system dialog is covered by a screen transition on a real phone (the request fires once
  the destination is built, which can be while it slides in).
- 320 px right-to-left rendering of the guest screen was not captured (360 px was).
- No iOS or Android native config changed, so there is no platform config script to run for this
  package.

## Device checks still owed (human, real phones)

Android 13+ phone, fresh install of a configured release build:

1. Open the app as a guest: the system dialog appears once on the first usable screen, not on the
   splash. Deny it. Go to Profile > Notifications (guest Profile has the row): the notice offers
   Enable notifications and says to sign in for account notifications.
2. Tap Enable and swipe the dialog away without choosing: the screen still offers Enable. Tap Enable and
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
