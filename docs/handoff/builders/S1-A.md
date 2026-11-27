# Builder brief S1-A: the session record and core

**Builder:** Claude Opus, extra-high effort. One builder at a time on the branch.
**Start only when** the lead says the plan is approved and gives you Ismail's answers to D1 to D9.
**Plan:** `docs/handoff/LOOP_END_PLAN.md` at commit `e66bb5b`, on branch
`claude/project-thread-mb20d4`. Read it with `git fetch origin claude/project-thread-mb20d4` and
`git show e66bb5b:docs/handoff/LOOP_END_PLAN.md`. If the lead names a later commit, use that one.
Where this brief and the plan differ, the plan wins, and you tell the lead.

## 1. Your job

Build the phone's session core: one stored record, one writer, one way in and one way out. You
own S-1, S-2, S-3, S-5 and S-6. A second brief, S1-B, then puts the member's screens inside a
boundary that ends with the session. Together you close a family that failed in P3B (rounds 3 to
8) and in N1 (rounds 3 to 5).

## 2. Branch and order

- A new branch, named by the lead, started from the tip of `claude/n1-notification-first-open`,
  because S1 rewrites three phone files that N1 changed. When N1 merges, merge `origin/main` in.
  If the lead prefers, wait for N1's merge and start from `main`.
- One pull request for S1-A and S1-B together. It merges after N1 and before P3B.
- You can run beside F1, G1-A, N1 and P3B-A. S1-B starts when your work is pushed and green.

## 3. Read first

1. `CLAUDE.md`, including the mobile rules.
2. The plan: sections 3 and 4 (rules R7, R8, R9 and the `ReadOrder` helper), all of section 5,
   AR-1 and AR-3 to AR-5 in section 11, the P3B r8 and N1 r5 rows of Appendix A, and item 1 of
   Appendix B.
3. The code you replace, on your branch: `mobile/lib/core/session/session.dart` and
   `token_store.dart`, `mobile/lib/core/api/api_client.dart`, and
   `mobile/lib/data/auth_repository.dart`.
4. The server contract you rely on: plan section 5.2. N1 builds it. Until it is on your branch,
   test against a fake that answers exactly as 5.2 says.

## 4. What you build

Paths are under `mobile/`.

**S-1. One record, one writer, durable when acknowledged** (`lib/core/session/`).

- One stored document under one key: the current sign-in (`sid`, account snapshot, access token,
  refresh token) or none, plus the list of ended sign-ins the server has not confirmed. Language,
  push prompt count, push sequence and installation id stay separate keys.
- Every transition is one write of that key. The core changes its in-memory copy, publishes
  anything and answers its caller only after the write is on disk.
- Android: the storage plugin writes with `apply()`, which returns before the disk write. After
  each record write, call one small native method that runs `commit()` on the same preferences
  file. The store is opened with `encryptedSharedPreferences: true`; name the file explicitly
  (`sharedPreferencesName`) so the flush names the same one.
  **[Guess]** `commit()` waits for the outstanding `apply()`. This is the platform's documented
  behaviour. The kill test below decides. If it fails, the only fallback is a native store that
  encrypts with the Android Keystore and writes with `commit()`. Stop and tell the lead first.
- iOS: the keychain write is synchronous. Confirm it in the plugin and say so in the phase
  document.
- Only the platform's confirmation counts: on Android the flush returning true, on iOS the
  keychain call returning success. Without it (false, an error, no answer) the transition did not
  happen: keep the previous state, write the previous record again so the stored copy cannot later
  reach the disk with a state nobody acknowledged, and tell the caller. On Android a read-back
  proves nothing, because it is served from memory. On iOS an unknown answer is settled by
  reading the record back.
- One writer per phone. `android:launchMode` becomes `singleTask` (P3B made this change; it is
  yours now). Only the UI isolate touches the record; the push background handler does not. One
  object, `SessionCore`, created in `main()`, holds the only in-memory copy and runs every write
  through one queue.

**S-2. One transition at a time, and every answer names its sign-in.**

- A sign-in attempt is reserved synchronously, before any await, and only when the state is
  signed out and no attempt is open. The core exposes one busy state for all sign-in controls.
- An attempt can be cancelled while it waits. If its answer later arrives with tokens, that
  sign-in goes to the ended list. It never becomes current.
- Tokens issued but the record write fails: try to add the sign-in to the ended list, post its end
  at once from memory, and return a typed, translated error.
- No transition from member A to member B. B starts from signed out only.
- Refresh moves into the core: one request at a time per sign-in. Its answer, success or refusal,
  applies only if the current sign-in still holds the refresh token that request sent. A refusal
  for a token that is no longer current is ignored. A late success is a rotation of a sign-in the
  phone already knows by its `sid`; it is never ended as a new one.
- Everything is keyed by `sid` (read from the token), not by account.

**S-3. One exit, always for a named sign-in.**

- Credentials leave the current slot only through `end(sid, reason)`, and only if `sid` is still
  current. Reasons: the member signed out; the server refused the current refresh token; the
  account was deleted.
- No other answer ends a session: not a 429, 403, 404, 5xx, timeout or offline answer, on
  `/api/me` or anywhere. The member stays signed in and the read is retried. A 429 at launch waits
  for its `Retry-After`.
- `end` is one acknowledged write: current becomes none, and the sign-in joins the ended list with
  its refresh token.
- If that write fails on a member's sign-out, the member stays signed in and is told. If it fails
  for a session the server refused, end in memory, keep retrying the write, and check again at the
  next launch (AR-3).
- The record cannot be read at launch: the core reports "not readable yet", and the app shows the
  start screen with no private screens and no sign-in, and tries again. Never write over a record
  you have not read. If reading keeps failing, the member may choose "sign in again on this
  phone", which is handled as permanent loss.
- Permanent loss, only when the platform reports the data as undecryptable or the text does not
  parse: replace the record with an empty one, delete the push token and retry that until it
  succeeds. **[Guess]** which platform errors mean "undecryptable": list them in the phase
  document.

**S-5. The server hears about every ended sign-in.** A sender inside the core posts each entry of
the ended list to `POST /api/auth/sign-out` with that entry's own refresh token and no other
credential: at once, at launch, when the network returns, with capped backoff. An entry is removed
only on 205 or on `sign_out_proof_invalid`. Every other answer keeps it. Entries are keyed by
`sid`. Nothing is evicted and there is no cap.

**S-6. Newer truth wins** (`lib/core/read_order.dart`). The account snapshot uses `ReadOrder`,
scoped to the sign-in, for what is shown and for what is persisted in the record. If the file is
not on `main` yet, create it with its tests exactly as plan section 4 describes.

**What you prepare for S1-B.** Every call into the core that changes state takes a `sid`: `end`,
the token replacement, the snapshot update. The API client gets its bearer only by asking the core
for the access token of its `sid`, and the core answers only while that sign-in is current. An
ended sign-in gets a typed "session ended" error.

## 5. What you remove

The three credential keys and the identity generation in `TokenStore`. `_generation` in
`SessionController`. The `expectedIdentityGeneration` path of `auth_repository.signOut`. The
interceptor's `_endSession`. The clear inside `_confirm`. The refresh bookkeeping in
`api_client.dart` that the core now owns. N1's `_endSignInOnServer` and its sign-out bookkeeping.

Keep the app compiling and its tests true: adapt the call sites of what you removed in the
simplest way. The screens are S1-B's.

## 6. What is not yours

- `MemberBoundary`, the router, the sockets, the sign-in screens' controls, the test harness and
  clearing shown notifications (S1-B).
- The push registration state machine (closed family N-C) and the permission prompt (N-A). They
  call the core; they do not change.
- Anything on the server.

## 7. Tests

Red first, on the rejected branches where the behaviour exists: P3B round-8 blocker 2 (an
interrupted credential save leaves A on screen with B's bearer) on `claude/p3b-profile-photos-app`
at `7727b19`; N1 round-5 blockers 2 and 3 on the N1 branch at `3e7fc17`. Then the green tests
here, through the public entry points.

The rows of plan section 5.5 for S-1, S-2, S-3, S-5 and S-6. All of them, including:

- the write throws at each transition; the flush answers false, throws or never answers;
- a server acknowledgment and a snapshot write queued together;
- two refresh triggers, a late refusal after a rotation, a late success after `end`, the same
  account signing out and in again, tokens issued and then a failed write;
- every status of the S-3 row, on `/api/me` at launch and on an ordinary request;
- the record unreadable and then readable; unreadable every time; undecryptable;
- nine sign-outs while the endpoint fails; a lost 205; a late acknowledgment for A while B signs
  in.

Mechanical checks: one place writes the record key; one function empties the current slot; no
read of an access token outside the core; no mutating call into the core without a `sid`.

**Device evidence, the kill test.** Write it and its steps: on an Android device or emulator, kill
the process immediately after an acknowledged sign-in, token replacement and sign-out, and check
the state after restart; and start the app from two tasks and check there is one engine. Do not
build or run it on a device yourself. Tell the lead it is ready: running it needs Ismail's OK.

## 8. Done when

1. The three findings above have red tests on their branches and green tests here.
2. The rows and the mechanical checks above pass.
3. The kill test is written, with steps, and handed to the lead.
4. New strings exist in English, French and Arabic.
5. CI is green on your head, and the status file tells S1-B what the core offers.

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
- `docs/handoff/status/S1.md` on the branch, rewritten to say where the work stands,
  and what S1-B needs to know.
