# P3B status: profile photos in the app (PR #66), written 2026-11-27 for the next agent

Branch `claude/p3b-profile-photos-app`. Last Astra-reviewed head: `a286b34` (round 7, rejected). The round-8
work is on this branch as a **WIP commit** that has **not** gone through CI or a full local test run. Do not
merge. Do not deploy. Read `CLAUDE.md`, then this file, then the "Round eight" section of
`docs/PHASE_P3B_PROFILE_PHOTOS_APP.md`.

## Triage rules from Ismail for round 8 (they stop the review loop)
1. **Fix** the in-scope blockers and should-fixes: the photo section's Dismiss press, the session republish
   after an overtaken sign-in, the storage-failure recovery, the stale result of a profile update, a
   source sheet that outlives its section, the conditional Dismiss.
2. **Do not fix** wrong-account writes in KYC, the payout cheque form, account deletion, sign-out and the
   public-profile and discovery forms. They are written up as a separate package in
   `docs/handoff/WRONG_ACCOUNT_WRITES_FOLLOWUP.md` (it also says what the `MemberScope` primitive makes cheap).
3. **No legacy or upgrade findings**: the app has never been live and has no users.
4. The round-8 Astra prompt must state rules 2 and 3 to Astra (the drafted prompt does).

Standing rules: never deploy; do not merge until all 12 CI checks are green (incl. "Schema drift") and Astra
approves; never skip, delete or weaken a test; long suites run on GitHub CI; the repo is public (no secrets or
server addresses); say "the cahier des charges", never "partner"; commits end with the attribution lines the
session gives. Model: this package was built on Sonnet; Ismail's escalation rule says to switch the builder to
Opus if Astra rejects a Sonnet-built package again.

## What is done (all in the WIP commit)
Astra's round-7 result is committed on `main` (`docs/handoff/astra/results/p3b-astra-round7-result.md`).
App (all in `mobile/`):
- **Press binding.** `lib/features/profile/profile_photo_section.dart`: `_drawnFor` is set in `build`;
  `_begin()` refuses a press unless `beginAction()` returns the member the section was last drawn for.
  `_pick` takes its scope as an argument; `_take` serves the two buttons of an account with no photo; `_choose`
  checks `mounted` right after the source sheet returns.
- **Stored-credentials owner.** `lib/core/session/session.dart`: `_credentialOwner` (set when a sign-in's
  credentials were saved, even if overtaken, and when a restore confirms them; cleared on sign-out, deletion,
  expiry, terminal refusal). `_settleAfterFailedSignIn` settles the newest failed sign-in against it (for any
  failure, not only `ApiException`); a foreign owner is restored and shown via `SessionRestoring`;
  unverifiable storage ends the local session and clears. `_adoptRoleContextFor` is best effort.
- **Stale profile updates.** `updatePreferredLanguage`, `setFullName`, `_updateProfile` return `bool`
  (applied or not); `language_screen.dart` and `account_name_screen.dart` act only on true.
- **Conditional Dismiss/Remove.** `DELETE /api/me/photo?version=<v>`. Client: `OwnPhoto.removed` now keeps
  its version (and a removed photo without one is null), `ApiClient.deleteVoid(query:)`,
  `AuthRepository.removePhoto(shownVersion)`, `ProfilePhotoController.remove(scope, shownVersion)` (409
  `profile_photo_changed` -> refresh the profile, result `stale`), `ApiErrorCode.profilePhotoChanged`.
  Server (small): `backend/monolith/apps/accounts/photos.py` `remove_own_photo(user, version=None)` and the
  `delete` view in `views.py` answer 409 `profile_photo_changed` for a different version; tests added in
  `apps/accounts/tests/test_p3a_profile_photos.py` (not run: Django is not installed in the builder sandbox,
  only `py_compile` was checked; the Django CI job is the first real run).
- **Tests.** `mobile/test/p3b_photo_round8_test.dart` (17 tests, all pass, mutation-checked: removing the
  drawn-for check, the `mounted` check, the owner-based settle and the stale-update result each fails a test).
  Direct calls in older tests gained the required `shownVersion` argument (round4, round6, round7,
  `p3b_photo_state_test.dart`, `test/support/photo_rig.dart`). `FakeTokenStore` (`test/support/fake_api.dart`)
  now records the access token a sign-in saves (`savedAccess`) and `readAccess` answers it. Do not make it
  record or return a saved refresh token: that made three `egs_social_sign_in_test.dart` tests hang (a
  sign-out then sends a request in the fake-async zone). That was fixed.
- **Docs.** "Round eight" section in `docs/PHASE_P3B_PROFILE_PHOTOS_APP.md`; top entry in
  `docs/IMPLEMENTATION_STATUS.md`; `docs/handoff/WRONG_ACCOUNT_WRITES_FOLLOWUP.md`.
- `dart format` and `flutter analyze --fatal-infos` were clean at the last run.

## What is half done / not verified
**Update 2026-11-27 11:38 UTC: CI is green on head `778da3a`, all 12 checks** (Flutter format, analyze and the
full suite; Django including the new server tests; Android; Schema drift; Go; the rest). So the two items below
about the full suite and CI are now resolved; what remains is the Astra prompt, HANDOFF §0 and Astra's review.

- **The full `flutter test` suite has not completed on the final code.** First full run: everything passed
  except 3 `egs_social_sign_in_test.dart` tests that hung (cause fixed since, and that file plus the round-8
  file pass: 62 tests). The second full run was stopped before it finished. Run the suite on GitHub CI.
- **Nothing has been pushed to CI yet for the server change** (Django tests, "Schema drift" and the other
  checks). Fix whatever fails there; do not weaken a test.
- **The round-8 Astra prompt is drafted but not committed to `main`.** It lives only in the coordinator-side
  worktree `/home/user/main-wt/docs/handoff/astra/p3b-review-round8.md`, which may be gone with this
  session. If it is gone, rewrite it from the round-7 prompt (`docs/handoff/astra/p3b-review-round7.md` on
  `main`): new head SHA and CI line, the two rules above, a list of what changed (the bullet list above), the
  same output format. Ismail pastes it into Astra himself (copy it to `/mnt/project-files/P3B-round8.md`).
- `HANDOFF.md` section 0 (three places: the section 0.3 row, the 0.6 row, the 0.7 table) still says round 7 at
  `a286b34`. Update it on `main` (docs-only; pull first) once the head is green.
- The group-4 language and name screens are covered through the session tests, not screen tests (stated in
  the phase doc).

## Exact next steps
1. `git pull` the branch; merge `origin/main` if it has moved (resolve conflicts; do not rewrite history).
2. In `mobile/`: `export PATH=/home/user/fl/flutter/bin:$PATH` (or your Flutter 3.47.1), `dart format lib test`,
   `flutter analyze --fatal-infos`, then run the photo tests locally
   (`flutter test test/p3b_*.dart test/egs_social_sign_in_test.dart`). Leave the full suite to CI.
3. Remove "WIP" by making a normal commit if anything changes; push; poll the 12 CI checks until green
   (`gh api repos/is-bo/shiptripis/commits/<sha>/check-runs`; a "Django" failure on an older head is usually
   a cancellation by a newer push).
4. Fill `__HEAD__` and the CI line in the round-8 prompt, commit it to `main` (docs-only), copy it to
   `/mnt/project-files/P3B-round8.md`, give Ismail the path.
5. When Astra's result comes back, commit it to `docs/handoff/astra/results/p3b-astra-round8-result.md` on
   `main` and triage with the three rules above (anything outside the photo package goes into
   `WRONG_ACCOUNT_WRITES_FOLLOWUP.md`, not into this PR). If Astra rejects a Sonnet-built round again, build the
   next round on Opus.
6. Update `HANDOFF.md` section 0 after every push and every Astra result.
