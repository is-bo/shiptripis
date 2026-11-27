# Wassla: plan to finish the open work and clean the code

**Status:** revision 3, 27 November 2026. Written under the ponytail rules (`CLAUDE.md`, "Working
style: ponytail"). Nothing here is built yet.
**History:** revision 1 was commit `b295f3a`, revision 2 was `e66bb5b`. Astra reviewed revision 1
and asked for changes. Ismail stopped Astra's re-check of revision 2 and asked for this revision:
smaller mechanisms, every follow-up as a package, a cleanup of the whole code, and builders who
work to it.
**Next:** Ismail answers the five questions of section 2. Then the lead hands out the briefs in
`docs/handoff/builders/`, in the order of section 9.

Guesses are marked **[Guess]**. Everything else was checked against the code: `main` at `b4b838f`
for the audit, and the four pull-request heads listed in section 1.

---

## 0. Summary for Ismail

The work has four parts.

- **Part A. Finish the four open packages** (P3B, G1, F1, N1) and one new small package for the
  phone's sign-in (S1). Revision 2 answered every rare case Astra could name. This revision keeps
  one mechanism per problem and drops the rest. Eleven mechanisms of revision 2 are gone
  (section 5.7).
- **Part B. The follow-ups.** Every problem that reviews found outside a package is now a package,
  folded into one, or closed with the reason (section 6).
- **Part C. Clean the code.** The server still carries a whole earlier version of the product: old
  payment, wallet, handover and trip code, kept only because of the rule "no table is dropped".
  Removing it is the largest cleanup by far. Then the unused code, on the server and in the app,
  and the stale files and branches (section 7).
- **Part D. One audit of each area, then the phone test.** A reader goes through each of the six
  areas once, with ponytail's audit rules, and what it finds is fixed once. Then the app goes to
  your phone (section 8).

**What you get at the end:** the four packages merged, no known open problem, the old product
version gone from the code and the database, no unused code that a tool or a reader can find, and
a list of what was accepted on purpose (section 10).

**What I did not plan, on purpose:** rewriting large files only because they are large, a reset of
the database migration history, and an iPhone build on every pull request. Section 7.5 says why.

---

## 1. What I found

### 1.1 The four packages

| Package | Original task | Rounds | Size now | Latest result |
|---|---|---|---|---|
| P3B #66 | Profile photos in the app | 8 | +14,865 lines, 138 files | Reject at `7727b19` |
| G1 #67 | Guest payment page without the browser-session check | 7 | +7,285 lines, 67 files | Reject at `57684cb` |
| F1 #69 | Show payout availability and actions | 5 | +4,189 lines, 37 files | Reject at `bd74c3a` |
| N1 #71 | Ask for notification permission once | 5 | +6,068 lines, 83 files | Reject at `3e7fc17` |

Why the rounds did not end: nothing written said what "done" means, so every reachable sequence
became a blocker; each fix added a mechanism, and each mechanism gave the next round something new
to find; one rule was written in two places (G1's gate and its screens); and on the phone, "who is
signed in" was read when a request was sent, not when the member acted.

### 1.2 The whole code (audit of `main`)

| Part | Size | What stands out |
|---|---|---|
| Server (Django) | 642 files, 191,780 lines | The earlier product version is still there: models and tables of `apps.payments`, `apps.wallet`, `apps.verification`, the old `Trip`, `ProductRequest`; branches for old `schema_version` values; about 190 "legacy" markers in 40 files |
| Server, unused code | 23 candidates | Classes, functions and properties nothing calls, or only a test calls (list in brief DC) |
| Server, large functions | 59 above the usual complexity limit | The largest, `evaluate_compatibility` (645 lines), mixes old and new schema versions. It shrinks when the old versions go |
| Go services | 71 files, 17,897 lines | Small. A few leftover keys and comments. An unused-code tool was not run (section 11) |
| App (Flutter) | 166 files, 103,681 lines, 37,976 of them generated | No unused file. About 40 "legacy" markers. Three screens above 1,900 lines |
| Repository | 238 document files, 19 remote branches | Files of earlier tools and an old two-owner task list at the root; branches nobody uses |

Three privacy points from the older findings were checked: parcel photos are stored exactly as
uploaded, so a photo keeps its GPS position (`apps/parcels/views.py`, `_store_image`); the journey
payload carries the traveler's full name (`apps/trips/serializers.py`, `traveler_name`); "own-card
labels" is described nowhere in the repository.

---

## 2. Decisions for Ismail

Five questions. Each has a recommendation. Everything else in this plan is technical and decided.

| # | Question | Recommendation |
|---|---|---|
| D1 | **Reviews.** One Astra pass per pull request that changes money, sign-in or staff rules. Only a Blocker (section 3.3) stops a merge. A smaller finding is fixed when the fix is in one place and adds nothing new; otherwise it goes on the follow-up list. A package that only deletes code is proven by tests and checked by a second Claude reader, not by Astra. | Yes |
| D2 | **Payment "being checked" (G1).** While a payment on an order is being checked, the order takes no new payment. The hold ends by itself when the provider confirms the payment or confirms that no money was taken. Otherwise Finance ends it, with a reason: "no money was taken" or "money returned", with the provider's reference. A payment that appears after Finance closed the item holds the order again and is never credited by itself. | Yes |
| D3 | **Payout setup (F1).** While a Stripe account is being created for a traveler, the app refuses a change of payout country: "setup in progress". A creation that is still unclear after 23 hours, with no account found at Stripe, starts again by itself. Today it waits for Finance, who have no button for it. | Yes |
| D4 | **Remove the earlier product version, tables included.** The old payments, wallet, handover codes, old trips, Kaba product requests, the old schema versions and the "legacy" money markers: code, tests, database tables and columns. `CLAUDE.md` says a table is dropped only in a cleanup you approved. This approval covers packages L1 to L4 only. The test server's demo rows in those tables go with them. | Yes |
| D5 | **Staff rights in one place.** In the technical admin, "staff", "superuser", groups, permissions and "active" become read only, as the ban already is. They change only in the console, with a reason and an audit row. | Yes |

Decided here, for your information:

- **Payouts on (O4)** stays as you decided: after F1 merges, with your OK at that time. I withdraw
  my earlier proposal to wait for F1b. F1b is needed only before Stripe Connect opens beyond the
  France-only test (section 6).
- **Push text.** Revision 2 asked whether push text should become neutral for a shared phone. I
  read every push text (`apps/notifications/push.py`): each is a fixed line such as "Payment
  received", with no name, amount or message text. Nothing needs to change, so the question and
  its package are withdrawn.
- **Builders** are Claude Opus, at the effort section 9 gives. Claude Sonnet at high effort does
  the one package that touches no rule (repository files).
- **Astra's re-check of the plan is dropped.** Its first review is kept in
  `docs/handoff/astra/results/loop-end-plan-astra-result.md`.

---

## 3. How the work is done

### 3.1 Working rules

Every builder works in ponytail mode and follows `docs/handoff/builders/README.md`. In short:

- The smallest change that fully solves the problem. In money, payout, codes, sign-in, staff
  authority, matching and location code there is no shortcut.
- **Mechanism budget.** A builder adds no lock, counter, flag, column, job kind, retry loop or
  helper class that its brief does not name. If one seems needed, the builder stops and asks.
- A package removes what it replaces, in the same pull request.
- Every case a brief lists under "Tests" is tested. A finding is first reproduced as a failing
  test.
- Before handing back, the builder runs `/ponytail-review` on the whole change.

### 3.2 What a review finding may assume

**Ordinary use, in any combination:** a second tap, a retry, two devices, a phone handed to the
next member, the app closed or sent to the background, a staff member doing an allowed action, a
webhook or a job delivered twice, a worker that was presumed dead and resumes.

**One fault:** one crash (a worker, a database connection or the app); or one lost, delayed or
repeated message; or one provider outage or unclear answer; or one failed write or read on the
phone.

**Outside:** a second independent fault; a malicious staff member; a compromised server, database
or provider; a signing-key change; data, URLs, jobs or app versions from before the package (the
app has never been live); a worker paused longer than a provider keeps an idempotency key (about
24 hours).

### 3.3 What blocks a merge

A **Blocker** is a concrete sequence inside 3.2 that ends in one of these:

| Class | Meaning |
|---|---|
| **M** money | Two payers for one obligation, or one payer debited twice. A debit that Finance cannot see. A credit or a payout that should not happen. |
| **A** authority and privacy | Someone reads or changes what belongs to another account. A hidden location, a delivery code or a tracking number leaks. Private data reaches an audience it was not given for. |
| **C** credentials | After the server ended a sign-in, a refresh, a push registration or a queued push for it still succeeds. An access token already issued works until its own expiry (5 minutes) plus the 30 seconds of leeway. |
| **L** lock-out | A member, an order or a setup is stuck, with no path in the app and no staff action that can be executed. |

Everything else is a **Should-fix** (a visible wrong result) or **not a finding** (no wrong
result). A problem that is the same on `main` without the package is **outside**: it goes on the
follow-up list and does not block. The three anti-loop rules of `docs/handoff/COORDINATOR.md`
section 3 stay in force.

### 3.4 Review of one package, and when it stops

1. The builder hands back with the evidence table and the `/ponytail-review` verdict.
2. CI is green. The lead runs the gate of `CLAUDE.md`: every "Done when" line, nothing outside
   the brief.
3. **One independent pass.** For F1, F1b, G1, N1, S1 and S2: Astra, with a prompt that carries
   sections 3.2 and 3.3, the brief, the diff and the evidence. For L2 and L3: a second Claude Opus
   agent with `/ponytail-review` and the proofs of 3.5. The other packages need no second pass.
4. A Blocker is verified against the code by the lead, fixed by the builder, and re-checked once,
   the fix only. A Should-fix is fixed when it is a build gap or a one-place fix that adds no
   mechanism; otherwise it goes on the follow-up list.
5. **Stop.** If the re-check still shows a Blocker, or a fix needs a mechanism the brief does not
   name, work on the package stops. The planner revises that one rule once, or Ismail chooses:
   cut the capability, switch it off on the server, or accept the risk in writing.

### 3.5 Proof for a package that deletes

- An inventory before any deletion: each item with the search that shows nothing live uses it
  (code, tests, fixtures, templates, settings, strings, dynamic references).
- The whole suites are green. A test goes only together with the code it tested, and the pull
  request lists it with the surface it covered.
- `backend/contracts/sql/schema.sql` changes only by the listed drops.
- No field the app reads leaves a payload: each removed field is searched in `mobile/lib`.
- Where a rule's code changes shape (matching in L2, money reports in L3): a differential test
  runs the old and the new code on generated current data and compares the full results. It is
  evidence in the pull request, and it is deleted with the old code in the last commit.

---

## 4. Design rules

| # | Rule | Replaces |
|---|---|---|
| R1 | Across a provider call, the only lock is a row. No transaction is open during a provider call. | F1's advisory lock |
| R2 | An intent is committed before its effect, in the same transaction as what must follow it. | G1's close intent and job wake in two transactions |
| R3 | An obligation is a predicate on rows, enforced by a sweep on every job cycle. | G1's "arm only on the way in" |
| R4 | A job run owns its claim. A completion is written only if the claim is still its own. | `run_job`'s unconditional updates |
| R5 | Automatic paths obey what staff recorded, read under the row lock. A staff decision about money is committed with its audit row. | G1's late success after a staff resolution |
| R6 | One decision function per rule. The write path and the read path both call it. | G1's `_checkout_step` and `next_checkout` |
| R7 | On the phone, authority is bound when an action starts: the API client belongs to one sign-in. | P3B's per-call scope checks |
| R8 | A state that must never exist cannot be stored (a constraint, one record, one writer). | Three credential keys; "final" without a terminal status |
| R9 | On the phone, each resource has one owner that reads it. A change, whatever it answered, makes the owner read again. Nothing else writes the resource. | `_photoApplied`; screens set from several answers |

**R9 needs no new helper.** A Riverpod provider that is rebuilt drops the result of its earlier
build, so an older read cannot replace a newer one. **[Guess]** The builder proves it with one
test per resource (two reads answered in reverse order). If it does not hold, the fallback is one
request counter inside that provider. The `ReadOrder` class of revision 2 is not built.

---

## 5. Part A: finish the open packages

Each package's details, files, tests and "Done when" are in its brief. This section states the
rules and why each mechanism is the smallest one.

### 5.1 F1: payout availability (brief F1)

| Rule | Mechanism |
|---|---|
| F-C. A Stripe account is created only for the declaration that is current | **The freeze.** While a creation can still produce an account, `set_preference` refuses a change of the euro country or of "euros enabled" with `payout_setup_in_progress`. Intent and preference take the same row lock, so one sees the other. The advisory lock and its helpers are deleted. |
| Overlapping calls | A call that finds its rows changed under it starts again from fresh rows, once. Two callers send the same idempotency key, so Stripe creates one account. |
| A creation that stays unclear | After the 23-hour replay window the call lists the accounts created around the request, every page. One match is recorded and bound. No match ends the creation as failed, and the next call starts a fresh one. The state "requires Finance review" goes. |
| F-F. Eligibility | One function (active, not banned, traveler role, confirmed email), read on the locked user row at the two write entry points and once more before the hosted link is returned. |
| F-G. One answer per response | The euro actions are computed once per response, inside the existing `consistent_read()`. |

### 5.2 G1: guest checkout and the payment attempt (briefs G1-A, G1-B, G1-C)

| Rule | Mechanism |
|---|---|
| G-D. Every reported payment is accounted for before the order collects again | `checkout_final_at` is written by one function, in the same statement as a terminal status, with a check constraint. "Verified" is one function (whole minor units, same amount, same currency). Three predicates, stated once: can still collect, held, outstanding. The gate refuses while a payment is held (`payment_under_review`). A hold ends as decision D2 says. |
| G-E. The obligation to follow a checkout cannot be lost | The sweep arms a settle job for every outstanding attempt. One helper writes every job completion, filtered on the claim's own `locked_at`, so a stale worker writes nothing. No new column. The close intent arms the job in the same transaction. |
| G-F. Screens offer what the gate allows | One pure function `checkout_gate(facts)`, called by the write path under the lock and by the read path. `next_checkout`'s own conditions are deleted. On the phone, rule R9. |

### 5.3 N1: notification permission and sign-in sessions (brief N1)

| Rule | Mechanism |
|---|---|
| N-B. A push registration belongs to one live sign-in | Ending a sign-in that is not live writes nothing. A sign-out carries no installation id and no sequence: ending the sign-in switches off every device it registered. |
| Sign-out contract | `POST /api/auth/sign-out` with a refresh token and no bearer answers 205 when that sign-in has ended, now or earlier, also for an expired or rotated token or a deleted account. It answers 400 `sign_out_proof_invalid` when the token cannot be verified. |
| N-D. Credentials and privileges have named writers | One function sets a password and ends every sign-in. Every save of an existing user names its fields, the technical admin included (it saves only what the form changed). Staff rights are read only in the technical admin (decision D5). A scan test fails on a save without named fields. |
| N-F. A queued push belongs to its sign-in | The queued push carries the sign-in that registered the device, and the worker's last check compares it. |

### 5.4 S1: session core on the phone (briefs S1-A, S1-B), after N1

P3B's "an action started as member A runs as member B" (fourteen of its twenty blockers) and N1's
"the phone leaves a sign-in the server still holds" have one root: the phone's session is several
pieces changed at different moments and removed in four places.

| Rule | Mechanism |
|---|---|
| S-1. One record, one writer | Who is signed in, and the sign-ins whose end the server has not confirmed, are one stored document under one key. One object, `SessionCore`, writes it: storage first, then memory. One Flutter engine (`singleTask`). |
| S-2. One transition at a time | A sign-in attempt is reserved before any await and ends with its answer or its timeout. There is no step from member A to member B: B starts from signed out. |
| S-3. One exit | Credentials leave only through `end(sid, reason)`: the member signed out, the server refused the current refresh token, or the account was deleted. A 429, 403, 404, 5xx, timeout or offline answer never ends a session. A record that cannot be read is never written over while the app is in the background (an iPhone's storage is closed until its first unlock). If it still cannot be read with the app open on screen, the member is signed out and the phone deletes its push token. |
| S-4. The member's screens end with the session | A `MemberBoundary` above the app owns the provider container. At `end` it disposes the container and builds a new one. The API client is built for one sign-in and gets no token once that sign-in has ended. |
| S-5. The server hears about every ended sign-in | The core posts each ended sign-in with its own refresh token: at once, at launch, and when the app returns to the foreground. An entry leaves the list only on 205 or `sign_out_proof_invalid`. |
| S-6. Newer truth wins | The account snapshot follows rule R9. |

### 5.5 P3B: profile photos in the app (briefs P3B-A, P3B-B), after S1

| Rule | Mechanism |
|---|---|
| P-D. Account switching | Moved to S1. P3B deletes its own account-switch code. |
| P-E. A write names the state it saw | A staff removal changes the photo's `version`. Every member write on an existing photo row carries the `version` it saw; a mismatch is the existing 409 `profile_photo_changed`. No new column. |
| P-F. One photo operation at a time | A command is accepted or refused before the first await. The photo controls are keyed by the `version` they show, so a change under a held finger ends the gesture. |
| P-G. A newer truth wins | The member's own photo has one owner, the account snapshot (R9). A success and a 409 both make it read again. |

### 5.6 Order inside Part A

F1 and G1 run side by side. N1, then S1, then P3B, because all three change the same phone files.
S1-A starts from the N1 branch. **[Guess]** That is easier than a late merge; the lead may wait
for N1 to merge instead.

### 5.7 What revision 3 drops from revision 2, and why

| Dropped | Why it is not needed |
|---|---|
| The native "flush" method and the device kill test (S1) | Android completes a pending storage write when the app is paused or stopped. What is left is a crash in the instant after a tap. The member sees it and repeats. Accepted risk AR-3. |
| The start screen for an unreadable record, with "sign in again on this phone" (S1) | One rule does the same without a button: a record that cannot be read while the app is open on screen means signed out. In the background the app waits. AR-4. |
| The wait for the first frame before a sign-in, and the cancelled-attempt handling (S1) | The old tree has no sign-in control. An attempt ends with its answer or its timeout. |
| Clearing shown notifications at sign-out (S1) | Every push is already a fixed line with no name, amount or message text, so a shown one tells the next holder of the phone nothing private. |
| The `ReadOrder` class (G1, S1, P3B) | The framework already drops an older read (R9). |
| The provider read inside the staff action, and the staff-only "no money was taken" proof (G1) | The settle job already reads the provider and releases the hold itself. Staff record what they saw, with a reason and an audit row. |
| The `claim_id` column (G1) | `locked_at` is already written at every claim and differs between claims. |
| The "binding successor" rule and the pre-send re-read (F1) | "Start again once from fresh rows" gives the same answers. The idempotency key already makes a repeated send harmless. |
| The "waiting for support" state and the "settle a creation" staff action (F1, F1b) | A complete listing at Stripe answers the question without a person. |
| The `revision` column and the `empty` row state (P3B) | The one harmful case is a staff removal that keeps `version`. Changing `version` there closes it. |
| Forms that carry what staff saw (N1) | Saving only the changed fields closes the reported case. Privileges leave the technical admin (D5). What remains is AR-6. |
| Sections 12 and 14 and Appendix B of revision 2 | They served the exchange with Astra about the plan. |

---

## 6. Part B: the follow-ups

Every finding that a review placed outside its package, and the older open findings of
`HANDOFF.md` 0.7 and 0.8.

| Finding | Where it came from | What happens |
|---|---|---|
| Wrong-account writes outside profile photos | P3B round 7 | **Closed by S1.** |
| An account opened for the wrong country has no way out | Revision 2 | **Package F1b**: one staff action, "retire a Stripe payout account". Needed before Stripe Connect opens beyond the France-only test. |
| The scheduled readiness refresh can send an old platform's account id | F1 round 5 (`apps/finance/jobs.py`) | **In F1b**: the job uses the same guard as the member's calls. |
| A lost answer to a token refresh signs the member out | Revision 2; the same on `main` | **Package S2**: the server accepts the previous refresh token until the new one is first used. |
| Push text on a shared phone | Astra's plan review | **Closed, no case.** Every push is a fixed line with no name, amount or message text (`apps/notifications/push.py`). |
| Parcel photos keep their GPS position | `HANDOFF.md` 0.7 | **Package PV**: every stored image is written again from its pixels. |
| The traveler's full name on the journey payload | `HANDOFF.md` 0.7 | **Package PV**: first name for anyone but the owner and staff. |
| "Own-card labels" | `HANDOFF.md` 0.7 | **Package PV**, once someone can say what is wrong. No description exists; with no case it is closed. |
| The rails a screen offers against the payout preflight | G1 round 7 | **In C1**, which owns that rule. The lead adds the line to C1's builder instructions. |
| A guest link that expired while its hosted page still works | G1 round 7 | **Closed, no case.** A tap on the new link goes through G1's gate, which closes the old checkout first. |
| Chargily creates a second checkout after a timeout | G1 round 7 | **Closed, no case.** The first address was never given to anyone, and it expires. |
| An empty currency or a fractional amount | G1 round 7 | **Closed by G1** ("verified" is one function). |
| An iPhone build on every pull request | P3B round 3 | **Not built.** It costs about ten times a Linux run. The existing "Build iOS" workflow runs once before the phone test, with Ismail's OK. |
| Astra's reports for G1 round 7, P3B round 8 and N1 round 5 are not in the repository | Revision 2 | **Closed.** Appendix A restates each finding, and the reports are on the pull requests. |

After Part A the queue of `HANDOFF.md` 0.4 continues as planned: C1, F2, M2, A1, M3.

---

## 7. Part C: clean the code

### 7.1 The earlier product version (packages L1 to L4, decision D4)

`docs/WASSLA_L1_CLEANUP_INVENTORY.md` (11 November) removed the old routes and kept the rest only
because no table could be dropped. It named this "a candidate follow-up that needs Ismail to lift
the rule".

| Package | What goes | Starts |
|---|---|---|
| **L1** | The models and tables of `apps.payments`, `apps.wallet` and `apps.verification`, their admin pages and tests, and the old chat eligibility that reads `PaymentIntent` | Now |
| **L2** | The old `Trip` and `TripMedia`, `Journey.legacy_trip`, `Place.legacy_airport`, `ProductRequest` and its "retired" branches, and every `schema_version` branch in parcels, trips, matching, discovery, finance, boosts, deals and disputes. A column that can hold only one value is dropped | After PV |
| **L3** | The "legacy" money markers: `is_legacy` on deals and terms, the `legacy_dzd` economics version, `LEGACY_DZD_FIELDS`, the "legacy / unknown" cohort in the finance pages and exports, `legacy_classification`, the `report_payout_legacy` command | After G1 and F1 |
| **L4** | The other compatibility code: the old admin-group mapping, `core/historical_admin.py`, the bare-array pagination, the old chat page API, leftover keys in the Go notification and email services | After N1 |

The dead apps keep an empty shell with their migration files, because older migrations of other
apps name them. Nothing else of them stays.

### 7.2 Unused code (packages DC and MC)

- **DC, server and Go.** The 23 candidates of the audit, each confirmed by a search before it
  goes. Then the same scan again on the code as it is after L1 to L4 and after the features.
- **MC, the app.** The "legacy" markers, then the identifier sweep and the translation-key sweep
  that package L1B used on 11 November. After the last app feature merges.

### 7.3 Repository files and branches (package H1)

Stale files at the root and in `docs/` (the old two-owner `TASKS.md`, the progress report PDF,
files of earlier tools in `backend/services/`, an empty `package.json` if nothing reads it, old
note folders). The builder lists each with its evidence. Branches: the builder lists the nineteen
remote branches with their state, and **Ismail approves the list before any branch is deleted**.
`main-old` stays. At the very end, this plan and its briefs are deleted too; git keeps them.

### 7.4 Complexity

The complexity this plan removes is named: four exits from a session become one (S1); a rule
written twice becomes one function (G1); a lock that depends on a connection becomes a row (F1);
two schema versions become one (L2). After L2, `evaluate_compatibility` is measured again. A
function is split only when it still mixes jobs, and never by line count. The area audits of
Part D report what remains, each with a concrete case.

### 7.5 Not done, and why

- **Large files are not rewritten for their size.** `console_views.py` (4,505 lines),
  `finance/services.py` (3,524) and three app screens are large and work. Moving code changes
  nothing for a user and risks much. They are split only where a package must change them.
- **The migration history is not reset.** It would give a tidier folder and needs the test
  server's database rebuilt. Normal migrations drop the tables safely.
- **No new checker is added to CI.** The scans are run by the builders. CI already runs the
  linters of all three languages.

---

## 8. Part D: one audit of each area, then the phone test

When Parts A to C are merged, six readers each audit one area with `/ponytail-audit` (brief
AUDIT): money; deals, codes and disputes; accounts, sign-in, notifications and chat, with the Go
services; listings, matching and location; the staff console; the app. Each report has at most
twenty findings, each with a concrete case, ranked. Each says what it did not read.

The planner turns the "must fix" and the one-place "should fix" findings of an area into at most
one fix package. There is one pass per area and no second audit. What is left goes on a written
list for Ismail.

Then, each step with Ismail's OK: deploy the reviewed `main` to the test server, build the app,
and run the phone test. It includes the device checks of P3B (prepare the same photo twice, on
Android and iPhone), of N1 (the permission prompt) and of S1 (sign out, close the app, open it).

---

## 9. Order, builders and branches

```
Money:      F1 -> F1b                      L3 (after G1 and F1) -> C1 -> F2
            G1-A -> G1-B -> G1-C
Sessions:   N1 -> S1-A -> S1-B             S2 and L4 (after N1)
Photos:     (after S1) P3B-A -> P3B-B      then M2, A1, M3, and MC last
Cleanup:    PV -> L2;  L1;  H1             DC after the features
Last:       AUDIT x 6 -> fix packages -> phone test
```

Seven builders can start at once: F1, G1-A, N1, S1-A, PV, L1 and H1. If usage is short, the
first four come first.

| Brief | Does | Branch | Starts after | Builder |
|---|---|---|---|---|
| F1 | Payout availability | `claude/f1-payout-availability` | Decisions | Opus, extra high |
| F1b | Retire a Stripe account; job guard | new | F1 merged | Opus, extra high |
| G1-A | Held payments and finality | `claude/g1-guest-checkout-csrf` | Decisions | Opus, extra high |
| G1-B | Jobs | same | G1-A | Opus, extra high |
| G1-C | Gate and screens | same | G1-B | Opus, extra high |
| N1 | Sign-in sessions, push ownership | `claude/n1-notification-first-open` | Decisions | Opus, extra high |
| S1-A | Session record and core | new, from the N1 branch | Decisions | Opus, extra high |
| S1-B | Member boundary and screens | same | S1-A | Opus, extra high |
| S2 | Refresh survives a lost answer | new | N1 merged | Opus, extra high |
| P3B-A | Rebase on S1, remove own session code | `claude/p3b-profile-photos-app` | S1 merged | Opus, high |
| P3B-B | Slot rule, controller, one owner | same | P3B-A | Opus, high |
| PV | Image metadata, names | new | Decisions | Opus, high |
| L1 | Dead apps | new | D4 yes | Opus, high |
| L2 | Old trips, product requests, schema versions | new | PV merged, D4 yes | Opus, extra high |
| L3 | Legacy money markers | new | G1 and F1 merged, D4 yes | Opus, extra high |
| L4 | Other compatibility code | new | N1 merged, D4 yes | Opus, high |
| DC | Unused code, server and Go | new | L1 to L4 and the features | Opus, high |
| MC | Unused code, app | new | The last app feature | Opus, high |
| H1 | Repository files and branches | new | Decisions | Sonnet, high |
| AUDIT | One area audit, six times | none (report only) | Parts A to C | Opus, extra high |

One builder at a time per branch. A new branch starts from the tip of `main`. The lead coordinates
and does not code.

---

## 10. Accepted risks

| # | Package | Risk | Why it is accepted | Repair |
|---|---|---|---|---|
| AR-1 | S1 | A sign-in whose answer never reached the phone stays live on the server. | The same on `main`. Nobody holds its tokens. | Its refresh token expires. |
| AR-2 | G1 | A payment that never verifies is read a few times a day until Finance closes it. | By design: it stays in front of Finance, and the order stays held. | Finance records the outcome. |
| AR-3 | S1 | The app crashes in the instant after a sign-in or a sign-out, before the phone's storage reached the disk: it restarts in the earlier state. | A crash in a window of milliseconds. If the server already heard the sign-out, the leftover tokens are refused. | The member sees it and repeats the step. |
| AR-4 | S1 | The stored record cannot be read with the app open: the phone signs out, and the sign-ins it held are not ended on the server. | A storage fault. The phone deletes its push token, so none of them can show a push there. | Their refresh tokens expire. |
| AR-5 | S1 | Tokens are issued, the phone's storage refuses the write, and the sign-out sent from memory fails too: that sign-in stays live. | Two faults at once. Nobody holds its tokens after the app closes. | Its refresh token expires. |
| AR-6 | N1 | An old open form in the technical admin can write back a verification flag or a role that changed after the form was opened. | Only a technical admin can do it, and Django's admin history shows it. Privileges are not affected (D5). | The flag is set again. |
| AR-7 | F1 | A Stripe listing that shows two accounts for one creation leaves that creation unclear, with no automatic way out. | It cannot happen by construction: one creation has one key. It is logged. | A developer looks at it. |
| AR-8 | P3B | Two devices of one member upload to an empty photo slot: the last one wins. | Both are the member's own choice. | The member uploads again. |

---

## 11. Guesses and what was not checked

- **[Guess]** A rebuilt Riverpod provider drops its earlier build's result (R9). Fallback named.
- **[Guess]** Replacing the provider container at the app root works with `go_router`, the push
  coordinator and the plugins in use. Not prototyped. If it does not, the builder stops and asks.
- **[Guess]** Stripe's list of accounts by creation time is complete 23 hours after a request, and
  a create can succeed only while its idempotency key is kept.
- **[Guess]** Two claims of one job never carry the same `locked_at`. Fallback: one `claim_id`
  column.
- **[Guess]** Both payment providers state a currency in a success answer or in the read after it.
- **[Guess]** The console has an audited action for each staff right that becomes read only (D5).
- **[Guess]** Android completes a pending storage write when the activity stops.
- The audit lists are scans. Each item is confirmed by its builder before it is removed.
- **Not checked:** unused Go code (the tool could not be run here); unused app identifiers (no
  Flutter here); speed and query counts (nothing was measured); whether the console's finance
  pages repeat each other. All four are in the area audits of Part D.
- Families that Astra's latest reports called closed were not verified again.
- No test was run for this plan. No code was changed.

---

## Appendix A. The latest findings, each with its rule

Builders reproduce their package's rows as failing tests first.

| Package | Finding | Where | Rule |
|---|---|---|---|
| F1 r5 | Blocker: the intent is committed, the database connection dies while the request to Stripe is being sent, the session lock drops, a DE preference commits, and the FR creation is still sent | `payout_accounts.py:1039`, `payout_profiles.py:144` | F-C, the freeze |
| F1 r5 | Should-fix: waits on the advisory lock have no deadline | `financial_locks.py:367,387` | The lock is deleted |
| F1 r5 | Should-fix: eligibility is not checked again at the link handoff | `payout_accounts.py:1024`, `payout_profiles.py:77` | F-F |
| F1 r5 | Should-fix: one GET computes the euro actions twice | `payout_profile_api.py:299`, `payout_mobile.py:103` | F-G |
| G1 r7 | Blocker 1: an unverified payment does not stop a new checkout; the owner's app says nothing was charged | `services.py:1413,1630,1860,2054` | G-D, the gate reads "outstanding" |
| G1 r7 | Blocker 2: a stale worker's completion overwrites a re-armed job | `jobs.py:1019,1079,1194`, `services.py:2184,2217` | G-E, the fenced completion |
| G1 r7 | Blocker 3: staff resolve while the settle job is mid-read; the late success is applied | `services.py:2032,2047,2697`, `operations.py:310` | G-D, automatic paths obey staff |
| G1 r7 | Should-fix: Chargily's close learns "failed" but reports only "closed"; the attempt is final and `processing` forever | `providers/chargily.py:391`, `services.py:2081,1622,1977` | G-D, final means terminal |
| G1 r7 | Should-fix: the close intent and the job wake commit separately | `services.py:1653,1835,1858,2209` | G-E, one transaction |
| G1 r7 | Should-fix: an older successful read re-enables a refused action | `guest_pay_screen.dart:83,194`, `checkout_section.dart:410,521` | G-F, R9 |
| P3B r8 | Blocker 1: pointer down on A's Dismiss, a rebuild publishes B, the release runs B's callback | `profile_screen.dart:99`, `profile_photo_section.dart:175` | S-4; keyed controls |
| P3B r8 | Blocker 2: an interrupted credential save leaves A on screen with B's bearer | `token_store.dart:134`, `session.dart:530` | S-1, S-2 |
| P3B r8 | Blocker 3: the name draft and the language retry take their scope when submitted | `account_name_screen.dart:118`, `language_screen.dart:148` | S-4 |
| P3B r8 | Should-fix: a staff removal keeps the version, so an old Remove dialog deletes the new notice | `photos.py:393,436` | P-E |
| P3B r8 | Should-fix: Retry and Discard in the same frame | `profile_photo_section.dart:305`, `profile_photo_state.dart:464` | P-F |
| P3B r8 | Should-fix: after a 409, an older `/api/me` undoes the fresh state, and previews stay stale | `profile_photo_state.dart:497`, `session.dart:740` | P-G, R9 |
| P3B r8 | Should-fix: a keystore error is not shown by the password screen | `session.dart:492`, `sign_in_screen.dart:70` | S-2, typed error |
| N1 r5 | Blocker 1: the technical admin's full-row save writes back the old password hash and `session_epoch` after a reset | `accounts/admin.py:25`, `accounts/sessions.py:57` | N-D |
| N1 r5 | Blocker 2: a sign-out overtaken by another sign-in returns without sending | `auth_repository.dart:184`, `session.dart:399` | S-2, S-3, S-5 |
| N1 r5 | Blocker 3: a 429 on the launch `/api/me` clears credentials | `session.dart:303`, `api_exception.dart:114` | S-3 |
| N1 r5 | Should-fix: a repeated sign-out of an ended sign-in still advances the installation order | `accounts/sessions.py:85`, `notifications/push.py:790` | N-B |
