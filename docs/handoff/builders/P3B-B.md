# Builder brief P3B-B: onto the session core, and tests by family

**Builder:** Claude Opus, extra-high effort. One builder at a time on the branch.
**Start only when** the lead says the plan is approved and gives you Ismail's answers to D1 to D9.
**Plan:** `docs/handoff/LOOP_END_PLAN.md` at commit `e66bb5b`, on branch
`claude/project-thread-mb20d4`. Read it with `git fetch origin claude/project-thread-mb20d4` and
`git show e66bb5b:docs/handoff/LOOP_END_PLAN.md`. If the lead names a later commit, use that one.
Where this brief and the plan differ, the plan wins, and you tell the lead.

## 1. Your job

Bring the P3B branch onto the session core that S1 put on `main`, and take out everything P3B
built for account switching. Six review rounds failed on that code; S1 now owns the problem. You
also regroup P3B's tests by family. You change no behaviour of the photo feature: P3B-C does
that after you.

## 2. Branch and order

- Branch `claude/p3b-profile-photos-app`, pull request #66. You start after **S1 and N1 have
  merged** and after P3B-A is pushed and green. Pull first.
- P3B-C follows you.

## 3. Read first

1. `CLAUDE.md`, including the mobile rules.
2. The plan: sections 3 and 4, section 5 (what S1 built and why), sections 9.2 (P-D) and 9.3, and
   item 5 of Appendix B.
3. On `main`: `docs/PHASE_S1_SESSION_CORE.md`. On your branch: `docs/handoff/status/P3B.md` as
   P3B-A left it.

## 4. What you do

Paths are under `mobile/`.

**Merge `origin/main` into the branch** with a merge commit. In these files take `main`'s version
whole, then put back only what the photo feature itself needs:
`lib/core/session/session.dart`, `lib/core/session/token_store.dart`,
`lib/core/api/api_client.dart`, `lib/data/auth_repository.dart`, `lib/main.dart`,
`lib/app/app.dart`, `lib/app/router.dart`, `test/support/harness.dart` and
`android/app/src/main/AndroidManifest.xml`.

**Remove P3B's account-switch code** (plan section 9.3): its changes to the session files that
concern credentials or switching; `_credentialOwner`; `_settleAfterFailedSignIn`; `beginAction()`
and `MemberScope` (`lib/core/session/member_scope.dart`) with every call site that threads them;
`_drawnFor`; `_photoApplied`; `docs/handoff/WRONG_ACCOUNT_WRITES_FOLLOWUP.md`. The `singleTask`
change is S1's now and arrives with the merge.

**Keep what belongs to the closed families.** `pending_pick_store.dart` and the native pick
marker store (P-A), image preparation (P-B) and the avatar cache (P-C) stay as they are.

**Keep the photo controller working.** Adapt `lib/app/profile_photo_state.dart` and
`lib/features/profile/profile_photo_section.dart` in the simplest way to live without
`MemberScope`: the controller is created inside the member's container, so it cannot outlive its
member. Do not redesign it; P3B-C rebuilds it to a transition table.

**Regroup the tests by family.** `test/p3b_photo_round2_test.dart` to `round8_test.dart` become
files named after the invariants: pick ownership (P-A), preparation (P-B), avatar cache (P-C),
member boundary (P-D), slot revision (P-E), one operation at a time (P-F), newer truth (P-G).

- A test moves with its assertions unchanged.
- A test of a mechanism you removed is rewritten as the same scenario through the real boundary,
  with the photo section on screen. It is not deleted.
- The pull request lists every test that moved or was rewritten, with the reason.

## 5. What you remove

See "Remove P3B's account-switch code" above. **[Guess]** The phone diff of the branch shrinks by
2,000 to 3,000 lines. Report the real number.

## 6. What is not yours

- Any change to `main`'s session core. If the photo feature needs something the core does not
  offer, stop and ask.
- The slot revision on the phone, the transition table and the photo store (P3B-C).
- The server (P3B-A, done before you).

## 7. Tests

- The whole mobile suite passes after the merge and the removal.
- Scan tests: `MemberScope`, `beginAction`, `_credentialOwner`, `_settleAfterFailedSignIn`,
  `_drawnFor` and `_photoApplied` appear nowhere in `mobile/lib`.
- Against `main`, the branch changes the session files only where the photo feature needs it. List
  each such change in the status file.
- The tests of the closed families P-A, P-B and P-C pass with their assertions unchanged.

## 8. Done when

1. The branch contains `main` with S1 and N1, and no account-switch code of its own.
2. No test file is named after a round.
3. The whole mobile suite and the Android build are green in CI.
4. The status file tells P3B-C what the controller looks like now, and lists the rewritten tests.

## Rules, the same for every builder

1. Build what this brief names and nothing else. Add no lock, counter, generation, flag, column,
   job kind or retry loop that the plan does not name. If one seems needed, stop and ask.
2. Red first. Reproduce each finding listed under "Tests" as a failing test before you fix it. A
   failing test must tell the bad outcome apart from a correct serial execution.
3. Group tests by family, in files named after the invariant. Never skip, delete or weaken a test.
   A test of a mechanism you delete is rewritten to the new rule, and the pull request lists it
   with the reason.
4. Remove what you replace in the same pull request. The tests of the closed families stay green.
5. The server enforces every rule. The app never fakes a result. Every user-facing string exists
   in English, French and Arabic.
6. After a migration, run `task check-drift` in `backend/` and commit the regenerated contract.
7. Push only to your branch, with ordinary pushes: no force push, no rebase of pushed commits. The
   whole suites and the Android build run in GitHub CI on the branch. While you fix, re-run locally
   only the tests that failed. The work is ready only when every CI check is green, "Schema drift"
   included.
8. Never deploy, never restart or change a server, never build the app for a device. The
   repository is public: no server address, account email, key, token or password in a file, a
   commit, the pull request or a comment.
9. Do not edit `HANDOFF.md`, the plan, or files that belong to another brief. Do not merge. Write
   nothing on GitHub except the pull request description.
10. No model name in a commit, a pull request or a document. Do not use the word "partner".

## Stop and ask the lead when

- a fix needs a mechanism the plan does not name;
- the code cannot do what the plan says, or the plan and the code disagree about a fact;
- a change would alter a money, code or matching result in a way the plan does not state;
- something marked **[Guess]** turns out to be wrong;
- the only way forward would weaken a test.

Say what you found, with file and line, and what you would do. Then wait. The lead takes it to the
planner. Do not patch around it.

## What you hand back

- The branch pushed, CI green on its head, and that head's commit id.
- The evidence table: one row per finding under "Tests", with the finding, the report it came
  from, the red test and the commit where it fails, the green test, and device evidence where this
  brief asks for it.
- The inventory of writers and callers of each mechanism you built: who writes the field, who
  calls the function.
- The tests you removed or rewrote, each with its reason.
- What you saw outside this brief, as a note for a follow-up. Do not fix it.
- `docs/handoff/status/P3B.md` on the branch, rewritten to say where the work stands,
  and what P3B-C needs to know.
