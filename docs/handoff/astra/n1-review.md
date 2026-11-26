You are an independent second-pass reviewer. This review is read-only: do not write, commit or push code, and do not comment on GitHub. You may read files and run read-only git commands.

Review pull request #71, "N1: ask for notifications once on first open", in this repository (is-bo/shiptripis), at head `6f1b858fd1c8b062a79909814a1cd808e4000dea`. Use a three-dot diff against `origin/main`, and run `git fetch origin` first if the commit is missing.
- The Flutter app is under `mobile/lib/`.
- The rules are in `CLAUDE.md`, especially "Mobile rules" and the rule that strings must exist in EN/FR/MSA.
- The package is section 4 "N1" of `docs/WASSLA_PHONE_TEST_2_PLAN.md`, and the finding is section 1.2.
- The write-up is `docs/PHASE_N1_NOTIFICATION_FIRST_OPEN.md`.
- The screenshots are in `docs/screenshots/n1/`.

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
