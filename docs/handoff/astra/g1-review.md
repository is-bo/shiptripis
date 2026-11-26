You are an independent second-pass reviewer. This review is read-only: do not write, commit or push code, and do not comment on GitHub. You may read files and run read-only git commands.

This is the **fifth review** of pull request #67, "G1: guest checkout without a browser-session dependency", in this repository (is-bo/shiptripis). Run `git fetch origin` first if a commit is missing.
- You rejected head `4337d9caff2d8e9961e3410f2e20343deb8ec5d4` (five findings), `f1fe5659fef2851c07473458fefc53ffa3a298d2` (six findings), `d99c8384882a3eaddae94d164e4bb3588acb4662` (three blockers, six should-fix) and `1643afc1857ea3c0c0ba807f440e18db03c7bf94` (two blockers, eight should-fix). Your fourth report is `docs/handoff/astra/results/g1-astra-round4-result.md` on `main`.
- The new head is `a0b48be0fba822c29216bed133b3fff8f99f2980`. The fixes are one commit, `a0b48be`, directly on `1643afc`. `main` had only docs since, so it is not merged in.
- Compare `1643afc..a0b48be` for this round's fixes, and `origin/main...a0b48be0fba822c29216bed133b3fff8f99f2980` (three dots) for the whole package.
- Backend code is under `backend/monolith/` (mostly `apps/finance/services.py`, `jobs.py`, `providers/`, `admin.py`); the app under `mobile/lib/`. The package is section 4 "G1" of `docs/WASSLA_PHONE_TEST_2_PLAN.md`. The write-up, with a "Fifth-pass review" section, is `docs/PHASE_G1_GUEST_CHECKOUT_CSRF.md`.
- Rules are in `CLAUDE.md`. Money is a "strongest model" area there.

## Lead instructions the fixes had to follow (treat as correct)
- **B:** never leave a superseded attempt payable. Ask the provider to close the old checkout (Stripe Checkout Session expire, Chargily expire) and supersede only after the provider confirms. Otherwise answer a neutral, translated "a payment is already being made, try again later" conflict. Never hold the database lock across a slow provider call in a way that can deadlock. The same rule applies when the same payer switches rail or amount.
- **A:** prefer removing the raw URI and Referer from proxy logs over regexes.
- **C:** recover with the original idempotency key and the exact original parameters.

## The rule claimed now (unchanged from round 4, plus event binding and order closure)
Migration `finance 0036` adds `checkout_request` (frozen create request), `opening_until` (the claim) and `close_requested_at` (close intent) to the payment attempt, and now also the `checkout_close` job kind. A checkout URL leaves the server only in the answer of a checkout call, and only after it is stored on an open attempt.

New this round:
- **Event binding.** Every checkout carries its attempt id in its metadata (Stripe session and payment intent, Chargily `metadata[0].attempt_id`, the mock). `ProviderEvent.attempt_reference` carries it. `_match_attempt` binds by checkout id, then payment id, then that attempt id, and only to an attempt with no checkout stored, of the same provider, on the order the event's reference names. There is no order-only fallback. `reconcile_attempt(provider_session_id=...)` rechecks under the attempt lock: an event about another checkout than the stored one is ignored (`another_checkout`), and a success of that kind raises `FinanceError`.
- **Order closure.** `cancel_order` and `close_order_to_collection` call `_stop_collecting_attempts`: under the order lock each open, non-settling attempt is cancelled; one with a stored checkout gets `close_requested_at` and a `checkout_close` job (`close_ended_checkout`), which closes the checkout at its provider with no lock held and retries until the provider confirms. A `processing` attempt is left to its outcome; a success on a cancelled order lands unapplied and is refunded.

## Your round-4 findings and the claimed fixes
Numbered in the order of your round-4 table of new findings. Your round-3 items marked partly fixed are covered here too: 2 (technical admin URL) by 6, 7 (stored event address) by 5, B (webhook and cancellation paths) by 1 and 2, C (credential failure) by 7.
1. **(blocker) Late expired event from an abandoned session expired the newest attempt.** Event binding and lock-time recheck, as above.
2. **(blocker) Order cancellation and settlement closure did not close checkouts.** Order closure, as above.
3. **(should-fix) Failed delayed payment polled as processing forever.** Stripe `fetch_attempt` expands `payment_intent`; a complete, unpaid session whose intent is `requires_payment_method` or `canceled` is failed; otherwise processing.
4. **(should-fix) Close work exhausted after eight tries.** Expiry and close jobs get 32 runs (`CHECKOUT_CLOSE_ATTEMPTS`), about six days with the capped backoff; an exhausted job is logged at error level and stays retryable by staff.
5. **(should-fix) Receipts off: the stored event kept the payer's address.** `_normalized_provider_event` keeps the address only for an attempt opened with a guest receipt address; Stripe's scrubber drops `customer_email`.
6. **(should-fix) Technical admin showed the hosted URL and frozen request.** `PaymentAttemptAdmin` has an explicit read-only field list without them.
7. **(should-fix) Recovery refused for credentials abandoned the key.** `RECOVERY_RETRYABLE_ERRORS` (unavailable, not configured, configuration invalid) keeps the key and answers `CheckoutInProgress`.
8. **(should-fix) Claim dated before the lock wait.** `_checkout_step` reads the clock after the locks.
9. **(should-fix) Attempt outlived its provider's checkout.** `CheckoutResult.expires_at` (Stripe `expires_at`) moves the attempt's `expires_at` earlier in `_store_checkout` and reschedules its jobs. Chargily states no expiry in its create answer.
10. **(should-fix) Settling owner payment offered Pay.** The owner screen shows "We're still confirming your payment" with "Check again" and no rail choice.

Tests rewritten to the new rule are listed in the write-up ("Tests rewritten to the new rule"). The write-up says each new test fails with its fix removed (14 server mutations, one app mutation).

## What to do
1. Mark round-3 findings 2 and 7, your ten round-4 findings, and B and C, **fixed**, **partly fixed** (say what is missing) or **not fixed**.
2. Hunt for **new**, real, reachable problems in the fixes. In particular:
   - **Event binding.** Can any provider event (Stripe session or payment intent events, Chargily, the mock, provider reconciliation, staff reconciliation) still reach an attempt it was not created for? Can an event that arrives before its checkout is stored, or after another checkout is stored, change the wrong attempt? Can a real payment be dropped or left unrecorded because an event is now ignored?
   - **Order closure.** After cancellation or closure to collection, can an issued checkout still collect with no close job scheduled or with the job ending before the provider confirms? Is any lock held during the provider call? What happens when the close job meets a collected or settling checkout?
   - **One checkout that can collect.** Can two checkouts that can collect exist for one order at any moment, on any path? Can an attempt be superseded or expired without its provider confirming the close, other than one whose URL never left the server?
   - **Expiry.** Is the provider's own expiry applied on every path that stores a checkout? Can the reschedule leave an attempt with no expiry job, or with two?
   - **Privacy.** Does any stored event, payload, admin page or log keep a checkout URL or a receipt address it should not?
   - **The app.** Can the owner or guest screen offer a payment the server would refuse? Is the copy present in all three languages?
   - **Tests.** Were any weakened? Check each rewritten test the write-up names: the change must be the new rule, not a loosened assertion.
3. Report only real, reachable problems. No style opinions.

## Output format
- One opening sentence.
- A table of round-3 findings 2 and 7, round-4 findings 1 to 10, then B and C: # | Status | Note.
- A table of new findings: Severity (Blocker / Should-fix / Nit) | File and line | Concrete failure | Suggested fix.
- What you could not check.
- A final line: "Overall verdict: approve" or "Overall verdict: reject".
