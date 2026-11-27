You are an independent second-pass reviewer. This review is read-only: do not write, commit or push code, and do not comment on GitHub. You may read files and run read-only git commands.

This is the **sixth review** of pull request #67, "G1: guest checkout without a browser-session dependency", in this repository (is-bo/shiptripis). Run `git fetch origin` first if a commit is missing.
- You rejected head `4337d9caff2d8e9961e3410f2e20343deb8ec5d4` (five findings), `f1fe5659fef2851c07473458fefc53ffa3a298d2` (six findings), `d99c8384882a3eaddae94d164e4bb3588acb4662` (three blockers, six should-fix), `1643afc1857ea3c0c0ba807f440e18db03c7bf94` (two blockers, eight should-fix) and `a0b48be0fba822c29216bed133b3fff8f99f2980` (three blockers, seven should-fix). Your fifth report is `docs/handoff/astra/results/g1-astra-round5-result.md` on `main`.
- The new head is `4e4c0ea98f677919fc02041d61398a4bc77698a2`. The fixes are one commit, `4e4c0ea`, directly on `a0b48be`. `main` had only docs since, so it is not merged in.
- Compare `a0b48be..4e4c0ea` for this round's fixes, and `origin/main...4e4c0ea98f677919fc02041d61398a4bc77698a2` (three dots) for the whole package.
- Backend code is under `backend/monolith/` (mostly `apps/finance/services.py`, `jobs.py`, `models.py`, `views.py`, `guest_web.py`, `providers/`); the app under `mobile/lib/` (`domain/payment.dart`, `features/requests/checkout_section.dart`, `features/guest/guest_pay_screen.dart`). The package is section 4 "G1" of `docs/WASSLA_PHONE_TEST_2_PLAN.md`. The write-up, with a "Sixth-pass review" section, is `docs/PHASE_G1_GUEST_CHECKOUT_CSRF.md`.
- Rules are in `CLAUDE.md`. Money is a "strongest model" area there. The app has never been in production and has no real users.

## Lead instructions the fixes had to follow (treat as correct)
- **B:** never leave a superseded attempt payable. Ask the provider to close the old checkout (Stripe Checkout Session expire, Chargily expire) and supersede only after the provider confirms. Otherwise answer a neutral, translated "a payment is already being made, try again later" conflict. Never hold the database lock across a slow provider call in a way that can deadlock. The same rule applies when the same payer switches rail or amount.
- **A:** prefer removing the raw URI and Referer from proxy logs over regexes.
- **C:** recover with the original idempotency key and the exact original parameters.

## What changed this round: the two causes, fixed where they live
The write-up's "The two causes behind six rounds of findings" explains why each correlation and closing finding since round 3 came back as a variant: events were bound by guesses, and whether a checkout can take money was read from the attempt's status. This round replaces both instead of patching paths:

1. **Binding.** An event binds only to the attempt that stored the provider object it names (`_match_attempt`: checkout id, else the payment id recorded with a success). Nothing else an event carries binds it. An event naming nothing stored is ignored (`unknown_checkout`); a success of that kind raises `FinanceError` (kept, retried, left for a human). Claimed complete because a checkout's id is stored before its URL leaves the server. Removed: the order-reference and attempt-id fallbacks, `ProviderEvent.attempt_reference`, `_reference_uuid`, the lock-time `another_checkout` check, Chargily's `attempt_id` metadata. Stripe `payment_intent.payment_failed` now maps to ignored.
2. **Liveness.** New column `PaymentAttempt.checkout_final_at` (migration `0036`, with partial index `fin_attempt_live_checkout_idx`), set only on a provider's word: an outcome reported through `reconcile_attempt` (succeeded, failed, expired, cancelled) for a stored checkout, or a confirmed close. `LIVE_CHECKOUT` (`models.py`) = stored checkout, not final, not succeeded, whatever the status.
3. **One settle routine.** `settle_checkout` (services.py): read the provider first; a final outcome is recorded through `reconcile_attempt`; processing answers `checkout_settling`; an open checkout still wanted (open status, no close intent, not expired) answers `checkout_open`; otherwise close, and only `CHECKOUT_CLOSED` marks it final (then an attempt past its expiry ends as expired). Used by in-request replacement (`_settle_before_checkout`), the expiry job, the settle job and order closure. Removed: `_close_checkout`, `close_ended_checkout`, the `checkout_close` job kind.
4. **One durable obligation.** The settle job `provider_reconcile:<attempt>` (`jobs.handle_provider_reconcile`) completes only when the checkout is final; it defers without spending retries while settling (1 h) or collecting (5 min), retries on any `ProviderError`, and is re-armed from any state by `_arm_checkout_settle`. The job loop's sweep (`arm_live_checkouts`, called from `run_due_jobs`) arms one for every live checkout without a pending or running settle job, which also covers rows left by code before G1 (no data migration).
5. **The gate.** `_checkout_step` settles any other live checkout of the order first (whatever its attempt's status), with no lock held, and hands the open attempt back only through `_hands_back`. A handleless attempt with no usable frozen request is refused like a provider refusal (`checkout_request_unusable`) and abandoned.
6. **Screens.** `checkout_state(order, ...)` tells the owner's order payload (`ready`, `resumable`, `guest_paying`, `in_progress`, `settling`) and the guest quote (`ready`, `in_progress`) what the next tap meets. The app's payment section and guest screen follow it; the guest web page opened in that state says so.

## Your round-5 findings and the claimed fixes
Blockers: 1 by binding (1); 2 by settling (3, 4); 3 by liveness, the gate and the sweep (2, 4, 5). Should-fix, in your table's order: 1 PI decline ignored; 2 Chargily `expires_at = created_at + 30 min` (`CHECKOUT_LIFETIME`); 3 hosted-URL keys scrubbed before storage (Chargily `url`, `checkout_url`; Stripe `url`); 4 Chargily `livemode` "true"/"false" normalised to booleans after signature verification and on API answers, anything else left for the strict check; 5 unusable frozen request; 6 and 7 `checkout_state`. Your partly-fixed items: round-3 #2 by should-fix 3; round-4 #1 by binding; #2 by settling; #4 by the sweep; #9 by should-fix 2; B by the gate and liveness; C by should-fix 5 (the key is not replayed with rebuilt parameters; the write-up explains why abandoning is safe).

Tests rewritten to the new rule are listed in the write-up ("Tests rewritten to the new rule"). The write-up says each new test fails with its fix removed (16 server mutations).

## What to do
1. Mark round-3 #2, round-4 #1, #2, #4 and #9, B and C, and your round-5 blockers 1 to 3 and should-fix 1 to 7, **fixed**, **partly fixed** (say what is missing) or **not fixed**.
2. Verify the two structural rules hold, rather than only the reported paths:
   - **Binding.** Is there any path left (webhook processing, persistence, provider or staff reconciliation, `settle_checkout`) where an event or snapshot reaches an attempt other than the one that stored the id it names? Can a real payment through one of our checkouts be ignored for good because it arrived before its id was stored?
   - **Liveness.** Is `checkout_final_at` set anywhere without a provider's word? Can any checkout whose URL left the server be not live while it can still collect? Can any live checkout be left without a pending settle job beyond one job-loop cycle? Can the sweep loop hot (re-arm and fail every cycle)?
   - **One checkout that can collect.** Can two checkouts that can collect exist for one order at any moment, on any path, old rows included?
   - **Money.** Does every payment taken through a checkout land exactly once (applied, or unapplied and refunded)? Any double application under the concurrent settle job, expiry job, webhook and tap?
   - **Locks.** Is any lock held across a provider call?
   - **Screens.** Can the owner or guest screen offer a tap the server would refuse? Does `checkout_state` leak anything about who is paying on the guest surfaces? Copy in all three languages?
   - **Tests.** Check each rewritten test: the change must be the new rule, not a loosened assertion.
3. Report only real, reachable problems. No style opinions.

## Output format
- One opening sentence.
- A table of the earlier findings listed in step 1: # | Status | Note.
- A table of new findings: Severity (Blocker / Should-fix / Nit) | File and line | Concrete failure | Suggested fix.
- What you could not check.
- A final line: "Overall verdict: approve" or "Overall verdict: reject".
