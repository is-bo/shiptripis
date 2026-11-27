# Brief S1-B: the member boundary and the screens

**Builder:** Claude Opus, extra-high effort.
**Branch:** the S1 branch. You start from S1-A's pushed, green head. Pull first. You are the last
brief on the branch, so you also finish the pull request.
**Read first:** `CLAUDE.md`, the mobile rules included; `docs/handoff/builders/README.md`; the
plan sections 3, 4 (rule R7), 5.4 and 10, and the P3B r8 rows of Appendix A;
`docs/handoff/status/S1.md` as S1-A left it; `mobile/lib/main.dart`, `mobile/lib/app/app.dart`,
`mobile/lib/app/router.dart`, `mobile/test/support/harness.dart`.

## 1. Your job

Make the member's screens end with the member's session: rule S-4. S1-A built the session core.
You put the app's provider container and screen tree inside a boundary that is thrown away when
a session ends, and you bind what outlives a screen to its sign-in.

## 2. What you build

Paths are under `mobile/`.

**The boundary** (`lib/main.dart`, `lib/app/app.dart`).

- A `MemberBoundary` widget above the app owns the provider container. On `end` it disposes the
  old container and builds a new container and a new app subtree under a new key.
- The core, the push messaging handle and the device settings (language, theme) are created
  outside and passed in. Language and theme are identical on the frame before and after.
- The old container is disposed without the signed-out state being published into it.
- **[Guess]** Replacing the container at the app root works with `go_router`, the push
  coordinator and the plugins in use. It was reasoned from the code, not prototyped. If it cannot
  be made to work, stop and tell the lead. A per-screen substitute is not acceptable.

**No widget state is shared between the two trees** (`lib/app/router.dart`). The top-level
`_rootNavigatorKey` moves inside the router provider.

**The API client is built for one sign-in.** Its provider lives in the member's container and
depends on the sign-in. It attaches a bearer only by asking the core for the access token of its
`sid`, and the core answers only while that sign-in is current. It is closed when the container
is disposed. An old client object gets a typed "session ended" error.

**Every call into the core names its sign-in:** `end(sid, ...)`, the token replacement, the
snapshot update. A completion that belongs to A, arriving after B signed in, changes nothing.

**Sockets belong to the member's container** (`lib/core/live/live_updates.dart`,
`lib/core/push/notification_socket.dart`). They take their token through the client of their
sign-in, close on dispose, and cannot reconnect after the end.

**Events from outside the tree** (a push that is opened, a link, a native result) are delivered
to the current tree as a destination to show, never as authority. A native result that returns
into disposed code is dropped.

**A guest who signs in keeps the tree**, so "sign in to continue" still works. Only the flow that
asked for the sign-in continues, through the router's return location. Other work that kept a
client from before the sign-in fails with "session ended".

**The sign-in controls** (`lib/features/auth/`). All of them read the core's one busy state. The
four separate busy flags go. The typed error for "tokens issued, could not be saved" is shown,
translated.

**The test harness** (`test/support/harness.dart`, `pumpApp`) builds the app through the
boundary, so every existing test runs inside it.

## 3. What you remove

`_leavePrivateScreens` in the router. The four separate sign-in busy flags. Any per-call check
of "who is signed in now" that the client-per-sign-in makes unnecessary.

## 4. What is not yours

The record, the transitions and the sender (S1-A). The photo section (P3B runs your cases again
with it on screen). Clearing shown notifications: not built (plan section 5.7).

## 5. Tests

Red first, on the rejected P3B branch: round-8 blockers 1 and 3 (plan Appendix A). Green here,
through the real screens.

- Pointer down on a member's button, `end`, pointer up: nothing runs.
- A dialog, a sheet and a draft in a text field at `end`, then another member signs in: none of
  them is there.
- A's delayed account-deletion or sign-out completion after B signed in changes nothing.
- The KYC and cheque files, the name and language retry, and the public-profile consent across
  an end: nothing of A is sent as B.
- An open socket at `end` closes and does not reconnect.
- A native result after the reset is dropped.
- An old client object and an old `ref` after `end` get "session ended".
- "Sign in to continue" resumes only the flow that asked.
- Language and theme are identical on the frame before and after the reset.

Mechanical checks: no top-level `GlobalKey` in `mobile/lib`; no mutating call into the core
without a `sid`.

## 6. Done when

1. The two findings are tests, red before and green after, and every case of section 5 passes.
2. Every new string exists in English, French and Arabic. Screenshots in English and Arabic at
   360 px for each changed screen state.
3. The phase document lists the device check for the phone test: sign out, close the app, open
   it; sign in as a second member; the first member's screens and pushes are gone.
4. The pull request description lists, per rule S-1 to S-6: the rule, where its one mechanism
   lives, its tests, and the evidence table of both briefs.
5. The whole mobile suite and the Android build are green in CI.
