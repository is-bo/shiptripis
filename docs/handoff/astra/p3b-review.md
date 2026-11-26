You are an independent second-pass reviewer. This review is read-only: do not write, commit or push code, and do not comment on GitHub. You may read files and run read-only git commands.

This is the **third review** of pull request #66, "P3B profile photos in the app", in this repository (is-bo/shiptripis). The new head is `d8c3607e55dc1aec05bfd002a7df1f041b3ce932`. Run `git fetch origin` first if that commit is missing.
- The second review rejected head `0f50142f1e97d98a770a5ac694a87231d47ea5dd`. Its findings and the builder's fix for each are in the round-two table in `docs/PHASE_P3B_PROFILE_PHOTOS_APP.md` at the new head.
- Compare `0f50142..d8c3607` for this round, and `origin/main...d8c3607` (three dots) for the whole package.
- The rules are in `CLAUDE.md` ("Mobile rules"). The server contract is spec section 21 of `docs/WASSLA_DISCOVERY_PRO_SPEC.md` and `backend/monolith/apps/accounts/photos.py`.

## What changed in round 3 (the builder's claims)
A. **Photo preparation moved to native code.** One platform channel, `wassla/photo_prepare`, returns the path of a new JPEG. The JPEG is upright, at most 1024 px on its long edge, carries no metadata, and is written to a unique cache path. `flutter_image_compress` and the Dart header probe were removed.
- Android, `mobile/android/app/src/main/kotlin/eu/wassla/app/PhotoPrepare.kt` and `MainActivity.kt`:
  - bounds are read first with inJustDecodeBounds;
  - the sample size is bounded by total pixels (about 6 MP);
  - one Matrix handles all eight EXIF orientations;
  - `ImageDecoder` handles HEIF on API 28 and later;
  - transparency is flattened onto white;
  - an OOM decode is retried at a larger sample;
  - `androidx.exifinterface` is added in `build.gradle.kts`.
- iOS, `mobile/ios/Runner/AppDelegate.swift`: `CGImageSourceCreateThumbnailAtIndex` with the transform applied and a 1024 maximum, and the JPEG is written without metadata.

B. **Account switch mid-upload.**
- The credential generation is captured before the file is read.
- The client refuses to send if the sign-in changed.
- The controller rechecks the account at every await.

C. **Other fixes.**
- A stale public-profile write cannot reinstall an old photo.
- The launch `/api/me` confirmation keeps a newer photo.
- A vanished prepared file is cleared on upload failure.
- A fresh avatar URL is retried after a stale load fails.
- `PickGuard` covers every image_picker entry point in the app. It uses a `purpose:account:nonce` marker, so a KYC selfie or ID photo can never be offered as a profile photo after process death.
- The layout tests use the real app shell.
- The first tap reserves the picker synchronously.
- Superseded prepared JPEGs are deleted.

**Important:** the Kotlin and Swift code has never been compiled or run, because CI builds neither app. Review the native code with extra care for compile errors and runtime crashes.

## What to do
1. Mark each finding in the round-two table **fixed**, **partly fixed** (say what is missing) or **not fixed**.
2. Hunt for **new**, real, reachable problems in this round. Check in particular:
   - **Kotlin compile errors and runtime crashes:** API-level guards (`ImageDecoder` below API 28, `Build.VERSION` checks), the minSdk in `build.gradle.kts`, nullability, the main-thread versus background-thread work and result delivery on the platform channel, bitmap recycling and leaks, the sample-size arithmetic (powers of two, overflow on huge dimensions), the EXIF matrix for each of the 8 orientations, HEIF ICC or 10-bit handling, a content:// path versus a file path, and the cache path collision.
   - **Swift compile errors:** the FlutterMethodChannel registration in AppDelegate (FlutterAppDelegate, implicit engine and plugin registrant patterns), CGImageDestination options that strip metadata, kCGImageSourceCreateThumbnailWithTransform, and thread use.
   - **The Dart channel wrapper and its error mapping.**
   - **PickGuard:** marker races, secure storage versus shared preferences, cleanup on sign-out, and whether any image_picker call site was missed (search the whole of `mobile/lib`).
   - **The account-generation checks:** is anything still sent, or any state written, under account B after a switch?
   - **Tests:** were any weakened or deleted?
3. Report only real, reachable problems. No style opinions.

## Output format
- One opening sentence.
- A table of the round-two findings: # | Status | Note.
- A table of new findings: Severity (Blocker / Should-fix / Nit) | File and line | Concrete failure | Suggested fix.
- What you could not check (for example, a real device or a compiler).
- A final line: "Overall verdict: approve" or "Overall verdict: reject".
