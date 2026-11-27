You are an independent second-pass reviewer. This review is read-only: do not write, commit or push code, and do not comment on GitHub. You may read files and run read-only git commands. Run `git fetch origin` first. If `git fetch` cannot write `.git/FETCH_HEAD`, say so and verify the SHAs through `git ls-remote origin`.

This is the **seventh review** of pull request #66, "P3B profile photos in the app", in this repository (is-bo/shiptripis). The new head is `a286b34146e6f83e47a99d25270f75965d95c687` (branch `origin/claude/p3b-profile-photos-app`). All 12 CI checks are green on it, including the job "Android — compile and Gradle unit tests".

- You rejected the previous head, `ead30e206ad702cf2ea91cedb95cf9704c778a7b`, with 3 blockers and 6 should-fixes. Your report is `docs/handoff/astra/results/p3b-astra-round6-result.md` on `main`.
- The builder's answer to each finding is the "Round seven" section of `docs/PHASE_P3B_PROFILE_PHOTOS_APP.md` at the new head.
- Compare `ead30e2..a286b34` for this round (a merge of `main` in it only brought documents), and `origin/main...a286b34` (three dots) for the whole package.
- The rules are in `CLAUDE.md` ("Mobile rules"). The server contract is spec section 21 of `docs/WASSLA_DISCOVERY_PRO_SPEC.md` and `backend/monolith/apps/accounts/photos.py`.

## What changed, and the design to judge
Every round found one more way for an action of member A to land on member B while one replaces the other. The builder says the cause was that an action read "who am I" more than once, from places that move at different moments (the published account, the token store's generation, the bearer in storage), and that this round fixes the cause:

- `SessionNotifier.beginAction()` (`mobile/lib/core/session/session.dart`) captures one immutable `MemberScope` (`member_scope.dart`): account id, `SessionSignedIn.generation` and `SessionSignedIn.identity`. It answers null when nobody is signed in **or when the published account's credentials are not the store's current generation** (a sign-in is replacing it). `isCurrent(scope)` is the one commit-time check (state signed in, same account, authentication and credentials, and the store's generation equal).
- Used by: `refreshAccount` and `_updateProfile` (and the snapshot write, under the scope's credentials), `uploadPhoto` and `removePhoto` (`_updatePhoto`), the profile photo controller (`profile_photo_state.dart`: `_Launch = (scope, epoch)`, `PickedPhoto.scope`, `pick(source, scope)`, `remove(scope)` answering `ProfilePhotoRemoval`), and the screen (`profile_photo_section.dart`), which takes the scope when the member first touches a control, **before** the sheet or the confirmation dialog.
- The two writes that send a bearer name their account (`ApiClient.upload` and `deleteVoid`, `expectedAccount`), and the request interceptor refuses a bearer whose `user_id` claim (`mobile/lib/core/api/bearer_account.dart`) is another account. A token that is not a readable JWT is not refused by the app.

**Your three blockers**
1. *Refresh during the A-to-B switch wrote A's snapshot under B's generation.* `refreshAccount` and `_updateProfile` begin an action (refused during the switch) and check `isCurrent` on the answer; `_remember` uses the scope's credentials.
2. *The removal dialog captured identity on confirm.* The scope is taken before the dialog; a stale removal answers `ProfilePhotoRemoval.stale` and the screen shows nothing.
3. *A second Android task with its own TokenStore generation.* `AndroidManifest.xml` now uses `launchMode="singleTask"` (with an empty task affinity), and the bearer-account check above is a net.

**Your six should-fixes**
4. `PickLaunchGate` names the activity that opened the pick (`opened(owner)`, `closed(owner)`, `shouldForward(code, owner)`); another activity's start-up no longer resets it, and `MainActivity.onDestroy` ends its own pick.
5. `PickGuard.run` rechecks the credentials and `proceed` right after `opened`, inside the `try` whose `finally` announces `closed`; a missing handler or any refusal of `opened` stops the pick.
6. A refused second sign-in re-publishes the member who was signed in under the generation they hold (`_authenticateWith`). `AuthRepository._authenticate` now reads the answer before it saves, so every `ApiException` precedes any credential write.
7. The stale branch of `remove()` calls `_abandon(launch)`.
8. `AvatarCacheManager._publish` owns the file name, awaits `store.putFile` (the record) and deletes the file if either step fails.
9. The round-6 test gap: `test/p3b_photo_round7_test.dart` group 1 holds the role-context write after B's credentials are saved and presses there (pick, removal, refresh, profile update); the earlier test stays.

## What to do
1. Mark each of your 6 round-5 blockers/should-fixes of the previous report that you can, and the **3 blockers and 6 should-fixes** of your round-6 report, **fixed**, **partly fixed** (say what is missing) or **not fixed**. Mark the round-3 findings 1, 4, 5, 13 you left open.
2. Hunt for **new**, real, reachable problems in this round. In particular:
   - **The scope model.** Is there any action that can still change an account or send a credential without `beginAction`/`isCurrent` (search for `_auth.`, `_api` writes and every reader of `accountProvider` that writes)? Can `SessionSignedIn.identity` ever differ from the store's generation while the same member is legitimately signed in, so that every photo action silently refuses (restore, `_confirm`, token refresh, `clearIfIdentityCurrent`, the re-publish after a failed sign-in, a sign-in that finishes after another)? Can two different logins have equal scopes?
   - `singleTask`: does it break notification taps, deep links, `taskAffinity=""`, the launcher, the picker's return (the camera and library activities return into the task)? Is a second instance still possible by another route?
   - The bearer check: a `user_id` claim that is not an int; a refresh that replaces the bearer between the generation check and the header; a 401 replay of an upload (`noReplay`).
   - The gate: the owner is compared by reference; can a legitimate result still be dropped (activity recreation with the engine retained, the picker returning to a different activity instance)?
   - Weakened or deleted tests: no assertion was changed; every test that called `pick`, `remove`, `uploadPhoto` or `removePhoto` only moved to the new signatures (`pickPhoto` and `removeOwnPhoto` in `test/support/photo_rig.dart`).
3. Report only real, reachable problems. No style opinions.

## Output format
- One opening sentence.
- A table of the open round-3 findings (1, 4, 5, 13): # | Status | Note.
- A table of the round-5 and round-6 findings: # | Status | Note.
- A table of new findings: Severity (Blocker / Should-fix / Nit) | File and line | Concrete failure | Suggested fix.
- What you could not check.
- A final line: "Overall verdict: approve" or "Overall verdict: reject".
