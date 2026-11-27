# Builder brief P3B-C: the photo controller and its screens

**Builder:** Claude Opus, high effort. One builder at a time on the branch.
**Start only when** the lead says the plan is approved and gives you Ismail's answers to D1 to D9.
**Plan:** `docs/handoff/LOOP_END_PLAN.md` at commit `e66bb5b`, on branch
`claude/project-thread-mb20d4`. Read it with `git fetch origin claude/project-thread-mb20d4` and
`git show e66bb5b:docs/handoff/LOOP_END_PLAN.md`. If the lead names a later commit, use that one.
Where this brief and the plan differ, the plan wins, and you tell the lead.

## 1. Your job

Close the phone side of P3B: P-E (every write names the state it saw), P-F (one photo operation
at a time) and P-G (a newer truth wins). Then run the member-boundary rows with the photo section
on screen. You are the last brief on the branch, so you also finish the pull request.

## 2. Branch and order

- Branch `claude/p3b-profile-photos-app`, pull request #66. You start from P3B-B's pushed, green
  head. Pull first.
- After you, the lead writes the Astra prompt for the whole pull request.

## 3. Read first

1. `CLAUDE.md`, including the mobile rules.
2. The plan: sections 3 and 4 (rule R9 and the `ReadOrder` helper), sections 9.2 (P-E, P-F with
   its table, P-G), 9.4 and 9.5, the P3B r8 rows of Appendix A, and item 5 of Appendix B.
3. On your branch: `docs/handoff/status/P3B.md` as P3B-B left it, with P3B-A's note on how the
   revision travels.

## 4. What you build

Paths are under `mobile/`.

**P-E on the phone.** Every member write sends the slot revision the screen was drawn from: the
first upload, a replacement, a retry, a removal, a dismissal. A 409 `profile_photo_changed` does
not carry the new state; the phone reads again (P-G).

**P-F. The transition table** (`lib/app/profile_photo_state.dart`). Rebuild the controller to the
table in plan section 9.2: the states Idle, Picking, Preparing, Uploading, Failed and Removing,
and for each the commands it accepts.

- A command is accepted or refused synchronously, before the first await, and moves the state in
  the same call. Two taps in one frame can never both be accepted.
- Each operation has an id and owns its files until it ends. Every completion and every progress
  callback carries its operation id. One that is not for the current operation changes no state;
  it may only delete its own files.
- File paths are unique per operation, and an operation's cleanup touches only its own files.
- Session end or dispose cancels the operation and deletes its files.

**A control acts on what it was drawn for** (`lib/features/profile/profile_photo_section.dart`).
Each control is keyed by the operation or the slot revision it shows, so a rebuild for another one
replaces it and ends a held gesture. Its callback carries that same id, and the controller refuses
a mismatch.

**P-G. One store for the member's own photo.** Every writer of the embedded photo goes through
it: `/api/me`, the answers to profile writes, and any response that embeds the member's own
photo. It is ordered by `ReadOrder` (`lib/core/read_order.dart`, already on `main`). A success and
a 409 both call `changed()`, which drops older reads, reads again and invalidates the same
dependent previews. Every surface that shows the member's own photo, retained previews included,
reads from that store.

## 5. What you remove

Whatever of the old controller the table replaces: its ad hoc launch and liveness flags, and any
second place that holds the member's own photo.

## 6. What is not yours

- The session core and the boundary (on `main`, from S1). The server (P3B-A).
- Pick ownership, image preparation and the avatar cache (closed families P-A, P-B, P-C): their
  tests stay green and their code stays as it is.

## 7. Tests

Red first: round-8 should-fix 2 (Retry and Discard in the same frame) and should-fix 3 (after a
409, an older `/api/me` undoes the fresh state and retained previews stay stale). Should-fix 1 is
P3B-A's on the server; add its phone half (an old Remove dialog sends the old revision and gets
the 409).

- **P-F:** every cell of the table; both orders of every pair of commands in one frame; a stale
  completion during a new operation; a slow cleanup during a new operation; pointer down, the
  slot's revision changes, pointer up.
- **P-G:** a 409 followed by an older `/api/me`; an upload answer followed by an older read; an
  older public-profile response; a failed refresh; a warm preview after a 409; the newer state
  after a restart.
- **P-E:** each member command sends the revision it was drawn from; a missing revision cannot be
  sent.
- **P-D:** the S-4 rows of plan section 5.5, with the photo section and the removal notice on
  screen.

**Device check (P-B).** Write the steps to prepare the same input twice on an Android phone and
on an iPhone, and what to compare. Do not build for a device. The result is recorded in the phase
document at the phone test.

## 8. Done when

1. The findings above are tests, red before and green after. The three round-8 blockers are
   covered by S1's tests, run here with the photo section mounted.
2. The rows above pass.
3. Screenshots in English and Arabic at 360 px for the photo states that changed. Nothing hides
   behind the bottom navigation.
4. New strings exist in English, French and Arabic.
5. `docs/PHASE_P3B_PROFILE_PHOTOS_APP.md` describes the final design in about 200 lines, with one
   evidence table for P3B-A, P3B-B and P3B-C and a place for the device check's result. The entry
   in `docs/IMPLEMENTATION_STATUS.md` is updated.
6. The pull request description lists each "Done when" line of plan section 9.5 with its
   evidence, the tests removed or rewritten on the whole branch, and the inventory of writers.
7. Every CI check is green, "Schema drift" included.

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
- `docs/handoff/status/P3B.md` on the branch, rewritten to say where the work stands.
