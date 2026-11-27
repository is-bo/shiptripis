# Brief P3B-A: bring profile photos onto the session core

**Builder:** Claude Opus, high effort.
**Branch:** `claude/p3b-profile-photos-app`, pull request #66. Last reviewed head: `7727b19`
(rejected, round 8). You start after **N1 and S1 have merged**. P3B-B follows you.
**Read first:** `CLAUDE.md`, the mobile rules included; `docs/handoff/builders/README.md`; the
plan (`docs/handoff/LOOP_END_PLAN.md`) sections 3, 5.4 and 5.5; on `main` the S1 phase document;
on your branch `docs/handoff/status/P3B.md` and `docs/PHASE_P3B_PROFILE_PHOTOS_APP.md`.

## 1. Your job

Bring the P3B branch onto the session core that S1 put on `main`, and take out everything P3B
built for account switching. Six review rounds failed on that code; S1 now owns the problem. You
also regroup P3B's tests by rule. You change no behaviour of the photo feature: P3B-B does that.

## 2. What you do

Paths are under `mobile/`.

**Merge `origin/main` into the branch.** In these files take `main`'s version whole, then put
back only what the photo feature itself needs: `lib/core/session/session.dart`,
`lib/core/session/token_store.dart`, `lib/core/api/api_client.dart`,
`lib/data/auth_repository.dart`, `lib/main.dart`, `lib/app/app.dart`, `lib/app/router.dart`,
`test/support/harness.dart` and `android/app/src/main/AndroidManifest.xml`.

**Remove P3B's account-switch code:** its changes to the session files that concern credentials
or switching; `_credentialOwner`; `_settleAfterFailedSignIn`; `beginAction()` and `MemberScope`
(`lib/core/session/member_scope.dart`) with every call site that threads them; `_drawnFor`;
`_photoApplied`; `docs/handoff/WRONG_ACCOUNT_WRITES_FOLLOWUP.md`. The `singleTask` change is
S1's now and arrives with the merge.

**Keep what belongs to the closed families.** `pending_pick_store.dart` and the native pick
marker store (P-A), image preparation (P-B) and the avatar cache (P-C) stay as they are.

**Keep the photo controller working.** Adapt `lib/app/profile_photo_state.dart` and
`lib/features/profile/profile_photo_section.dart` in the simplest way to live without
`MemberScope`: the controller is created inside the member's container, so it cannot outlive its
member.

**Regroup the tests by rule.** `test/p3b_photo_round2_test.dart` to `round8_test.dart` become
files named after the rules: pick ownership (P-A), preparation (P-B), avatar cache (P-C), member
boundary (P-D), the slot rule (P-E), one operation at a time (P-F), newer truth (P-G).

- A test moves with its assertions unchanged.
- A test of a mechanism you removed is rewritten as the same scenario through the real boundary,
  with the photo section on screen. It is deleted only when S1's own tests already cover exactly
  that scenario, and the pull request names the S1 test.

## 3. What is not yours

Any change to `main`'s session core: if the photo feature needs something the core does not
offer, stop and ask. The slot rule, the one-at-a-time rule and the photo's one owner (P3B-B).

## 4. Tests

- S1-B's cases, run again with the photo section and the removal notice on screen: pointer down
  on A's Dismiss, `end`, pointer up; a picker result that returns after the reset; an upload in
  flight at `end`.
- The closed families' tests (P-A, P-B, P-C) pass unchanged.

## 5. Done when

1. The branch holds no account-switch code of its own, and the cases of section 4 pass.
2. The pull request lists every test that moved, was rewritten or was removed, with the reason.
3. You report by how many lines the phone diff of the branch shrank.
4. `docs/handoff/status/P3B.md` tells P3B-B where things stand. CI is green on your last commit.
