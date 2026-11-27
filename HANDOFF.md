# Wassla handoff

Written on 2026-11-15 by the planning session of the L-series, at Ismail's request, so that a
session on another account can continue exactly where the work stands. Everything such a session
needs is in this repository. Nothing here depends on an earlier conversation.

**Read `CLAUDE.md` first** (the rules), then this file, then the board
(`docs/WASSLA_L_SERIES_PROGRESS.md`).

## 0. Current status (2026-11-26) — read this before section 1

**A coordinator running in the cloud reads `docs/handoff/COORDINATOR.md` first**: the session setup
(cloud coordinator, cloud builders, a local operator on Ismail's PC for the server and Astra),
Ismail's reply format, and the two Astra runs still going.

Written by the lead session on 2026-11-26 so a session on another account can continue. Sections 1
to 11 below date from 2026-11-15 and still hold for rules and background; this section overrides
them where they differ. Server access details are never in this public repository: they live in
Ismail's local, uncommitted `CLAUDE.local.md` on his PC.

### 0.1 How work runs now (Ismail's rules, latest first)
- **Lead session** coordinates, reviews, merges and operates; it does not write product code.
  Builders are Claude Sonnet/Opus agents, one package per worktree, branch and pull request.
- **Planner:** normally a Claude Opus 5.5 extra-high agent (`CLAUDE.md` "Models"). For the phone
  test 2 plan and for package C1, Ismail chose **Astra 6.2 (OpenAI) at extra-high** instead.
- **Reviews:** every package gets an independent second pass by **Astra 6.2 at high effort**. The
  lead runs it itself through the Codex CLI, read-only, and verifies each finding before sending it
  back to the builder:
  `codex exec -m gpt-6.2-astra -s read-only -c model_reasoning_effort=high --output-last-message OUT.md - < PROMPT.md`
  Prompt templates used so far are in `docs/handoff/astra/` (update the head SHA before reuse).
  The Codex CLI must be recent (`npm install -g @openai/codex@latest`; 0.163 refused 6.2). Do not
  ration Astra; if Codex hits its usage limit, tell Ismail (he holds reset credits) and rerun after.
- **Never deploy, restart the server or build the app without Ismail's explicit OK.** The app is
  built only after all packages below are merged (one deploy, one Android test build at the end).
- Every Astra review result is posted as a comment on its pull request; read those comments for the
  exact open findings.

### 0.2 Live server
Release `5ee8cd2` (deployed 2026-11-23). Nothing below is deployed. Payments in TEST mode
(Chargily and Stripe on), Stripe Connect off, payout profiles off, FCM push off.

### 0.3 Packages (phone test 2 plan `docs/WASSLA_PHONE_TEST_2_PLAN.md` + 2026-11-24 fix plan)
Board: `docs/WASSLA_L_SERIES_PROGRESS.md`, table "Fixes after the phone tests".

| Package | PR | State on 2026-11-26 | Next action |
|---|---|---|---|
| P1, P2, P4, P3A, P3C, M1 | #60 #62 #61 #64 #65 #68 | merged | — |
| N2 bell names the ticket decision | #70 | merged (`ec24abc`), Astra approved | — |
| P3B profile photos in the app | #66 | Round 7 **finished and pushed** (2026-11-27): head `a286b34`, all 12 CI checks green (including `Android — compile and Gradle unit tests`). Answers Astra round 6 (3 blockers, 6 should-fixes) by fixing the cause: one `MemberScope` (account + authentication + credentials) captured once when an action starts and checked once when it commits; the photo writes also name their account and the request refuses another account's bearer; `MainActivity` is `singleTask`. | Astra round-7 review, high: prompt `docs/handoff/astra/p3b-review-round7.md` (head already set), result to `docs/handoff/astra/results/p3b-astra-round7-result.md`. Approve and CI green: gate and merge. Reject: a new builder round (Claude Sonnet, high). |
| G1 guest checkout without CSRF dependency | #67 | Round 5 **finished and pushed** (2026-11-26): fixes `a0b48be` on top of `1643afc`. No force-push, `main` not merged in (docs only). Answers both round-4 blockers (provider events bind to their own attempt by the attempt id in the checkout metadata, rechecked under the lock; order cancellation and closure to collection close issued checkouts at the provider through a durable `checkout_close` job) and all 8 should-fixes. Migration `finance 0036` now also adds the job kind (no SQL). Local: changed-path finance files 389 passed, app format and analyze clean; 14 server mutations and one app mutation each fail their tests. **CI all 11 checks green on `a0b48be`**, Schema drift included. | Astra round-5 review, high: prompt `docs/handoff/astra/g1-review.md` (head already set), result to `docs/handoff/astra/results/g1-astra-round5-result.md`. Approve and CI green: gate and merge. Reject: new Opus extra-high builder round. |
| F1 payout setup availability, server | #69 | Round 3 **finished and pushed** (2026-11-26): fix `ee1e477`, prompt `cb80430` (PR head), rebased on `main` `7ce265f`. CI all 11 checks green on `cb80430`. | Astra round-3 review, high: prompt `docs/handoff/astra/f1-review-round3.md`, result to `docs/handoff/astra/results/f1-astra-round3-result.md`. |
| N1 notification prompt on first open | #71 | Round 4 **finished and pushed** (2026-11-27), builder switched to Claude Opus (Ismail, 2026-11-26): code `139a206` and `227d8aa` (the refresh reads its token once; the K7 speed-budget test mints through a real sign-in), write-up and Astra prompt in the commit after it (PR head), `main` merged in (docs only). Answers Astra round 3 (`docs/handoff/astra/results/n1-astra-round3-result.md`: 4 blockers, 5 should-fixes, 1 nit) by replacing the mechanism instead of patching a fourth variant: every sign-in is a server row (`SignInSession`, migration `accounts.0008`) named by the `sid` of all its tokens, rotation included; a refresh and a push registration need it live, under the account lock that sign-out and reset also take. `PushAccountRevocation`, the issue-time cutoff and the outstanding-token blacklist loop are gone. Phone: newest-attempt check after every wait, retryable catch-up failure, Profile request needs its screen on top, Android upgrade second denial leads to Settings, guest copy. Offline sign-out documented as best-effort (should-fix 5, Astra's option 1). Every blocker and should-fix has a test that fails with its fix removed (mutation-checked). Local: 662 server tests (notifications, accounts, staff/claims, ticket copy) and the whole phone suite (1,717) passed. Heads up: migration `notifications.0009` deletes push devices that name no sign-in, and tokens issued before this change no longer refresh, so every tester signs in once more after deploy. | Astra round-4 review, high: prompt `docs/handoff/astra/n1-review.md` on the PR branch (round-4 section, head set to `227d8aa`), result to `docs/handoff/astra/results/n1-astra-round4-result.md`. Do not merge before it approves and every CI check is green. |
| C1 pay only in the traveler's currency | — | **New, owner decision Q5 (plan section 6).** Astra extra-high writing the plan (prompt `docs/handoff/astra/c1-plan.md`). | Bring Astra's questions to Ismail, then build after F1 (both touch `payout_snapshots.py`). |
| F2 payout pages on the phone | — | not started | After F1 and P3B (and C1's contract). |
| M2 route/date failures on the phone | — | not started | After P3B. |
| A1 route alert offer (after empty search and after posting) | — | not started | After P3B. |
| M3 other departure cities, browse only | — | not started | After A1 and M2. |

### 0.6 Exact pickup point (Ismail stopped all Claude work on 2026-11-26, about 10:00 Lagos)

**Nothing was lost.** Each unfinished builder's work is on a `wip/` branch on GitHub, committed as is
with a commit titled "WIP (unfinished, do not merge)". That branch is rebased on `main` as it was at
the time, so it differs from its PR branch; the PR branches were left exactly as reviewed. The open
findings for each round are in the latest Astra comment on each PR. The table below also lists the
extra instructions the lead gave each builder on top of those findings.

**How to resume a package** (one fresh builder agent per package, at the model and effort below, in
its own worktree):
1. Check out the `wip/` branch, then read the latest Astra comment on the PR and the phase doc.
2. See what the WIP commit already covers: `git show --stat` on it, then its diff.
3. Finish every finding, then reword or squash away the WIP commit.
4. Run the full suites the package needs.
5. Update the PR with `git push --force-with-lease origin HEAD:claude/<branch>`.
6. Re-run Astra with the prompt in `docs/handoff/astra/` (update the head SHA first).
7. Merge only after Astra approves and CI is green, with the gate comment on the PR.

| Package | Builder | Saved work | What it covers (from the builder's last words) | Extra lead instructions still binding |
|---|---|---|---|---|
| G1 #67 round 5 | Claude Opus, extra high | **Done 2026-11-26**: fixes `a0b48be` pushed to the PR branch on top of `1643afc`. The `wip/` branch can be deleted after G1 merges. | Both round-4 blockers and all 8 should-fixes: event binding by attempt id with a lock-time checkout recheck, order cancellation and closure closing checkouts at the provider (`checkout_close` job), Stripe delayed-payment failure read from the payment intent, 32-run close budget, receipts-off stored event, explicit technical admin fields, credential errors keep the recovery key, claim dated after the locks, provider expiry caps the attempt, owner screen waits on a settling payment. Detail: phase doc, "Fifth-pass review". | **B:** never leave a superseded attempt payable. Ask the provider to close the old session (Stripe Checkout Session expire, Chargily expire), and supersede only after the provider confirms. Otherwise answer a neutral, translated "a payment is already being made, try again later" conflict. Never hold the DB lock across a slow provider call in a way that can deadlock. The same rule applies when the same payer switches rail or amount. **A:** prefer removing the raw URI and Referer from proxy error logs over regexes. **C:** recover with the original idempotency key and the exact original parameters. If B needs a product or money decision, stop and ask Ismail. |
| F1 #69 round 2 | Claude Opus, extra high | Done 2026-11-26. Rounds 2 and 3 are on the PR branch. Delete `wip/f1-payout-availability` after F1 merges. | Edits in `core/financial_locks.py` (the per-traveler funding/preference lock), `payout_snapshots`, `payout_profiles`, `payout_profile_api`, `payout_mobile` and `payout_accounts`. When stopped it was writing "the account lookup helpers used by both the creation path and the read model". The round-2 tests are not written yet. | **Finding 1:** a stable per-traveler lock in the canonical lock order (never invert the order used in `services.py` and `payout_snapshots.py`), plus a two-connection PostgreSQL real-thread test. **Finding 6:** check the real Algérie Poste CCP number format, and tighten validation if a 1-digit minimum is wrong. The projection must always hide at least one digit. If any fix changes a money rule rather than enforcing the existing one, stop and ask Ismail. |
| N1 #71 round 2 | Claude Sonnet, high | Done 2026-11-26. Rounds 2 and 3 are on the PR branch. Delete `wip/n1-notification-first-open` after N1 merges. | The server part of finding 1 is started: `notifications/models.py`, `push.py`, the serializers and views, `accounts/views.py`, tests, and a new migration `0009_push_installation_binding.py`. When stopped it was "updating existing tests and adding new ones". Mobile findings 2–6 are not done yet. | The server change for finding 1 is allowed inside N1, limited to the device-registration path. It needs Django tests (a delayed A registration after logout and after B registers; check the final owner and active flag) and `task check-drift` for the migration. Retake the guest screenshots honestly, through the real guest route. |
| P3B #66 | Claude Sonnet, high | none needed: round 7 is pushed (head `a286b34`) | Round 7 replaces the per-action reads of the account and the generation with one `MemberScope` (`beginAction`, `isCurrent`); photo writes name their account and the interceptor checks the bearer's `user_id`; `singleTask`; the pick gate belongs to its activity. 25 Kotlin tests run under Gradle in CI. | `AppDelegate.swift` was never compiled; nothing ran on a device. Device checks are in the phase doc ("Handoff", "Round six", "Round seven"). |

**Astra runs still going at the stop.** They run on Ismail's PC through the Codex CLI, and the
results are files on that PC.
- **The C1 plan** (Astra extra high).
  - Output file: `C:\Users\URES\AppData\Local\Temp\claude\83ae47049b838ea9\7b73354f-ab9f-4bb7-9fdc-63036aaf1e66\scratchpad\plans\c1-plan.md`. Its log, `c1-astra-plan-log.txt`, is in the same folder.
  - The lead will also copy it to `D:\Code\Shiptrip\.astra-results\c1-plan.md` if it finishes while the lead session is still open.
  - If both are empty or missing, re-run `docs/handoff/astra/c1-plan.md` at `model_reasoning_effort=xhigh`.
  - Then bring Astra's questions to Ismail in plain words before any C1 build. C1 is built after F1 merges, by Claude Opus extra high.
- **The P3B round-4 review** (Astra high).
  - Output file: `D:\Code\Shiptrip\.astra-results\p3b-astra-round4-result.md`.
  - Prompt: `docs/handoff/astra/p3b-review-round4.md`.
  - Finished Astra results are committed to `docs/handoff/astra/results/`, the folder a cloud session can read.

**Order after that:**
1. Merge P3B, G1, F1 and N1 as each one passes.
2. Then C1 (server), F2 (phone payouts, consuming F1 and C1), M2, A1 and M3. Each is a planned package in `docs/WASSLA_PHONE_TEST_2_PLAN.md`, and each gets an Astra review.
3. Update the board and this section after every merge.
4. Then section 0.4, with Ismail's OK at each step.

### 0.7 Astra results after the Codex reset (local operator log, 2026-11-26)
The local operator on Ismail's PC runs Astra 6.2 at high effort, read-only, and pushes each result here.

| Package | Head reviewed | Verdict | Result file |
|---|---|---|---|
| C1 plan (extra high) | — | Plan complete, with questions for Ismail | `docs/handoff/astra/results/c1-plan.md` |
| P3B round 7 | `a286b34` | awaiting review (run by Ismail) | prompt `docs/handoff/astra/p3b-review-round7.md` |
| P3B round 6 | `ead30e2` | **Reject** (run by Ismail): 3 blockers (a refresh during the A-to-B switch saves A's snapshot under B's generation, the removal dialog confirmed after a switch deletes B's photo, a second Android window shares the bearer with its own generation), 6 should-fixes | `docs/handoff/astra/results/p3b-astra-round6-result.md` |
| P3B round 5 | `f4394f1` | **Reject** (run by Ismail): 2 blockers (a restored KYC image can still reach a Profile pick, and a fresh pick during an A-to-B switch pairs A with B's generation), 5 should-fixes | `docs/handoff/astra/results/p3b-astra-round5-result.md` |
| P3B round 4 | `c8b4e68` | **Reject**: 5 of 13 fixed, 8 partly fixed; 3 new blockers (KYC picker ownership, uncertain tickets returned to the parcel picker, retry during an account switch) | `docs/handoff/astra/results/p3b-astra-round4-result.md` |
| G1 round 5 | `a0b48be` | **Reject** (run by Ismail): 3 blockers (the metadata fallback accepts a missing order reference and PaymentIntent events skip the session check, a close that finds collection re-arms no reconciliation, live sessions inherited from the old main stay payable), 7 should-fixes | `docs/handoff/astra/results/g1-astra-round5-result.md` |
| G1 round 4 | `1643afc` | **Reject** (run by Ismail): 2 blockers (a delayed expired webhook is bound to the newest handleless attempt, and order cancellation leaves an issued checkout payable), 8 should-fixes | `docs/handoff/astra/results/g1-astra-round4-result.md` |
| G1 round 3 | `d99c838` | **Reject**: A, D, E and F fixed, B and C partly fixed; 3 new blockers (an expiry job leaves a Stripe URL payable, recovery republishes a URL on a terminal attempt, a recovery race supersedes without closing) | `docs/handoff/astra/results/g1-astra-round3-result.md` |
| N1 round 3 | `13b7ea4` | **Reject** (run by Ismail; accepts the declined old-app blocker): 4 blockers (an unnumbered sign-out before first registration, the same-second `iat` cutoff, a rotated session that survives reset, an exact-repeat check that ignores `sid`), 5 should-fixes, 1 nit | `docs/handoff/astra/results/n1-astra-round3-result.md` |
| N1 round 2 | `49ae6d8` | **Reject** (run by Ismail on a second Codex account): 6 blockers. Logout can leave the old account receiving pushes (old-app compatibility, out-of-order logout and registration, stale logout after a counter reset, equal sequence numbers, a racing installation ID, password reset) | `docs/handoff/astra/results/n1-astra-round2-result.md` |
| F1 round 3 | `cb80430` | **Reject** (run by Ismail): 3 blockers (an explicit stale `country=DE` replaces a newer FR declaration, a late timeout reopens a failed key and recovery binds the wrong account, a crashed intent sends its first POST for a closed country), 6 should-fixes, 1 nit | `docs/handoff/astra/results/f1-astra-round3-result.md` |
| F1 round 2 | `8d1a1cd` | **Reject** (run by Ismail): 8 of 10 fixed, 2 partly fixed; 1 blocker (a stale Stripe onboarding overwrites a newer payout-country declaration) | `docs/handoff/astra/results/f1-astra-round2-result.md` |

### 0.4 After every package is merged (each step needs Ismail's OK)
1. Deploy the reviewed `main` SHA to the VPS (`infra/vps/README.md`), then O2 (guest checkout check).
2. Build a `release` Android APK with the GitHub "Build Android" workflow, give it to Ismail on his
   PC, then delete the artifact and the run from GitHub (his rule). Run the device checks listed in
   the P3B and N1 phase docs.
3. Operations O3 (FCM push on), O4 (private payout bucket, payout profiles on, DZD rehearsal),
   O5 (France-only Stripe Connect test), O6 (route alerts), monitor and systemd timers.

### 0.5 Before launch (not code packages)
Remove the demo data on the live database, rotate the three Backblaze keys, real Stripe and
Connect, Google Play and Apple accounts and the Data safety form, publish the Google consent
screen, an uptime monitor, and the older findings (parcel photo GPS metadata, full name on journey
detail, own-card labels).

## 1. Start here

```
git fetch origin
git checkout main
```

All current work is on `main`. Since 2026-11-16 `main` is the L-series branch; the September `main` is kept as `main-old` (section 4). Never deploy without Ismail's approval.

A first message that works for a fresh session:

> Read CLAUDE.md, HANDOFF.md and the board in docs/WASSLA_L_SERIES_PROGRESS.md on the branch
> main. Tell me where the work stands and what you would do
> next, then wait for my go.

## 2. What Wassla is

A marketplace where a sender's parcel travels with a traveler who is already making the trip.
A sender posts a request and proposes to a compatible traveler; the deal is funded; the traveler
collects the parcel with a pickup code, reports progress, and delivers by entering the recipient's
code; the payout is released 48 hours later unless a dispute freezes it.

Since 2026-11-13 the product is **fast delivery**: urgent parcels, mostly on flights and drives made
the same day. Ismail's words: "we just wanna try and target same day urgent delivery". It is a
target and a positioning, not a rule the app enforces.

Stack: Flutter app in `mobile/` (English, French, Arabic); Django monolith in `backend/monolith/`
(REST API, staff console, staff API under `/api/admin/`); Go services in `backend/services/` (chat,
notifications, ID upload); PostgreSQL 16, Redis 7, S3-compatible storage; the production host stack in
`infra/vps/`; the public site in `web/`. `ARCHITECTURE.md` describes the system.

## 3. Where the work stands (2026-11-15)

The **L-series** (Home discovery, routes for everyone, traveler pricing, progress reports, the staff
verification inbox, problems and schedule changes, tracking numbers, proposal deadlines and trip-fit
alerts, reviews, staff two-step sign-in, finance exports, the admin AI helper and its skill) is
built, merged into the integration branch and accepted by its final package:

- Every package from L1A to L18B, and L10 (final acceptance), is **merged**. Pull requests #22 to
  #49. The board has one row and one handoff block per package.
- L10 changed no product code. Its verdict and every number are in
  `docs/WASSLA_L_SERIES_RELEASE_REPORT.md`. Tests on the final build: Django 3,270 passed, Flutter
  1,533 passed, Go race tests clean on 14 packages.
- **On 2026-11-16 the integration branch became `main`** (at Ismail's request). Nothing is deployed. The release report has not yet been
  formally handed to Ismail for his end review; that is the next step (section 5).
- **L19** (the two findings of L10) is merged too: PR #51, `bfecca1`, 2026-11-16.

The last commit of the integration branch when this was written: `4478ad9` (board after L10).

## 4. Branches

| Branch | What it is |
| --- | --- |
| `main` | **The working branch. All work lands here** through pull requests. Since 2026-11-16 it holds the whole L-series (built on the former integration branch `feature/discovery-professional-delivery`, itself started from the baseline `dd7f820`) plus the old `main`. |
| `main-old` (`03aac94`) | The `main` before 2026-11-16: last real change in September 2026 (the K-series release record) plus Ismail's README revision. Kept for history; do not build on it. |

On 2026-11-16, at Ismail's request, every other branch was deleted: the former integration branch,
`feature/wassla-v3-baseline`, the three `codex/*` branches and the `claude/project-thread-*` package
branches. Each was checked first: either fully contained in `main` or the head of a merged pull
request. Their commits stay reachable from `main` or from the merged pull requests.

Pull requests are squash-merged. After a squash merge, a warning that the old branch has "unpushed
commits" is harmless; nothing needs a force-push.

Brand history: ShipTrip, then Waçla, then **Wassla**. Some `shiptrip` and `wacla` names remain on
purpose: the Go module path, the database role, `docs/SHIPTRIP_V1_SPEC.md`, systemd unit names, a
fixture name, and provider checkout descriptions that are part of idempotency fingerprints. Do not
rename them as "cleanup" without checking what depends on each.

## 5. What is next, in Ismail's order

Ismail decides when each starts. Do not start any of them on your own.

### 5.1 L19, findings of final acceptance (merged 2026-11-16, PR #51)

Plan section "L19" and decision 5.1g. **Done:** both findings are fixed and closed in release report
section 14; detail in `docs/PHASE_L19_ACCEPTANCE_FINDINGS.md`. What it was:

1. The admin helper's notes still describe a staff path to open a dispute that L18A removed
   (`backend/monolith/apps/admin_helper/skill/knowledge/architecture-and-diagrams.md`, and the same
   line in the generated `INSTRUCTIONS.txt`). Drop the sentence, search the skill for other mentions,
   regenerate with `python manage.py build_helper_instructions`, rerun the one proof conversation.
2. With `PAYOUT_PROFILES_ENABLED` off (the shipped example configuration), `ensure_payout_for_deal`
   in `apps/finance/services.py` creates the payout with no mode, so it defaults to `legacy_unknown`
   while its funding is in test mode, and the finance dashboard splits one deal's traveler balance
   across two modes. The payout takes the mode of its funding attempt (the `funding_attempt(order)`
   lookup that `create_snapshot` uses). Production cannot reach this branch.

Done when L10's 22 acceptance tests and the whole suites are green on its pull request and the
release report's section 14 marks both findings closed. **After L19, hand Ismail the release report**
(plan L10 item 9): the report, the switches still off, and the open decisions of section 8 below.

### 5.2 A scan for unnecessary complexity and repeated logic

Ismail wants the code scanned for unnecessary complexity and repeated logic. Suggested way to run it,
so that nothing changes behaviour by accident:

1. **Read-only first.** Produce a findings document (for example `docs/WASSLA_CLEANUP_AUDIT.md`):
   each finding with its place, why it is unnecessary or repeated, what would replace it, the risk,
   and whether it touches matching, money, codes or staff authority.
2. Ismail approves the list. Only then is anything changed.
3. Group the approved findings into small packages, one pull request each, with the model and
   effort decided by the rule of plan 1.2. Each is behaviour-preserving: the whole suites and L10's
   acceptance tests (`backend/monolith/apps/core/tests/test_l10_*.py`) pass unchanged.
4. No money result, code rule or matching result may change. If a simplification would change one,
   it stops and becomes a question for Ismail.

Rules that already have one home. A second copy of any of these is a finding; the home itself is
not:

| Rule | Its one home |
| --- | --- |
| Ticket proof for flight and sea legs | `apps/trips/proofs.py` |
| Switches and settings | `apps/core/marketplace_policy.py` |
| Listed price arithmetic | `apps/matching/listed_price.py` |
| Writes to `Deal.status` | `apps/deals` only |
| Tracking number | `apps/parcels/tracking.py` |
| Public rating averages and counts | `apps/ratings/public.py` (`countable`) |
| Staff work list and its severity | `apps/admin_panel/worklist.py` |
| "Waiting" in the verification inbox and its three decisions | `apps/admin_panel/verification_inbox.py` |
| Console actions the AI helper also runs | `apps/admin_panel/staff_actions.py`, registry in `apps/admin_helper/actions.py` |
| Problem reports | `apps/problems` |
| Schedule changes | `apps/trips/schedule_changes.py` |
| Ending every session of an account | `apps/accounts/sessions.py` (`end_all_sessions`) |
| "Confirmed email needed to write" | `apps/accounts/permissions.py` (`EmailVerifiedToWrite`) |
| Staff second-step gate | `apps/admin_panel/two_step.py` |

Known candidates, found during the L-series and deliberately left (verify each before acting):

- **Legacy tables and branches** (`docs/WASSLA_L1_CLEANUP_INVENTORY.md`, section 2): the models,
  migrations and tables of `apps.payments`, `apps.wallet`, `apps.verification`, `apps.trips.Trip`
  and `ProductRequest`; the `schema_version` 1 and 2 branches in matching, trips, parcels and
  finance; `apps/matching/services.py::_legacy_chat_eligibility`. No real row needs them. They stayed
  because the L-series forbade any migration that drops or narrows (plan 1.5 rule 5). **Removing
  them needs Ismail to lift that rule for a dedicated cleanup package**, on the strongest model,
  because the branches sit inside matching, finance and pricing reads.
- **The payout path without payout profiles** (`PAYOUT_PROFILES_ENABLED` off). Live mode requires
  profiles, so this branch serves development and tests only. Whether to keep two payout paths is a
  question for Ismail after L19.
- **Statuses nothing sets**: deal `offer_accepted` and `payment_failed`, journey
  `pending_verification`. Left on purpose (plan 5.1f): the V1 specification names them and they sit
  in status lists, a database constraint and the app.
- **About 80 code comments cite sections of an earlier `CLAUDE.md`** (`CLAUDE.md §4`, `§9`, `G1`
  and so on). The guardrails G1 to G6b are restated in today's `CLAUDE.md`; the numbered sections no
  longer exist. The earlier file is in git history (`git log --follow CLAUDE.md`, before 2026-08-30).
- L9A known limit: after an accepted later pickup time, the no-show window still uses the original
  time (`agreed_pickup_at` keeps its funded value).
- The console refund form, asked twice for the same payment and reason, answers with the refund that
  exists whatever the amount (`finance.services.request_refund`); the AI helper refuses that case.
- `tools/geography` tests are not run in CI.

### 5.3 Repository cleanup

Candidates, for Ismail to approve before anything is deleted:

- Root files from earlier phases: `TASKS.md` (a two-person task list from mid-2026, stale but with
  notes on why some behaviours are deliberate), `ShipTrip_Progress_Report.pdf`, the empty
  `package.json` and `package-lock.json`, `backend/services/HANDOVER.md`.
- Tool folders: `.cursor/`, `.codegraph/`.
- `docs/`: about 120 files. The dated phase reports (`PHASE_*`, `K_SERIES_*`, `V1_*`, `V2_*`,
  `k6-notes/`, `k7-notes/`, `superpowers/`) are history; `docs/IMPLEMENTATION_STATUS.md` is close to
  9,000 lines. An archive folder or a trimmed status file would make the live documents easier to
  find. The live ones are listed in section 9.
- `ARCHITECTURE.md` was corrected in L1A but predates most of the L-series.
- Removed in the handoff commit because they contradicted today's rules: the old `HANDOFF.md`
  (April 2026) and `.claude/MEMORY.md` with `.claude/memory/` (a two-agent split, DZD commission
  rules and a storage design that no longer exist). Git history has them.

### 5.4 Other changes

Ismail said there are other changes he wants. He has not described them yet. Ask him.

## 6. How the work is run

`CLAUDE.md` has the rules. The full procedure is plan section 1 (`docs/WASSLA_DISCOVERY_PRO_PLAN.md`):
1.0 the runbook, 1.2 models and effort, 1.4 the checks, 1.5 the rules of every package, 1.6 the gate
review, 1.7 when to stop and ask, 1.8 the board, 1.9 the brief for a package.

The L-series was run by three roles: an orchestrator that kept the board, started one worker per
package with the plan's model and effort, ran the gate review and merged; one worker per package;
and an advisor that settled questions about the specification and plan and recorded each answer in
the plan. One session can play all three, or the person can start one session per package. What must
not change:

- One package at a time, in the board's order, each in its own pull request into the integration
  branch.
- The model and effort the plan names for the package. Before starting a package, say which model
  and effort it needs so the person can switch to it. Ismail corrected this once and asked to be
  reminded at every step.
- The gate review is recorded on the pull request before the merge, and the merge waits for every
  check: `Go — build, vet, unit tests`, `Go — integration tests (real Redis)`, the four
  `Django — tests (shard N)` jobs, `Django — migrations + tests + lint`,
  `Production config + static web`, `Flutter — format, analyze, tests` and `Schema drift`.
- After a merge, the board is updated in a small docs-only commit on `main`. Pull
  before editing it.
- Ismail did not want to be asked small questions during the build. A question about what the
  specification or plan means, or a choice between two ways to build the same rule, is settled by
  reading them and recording the choice as a judgment call in the package's handoff block. Only
  what would change a product decision, a money rule or the approved scope waits for him.
- Judgment calls are listed, not hidden: each package's handoff block and the release report
  (section 12) collect them for Ismail's end review.

Gate screenshots were saved outside the repository (section 9). From now on, attach them to the
pull request, which the plan allows (1.6), unless Ismail names another place.

## 7. Decisions Ismail has made

Locked. Do not reopen them; the plan's section 5 has the dates and the detail.

**Scope**
- Fast delivery, mostly same-day flights and drives. No enforced same-day rule.
- Parked, with their full text kept in `docs/parked/WASSLA_PROFESSIONAL_AND_COURIER_PLAN.md` for a
  later subdomain: professional transporters (profile, business document, ticket exemption), the
  manifest dashboard, custody history, courier handoff. Packages L6B, L7A, L7B, L8A, L8B and the
  professional half of L6A. Never start them, leave no hooks.
- Sea legs stay built and switched off. Turning them on is Ismail's call: the legal and customs
  position was not researched and the crossings were not checked on the operators' sites.
- Launch countries: Algeria, France, Spain, Germany.
- Not built, because he declined them: a legal package (terms page with recorded acceptance, final
  prohibited-items list). He also declined shipping the AI helper switched off: it ships on.

**Product**
- Every traveler may build a multi-stop route. Travelers pass the ID check, and upload a ticket for
  each flight and sea leg. Nobody is exempt.
- No capacity cap set by staff.
- Pricing: a price per kg and a minimum per parcel, per route; the offer is pre-filled and still
  negotiable; Wassla's minimum applies; the fee is on top.
- Discovery profiles are opt-in. "I can carry this" stays. Depart and arrive reminders per leg.
- A declined schedule change followed by a cancellation counts as caused by the traveler.
- A proposal waits 6 hours, or until the pickup time if that is sooner, with a reminder 1 hour
  before.
- Senders verify by email only. Travelers by ID.
- Push: Firebase only, for the closed app.
- From the cahier des charges, he chose to build: the tracking number, alerts to travelers whose
  trip fits a new request, the reminder before a proposal expires, "the other person did not come",
  public reviews with report and hide, finance exports and staff two-step sign-in.

**Staff side**
- One verification inbox (ID and Tickets), switches, suspend and pause, everything audited.
- AI helper: per-admin keys; the read key ends 8 hours after creation, the change key after 30
  minutes; no ID documents, bank details, delivery codes or chat contents ever reach it; money, ban,
  role and settings actions are prepared by the helper and confirmed by the admin in the console.
  The skill is for the Super Admin only for now and must answer any question about the app,
  including how it is built, with diagrams.

**Process**
- Never deploy without his approval; work reaches `main` only through pull requests that follow the gate. Model and effort exactly as planned.
- The app has no real users: no legacy or backward-compatibility work.
- Quality bar: impeccable UX; clean code, dead and messy code removed; location, finance and
  admin-control logic airtight.

Four ways the app differs from the cahier des charges that Ismail has **not** decided, and that no
plan covers. Do not build any of them unless he asks: payment in full before matching (the app takes
a small refundable posting deposit, full payment after a traveler agrees); a fixed price grid (the
app has a minimum, a suggestion and negotiation); travelers alerted and the first to accept assigned
(the app lets the sender choose and propose); weekly payouts (the app pays per delivery after 48
hours).

## 8. Open items for Ismail

**Before real users** (release report section 10)
1. The support address is now set in the code and the examples: **contact@wassla.eu** (From,
   Reply-To and support). It still needs a real monitored mailbox with MX records, because Sender.net
   only sends.
2. `web/support.html` shows contact@wassla.eu. `web/robots.txt` and `web/sitemap.xml` name
   `https://wassla.eu` (2026-11-23).
3. A terms page with recorded acceptance and the final prohibited-items list.
4. If a CDN or another proxy is ever put in front of the web server, set the trusted proxies and the
   per-address limits for it first.
5. The payout keyring must be provisioned before the first production start.
6. Package EGS (email, guest browsing, Google and Apple sign-in) is built and off. Ismail's own steps,
   in order, are in `docs/WASSLA_SETUP_FOR_ISMAIL.md`: Sender.net account, domain, DNS and token; the
   mailbox; Google Cloud clients; Apple Developer, including the Sign in with Apple key that account
   deletion uses. The app id is `eu.wassla.app`, and account deletion, chat reports and blocking are
   built (STORE).

**Open decisions** (release report section 11, plan 5.1f and 5.1g)
1. Should staff be able to open a dispute? Today only the sender or the traveler can.
2. Payout setup needs a confirmed email (added in L18A as a safety measure). Keep it?
3. The AI helper's urgency thresholds: tickets after 2 hours; ID checks and payouts after 24;
   payout methods and payout identity after 48; reported reviews after 72.
4. Turning sea legs on.
5. The planner's choices he has not individually confirmed (plan 5.1c): random tracking number;
   trip-fit caps of 30 travelers per request and 5 alerts per traveler per day; reviews show the
   role, not the name; authenticator app only for two-step; no email, phone, address or bank detail
   in exports. Also the schedule-change threshold `route_change.material_shift_minutes`, 360.
6. When to start the scan and the cleanup, and what the other changes are (section 5). L19 is done.
7. For the cleanup: whether to lift the "no migration drops or narrows" rule so the legacy tables
   and branches can go (section 5.2).

**For his end review**: the judgment calls of every package, release report section 12.

## 9. Where everything lives

| What | Where |
| --- | --- |
| Rules for agents | `CLAUDE.md` (and `AGENTS.md`, which points to it) |
| V1 specification | `docs/SHIPTRIP_V1_SPEC.md` |
| Addendum that overrides it for the L-series topics | `docs/WASSLA_DISCOVERY_PRO_SPEC.md` |
| Plan: runbook, rules, packages, decisions | `docs/WASSLA_DISCOVERY_PRO_PLAN.md` |
| Board, handoff notes, questions, change log | `docs/WASSLA_L_SERIES_PROGRESS.md` |
| Release report of the L-series | `docs/WASSLA_L_SERIES_RELEASE_REPORT.md` |
| What each package built | `docs/PHASE_L*.md`, one per package |
| Parked plan | `docs/parked/WASSLA_PROFESSIONAL_AND_COURIER_PLAN.md` |
| What the first cleanup removed and kept | `docs/WASSLA_L1_CLEANUP_INVENTORY.md` |
| Progress log | `docs/IMPLEMENTATION_STATUS.md` (newest entry at the top) |
| AI helper skill and its notes | `backend/monolith/apps/admin_helper/skill/` |
| Staff operations, deployment, rollback, providers, push | `docs/ADMIN_OPERATIONS.md`, `docs/DEPLOYMENT_RUNBOOK.md`, `docs/ROLLBACK_RUNBOOK.md`, `docs/PROVIDER_ACTIVATION_RUNBOOK.md`, `docs/PUSH_NOTIFICATIONS_RUNBOOK.md` |
| Production host and its settings | `infra/vps/`, `infra/vps/ENVIRONMENT.md`, `infra/vps/stack.env.example` |
| CI | `.github/workflows/ci.yml` |
| Design and product notes | `DESIGN.md`, `PRODUCT.md`, `ARCHITECTURE.md` |

**Not in the repository.** These were kept in the previous account's project folder, which another
account cannot reach. Ismail has them and can pass them on:

- The gate screenshots of every package and the gallery L10 built from them (324 images, about
  57 MB, `l-series-screens/gallery.html`). The file names are listed in each package's phase doc.
- The comparison of the app with the cahier des charges (a PDF in English and one in French).

## 10. Working notes that save time

**Checks** (plan 1.4 has the full list)
- Backend: `ruff check .`, `python manage.py makemigrations --check --dry-run`, the whole pytest
  suite on PostgreSQL. Use `python -m ruff` with the pinned version (0.8.4 in `requirements.txt`); a
  newer global ruff reports about a thousand false errors.
- The Django suite needs PostgreSQL 16 and Redis 7 and the environment of `ci.yml`, including every
  `DRF_*_THROTTLE_RATE=10000/min` variable; without them about 30 tests fail with 429. Serially it
  takes about 30 minutes; CI splits it into four shards by file
  (`backend/monolith/config/test_shards.py`, durations in `config/test_durations.json`). A second run
  in parallel needs its own `POSTGRES_DB`.
- After a migration: `task check-drift` in `backend/`, and commit the regenerated `schema.sql` and
  sqlc output. If drift appears with no schema change, check the `pg_dump` client version first: CI
  runs `pg_dump` inside the PostgreSQL 16 service container for that reason.
- Go: `gofmt -l .`, `go build ./...`, `go vet ./...`, `go test -race -count=1 ./...` in
  `backend/services`.
- Mobile: `flutter gen-l10n`, `dart format --output=none --set-exit-if-changed lib test`,
  `flutter analyze --fatal-infos`, `flutter test` (about 3 minutes). CI uses Flutter 3.47.1,
  Go 1.26, Python 3.12.

**CI**
- If every check fails within seconds and shows no logs, the fault is the runner or the GitHub
  account, not the code. It happened on 2026-11-14 and twice on 2026-11-15, and Ismail fixed it each
  time. Tell him once, then re-run the failed jobs when he says. Never push an empty commit to
  retry.
- One test has failed once in a full local run and passed alone and in CI:
  `test_phase8fh5_control_plane::test_user_dispute_is_separate_and_postgres_plan_uses_existing_indexes`.

**Tests that fail when something new is not registered**
- A new `/api/admin` route must be added to the frozen inventory `STAFF_API_ROUTES` in
  `apps/admin_panel/tests/test_l14_two_step.py`.
- A new console POST route must be in the AI helper's action table or its "never" list
  (`apps/admin_helper/actions.py`), or `test_l16_coverage.py` fails.
- A new person-page tab in the console must be added to the expectations in
  `apps/admin_panel/tests/test_phase_j64_person_profile.py`.
- A new Redis channel is added in three places together (plan 1.5 rule 8); a Go test compares the
  lists.
- A change to the helper's notes needs `python manage.py build_helper_instructions`; a test fails
  when `INSTRUCTIONS.txt` is stale. A package that changes behaviour the notes describe updates the
  matching file in `skill/knowledge/`.

**Test helpers**
- Staff: sign in with `apps/admin_panel/tests/two_step_helpers.staff_login(client, user)`. Never
  `force_authenticate` on a staff route and never turn the gate off. The staff API is session-only;
  bearer tokens open no staff route.
- Any test that posts a parcel or writes payout setup over HTTP creates the user with
  `is_email_verified=True`.
- The acceptance world: `backend/monolith/apps/core/tests/l10_world.py`.

**PostgreSQL and Django traps met during the build**
- `select_for_update()` with `select_related(...)` locks the joined rows too. Use
  `select_for_update(of=("self",))` when only the main row should be locked.
- A `CHECK (x >= 1)` passes when `x` is NULL; a both-or-neither constraint needs an explicit
  not-null test.
- DRF wraps error values in lists, so `None` in a `ValidationError` payload renders as the string
  "None". Leave the key out instead.
- Lock order in the AI helper: the admin user row, then the active settings revision, then key rows,
  then prepared-action rows.
- "Ask for a new upload" in the verification inbox is stored as status `rejected` with
  `outcome: resubmission_requested`, because the Go service owns the ID status values. Never add an
  ID status in Django.
- A whole-route update of a journey that omits the price fields clears the price; the app always
  resends them.

**Flutter test traps**
- The test font is Ahem, every glyph one em wide, so overflow with long strings can be an artefact;
  wrap with `Flexible` anyway.
- To reach the end of a lazy list in a test, scroll in steps of 80% of the viewport; jumping to the
  maximum extent never converges. Call `ensureVisible` before tapping a row that
  `scrollUntilVisible` found.
- Screenshots come from a throwaway widget test that loads the real fonts and writes PNG files. Do
  not commit it. Console screenshots come from a live-server test driven by Playwright.

**Geography**
- Every French commune and Spanish municipality has coordinates (PR #27). Refresh only coordinates
  with `tools/geography/normalize_sources.py --download --supplement-coordinates ...`; a full rebuild
  pulls newer upstream data and is not needed.

## 11. What the other account needs

- Write access to the GitHub repository `is-bo/shiptripis`, given by Ismail.
- CI runs on the repository's own GitHub Actions; nothing to set up.
- The provider keys, the production host and the Firebase project are Ismail's. No task in section
  5 needs them: everything runs in test mode with the mock payment rail.
