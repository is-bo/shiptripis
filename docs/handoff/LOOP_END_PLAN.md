# Plan to end the Astra review loop (P3B, G1, F1, N1)

**Status:** revision 2, 27 November 2026. A proposal. Nothing here is built yet.
**History:** revision 1 was commit `b295f3a`. Astra reviewed it and answered "revise". Section 14 lists
each change Astra required and where this revision makes it.
**Next:** Astra re-checks only the revisions (`docs/handoff/astra/loop-end-plan-recheck.md`). Ismail
decides the questions in section 2. Builders start only after both. Their briefs are in
`docs/handoff/builders/`.

Guesses are marked **[Guess]**. Everything else was checked against the code at the pull-request
heads listed in section 1, or against Astra's reports.

---

## 0. Summary for Ismail

The four packages keep failing review for one reason: nobody fixed what "done" means. Astra can
always find one more rare sequence. Each fix added new code, and new code gave Astra new things to
find. Packages that began as small tasks are now between 4,000 and 15,000 lines.

This plan does five things.

1. **It fixes the rules of the review** (section 3): which failures a finding may assume, what
   counts as a blocker, what belongs to a package, and when the rounds stop.
2. **It replaces case-by-case fixes with a few mechanisms per package** (sections 5 to 9). All
   findings fall into 26 families. 12 are closed. The 14 open ones get one invariant, one mechanism
   and one test matrix each.
3. **It builds the "two accounts on one phone" protection once**, in a small package (S1), instead
   of twice inside P3B and N1.
4. **It caps the rounds**: after this plan is settled, each package gets one full code review and
   one re-check.
5. **It splits the building into eleven briefs** for Opus builders, so that no builder has to hold
   a whole package in its head (section 10).

**What changed after Astra's review of revision 1**

- The money rule for a payment that is "being checked" is stricter. Staff can release an order
  only on proof from the provider, or by recording what happened to the money.
- Signing out on the phone must survive the app being killed. The server side of sign-in (in N1)
  now lands before the phone side (S1).
- Two repair actions that Finance needs for Stripe payout accounts do not exist in the code today.
  They become a small package (F1b), required before payouts are switched on.
- A question about what push notifications may say on a shared phone needs your decision.

What you need to decide is in section 2: nine short questions.

---

## 1. Why the reviews do not converge

| Package | Original task | Rounds | Size now | Latest result |
|---|---|---|---|---|
| P3B #66 | Profile photos in the app | 8 | +14,865 lines, 138 files | Reject at `7727b19`: 3 blockers, 4 should-fix |
| G1 #67 | Guest payment page works without the browser-session check | 7 | +7,285 lines, 67 files | Reject at `57684cb`: 3 blockers, 3 should-fix |
| F1 #69 | Show payout availability and actions. "No new rail or switch" | 5 | +4,189 lines, 37 files | Reject at `bd74c3a`: 1 blocker, 3 should-fix |
| N1 #71 | Ask for notification permission once, at first open. Mobile only | 5 | +6,068 lines, 83 files | Reject at `3e7fc17`: 3 blockers, 1 should-fix |

Six causes, each with evidence.

1. **No agreed fault model and no severity bar.** Every reachable sequence became a blocker,
   because nothing written said otherwise.
2. **Each fix added a mechanism, and each mechanism is new surface.** F1 round 5 added a session
   lock (`hold_payout_account_setup`); the round-5 findings are about that lock. On P3B,
   `session.dart` grew from 616 to 895 lines and carries two generation counters, a credential owner
   and an ad hoc ordering counter.
3. **Correctness leaned on things that are not durable or not atomic.** A session-level advisory
   lock that ends with its connection (F1). Three storage keys written one after the other on the
   phone. A job armed only at the moment a state is entered (G1). Completion writes that do not
   check the worker still owns the job (`jobs.run_job`).
4. **One rule, two implementations.** G1's gate `_checkout_step` and its screen mirror
   `next_checkout` restate the same conditions separately. In every round from 3 to 7 Astra found a
   screen offering what the gate refuses.
5. **Ambient authority on the phone.** "Who is signed in" is read when a request is sent, not when
   the member acted. P3B rounds 3 to 8 and N1 rounds 4 and 5 are this one family.
6. **Tests are organised by round, not by rule.** P3B has `p3b_photo_round2_test.dart` to
   `round8_test.dart`. Nobody can see which interleavings a rule's tests cover.

---

## 2. Decisions for Ismail

Each has a recommendation. Building does not start before these are answered.

| # | Question | Recommendation |
|---|---|---|
| D1 | Adopt the review contract in section 3: the fault model, the severity table and the written list of accepted risks? | Yes |
| D2 | Adopt the stop rule in section 3.4? At the cap you choose: cut the feature, re-plan it, or merge it switched off. Switched off is allowed only when the switch makes the reported problem impossible to reach. | Yes |
| D3 | Add the package **S1 (session core)**, built after N1 and before P3B? It replaces the follow-up "wrong-account writes outside profile photos" in HANDOFF 0.8. | Yes |
| D4 | G1 money rule. (a) While a payment on an order is "being checked", the order takes no new payment. (b) Staff can release the order only when the provider confirms that no money was taken, or by recording, with the provider's reference, that the money was returned. An unclear answer keeps the hold. (c) If a payment shows up after staff closed the item, the order is held again and Finance must deal with it. It is never credited by itself. | Yes to all three |
| D5 | F1: while a Stripe account is being created for a traveler, the app refuses to change the payout country or switch euros off, with "setup in progress". Changes that do not touch the euro account stay possible. | Yes |
| D6 | Accept the scope cuts in section 3.3 and the follow-ups in section 10.5? | Yes |
| D7 | Builders: eleven briefs, all Claude Opus, at the effort section 10.2 gives each (extra high for money, sessions and staff authority; high for the rest)? | Yes |
| D8 | Push text on a shared phone. Today a push says things like "Your KYC was approved", and the phone's system shows it. N1 will stop the server sending after sign-out, and the app will clear shown notifications at sign-out. A push already handed to Google or Apple can still appear afterwards. Should push text become safe for anyone holding the phone (no names, amounts, message text or status), with details loaded after opening? | Yes, as its own small package before launch, not inside N1 |
| D9 | Payouts on (O4): besides F1, wait for **F1b**, the two Finance repair actions (settle a stuck Stripe account creation; retire a Stripe account opened for the wrong country)? Without them those two situations have no way out. They have none on `main` today either. | Yes |

---

## 3. The review contract

This section is the same for every package. Every Astra prompt carries it, next to the three
anti-loop rules of `docs/handoff/COORDINATOR.md` section 3, which stay in force unchanged.

### 3.1 Fault model: what a finding may assume

**Ordinary participants. These are not faults; any number may combine.**
A second tap. A retry. Two devices. A phone handed to the next member. The app sent to the
background or closed by the person or the system. A staff member doing an allowed action. A webhook
delivered again. A job run again. A worker that was presumed dead and resumes. A request that starts
after a deploy or a configuration change, including one that meets an unresolved intent from before
the change.

**Faults. A finding may assume one. Each line is one fault.**

- a. One crash at any point: a web worker, a job worker, a database connection, or the app process.
- b. One lost, delayed, duplicated or reordered message, together with the retries it causes.
- c. One provider outage or ambiguous answer (Stripe, Chargily, FCM, Google, Apple), however many
  calls it affects.
- d. One storage failure on the phone: a write or a read that fails or whose outcome is unknown.

**Recovery.** A claim that something recovers assumes the app or worker runs again and the
dependency eventually answers. "The server always hears" means: once the network returns.

**Bounds.**

- A paused worker resumes inside the provider's idempotency retention (about 24 hours for Stripe).
  A pause between a pre-send check and its send that outlasts the retention is outside the model.
- A configuration change racing a request that is already in flight is outside the model.
- A signing-key change, and stored data damaged beyond reading, are outside the model, except where
  a section says what happens ("permanent loss" in S-3).
- A malicious staff member, or a compromised server, database or provider, is outside the model.
- Data, URLs, events, jobs or app versions from before the package are outside (anti-loop rule 1).

### 3.2 Severity

**Order of the questions. The first that applies decides.**

1. Does it need data or a client from before the package? **Not applicable.**
2. Is it the same on `main` without the package, in code the package neither changes nor depends
   on? **Out of scope**: a follow-up in HANDOFF 0.8, and its own fix package at once if it is
   blocker class. But a failure that the package, or a mechanism of this plan, introduces or
   changes is **in scope even when no family names it**. It is then a plan gap or a build gap.
3. Is a breach of M, A or C shown, by any sequence inside the model, including one fault with its
   consequences? **Blocker.**
4. Is someone or something stuck, with no path in the app and no named staff action that a staff
   member can execute and see succeed? **Blocker (L).**
5. Is there a visible wrong result through ordinary use or one fault? **Should-fix.**
6. Otherwise, if it is named, evidenced, bounded and repairable: **Accepted risk**, written in
   section 11 with its bound and its repair path.
7. An observation inside the model with no wrong result is **not a finding**.

**The blocker classes.**

| Class | Definition |
|---|---|
| **M** money | Two payers for the same obligation, or one payer debited twice. A refund does not erase a second debit. A debit on an obligation already closed to collection. A debit lost to Finance: neither credited, refunded nor durably in front of staff. A credit or payout that should not happen. A funded payout instruction that no valid committed preference supports. An external payout destination created or bound under a superseded declaration when it takes the member's only usable slot. (A delayed provider read is Should-fix when the money is already durably in front of Finance and recovery is shown.) |
| **A** authority and privacy | Anyone reads or changes what belongs to another account. Private data shown to an audience or used for a purpose it was not given for, such as a private document becoming a public photo. A usable bearer capability disclosed, a log included. A hidden location, delivery code or tracking number leaking. |
| **C** credentials | After the server ended a sign-in: a refresh, a new push registration, a new socket or the delivery of a queued push still succeeds. Bounded exception: an access token already issued works until its own expiry plus the 30 seconds of leeway, and an open socket closes by then. On the phone: signing out removes the phone's authority at once; the server end can be outstanding while offline, must survive a restart, and must complete once the network returns. |
| **L** lock-out | A member, an order or a setup stuck with no path in the app and no named, executable staff action with a visible result. A supported phone that cannot start the app. |

The verdict rule does not change: reject only for an in-scope Blocker or Should-fix.

### 3.3 Scope

A package's scope is its families (sections 5 to 9), plus anything rule 2 of section 3.2 pulls in.

Scope cuts this plan makes:

- **P3B** no longer owns account switching on a shared phone. That is S1. P3B is profile photos.
- **N1** no longer owns how the phone leaves a sign-in. That is S1. N1 is the permission prompt, the
  server's sign-in sessions, and "a push belongs to one live sign-in".
- **G1** keeps the payment-attempt lifecycle it grew into, because the code is on its branch and
  entangled. Its scope is stated as six families (section 6).
- **F1** keeps onboarding creation, because the read model cannot be correct without it.
- **P3B round-3 item 13** (the native "prepare the same input twice" check and an iOS build in
  pull-request CI) becomes a device check with an owner and a recorded result, plus a follow-up for
  the CI cost.

### 3.4 Stop rule

**The plan.** Astra reviewed revision 1. This is the one revision. Astra re-checks only what
changed. There is no third pass: an open disagreement goes to Ismail as a decision.

**Each package.** Round 1 is a full review against this plan. Round 2 re-checks only the round-1
fixes and the callers they affect. A round 3 needs Ismail's explicit OK.

**Each finding** is verified against the code by the lead, then classified:

| Class | Meaning | Who acts |
|---|---|---|
| Build gap | The code does not do what the plan says. | The builder fixes it. The plan does not change. |
| Plan gap | The code does what the plan says and an invariant still breaks, or a planned mechanism introduced the failure. | The planner revises that family once. The mechanism changes; no case is patched. Then the builder applies it. |
| Outside | Rule 2 of section 3.2. | Follow-up, or its own fix package if blocker class. |

**Work on a package stops, and Ismail chooses, when any of these happens:**

- a second plan gap in the same family, after its one revision;
- round 2 still has an in-scope Blocker or Should-fix;
- a fix would need a mechanism this plan does not name (a new lock, counter, flag, column, job kind
  or retry loop). The builder stops and asks the planner instead of adding it.

**Ismail's options at a stop:** (a) cut the capability from the package; (b) re-plan the family;
(c) merge with the capability switched off on the server. Option (c) is allowed only when the switch
makes the reported sequence unreachable, shared writes and background jobs included. It never
applies to S1, to the shared job runner, or to a change in how user rows are saved, because no
switch turns those off.

**Budget.** The plan: 2 Astra runs. G1, F1, N1, S1, P3B: at most 2 each. F1b: at most 2. Fourteen
in total. The four packages have used 25 so far.

**What the cap accepts.** Two rounds will not find everything. What they miss is found by the
phone test and by later packages, while the app still has no users.

### 3.5 Rules for builders that keep packages from growing

1. **Mechanism budget.** A builder adds no lock, counter, generation, flag, column, job kind or
   retry loop that this plan does not name. If one seems needed, the builder stops and asks.
2. **Remove what is replaced, in the same pull request.** Each section lists what goes. Removing an
   old mechanism must keep the earlier fixes that depended on it: the closed families' regression
   tests stay green.
3. **Tests by family.** One matrix per family, named after its invariant. Round-named test files
   are regrouped. A test of a deleted mechanism is rewritten to the new rule and listed in the pull
   request with the reason. No assertion is loosened.
4. **Red first.** Each latest-round finding of an open family is first reproduced as a failing
   test. For a finding moved to another package, the red test runs on the rejected branch where the
   behaviour exists; the green test goes through the integrated public entry point. A failing test
   must tell the bad outcome apart from a correct serial execution.
5. **One writer, checked mechanically.** Each mechanism has a check that there is one writer: a
   database constraint, or a test that scans the source for a forbidden pattern.
6. **The phase document describes the final design**: families, invariants, where each mechanism
   lives, the matrix, and an evidence table: finding, original report, red test and its baseline
   commit, green test, device evidence. About 200 lines. Round history stays in git.

### 3.6 What every code-review prompt contains

The approved plan revision and Ismail's decisions. The merge base, the code head and the heads of
the packages it depends on. The whole package diff. The earlier reports. The inventory of writers
and callers for each mechanism. The state and event matrices with expected outcomes. The red and
green evidence. The tests removed or rewritten, and why. CI results for that exact head, and device
evidence where a matrix asks for it. Astra's pre-registered criteria (Appendix B).

---

## 4. Design rules shared by every package

| # | Rule | Replaces |
|---|---|---|
| R1 | Across a provider call, the only lock is a durable row. Nothing is correct because a connection stayed open, a process stayed alive or a timer has not fired. No transaction is open during a provider call. | F1's session advisory lock |
| R2 | An intent is committed before its effect, in the same transaction as whatever must follow it (the job, the freeze). | G1's close intent and job wake in two transactions |
| R3 | An obligation is a predicate on rows, enforced by a sweep on every job cycle. Arming a job when a state changes only makes it faster. | G1's "arm only on the way in" |
| R4 | A job run owns its claim. A completion is written only if the claim is still its own. Handlers are idempotent and re-read state under the domain lock, whoever owns the claim. | `run_job`'s unconditional updates |
| R5 | Automatic paths obey decisions that staff recorded, read under the row lock. A staff decision about money needs evidence, and is committed with its audit row. | G1's late success after a staff resolution |
| R6 | One decision function per rule. The write path calls it under the lock. The read path calls the same function on the same kind of facts. For the same facts and the same time the two agree. | G1's `_checkout_step` and `next_checkout` |
| R7 | Authority is bound when an action starts. It is never read from "who is signed in now" when the request is sent. Every call back into a long-lived object names the session it belongs to. | P3B's per-call scope checks |
| R8 | A state that must never exist is made impossible to store (a constraint, one record, one writer), not avoided by care. | Three credential keys; "final" without a terminal status |
| R9 | On the phone, per session and per resource, an older read never replaces a newer truth, on screen or in storage. After any change the phone reads again. | P3B's `_photoApplied`; G1's screens |
| R10 | Work that leaves the process (a queued push, a socket, a native callback) carries the sign-in it was allowed for and is checked again where it lands. | N1's queued push and open socket |

**`ReadOrder`, the one helper for R9.** A small class in `mobile/lib/core/read_order.dart`, one
instance per member session and per resource (the account snapshot; the photo slot; an order's
checkout state).

- `begin()` gives a read its ticket. `accept(ticket)` is true only for a ticket newer than the last
  accepted one and newer than the barrier.
- `changed()` is called when a mutation completes, whatever it answered (success, refusal,
  conflict, or an error with an unknown outcome). It sets the barrier to the newest ticket issued
  and asks for a fresh read. Reads that started before it are dropped.
- A mutation's own answer is shown at once only if no read has been accepted since the mutation
  started. Either way the fresh read that follows is what stays.
- Mutations of one resource run one at a time.
- What is persisted follows the same order as what is shown.

Whichever of G1 and S1 merges first creates the file with its tests; the other rebases onto it.

---

## 5. S1: session core (phone)

**Two briefs: S1-A (record and core) then S1-B (boundary and screens). One pull request. Lands
after N1 and before P3B.**

### 5.1 Why it exists

Two families, in two packages, have one root.

- P3B "an action started as member A runs as member B": fourteen of the twenty blockers of rounds
  3 to 8, by the planner's count.
- N1 "the phone leaves a sign-in that the server still holds": round 3 (offline sign-out);
  round 4 blocker 2; round 5 blockers 2 and 3.

The root: the phone's session is several pieces changed at different moments, removed in several
places, and its authority is read at send time.

Checked on `main`:

- Credentials are three keys written one after the other (`token_store.dart`).
- Two generation counters decide what is current.
- Credentials are removed in four places: `auth_repository.signOut`, the interceptor's
  `_endSession`, `SessionController._confirm`, and `accountDeleted`.
- `_confirm` removes credentials on any error that is not "retryable", and a 429 is not.
- There is one root `ProviderScope` for the whole app life, and one top-level `GlobalKey`
  (`_rootNavigatorKey` in `router.dart`).
- The Android activity is `singleTop` with an empty task affinity, so a second task can start a
  second Flutter engine on the same storage. P3B changed it to `singleTask` for this reason.
- The token refresh is already one request at a time and compares the refresh token it sent
  (`api_client.dart`, `_refreshOnce`).

### 5.2 What S1 needs from the server (delivered by N1, section 8)

- Every token carries the id of its sign-in (`sid`).
- `POST /api/auth/sign-out` with a refresh token in the body, and no bearer needed:
  - **205**: the sign-in that the token names has ended, now or earlier, and every push device it
    registered is off. This holds for an expired or rotated token, and for an account that no
    longer exists. A repeat answers the same and writes nothing.
  - **400 with code `sign_out_proof_invalid`**: the server cannot verify the token as one of its
    own. This can come only from a signing-key change or damaged storage.
  - Anything else is not an answer about the sign-in.

### 5.3 Invariants and mechanisms

**S-1. One record, one writer, durable when acknowledged.**

- Everything that says who is signed in on this phone is one stored document under one key: the
  current sign-in (its `sid`, account snapshot, access token and refresh token) or none, plus the
  list of ended sign-ins whose end the server has not confirmed.
- Every transition is one write of that one key. An interrupted write leaves the state before or
  the state after, never a mix.
- **A transition is acknowledged only when it is on disk.** On iOS the keychain write is
  synchronous. On Android the storage plugin writes with `apply()`, which returns before the disk
  write. So on Android each record write is followed by a flush: a small native method calls
  `commit()` on the same preferences file, which by the platform's documented behaviour waits for
  the outstanding write. Only then does the core change its in-memory copy, publish anything or
  tell the caller it succeeded. **[Guess]** that this barrier works with the plugin's file; the
  builder proves it with the kill test of 5.6. If it cannot be proven, the fallback is a native
  store that encrypts with the Android Keystore and writes with `commit()`, as P3B's pick marker
  store does without encryption. There is no third option.
- **Only the platform's confirmation counts.** On Android that is the flush returning true; on iOS
  the keychain call returning success. Without it (false, an error, or no answer) the transition
  did not happen: the core keeps its previous state, writes the previous record again so that the
  stored copy cannot later reach the disk with a state nobody acknowledged, and tells the caller.
  On Android a read-back proves nothing, because it is served from memory. On iOS a read goes to
  the keychain, so an unknown answer is settled by reading the record back.
- **One writer per phone.** One Flutter engine: the activity becomes `singleTask` (the change P3B
  made moves here). Only the UI isolate touches the record; the push background handler does not.
  One object, `SessionCore`, created in `main()`, holds the only in-memory copy and runs every
  write through one queue.
- Device-level values (language, push prompt count, push sequence, installation id) are separate
  keys. They say nothing about who is signed in.

**S-2. One transition at a time, and every answer names its sign-in.**

- A sign-in attempt is reserved synchronously, before any await. It can be reserved only when the
  state is signed out, the reset of S-4 is complete and no attempt is open. All sign-in controls
  share one busy state from the core.
- An attempt can be cancelled while it waits on the network. If its answer arrives later with
  tokens, that new sign-in goes to the ended list, so the server ends it. It never becomes the
  current sign-in.
- If tokens were issued but the record write fails, the core tries to add that sign-in to the ended
  list, and also posts its end at once from memory. The screen gets a typed, translated error.
- **There is no transition from member A to member B.** B can only start from signed out.
- A refresh is one request at a time per sign-in. Its answer, success or refusal, applies only if
  the current sign-in still holds the refresh token that request sent. A refusal for a token that
  is no longer current is ignored. A late success is never treated as a new sign-in to end: it is a
  rotation of a sign-in the phone already knows by its `sid`.
- Everything is keyed by `sid`, not by account. The same member signing out and in again is two
  sign-ins.

**S-3. One exit, always for a named sign-in.**

- Credentials leave the current slot only through `end(sid, reason)`, and only if `sid` is still
  the current sign-in. Reasons: the member signed out; the server refused the refresh token that is
  current; the account was deleted.
- No other answer ends a session. A 429, 403, 404, 5xx, timeout or offline answer, on `/api/me` or
  anywhere else, keeps the member signed in and is retried later. A 429 at launch waits for its
  `Retry-After`.
- `end` is one acknowledged write: current becomes none, and the sign-in moves to the ended list
  with its refresh token. Then the in-memory copy, then the teardown of S-4, then the sender of S-5.
- If that write fails on a member's sign-out, the member stays signed in and is told so. If it
  fails for a session the server already refused, the phone ends in memory, keeps retrying the
  write, and checks again at next launch (accepted risk AR-3).
- **The record cannot be read at launch.** The app shows the start screen, offers no private
  screens and no sign-in, and tries again. It never writes over a record it has not read, because
  that record may hold the only proof of the current sign-in and of every pending end. If reading
  keeps failing, the start screen offers "sign in again on this phone". Choosing it is handled as
  permanent loss, so a store that never recovers locks nobody out.
- **Permanent loss.** Only when the platform reports the stored data as undecryptable, or the text
  does not parse, the record is replaced by an empty one. The proofs are gone, so the phone also
  deletes its push token and retries until that succeeds. No sign-in whose proof was lost can then
  deliver a push to this phone. **[Guess]** which platform errors mean "undecryptable"; the builder
  lists them.

**S-4. The member's screens end with the member's session.**

- A `MemberBoundary` widget above the app owns the provider container. On `end` it disposes the old
  container and builds a new container and a new app subtree under a new key. The core, the push
  messaging handle and the device settings (language, theme) are created outside and passed in.
- The old container is disposed without the signed-out state being published into it.
- No top-level `GlobalKey` remains. `_rootNavigatorKey` moves inside the router provider.
- The core refuses to reserve a sign-in until the boundary reports the first frame of the new tree.
- **The API client is built for one sign-in.** It can attach a bearer only by asking the core for
  the access token of its `sid`, and the core answers only while that sign-in is current. It is
  closed when its container is disposed. An old client object gets a typed "session ended" error.
- **Every call into the core names its sign-in**: `end(sid, ...)`, the token replacement, the
  snapshot update. A completion that belongs to A, arriving after B signed in, changes nothing.
- **Sockets belong to the member's container.** They take their token through the client of their
  sign-in, close on dispose, and cannot reconnect after the end.
- **Events from outside the tree** (a push that is opened, a link, a native result) are delivered
  to the current tree as a destination to show, never as authority. A native picker result that
  returns into disposed code is dropped.
- **A guest who signs in keeps the tree**, so "sign in to continue" still works. Only the flow that
  asked for the sign-in continues, through the router's return location. Any other work that kept a
  client from before the sign-in fails with "session ended", because the client provider depends on
  the sign-in.
- At `end` the app removes its delivered notifications from the phone's tray (one native call per
  platform).

**S-5. The server hears about every ended sign-in.**

- A sender inside the core posts each entry of the ended list to `POST /api/auth/sign-out` with
  that entry's own refresh token and no other credential: at once, at launch, when the network
  returns, with capped backoff.
- An entry is removed only on **205**, or on **`sign_out_proof_invalid`**. Every other answer,
  including a 401, 403, 404, 408, 429 or 5xx, keeps it.
- Entries are keyed by `sid`. A second end of the same sign-in replaces its entry. No entry is ever
  evicted, and there is no cap.
- An acknowledgment for A's entry removes only A's entry, whatever happened since.

**S-6. Newer truth wins, on screen and in storage.** The account snapshot uses `ReadOrder`, scoped
to the sign-in. The snapshot that is persisted in the record follows the same order.

### 5.4 What S1 removes

The three credential keys and the identity generation in `TokenStore`; `_generation` in
`SessionController`; the `expectedIdentityGeneration` path of `auth_repository.signOut`; the
interceptor's `_endSession`; the clear inside `_confirm`; `_leavePrivateScreens` in the router; the
four separate sign-in busy flags; N1's `_endSignInOnServer` and its own sign-out bookkeeping.

### 5.5 Test matrix

| Invariant | Rows |
|---|---|
| S-1 | The write throws, at each transition: state before, in memory and after a restart. The flush answers false, throws or never answers: the transition did not happen, the previous record is written back, and a restart shows the previous state. On iOS an unknown answer is settled by a read-back. A kill immediately after an acknowledged sign-in, token replacement and sign-out: the new state is there after restart. Two task launches: one engine. A server acknowledgment and a snapshot write queued together: neither is lost. |
| S-2 | Password and Google tapped in one frame. A second attempt while the first waits. An attempt cancelled, then its answer arrives with tokens. Tokens issued, then the record write fails. Two refresh triggers: one request. A refresh refusal that arrives after another refresh rotated the token: ignored. A refresh success that arrives after `end`: nothing is ended twice and nothing revived. The same account signs out and in again: the first sign-in's late answers touch nothing. A lost rotation answer. |
| S-3 | For each of: 401 after a refused refresh; 401 with a network error on refresh; 403; 404; 429 with `Retry-After`; 500; timeout; offline. On `/api/me` at launch, and on an ordinary request. The record unreadable at launch, then readable. The record unreadable every time: the member chooses to sign in again. The record undecryptable. A failed `end` write, then a restart. A sign-in that fails after a session ended (the earlier snapshot is not shown again). |
| S-4 | Pointer down on a member's button, `end`, pointer up. A dialog, a sheet, a draft in a text field at `end`, then another member signs in. A's delayed account-deletion or sign-out completion after B signed in. The KYC and cheque files, the name and language retry, and the public-profile consent across an end. An open socket at `end`. A native result after the reset. An old client object and an old `ref` after `end`. "Sign in to continue" resumes only the flow that asked. Language and theme identical on the frame before and after the reset. Delivered notifications are gone after `end`. |
| S-5 | An expired proof, a rotated proof, a deleted account: 205 removes the entry. A 401, 403, 404, 429 and 500: the entry stays. A lost 205, then the repeat. Nine sign-outs while the endpoint fails: nine entries, all sent later. The app killed before the send. A late acknowledgment for A while B signs in. No request carries another sign-in's credentials. |
| S-6 | Two reads answered in reverse order. A change answered after a newer read was accepted. A failed change. The same after a restart. The same across a session end. |

Mechanical checks: one place writes the record key; one function empties the current slot; no
top-level `GlobalKey` in `mobile/lib`; no read of an access token outside the core; no mutating
call into the core without a `sid`.

### 5.6 Done when

1. Every row of 5.5 passes.
2. P3B round-8 blockers 1 to 3 and N1 round-5 blockers 2 and 3 have red tests on their rejected
   branches and green tests here, through the real screens where a screen is involved. The photo
   screen itself is exercised again in P3B.
3. The kill test passes on an Android device or emulator, and the result is recorded.
4. Every new string exists in English, French and Arabic. Screenshots in English and Arabic at
   360 px for each changed screen state.
5. The whole mobile suite and the Android build are green in CI.

### 5.7 Risks

- **[Guess]** Replacing the provider container at the app root works with `go_router`, the push
  coordinator and the plugins in use. Reasoned from the code, not prototyped. If it cannot be made
  to work, the builder stops and comes back to the planner. A per-screen substitute is not
  acceptable.
- **[Guess]** S1 is about 1,500 to 2,500 lines with tests.
- The device kill test needs a test build, which needs Ismail's OK at that time.

---

## 6. G1: guest checkout and the payment-attempt lifecycle

**Three briefs on one branch, in order: G1-A (state and money), G1-B (jobs), G1-C (gate and
screens). Continue on `claude/g1-guest-checkout-csrf`, after merging `main` in.**

### 6.1 Families

| Family | Where it appeared | State |
|---|---|---|
| G-A The guest page as a capability: no browser session, no Referer or token in logs, throttle, receipt address | Re-check, round 3 | Closed |
| G-B A provider event reaches an attempt only through ids that attempt stored | Round 5 blocker 1, round 6 blocker 1 | Closed |
| G-C One order has at most one checkout that can collect | Re-check, rounds 3 to 5 | Closed. Astra round 7: "no ordinary path issuing two simultaneously payable URLs" |
| **G-D Every reported payment is accounted for before the order collects again** | Round 6 blocker 2; round 7 blockers 1 and 3, should-fix 1 | **Open** |
| **G-E The obligation to follow a checkout cannot be lost** | Rounds 3 to 6 (job and expiry findings); round 7 blocker 2, should-fix 2 | **Open** |
| **G-F Screens offer exactly what the gate allows** | Rounds 3 to 6 (should-fix in each); round 7 should-fix 3 | **Open** |

Lead rules A, B and C from the earlier rounds stay in force.

### 6.2 What the code does today (checked at `57684cb`)

- An attempt's fate is spread over `status`, `checkout_final_at`, `close_requested_at`,
  `failure_code`, `operational_resolution`, `expires_at`, `opening_until` and its job row.
- `LIVE_CHECKOUT` means stored, not final, not succeeded. `UNVERIFIED_PAYMENT` means failed with an
  unverified code and no staff resolution.
- The gate `_checkout_step` checks `LIVE_CHECKOUT` and never `UNVERIFIED_PAYMENT`.
- `next_checkout` restates the gate's conditions for the screens.
- `_record_checkout_final` sets `checkout_final_at` without a terminal status.
- `reconcile_attempt` accepts a success with an empty currency, applies a late success to a failed
  attempt without reading `operational_resolution`, and saves `checkout_final_at` in an earlier
  statement than the status.
- The console's "resolve" view opens a transaction, calls `resolve_payment_attention` and writes
  the audit row. No provider is read. The form offers "resolved", "dismissed" and "superseded".
- The finance queue (`payment_attention_queryset`) shows unresolved attempts that are unverified,
  or unapplied with a refund not yet complete.
- `run_job` writes five outcomes with `filter(pk=job.pk).update(...)`: missing handler, deferred,
  permanent failure, failure, success.
- `arm_live_checkouts` re-arms `LIVE_CHECKOUT` attempts only, up to 100 per cycle.

### 6.3 Invariants and mechanisms

Three facts are kept apart: **can this checkout still collect** (finality), **did the provider
report a payment** (evidence), and **what became of the money** (disposition).

**G-D1. Final means terminal.** `checkout_final_at` is written by one function only,
`reconcile_attempt`, in the same UPDATE statement as the terminal status. `_record_checkout_final`
goes. `close_checkout` returns how the provider says the checkout ended (closed unpaid, failed,
expired, cancelled, or a payment under way), and `settle_checkout` passes that outcome on. A check
constraint makes the bad state impossible to store:
`checkout_final_at IS NULL OR status IN ('succeeded','failed','expired','cancelled')`.

**G-D2. "Verified" has one meaning.** A reported payment is verified only when the provider's
answer states an amount that is a whole number of minor units and equals the expected one, and
states a currency that equals the expected one. A missing amount, a missing currency, a fractional
amount or a mismatch is not verified. **[Guess]** Both providers state a currency in their success
answers; where an event does not, the provider read that follows does, and the hold heals itself.

**G-D3. A held payment.** An attempt is **held** when the provider reported a payment that is not
verified, or that arrived after staff closed the item (code `paid_after_disposition`). This is
today's `UNVERIFIED_PAYMENT` with one more code. Three predicates in `models.py`, and no other
statement of them anywhere:

- `LIVE_CHECKOUT`: can still collect.
- `HELD_PAYMENT`: a reported debit with no disposition.
- `OUTSTANDING = LIVE_CHECKOUT or HELD_PAYMENT`: read by the gate, by `settle_checkout`'s early
  return, by the sweep and by `_already_satisfied_reason`.

The finance queue keeps its own rule: held, or unapplied with a refund not complete. The existing
unapplied-payment and refund path does not change.

**G-D4. The gate refuses while a payment is held.** An order with a `HELD_PAYMENT` attempt opens
and hands out no checkout. The answer is the stable code `payment_under_review` (409), translated:
a payment for this order is being checked, do not pay again. No surface says "nothing was charged"
for a held attempt: not the app, not the guest page, not the payment-failed email (a hold sends
none).

**G-D5. A hold ends only by a disposition.** There are four, and nothing else releases the order.

| Disposition | Who | Condition |
|---|---|---|
| Applied | Automatic | A verified report, on a hold that staff have never closed. Credited exactly once, through the existing path. |
| Unapplied and refunded | Automatic | A verified report that the order cannot absorb. The existing path. |
| `no_debit` | Staff | The staff action reads the provider itself. The typed answer must be: the checkout is final and holds no successful payment. |
| `returned` | Staff | The staff action reads the provider itself. The typed answer must be: the checkout is final and a payment was reported. Staff give the provider's payment reference, which must match the one read when the provider gave one, and the evidence that the money went back. |

- The provider read gives a typed answer: no payment and final; paid and verified; paid and not
  verified; open; processing; unreadable. **Open, processing and unreadable allow no disposition.**
  The hold stays.
- The staff action reads the provider first, outside any transaction. Then one transaction locks
  the attempt, checks it is still held with the same code and reference, writes the disposition
  with actor, reason, provider reference and evidence, and writes the audit row. The console view's
  transaction wraps only that second step.
- The form offers `no_debit` and `returned` for a held payment. "Resolved", "dismissed" and
  "superseded" remain for the other kinds of item only.
- One new column records the provider payment a `returned` disposition accounted for.

**G-D6. Automatic paths obey the disposition.** In `reconcile_attempt`, under the attempt row lock,
for an attempt that staff closed:

- A report of the same payment that a `returned` disposition accounted for changes nothing.
- Any other reported success puts the attempt **back on hold** with code `paid_after_disposition`,
  clears the disposition (the audit log keeps it) and records the event. This is a row, so it
  happens whichever path saw the payment, a webhook or a provider read, and it happens once.
- A hold with that code is never applied automatically. Only `returned` closes it.

The staff action and `reconcile_attempt` take the same row lock, so whichever commits second sees
the other.

**G-E1. The sweep defines the obligation.** On every job cycle, each `OUTSTANDING` attempt has a
settle job that is pending or running. Where it has none, or one that is succeeded, failed or
cancelled, the sweep makes it pending. A job the sweep re-arms after its tries ran out is due after
the capped delay, not at once. The sweep does not pull a pending job forward. It takes unarmed
obligations in id order up to its limit; an armed one leaves the unarmed set, so every obligation is
armed within a known number of cycles. The settle handler reports "done" only when the attempt is no
longer `OUTSTANDING`.

**G-E2. Claim fencing, for every job kind.** `claim_due_jobs` stamps a fresh `claim_id` (a new
UUID column on `ScheduledJob`). One helper writes all five completions. Each filters on `pk`,
`status = running` and that `claim_id`. Zero rows means the run lost its claim: it logs and writes
nothing. Every write that makes a job pending again clears `claim_id`. A handler's effects are safe
on their own, whether or not its completion is later accepted.

**G-E3. Intent and wake in one transaction, and a wake during a run is kept.**
`_record_close_intent` also arms the settle job due now, inside the caller's transaction, taking the
job row lock last as today. No caller arms separately. If the job is running under the same claim,
the wake is recorded on the row as today (`run_at` later than `locked_at`), and no completion of
that run pushes it later (`_next_run_at` stays). The immediate wake comes from the new intent only,
so an outage still backs off.

**G-F1. One gate function over stated facts.** `checkout_gate(facts)` is a pure function. The
facts are: the order (collectable, amount outstanding), its attempts, the caller (the owner, or a
guest link and what it may do), the rail asked for and the rails available, the amount, and the
time. `_checkout_step` builds the facts under the order lock and acts on the answer. The read path
builds the same kind of facts without the lock and maps the answer to a screen state. The conditions
exist once. **For the same facts and the same time the two agree**; a screen cannot predict a later
webhook, and a refusal after an older read is not a disagreement.

- Owner states: ready, resumable (with its rail), settling, guest paying, in progress, under review.
- Guest states: ready, in progress, paid, inactive. "In progress" is one neutral message for every
  case where the guest must wait or must not pay again. It never says who is paying.
- The payout preflight (`payout_snapshots.preflight`) is not part of the gate function. A rail the
  screen offers can still be refused by it. That mismatch is the follow-up "provider list against
  payout preflight", which belongs to C1.

**G-F2. On the phone, a refusal beats an older read.** The owner's checkout section and the guest
pay screen use `ReadOrder` per order.

### 6.4 What G1 removes

`_record_checkout_final`; the gate's "final but open" branch; the conditions restated in
`next_checkout`; the five unconditional completion updates in `run_job`; every separate call that
arms the settle job after a close intent; the "resolved, dismissed, superseded" choices for a held
payment.

### 6.5 Test matrix

The specification is a state table. The builder writes it as data and generates the tests from it.

**Attempt states.** S0 opening (no checkout stored, inside its window). S1 never opened (window
passed). S2 open and payable. S3 closing. S4 settling. S5 ended locally, provider not confirmed.
S6 paid. S7 ended and confirmed. S8 held, never closed by staff. S9 closed by staff as `no_debit`.
S10 closed by staff as `returned`. S11 held again after a disposition.

**Events.** A tap by the member who opened it. A tap by another member or a guest. A webhook:
paid and verified; paid with no amount; paid with no currency; paid with a fractional amount; paid
with a mismatch; failed. The settle job's read, for each typed provider answer. A close confirmed
unpaid; a close refused because a payment is under way; a close that reports a failure. Expiry.
Each staff disposition, on each typed provider answer. Staff reconcile. The order stops collecting.
The order is paid by another attempt.

For every state and event: the next state, the answer, the ledger effect, the finance queue, and
what the owner and guest screens offer. Then:

- **Interleavings**, each in both orders: tap and webhook; tap and job; job and staff disposition;
  webhook and staff disposition; job and job (a stale run finishing after a newer claim); webhook
  and expiry.
- **Late evidence**: a success seen only by a provider read (no webhook) after each disposition; the
  same report twice; the unapplied-refund queue unchanged.
- **Jobs**: 101 obligations and the sweep's limit; tries exhausted with a close outstanding; a wake
  during the same claim; a stale success, deferral, retry, permanent failure and missing handler; a
  crash on either side of the close-intent transaction.
- **Screens**: owner detail, deposit summary, guest page and guest app; a refused tap followed by an
  older read; a failed refresh; a paid order and a cancelled order. Property: for the same facts
  and time, what the screens offer equals what the gate accepts.

Mechanical checks: the check constraint; `checkout_final_at` assigned in one function; no
`ScheduledJob` completion outside the helper; the three predicates stated once; the test gateway
fails if it is called inside a transaction.

### 6.6 Done when

1. Each family in 6.1 has its invariant, one mechanism and its matrix, shown in the pull request.
2. The three round-7 blockers and three should-fix findings are tests, red before and green after.
3. Migrations are generated, `task check-drift` is clean and the regenerated contract is committed.
4. New strings exist in English, French and Arabic, with 360 px screenshots of the "being checked"
   state on the owner and guest screens, and of the staff disposition form.
5. `docs/ADMIN_OPERATIONS.md` says how Finance uses the two dispositions.
6. All CI checks are green.

---

## 7. F1: payout availability

**One brief. Continue on `claude/f1-payout-availability`.**

### 7.1 Families

| Family | Where it appeared | State |
|---|---|---|
| F-A The read and the write give the same answer | Rounds 1 to 4 (about a dozen should-fix) | Closed by the shared `onboarding_refusal` |
| F-B Changing the method set against funding | Round 1 blocker, round 2 | Closed |
| **F-C An account-creation request is sent only for the declaration that is current** | Round 2 blocker; round 3 blockers 1 and 3; round 4 blocker; round 5 blocker | **Open. Five rounds.** |
| F-D An older in-memory copy written over newer account state | Round 3, round 4 (two) | Closed |
| F-E Creation identity: key, attempt, fingerprint | Round 3 blocker 2, round 4 | Closed |
| **F-F Eligibility and waiting** | Round 5 (two should-fix) | **Open** |
| **F-G One answer per response** | Round 3, round 4, round 5 | **Open** |

### 7.2 What the code does today (checked at `bd74c3a`)

- `_plan_onboarding` locks the user row and the method row, checks the declaration has not changed
  (`_require_unchanged`), and commits a durable creation intent before any request to Stripe.
- `set_preference` reaches the same method row lock through `_method`, checks the revision, and
  creates a new version when the euro country changes.
- Binding an account also creates a new version (`_bind_version`): a version with an account, the
  same country, created in the traveler's name.
- Nothing stops `set_preference` once an intent is committed. Round 5 tried to close that with a
  session-level `pg_advisory_lock` held across the Stripe call. It drops if its connection dies.
  The same lock also kept two onboarding calls from overlapping.
- A create is replayed only inside `IDEMPOTENT_REPLAY_SECONDS` (23 hours); after that the call only
  searches.
- `_traveler` reads eligibility without a lock. Email confirmation is checked separately, in the
  views.
- "Requires Finance review" (`stripe_account_unresolved`) has no staff action behind it, and
  nothing ever sets a Stripe payout account inactive. Both are the same on `main`.

### 7.3 Invariants and mechanisms

**F-C1. The freeze.** While a creation for this platform and mode can still produce an account
(`current_creation(method)` with status prepared, committed or unknown), every write that would
change the euro method's `enabled` or its country is refused with the stable code
`payout_setup_in_progress` (409). The check sits in `set_preference`, the one function both entry
points call (the PATCH and the single-currency POST), after `_method` has taken the method row lock
and before any write. A write that changes neither (a no-op, or a change to the DZD side only) is
not refused.

- Intent commit and preference write take the same row lock. One commits first and the other sees
  it.
- After its commit the intent is a row. No connection has to stay alive (R1). The advisory lock and
  its helpers are deleted.

**F-C2. Who may still send.** Immediately before a create is sent, the caller reads the operation
row again. It sends only if the operation is still outstanding, carries the caller's fingerprint,
and is inside the replay window. Otherwise it only looks (retrieve or search), reads the rows again
and answers from what is there now. Inside the provider's retention a second send of the same key
returns the first answer, so a caller that passes the check and is overtaken creates nothing new.
A caller paused beyond the retention between that check and its send is outside the model (3.1).

**F-C3. When the freeze ends.**

- An account is recorded and bound: the freeze ends. A late send of the same key returns that same
  account.
- A definite refusal with no provider object is recorded: the freeze ends. **[Guess]** A second
  send of the same request is refused the same way by Stripe.
- An unknown outcome, or a search that found nothing: the freeze stays. Inside the window the next
  onboarding call resolves it. Past the window it waits for Finance (F1b).

**F-C4. Two onboarding calls may overlap.** Without the advisory lock they do. So:

- `_require_unchanged` accepts the declaration the call planned for, and also its **binding
  successor**: a later version of the same method, with the same country and an account, where
  every version in between is one too. A traveler's own change breaks that chain and is still
  refused as `payout_preference_changed`.
- A conditional update that changes zero rows means another caller got there first. The call reads
  the rows again and answers from them. It never reports "Finance required" or "preference changed"
  from what it saw before.

**F-C5. The read model offers only what can advance.** While the freeze holds inside the window:
the euro options are not changeable (`payout_setup_in_progress`) and "continue setup" is offered.
Past the window with nothing found (`stripe_account_unresolved`): "continue setup" is **not**
offered, because onboarding would refuse it every time; the state shown is "waiting for support".

**F-F. Eligibility is read on the locked row, in full.** One function says whether this account
may write payout setup now: active, not banned, a traveler role, and a confirmed email. It is
evaluated on the user row locked first, before the method row, in `_method`, in `_plan_onboarding`,
and in the last transaction before the hosted link is returned.

- A creation that was already committed when a ban arrives may still be **recorded**, so the
  account at Stripe is never unknown to the database. It is not bound and no link is handed out.
- No lock is held across a provider call, so no wait lasts as long as a provider call. The test
  gateway proves it: it fails when called inside a transaction.

**F-G. One snapshot per response.**

- Each payout GET loads its facts (user, methods, versions, standing account, creation, policy)
  inside one read-only `REPEATABLE READ` transaction, into plain values. Serializers receive those
  values and make no query of their own. `payout_profile_api.py` and `payout_mobile.py` stop
  computing the euro actions separately.
- A write's response is built from facts read inside its own last transaction, under its locks.
- At the link handoff the method's current version must be the version the call planned for, or its
  binding successor. A different version is `payout_preference_changed`, even when the country
  matches again.

### 7.4 What F1 removes

The session advisory lock and its helpers; the test that waits on it (rewritten as a row-lock
test); the second computation of the euro actions; the unlocked eligibility read.

### 7.5 Test matrix

**Durable states.** N0 no intent and no account. N1 intent committed, never sent. N2 intent
committed, request in flight. N3 ambiguous answer, inside the window. N4 past the window and a
search found nothing. N5 definite refusal. N6 standing account bound to the current version. N7
standing account and a changed declaration. N8 standing account from another platform or mode.

**Writers.** PATCH changing the country. PATCH switching euros off. PATCH that changes nothing. A
DZD-only change. The single-currency POST. Onboarding from the same device. Onboarding from a second
device. A refresh or webhook. A ban, a role change, an email unconfirmed by staff.

For every state and writer: the answer code and the rows afterwards. Then:

- **Property**: in every state, each action the GET offers is accepted by its write, or refused
  only with a "changed since you read" code. No action is offered that is refused every time.
- **Real threads**, both orders: preference write and intent commit; two creators; a search and an
  acceptance; a ban, a role change and an email change against the link handoff; a held row.
- **Crash points**: after the intent commit and before the request; after the request and before
  the record; after the record and before the link. Closing the database connection releases
  nothing that matters.
- **A resumed caller**: one that passed its plan, waits past the replay window, then resumes: it
  does not send.
- **Snapshot**: a commit between two of the GET's queries; a serializer that would read lazily
  after the transaction; FR to DE and back to FR while the link is issued.

Mechanical checks: no session-level advisory lock in the payout setup path; no provider call inside
a transaction.

### 7.6 Done when

1. The round-5 blocker and three should-fix findings are tests, red before and green after.
2. The matrix of 7.5 passes, and the advisory lock is gone.
3. The closed families' tests (F-A, F-B, F-D, F-E) still pass with the lock removed.
4. `payout_setup_in_progress` and "waiting for support" are in the contract for F2, which owns the
   screen. **[Guess]**
5. All CI checks are green.

### 7.7 F1b: the two Finance repair actions (new small package, after F1)

Two states have no way out today, on `main` too: a creation that waits for Finance, and an account
opened for a country the traveler no longer wants. F1b adds the two staff actions. Both are console
actions with a required reason, an audit row, and the staff second step. It is required before
payouts are switched on (decision D9). Until then Connect stays off, which makes both states
unreachable.

- **Settle a creation.** Allowed only for a creation past the replay window whose search found
  nothing. Finance looks at Stripe and records one of two findings: no account exists (the
  operation becomes a definite failure, and the next onboarding starts a new attempt), or this
  account exists (its id is recorded, and the next onboarding retrieves it).
- **Retire an account.** Sets the account inactive with a reason. It is refused while a payout to
  that account is in progress. The creation that produced the account is passed over afterwards, so
  the next onboarding creates a new account for the country now declared. Funded payout
  instructions are not changed.

Done when: each action is executed in a test from the stuck state to a working setup, with the
audit row checked; the funded-instruction rows are identical before and after; strings in three
languages where the app shows the new state.

---

## 8. N1: notification permission, sign-in sessions, and who a push belongs to

**One brief. Continue on `claude/n1-notification-first-open`. N1 merges before S1.**

### 8.1 Families

| Family | Where it appeared | State |
|---|---|---|
| N-A When the permission prompt may appear | Rounds 1 to 4 | Closed |
| **N-B A push registration belongs to one live sign-in** | Round 2 (six blockers); round 3 blockers 1 and 4; round 4 (three should-fix); round 5 (one should-fix) | **One item open** |
| N-C The phone's registration state machine | Rounds 2 to 4 | Closed. Round 5 reported nothing here |
| **N-D Ending every sign-in of an account, against writes to the account** | Round 3 blockers 2 and 3; round 4 blocker 1; round 5 blocker 1 | **Open** |
| **N-E Every way the phone leaves a sign-in also ends it on the server** | Round 3 (offline sign-out); round 4 blocker 2; round 5 blockers 2 and 3 | **Open. Moves to S1** |
| **N-F A push that has left the server still belongs to its sign-in** | Round 4 (queued push, open socket); Astra's plan review | **Open. New** |

### 8.2 Invariants and mechanisms

**N-B. The sign-in row decides.**

- `end_session` writes nothing when the sign-in is not live, and answers the same 205.
- A sign-out carries no installation id and no sequence. Ending the sign-in switches off every
  device it registered, and a registration that arrives from an ended sign-in is refused. Checked
  at `3e7fc17`: registration tests liveness under the account lock before it claims a sequence.
- The installation order (`PushInstallationBinding`) keeps ordering the operations of live
  sign-ins (register and unregister), and an exact repeat is recognised by operation, account,
  sign-in and token together.
- The sign-out endpoint answers as section 5.2 says.

**N-D. Credentials and privileges have named writers.** No global change to how the model saves.

- **One credential writer.** One function sets a password and ends every sign-in of the account,
  under the account lock. The reset, the password change and the technical admin's password form
  all go through it.
- **`session_epoch` has one writer**, `end_all_sessions`.
- **Every edit of an existing user row names its fields.** The inventory (`accounts/admin.py`,
  `admin_panel/services.py`, `accounts/social.py`, `accounts/deletion.py`,
  `accounts/serializers.py`, the bootstrap command) is converted to `update_fields`. A scan test
  fails on a save of a loaded user without `update_fields`, and on `password` or `session_epoch`
  named anywhere but in their writers.
- **A form that can submit a sensitive field carries what the staff member saw.** Sensitive fields
  are: staff and superuser flags, groups and permissions, active, banned, role, and the
  verification flags. The technical admin form and the console's staff actions send the values
  shown when the page was opened. Under the account lock, a difference between those and the row
  rejects the edit: "this account changed since you opened it". So an old form cannot give back a
  privilege that someone removed meanwhile, and a second removal of the same privilege reports
  that it was already done.

**N-E. Moved to S1** (S-3 and S-5). N1 leaves its phone exit code as it is; S1 replaces it. The
N1 review does not judge it, because it is no worse than `main` (rule 2 of 3.2). N1 must not make
any exit worse than `main`.

**N-F. A push belongs to the sign-in that registered the device (R10).** Stated precisely, N1
guarantees:

- **Queued.** A queued push carries, for each device, the sign-in that registered it. The worker's
  last check before sending compares user, device, token fingerprint **and that sign-in** with the
  row as it is now. A device rebound to another sign-in, of the same member or another, does not
  receive it. A retry checks again.
- **Sockets.** A socket closes when its token expires (kept from round 4, with its test).
- **Already shown.** Cleared from the tray at sign-out (S-4).
- **Already handed to Google or Apple, not yet shown.** N1 does not cover this. It cannot be
  recalled, and it is the same on `main`. It depends on what the text says, which is decision D8
  and its own package.

### 8.3 Test matrix

- **N-B**: a sign-out repeated after it was acknowledged makes zero writes; a sign-out for a
  sign-in a password reset already ended; a reset before the first registration; A's delayed
  sign-out after B registered on the same installation; A's registration arriving after A's
  sign-out; the same account with two sign-ins on one installation; low, equal and highest
  sequences among live operations; an unregister against a newer register; a lost acknowledgment.
- **Sign-out contract**: an expired proof, a rotated proof, a proof of a deleted account, an
  unverifiable proof.
- **N-D**: the technical admin form opened, a privilege removed elsewhere, then the old form posted
  to change a name; the form read on POST, then a reset, then the save; two removals of one
  privilege; every converted save with a concurrent change of another field; deferred and reloaded
  instances; after each, the new password and `session_epoch` hold, checked with a real sign-in and
  a real refresh.
- **N-F**: a queued send and a queued retry across a rebind to another member and to a new sign-in
  of the same member with the same token; socket expiry.
- **N-A, N-C**: the first-open and denial-recovery tests stay, through the real router.

Mechanical checks: the two scan tests; no installation-order write before the liveness check.

### 8.4 Done when

1. Round-5 blocker 1 and the should-fix are tests, red before and green after. Blockers 2 and 3 are
   handed to S1 with their red tests.
2. The sign-out contract of 5.2 is implemented and tested.
3. All CI checks are green, "Schema drift" included.

---

## 9. P3B: profile photos in the app

**Three briefs: P3B-A (server slot, can start now), then after S1 merges P3B-B (rebase and
removal) and P3B-C (controller and screens). Continue on `claude/p3b-profile-photos-app`.**

### 9.1 Families

| Family | Where it appeared | State |
|---|---|---|
| P-A A picker result belongs to the pick that opened it | Rounds 3 to 6 | Closed |
| P-B Preparing the image on Android and iOS | Rounds 3 to 5 | Closed. Round-3 item 13 becomes a recorded device check |
| P-C The avatar cache | Rounds 3 to 6 | Closed |
| **P-D An action started as member A runs as member B** | Every round from 3 to 8 | **Open. Moves to S1** |
| **P-E A member's write names the state it saw** | Round 7 should-fix; round 8 should-fix 1 | **Open** |
| **P-F One photo operation at a time** | Round 8 should-fix 2 | **Open** |
| **P-G A newer truth wins on the phone** | Round 3 should-fix; round 8 should-fix 3 | **Open** |

### 9.2 Invariants and mechanisms

**P-D. Moved to S1.** Round-8 blocker 1 is S-4. Blocker 2 is S-1 and S-2. Blocker 3 is S-4. The
keystore error the password screen does not show is S-2. P3B runs S1's matrix again with the photo
section on screen.

**P-E. The slot has a revision that outlives the photo.** Checked at `7727b19`: the photo is one
row per member, a member's removal deletes the row, the empty slot is "no row", and a staff removal
keeps `version`. So an empty slot looks the same before and after an upload and a removal.

- The slot gets a `revision`: an opaque token, shown only to the owner, that changes on every
  transition: upload, the member's own removal, staff removal, dismissal of a notice.
- Once a row exists, a member's action never deletes it. Removal and dismissal leave the row in a
  new `empty` state with a new revision. Before the first upload there is no row, and the revision
  is one fixed value that means "never had a photo".
- **Every member write carries the revision it saw**: the first upload, a replacement, a retry, a
  removal, a dismissal. A write without one is refused. The server compares under the member lock
  (`_hold_member`), before the stored object is published. A mismatch is the existing 409
  `profile_photo_changed`, and the object uploaded for that request is released.
- `version` keeps its one job: the identity of the image, for caches.
- The revision never appears in a public payload. A privacy test checks it.
- The 409 does not change its body. The phone reads again (P-G).

**P-F. An explicit transition table in the photo controller.** One controller per member session.
Each operation has an id and owns its files until it ends.

| State | Pick | Retry | Discard | Remove or dismiss | A completion of the current operation | Session end or dispose |
|---|---|---|---|---|---|---|
| Idle | to Picking | refused | refused | to Removing, if the control's revision is the slot's | none expected | nothing |
| Picking | refused | refused | refused | refused | a file: to Preparing. Nothing: to Idle. An error: to Idle with a message | operation cancelled |
| Preparing | refused | refused | refused | refused | done: to Uploading. An error: to Idle with a message, files deleted | cancelled, files deleted |
| Uploading | refused | refused | refused | refused | stored: to Idle, read again. 409: to Idle, read again. An error: to Failed | cancelled, files deleted |
| Failed | refused | to Uploading, same operation | to Idle, files deleted | refused | none expected | files deleted |
| Removing | refused | refused | refused | refused | done or 409: to Idle, read again. An error: to Idle with a message | nothing |

- A command is accepted or refused synchronously, before the first await, and moves the state in
  the same call. Two taps in one frame can never both be accepted.
- Every completion and every progress callback carries its operation id. One that is not for the
  current operation changes no state. It may only delete its own files.
- File paths are unique per operation, and an operation's cleanup touches only its own files. A
  cleanup that is still running cannot affect the next operation.
- **A control acts on what it was drawn for.** Each control is keyed by the operation or the slot
  revision it shows, so a rebuild for another one replaces it and ends a held gesture. Its callback
  carries that same id, and the controller refuses a mismatch.

**P-G. One store for the member's own photo, ordered by `ReadOrder`.** Every writer of the
embedded photo goes through it: `/api/me`, the answers to profile writes, and any response that
embeds the member's own photo. A success and a 409 both call `changed()`, which drops older reads,
reads again, and invalidates the same dependent previews. Every surface that shows the member's own
photo, retained previews included, reads from that store.

### 9.3 What P3B removes after the rebase

Its changes to `session.dart`, `token_store.dart`, `api_client.dart` and `auth_repository.dart`
that concern credentials or account switching; `_credentialOwner`; `_settleAfterFailedSignIn`;
`beginAction()` and `MemberScope` and every call site that threads them; `_drawnFor`;
`_photoApplied`; the `singleTask` change (now in S1); `docs/handoff/WRONG_ACCOUNT_WRITES_FOLLOWUP.md`.
Test files named by round are regrouped by family. **[Guess]** The mobile diff shrinks by 2,000 to
3,000 lines.

### 9.4 Test matrix

- **P-E**: empty, then active, then empty again, against an old "empty" write; two first uploads;
  a write with no revision; a stale retry; each member command opened in state X against each
  change in between (staff removal, an upload or a dismissal from a second device); the rejected
  upload's object is released; the revision is absent from every public payload.
- **P-F**: the whole table; both orders of every pair of commands in one frame; a stale completion
  during a new operation; a slow cleanup during a new operation; pointer down, the slot's revision
  changes, pointer up.
- **P-G**: a 409 followed by an older `/api/me`; an upload answer followed by an older read; an
  older public-profile response; a failed refresh; a warm preview after a 409; the newer state
  after a restart.
- **P-D**: S1's S-4 rows, with the photo section and the removal notice on screen.
- **Device check (P-B)**: prepare the same input twice on an Android phone and an iPhone. The
  builder writes the steps; the result is recorded in the phase document at the phone test.

### 9.5 Done when

1. The four round-8 should-fix findings are tests, red before and green after. The three blockers
   are covered by S1's tests, run here with the photo section mounted.
2. The P3B branch holds no account-switch code of its own.
3. Screenshots in English and Arabic at 360 px for the photo states that changed.
4. All CI checks are green, "Schema drift" included.

---

## 10. Order, builders, branches

### 10.1 The order

```
Server, money:   F1  ................................  ->  F1b
                 G1-A -> G1-B -> G1-C  (one branch)        C1 after F1 and G1
Sessions:        N1  ->  S1-A -> S1-B  (S1 merges after N1)
Photos:          P3B-A  ............  -> P3B-B -> P3B-C  (after S1 merges)
```

- **Five builders can start together** once the plan is approved: F1, G1-A, N1, P3B-A and S1-A.
- G1 and F1 share only `docs/IMPLEMENTATION_STATUS.md`. The second to merge rebases, regenerates
  the schema contract, and the whole finance suite runs before C1 starts.
- N1 merges before S1, so the server answers sign-out the way S1's sender expects. `main` between
  the two merges has N1's server with N1's own phone code: registration works, and the phone's
  exits are as on `main` today.
- S1-A starts from the N1 branch, because S1 rewrites three phone files that N1 changed. It
  merges `main` in when N1 merges. **[Guess]** This is easier than starting from `main`; the lead
  may choose to wait for N1's merge instead.
- P3B-B waits for S1 to merge. P3B merges last, after N1 and S1, because all three change the same
  phone files.
- After these: C1, F2, M2, A1, M3, as HANDOFF 0.4 says, and the push-text package if D8 is yes.

### 10.2 The eleven briefs

Every builder is Claude Opus. Each brief is one file in `docs/handoff/builders/`, written to be
handed over as it is. A builder reads its brief, sections 3 and 4 of this plan, its own section,
and `CLAUDE.md`.

| Brief | Families | Main files | Branch | Starts after | Effort |
|---|---|---|---|---|---|
| F1 | F-C, F-F, F-G | `apps/finance/payout_accounts.py`, `payout_profiles.py`, `payout_profile_api.py`, `payout_mobile.py`, `payout_account_api.py`, `apps/core/financial_locks.py` | `claude/f1-payout-availability` | Approval | Extra high |
| F1b | Repair actions | `apps/finance/payout_accounts.py`, `apps/admin_panel/` console | new, from `main` | F1 merged | Extra high |
| G1-A | G-D | `apps/finance/models.py`, `services.py` (`reconcile_attempt`, `settle_checkout`), `providers/`, `operations.py`, console view and form | `claude/g1-guest-checkout-csrf` | Approval | Extra high |
| G1-B | G-E | `apps/finance/jobs.py`, `ScheduledJob`, the arm functions in `services.py` | same | G1-A | Extra high |
| G1-C | G-F | `services.py` (`_checkout_step`, `next_checkout`), `views.py`, `guest_web.py`, the two phone screens, `read_order.dart` | same | G1-B | Extra high |
| N1 | N-B, N-D, N-F | `apps/accounts/`, `apps/notifications/`, `backend/services/internal/notification/`, the phone's sign-out call | `claude/n1-notification-first-open` | Approval | Extra high |
| S1-A | S-1, S-2, S-3, S-5, S-6 | `mobile/lib/core/session/`, `core/api/api_client.dart`, `data/auth_repository.dart`, `read_order.dart`, Android manifest and one native method | new, from the N1 branch | Approval | Extra high |
| S1-B | S-4 | `mobile/lib/main.dart`, `app/app.dart`, `app/router.dart`, the sign-in screens, the socket providers, the test harness | same | S1-A | Extra high |
| P3B-A | P-E, server side | `apps/accounts/photos.py`, `models.py`, its views and serializers | `claude/p3b-profile-photos-app` | Approval | High |
| P3B-B | P-D removal, tests by family | the phone session files on the P3B branch, `mobile/test/` | same | S1 merged | Extra high |
| P3B-C | P-E phone side, P-F, P-G | `mobile/lib/app/profile_photo_state.dart`, `features/profile/profile_photo_section.dart` | same | P3B-B | High |

The lead coordinates and does not code. The lead hands over one brief at a time per branch, checks
the evidence table, and runs the gate.

### 10.3 Why the split is by family and by file

Each brief holds a set of families whose mechanisms live in files no other running brief touches.
A builder then needs its own section of this plan and those files, not the whole package and not
the history of the rounds. Briefs on one branch run one after the other, so two builders never edit
the same branch at once and no migration is written twice.

### 10.4 Astra runs

One prompt per pull request per round, built as section 3.6 says. Ismail gets each prompt as soon
as its package is green in CI. Briefs on one branch are reviewed together, once, when the last one
is done.

### 10.5 Follow-ups this plan creates or keeps (for HANDOFF 0.8, by the lead)

- Replaced by S1: "wrong-account writes outside profile photos".
- New package F1b (section 7.7), before payouts are switched on.
- New package, if D8 is yes: push text that is safe for anyone holding the phone.
- Kept: scheduled readiness refresh, `apps/finance/jobs.py:650` (F1 round 5).
- Kept: guest link expiry against the hosted URL; provider list against payout preflight (C1);
  Chargily create idempotency (G1 round 7).
- Closed here, no longer a follow-up: the empty currency and fractional amount (now G-D2).
- New: the refresh rotation does not tolerate a lost answer; the member is signed out. The same on
  `main`.
- New: an iOS build in pull-request CI. A cost decision.
- For the lead: Astra's reports for G1 round 7, P3B round 8 and N1 round 5 are not yet committed
  under `docs/handoff/astra/results/`. Its review of revision 1 of this plan is, on this branch:
  `docs/handoff/astra/results/loop-end-plan-astra-result.md`.

---

## 11. Accepted-risk register

Revision 1 had seven entries. Astra accepted two, rejected four and made one conditional. This is
the register after that.

| # | Package | Risk | Bound and why it is accepted | Repair |
|---|---|---|---|---|
| AR-1 | S1 | A sign-in whose answer never reached the phone, and whose tokens were never used or registered, stays live on the server. | The same on `main`. Nobody holds its tokens. A received answer is not this case: it goes to the ended list (S-2). | Its refresh token expires. |
| AR-2 | G1 | A payment that never verifies is read a few times a day until staff close it. | By design: it stays in front of Finance, the retries back off, and the order stays held. | Staff record a disposition. |
| AR-3 | S1 | The server refused a session, the phone's store refuses the write that records the end, and the phone restarts with no network: the earlier account snapshot is shown until the network returns. | One storage fault. No credential works; no request is authorised. | The first launch with a network ends the session. |
| AR-4 | S1 | The stored record is damaged beyond reading: the sign-ins it held are not ended on the server. | Outside the model (3.1). Handled anyway: the phone deletes its push token, so none of them can deliver a push here. | Their refresh tokens expire. |
| AR-5 | S1 | Tokens are issued, the phone's store refuses every write, and the sign-out that the core posts from memory also fails until the app closes: that sign-in stays live on the server. | Two faults at once, storage and network. Nobody holds its tokens once the app has closed, and it registered no push device. | Its refresh token expires. |

Removed from the register, and why:

- "A sign-out lost when the app is killed" is now closed by S-1 (acknowledged means on disk).
- "The ninth unsent sign-out is dropped" is now closed by S-5 (nothing is evicted).
- "A creation outstanding while its country closes" and "the wrong country" are not risks to
  accept: they need the two actions of F1b, and are unreachable while Connect is off.
- "A late payment after staff closed the item is only logged" is now closed by G-D6 (held again).

---

## 12. How a round runs from now on

1. The builder restates, per family: the invariant, where the one mechanism lives, the matrix
   tests, and the evidence table. That goes in the pull request.
2. CI is green on the branch.
3. The lead checks the table and the mechanical checks, and that nothing outside the families
   changed.
4. The lead writes the Astra prompt as section 3.6 says, with the three anti-loop rules, and gives
   it to Ismail at once.
5. Astra maps every finding to a family or to rule 2 of 3.2, gives the fault sequence in the terms
   of 3.1, and the class from 3.2.
6. The lead verifies each finding against the code and classifies it (3.4).
7. Merge when CI is green and Astra approves, or as Ismail decides at a stop.

---

## 13. Guesses and what was not checked

- **[Guess]** The provider-container swap of S-4 is feasible with the current router, plugins and
  test harness. Not prototyped.
- **[Guess]** On Android, a `commit()` on the storage plugin's preferences file waits for its
  outstanding `apply()`. This is the platform's documented behaviour; it was not run. The kill test
  decides, and the fallback is named in S-1.
- **[Guess]** Which platform errors mean the stored record is undecryptable.
- **[Guess]** Both payment providers state a currency in a success answer or in the read that
  follows.
- **[Guess]** Stripe refuses a repeated create with the same request the same way it refused the
  first.
- **[Guess]** Sizes: S1 at 1,500 to 2,500 lines; P3B shrinking by 2,000 to 3,000.
- **[Guess]** F2, not F1, owns the screen that shows the two new payout states.
- **[Guess]** F1b's "refused while a payout to that account is in progress" maps onto existing
  payout states without a new one.
- **[Guess]** Starting S1-A from the N1 branch is less work than rebasing it later.
- Families marked "Closed" were not re-verified. They are closed because Astra's latest report on
  each package raised nothing in them, and Astra disputed none in its plan review.
- Astra could not find its own G1 round-7 report apart from Appendix A, so Appendix A's G1 rows
  rest on the copy Ismail pasted.
- No test was run for this plan. No code was changed.

---

## 14. What changed from revision 1, by Astra's required change

| Astra's required change | Where this revision makes it |
|---|---|
| 1. Tighten D4 and G-D: account for every reported debit through staff resolution, refunds and late evidence before another collection | D4 reworded. G-D rebuilt as G-D1 to G-D6: three facts kept apart; "verified" defined (G-D2, which takes in the currency and fraction defect); a hold ends only by one of four dispositions (G-D5); a typed provider read; open, processing and unreadable keep the hold; late evidence puts the attempt back on hold as a row (G-D6); the finance queue and the unapplied-refund path are unchanged. The "log only" risk is removed. |
| 2. Land the revocation contract with S1; durable acknowledged transitions; no silent eviction; no status-code-only acknowledgment | N1 merges before S1 (10.1). The sign-out contract is stated (5.2). S-1 requires "on disk before acknowledged", with a mechanism and a kill test. S-5 removes an entry only on 205 or `sign_out_proof_invalid`, keys by `sid`, never evicts. One engine per phone moves into S1. |
| 3. Protect credential and privilege writers in N-D; assign end-to-end notification privacy to N1 | N-D rebuilt without a model override: named writers, named fields on every save, and forms that carry what staff saw (8.2). New family N-F and rule R10: the queued push is checked against its sign-in; shown notifications are cleared; the part that cannot be recalled is decision D8. |
| 4. Complete F-C's concurrent-dispatch and release rules; demonstrate the Finance and Support repairs | F-C1 to F-C5: who may still send, when the freeze ends, overlapping callers and the binding successor, and a read model that offers only what can advance. The repairs do not exist in the code; they are package F1b (7.7) and decision D9, and the states are unreachable while Connect is off. |
| 5. Severity precedence, the bounded credential contract, newly introduced families, and the round-two Should-fix stop; keep the two-pass cap | 3.1 defines one fault, the ordinary participants, recovery and the bounds. 3.2 is an ordered list of questions; M, A, C and L are redefined with Astra's additions; C has its time boundary. Rule 2 of 3.2 puts failures a planned mechanism introduces in scope. 3.4 stops on a Should-fix too, and limits "switched off". The cap stays. |
| 6. Complete the slot-version, read-order, job-wake, eligibility and response-snapshot matrices; preserve earlier fixes | P-E (a revision that outlives the photo), `ReadOrder` (section 4) and S-6 and P-G, G-E1 to G-E3, F-F, F-G, each with the rows Astra listed. Rule 3.5 item 2 and "Done when" lines keep the closed families' tests green. |
| 7. (Should) Reports, red-test baselines and device evidence beside the matrices | 3.5 items 4 and 6, and 3.6. |

Other points taken from the review: S-2 (refresh answers compare the credential they sent; a late
rotation is not a new sign-in); S-3 (an unreadable record is never overwritten; every end names its
sign-in; `Retry-After`); S-4 (every call into the core names its sign-in; sockets; guest
continuation only for the flow that asked); P-F (the actual table, completions and file ownership,
controls bound to what they show); G-F (the facts the gate takes, the neutral guest projection, the
preflight left to C1); Appendix A's three corrections; Astra's criteria as Appendix B.

Not taken as written, with the reason:

- Astra offered "ship the server contract before **or together with** S1". This plan takes
  "before": N1 whole, then S1. N1's server is not split from its phone code, so `main` never has a
  server that the phone on `main` cannot register with.
- Astra asked that a late verified payment on a closed item have "a named disposition". This plan
  gives that item one way out, `returned`. It adds no staff action that credits the order, to keep
  the money paths at the two that exist. The payer is refunded and pays again.

---

## Appendix A. The latest findings, each mapped to a family and a mechanism

Astra's reports for G1 round 7, P3B round 8 and N1 round 5 are not committed yet. This table
restates each finding of the four latest reports, with Astra's three corrections applied.

| Package | Finding | Where | Family | Mechanism |
|---|---|---|---|---|
| F1 r5 | Blocker: the intent is committed, the database connection dies while the request to Stripe is still being sent, the session lock drops, a DE preference commits, and the FR creation is still sent | `payout_accounts.py:1039`, `payout_profiles.py:144` | F-C | F-C1, F-C2 |
| F1 r5 | Should-fix: waits on the advisory lock have no deadline | `financial_locks.py:367,387` | F-F | The lock is deleted; no lock across a provider call |
| F1 r5 | Should-fix: eligibility is not checked again after the wait, nor at the link handoff | `payout_accounts.py:1024`, `payout_profiles.py:77` | F-F | Eligibility on the locked row |
| F1 r5 | Should-fix: one GET computes the euro actions twice | `payout_profile_api.py:299`, `payout_mobile.py:103` | F-G | One snapshot per response |
| F1 r5 | Outside F1: scheduled readiness refresh | `jobs.py:650` | none | Follow-up |
| G1 r7 | Blocker 1: an unverified payment does not stop a new checkout; the owner's app says nothing was charged | `services.py:1413,1630,1860,2054` | G-D | G-D3, G-D4 |
| G1 r7 | Blocker 2: a stale worker's completion overwrites a re-armed job | `jobs.py:1019,1079,1194`, `services.py:2184,2217` | G-E | G-E2, G-E1 |
| G1 r7 | Blocker 3: staff resolve while the settle job is mid-read; the late success is applied | `services.py:2032,2047,2697`, `operations.py:310` | G-D | G-D5, G-D6 |
| G1 r7 | Should-fix: Chargily's close learns "failed" but reports only "closed"; the attempt is final and `processing` forever | `providers/chargily.py:391`, `services.py:2081,1622,1977` | G-D | G-D1 |
| G1 r7 | Should-fix: the close intent and the job wake commit separately | `services.py:1653,1835,1858,2209` | G-E | G-E3, G-E1 |
| G1 r7 | Should-fix: an older successful read re-enables a refused action | `guest_pay_screen.dart:83,194`, `checkout_section.dart:410,521` | G-F | G-F2, G-F1 |
| G1 r7 | Outside G1: four rows | see 10.5 | none | Follow-up; the currency and fraction row is now G-D2 |
| P3B r8 | Blocker 1: pointer down on A's Dismiss, a rebuild publishes B while the pointer is down, the release runs B's callback | `profile_screen.dart:99`, `profile_photo_section.dart:175`, `primitives.dart:615` | P-D | S-4; within one session, P-F's keyed controls |
| P3B r8 | Blocker 2: an interrupted credential save leaves A on screen with B's bearer; the overtaken clear is the same | `token_store.dart:134`, `session.dart:530` | P-D | S-1, S-2 |
| P3B r8 | Blocker 3: the name draft and the language retry take their scope when submitted | `account_name_screen.dart:118`, `language_screen.dart:148`, `session.dart:689` | P-D | S-4 |
| P3B r8 | Should-fix: a staff removal keeps the version, so an old Remove dialog deletes the new notice | `photos.py:393,436` | P-E | A revision that outlives the photo |
| P3B r8 | Should-fix: Retry and Discard in the same frame | `profile_photo_section.dart:305`, `profile_photo_state.dart:464` | P-F | Transition table |
| P3B r8 | Should-fix: after a 409, the reread it triggers shows the fresh state, an older `/api/me` then undoes it, and retained previews stay stale | `profile_photo_state.dart:497`, `session.dart:740` | P-G | `ReadOrder`, one store, previews invalidated |
| P3B r8 | Should-fix: a keystore error is not shown by the password screen | `session.dart:492`, `sign_in_screen.dart:70` | P-D | S-2 typed error |
| P3B r8 | Partly fixed: round-3 item 13, native fixture and iOS build in CI | native code, CI | P-B | Recorded device check; follow-up for CI |
| N1 r5 | Blocker 1: the technical admin's full-row save writes back the old password hash and `session_epoch` after a reset | `accounts/admin.py:25`, `accounts/sessions.py:57` | N-D | Named writers, named fields |
| N1 r5 | Blocker 2: a sign-out overtaken by another sign-in returns without sending, also when that later sign-in fails; a test expects no request | `auth_repository.dart:184`, `session.dart:399`, `phase8ff4_session_test.dart:215` | N-E | S-2, S-3, S-5 |
| N1 r5 | Blocker 3: a 429 on the launch `/api/me` clears credentials instead of waiting for `Retry-After`; the server sign-in and the push device stay on | `session.dart:303`, `api_exception.dart:114`, `config/settings/base.py:196` | N-E | S-3 |
| N1 r5 | Should-fix: a repeated sign-out of an ended sign-in still advances the installation order, taking the highest accepted sequence | `accounts/sessions.py:85`, `notifications/push.py:790`, `test_push.py:596` | N-B | The sign-in row decides; zero writes |

---

## Appendix B. Astra's pre-registered code-review criteria

Given by Astra in its review of revision 1. Later rounds are held to this list.

1. **S1.** Trace restore, all four sign-ins, token rotation and reissue, every exit, snapshot
   persistence, socket authentication, and outbox acknowledgment through the production adapters.
   Exercise cancellation, restart, failure at storage acknowledgment, same-account re-login, and
   shared-device UI teardown. Reject a restored ended session, lost cleanup proof, stale callback
   acting on the current session, or wrong-member read or write.
2. **G1.** Trace each provider outcome through checkout, webhook, poll, close, staff action,
   ledger, refund obligation, attention queue, guest HTML, and both phone screens. Exercise claim
   loss and same-claim wakeups. Reject a second collection, unverified credit, suppressed Finance
   obligation, false final state, lost job, or reproducible screen/gate disagreement on identical
   facts.
3. **F1.** Exercise PATCH and single-currency POST, two onboarding callers, funding, provider
   recovery, staff eligibility changes, and hosted-link return. Observe the actual locked rows,
   request identity, provider object, funded instruction, and serialized response. Reject
   superseded dispatch, a false thaw, a mixed response, an ineligible handoff, or a freeze without
   its advertised recovery.
4. **N1.** Exercise real session issuance, rotation, reset, account claim, deletion,
   technical-admin POST, register, unregister, sign-out, queued push and socket expiry. Retain
   first-open and denial-recovery coverage through the real router. Reject restored credentials or
   privileges, changes by an ended sign-in, stale binding or private delivery, or a regression in
   the agreed prompt behavior.
5. **P3B.** Exercise the real picker, controller, HTTP preconditions, locked slot, profile snapshot
   and retained previews. Include both devices, same-frame commands, interrupted responses and the
   member boundary. Reject a stale write, wrong file or account, lost moderation notice, or stale
   preview after an authoritative refresh.
6. **Every package.** Apply the family table and the existing closed-family regression assertions.
   A failing test must distinguish the bad outcome from a correct serial execution. Reject an
   in-scope Blocker or Should-fix, including an agreed gate that the supplied evidence does not
   exercise. An unrelated pre-existing defect goes to its follow-up.

For F1's criterion 3, "a freeze without its advertised recovery": the recovery inside the replay
window is the next onboarding call. Past the window it is F1b, and until F1b merges Connect stays
off.
