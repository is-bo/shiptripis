You are an independent second-pass reviewer. This review is read-only: do not write, commit or push code, and do not comment on GitHub. You may read files and run read-only git commands. Run `git fetch origin` first.

This is the **fourth review** of pull request #66, "P3B profile photos in the app", in this repository (is-bo/shiptripis). The new head is `c8b4e68`; use the full SHA of `origin/claude/p3b-profile-photos-app`.

- You rejected the previous head, `d8c3607e55dc1aec05bfd002a7df1f041b3ce932`, with 4 blockers and 9 should-fixes. That report is the PR comment "Independent second pass — Astra 6.2 (high), read-only, at `d8c3607`".
- The builder's answer to each finding is in the "Round three" section of `docs/PHASE_P3B_PROFILE_PHOTOS_APP.md` at the new head.
- Compare `d8c3607..c8b4e68` for this round, and `origin/main...c8b4e68` (three dots) for the whole package.
- The rules are in `CLAUDE.md` ("Mobile rules"). The server contract is spec section 21 of `docs/WASSLA_DISCOVERY_PRO_SPEC.md` and `backend/monolith/apps/accounts/photos.py`.

## Your round-3 findings, in short
1. **Blocker.** A late Android picker result, restored from a KYC pick, could complete a new profile pick. The builder says it chose "no photo recovered after process death" plus "owned picks" (allowed by the lead: correctness beats recovery).
2. **Blocker.** Picker-marker durability: a swallowed marker write, and a read-then-delete cleanup race.
3. **Blocker.** iOS launch: the customized AppDelegate no longer matched Flutter's UIScene auto-migration. The builder says it migrated to the scene lifecycle, with registration via `didInitializeImplicitFlutterEngine`.
4. **Blocker.** The account-switch window: B's credentials were stored while `accountProvider` still reported A. The credential generation must be captured at the tap.
5. **Should-fix.** Session rechecks were missing after filesystem awaits.
6. **Should-fix.** The launch snapshot overwrote the photo after a failed overlapping PUT.
7. **Should-fix.** Two mounted avatars with different signed URLs shared one retry ("per-address avatar loads").
8. **Should-fix.** Unbounded HEIF intermediate allocation, a null BitmapFactory result, and no retry on the ImageDecoder path ("bounded native decode").
9. **Should-fix.** Ultra HDR, gain-map or ICC metadata in the output: always render a fresh SDR sRGB bitmap.
10. **Should-fix.** A 4096×1 PNG produced a zero-size bitmap.
11. **Should-fix.** Every preparation failure was mapped to "unsupported".
12. **Should-fix.** `flutter_cache_manager` persisted the signed URL on disk.
13. **Should-fix.** Executable sample-size and output tests had been replaced by mocks, and the "no marker, no offer" assertion was lost.

The lead also asked the builder to clean stale prepared JPEGs left by a killed process.

## What to do
1. Mark each finding **fixed**, **partly fixed** (say what is missing) or **not fixed**.
2. Hunt for **new**, real, reachable problems in this round. In particular:
   - **Swift and Kotlin compile errors and runtime crashes.** Neither native target has ever been compiled; CI builds neither. Check the scene-delegate wiring in `Info.plist` against the Flutter version pinned in the repo.
   - Races in the new ownership and generation logic.
   - The custom cache manager's on-disk record.
   - Weakened tests.
3. Report only real, reachable problems. No style opinions.

## Output format
- One opening sentence.
- A table of the 13 round-3 findings: # | Status | Note.
- A table of new findings: Severity (Blocker / Should-fix / Nit) | File and line | Concrete failure | Suggested fix.
- What you could not check.
- A final line: "Overall verdict: approve" or "Overall verdict: reject".
