# Brief S1-A: the phone's session record and core

**Builder:** Claude Opus, extra-high effort.
**Branch:** new, named by the lead, started from the tip of `claude/n1-notification-first-open`,
because S1 rewrites three phone files that N1 changed. When N1 merges, merge `origin/main` in. If
the lead prefers, wait for N1's merge and start from `main`. One pull request for S1-A and S1-B.
It merges after N1 and before P3B.
**Starts:** when the lead gives you Ismail's answers to the plan's decisions.
**Read first:** `CLAUDE.md`, the mobile rules included; `docs/handoff/builders/README.md`; the
plan (`docs/handoff/LOOP_END_PLAN.md`) sections 3, 4 (rules R7, R8, R9), 5.3 (the sign-out
contract), 5.4 and 10, and the P3B r8 and N1 r5 rows of Appendix A. The code you replace:
`mobile/lib/core/session/session.dart` and `token_store.dart`,
`mobile/lib/core/api/api_client.dart`, `mobile/lib/data/auth_repository.dart`.

## 1. Your job

Build the phone's session core: one stored record, one writer, one way in and one way out. You
own S-1, S-2, S-3, S-5 and S-6. Brief S1-B then puts the member's screens inside a boundary that
ends with the session. Together you close a problem that failed in P3B (rounds 3 to 8) and in N1
(rounds 3 to 5).

## 2. What the code does today (checked on `main`)

- Credentials are three keys written one after the other (`token_store.dart`), with
  `AndroidOptions(encryptedSharedPreferences: true)`.
- Two generation counters decide what is current.
- Credentials are removed in four places: `auth_repository.signOut`, the interceptor's
  `_endSession`, `SessionController._confirm`, and `accountDeleted`.
- `_confirm` removes credentials on any error that is not "retryable", and a 429 is not.
- The Android activity is `singleTop` with an empty task affinity, so a second task can start a
  second Flutter engine on the same storage.
- The token refresh is already one request at a time and compares the refresh token it sent
  (`api_client.dart`, `_refreshOnce`). Keep that.

## 3. What you build

Paths are under `mobile/`.

**S-1. One record, one writer** (`lib/core/session/`).

- One stored document under one key: the current sign-in (`sid`, account snapshot, access token,
  refresh token) or none, plus the list of ended sign-ins whose end the server has not confirmed.
  Language, push prompt count, push sequence and installation id stay separate keys.
- Every transition is one write of that key: storage first, then the in-memory copy, then the
  answer to the caller. A write that throws means the transition did not happen: memory is
  unchanged and the caller is told.
- One object, `SessionCore`, created in `main()`, holds the only in-memory copy and runs every
  write through one queue. Only the UI isolate touches the record; the push background handler
  does not.
- One Flutter engine: the activity becomes `singleTask` in the Android manifest.
- No migration from the three old keys. A test phone signs in again. Write no code for them.

**S-2. One transition at a time.**

- A sign-in attempt is reserved before any await. It can be reserved only when the state is
  signed out and no attempt is open. Every sign-in control reads one busy state from the core.
- An attempt ends with its answer or with the HTTP timeout. There is no cancel path.
- There is no step from member A to member B. B starts from signed out.
- If tokens were issued and the record write fails: post that sign-in's end once, from memory,
  and give the screen a typed, translated error.
- Everything is keyed by `sid`, not by account. One member signing out and in again is two
  sign-ins.

**S-3. One exit, always for a named sign-in.**

- Credentials leave the current slot only through `end(sid, reason)`, and only if `sid` is still
  the current sign-in. Reasons: the member signed out; the server refused the refresh token that
  is current; the account was deleted.
- No other answer ends a session. A 429, 403, 404, 5xx, timeout or offline answer, on `/api/me`
  or anywhere else, keeps the member signed in. A 429 at launch waits for its `Retry-After`.
- `end` is one write: current becomes none, and the sign-in moves to the ended list with its
  refresh token. Then memory, then the boundary reset (S1-B), then the sender of S-5.
- If that write fails on a member's sign-out, the member stays signed in and is told. If it
  fails for a session the server refused, the phone ends it in memory; the next launch meets the
  same refusal and ends it again.
- **A record that cannot be read.** The store is opened with `first_unlock_this_device`, so on
  an iPhone it cannot be read between a restart and the first unlock, and the system can start
  the app in that time. So: while the record has not been read, the app shows the start screen,
  no private screen and no sign-in, and **never writes the record**. It reads again each time
  the app comes to the foreground. A read that fails while the app is in the foreground, or a
  record that is read and cannot be parsed, is permanent loss: the core stores an empty record
  and deletes the phone's push token (`FirebaseMessaging.deleteToken`), retrying until it
  succeeds, so no earlier sign-in can show a push on this phone. The member is signed out.

**S-5. The server hears about every ended sign-in.**

- A sender inside the core posts each entry of the ended list to `POST /api/auth/sign-out` with
  that entry's own refresh token and no other credential: at once, at launch, and when the app
  returns to the foreground.
- An entry is removed only on **205**, or on **400 `sign_out_proof_invalid`**. Every other
  answer keeps it. Entries are keyed by `sid`. Nothing is evicted and there is no cap.
- Until N1's endpoint is on your branch, test against a fake that answers exactly as plan
  section 5.3 says.

**S-6. Newer truth wins** (plan rule R9). The account snapshot has one owner. Only it reads
`/api/me`; a profile write, whatever it answered, makes it read again; no other code sets the
snapshot from another call's answer. The snapshot stored in the record follows what is shown.
**[Guess]** A rebuilt Riverpod provider drops the result of its earlier build. Prove it with the
test "two reads answered in reverse order". If it does not hold, keep one request counter inside
the owner and accept only the newest. Build no helper class.

## 4. What you remove

The three credential keys and the identity generation in `TokenStore`. `_generation` in
`SessionController`. The `expectedIdentityGeneration` path of `auth_repository.signOut`. The
interceptor's `_endSession`. The clear inside `_confirm`. N1's `_endSignInOnServer` and its own
sign-out bookkeeping.

## 5. What is not yours

The boundary, the router, the sign-in screens and the sockets (S1-B). The server (N1). Profile
photos (P3B). A lost refresh answer (S2, on the server).

## 6. Tests

Red first, on the rejected branches where the behaviour exists: N1 round-5 blockers 2 and 3 and
P3B round-8 blocker 2 (plan Appendix A). Green here.

- **S-1:** the write throws, at each transition: the state before, in memory and after a
  restart. Two task launches: one engine. A server acknowledgment and a snapshot write queued
  together: neither is lost.
- **S-2:** password and Google tapped in one frame; a second attempt while the first waits;
  tokens issued and the record write fails; two refresh triggers make one request; a refresh
  refusal that arrives after another refresh rotated the token is ignored; the same account
  signs out and in again, and the first sign-in's late answers touch nothing.
- **S-3:** for each of 401 after a refused refresh, 401 with a network error on refresh, 403,
  404, 429 with `Retry-After`, 500, timeout and offline: on `/api/me` at launch and on an
  ordinary request. A record that cannot be read in the background, then is readable in the
  foreground: the member is still signed in and nothing was written. A record that cannot be
  read in the foreground. A record that cannot be parsed. A failed `end` write, then a restart.
- **S-5:** an expired proof, a rotated proof, a deleted account: 205 removes the entry. A 401,
  403, 404, 429 and 500 keep it. A lost 205, then the repeat. Nine sign-outs while the endpoint
  fails: nine entries, all sent later. The app closed before the send. No request carries
  another sign-in's credentials.
- **S-6:** two reads answered in reverse order; a write answered after a newer read; the same
  after a restart.

Mechanical checks: one place writes the record key; one function empties the current slot; no
read of an access token outside the core.

## 7. Done when

1. The three findings are tests, red before and green after, and every case of section 6 passes.
2. `docs/handoff/status/S1.md` tells S1-B where things stand. CI is green on your last commit.
