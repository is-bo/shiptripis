# Brief AUDIT: one area audit (used six times, once per area)

**Reader:** Claude Opus, extra-high effort. Read only: you change no code and open no pull
request.
**Starts:** when Parts A to C of the plan have merged. The lead gives you one area from the table
below and the commit of `main` to read.
**Read first:** `CLAUDE.md`, the product invariants and engineering rules above all;
`docs/handoff/builders/README.md` rules 9 to 11; the plan (`docs/handoff/LOOP_END_PLAN.md`)
sections 3.2, 3.3, 8 and 10; `.claude/skills/ponytail-audit/SKILL.md`.

## 1. Your job

Audit one area of Wassla like the developer who just inherited it and will be called when it
breaks. Use `/ponytail-audit` on your area. This is the one audit of that area before the phone
test, and there is no second pass, so go deep where a mistake costs the most.

## 2. The areas

| Area | Where | Look hardest at |
|---|---|---|
| Money | `backend/monolith/apps/finance`, `boosts`, the money parts of `deals` and `matching` | Double charge, lost debit, wrong payout, idempotency, what happens when a provider answers late or twice |
| Deals, codes, disputes | `apps/deals`, `handover`, `disputes`, `problems`, `ratings`, `parcels/tracking.py` | The delivery code rules, the 30-minute lock, the 48-hour payout wait, who can move a deal |
| Accounts and messages | `apps/accounts`, `kyc`, `notifications`, `chat`, and `backend/services` (Go) | Who can sign in as whom, what a push or an email reveals, what is delivered twice or never |
| Listings and location | `apps/trips`, `parcels`, `matching`, `discovery`, `locations`, `routing` | Every public payload against its allowlist, exact locations before funding, matching results |
| Staff console | `apps/admin_panel`, `admin_helper`, `core/permissions.py`, the Django admin files | Every staff action against its permission, its reason and its audit row; pages that repeat each other |
| The app | `mobile/lib` | What hides behind the bottom navigation, wrong states after an error or offline, a screen that offers what the server refuses, slow lists |

## 3. Rules for the report

- Assume the load of a young marketplace: hundreds of members at once, several server processes,
  phones on weak networks.
- **Every finding needs a concrete case:** this input or situation leads to this wrong result.
  No case, no finding. No style opinions.
- A finding may assume ordinary use and one fault, as plan section 3.2 says. Say which.
- Data from before the app was live does not exist. Parked scope is not a gap.
- Check the plan's accepted risks (section 10) before you report: a listed risk is a decision.
- Also report, under "Lean": code that should not exist, two helpers that do the same thing, a
  function that mixes separate jobs (split by job, never by line count), a slow path with its
  cause. For the staff console: say whether the finance pages (`finance/control-plane/`,
  `finance/dashboard/`, `finance/payouts-hub/`, `finance/exceptions/`, and the older
  `finance/payments/`, `refunds/`, `payouts/`, `ledger/`) show the same things twice.
- At most twenty findings, ranked: must fix, should fix, nice to have. If you left smaller ones
  out, say how many.
- Propose the smallest fix for each, and prefer a fix that deletes.
- Say plainly which parts you did not read.

## 4. What you hand back

One file, `docs/handoff/audit/<AREA>.md`, on a branch the lead names, in the format of the
audit skill: what the area does, the findings with their four parts each, the verdict, and "not
checked". Nothing else. The planner turns the findings into at most one fix package per area.
