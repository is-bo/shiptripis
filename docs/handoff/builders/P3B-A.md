# Builder brief P3B-A: the photo slot on the server

**Builder:** Claude Opus, high effort. One builder at a time on the branch.
**Start only when** the lead says the plan is approved and gives you Ismail's answers to D1 to D9.
**Plan:** `docs/handoff/LOOP_END_PLAN.md` at commit `e66bb5b`, on branch
`claude/project-thread-mb20d4`. Read it with `git fetch origin claude/project-thread-mb20d4` and
`git show e66bb5b:docs/handoff/LOOP_END_PLAN.md`. If the lead names a later commit, use that one.
Where this brief and the plan differ, the plan wins, and you tell the lead.

## 1. Your job

Close the server side of family P-E on the P3B branch: a member's write names the state it saw.
Today an empty photo slot looks the same before and after an upload and a removal, so an old
request can act on a state the member never saw. You give the slot a revision that outlives the
photo. Server only. Two briefs follow you on the same branch after S1 merges: P3B-B and P3B-C.

## 2. Branch and order

- Branch `claude/p3b-profile-photos-app`, pull request #66. Last reviewed head: `7727b19`
  (rejected, round 8).
- First merge `origin/main` into the branch with a merge commit.
- You can run beside F1, G1-A, N1 and S1-A. You touch no phone file.
- The phone keeps sending the old parameter until P3B-C. That is fine: the branch does not merge
  before P3B-C.

## 3. Read first

1. `CLAUDE.md`.
2. The plan: sections 3 and 4, section 9.2 (P-E) and 9.4, the P3B r8 rows of Appendix A, and item
   5 of Appendix B.
3. On your branch: `docs/handoff/status/P3B.md`, `docs/PHASE_P3B_PROFILE_PHOTOS_APP.md`, and
   `backend/monolith/apps/accounts/photos.py` from top to bottom.

## 4. What you build

Paths are under `backend/monolith/`.

**The slot has a revision** (`apps/accounts/models.py` `ProfilePhoto`; `apps/accounts/photos.py`).

- A new field `revision`: an opaque random token that changes on every transition of the slot: an
  upload, the member's own removal, a staff removal, the dismissal of a removal notice.
- A new state `empty`. Once a row exists, a member's action never deletes it. The member's removal
  and the dismissal (today both `remove_own_photo`, which deletes the row) leave the row `empty`
  with a new revision. The stored object is still released, as the row's deletion releases it
  today.
- Before the first upload there is no row. The slot's revision is then one fixed value that means
  "never had a photo".
- `version` keeps its one job: the identity of the image, for caches.
- Account erasure (`erase`) may still delete the row.

**Every member write carries the revision it saw** (`apps/accounts/views.py` `MePhotoView`;
`replace_photo`, `remove_own_photo`).

- The first upload, a replacement, a retry, a removal and a dismissal all carry it, in the same
  way. Today the removal carries `version` as a query parameter. A request header is the cleaner
  home for a precondition. Choose one, use it for PUT and DELETE alike, and write it in the API
  contract and in the status file for P3B-C.
- A write without a revision is refused with a stable code.
- The server compares under the member lock (`_hold_member`), before the new object is published.
  A mismatch is the existing 409 `profile_photo_changed`, with its body unchanged, and the object
  uploaded for that request is released.

**Staff removal moves the revision** (`remove_by_staff`; `apps/admin_panel/console_photos.py`).
It keeps naming the `version` the staff member looked at.

**The owner's payload states the revision; nobody else's does** (`own_view`, `own_photo`,
`public_photo`). The owner always gets the slot's revision, also when the slot is empty. Make the
smallest change to the owner's payload that does this. Public payloads do not change, and a
privacy test proves the revision is in none of them.

## 5. What you remove

The row deletion in `remove_own_photo`. The optional `version` on the member's removal: the
revision replaces it, and it is required.

## 6. What is not yours

- Every file under `mobile/` (P3B-B and P3B-C).
- Image preparation, the avatar cache, pick ownership (closed families P-A, P-B, P-C).
- How staff decide to remove a photo.

## 7. Tests

Red first: round-8 should-fix 1 (a staff removal keeps the version, so an old Remove request
deletes the new notice), and the sequence empty, then active, then empty again against an old
"empty" write.

Then the P-E rows of plan section 9.4:

- two first uploads with the same revision, with real threads: one is stored, one gets the 409 and
  its object is released;
- a write with no revision;
- a stale retry;
- each member command opened in state X against each change in between: a staff removal, and an
  upload, a removal or a dismissal from a second device;
- the revision is absent from every public payload.

The existing photo tests (`apps/accounts/tests/test_p3a_profile_photos.py` and the P3B server
tests) stay green; those that send a removal without a precondition are rewritten to send one, and
listed.

## 8. Done when

1. The two sequences above are tests, red before and green after.
2. The rows above pass.
3. The migration is generated, `task check-drift` is clean and the contract is committed.
4. CI is green on your head, and the status file tells P3B-C how the revision travels and which
   code a missing one gets.

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
