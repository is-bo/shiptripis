You are the **planner** for a new money package in this repository (is-bo/shiptripis): **C1 · Pay only in the traveler's currency (no conversion)**. This task is read-only: investigate and write an implementation plan. Do not write product code, commit, push, or comment on GitHub. You may read files and run read-only git commands (run `git fetch origin` first). Your final message **is** the plan, so write it complete, in plain English, and cite file:line.

## Read first
- `CLAUDE.md`: the authority order, product invariants, "Models" and the quality bar. Money is a "strongest model" area.
- `docs/WASSLA_PHONE_TEST_2_PLAN.md`:
  - section 1.3 (payouts);
  - the F1 and F2 package text;
  - section 5 (order);
  - section 6 owner answers, especially the new **Q5** (26 November 2026).
- `docs/SHIPTRIP_V1_SPEC.md`, the money sections: Chargily, Stripe, traveler payouts, FX. Also `docs/WASSLA_DISCOVERY_PRO_SPEC.md`, for anything it overrides.
- Backend code under `backend/monolith/apps/finance/`:
  - `payout_snapshots.py`: `choose_method`, `preflight`, and `create_snapshot` with its FX conversion;
  - `providers/__init__.py`: `available_providers` and `resolve_gateway_for_checkout`;
  - `services.py`: `start_checkout`, the deal-balance and posting-deposit orders, and guest checkout;
  - `payout_profiles.py` and `payout_mobile.py`.
- The mobile checkout and payment-method screens under `mobile/lib/`. Read them only to understand what the app asks the server.
- **Open PR #69** (F1, branch `origin/claude/f1-payout-availability`, being revised now). It also edits `payout_snapshots.py`, adding a funding/preference lock. Read `git diff origin/main...origin/claude/f1-payout-availability`.
- **Open PR #67** (G1, branch `origin/claude/g1-guest-checkout-csrf`). It edits `start_checkout`.
- C1 lands after F1. Plan on top of F1's interfaces and call out every overlap.

## The owner's rule
Ismail, 26 November 2026, verbatim: "they should only pay in what the traveler choses we dont convert money".

What this means:
- The traveler chooses how to be paid: euros, dinars, or both.
- The sender may pay only in a currency the traveler accepts.
- Wassla never converts money between what the sender pays and what the traveler receives.
- EUR integer cents stay the canonical record (a `CLAUDE.md` invariant). A dinar payment for a dinar payout uses one snapshotted rate on both sides, which is not a conversion of value.

Known gaps today. Verify them; do not trust this list.
1. A dinars-only traveler can be paid by card (Stripe, EUR), and `create_snapshot` converts to DZD at the admin rate.
2. `available_providers` lists every enabled rail without regard to the traveler's choice. So a euros-only traveler's sender is offered Chargily and is refused only at checkout ("This payout requires Stripe funding").

## What the plan must settle
1. **Every path where the payment rail and the payout rail can differ.** Cover:
   - deal balance;
   - the posting deposit (does a deposit go to a traveler at all?);
   - guest-link payments;
   - counters and re-funding;
   - mixed funding across several source orders;
   - refunds and unapplied payments;
   - re-snapshot on a preference change after funding;
   - manual DZD settlement;
   - Stripe Connect transfer.

   For each one, say what happens today and what the rule requires.
2. **Where enforcement lives.** One home for the rule, per the quality bar. Also cover:
   - how the payment-options answer is filtered for a given deal, guest payers included;
   - the stable error code when a payment is refused;
   - how the app learns the allowed options. This is the contract for F2, the phone package.
3. **Cases the rule does not answer yet**, as precise questions for Ismail (stop-and-ask, plan rule 1.7). At least consider:
   - Payout profiles switched off. The live server has `PAYOUT_PROFILES_ENABLED=false`, so no traveler has a preference. What may a sender pay with then?
   - A traveler with no preference yet when a sender wants to pay.
   - A traveler who changes preference after a proposal, or after funding.
   - A rail that is down (for example Chargily off) when it is the only accepted one.
   - The Wassla fee and the posting deposit. These are paid to Wassla, not the traveler. Does the rule apply to them?
   - Deals already funded under conversion. There are no real users, so probably none; say so.
4. **Exact changes.**
   - files and functions;
   - tests: real-thread race tests where money state is involved, and privacy tests for new payload fields;
   - migrations, if any (Django owns them; there is a schema drift gate);
   - helper knowledge files to regenerate (`apps/admin_helper/skill/knowledge/`);
   - doc updates: record the rule in the money section of `docs/SHIPTRIP_V1_SPEC.md`, and propose one product-invariant line for `CLAUDE.md`.
5. **Builder and order.**
   - Builder model and effort: Claude Opus, extra high, for money, unless you justify high.
   - Order relative to F1, F2 and G1.
   - Whether C1 should be server-only, with F2 consuming it.
6. **"Done when" lines**, and the independent second-pass checklist: races, authorization, idempotency, money.

## Output format (your final message)
1. A summary of the current behaviour, with a table: traveler choice × payment rail → what happens today → what the rule requires.
2. The implementation plan: packages, files, functions, tests, docs, builder model and effort, and order.
3. Questions for Ismail. For each one: the question in plain words, your recommended answer, and why.
4. Conflicts with F1, F2 and G1 in flight.
5. "Done when" lines and the second-pass checklist.
