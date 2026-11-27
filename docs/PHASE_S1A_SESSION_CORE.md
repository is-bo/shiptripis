# S1-A: the phone's session record and core

Brief `docs/handoff/builders/S1-A.md`, loop-end plan section 5.4, rules S-1, S-2, S-3, S-5 and
S-6. Branch `claude/s1-session-core`, started from N1 and merged with it; S1-B continues on the
same branch and the same pull request. Phone only. Nothing deployed, no app build.

## The record

One document in secure storage under one key, `session.record`:

```
{"current": {"sid", "account": <snapshot fields>, "access", "refresh"} | null,
 "ended":   [{"sid", "refresh"}, ...]}
```

`current` is the sign-in on this phone or none. `ended` holds the sign-ins whose end the server
has not confirmed yet. The language, the role context, the installation id, the push prompt count
and the push sequence stay separate keys in `TokenStore`, which no longer holds anything of a
sign-in. There is no migration from the three old keys: a test phone signs in again.

## The core (`mobile/lib/core/session/session_core.dart`)

`SessionCore` is created once in `main()`, outside every provider container, and handed in through
`sessionCoreProvider`. It holds the only copy of the record in memory and is the only code that
reads or writes it. Every change runs through one queue and is one write (`_commit`): storage,
then memory, then the listeners. A write that throws changed nothing and the caller is told. Only
the UI isolate touches it; the push background handler does not.

| Call | What it does |
|---|---|
| `load()` | Reads the record once. While unread: the splash, no sign-in, no write. |
| `resumed()` | The app came to the foreground: reads again if unread, else sends the ended list. |
| `reserve()` / `release()` | The one sign-in attempt: only when the record is read, nobody is signed in and no attempt is open. `busy` is the one busy state. |
| `signedIn(attempt, signIn)` | Stores the issued sign-in. If it cannot be stored: posts that sign-in's end once, from memory, and throws `SessionNotSaved`. |
| `replaceTokens(sid, sentRefresh, ...)` | A refresh's answer, only while `sid` is current and still holds the refresh token sent. |
| `updateAccount(sid, account)` | The account shown, only while `sid` is current. |
| `end(sid, reason, refusedRefresh)` | The one exit. |
| `sendEnded()` | The sender of S-5. |
| `accessFor(sid)` | The only way to the access token: answers only while `sid` is current. |

## The rules and where each one lives

- **S-1. One record, one writer.** `_commit` is the one place the key is written; every
  transition goes through `_serial`. The Android activity is `singleTask`, so a second task does
  not start a second engine over the same storage.
- **S-2. One transition at a time.** `SessionController.signInWith` reserves before its first
  await; password, sign-up, Google and Apple all go through it, so a second tap starts nothing.
  There is no step from member A to member B: `reserve` refuses while anyone is signed in.
  Everything is keyed by `sid`, decoded from the refresh token's `sid` claim
  (`SessionCore.sidOf`). The failure "tokens issued, could not be saved" is `SessionNotSaved`,
  shown by `describeFailure` in English, French and Arabic.
- **S-3. One exit.** `end(sid, reason)` acts only while `sid` is current; for a refusal, only
  while the refused token is still the current one. Reasons: `signedOut`, `refused` (the refresh
  endpoint answered 401 for the token that is current) and `deleted`. Nothing else ends a sign-in:
  the launch confirmation (`SessionController._confirm`) waits a 429 out for its `Retry-After` and
  retries no network or a server error on its short schedule; it clears nothing. `end` is one
  write; if it fails on a sign-out the member stays signed in and the Profile screen says so; for
  a refusal or a deletion the sign-in ends in memory and the next launch meets the same answer.
  An unreadable record: a failed read with the app in the background is waited out, and read
  again on the next foreground; a failed read in the foreground (5 s budget) or a record that
  cannot be parsed is lost for good: an empty record is stored, and the push token is deleted
  (`FirebaseMessaging.deleteToken` from `main()`) until that succeeds, the wait doubling up to five
  minutes.
- **S-5. The server hears about every ended sign-in.** `sendEnded` posts each entry to
  `POST /api/auth/sign-out` with its own refresh token and nothing else (no bearer, no
  installation id, no sequence): at once after an end, at launch, and on every return to the
  foreground. An entry leaves the list only on 205 or 400 `sign_out_proof_invalid` (N1's
  contract); every other answer keeps it. No cap, no eviction.
- **S-6. Newer truth wins.** `SessionController` is the one owner of the account: only `_read`
  reads `/api/me` and only it stores the answer. A profile write (`_write`) ignores its own answer
  and reads again. The brief's guess, that a rebuilt provider drops an older answer, does not
  hold: the controller is a `Notifier` that is not rebuilt between reads. So `_reads` counts the
  reads and only the newest is stored. With that check removed, "two reads answered in reverse
  order" fails (shown `Older`, expected `Newer`).

The API client (`mobile/lib/core/api/api_client.dart`) binds every request to the `sid` current
when it starts. Its interceptor takes the bearer from `accessFor(sid)` in the same step that sends
the request, refuses a request of a sign-in that ended, never replays a 401 of an earlier sign-in,
and keeps one refresh in flight per refresh token sent.

The role context leaves with the sign-in: when a sign-in ends the controller removes it, and at
sign-in it stores the server's side (or the guest's choice for an account that can do both), as
before.

## What was removed

The three credential keys and the account snapshot key in `TokenStore`, its identity generation,
`bearerWithheld` and every credential write and clear. `SessionController._generation`,
`restore()`, `handleSessionExpired()` and the clear inside `_confirm`. `AuthRepository.signOut` with its `expectedIdentityGeneration` path, its installation
id and its sequence, and the token arguments of every sign-in method. The interceptor's
`_endSession` and `OnSessionExpired`. The splash screen's offline retry, which nothing reaches any
more: a stored sign-in always carries its account, so the splash never waits for the network.

## Evidence

| Finding or rule | Red (rejected commit) | Green (this branch) |
|---|---|---|
| N1 r5 blocker 2: a sign-out overtaken by a sign-in returns without sending | `RED N1r5-B2` on N1 `3e7fc17`: sign-out list `[]`, expected `['old-refresh']` | `s1a_session_core_test.dart` S-5 "a sign-out overtaken by another sign-in still ends the first sign-in on the server" |
| N1 r5 blocker 3: a 429 on the launch `/api/me` clears credentials | `RED N1r5-B3` on N1 `3e7fc17`: `SessionSignedOut`, expected `SessionSignedIn` | S-3 "429 with Retry-After on /api/me at launch keeps the member signed in" and "a 429 at launch waits for its Retry-After" |
| P3B r8 blocker 2: an interrupted credential save leaves A on screen with B's bearer | `RED P3Br8-B2` on P3B `2ef5d95`: `Bearer b-access` with A shown | S-1 "an interrupted sign-in save never leaves one member on screen with another's bearer" |
| S-1 | | S-1 group: each transition's write refused (memory and a restart unchanged), a confirmation and an account write queued together, the `singleTask` manifest check |
| S-2 | | S-2 group: password and Google in one frame, a second attempt while one waits, tokens issued and not stored, two refresh triggers, a late refusal after a rotation, the same account out and in again |
| S-3 | | S-3 group: 401 after a refused refresh ends; 401 with no network on the refresh, 403, 404, 429, 500, timeout and offline keep the member, on `/api/me` at launch and on an ordinary request; the unreadable record in the background, in the foreground, unparseable |
| S-5 | | S-5 group: 205 and 400 `sign_out_proof_invalid` remove; 401, 403, 404, 429, 500, another 400 keep; a lost 205 then the repeat; nine sign-outs while failing; closed before the send; no other sign-in's credentials |
| S-6 | | S-6 group: two reads in reverse order; a write answered after a newer read; both after a restart |
| Mechanical | | One place writes the record key; one function empties the current slot; no read of an access token outside the core |

The red tests ran in local worktrees of those commits only; their text is in the pull request.
Whole mobile suite: 1,759 tests pass locally (`flutter test`), `flutter analyze --fatal-infos`
and `dart format` are clean.

## For the phone test

S1-B adds the member boundary. After it, on a device: sign in, put the phone in flight mode and
reopen the app (it opens on the account, no splash); sign out in flight mode, then reconnect and
bring the app to the front (the server ends the sign-in); restart an iPhone and let a push arrive
before the first unlock (the app opens signed in after the unlock).
