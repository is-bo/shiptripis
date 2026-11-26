You are an independent second-pass reviewer. This review is read-only: do not write, commit or push code, and do not comment on GitHub. You may read files and run read-only git commands.

This is the **fourth review** of pull request #67, "G1: guest checkout without a browser-session dependency", in this repository (is-bo/shiptripis). Run `git fetch origin` first if a commit is missing.
- You rejected head `4337d9caff2d8e9961e3410f2e20343deb8ec5d4` (five findings), `f1fe5659fef2851c07473458fefc53ffa3a298d2` (six findings) and `d99c8384882a3eaddae94d164e4bb3588acb4662` (three blockers, six should-fix). Your third report is `docs/handoff/astra/results/g1-astra-round3-result.md` on `main`.
- The new head is `1643afc1857ea3c0c0ba807f440e18db03c7bf94`. The fixes are one commit, `0b088be`, directly on `d99c838`; `1643afc` on top only records the local suite results in the write-up. `main` had only docs since, so it is not merged in.
- Compare `d99c838..0b088be` for this round's fixes, and `origin/main...1643afc1857ea3c0c0ba807f440e18db03c7bf94` (three dots) for the whole package.
- Backend code is under `backend/monolith/` (mostly `apps/finance/services.py`, `jobs.py`, `operations.py`, `serializers.py`, `providers/`); the app under `mobile/lib/`. The package is section 4 "G1" of `docs/WASSLA_PHONE_TEST_2_PLAN.md`. The write-up, with a "Fourth-pass review" section, is `docs/PHASE_G1_GUEST_CHECKOUT_CSRF.md`.
- Rules are in `CLAUDE.md`. Money is a "strongest model" area there.

## Lead instructions the fixes had to follow (treat as correct)
- **B:** never leave a superseded attempt payable. Ask the provider to close the old checkout (Stripe Checkout Session expire, Chargily expire) and supersede only after the provider confirms. Otherwise answer a neutral, translated "a payment is already being made, try again later" conflict. Never hold the database lock across a slow provider call in a way that can deadlock. The same rule applies when the same payer switches rail or amount.
- **A:** prefer removing the raw URI and Referer from proxy logs over regexes.
- **C:** recover with the original idempotency key and the exact original parameters.

## The rule claimed now
Migration `finance 0036` adds three columns to the payment attempt:
- `checkout_request`: the provider create request, frozen when the attempt is written. The first call and every recovery send exactly it (`_new_checkout_request`, `_checkout_request`).
- `opening_until`: the claim. The request that creates an attempt owns it for `CHECKOUT_OPENING_WINDOW` (2 min); a request that recovers it claims it the same way. Nothing else moves it, except `_release_opening_claim` by the claim's own holder when the provider was unreachable.
- `close_requested_at`: written under the order lock before any provider is asked to close the checkout. An attempt carrying it is never handed out again, its own payer included, and any later request may finish the close.

Claimed invariant: a checkout URL leaves the server only in the answer of a checkout call (owner JSON, guest JSON, guest page redirect), and only after it is stored on an open attempt. So an attempt with no checkout stored was never handed out.

## Your round-3 findings and the claimed fixes
1. **(blocker) The expiry job ended an attempt its provider could still collect.** `handle_attempt_expiry` now calls `expire_checkout_attempt`: under the order lock, `processing` is left alone (`attempt_settling`), a handleless attempt ends now unless its claim is live (the job defers), one with a checkout gets `close_requested_at`; then with no lock held the provider is asked to close it, and only `CHECKOUT_CLOSED` expires it. Collected or collecting: left to that payment (`attempt_collecting`). A provider error is retried by the job.
2. **(blocker) Reconciliation replayed a create, and order history showed every URL.** `handle_provider_reconcile` never repeats a create (handleless: defer while open, else `checkout_never_handed_out`); `queue_payment_reconciliation` refuses a handleless attempt on every rail. `recover_checkout_attempt` stores only on an attempt still `created` and handleless, and closes the recovered checkout otherwise. `PaymentAttemptSerializer` no longer has `checkout_url`; only `CheckoutAttemptSerializer` (the checkout endpoint's answer) has it. The app's "Continue your payment" calls the checkout endpoint again.
3. **(blocker) Refused-recovery set, job bypassing the claim, Stripe key in use.** The set is gone. A stored checkout is always examined first. After a refusal an attempt is abandoned only if it is still handleless and its `opening_until` still equals the refused claim. The job no longer recovers. Stripe's 409, and any `idempotency_key_in_use`, raise `ProviderUnavailable`.
4. **(should-fix) Lost create answer.** On Stripe and the mock, `ProviderUnavailable` from create keeps the attempt `created` with its key and releases the claim; a failed create marks the attempt failed only while it is still handleless. Recovery is tried for `CHECKOUT_RECOVERY_LIMIT` (10 min from `created_at`), then the attempt is abandoned.
5. **(should-fix) Recovery rebuilt the request from current settings.** Frozen `checkout_request`. The mock refuses a reused key with other parameters.
6. **(should-fix) Close intent lost with the request.** `close_requested_at`, as above.
7. **(should-fix) Receipts-off webhook wrote an address back.** `reconcile_attempt` keeps a provider address only when the attempt already had a guest address from checkout.
8. **(should-fix) The app showed a generic failure.** `checkout_in_progress` maps to "A payment is already under way" on the owner payment screen and the guest pay screen, in English, French and Arabic. A settling payment no longer offers "Continue".
9. **(should-fix) Two-tap test and mock.** The race test requires distinct redirects, one per attempt, and each replaced attempt cancelled and closed at the provider. The mock answers "collected" for a checkout processing at the provider.

Tests rewritten to the new rule are listed in the write-up ("Tests rewritten to the new rule"). The write-up says each new test fails with its fix removed (10 server mutations, 2 app mutations).

## What to do
1. Mark each of your nine round-3 findings, and B and C, **fixed**, **partly fixed** (say what is missing) or **not fixed**.
2. Hunt for **new**, real, reachable problems in the fixes. In particular:
   - **One checkout that can collect.** Can two checkouts that can collect exist for one order at any moment, on any rail, through any path: checkout (owner, guest JSON, guest page), expiry job, provider reconcile job, staff reconcile, webhooks, recovery, order or deal cancellation? Can an attempt be superseded or expired without its provider confirming the close, other than one whose URL never left the server? Is the "URL never left the server" invariant true everywhere (serializers, admin views, emails, events, logs)?
   - **The three columns.** Can the `opening_until` claim be stolen, lost, extended or released by someone other than its holder? Can `close_requested_at` be cleared, or an attempt carrying it be handed out? Is `checkout_request` ever rebuilt, or different from what was first sent?
   - **Expiry.** Can an order stay stuck in `checkout_in_progress` longer than its provider's own expiry when the provider is reachable? Does the job's retry budget end with a checkout still payable and the attempt open forever? Is any lock held during a provider call, including through a caller's transaction?
   - **Provider contracts.** Stripe expire (only `open` sessions), Stripe idempotency (409 in use, 400 for different parameters, replay of a first 500 answer), Chargily expire (only `pending`; 400 if already expired, 403 for other statuses). Can a refusal be misread as closed, or a transient error as a permanent refusal?
   - **Privacy.** Does any response, status code, timing or page text depend on the receipt address a holder sends? Does order history, or any other payload, still carry a checkout URL or a guest's receipt address?
   - **The app.** Does the owner or guest screen ever open a URL it did not just get from a checkout call? Is the new copy present in all three languages?
   - **Tests.** Were any weakened? Do the new tests assert real outcomes? Check each rewritten test the write-up names: the change must be the new rule, not a loosened assertion.
3. Report only real, reachable problems. No style opinions.

## Output format
- One opening sentence.
- A table of findings 1 to 9 from round 3, then B and C: # | Status | Note.
- A table of new findings: Severity (Blocker / Should-fix / Nit) | File and line | Concrete failure | Suggested fix.
- What you could not check.
- A final line: "Overall verdict: approve" or "Overall verdict: reject".
