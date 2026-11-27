You are an independent second-pass reviewer. This review is read-only: do not write, commit or push code, and do not comment on GitHub. You may read files and run read-only git commands. Run `git fetch origin` first. If `git fetch` cannot write `.git/FETCH_HEAD`, say so and verify the SHAs through `git ls-remote origin`.

This is the **eighth review** of pull request #66, "P3B profile photos in the app", in this repository (is-bo/shiptripis). The head to review is `7a4d3303e0ff47357c9211cadba87f0c0fea078e` (branch `origin/claude/p3b-profile-photos-app`). **All 12 CI checks are green on it**, including "Schema drift", the Django shards (with the new server tests), "Flutter — format, analyze, tests" and "Android — compile and Gradle unit tests". The head is a docs-only commit (a status file) on top of the round-8 code commit `778da3a`.

- You rejected the previous head, `a286b34146e6f83e47a99d25270f75965d95c687`, with 5 blockers and 4 should-fixes. Your report is `docs/handoff/astra/results/p3b-astra-round7-result.md` on `main`.
- The builder's answer is the "Round eight" section of `docs/PHASE_P3B_PROFILE_PHOTOS_APP.md` at the head, and `docs/handoff/status/P3B.md`.
- Compare `a286b34..7a4d330` for this round, and `origin/main...7a4d330` (three dots) for the whole package.
- The rules are in `CLAUDE.md` ("Mobile rules"). The server contract is spec section 21 of `docs/WASSLA_DISCOVERY_PRO_SPEC.md` and `backend/monolith/apps/accounts/photos.py`.

## Review scope: three rules from the owner (read before you report)
These stop the review loop. A finding that breaks them is out of this review; list it once, under "Out of scope", and do not count it toward the verdict.

1. **Legacy and upgrade findings are not applicable.** The app has never been live and has no users: no rows written by older code, no old app versions, no URLs issued before the change, no migrations of old data.
2. **Out-of-scope findings go to a follow-up package, not into this one.** This package is the profile photo, the session scope it uses, and what it needs to be correct. **Wrong-account writes in KYC, the payout cheque form, account deletion, sign-out, and the public-profile and discovery forms** (your round-7 blockers 3, 4 and 5) are already recorded as a separate package (`HANDOFF.md` section 0.8; `docs/handoff/WRONG_ACCOUNT_WRITES_FOLLOWUP.md` on the PR branch). Do not re-raise them as blockers. A new instance of that same family in a flow this package does not touch is also out of scope.
3. **Fixes go to the root cause.** When you find a new variant of a problem already raised, say whether the design still allows the family, not only the single case, and propose the change to the design.

## What round 8 changed, and the design to judge
Round 7 found two blockers inside this package. The builder says both had one root cause: an action or a recovery read "who is this" from the **displayed** state instead of from what it actually belongs to.

**Your round-7 blocker 1: the Dismiss press** (`profile_photo_section.dart`: Dismiss callback, `_begin()`). A tap on A's removal notice delivered after B was published and before the next Flutter rebuild called `_begin()`, which read B.
- `_drawnFor` (an `AccountSession`: account and sign-in generation) is set in `build()` from `accountSessionProvider`, and is null when the session is not for the account this section was built with.
- `_begin()` returns a scope only if `beginAction()` returns the member the section was **last drawn for** (same account id and same sign-in generation). A press on a control that is still on screen for A while B is published therefore does nothing.
- `_take` serves the two buttons of an account with no photo; `_pick` takes its scope as an argument; `_choose` checks `mounted` right after the source sheet returns (your should-fix: a source sheet outliving its section).

**Your round-7 blocker 2: the overtaken sign-in** (`session.dart`). B saved credentials and was overtaken while still awaiting the role-context write; a later sign-in then failed and the catch re-published A under the newest generation although storage held B.
- `_credentialOwner` records which account the stored credentials belong to: set when a sign-in's credentials were saved (even if that sign-in was then overtaken), and when a restore confirms them; cleared on sign-out, deletion, expiry and terminal refusal.
- `_settleAfterFailedSignIn` settles the **newest** failed sign-in against that owner, for any failure (not only `ApiException`): if the owner is the displayed member, they are re-published under the new generation; if the owner is someone else, that member is restored and shown through `SessionRestoring` (guest case included); if storage cannot say whose credentials they are, the local session ends and the credentials are cleared. The role-context write is best effort (`_adoptRoleContextFor`), so a keystore error no longer strands a saved sign-in. This also answers your should-fix about storage failures.

**Your round-7 should-fixes**
- *Refused profile update announced success* (`language_screen.dart`, `account_name_screen.dart`): `updatePreferredLanguage`, `setFullName` and `_updateProfile` now return `bool` (applied or not); the screens act only on true.
- *Unconditional Dismiss/Remove*: `DELETE /api/me/photo?version=<v>` is conditional. The client sends the version it showed (`OwnPhoto.removed` now keeps its version; a removed photo without one is no photo), the server (`photos.py` `remove_own_photo(user, version=None)`, `views.py`) answers 409 `profile_photo_changed` for a different version, and the app refreshes the profile and reports `stale`.

**Tests.** `mobile/test/p3b_photo_round8_test.dart` (17 tests; the builder removed in turn the drawn-for check, the `mounted` check, the owner-based settle and the stale-update result, and each removal failed a test) and the server tests in `backend/monolith/apps/accounts/tests/test_p3a_profile_photos.py`. Earlier tests only gained the new `shownVersion` argument; `FakeTokenStore` (`test/support/fake_api.dart`) now records the saved access token.

## What to do
1. Mark each of your round-7 findings that belong to this package **fixed**, **partly fixed** (say what is missing) or **not fixed**: the two blockers above and the four should-fixes (storage failure recovery, stale profile update result, source sheet outliving its section, conditional Dismiss). List your round-7 blockers 3, 4 and 5 once as "Out of scope: recorded as a follow-up package", with no further analysis.
2. Mark the round-3 findings 1, 4, 5, 13 and the round-5 and round-6 findings you left open, as in your round-7 table.
3. Hunt for **new**, real, reachable problems **inside this package**. In particular:
   - **The press binding.** Is there any press path of the photo section (Change, Remove, Dismiss, Take, Choose, Retry, Discard, the source sheet, the removal dialog) that still reaches a write with a scope that is not the one the control was drawn for? Can `_drawnFor` be stale in the other direction, so a legitimate press by the member who is shown is silently refused for good (restore, token refresh, role switch, the re-publish after a failed sign-in)?
   - **The credential owner.** Can `_credentialOwner` differ from what storage holds in a reachable sequence (restore from a snapshot, a refresh that rotates the tokens, `clearIfIdentityCurrent`, a sign-in overtaken after its save, two failures in a row, sign-out during a settle)? Is there still a path where the displayed member and the stored credentials are different accounts and the session stays that way?
   - **The conditional delete.** Race between the version check and the delete on the server (transaction, lock), a removed photo with no version, the 409 handling on the client, idempotency of a repeated Dismiss.
   - **Weakened or deleted tests:** the builder says no assertion was changed.
4. Report only real, reachable problems. No style opinions, no legacy or upgrade findings, no findings outside the scope above.

## Output format
- One opening sentence.
- A table of the open round-3 findings (1, 4, 5, 13): # | Status | Note.
- A table of your round-5, round-6 and round-7 findings that belong to this package: # | Status | Note.
- A table of new findings: Severity (Blocker / Should-fix / Nit) | File and line | Concrete failure | Suggested fix (the root cause, per rule 3).
- A short list "Out of scope" (rule 2), one line each, not counted.
- What you could not check.
- A final line: "Overall verdict: approve" or "Overall verdict: reject".
