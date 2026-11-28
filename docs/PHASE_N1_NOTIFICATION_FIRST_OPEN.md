# N1: notifications on first open, sign-in sessions and who a push belongs to (2026-11-27)

Package N1, pull request #71, branch `claude/n1-notification-first-open`. The app asks for notification
permission on its own, once, the first time it is opened on a usable screen, guests included (Ismail,
2026-11-26). Making that safe needed a server that knows which sign-in a phone belongs to. Migrations
`accounts.0008` and `notifications.0009` (no existing data), `contracts/sql/schema.sql` regenerated.
Nothing deployed. Round history is in git and in `docs/handoff/astra/results/`.

## The phone

- **When it asks** (`core/push/push_coordinator.dart`). After a frame, with Firebase started and the
  first permission read settled, the session resolved to a guest or a member, the app resumed, and the
  top route neither the splash, an `/auth/` screen, the guest payment screen nor a notification still
  opening. `RouteTransitionTracker` (`app/route_transition_tracker.dart`) makes it wait until a leaving
  screen has finished its exit. The conditions are checked again just before the system call.
- **Which status asks.** Only `notDetermined`. On Android only when this installation has made no request
  yet (`TokenStore` key `push.permission_requests`, written to disk before the system is asked and taken
  back when the system was not reached); a requestable denial with no count (an upgrade) is not asked.
  `requestPermission()` is single-flight, so first open, resume and Profile share one dialog.
- **Recovery.** Nothing asks again on its own. Profile > Notifications (now public, for a guest too)
  offers Enable or Open settings; a first Android dialog swiped away keeps Enable. Guests see the phone's
  permission only and are told that account notifications come with signing in. New strings in EN, FR
  and MSA (`pushPermissionEnabledGuest`, `pushGuestSignInNote`, `pushPermissionDeniedRequestableGuest`,
  `pushPermissionUnavailableGuest`, `pushPermissionInitializationFailedGuest`).
- **Registration** waits for sign-in. One installation ID per phone; each registration takes the next
  number of one counter (`push.binding_sequence`, only grows, kept through logout). Only the newest
  attempt may settle state or clear the pending token; behind the server, the phone raises its counter
  to `current_sequence` and registers once more. The app reads `active` from the receipt. It sends
  Firebase's current token, the one a refresh carried only when Firebase has none.
- **Leaving a sign-in.** The Sign-out button, and a session dropped because renewing it failed, send
  `POST /api/auth/sign-out` best-effort. N1 does not change how the phone exits (S1 replaces that code);
  the installation ID and number the phone still sends with a sign-out are no longer read.

## The server

- **A sign-in is a row** (`SignInSession`, `apps/accounts/sessions.py`). Every token carries its id as
  `sid`, rotations included. A refresh and a push registration need the sign-in live; each device records
  the sign-in that registered it (`PushDevice.session`). `start_session`, `end_session` and
  `end_all_sessions` work under the account row lock (`lock_account`). `User.session_epoch` counts
  account-wide ends and has one writer, `end_all_sessions`; a sign-in whose credentials were checked
  before an end is not issued (`SignInInterrupted`, then one more check, then `409 sign_in_interrupted`).
- **Sign-out contract** (`apps/accounts/views.py` `SignOutView`, `_proven_sign_in`). 205 when the proof
  is a valid access token (its own sign-in) or a refresh token this server signed, whatever else is true
  of it: live, already ended, expired, rotated, or of a deleted account. After a 205 the sign-in is ended
  and every device it registered is off; a repeat answers 205 and writes nothing. A proof that cannot be
  verified as ours, or none, answers `400 sign_out_proof_invalid` (the 401 is gone). Only the signature
  counts, not the expiry or the issue time; the throttle is its own roomy scope (`sign_out`), apart from
  the shared guest quota; an account deleted mid-request answers 205.
- **The sign-in row decides (N-B).** `end_session` writes nothing when the sign-in is not live, and
  otherwise switches off only that sign-in's devices (`deactivate_session_push_devices`). A sign-out
  records nothing in `PushInstallationBinding`, which now holds registrations and unregisters only (its
  sign-out operation is removed). Registration and unregister both check, under the account lock, that
  their sign-in is live before they write the installation's order. A number below the stored one is
  refused (`409 push_registration_superseded`); the same number is an exact repeat only for the same
  operation, owner, sign-in and token.
- **Credentials have named writers (N-D).** `write_password` (`sessions.py`) sets a password, or makes
  it unusable, and for an existing account ends every sign-in in the same transaction, under the lock.
  Its callers: the reset, sign-up, the Google and Apple account paths, account deletion, the invitation
  of a new staff member, the bootstrap command, and both of Django's admin password forms (a member's,
  and an operator's own at `/admin/password_change/`), which save through `_WritesPassword`
  (`accounts/admin.py`). Every save of an existing user names its fields. No override of `User.save()`.
- **The technical admin** (`apps/accounts/admin.py`) saves an existing user with
  `update_fields` = the model fields in `form.changed_data`, never `password` or `session_epoch`. Staff
  rights are read only there (decision D5), with one line saying where they change:

  | Field | Where it changes, audited |
  |---|---|
  | `is_staff` | the invitation (`accept_admin_invitation`), `change_admin_role` |
  | `is_superuser` | `change_admin_role`, the `bootstrap_super_admin` command |
  | `groups` | `change_admin_role` and the invitation (`assign_admin_roles`) |
  | `is_active` | `set_admin_access` for staff; account deletion for a member |
  | `user_permissions` | no console action: stays editable (reported to the lead) |

## The Go notification worker (N-F)

A queued push (`enqueue_fcm_for_event`) carries, per device, the sign-in that registered it
(`session_ids`, aligned with the tokens; a payload that does not align is refused). Before each send and
each retry, `PostgresDevices.StillBound` (`services/internal/notification/fcm_devices.go`) keeps a device
only if it is still active for the recipient with the same token fingerprint and the same sign-in. A
device rebound to another sign-in, of the same member or another, gets nothing. None left: the entry is
acknowledged and dropped. The database cannot answer: the entry stays pending for the sweeper. A
notification WebSocket closes when the token that opened it stops being valid (expiry plus 30 s, G2).

## Evidence

| Finding or rule | Test | Red at | Green at |
|---|---|---|---|
| Round 5 blocker 1: the technical admin's full-row save writes back the old hash and epoch | `test_credential_writers.py::TechnicalAdminSaveTests::test_a_form_read_before_a_reset_keeps_the_new_password_and_epoch` (real sign-in and real refresh) | `53af659` | `65b90c2` |
| Round 5 should-fix: a repeated sign-out of an ended sign-in advances the order | `test_sign_out.py::SignOutWritesTests::test_a_repeated_sign_out_of_an_ended_sign_in_writes_nothing` | `53af659` | `f22040c` |
| Sign-out contract: live, expired, rotated, deleted account, unverifiable, none, repeat writes nothing | `test_sign_out.py::SignOutContractTests` (10) | new rule | `f22040c` |
| N-B: ended by a reset, late sign-out after B registered, registration after its sign-out, two sign-ins of one account | `test_sign_out.py::SignOutWritesTests` | new rule | `f22040c` |
| N-B: an unregister against a newer register, from an ended sign-in, sharing a number | `test_push.py` (`late_unregister`, `unregister_from_an_ended_sign_in`, `sharing_a_number_with_an_unregister`) | | `f22040c` |
| N-D: form changes only what it changed; a POST of a staff right changes nothing; the password form ends every sign-in | `TechnicalAdminSaveTests` (4 more) | | `65b90c2` |
| N-D: each converted save holds against a concurrent change of another field | `NamedFieldSaveTests` (reset, deletion, provider claim, invitation, bootstrap) | | `65b90c2` |
| N-D scans: a whole-row save of a loaded user; `password` or `session_epoch` written outside their writers | `conftest.py::_a_loaded_user_is_saved_by_name` (every test); `CredentialWriterScanTests` | mutation | `65b90c2` |
| N-F: a queued push names each device's sign-in | `test_push.py::test_a_queued_push_names_the_sign_in_of_each_device` | `d830d22` | `621cf4d` |
| N-F: the row as it is now; same member new sign-in, other member, off, token rotated | Go `TestPostgresDevicesKeepAPushToItsSignIn` (integration, real PostgreSQL) | `d830d22` | `621cf4d` |
| N-F: a retry is checked again, with its sign-in | Go `TestFCMChecksARetryAgainWithItsSignIn` | | `621cf4d` |
| Final review, Blocker C: the admin site's own password form saves the whole row and ends no sign-in | `TechnicalAdminSaveTests::test_the_site_password_form_ends_every_sign_in`, `::test_a_reset_during_the_site_password_form_keeps_the_epoch_moving` | `a5d5e57` | `2db6cf7` |
| Final review: a genuine proof read by a clock a few seconds behind; the shared guest quota spent; the account deleted between the two lookups | `SignOutContractTests` (3 tests) | `a5d5e57` | `2db6cf7` |
| Final review: a late repeat of a replaced Firebase token | `n1_notification_recovery_test.dart` "a late repeat of a replaced token registers the current one" | `a5d5e57` | `2db6cf7` |
| Socket expiry stays | Go `TestUpgrade_ClosesWhenTheTokenExpires`, `TestUpgrade_RefusesATokenWithoutExpiry` | | kept |

Mutation: the scan guard fails at a whole-row save put back into `deletion.py`, with that path's
concurrent-change test. The phone's prompt and registration tests were each checked to fail with their
fix removed in earlier rounds.

## Tests removed or rewritten, against `main`

- `test_auth.py::SignOutTests`: `test_blacklists_refresh_token` pinned blacklisting, now the sign-in row
  ends and its refresh is refused; `test_missing_refresh_returns_400` is now "a valid access token alone
  is a proof" (205) and "no proof is 400 `sign_out_proof_invalid`". Moved to `test_sign_out.py`.
- `test_push.py::test_valid_logout_disables_current_installation` switched a device off by the
  installation in the body; the device is now switched off because its sign-in ended (in
  `test_sign_out.py`). The unregister test uses the next number, as the app's counter would.
- Server: the account-deletion test asserts the sign-in ended instead of a blacklist; the K7
  speed-budget test mints its tokens through a real sign-in, outside the counted queries; device
  fixtures elsewhere now carry the sign-in that registered them.
- Phone: "a refreshed token the keystore cannot keep" now makes the fake Firebase hold the new token, as
  the real one does once it hands a refresh over. The first-open tests run on a real router; the "Profile only" and "Android fresh install reads
  as denied" rules were replaced; `egs_guest_mode_test.dart` now pins `/profile/notifications` as
  public; the two registration-retry tests use an HTTP 500 again.

## Screenshots

`docs/screenshots/n1/`, 360 px at 2x, English and Arabic: guest Profile, the guest Notifications screen
(`not-asked`, `denied-retry`, `denied-settings`, `granted`, `push-failed`) and the member's screen. The
first-open prompt is the system's own dialog and cannot be captured here.

## Not checked here

- No device or emulator: the real Android 13+ and iOS dialogs were not seen. Owed on real phones: first
  open as a guest asks once, not on the splash; deny, swipe away and Settings recovery from Profile; kill
  and reopen asks nothing; Android 12 and older never asks; sign out online stops notifications, and a
  new sign-in on the same phone moves them; iPhone reinstall asks again.
- Known windows: a sign-out made offline never reaches the server, so the phone keeps receiving until it
  signs in again or the account's sign-ins end; an access token outlives its sign-out for its lifetime
  (5 minutes plus 30 s) on HTTP, but cannot refresh, register or keep a socket.

## Follow-ups, outside N1

- `POST /api/notifications/devices/unregister` has no caller in the app: it and the binding's
  `operation` column could go in a cleanup.
- `manage.py changepassword` (Django's own command, unused here) saves the whole row and ends no sign-in.
- A password check that rehashes an old hash could write it back if a reset races a sign-in during a
  hasher change (Django's `check_password` setter).
- A renewal failing on the network signs out on the phone (S1, S2). A ban ends none of the member's
  sign-ins.
- The Go worker can still hand a push to Firebase when a reset commits between its device check and the
  handoff (the same on `main`; final review, out of scope).
