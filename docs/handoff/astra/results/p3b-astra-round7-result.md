<!-- Astra 6.2, high effort, read-only. Run by Ismail on his second Codex account, 2026-11-27; pasted into the project thread and committed by the P3B builder. Head a286b34. Verbatim P3B section of a multi-PR paste. -->

I recommend rejecting PR #66 at a286b34 because a control still visible for A can delete B’s photo, and the account-deletion and private-document flows also permit wrong-account writes.

### Open round-3 findings

| # | Status | Note |
|---|---|---|
| 1 | Fixed | On the app’s declared Android launch path, a restored picker result reaches the plugin only if that activity owns an open pick. Starting or destroying an unrelated activity no longer resets the owner. |
| 4 | Partly fixed | Preparation and retry carry the original scope through dispatch. The remaining gap is at the first press, when the account on screen can differ from the account `_begin()` reads. |
| 5 | Fixed | File cleanup checks the operation’s epoch and the specific PickedPhoto. A late continuation cannot discard a newer operation’s distinct file. |
| 13 | Partly fixed | Android compilation, Kotlin tests and zero-picker assertions are present. The native fixture that prepares the same input twice and verifies both output files is still missing, as is an iOS build in PR CI. |

### Round-5 and round-6 findings

| # | Status | Note |
|---|---|---|
| R5-1 · Blocker | Fixed | The activity-owner check closes the reported cold-return and unrelated-activity startup cases. |
| R5-2 · Blocker | Partly fixed | The pre-publication interval, prepared-file retry and already-open removal dialog are guarded. A press on the previous member’s still-rendered control can acquire the new member’s valid scope. |
| R5-3 · Should-fix | Fixed | `_upload` verifies that the pending file is the exact selection its caller supplied. |
| R5-4 · Should-fix | Fixed | A failed pending-pick tombstone write no longer interrupts credential cleanup or suppresses the expiry callback. |
| R5-5 · Should-fix | Fixed | Each signed address reads its response independently. Only completed bodies queue for publication. |
| R5-6 · Should-fix | Fixed | A failed network body never reaches the filesystem. |
| R5-7 · Should-fix | Fixed | The app declares JUnit 4.13.2 and the Android CI job runs `:app:testDebugUnitTest`. |
| R6-1 · Blocker | Fixed | `refreshAccount` and `_updateProfile` reject the reported transition, check the returned account and scope, and pass the captured credential generation to the queued snapshot write. |
| R6-2 · Blocker | Fixed | A dialog opened while A is current retains A’s scope. Confirming after B signs in returns stale, sends no DELETE and shows no success message. |
| R6-3 · Blocker | Fixed | `singleTask` closes the reported ordinary second-task route. Both photo writes also check the account in the actual bearer selected for dispatch. |
| R6-4 · Should-fix | Fixed | Startup leaves the gate alone. `closed(owner)` clears only that owner, including from `onDestroy`. |
| R6-5 · Should-fix | Fixed | The guard rechecks credentials and proceed immediately after `opened`, inside the finally that announces `closed`. A missing Android handler stops the pick. |
| R6-6 · Should-fix | Partly fixed | An isolated bad-password response leaves A able to act. The recovery still assumes that the published member owns the stored credentials, and storage errors bypass recovery entirely. |
| R6-7 · Should-fix | Fixed | A stale DELETE error calls `_abandon(launch)`, releasing `removing` when the operation still owns the state. |
| R6-8 · Should-fix | Fixed | `_publish` owns the path, awaits both the byte write and the record write, and attempts to delete the file on either failure. |
| R6-9 · Should-fix | Partly fixed | Group 1 now waits at the role-context write and exercises all four actions. Its fake discards both credentials and always returns `access-token`, so it never establishes the requested precondition that B’s bearer is actually stored while A is published. (Test setup · Fake store) |

### New findings

| Severity | File and line | Concrete failure | Suggested fix |
|---|---|---|---|
| Blocker | `profile_photo_section.dart:55` · Dismiss callback:207 | A’s removal notice can still be on screen when B is published. A tap delivered before the next Flutter rebuild invokes A’s Dismiss callback, but `_begin()` reads B. Dismiss skips confirmation, so the DELETE carries B’s valid scope and bearer and removes B’s active photo. Every downstream check passes. | Bind the callback to the scope used to render the control and validate it at the press. Test a tap after publishing B and before pumping the next frame. |
| Blocker | `session.dart:480` · credential writes:127 | B can save credentials and still be awaiting role-context storage when another sign-in starts and fails. The catch republishes the previously visible A under the newest generation, although storage holds B. `beginAction()` now accepts A. The photo bearer check refuses A’s photo writes, but `PATCH /api/me` can change B before the response-ID check drops the answer. Starting from the sign-in screen as a guest also exposes the inconsistency: the UI can remain signed out while the next launch restores the overtaken login. | Track which account actually committed its credentials. Serialize credential replacement and session publication, or reconcile the stored owner before recovering a failed attempt. Exercise an overtaken successful save followed by a refusal and a restart. |
| Blocker | `discovery_state.dart:277` · `public_profile_screen.dart:64` | The public-profile writer checks only `photoWrites`. During the tested interval with A displayed and B’s bearer saved, A’s Home opt-in can record public-profile consent for B. The route editor also retains A’s route list across two city pickers and can submit that list to B’s `/api/discovery/profile/me`. | Capture the displayed member’s scope before opt-in or the first city picker. Bind the PUT to that scope and recheck it before applying the response. |
| Blocker | `kyc_screen.dart:145` · KYC upload:2257 · cheque upload:162 | The shared picker returns a bare XFile. A’s selected ID and selfie stay in the KYC form across a direct signed-in account change. Submitting reads the current bearer after opening the files, so the documents can be sent as B’s KYC submission. The cheque form likewise retains A’s file and bank fields and can start its proof upload under B. | Give each private form and its selected files a member scope. Clear the form when ownership changes and pass the original scope through multipart construction and each subsequent write. |
| Blocker | `delete_account_screen.dart:69` · server deletion checks:183 | The existing account-deletion dialog has the same ownership gap that this round fixed for photo removal. A opens it, B signs in, and confirmation posts to `/api/me/deletion` with B’s bearer. For an eligible Google-only B with no password, Apple identity or deletion blocker, the server deletes B. The existing sign-out dialog also acts on the member current at confirmation. | Capture scope before each dialog. Bind deletion and sign-out to that scope, and clear local credentials after deletion only if the same session still owns them. |
| Should-fix | `session.dart:469` · `token_store.dart:133` | If secure storage fails deleting the old snapshot, neither token has changed. A is still legitimately signed in, but the generation already advanced and the platform exception bypasses `on ApiException`. Every new photo action and `refreshAccount()` now silently returns until another login or restart. A role-context storage error after token replacement strands the transition on the other side of the save. | Handle storage failures according to whether credentials committed. Recover the verified owner or end the local session explicitly. Treat the role preference as recoverable independently of authentication. |
| Should-fix | `session.dart:599` · `language_screen.dart:79` | A refused profile update completes normally when `beginAction()` returns null. The language screen announces that the preference was saved despite sending zero PATCH requests. The account-name screen likewise leaves the form as though the name had been saved. | Return an explicit stale result and show success or leave the form only after an applied update. |
| Should-fix | `profile_photo_section.dart:82` | If the session expires with the source sheet open, Profile can stay visible as a guest while its photo section is disposed. Choosing a source then enters `_pick`, which reads `L.of(context)` from the disposed state before checking ownership. | Check `mounted` immediately after the sheet returns, before calling `_pick`, as the removal dialog already does. |
| Should-fix | `profile_photo_section.dart:207` · `photos.py:383` | Even with the correct member, Dismiss sends an unconditional DELETE. If the member uploads a replacement on a second device while the first still shows the moderation notice, dismissing that old notice deletes the replacement. | Retain the removed version supplied by `/api/me` and make dismissal conditional on that version still being in the removed state, or dismiss that specific notice locally. |

### What I could not check

`git fetch origin` succeeded. `git ls-remote` independently confirmed that both the branch and PR head point to a286b34146e6f83e47a99d25270f75965d95c687. I reviewed ead30e2..a286b34 and origin/main...a286b34. The handoff records all 12 checks green. I did not rerun builds or tests during this read-only review.

On the ordinary single-store path, separate successful logins get distinct scopes, restore carries its captured identity into `_confirm`, and token refresh preserves the generation. The interceptor accepts integer and numeric-string `user_id` claims, checks the same local token string it attaches, and honors `noReplay` for uploads on both 401 refresh paths. The existing Dart test edits preserve the expected outcomes. The pre-response helper now short-circuits at `beginAction()`, and the Kotlin reset test was replaced with owner/destruction cases.

I found one declared Android UI activity, a launcher filter, inherited Flutter intent handling and no app-declared VIEW deep-link filter on `MainActivity`. An ordinary camera or library return uses `onActivityResult`. I could not verify launcher re-entry, notification taps over an open picker, multi-window delivery, process death or retained-engine recreation on a device. I found no configured retained UI engine that would establish a stranded Dart picker future after activity destruction. I also did not compile Swift or inspect a device-produced JPEG.

Overall verdict: reject
