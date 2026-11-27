You are an independent second-pass reviewer. This review is read-only: do not write, commit or push code, and do not comment on GitHub. You may read files and run read-only git commands.

Review pull request #71, "N1: ask for notifications once on first open", in this repository (is-bo/shiptripis), at head `227d8aa31f2cfdd60ad928c1fa50d71a862bf5b2` (round 4; round 3 was `b200577`, round 2 `5372776`, round 1 `6f1b858`). Use a three-dot diff against `origin/main`, and run `git fetch origin` first if the commit is missing.
- The Flutter app is under `mobile/lib/`.
- The rules are in `CLAUDE.md`, especially "Mobile rules" and the rule that strings must exist in EN/FR/MSA.
- The package is section 4 "N1" of `docs/WASSLA_PHONE_TEST_2_PLAN.md`, and the finding is section 1.2.
- The write-up is `docs/PHASE_N1_NOTIFICATION_FIRST_OPEN.md`.
- The screenshots are in `docs/screenshots/n1/`.

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
