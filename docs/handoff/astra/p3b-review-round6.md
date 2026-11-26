You are an independent second-pass reviewer. This review is read-only: do not write, commit or push code, and do not comment on GitHub. You may read files and run read-only git commands. Run `git fetch origin` first. If `git fetch` cannot write `.git/FETCH_HEAD`, say so and verify the SHAs through `git ls-remote origin`.

This is the **sixth review** of pull request #66, "P3B profile photos in the app", in this repository (is-bo/shiptripis). The new head is `ead30e206ad702cf2ea91cedb95cf9704c778a7b` (branch `origin/claude/p3b-profile-photos-app`).

- You rejected the previous head, `f4394f196aa8eb7ebcf5bb337f32c9f89afc032c`, with 2 blockers, 5 should-fixes and 6 partly-fixed round-3 findings (and round-4 finding 2). Your report is `docs/handoff/astra/results/p3b-astra-round5-result.md` on `main`.
- The builder's answer to each finding is the "Round six" section of `docs/PHASE_P3B_PROFILE_PHOTOS_APP.md` at the new head.
- Compare `f4394f1..ead30e2` for this round (the branch also has a merge of `main`, which only brought documents, and commits that add a CI job and correct documents), and `origin/main...ead30e2` (three dots) for the whole package.
- The rules are in `CLAUDE.md` ("Mobile rules"). The server contract is spec section 21 of `docs/WASSLA_DISCOVERY_PRO_SPEC.md` and `backend/monolith/apps/accounts/photos.py`.

## What the builder says it did, to check against the code
**Your two blockers**
1. *A restored KYC copy worker could complete a later Profile gallery pick.* The result is bound to its launch at the source. `PickGuard.run` (`mobile/lib/core/media/pick_guard.dart`) calls `wassla/pick_launch` `opened` just before the picker opens (a refusal throws `PickBlockedException` and no picker opens) and `closed` in a `finally`. `MainActivity.onActivityResult` forwards a result for one of the plugin's request codes to the plugin only while `PickLaunchGate` (`PickLaunchGate.kt`) says a pick of this process is open; a result restored after process death is dropped before the plugin starts copying it. A new engine resets the gate. The guard now judges trust the moment the picker answers, before the marker's release is awaited. Announcements are made on Android only (`PickGuard(nativeLaunchGate: Platform.isAndroid)`). A test pins the gate's request codes against the plugin's Java source.
2. *A press during an A-to-B switch paired A's id with B's generation.* `SessionSignedIn` stores the credential generation (`identity`) it was published under. `ProfilePhotoController._launch` reads the owner and generation from the published session, never from the token store, and `_live` requires the session's, the launch's and the store's generation to agree. `remove()` checks `_live` first and passes `expectedIdentity` to `SessionNotifier.removePhoto`, `AuthRepository.removePhoto` and `ApiClient.deleteVoid`, which refuses when the generation moved.

**Your five should-fixes**
3. `_upload(launch, photo)` takes the exact `PickedPhoto` and returns unless it is still `state.picked`.
4. `TokenStore._clearCredentials` swallows a refused `closeBySignOut` (the marker stays) so `clearIfIdentityCurrent` finishes and the expiry callback runs.
5. `AvatarCacheManager._fetch` reads each body independently (4 MiB cap) and only the publication (`putFile`) is queued per version.
6. A body that fails halfway therefore leaves no file and no record.
7. `testImplementation("junit:junit:4.13.2")` is in `mobile/android/app/build.gradle.kts`; the Gradle unit-test task now runs in CI and passes (12 + 5 + 6 tests).

**Your partly-fixed round-3 findings**
- **#8:** the 64 MP limit for HEIF, HEIC and AVIF is applied at the successful `BitmapFactory` bounds read (`PhotoGeometry.isFullFrameFormat`, `withinSourceLimit`) before any pixel decode, as well as in the `ImageDecoder` header.
- **#11:** when `BitmapFactory` answers null, `PhotoPrepare.decode` rechecks the file and answers `not_found` when it is gone.
- **#13:** still no native fixture that prepares a photo twice (needs a device). The pure Kotlin has 23 JUnit tests (`PhotoGeometry`, `JpegMetadata`, `PickLaunchGate`), now also run by Gradle in CI.
- **#1, #4, #5** are said to be closed by blockers 1 and 2 and should-fix 3.

## What to do
1. Mark each of your 13 round-3 findings and each of your 7 round-4 findings **fixed**, **partly fixed** (say what is missing) or **not fixed**. Also mark the two blockers and five should-fixes of your round-5 report.
2. Hunt for **new**, real, reachable problems in this round. In particular:
   - **The launch gate.** `MainActivity.kt`, `PickLaunchGate.kt` and the `wassla/pick_launch` channel now compile: a new CI job "Android — compile and Gradle unit tests" (`.github/workflows/ci.yml`) builds a debug APK and runs `:app:testDebugUnitTest` (green). They have never run on a device. Can a legitimate result be dropped (a result arriving after `closed`, a launch opened while the Dart side is not yet announcing, an activity recreated while the picker is open but the process lives, a camera pick that goes through a permission request, the picker answering while the engine is detached)? Can a restored result still reach the plugin (a second engine, a hot restart, `opened` left set by a pick that never closed)? Are all of the plugin's launch request codes listed?
   - Whether `PickGuard.run` can leave the gate open (an exception between `opened` and the `finally`) or the guard taken.
   - **The session identity.** Every place a `SessionSignedIn` is built (`session.dart`): can the published `identity` ever differ from the store's generation while the same member is legitimately signed in (restore, `_confirm`, refresh, token refresh, profile update), which would make every photo action silently refuse? Can it still be equal for two different logins?
   - The avatar cache: memory use of reading a body whole, and the error paths.
   - Weakened or deleted tests (two tests in `p3b_photo_round4_test.dart` and `p3b_photo_state_test.dart` only gained the new `expectedIdentity` argument; the "credentials settled" test in round 4 was rewritten to sign in for real; the reason is in the Round six section).
3. Report only real, reachable problems. No style opinions.

## Output format
- One opening sentence.
- A table of the 13 round-3 findings: # | Status | Note.
- A table of the 7 round-4 findings: # | Status | Note.
- A table of the round-5 findings (2 blockers, 5 should-fixes): # | Status | Note.
- A table of new findings: Severity (Blocker / Should-fix / Nit) | File and line | Concrete failure | Suggested fix.
- What you could not check.
- A final line: "Overall verdict: approve" or "Overall verdict: reject".
