You are an independent second-pass reviewer. This review is read-only: do not write, commit or push code, and do not comment on GitHub. You may read files and run read-only git commands. Run `git fetch origin` first. If `git fetch` cannot write `.git/FETCH_HEAD`, say so and verify the SHAs through `git ls-remote origin`.

This is the **fifth review** of pull request #66, "P3B profile photos in the app", in this repository (is-bo/shiptripis). The new head is `f4394f196aa8eb7ebcf5bb337f32c9f89afc032c` (branch `origin/claude/p3b-profile-photos-app`).

- You rejected the previous head, `c8b4e68dc0160b061ea13974856cbe2dae243f73`, with 3 new blockers, 4 should-fixes and 8 partly-fixed round-3 findings. Your report is `docs/handoff/astra/results/p3b-astra-round4-result.md` on `main`.
- The builder's answer to each finding is the "Round five" section of `docs/PHASE_P3B_PROFILE_PHOTOS_APP.md` at the new head.
- Compare `c8b4e68..f4394f1` for this round, and `origin/main...f4394f1` (three dots) for the whole package.
- The rules are in `CLAUDE.md` ("Mobile rules"). The server contract is spec section 21 of `docs/WASSLA_DISCOVERY_PRO_SPEC.md` and `backend/monolith/apps/accounts/photos.py`.

## What the builder says it did, to check against the code
**Your three new blockers**
1. *Two KYC taps replaced the first marker.* `PickGuard` (`mobile/lib/core/media/pick_guard.dart`) is now reserved before its first await, for every purpose. A second launch returns null without touching storage or the picker, and a pick's marker is released only by that pick.
2. *`pickImage` and `pickVideo` returned files from uncertain tickets.* The ownership check moved into the guard (`PickGuard.run`). An uncertain result is deleted and refused with `PickBlockedException(uncertain: true)` before it is returned to any caller. `begin`, `end` and `trusts` are no longer public. The profile photo uses `run` too.
3. *A retry during B's sign-in sent A's file with B's bearer.* A prepared photo keeps its owner and credential generation (`PickedPhoto.owner`, `.identity`). "Try again" is checked against those, never against the current session, and `_upload` checks them before it dispatches.

**Your four should-fixes**
4. Only the operation that owns the state resets it: every press takes an epoch (`_launch`, `_launchFor`), `_abandon` acts only for the owning epoch, and `discard()` detaches the photo synchronously.
5. A sign-out during the marker write: `run` rechecks the credential generation after storage and on the answer, and the profile flow passes `proceed: () => _live(launch)`, asked last, just before the picker opens.
6. Avatar installs are serialized per version (`AvatarCacheManager._installOnce`); a response that finds the picture present is dropped unwritten.
7. The iOS sweep cutoff is taken at registration and passed in (`removeLeftovers(before:)`).

**Your round-3 findings that were partly fixed**
- **#2 Android `apply()`:** the marker now lives in `PendingPickStore` (`mobile/lib/core/session/pending_pick_store.dart`). On Android it goes through the `wassla/pick_marker` channel to `PickMarkerStore.kt`, which uses `commit()` and throws when the disk refuses. Elsewhere it stays in secure storage.
- **#8 retry sequence and oversized HEIF:** `PhotoGeometry.sampleLadder` gives 4, 8, 16, 32. The `ImageDecoder` path refuses a picture over 64 MP in `onHeaderDecoded`, before any pixel is decoded, with code `failed`.
- **#9 ICC segment:** `JpegMetadata.withoutMetadata` removes APP1 to APP15 and comments from the encoded JPEG.
- **#11 error mapping:** the `ImageDecoder` path maps a missing file to `not_found`, an `IOException` with the file present to `unsupported`, and anything else to `failed`.
- **#13 tests:** the Dart copy of the arithmetic is deleted. `PhotoGeometry` and `JpegMetadata` have JUnit tests of the real Kotlin (`mobile/android/app/src/test`, run by `tools/test_android_pure.sh` and a CI step).
- **#1, #4, #5** are closed by the rows above.

## What to do
1. Mark each of your 13 round-3 findings and each of your 7 round-4 findings **fixed**, **partly fixed** (say what is missing) or **not fixed**.
2. Hunt for **new**, real, reachable problems in this round. In particular:
   - **Kotlin and Swift compile errors and runtime crashes.** `PhotoPrepare.kt`, `PickMarkerStore.kt`, `MainActivity.kt` and `AppDelegate.swift` have never been compiled; CI builds neither app. `PhotoGeometry.kt` and `JpegMetadata.kt` are compiled and tested by CI. Read the new `ImageDecoder` error handling and the `wassla/pick_marker` channel for a runtime fault (for example a `Unit` answered across the channel, an exception thrown from `onHeaderDecoded`, a handler that never answers).
   - Races in the guard reservation: can `_taken` be left set, can a result be returned that the guard cannot prove, can a screen still open a picker outside the guard (search for `ImagePicker` and `pickImage` uses).
   - The retry binding: can an upload still go out under credentials other than those the photo was prepared under, and can a legitimate retry now be refused (a token refresh must not count as a new sign-in).
   - The committed marker store: sign-out, release and exchange ordering through the credential queue, and the iOS path still using secure storage.
   - Weakened or deleted tests (the Dart arithmetic copy was deleted on purpose; check its cases all moved to Kotlin).
3. Report only real, reachable problems. No style opinions.

## Output format
- One opening sentence.
- A table of the 13 round-3 findings: # | Status | Note.
- A table of the 7 round-4 findings: # | Status | Note.
- A table of new findings: Severity (Blocker / Should-fix / Nit) | File and line | Concrete failure | Suggested fix.
- What you could not check.
- A final line: "Overall verdict: approve" or "Overall verdict: reject".
