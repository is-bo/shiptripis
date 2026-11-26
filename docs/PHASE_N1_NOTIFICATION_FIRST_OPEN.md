# N1: ask for notifications once on first open and recover from denial (2026-11-26)

Phone test 2, plan `docs/WASSLA_PHONE_TEST_2_PLAN.md` section 1.2, package N1 (Claude Sonnet, high).
App only: no server, Go, migration or contract change. Nothing is deployed by this change.

## The decision

Until now the notification permission was asked only from Profile > Notifications. Ismail's decision
after the 2026-11-26 phone test: the app asks on its own, once, the first time it is opened, including
for a guest. The V1 specification (line 1155) and `docs/PUSH_NOTIFICATIONS_RUNBOOK.md` (Android, iOS,
and client configuration) now record that timing. The older "contextual from Profile only" rule, its
copy ("Wassla asks only when you choose Enable") and its test name are replaced.

## What changed

`core/push/push_coordinator.dart` owns the whole behavior; `main.dart` and the widget tree are
unchanged, so the first frame is not delayed (Firebase still starts after it, as in K5).

- **When it asks.** `_askOnFirstOpen` runs after the first permission read has settled, which is after
  the first frame and Firebase's start. It also needs the session to be resolved (a guest or a member,
  not the splash), the app in the foreground, and the OS able to show a dialog. The triggers are the
  end of the startup restore, a session change and every resume. A launch in the background asks when
  the app first comes forward.
- **Which statuses ask.** iOS `notDetermined` always asks: the OS itself guarantees one answer, and an
  iOS reinstall keeps the keychain but resets the permission, so history must not block it. Android 13+
  reports a never-asked permission as `deniedRequestable`; it asks only if this installation has made
  no request yet. `authorized`, `provisional` and `settingsRequired` (a permanent denial, Android below
  13, an iOS denial) never ask.
- **Installation history.** `TokenStore.readPushPermissionRequests / recordPushPermissionRequest`
  (key `push.permission_requests`) count the requests this installation made, from the first-open
  prompt or from Profile. The count is written before the system is asked, so a prompt interrupted by
  the app being killed counts as spent. It belongs to the phone, not the account: logout and terminal
  clears leave it alone, so a second person signing in is never asked again.
- **One request at a time.** `requestPermission()` is single-flight: the first-open prompt, a resume and
  the Profile button join the request in flight instead of asking again. The first-open attempt is also
  limited to one per app run.
- **No automatic retry.** After a dismissal or denial nothing asks on its own. Profile recovers:
  Android 13+ shows its dialog at most twice, so after two requests a denial is reported as
  `settingsRequired` (system Settings) instead of a button that would do nothing
  (`_androidDialogsBeforeSettings`). iOS offers Settings after its first denial. Returning from Settings
  refreshes the permission on resume and registers the phone if it was granted there.
- **Firebase missing or failed.** `_messagingRestored` is never set, nothing is asked and no count is
  written, so the next launch that can ask still does. Launch is never blocked.
- **Registration.** Unchanged and still gated on a signed-in session: a guest who grants is registered
  at sign-in (`_sessionChanged`), and a failed registration is retried with the existing button without
  asking the system again.
- **Copy.** `pushPermissionBody` no longer says Wassla asks only when you choose Enable. English,
  French and Modern Standard Arabic; the localizations are regenerated (`flutter pub get`).

## Files

- `mobile/lib/core/push/push_coordinator.dart`, `mobile/lib/core/session/token_store.dart`
- `mobile/lib/l10n/app_{en,fr,ar}.arb` and the regenerated `app_localizations*.dart`
- `docs/SHIPTRIP_V1_SPEC.md`, `docs/PUSH_NOTIFICATIONS_RUNBOOK.md`, this file,
  `docs/IMPLEMENTATION_STATUS.md`
- Tests: `mobile/test/k5_cold_start_test.dart` (new group, 16 tests, and the first-frame test now
  expects the prompt), `mobile/test/phase8fd_push_test.dart` (the contextual-only test is renamed to
  say what it still proves: the Profile screen asks only when its button is pressed),
  `mobile/test/k5_session_snapshot_test.dart` (the count survives every clear),
  `mobile/test/handover_isolation_test.dart` (the pinned list of storage keys gains
  `_kPushPermissionRequests`, a non-secret counter), `mobile/test/support/fake_api.dart` (in-memory
  count).
- `features/profile/notification_settings_screen.dart` and `main.dart` needed no change: the screen's
  button already goes through the coordinator, which now shares the request.

## Tests

New coverage in `k5_cold_start_test.dart`: guest first then sign-in (registers only at sign-in), sign
out and in again, restart after a denial, Android 13+ fresh install reading as denied, Profile retry
then Settings after two denials, an iPhone refusal, a denial no dialog can follow (Android below 13 or
permanent), prior authorized and provisional grants, return from Settings, a Firebase that never
started (two causes, nothing spent, next launch asks), registration retry without a second request,
startup + double resume + Profile button sharing one dialog, Profile asking before Firebase is ready, a
background launch, the splash not counting as usable (offline launch), and the first frame drawn before
anything asks.

Checks, run from `mobile/`: `dart format --output=none --set-exit-if-changed lib test`,
`flutter analyze --fatal-infos`, `flutter test` (the whole suite). Results are in the pull request.

## Screenshots

`docs/screenshots/n1/`, 360 px, English and Arabic, rendered with a throwaway golden rig (not
committed) over the real `NotificationSettingsScreen` with a fixed coordinator state:
`profile-notifications-<state>-<lang>.png` for `granted`, `granted-as-guest` (permission on, device not
yet registered), `denied-retry`, `denied-settings` and `not-asked`. The first-open prompt itself is the
operating system's own dialog: Wassla draws nothing for it, and it cannot be captured on this machine.

## Not checked here

- No device or emulator on this machine: the real Android 13+ dialog and the real iOS dialog were not
  seen. The permission statuses were driven through a fake messaging layer.
- `FirebasePushMessaging` itself is unchanged and is not exercised by the tests.
- No iOS or Android native config changed, so there is no platform config script to run for this
  package; CI's mobile job is format, analyze and test.

## Device checks still owed (human, real phones)

Android 13+ phone, fresh install of a configured release build:

1. Open the app as a guest: the system dialog appears once on the first usable screen, not on the
   splash. Deny it. Go to Profile > Notifications: the notice offers Enable notifications.
2. Tap Enable: the dialog appears a second time. Deny again: the screen now offers Open notification
   settings, and tapping it opens Wassla's notification settings. Turn them on and return: the screen
   reads enabled.
3. Kill and reopen the app: no dialog. Sign out and in as someone else: no dialog.
4. Fresh install, allow at first open as a guest, then sign in: the screen shows registering and then
   enabled; the device appears for that account.
5. Android 12 or older: no dialog at any point.

iPhone, fresh install:

1. Open as a guest: the iOS dialog appears once. Allow, sign in, and confirm registration.
2. Reinstall (keychain kept): the dialog appears again, because the OS status is undetermined.
3. Deny, then Profile > Notifications offers Open notification settings; grant there and return.

## Handoff to later packages

N2 (ticket decision in the bell) shares the ARB files and generated localizations: rebase and
regenerate from the merged tip. O3 (enable and prove push) can now rely on a first-open prompt, but must
still verify registration for the signed-in test account.
