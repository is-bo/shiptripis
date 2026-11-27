# Builder brief S1-B: the member boundary and the screens

**Builder:** Claude Opus, extra-high effort. One builder at a time on the branch.
**Start only when** the lead says the plan is approved and gives you Ismail's answers to D1 to D9.
**Plan:** `docs/handoff/LOOP_END_PLAN.md` at commit `e66bb5b`, on branch
`claude/project-thread-mb20d4`. Read it with `git fetch origin claude/project-thread-mb20d4` and
`git show e66bb5b:docs/handoff/LOOP_END_PLAN.md`. If the lead names a later commit, use that one.
Where this brief and the plan differ, the plan wins, and you tell the lead.

## 1. Your job

Make the member's screens end with the member's session: family S-4. S1-A built the session
core. You put the app's provider container and screen tree inside a boundary that is thrown away
when a session ends, and you bind everything that outlives a screen to its sign-in. You are the
last brief on the branch, so you also finish the pull request.

## 2. Branch and order

- The S1 branch. You start from S1-A's pushed, green head. Pull first.
- One pull request for S1-A and S1-B. It merges after N1 and before P3B.

## 3. Read first

1. `CLAUDE.md`, including the mobile rules.
2. The plan: sections 3 and 4 (rules R7 and R10), section 5 (S-4 above all, then 5.4 to 5.7), the
   P3B r8 rows of Appendix A, and item 1 of Appendix B.
3. On your branch: `docs/handoff/status/S1.md` as S1-A left it; `mobile/lib/main.dart`,
   `mobile/lib/app/app.dart`, `mobile/lib/app/router.dart`, `mobile/test/support/harness.dart`.

## 4. What you build

Paths are under `mobile/`.

**The boundary** (`lib/main.dart`, `lib/app/app.dart`).

- A `MemberBoundary` widget above the app owns the provider container. On `end` it disposes the
  old container and builds a new container and a new app subtree under a new key.
- The core, the push messaging handle and the device settings (language, theme) are created
  outside and passed in. Language and theme are identical on the frame before and after.
- The old container is disposed without the signed-out state being published into it.
- The core refuses to reserve a sign-in until the boundary reports the first frame of the new
  tree.
- **[Guess]** Replacing the container at the app root works with `go_router`, the push coordinator
  and the plugins in use. It was reasoned from the code, not prototyped. If it cannot be made to
  work, stop and tell the lead. A per-screen substitute is not acceptable.

**No top-level key** (`lib/app/router.dart`). `_rootNavigatorKey` moves inside the router
provider. No top-level `GlobalKey` remains in `mobile/lib`.

**The API client is built for one sign-in.** Its provider lives in the member's container and
depends on the sign-in. It is closed when the container is disposed. An old client object gets
"session ended".

**Sockets belong to the member's container** (`lib/core/live/live_updates.dart`,
`lib/core/push/notification_socket.dart`). They take their token through the client of their
sign-in, close on dispose, and cannot reconnect after the end.

**Events from outside the tree** (a push that is opened, a link, a native result) are delivered to
the current tree as a destination to show, never as authority. A native result that returns into
disposed code is dropped.

**A guest who signs in keeps the tree**, so "sign in to continue" still works. Only the flow that
asked for the sign-in continues, through the router's return location. Other work that kept a
client from before the sign-in fails with "session ended".

**The sign-in controls** (`lib/features/auth/`). All of them read the core's one busy state. The
four separate busy flags go. The typed error for "tokens issued, could not be saved" is shown,
translated.

**The start screen for a record that cannot be read.** No private screens and no sign-in while the
core says "not readable yet". After repeated failures it offers "sign in again on this phone",
which calls the core's permanent-loss path.

**Shown notifications are cleared at `end`.** One native call per platform removes the app's
delivered notifications from the tray.

**The test harness** (`test/support/harness.dart`). `pumpApp` mounts the real boundary, so every
existing test runs through it.

## 5. What you remove

`_leavePrivateScreens` in the router. The four sign-in busy flags. Whatever S1-A left as a
temporary adaptation of a call site. Any per-screen check of "who is signed in now" that the
boundary makes unnecessary.

## 6. What is not yours

- The record, the core, the refresh and the sign-out sender (S1-A). If the boundary needs
  something the core does not offer, stop and ask; do not add a second source of truth.
- The profile photo section. It is not on this branch; P3B runs your S-4 rows again with it on
  screen.
- The permission prompt and the registration state machine. Anything on the server.

## 7. Tests

Red first, on `claude/p3b-profile-photos-app` at `7727b19`: round-8 blocker 1 (pointer down on
A's button, a rebuild publishes B, the release runs B's callback) and blocker 3 (a name draft and
a language retry take their scope when submitted). Then the green tests here, through the real
screens.

The S-4 row of plan section 5.5, all of it:

- pointer down on a member's button, `end`, pointer up;
- a dialog, a sheet and a draft in a text field at `end`, then another member signs in;
- A's delayed account-deletion or sign-out completion after B signed in;
- the KYC and cheque files, the name and language retry, and the public-profile consent across an
  end;
- an open socket at `end`; a native result after the reset;
- an old client object and an old `ref` after `end`;
- "sign in to continue" resumes only the flow that asked;
- language and theme on the frame before and after the reset;
- delivered notifications gone after `end`;
- the unreadable-record start screen, and its "sign in again on this phone" choice;
- the S-2 screen rows: password and Google tapped in one frame; a second attempt while the first
  waits.

Mechanical checks: no top-level `GlobalKey` in `mobile/lib`; no provider outside the member's
container holds a client or a socket.

## 8. Done when

1. The two findings above have red tests on the P3B branch and green tests here.
2. Every row of plan section 5.5 passes: S1-A's and yours.
3. Screenshots in English and Arabic at 360 px for each changed screen state. Nothing hides
   behind the bottom navigation.
4. New strings exist in English, French and Arabic.
5. `docs/PHASE_S1_SESSION_CORE.md` describes the final design in about 200 lines, with one
   evidence table for S1-A and S1-B and a place for the kill test's result. The entry in
   `docs/IMPLEMENTATION_STATUS.md` is added.
6. The pull request description lists each "Done when" line of plan section 5.6 with its
   evidence, the tests removed or rewritten on the whole branch, and the inventory of writers.
7. The whole mobile suite and the Android build are green in CI.

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
- `docs/handoff/status/S1.md` on the branch, rewritten to say where the work stands.
