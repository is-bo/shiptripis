# Plan to end the Astra review loop (P3B, G1, F1, N1)

**Status:** proposal by the planner, 27 November 2026. Not approved. Nothing here is built yet.
**Next:** Astra reviews this plan before any code (`docs/handoff/astra/loop-end-plan-review.md`).
Ismail decides the questions in section 2. Builders start only after both.

Guesses are marked **[Guess]**. Everything else was checked against the code at the pull-request
heads listed in section 1, or against Astra's reports.

---

## 0. Summary for Ismail

The four packages keep failing review for one reason: nobody fixed what "done" means. Astra can
always find one more rare sequence. Each fix added new code, and new code gave Astra new things to
find. Packages that began as small tasks are now between 4,000 and 15,000 lines.

This plan does four things.

1. **It fixes the rules of the review** (section 3): which failures a finding may assume, what
   counts as a blocker, what belongs to a package, and when the rounds stop.
2. **It replaces case-by-case fixes with a few mechanisms per package** (sections 5 to 9). All
   findings of all rounds fall into 25 families. 12 are closed. The 13 open ones get one invariant,
   one mechanism and one test matrix each.
3. **It builds the "two accounts on one phone" protection once**, in a small new package (S1),
   instead of twice inside P3B and N1. That problem alone produced most P3B blockers.
4. **It caps the rounds**: Astra reviews this plan (two passes at most), then each package gets one
   full code review and one re-check. Twelve Astra runs at most. The four packages have used 25.

What you need to decide is in section 2. It is seven short questions.

---

## 1. Why the reviews do not converge

| Package | Original task | Rounds | Size now | Latest result |
|---|---|---|---|---|
| P3B #66 | Profile photos in the app | 8 | +14,865 lines, 138 files | Reject at `7727b19`: 3 blockers, 4 should-fix |
| G1 #67 | Guest payment page works without the browser-session check | 7 | +7,285 lines, 67 files | Reject at `57684cb`: 3 blockers, 3 should-fix |
| F1 #69 | Show payout availability and actions. "No new rail or switch" | 5 | +4,189 lines, 37 files | Reject at `bd74c3a`: 1 blocker, 3 should-fix |
| N1 #71 | Ask for notification permission once, at first open. Mobile only | 5 | +6,068 lines, 83 files | Reject at `3e7fc17`: 3 blockers, 1 should-fix |

Six causes, each with evidence.

1. **No agreed fault model and no severity bar.** The F1 round-5 blocker needs the database
   connection to die at one precise moment, and its result is a refusal the traveler can recover
   from. P3B round-8 blocker 1 needs a finger down on one account's button while another account
   signs in on the same phone before the finger lifts. Both may be worth closing. Neither was ever
   weighed against a written bar, so every reachable sequence became a blocker.
2. **Each fix added a mechanism, and each mechanism is new surface.** F1 round 5 added a session
   lock (`hold_payout_account_setup`); the round-5 blocker and two should-fix findings are about
   that lock. On P3B, `session.dart` grew from 616 to 895 lines and now carries two generation
   counters, a credential owner and an ad hoc ordering counter. G1's settle job has three special
   cases for when it is armed.
3. **Correctness leaned on things that are not durable or not atomic.** A session-level advisory
   lock that ends with its connection (F1). Three storage keys written one after the other
   (`auth.access`, `auth.refresh`, `auth.account_snapshot`, on main and both mobile branches). A job
   armed only at the moment a state is entered (G1 `_hold_unverified_payment`). Completion writes
   that do not check the worker still owns the job (`jobs.run_job`).
4. **One rule, two implementations.** G1's gate `_checkout_step` and its screen mirror
   `next_checkout` restate the same conditions separately. In every round from 3 to 7 Astra found a
   screen offering what the gate refuses.
5. **Ambient authority on the phone.** "Who is signed in" is read when a request is sent, not when
   the member acted. P3B rounds 3 to 8 and N1 rounds 4 and 5 are this one family. P3B answered it
   call site by call site (`beginAction()`, `MemberScope`), and every round found the next call
   site.
6. **Tests are organised by round, not by rule.** P3B has `p3b_photo_round2_test.dart` to
   `round8_test.dart`. Nobody can see which interleavings a rule's tests cover, so nobody can say
   a family is closed.

---

## 2. Decisions for Ismail

Each has a recommendation. Building does not start before these are answered.

| # | Question | Recommendation |
|---|---|---|
| D1 | Adopt the review contract in section 3: the fault model, the severity table and the written list of accepted risks? | Yes |
| D2 | Adopt the stop rule in section 3.4? It changes "merge only when Astra approves" in one case: when a package hits its cap, you choose between merging with the feature switched off, cutting the feature, or re-planning. | Yes |
| D3 | Add the small package **S1 (session core)** before N1 and P3B? It replaces the follow-up "wrong-account writes outside profile photos" in HANDOFF 0.8. | Yes |
| D4 | G1 money rule, two parts. (a) While a payment on an order is "being checked" (the provider said paid but the amount could not be verified), the order takes no new payment. (b) To close such an item, the system first re-reads the provider, so a real payment is credited at that moment. After staff close it, a late "paid" report is **not** credited automatically. It raises an alert. | Yes to both |
| D5 | F1: while a Stripe account is being created for a traveler, the app refuses to change the payout country or switch euros off, with "setup in progress". Today it lets the change through and the account can end up in the wrong country. | Yes |
| D6 | Accept the scope cuts in section 3.3 and the follow-ups in section 10.4? | Yes |
| D7 | Builders: Claude Opus at extra-high effort for S1, G1, F1, N1 and P3B? (P3B and N1 were planned on the lighter model; they now touch sign-in and sessions.) | Yes |

---

## 3. The review contract

This section is the same for every package. Every Astra prompt carries it, next to the three
anti-loop rules of `docs/handoff/COORDINATOR.md` section 3, which stay in force unchanged.

### 3.1 Fault model: what a finding may assume

**Inside the model**

- a. Any interleaving of requests from any number of members, guests and staff, with webhooks and
  job runs.
- b. Any message delayed, duplicated, reordered or lost: a request, a response, a webhook, a push.
- c. One crash at any point: a web worker, a job worker, a database connection, the app process.
  Also a worker that was presumed dead and resumes later.
- d. A provider (Stripe, Chargily, FCM, Google, Apple) slow, down, or answering ambiguously, for
  example a timeout after it may have acted.
- e. A person at human speed: double tap, back, backgrounding, killing the app, two devices, and a
  phone used by two members one after the other.
- f. A storage write on the phone failing, or the app dying between two storage writes.
- g. A staff member doing an allowed action at any moment.

**Outside the model**

- h. Data, URLs, events, jobs or app versions from before the package (anti-loop rule 1).
- i. A deploy or a configuration change (country allowlist, platform account, test or live mode,
  rail switch) racing a request that is already in flight. The state after the change must be
  handled correctly by requests that start after it.
- j. Two or more independent faults together, unless the result is in a blocker class below and can
  be neither seen nor repaired.
- k. A malicious staff member, or a compromised server, database or provider.

### 3.2 Severity

| Class | Definition |
|---|---|
| **Blocker** | Reachable inside the model **and** one of: **M** money (a payer charged twice for one order; money taken that is neither credited, refunded nor in front of staff; a credit or payout that should not happen). **A** authority or privacy (anyone reads or changes what belongs to another account; a hidden location, delivery code or tracking number leaks). **C** credentials (a sign-in, token or push registration that the member or the server ended keeps working). **L** lock-out (a member or an order stuck with no path in the app and no staff action that repairs it). |
| **Should-fix** | Reachable inside the model through ordinary use or one fault, with a visible wrong result: a wrong message, an action offered and then refused, a state stuck until staff act, two implementations of one rule that disagree. |
| **Accepted risk** | Inside the model, but it needs two independent faults or a crash inside a sub-second window, **and** the result is none of M, A, C, **and** it repairs itself or staff can repair it. It is written in the register (section 11) with its repair path. It is not fixed in the package. |
| **Not applicable** | Anti-loop rule 1: legacy data, upgrades, old app versions. |
| **Out of scope** | Anti-loop rule 2: it exists on `main` the same way without the package, or sits in code the package neither changes nor depends on. It goes to HANDOFF 0.8. If it is blocker class it gets its own small fix package at once. It never blocks the current package. |

The verdict rule does not change: reject only for an in-scope Blocker or Should-fix. What changes is
that the class now follows this table.

### 3.3 Scope

A package's scope is its families (sections 5 to 9). A finding names the family it belongs to, or
says "outside the families".

Scope cuts this plan makes:

- **P3B** no longer owns account switching on a shared phone. That is S1. P3B is profile photos.
- **N1** no longer owns how the phone leaves a sign-in. That is S1. N1 is the permission prompt
  plus "a phone's push registration follows its sign-in".
- **G1** keeps the payment-attempt lifecycle it grew into, because the code is on its branch and
  entangled. Its scope is now stated honestly as six families (section 6). The four out-of-scope
  rows of Astra's round-7 report stay follow-ups.
- **F1** keeps onboarding creation, because the read model cannot be correct without it. The
  scheduled readiness refresh (`jobs.py:650`) stays a follow-up.
- **P3B round-3 item 13** (the native "prepare twice" fixture and an iOS build in pull-request CI)
  becomes a device check plus a follow-up. An iOS build in CI is a cost decision for Ismail.

### 3.4 Stop rule

**The plan.** Astra reviews this plan once. The planner revises. Astra re-checks only the revisions.
There is no third pass: an open disagreement goes to Ismail as a decision.

**Each package.** Round 1 is a full review against this plan. Round 2 re-checks only the round-1
fixes and what they touched. A round 3 needs Ismail's explicit OK.

**Each finding** is verified against the code by the lead, then classified:

| Class | Meaning | Who acts |
|---|---|---|
| Build gap | The code does not do what the plan says. | The builder fixes it. The plan does not change. |
| Plan gap | The code does what the plan says and the family's invariant still breaks. | The planner revises that family once. The mechanism changes; no case is patched. Then the builder applies it. |
| Outside | Not in any family of the package. | Triage with the table in 3.2: follow-up, accepted risk, or its own fix package. |

**Work on a package stops, and Ismail chooses, when any of these happens:**

- a second plan gap in the same family, after its one revision;
- round 2 still has an in-scope blocker;
- a fix would need a mechanism this plan does not name (a new lock, counter, flag, column, job kind
  or retry loop). The builder stops and asks the planner instead of adding it.

**Ismail's options at a stop:** (a) merge with the capability switched off on the server, and
record the open item as the condition for switching it on; (b) cut the capability from the package;
(c) re-plan the family. Option (a) exists today for F1 (Connect payouts are off) and N1 (push is
off). **[Guess]** P3B would need a new switch for photo upload. G1 has no switch, because checkout
is core; for G1 only (b) and (c) apply.

**Budget.** The plan: at most 2 Astra runs. S1, G1, F1, N1, P3B: at most 2 each. Twelve in total.

**What the cap accepts.** Two rounds will not find everything. What they miss is found by the
phone test and by later packages, while the app still has no users. The cap trades a small, written
risk for packages that merge.

### 3.5 Rules for builders that keep packages from growing

1. **Mechanism budget.** A builder adds no lock, counter, generation, flag, column, job kind or
   retry loop that this plan does not name. If one seems needed, the builder stops and asks.
2. **Remove what is replaced, in the same pull request** (CLAUDE.md quality bar). Each section
   lists what goes.
3. **Tests by family.** One matrix per family, named after its invariant. Round-named test files
   are regrouped. A test of a deleted mechanism is rewritten to the new rule and listed in the pull
   request with the reason. No assertion is loosened.
4. **Red first.** Each latest-round finding of an open family is first reproduced as a failing
   test on the current branch. The pull request shows it red before and green after.
5. **One writer, checked mechanically.** Each mechanism has a check that there is one writer: a
   database constraint, or a test that scans the source for a forbidden pattern. Each section names
   them.
6. **The phase document describes the final design**: families, invariants, where each mechanism
   lives, the matrix. About 200 lines. Round history stays in git and in
   `docs/handoff/astra/results/`.

---

## 4. Design rules shared by every package

| # | Rule | Replaces |
|---|---|---|
| R1 | Across a provider call, the only lock is a durable row. Nothing is correct because a connection stayed open, a process stayed alive or a timer has not fired. | F1's session advisory lock |
| R2 | An intent is committed before its effect, in the same transaction as whatever must follow it (the job, the freeze). | G1's close intent and job wake in two transactions |
| R3 | An obligation is a predicate on rows, enforced by a sweep on every job cycle. Arming a job when a state changes only makes it faster. | G1's "arm only on the way in" |
| R4 | A job run owns its claim. A completion is written only if the claim is still its own. Handlers are idempotent and re-read state under the domain lock. | `run_job`'s unconditional updates |
| R5 | Automatic paths obey decisions that staff recorded, read under the row lock. | G1's late success after a staff resolution |
| R6 | One decision function per rule. The write path calls it under the lock. The read path calls the same function without the lock. Screens render its answer. | G1's `_checkout_step` and `next_checkout` |
| R7 | Authority is bound when an action starts. It is never read from "who is signed in now" when the request is sent. | P3B's per-call scope checks |
| R8 | A state that must never exist is made impossible to store (a constraint, one record, one writer), not avoided by care. | Three credential keys; "final" without a terminal status |
| R9 | On the phone, a refusal or a newer answer always beats an older read. | P3B's `_photoApplied`; G1's screens |

**`ReadOrder`, the one helper for R9.** A small class in `mobile/lib/core/read_order.dart`: `begin()`
returns a ticket; `accept(ticket)` is true only for a ticket newer than the last accepted one and
newer than the barrier; `invalidateEarlier()` sets the barrier to the newest ticket issued. A
mutation's answer and a refusal both call `invalidateEarlier()`. G1's two screens, the account
snapshot in S1 and P3B's photo state all use it. Whichever of G1 and S1 merges first creates the
file; the other rebases onto it.

---

## 5. S1: session core (new package, mobile)

**Branch from `main`. Builder: Claude Opus, extra-high effort. Lands before N1 and P3B.**

### 5.1 Why it exists

Two families, in two packages, have one root.

- P3B "an action started as member A runs as member B": round 3 blocker 4; round 4 blocker 3;
  round 5 blocker 2; round 6 blockers 1 to 3; round 7 blockers 1 to 5; round 8 blockers 1 to 3.
- N1 "the phone leaves a sign-in that the server still holds": round 3 (offline sign-out);
  round 4 blocker 2; round 5 blockers 2 and 3.

The root: the phone's session is several pieces changed at different moments, removed in several
places, and its authority is read at send time.

Checked on `main`:

- Credentials are three keys written one after the other (`token_store.dart`).
- Two generation counters decide what is current (`SessionController._generation` and the token
  store's identity generation).
- Credentials are removed in four places: `auth_repository.signOut`, the interceptor's
  `_endSession`, `SessionController._confirm`, and `accountDeleted`.
- `_confirm` removes credentials on any error that is not "retryable", and a 429 is not
  (`ApiException.isRetryable` covers offline, timeout and server errors only).
- There is one root `ProviderScope` for the whole app life, and one top-level `GlobalKey`
  (`_rootNavigatorKey` in `router.dart`).
- The four sign-in entry points (password, sign-up, Google, Apple) each have their own busy state.

### 5.2 Invariants and mechanisms

**S-1. One record.** Everything that says who is signed in on this phone is one stored document
under one key: the account snapshot, the access token and the refresh token, or nothing; plus the
list of ended sign-ins the server has not yet confirmed. Every transition is one write of that one
key. An interrupted write leaves the state before or the state after, never a mix.

- One object, `SessionCore`, created in `main()` before `runApp`, holds the only in-memory copy.
  The published session state, the bearer of every request and the account on screen are all read
  from that copy. The copy changes only after the write has resolved.
- One number, the member-session id, changes at every commit that changes who is signed in. It
  replaces `_generation`, the token store's identity generation and P3B's `_credentialOwner`.
- Device-level values (language, push prompt count, push sequence, installation id) are not part of
  the record. They say nothing about who is signed in.

**S-2. One transition at a time.** Restore, sign-in, token replacement and end go through one queue
inside the core.

- A sign-in attempt can start only when the state is signed out, the reset of S-4 is complete and
  no attempt is open. All sign-in controls share one busy state from the core.
- An attempt commits only if it is still the open attempt, in the member-session id it started in.
  An attempt whose screen went away is cancelled. If its answer arrives later with tokens, that
  sign-in goes straight to the ended list, so the server ends it. It never reaches the record.
- **There is no transition from member A to member B.** B can only start from signed out.
- New tokens for the same account (a refresh, or any endpoint that reissues tokens) replace the
  tokens by one write, and only for the same member-session id and the same account id. Anything
  else is treated as a dead attempt.
- A storage failure leaves the in-memory copy unchanged and reaches the screen that asked as a
  typed, translated error.

**S-3. One exit.** Credentials leave the record only through `end(reason)`, for four reasons: the
member signed out; the server definitively refused the refresh token; the account was deleted; the
stored record cannot be read at launch. No other answer ends a session. A 429, 403, 404, 5xx,
timeout or offline answer, on `/api/me` or anywhere else, keeps the member signed in with the stored
snapshot and is retried later.

- `end` is: one write (record to none, ended list plus this sign-in), then the in-memory copy, then
  the teardown of S-4, then the sender of S-5.
- If that write fails on a member's sign-out, the member stays signed in and is told so. If it
  fails for a session the server already ended, the phone ends in memory anyway and repeats the end
  at next launch; the stored credentials are already dead.

**S-4. The member's screens end with the member's session.** When a member session ends,
everything built during it is destroyed before anything else can be shown or tapped: widgets and
their state, routes, dialogs, sheets, controllers, providers and the API client.

- A `MemberBoundary` widget above the app owns the provider container. On `end` it disposes the
  old container and builds a new container and a new app subtree under a new key. The core, the
  push messaging handle and the device settings (language, theme) are created outside and passed
  in, so they survive and nothing flickers.
- The old container is disposed without the signed-out state being published into it, so no old
  listener runs "on signed out" code.
- No top-level `GlobalKey` remains. `_rootNavigatorKey` moves inside the router provider. A
  top-level key would carry the old navigator, with its open dialogs, into the new tree.
- The core refuses a sign-in until the boundary reports the first frame of the new tree.
- **The API client is built for one member-session id.** It can attach a bearer only by asking the
  core for the access token of that id, and the core answers only while that id is current. It is
  closed when its container is disposed. A continuation that kept an old client object gets a typed
  "session ended" error. It cannot send as another member. The client provider depends on the
  member-session id, so a sign-in gives every provider a new client; a guest flow that kept the old
  one across a sign-in fails loudly and is fixed to read it again.
- A guest who signs in keeps the tree, so "sign in to continue" still works. Nothing in that tree
  was built for another member, because the previous member's end destroyed it.
- A native picker or sheet that outlives the tree returns into disposed code, and its result is
  dropped.

**S-5. The server always hears about an ended sign-in.** A sender inside the core posts each entry
of the ended list to `POST /api/auth/sign-out`, with that sign-in's own credentials and never the
current member's: at once, at launch, when the network returns, with capped backoff. An entry is
removed only by a definitive answer: any 2xx, or a 4xx other than 408 and 429. The list is bounded
at eight entries.

- Until N1's server change lands, `main`'s endpoint needs a valid access token. The sender sends
  the ended sign-in's own access token as bearer and its refresh token in the body. That equals
  today's behaviour. After N1, the refresh token alone is enough.

**S-6. Newer truth wins.** Updates to the account snapshot go through `ReadOrder`. The answer to a
profile change invalidates any `/api/me` read that started before it.

### 5.3 What S1 removes

The three credential keys and the identity generation in `TokenStore`; `_generation` in
`SessionController`; the `expectedIdentityGeneration` path of `auth_repository.signOut`; the
interceptor's `_endSession`; the clear inside `_confirm`; `_leavePrivateScreens` in the router
(the boundary replaces it); the four separate sign-in busy flags.

### 5.4 Test matrix

| Invariant | Rows |
|---|---|
| S-1 | The one write throws, at each transition (sign-in, token replacement, end, snapshot update): state before, in memory and after a restart. The app is killed at each await of each transition, then restarted. |
| S-2 | Password and Google tapped in one frame. A second attempt while the first waits on the network. An attempt cancelled, then its answer arrives with tokens (they go to the ended list). A sign-in answer arriving after background and foreground. A refresh answer arriving after `end`. Reissued tokens for the same account, and for another account. |
| S-3 | For each of: 401 after a refused refresh; 401 with a network error on refresh; 403; 404; 429; 500; timeout; offline. On `/api/me` at launch, and on an ordinary request. Expected: ended only in the first case. |
| S-4 | Pointer down on a member's button, `end`, pointer up. A dialog open at `end`. A bottom sheet open at `end`. A text field holding a draft at `end`, then another member signs in. An old client object used after `end`. An old `ref` used after `end`. "Sign in to continue" still resumes for a guest. Language and theme identical on the frame before and after the reset. |
| S-5 | Sign-out offline, then online. The app killed before the send. Answers 500, then 429, then 205. A 401 answer drops the entry. Member B signed in while A's entry is pending: the request carries none of B's credentials. No entry is sent again after a definitive answer. |

Mechanical checks: one place writes the record key; one function removes credentials; no top-level
`GlobalKey` in `mobile/lib`; no read of an access token outside the core.

### 5.5 Done when

1. One stored record holds the sign-in. No other key says who is signed in.
2. Credentials are removed in one function, for the four reasons only.
3. Every row of 5.4 passes. The three P3B round-8 blockers and N1 round-5 blockers 2 and 3 are
   among them, as tests that fail on `main`.
4. A member session's end rebuilds the app tree.
5. An old API client cannot send after its session ended.
6. Every new string exists in English, French and Arabic. Screenshots in English and Arabic at
   360 px for each changed screen state.
7. The whole mobile suite and the Android build are green in CI.

### 5.6 Risks

- **[Guess]** Replacing the provider container at the app root works with `go_router`, the push
  coordinator and the plugins in use. This was reasoned from the code, not prototyped. It is the
  main implementation risk. If it cannot be made to work, the builder stops and comes back to the
  planner. A per-screen substitute is not acceptable: it is the discipline that failed.
- **[Guess]** S1 is about 1,200 to 2,000 lines with tests, and close to neutral in `mobile/lib`.
- About 12 test files drive sign-out today and will need the new harness.

---

## 6. G1: guest checkout and the payment-attempt lifecycle

**Continue on `claude/g1-guest-checkout-csrf`, after merging `main` in (the branch is 27 commits
behind). Builder: Claude Opus, extra-high effort.**

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
- Two predicates exist: `LIVE_CHECKOUT` (stored, not final, not succeeded) and
  `UNVERIFIED_PAYMENT` (failed with an unverified code and no staff resolution).
- The gate `_checkout_step` checks `LIVE_CHECKOUT` and never `UNVERIFIED_PAYMENT`.
- `next_checkout` restates the gate's conditions for the screens.
- `_record_checkout_final` sets `checkout_final_at` without a terminal status.
- `settle_checkout` returns "final" when `checkout_final_at` is set, whatever the status.
- `reconcile_attempt` applies a late success to a failed attempt without reading
  `operational_resolution`.
- `run_job` writes all four outcomes with `filter(pk=job.pk).update(...)`.
- `arm_live_checkouts` re-arms `LIVE_CHECKOUT` attempts only.

### 6.3 Invariants and mechanisms

**G-D1. Final means terminal.** `checkout_final_at` is written by one function only,
`reconcile_attempt`, in the transaction that also writes the terminal status. `_record_checkout_final`
goes. `close_checkout` returns how the provider says the checkout ended (closed unpaid, failed,
expired, cancelled, or a payment under way), and `settle_checkout` passes that outcome on.
A check constraint makes the bad state impossible to store:
`checkout_final_at IS NULL OR status IN ('succeeded','failed','expired','cancelled')`.
A check constraint is tested per statement, so the two columns are written by one UPDATE; today
`reconcile_attempt` saves `checkout_final_at` first and the status in a later statement.
The gate's branch "final but still open: replace it" disappears, because that state cannot exist.

**G-D2. One predicate for "not settled".** `OUTSTANDING = LIVE_CHECKOUT or UNVERIFIED_PAYMENT`, in
`models.py`. With G-D1 this is exactly "handed out and not settled". The gate, the early return of
`settle_checkout`, the sweep, `_already_satisfied_reason` and the finance attention queue all read
it. No path states its own version.

**G-D3. The gate refuses while a payment is being checked.** An order with an `UNVERIFIED_PAYMENT`
attempt opens and hands out no checkout. The answer is the stable code `payment_under_review` (409),
translated: a payment for this order is being checked, do not pay again. No surface says "nothing
was charged" for such an attempt: not the app, not the guest page, not the payment-failed email
(an unverified hold sends none). This is decision D4(a).

**G-D4. A staff decision fences the automatic paths, and is taken on a fresh provider read.**
Two parts.

- `resolve_payment_attention` first runs `settle_checkout` for the attempt, outside any lock. If the
  provider now reports a verified payment, it is credited there and the item is no longer
  actionable. Staff can record a resolution only for an attempt that is still unverified after that
  read. If the provider cannot be read, the item cannot be closed yet.
- In `reconcile_attempt`, under the attempt row lock: if `operational_resolution` is set on an
  attempt that failed unverified, no automatic outcome changes its status, the ledger or the order.
  The report is recorded (an error-level log `finance.success_after_resolution` and the event's
  result note) and the answer is `resolved_by_staff`.

`resolve_payment_attention` and `reconcile_attempt` take the same row lock, so the two serialize:
whichever commits second sees the other. A settle job that read "paid" before staff resolved is
then either applied first (staff see "already credited") or fenced (staff's own read came later and
said otherwise, so the job's read was stale). A success that arrives after a resolution means the
provider contradicted its own earlier answer about a closed checkout; that is accepted risk AR-6.
This is decision D4(b).

**G-E1. The sweep defines the obligation.** On every job cycle, each `OUTSTANDING` attempt has a
settle job that is pending or running. Where it has none, or one that is succeeded, failed or
cancelled, the sweep makes it pending. The job of an attempt with a close requested is due now. The
settle handler reports "done" only when the attempt is no longer `OUTSTANDING`. A job the sweep
re-arms after its tries ran out is due after the capped delay, not at once, so an attempt that never
verifies is read a few times a day and never in a tight loop.

**G-E2. Claim fencing, for every job kind.** `claim_due_jobs` stamps a fresh `claim_id` (a new
UUID column on `ScheduledJob`). One helper writes every completion. Each completion filters on
`pk`, `status = running` and that `claim_id`. Zero rows means the run lost its claim: it logs and
writes nothing. Every write that makes a job pending again (`requeue_stuck_jobs`, a re-arm) clears
`claim_id`. This is the one claim-ownership helper for the
job runner.

**G-E3. Intent and wake in one transaction.** `_record_close_intent` also arms the settle job,
inside the caller's transaction, taking the job row lock last as today. No caller arms separately.

**G-F1. One gate function.** `checkout_gate(...)` is a pure function over the order and its
attempt rows. `_checkout_step` calls it under the order lock and acts on its answer. `next_checkout`
calls the same function without the lock and maps the answer to a screen state. The conditions exist
once. The answers are: under review, settling, closing another checkout, opening, resume, recover,
ready.

**G-F2. On the phone, a refusal beats an older read.** The owner's checkout section and the guest
pay screen use `ReadOrder`: a refused tap disables the action and starts a new read, and only a read
that started after the refusal may enable it again.

### 6.4 What G1 removes

`_record_checkout_final`; the gate's "final but open" branch; the conditions restated in
`next_checkout`; the four unconditional completion updates in `run_job`; every separate call that
arms the settle job after a close intent.

### 6.5 Test matrix

The specification is a state table. The builder writes it as data and generates the tests from it.

**Attempt states.** S0 opening (no checkout stored, inside its window). S1 never opened (window
passed). S2 open and payable. S3 closing (close requested, provider not confirmed). S4 settling.
S5 ended locally, provider not confirmed. S6 paid. S7 ended and confirmed. S8 under review.
S9 closed by staff.

**Events.** A tap by the member who opened it. A tap by another member or a guest. A webhook:
paid and verified, paid and unverifiable, failed. The settle job's read, for each provider answer.
A close confirmed unpaid; a close refused because a payment is under way; a close that reports a
failure. Expiry. Staff resolve. Staff reconcile. The order stops collecting.

For every state and event: the next state, the answer, the ledger effect, and what the screen
offers. Then:

- **Interleavings**, each in both orders: tap and webhook; tap and job; job and staff resolve;
  job and job (a stale run finishing after a newer claim); webhook and expiry.
- **Crash points**: between every two commits of `start_checkout`, `settle_checkout` and
  `run_job`. After each, one job cycle must restore "every `OUTSTANDING` attempt has a live job".
- **Property**: for every reachable state, what the owner and guest screens offer equals what the
  gate would accept.

Mechanical checks: the check constraint; `checkout_final_at` assigned in one function; no
`ScheduledJob` completion outside the helper.

### 6.6 Done when

1. Each family in 6.1 has its invariant, one mechanism and its matrix, shown in the pull request.
2. The three round-7 blockers and three should-fix findings are tests, red before and green after.
3. Migrations are generated, `task check-drift` is clean and the regenerated contract is committed.
4. New strings exist in English, French and Arabic, with 360 px screenshots of the "being checked"
   state on the owner and guest screens.
5. All CI checks are green.

---

## 7. F1: payout availability

**Continue on `claude/f1-payout-availability`. Builder: Claude Opus, extra-high effort.**

### 7.1 Families

| Family | Where it appeared | State |
|---|---|---|
| F-A The read and the write give the same answer | Rounds 1 to 4 (about a dozen should-fix) | Closed by the shared `onboarding_refusal` |
| F-B Changing the method set against funding | Round 1 blocker, round 2 | Closed |
| **F-C An account-creation request is sent only for the declaration that is current** | Round 2 blocker; round 3 blockers 1 and 3; round 4 blocker; round 5 blocker | **Open. Five rounds.** |
| F-D An older in-memory copy written over newer account state | Round 3, round 4 (two) | Closed |
| F-E Creation identity: key, attempt, fingerprint | Round 3 blocker 2, round 4 | Closed |
| **F-F Eligibility and waiting** | Round 5 (two should-fix) | **Open. Both come from the round-5 lock.** |
| **F-G One answer per response** | Round 3, round 4, round 5 | **Open** |

### 7.2 What the code does today (checked at `bd74c3a`)

- `_plan_onboarding` locks the user row and the method row, checks the declaration has not changed
  (`_require_unchanged`), and commits a durable creation intent (`PayoutProviderOperation`, status
  `committed`) before any request to Stripe.
- `set_preference` reaches the same method row lock through `_method`, checks the revision, and
  creates a new version when the euro country changes.
- Nothing stops `set_preference` once an intent is committed. Round 5 tried to close that with
  `hold_payout_account_setup`, a session-level `pg_advisory_lock` held across the Stripe call. It
  drops if its connection dies, which is the round-5 blocker.
- `_traveler` reads eligibility without a lock, before any wait.

### 7.3 Invariants and mechanisms

**F-C. The freeze.** While a creation is outstanding for a method in this platform and mode
(`current_creation(method)` with status prepared, committed or unknown), every write to the euro
method that would change `enabled` or the country is refused with the stable code
`payout_setup_in_progress` (409). The check sits inside `_method` for EUR, under the method row
lock, so no caller can skip it.

- Intent commit and preference write already take the same row lock. One commits first and the
  other sees it: either the preference change lands first and `_require_unchanged` refuses the
  onboarding, or the intent lands first and the freeze refuses the preference change.
- After its commit the intent is a row. No connection has to stay alive. This is rule R1.
- `hold_payout_account_setup` and `lock_payout_account_setup` are deleted from
  `financial_locks.py`, with their callers.
- The freeze ends when the next onboarding call resolves the intent (replay, retrieve or search),
  or when a definite failure with no provider object is recorded. `CREATION_NOT_FOUND` waits for
  Finance, as today.
- The read model uses the same function. While the freeze holds, the euro options are shown as not
  changeable with reason `payout_setup_in_progress`, and "continue setup" is offered. This is
  decision D5.

**F-F. Eligibility is read on the locked row.** `holds_payout_setup` is evaluated on the user row
locked in the transaction of the write it guards: in `_method`, in `_plan_onboarding`, and once
more in the last transaction before the hosted link is returned. One helper locks and checks; the
unlocked `_traveler` read goes. With the advisory lock gone there is no wait between the check and
the lock, so the "no deadline on the wait" finding has nothing left to apply to.

**F-G. One snapshot per response.** Each payout GET builds one immutable set of facts (user,
methods, standing account, creation, policy) and derives every block of the response from it.
`payout_profile_api.py` and `payout_mobile.py` stop computing the euro actions separately. A
write's response is built from facts read inside its own last transaction, under its locks, never
from a later read. At the link handoff the method's current version id is compared with the version
id the call planned for; a different id is `payout_preference_changed`, even when the country
happens to match again.

### 7.4 What F1 removes

The session advisory lock and its helpers; the test that waits on it
(`test_f1_payout_account_setup_race.py`, rewritten as a row-lock test); the second computation of
the euro actions; the unlocked eligibility read.

### 7.5 Test matrix

**Durable states.** N0 no intent and no account. N1 intent committed, never sent. N2 intent
committed, request in flight. N3 ambiguous answer, inside the replay window. N4 past the window and
a search found nothing (waits for Finance). N5 definite failure. N6 standing account bound to the
current version. N7 standing account and a changed declaration. N8 standing account from another
platform or mode.

**Writers.** PATCH changing the country. PATCH switching euros off. The single-currency POST.
Onboarding from the same device. Onboarding from a second device. A refresh or webhook. A ban or a
role change.

For every state and writer: the answer code and the rows afterwards. Then:

- **Property**: in every state, each action the GET offers is accepted by its write, or refused
  only with a "changed since you read" code.
- **Real threads**, both orders: preference write and intent commit; ban and link handoff.
- **Crash points**: after the intent commit and before the request; after the request and before
  the record; after the record and before the link. In each, closing the database connection
  releases nothing that matters.

Mechanical check: no session-level advisory lock in the payout setup path.

### 7.6 Done when

1. The round-5 blocker and three should-fix findings are tests, red before and green after.
2. The matrix of 7.5 passes, and the advisory lock is gone.
3. `payout_setup_in_progress` is translated in English, French and Arabic where the app shows it.
   **[Guess]** F2 owns the screen; F1 delivers the code and the contract line.
4. All CI checks are green.

---

## 8. N1: notification permission at first open

**Continue on `claude/n1-notification-first-open`. Server fixes can be built at once. The mobile
part is rebased onto S1. Builder: Claude Opus, extra-high effort.**

### 8.1 Families

| Family | Where it appeared | State |
|---|---|---|
| N-A When the permission prompt may appear | Rounds 1 to 4 | Closed |
| **N-B A push registration belongs to one live sign-in** | Round 2 (six blockers); round 3 blockers 1 and 4; round 4 (three should-fix); round 5 (one should-fix) | **One item open** |
| N-C The phone's registration state machine | Rounds 2 to 4 | Closed. Round 5 reported nothing here |
| **N-D Ending every sign-in of an account, against issuing one** | Round 3 blockers 2 and 3; round 4 blocker 1; round 5 blocker 1 | **Open** |
| **N-E Every way the phone leaves a sign-in also ends it on the server** | Round 3 (offline sign-out); round 4 blocker 2; round 5 blockers 2 and 3 | **Open. Moves to S1** |

### 8.2 Invariants and mechanisms

**N-B. The sign-in row decides.** `end_session` writes nothing when the sign-in is not live, and
answers the same 205. A sign-out no longer carries an installation id or a sequence: ending the
sign-in switches off every device it registered, and a registration that arrives from an ended
sign-in is refused. The installation order (`PushInstallationBinding`) orders only the operations
of live sign-ins. The rule for all three operations (register, unregister, sign-out): nothing is
written to the installation order before the sign-in is known to be live, under the account lock.
**[Guess]** `register_push_device` already checks liveness before it claims a sequence; the builder
confirms it.

**N-D. A write to a user row changes only what the writer changed.** `User.save()` without
`update_fields`, on a row loaded from the database, writes only the fields whose values differ from
the loaded ones. A form or service holding an older copy can then never write back `password`,
`session_epoch`, `is_active`, `is_banned` or anything else it did not touch. This covers the
technical admin form and every other full-row save (`admin_panel/services.py`,
`accounts/social.py`, `accounts/deletion.py`, `accounts/serializers.py`) with one rule on the
model. `session_epoch` keeps one writer, `end_all_sessions`.

**N-E. Moved to S1** (S-3 and S-5). After the rebase, N1's mobile code drops `_endSignInOnServer`,
the sign-out metadata, and the early return in `auth_repository.signOut`. The test at
`phase8ff4_session_test.dart:215`, which expects no request when a sign-out is overtaken, is
rewritten to the new rule: an ended sign-in is always sent.

### 8.3 Test matrix

- **N-B**: a sign-out repeated after it was acknowledged; a sign-out for a sign-in a password reset
  already ended; A's delayed sign-out after B registered on the same installation; A's registration
  arriving after A's sign-out; each of these with S1's sender retrying.
- **N-D**: for every concrete field of `User`: a concurrent update of that field, then an older
  copy saving another field; the concurrent value survives. The technical admin form posted with
  older data after a password reset: the new password hash and the new `session_epoch` survive, and
  a sign-in checked before the reset is still refused.
- **N-E**: S1's matrix, run with N1's server.

Mechanical checks: one writer of `session_epoch`; no installation-order write before the liveness
check.

### 8.4 Done when

1. The three round-5 blockers and the should-fix are tests, red before and green after (blockers 2
   and 3 through S1).
2. The N1 branch holds no credential storage, exit or sign-out code of its own.
3. All CI checks are green, "Schema drift" included.

---

## 9. P3B: profile photos in the app

**Continue on `claude/p3b-profile-photos-app`, rebased onto S1 and then N1. Builder: Claude Opus,
extra-high effort.**

### 9.1 Families

| Family | Where it appeared | State |
|---|---|---|
| P-A A picker result belongs to the pick that opened it | Rounds 3 to 6 | Closed |
| P-B Preparing the image on Android and iOS | Rounds 3 to 5 | Closed. Round-3 item 13 becomes a device check and a follow-up |
| P-C The avatar cache | Rounds 3 to 6 | Closed |
| **P-D An action started as member A runs as member B** | Every round from 3 to 8: fourteen of the twenty blockers, by the planner's count | **Open. Moves to S1** |
| **P-E A member's write names the state it saw** | Round 7 should-fix; round 8 should-fix 1 | **Open** |
| **P-F One photo operation at a time** | Round 8 should-fix 2 | **Open** |
| **P-G A newer truth wins on the phone** | Round 3 should-fix; round 8 should-fix 3 | **Open. Uses `ReadOrder`** |

### 9.2 Invariants and mechanisms

**P-D. Moved to S1.** Round-8 blocker 1 (a tap that began on A's button ends on B's) is S-4.
Blocker 2 (A on screen with B's bearer after an interrupted save) is S-1. Blocker 3 (a name draft
and a language retry that take their authority when submitted) is S-4. The keystore error the
password screen does not show is S-2. Round-7 blockers 3 to 5, which were outside P3B (the public
profile writer, the files in the KYC form, the delete-account dialog), are closed by S1 for the
whole app.

**P-E. One version per photo slot, moved by every visible change.** An upload, the member's own
removal, a staff removal and the dismissal of a notice each move the version. Every member write
(replace, remove, dismiss) carries the version it saw. The server compares under the member lock
(`_hold_member`); a mismatch is 409 `photo_changed` with the current state in the body.
`remove_by_staff` moves the version; today it keeps it, so an old "Remove" dialog deletes the new
staff notice.

**P-F. An explicit transition table in the photo controller.** States: idle, picking, preparing,
uploading, failed, removing. Commands: pick, retry, discard, remove, dismiss. A command is accepted
or refused synchronously, before the first await, and moves the state in the same call. Each control
passes the operation or version it was drawn for; a mismatch is refused. Two taps in one frame can
then never both be accepted.

**P-G. `ReadOrder`** on the photo state and the account snapshot. A 409's fresh state cannot be
undone by an older `/api/me`.

### 9.3 What P3B removes after the rebase

Its changes to `session.dart`, `token_store.dart`, `api_client.dart` and `auth_repository.dart`
that concern credentials or account switching; `_credentialOwner`; `_settleAfterFailedSignIn`;
`beginAction()` and `MemberScope` and every call site that threads them; `_drawnFor`;
`_photoApplied`; `docs/handoff/WRONG_ACCOUNT_WRITES_FOLLOWUP.md`. Test files named by round are
regrouped by family. **[Guess]** The mobile diff shrinks by 2,000 to 3,000 lines.

### 9.4 Test matrix

- **P-E**: for each member command opened in state X, each change in between (a staff removal, an
  upload from a second device, a dismissal from a second device): 409 `photo_changed`, and the
  screen shows the current state.
- **P-F**: the full table of states and commands; every pair of commands in one frame; a command
  carrying a stale operation id.
- **P-G**: a 409 answer followed by an older `/api/me` answer; an upload answer followed by an
  older read.
- **P-D**: S1's matrix, run with the photo section on screen.

### 9.5 Done when

1. The four round-8 should-fix findings are tests, red before and green after. The three blockers
   are covered by S1's tests, run here with the photo section mounted.
2. The P3B branch holds no account-switch code of its own.
3. Screenshots in English and Arabic at 360 px for the photo states that changed.
4. All CI checks are green.

---

## 10. Order, builders, branches

### 10.1 Two lanes that run at the same time

```
Server lane:   G1  and  F1  (in parallel, separate files)   ->  C1
Phone lane:    S1  ->  N1  ->  P3B
```

- G1 and F1 share only `docs/IMPLEMENTATION_STATUS.md`. C1 waits for both, as HANDOFF 0.4 says.
- N1's server fixes (N-B, N-D) and P3B's server fix (P-E) do not wait for S1. They are built on
  their own branches while S1 is built.
- N1's and P3B's mobile parts wait for S1. N1 merges before P3B because both change the same eight
  mobile files, and N1's remaining mobile change is the smaller one.
- After these: F2, M2, A1, M3, as HANDOFF 0.4 says.

### 10.2 Builders

Claude Opus at extra-high effort for all five (decision D7). Each builder gets its section of this
plan, sections 3 and 4, and the rules of CLAUDE.md. The lead coordinates and does not code.

### 10.3 Astra runs

One prompt per package per round, built from the template in section 12. Ismail gets each prompt as
soon as its package is green in CI.

### 10.4 Follow-ups this plan creates or keeps (for HANDOFF 0.8, by the lead)

- Replaced by S1: "wrong-account writes outside profile photos".
- Kept: scheduled readiness refresh, `apps/finance/jobs.py:650` (F1 round 5).
- Kept: the four out-of-scope rows of G1 round 7 (empty currency or fractional amount; guest link
  expiry against the hosted URL; provider list against payout preflight; Chargily create
  idempotency).
- New: an iOS build in pull-request CI (P3B round 3, item 13). A cost decision.
- New: Astra's reports for G1 round 7, P3B round 8 and N1 round 5 are not yet committed under
  `docs/handoff/astra/results/`.

---

## 11. Accepted-risk register (first entries)

| # | Package | Risk | Why it is accepted | Repair |
|---|---|---|---|---|
| AR-1 | S1 | **[Guess]** On Android the secure-storage plugin can report a write done before it is on disk. If the app is killed inside that window, the last transition is lost and the phone is back in the state before it, for example still signed in after a sign-out. | Needs a kill inside a window of milliseconds. The state is consistent, because the record is one key. | Visible at next launch. The member signs out again. |
| AR-2 | S1 | A sign-in whose answer never reached the phone stays live on the server. | Exists on `main` today. Nobody holds its tokens. | It ends when its refresh token expires or the member ends all sessions. |
| AR-3 | S1 | A ninth unsent ended sign-in pushes the oldest out of the list. | Needs eight sign-outs with no network in between. | Same as AR-2. |
| AR-4 | F1 | A creation is outstanding and its country is closed by configuration: onboarding and the preference change are both refused. | A crash plus a configuration change (outside the model, 3.1 i). | Finance resolves the operation. |
| AR-5 | G1 | A payment that never verifies is read a few times a day until staff close it. | By design: it must stay in front of staff. | Staff resolve the item. |
| AR-6 | G1 | After staff closed an item on a fresh provider read, the provider later reports that same closed checkout as paid. The payment is not credited. | The provider contradicted its own answer about a closed checkout. | The error log `finance.success_after_resolution` alerts. Staff refund at the provider. |
| AR-7 | F1 | A traveler picked the wrong country and a creation is outstanding. The app refuses the change until setup continues, which creates the account in the first country. | A product limit, not a fault: a connected account never changes country. The same dead end exists today after any creation. | Support deactivates the account so a new one can be opened. |

Astra and the builders add entries here instead of fixing them in a package. Ismail sees the list
at each merge.

---

## 12. How a round runs from now on

1. The builder restates, per family: the invariant, where the one mechanism lives, the matrix
   tests. That table goes in the pull request.
2. CI is green on the branch.
3. The lead checks the table and the mechanical checks, and that nothing outside the families
   changed.
4. The lead writes the Astra prompt from this template and gives it to Ismail at once:
   - the three anti-loop rules;
   - section 3 of this plan (fault model, severity, scope, verdict rule);
   - the package's family table, with invariant and mechanism;
   - the instruction: map every finding to a family or say "outside the families"; give the fault
     sequence in the terms of 3.1; give the class from 3.2;
   - round 2 only: the round-1 findings and their fixes; re-check those and what they touched.
5. The lead verifies each finding against the code and classifies it (3.4).
6. Merge when CI is green and Astra approves, or as Ismail decides at a stop.

---

## 13. Guesses and what was not checked

- **[Guess]** The provider-container swap of S-4 is feasible with the current router, plugins and
  test harness. Not prototyped.
- **[Guess]** The Android secure-storage write returns before the disk write (AR-1). Taken from a
  comment on the P3B branch (`pending_pick_store.dart`), not from the plugin's source.
- **[Guess]** Sizes: S1 at 1,200 to 2,000 lines; P3B shrinking by 2,000 to 3,000.
- **[Guess]** `register_push_device` checks that the sign-in is live before it claims a sequence.
- **[Guess]** P3B would need a new server switch to merge switched off; F1 and N1 already have one.
- **[Guess]** F2, not F1, owns the screen that shows `payout_setup_in_progress`.
- **[Guess]** No finance console screen needs a change for G-D4; the existing error log and event
  note are the alert.
- Families marked "Closed" were not re-verified. They are closed because Astra's latest report on
  each package raised nothing in them.
- No test was run for this plan. No code was changed.

---

## Appendix A. The latest findings, each mapped to a family and a mechanism

Astra's reports for G1 round 7, P3B round 8 and N1 round 5 are not committed yet. This table
restates each finding of the four latest reports.

| Package | Finding | Where | Family | Mechanism |
|---|---|---|---|---|
| F1 r5 | Blocker: the intent is committed, the database connection dies while the request to Stripe is still being sent, the session lock drops, a DE preference commits, and the FR creation is still sent | `payout_accounts.py:1039`, `payout_profiles.py:144` | F-C | Freeze |
| F1 r5 | Should-fix: waits on the advisory lock have no deadline | `financial_locks.py:367,387` | F-F | The lock is deleted |
| F1 r5 | Should-fix: eligibility is not checked again after the wait, nor at the link handoff | `payout_accounts.py:1024`, `payout_profiles.py:77` | F-F | Eligibility on the locked row |
| F1 r5 | Should-fix: one GET computes the euro actions twice | `payout_profile_api.py:299`, `payout_mobile.py:103` | F-G | One snapshot per response |
| F1 r5 | Outside F1: scheduled readiness refresh | `jobs.py:650` | none | Follow-up |
| G1 r7 | Blocker 1: an unverified payment does not stop a new checkout; the owner's app says nothing was charged | `services.py:1413,1630,1860,2054` | G-D | G-D2, G-D3 |
| G1 r7 | Blocker 2: a stale worker's completion overwrites a re-armed job | `jobs.py:1019,1079,1194`, `services.py:2184,2217` | G-E | G-E2, G-E1 |
| G1 r7 | Blocker 3: staff resolve while the settle job is mid-read; the late success is applied | `services.py:2032,2047,2697`, `operations.py:310` | G-D | G-D4 |
| G1 r7 | Should-fix: Chargily's close learns "failed" but reports only "closed"; the attempt is final and `processing` forever | `providers/chargily.py:391`, `services.py:2081,1622,1977` | G-D | G-D1 |
| G1 r7 | Should-fix: the close intent and the job wake commit separately | `services.py:1653,1835,1858,2209` | G-E | G-E3, G-E1 |
| G1 r7 | Should-fix: an older successful read re-enables a refused action | `guest_pay_screen.dart:83,194`, `checkout_section.dart:410,521` | G-F | G-F2, G-F1 |
| G1 r7 | Outside G1: four rows | see 10.4 | none | Follow-up |
| P3B r8 | Blocker 1: pointer down on A's Dismiss, B is published, the release runs B's callback | `profile_screen.dart:99`, `profile_photo_section.dart:175`, `primitives.dart:615` | P-D | S-4 |
| P3B r8 | Blocker 2: an interrupted credential save leaves A on screen with B's bearer; the overtaken clear is the same | `token_store.dart:134`, `session.dart:530` | P-D | S-1, S-2 |
| P3B r8 | Blocker 3: the name draft and the language retry take their scope when submitted | `account_name_screen.dart:118`, `language_screen.dart:148`, `session.dart:689` | P-D | S-4 |
| P3B r8 | Should-fix: a staff removal keeps the version, so an old Remove dialog deletes the new notice | `photos.py:393,436` | P-E | Version moves on every change |
| P3B r8 | Should-fix: Retry and Discard in the same frame | `profile_photo_section.dart:305`, `profile_photo_state.dart:464` | P-F | Transition table |
| P3B r8 | Should-fix: a 409's fresh state is undone by an older `/api/me`; previews are stale | `profile_photo_state.dart:497`, `session.dart:740` | P-G | `ReadOrder` |
| P3B r8 | Should-fix: a keystore error is not shown by the password screen | `session.dart:492`, `sign_in_screen.dart:70` | P-D | S-2 typed error |
| P3B r8 | Partly fixed: round-3 item 13, native fixture and iOS build in CI | native code, CI | P-B | Device check and follow-up |
| N1 r5 | Blocker 1: the technical admin's full-row save writes back the old password hash and `session_epoch` after a reset | `accounts/admin.py:25`, `accounts/sessions.py:57` | N-D | Changed-fields rule on `User.save()` |
| N1 r5 | Blocker 2: a sign-out overtaken by another sign-in returns without sending; a test expects no request | `auth_repository.dart:184`, `session.dart:399`, `phase8ff4_session_test.dart:215` | N-E | S-2, S-5 |
| N1 r5 | Blocker 3: a 429 on the launch `/api/me` clears credentials; the server sign-in and the push device stay on | `session.dart:303`, `api_exception.dart:114`, `config/settings/base.py:196` | N-E | S-3 |
| N1 r5 | Should-fix: a repeated sign-out of an ended sign-in still advances the installation order | `accounts/sessions.py:85`, `notifications/push.py:790`, `test_push.py:596` | N-B | The sign-in row decides |
