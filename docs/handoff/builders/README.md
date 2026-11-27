# Builder briefs

One file per brief. The lead hands a brief to a builder as it is. The order, the branches and the
model and effort of each brief are in section 9 of the plan, `docs/handoff/LOOP_END_PLAN.md`.

The plan and these briefs are on `main` once the lead has copied them there. Until then they are
on branch `claude/project-thread-mb20d4` (`git fetch origin claude/project-thread-mb20d4`).

A builder reads, in this order: `CLAUDE.md`, this file, its brief, and the plan sections its brief
names. Where a brief and the plan differ, the brief wins for details and the plan for rules, and
the builder tells the lead.

## Rules, the same for every builder

1. **Ponytail.** Work as the section "Working style: ponytail" of `CLAUDE.md` says: the smallest
   change that fully solves the problem, with what the codebase already has. In money, payout,
   codes, sign-in, staff authority, matching and location code there is no `shortcut:`.
2. **Build what your brief names and nothing else.** Add no lock, counter, flag, column, job kind,
   retry loop, helper class or option that the brief does not name. If one seems needed, stop and
   ask.
3. **Red first.** Reproduce each finding your brief lists as a failing test before you fix it. A
   failing test must tell the bad outcome apart from a correct serial execution.
4. **Tests.** Test every case the brief lists. Group tests by rule, in files named after the rule,
   not after a review round. Never skip or weaken a test. A test goes only together with the code
   it tested, and the pull request lists it with the surface it covered.
5. **Remove what you replace**, in the same pull request. No commented-out code, no parameter for
   later, no second copy of a rule.
6. The server enforces every rule. The app never fakes a result. Every user-facing string exists
   in English, French and Arabic. Each new or changed screen state has a screenshot in English and
   in Arabic at 360 px.
7. After a migration, run `task check-drift` in `backend/` and commit the regenerated contract.
8. Push only to your branch, with ordinary pushes: no force push, no rebase of pushed commits. To
   take in `main`, merge it. The whole suites and the Android build run in GitHub CI on the
   branch. While you fix, re-run locally only the tests that failed. The work is ready only when
   every CI check is green, "Schema drift" included.
9. Never deploy, never restart or change a server, never build the app for a device. The
   repository is public: no server address, account email, key, token or password in a file, a
   commit, the pull request or a comment.
10. Do not edit `HANDOFF.md`, the plan, or files that belong to another brief. Do not merge. Write
    nothing on GitHub except the pull request description.
11. No model name in a commit, a pull request or a document. Do not use the word "partner". The
    requirements document of 11 November is "the cahier des charges".
12. **Documents.** Write `docs/PHASE_<id>_<NAME>.md`: the final design in at most 150 lines, with
    the evidence table. Add a dated entry at the top of `docs/IMPLEMENTATION_STATUS.md`. Round
    history stays in git.
13. **Before you hand back**, run `/ponytail-review` on your whole change against `main`. Fix what
    it finds. A finding whose fix needs something your brief does not name is reported, not fixed.

## Stop and ask the lead when

- a fix needs a mechanism the brief does not name;
- the code cannot do what the brief says, or the brief and the code disagree about a fact;
- a change would alter a money, code or matching result in a way the brief does not state;
- something marked **[Guess]** turns out to be wrong and the brief names no fallback;
- the only way forward would weaken a test.

Say what you found, with file and line, and what you would do. Then wait. The lead takes it to the
planner. Do not patch around it.

## What you hand back

- The branch pushed, CI green on its head, and that head's commit id.
- The evidence table: one row per finding or rule under "Tests", with the red test and the commit
  where it fails, the green test, and device evidence where the brief asks for it.
- For a brief that deletes: the inventory, with the search that shows each item is unused.
- The tests you removed or rewrote, each with its reason.
- The verdict of `/ponytail-review`, and what you did not fix, with the reason.
- What you saw outside your brief, as a note for a follow-up. Do not fix it.
- `docs/handoff/status/<BRIEF>.md` on the branch: where the work stands.

End your reply to the lead with one or two lines: what you skipped or did not check, and any risk
Ismail must know.
