You are an independent second-pass reviewer. This review is read-only: do not write, commit or push code, and do not comment on GitHub. You may read files and run read-only git commands.

Review pull request #71, "N1: ask for notifications once on first open", in this repository (is-bo/shiptripis), at head `3e7fc1780878b3e017a9dd9f921a90774346142b` (round 5; round 4 was `227d8aa`, round 3 `b200577`, round 2 `5372776`, round 1 `6f1b858`). Use a three-dot diff against `origin/main`, and run `git fetch origin` first if the commit is missing.
- The Flutter app is under `mobile/lib/`.
- The rules are in `CLAUDE.md`, especially "Mobile rules" and the rule that strings must exist in EN/FR/MSA.
- The package is section 4 "N1" of `docs/WASSLA_PHONE_TEST_2_PLAN.md`, and the finding is section 1.2.
- The write-up is `docs/PHASE_N1_NOTIFICATION_FIRST_OPEN.md`.
- The screenshots are in `docs/screenshots/n1/`.

## Round 5
Your round-4 result (`docs/handoff/astra/results/n1-astra-round4-result.md`, reject at `227d8aa`: 2 blockers,
7 should-fixes, 1 nit) is answered by two code commits: `0cd1330` (the round) and `64a3283` (a
verification pass that closed one more path of blocker 2's family). The pinned head `3e7fc17` is
`64a3283` plus a merge of `main` that brought documentation only. **CI completed green on the pinned
head, every check included ("Schema drift", Flutter, the Django shards and their "Every shard passed"
step, and VPS readiness): https://github.com/is-bo/shiptripis/actions/runs/46016246273.** The one commit after it adds only this section. Each fix below has a
test that fails with the fix removed (checked by mutation); the phase doc lists them under "Tests".

**Review rules for this round (the owner's anti-loop rule, `docs/handoff/COORDINATOR.md` section 3).**
1. **Legacy and upgrade findings are not applicable.** The app has never been live and has no users:
   rows written by older code, old app versions, tokens or URLs issued before the change and migrations
   of old data are out. Do not report them.
2. **Out-of-scope findings go to a follow-up note, not into N1.** N1's scope is the first-open prompt and
   what your rounds 1 to 4 pulled in: registering the phone to the right sign-in, and switching it off
   when that sign-in ends. Report anything else in a separate table headed "Out of scope (follow-up)",
   and do not let it decide the verdict.
3. **Fixes go to the root cause.** If you find a new variant of a family already raised, say which family
   and which part of the design still allows it, rather than the single case.

**Blocker 1 (a sign-in issued after a reset, claim or deletion it should have been subject to).** The
root: the credential check and the sign-in row were separate operations. Now `User.session_epoch`
(folded into the still-unmerged `accounts.0008`) counts the account-wide ends. `end_all_sessions` moves
it under `lock_account`, in the same transaction as the reset's new password, the claim's unusable
password or the deletion. `start_session` creates the row only if, under that same lock, the epoch still
equals the one the credential check read (`SignInInterrupted` otherwise), and `_sign_in`
(`apps/accounts/views.py`) checks the credentials once more: an old password then fails (400), a
provider identity that still owns the account signs in, and a second end in that instant answers `409
sign_in_interrupted`. Check that **every** token issuer goes through `_tokens_for_user` -> `start_session`
(password, Google, Apple, sign-up; we found no other in Django or Go) and that every account-wide end
moves the epoch in the transaction that changes the credentials. Tests:
`test_l18a_sessions.py::SignInDuringAnEndTests`, each across a real reset or claim.

**Blocker 2 (the phone shows signed out while its server device stays on).** The root: the server
switched a phone off only when a sign-out request reached it with a proof it accepted, and the app sent
that request from one place only.
- Server, `0cd1330`: `SignOutView` is `AllowAny` with `_AccessIfValid` (an expired access token is no
  answer instead of a 401). `_proven_sign_in`: a valid access token proves its own `sid`, whatever
  refresh token comes with it; otherwise a refresh token proves its `sid`. Nothing is blacklisted or
  changed before the sign-in is known, and `end_session` is idempotent (205 again).
- `64a3283`: the refresh token proves its sign-in when **this server signed it, whatever its age or
  rotation** (`_signed_claims`: signature checked, expiry not). All it can do here is end the sign-in it
  names, of the account it names; a token signed with another key is refused. And the app's other exit
  now sends the sign-out too: when renewing a sign-in fails, `_AuthInterceptor._endSession`
  (`mobile/lib/core/api/api_client.dart`) clears the credentials and then sends `POST /api/auth/sign-out
  {refresh}`, best-effort, with **no bearer** (the stored credentials may already be those of a sign-in
  made since). Before this, a refresh token that expired while the app went unopened (30 days), or one
  rotated by an answer that never arrived, left the sign-in live and the phone on.
- Still best-effort, by the V1 spec ("logout disables that installation best-effort") and as you
  accepted in round 4: a sign-out that never reaches the server (offline) leaves the phone on until it
  signs in again or the account's sign-ins end. Phase doc, device check 7; runbook.
- Tests: `test_push.py` (expired access, rotated refresh, both, an expired refresh alone, a lost
  rotation alone, nothing provable including another key's signature, a repeat);
  `phase8ff4_session_test.dart`, group "a session the app lets go of" (ended on the server by its refresh
  token alone; a sign-in made at that instant never lends it its bearer; a failing sign-out still signs
  out).

**Should-fixes and the nit, in your table's order.** Cross-account sign-out: ownership is known before
anything changes, and the test also proves the other account can still refresh. Unregister:
`unregister_push_device` checks liveness first and uses `refuse_stale=True` (a late lower number is 409
and the newer registration stays on). Queued FCM job: the Go sender asks the database right before each
send or retry which devices are still on for the recipient with the same token fingerprint
(`DeviceRegistry`, `PostgresDevices` in `services/internal/notification/fcm_devices.go`, required by
`NewConsumer`); none left drops the entry, a database error leaves it pending. Permission loss and the
token refresh with a failing keystore write: `push_coordinator.dart`. Inactive receipt: an exact repeat
whose device is off is refused as superseded, and the phone reads `active` from the receipt. WebSocket:
`wsproto.Upgrade` closes the connection at the token's expiry plus the 30 s leeway, and the validator
requires `exp`. Nit: guest copy when push cannot start (`pushPermissionUnavailableGuest`,
`pushPermissionInitializationFailedGuest`, EN/FR/MSA) and the guest screenshots recaptured.

**Already found outside N1 (on the follow-up list; do not report again):** a renewal that fails on the
network (not refused) also signs the member out on the phone, as before N1; a ban ends none of the
member's sign-ins and switches off none of their phones.

Ismail pastes your result back; it is committed as `docs/handoff/astra/results/n1-astra-round5-result.md`.

## Round 4
Your round-3 result (`docs/handoff/astra/results/n1-astra-round3-result.md`, 4 blockers, 5 should-fixes, 1
nit) is answered in the phase doc ("Registration order", "Files", "Tests"). Rounds 2 and 3 patched each
case and new variants kept appearing, so round 4 replaces the mechanism rather than adding a fifth patch:
1. **One server row per sign-in.** `SignInSession` (`apps/accounts/models.py`, migration `accounts.0008`)
   is created when tokens are issued (`_tokens_for_user`); every token of the sign-in carries its id as
   `sid`, rotation included. `/api/auth/refresh` uses `SessionTokenRefreshSerializer`
   (`apps/accounts/sessions.py`), which refuses an ended sign-in. A push registration needs the sign-in
   live, checked under `lock_account` (`apps/accounts/locks.py`), the lock sign-out (`end_session`) and
   `end_all_sessions` take first; `PushDevice.session` is now a foreign key. `PushAccountRevocation`, the
   `iat` cutoff and the outstanding-token blacklist loop in `end_all_sessions` are gone. Check the lock
   order (account, then installation binding, then devices) on all four paths (register, sign-out,
   unregister, end-all), the refresh race (a refresh that passes the check just before the sign-in ends
   yields tokens of an ended sign-in: can any of them still do harm?), and that no other token issuer
   bypasses `_tokens_for_user`.
2. Blocker 1: sign-out ends the sign-in and switches off **every** device it registered, whether or not
   the body names an installation or a number. Blocker 2: no time comparison remains. Blocker 3: real
   sign-in, two rotations, reset, then the rotated refresh and its access token (`test_l18a_sessions.py`,
   `RotatedSignInTests`). Blocker 4: the sign-in is part of the exact-repeat identity
   (`PushInstallationBinding.session_id`), and an acknowledged repeat returns the binding unchanged (a
   repeat whose device is gone is refused so the app registers again).
3. Migration `notifications.0009` deletes push devices that predate sign-in rows (they name none; no real
   users, CLAUDE.md). Tokens that name no sign-in no longer refresh, so every tester signs in once more.
4. Phone: `_syncRegistration` checks `overtaken()` (account, newest attempt, signed in) after every await
   and before numbering, sending or publishing; a failed `raisePushBindingSequence` during the 409
   catch-up leaves `failed`; the retry starts only if still newest, and `_syncRegistration` refuses a
   stale `expectedGeneration` at its top. The Profile button passes `onScreen` (`ModalRoute.isCurrent`),
   checked after the count write. A request started from `deniedRequestable` on Android records
   `afterDenial` (count at least two). Guest denial copy `pushPermissionDeniedRequestableGuest`.
   Should-fix 5 (offline sign-out) is handled as Astra suggested option 1: the device checklist now
   matches the best-effort contract and states the exposure (phase doc, device check 7; runbook).
5. Tests: each blocker and each should-fix has a test that fails with its fix removed (checked by
   mutation; the phase doc lists them and the tests rewritten because their rule changed).

## Round 3
Your round-2 result (`docs/handoff/astra/results/n1-astra-round2-result.md`, 6 blockers and 7 should-fixes)
is answered in the phase doc ("Registration order", "What changed", "Tests"). Verify each fix is real and
complete, and hunt for what it broke:
1. **Blocker 1 (old app, no `binding_sequence`) is declined, on purpose**: CLAUDE.md says there are no real
   users and nothing is spent on old clients. Registration still requires the number; sign-out accepts it
   as optional and ends the device by session. Say if you still consider that a blocker given the rule.
2. Blockers 2-4, 6: the server design is `session_id` on `PushDevice` (copied from the `sid` claim of the
   access token; rotation copies it), `PushInstallationBinding` with operation, owner and token
   fingerprint, and `PushAccountRevocation` locked with the user row (`apps/notifications/push.py`,
   `apps/accounts/views.py`, `apps/accounts/sessions.py`). Check the lock order, the exact-repeat rule,
   the late/low sign-out paths, the revocation by `iat`, and that no new race exists between a
   registration and `end_all_sessions`.
3. Blocker 5 and the phone-side should-fixes: one installation ID (`TokenStore.readOrCreateInstallationId`
   in the phone write queue), sign-out sent without the number when it cannot be prepared, the
   newest-attempt check in `_syncRegistration`, `RouteTransitionTracker` and the wait in
   `_askOnFirstOpen`, the foreground recheck of the Profile button, the durable count for the automatic
   prompt, `notDetermined`-only automatic asks (Android upgrade after a pre-N1 denial), and the
   first-dialog dismissal read (one request + permanent = requestable).
4. Tests: the two registration-retry tests are back to HTTP 500; the phase doc lists every rewritten
   test and why. New tests were checked to fail when the fix is removed.

Unchanged from earlier rounds: the owner decision, the platform logic and the hunting list below still
apply; the "second denial" text under "What N1 claims" is superseded by the phase doc.

## Round 2
Your round-1 review rejected `6f1b858` with six findings; round 2 answers them (phase doc, "Registration order" and "What changed"). Verify each fix is real and complete, and hunt for what it broke:
1. Late registration rebinding the phone: the app numbers registrations and sign-outs per installation, and the server (`PushInstallationBinding`, migration `notifications.0009`, `apps/notifications/push.py`) refuses a lower number with 409. Check races, the row lock, sign-out before first registration, idempotent repeat, the catch-up path (`current_sequence`) and its retry bound.
2. Prompt timing: post-frame checks on route changes, deferral over splash, `/auth/`, the guest payment screen and a pending deep link, one frame awaited before the request.
3. Foreground: `resumed` only, count taken back when the system was never reached, two failures per run at most.
4. Android `notDetermined` with a spent count; iOS exception kept.
5. The count rule for Settings is removed; the system's `deniedPermanently` decides.
6. Guest Profile Notifications row, public `/profile/notifications`, guest variant of the screen, new copy in EN/FR/MSA.
Also check that no test was weakened (phase doc lists the four rewritten ones).

## Owner decision (treat as correct)
The app asks for notification permission once, by itself, on the first usable foreground screen. That is after first paint and messaging initialization, and it includes a guest. Registering the device to an account needs sign-in, and only happens after a grant. A denial leaves the app usable, and there is no automatic re-prompt.

## What N1 claims
- **One coordinator.** The prompt lives in the app-wide push coordinator. Startup, resume and the Profile button share one in-flight request.
- **Install count.** A per-installation OS-request count sits in `core/session/token_store.dart`. It is written before asking, and it survives logout and account changes.
- **Android 13+.** The count plus the OS status decide the prompt. After the second denial, the app offers system Settings, because Android stops showing the dialog. This is the builder's own addition.
- **Android below 33.** No dialog.
- **iOS.** The app asks whenever the status is undetermined, regardless of the count, because the keychain survives a reinstall.
- **Firebase failures.** Missing or failed Firebase asks nothing and spends nothing.
- **Grant in Settings.** Returning from Settings with a grant registers the device.
- **Rewritten tests:** `phase8fd_push_test.dart`, `k5_cold_start_test.dart`, and the storage-key list in `handover_isolation_test.dart`.

## What to hunt for (concrete failures only)
1. **Double or missing prompts.** Look for races between startup, resume, the Profile button and session resolution. Check:
   - a prompt over the splash, a sign-in sheet or a deep link;
   - a prompt while the app is backgrounded;
   - no prompt ever, for example when the count is written but the OS call never happens because of a crash or an exception between the write and the request.
2. **Registration correctness.**
   - A guest grants and then signs in.
   - Account A grants, then account B signs in on the same phone.
   - The device must never be registered to the wrong account or while signed out.
   - Check sign-out cleanup.
3. **Platform logic.**
   - Android 13+ before the first request reports a requestable denial.
   - Check permanent denial, the provisional and authorized states on iOS, the second-denial rule, and the Settings return.
   - Check the keychain or secure-storage behaviour of the count on both platforms.
4. **Privacy and storage.** Is the new storage key safe to keep across accounts? Does the handover isolation test still protect secrets?
5. **UX and copy.**
   - EN/FR/MSA copy, and "Wassla" in Latin script.
   - The Profile states at 320–360 px in RTL, with nothing hidden behind the bottom navigation.
6. **Tests.** Do the rewritten tests still assert real behaviour? Does anything rely on fake timing that hides a race?

## Output format
- One opening sentence.
- A table: Severity (Blocker / Should-fix / Nit) | File and line | Concrete failure | Suggested fix.
- What you checked and found sound, and what you could not check.
- Final line: "Overall verdict: approve" or "Overall verdict: reject".

Report only real, reachable problems. No style opinions.
