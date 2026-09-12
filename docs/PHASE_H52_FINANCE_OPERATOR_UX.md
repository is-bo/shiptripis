# Phase H5.2 — Finance operator experience

H5 built a financial control plane. H5.1 rendered it faithfully. This phase
changes who the rendering is addressed to, and changes nothing else.

Nothing in `apps/finance/control_plane/` was touched. No metric was renamed, no
definition rewritten, no state machine altered, no permission widened. Every
figure on every screen below is a value H5 published, printed verbatim.

---

## 1. Why this phase exists

An independent UX audit scored the H5.1 dashboard **~2.5 / 10**. Measured
against the deployed TEST environment at 1440×900 and at 375px, the complaints
were all reproducible:

| Audit complaint | Measured |
|---|---|
| Too long | **7,241 px — 8.0 screens** at 1440×900 |
| Too dense | **63 money values**, 26 KPI tiles, 6 tables, 59 table rows |
| ~30 competing KPIs | 13 eyebrow-labelled sections, **18 `<h2>`s** |
| ~10 global filters | **11 form controls** above the first number |
| Queues buried | first work queue at **2,839 px** (3.2 screens down) |
| No "what needs me?" | no attention surface existed at all |
| Terrible at 375 px | **14,814 px — 18.2 screens**; filter wall alone **926 px**; first queue at **6,783 px**; 4 tables scrolling sideways at 720–835 px inside a 311 px column |

The first screen at 375px contained the brand, the welcome line, two nav rows, a
breadcrumb, a title, a paragraph of prose and the top of the filter form. Zero
financial information. Zero actionable content.

The page behaved like an accounting control-plane report handed to an operator.
It had to become a Finance operations workspace backed by that same control
plane.

---

## 2. The governing principle: operations and audit are different readers

The redesign separates two audiences that H5.1 had sharing one screen.

**Operations** — things needing human awareness or action: payouts waiting for
Finance, failed and returned payouts, blocked payouts, holds, disputes, refunds
needing intervention, payouts worth monitoring.

**Accounting / audit** — reconciliation comparisons, the recognition partition,
ledger conservation, provider attribution, mode provenance, liability
decomposition, historical definitions, stated limitations.

Both are necessary. Neither is served by competing with the other for the same
viewport. Operations got four destinations; audit got one, and kept everything.

---

## 3. Information architecture

| Destination | Route | Answers |
|---|---|---|
| **Overview** | `/admin/finance/dashboard/` | What needs me today? |
| **Payouts** | `/admin/finance/payouts-hub/` | Where is any payout, and which are stuck? |
| **Manual DZD** | `/admin/finance/manual-dzd/` | Which dinar transfers need a person? |
| **Refunds & disputes** | `/admin/finance/exceptions/` | What went sideways, and whose is it? |
| **Reconciliation** | `/admin/finance/reconciliation/` | Can I prove this is right? |

`finance-dashboard` keeps its url name through the redesign. It is what the
feature flag, the navigation and every existing bookmark address; what changed
is the page behind it. The H5 drilldown (`finance-rows`) is unchanged and is
still reached from the reconciliation surface and from every queue.

Navigation lives in `NAVIGATION` in `apps/core/templatetags/shiptrip_admin.py`.
With the flag on, Finance shows: Overview · Payouts · Manual DZD · Refunds &
disputes · Reconciliation · Payments. With the flag **off**, the five new
destinations disappear and the raw Payouts, Refunds, Payout accounts and Ledger
queues come back — see `FLAG_SUPERSEDED_ROUTES`. The console never loses its
route to a payout because a reporting flag is off.

---

## 4. The Overview — five zones

| Zone | Contents |
|---|---|
| 1. Head, health, scope | page title, TEST/LIVE chip, date range, one-line Finance health, Refresh, and three scope controls |
| 2. Needs attention | actionable counts, strongest element on the page; a calm single line when empty |
| 3. Work queues | Manual DZD (waiting / claimed / sent + CTA) and Stripe EUR (processing / ready / action required) |
| 4. Money | exactly three figures |
| 5. Recent Finance activity | six lines from the console's own audit log |

**Above the fold at 1440×900** an operator sees zones 1–3: whether Finance is
healthy, whether anything needs attention, both work queues, and the one-click
entry into Manual DZD. That was achieved by removing information, not by
shrinking type — body text, tile values and headings are all the same sizes or
larger than H5.1's.

### What the Overview no longer carries

Moved to **Reconciliation**, intact: the liability-by-state table, the
rail/funding permutation table, the six-comparison reconciliation table, ledger
conservation, data issues, warnings, provenance, provider exposure cards,
provider balance and provider cost unavailability, the metric dictionary, the
snapshot limitations block, and the legacy/provenance explanation.

Moved to **Payouts** and **Manual DZD**: the Stripe stage table and the manual
DZD stage table, as cohorts with rows rather than as stage counts.

Moved to **Refunds & disputes**: the seven-card refund lifecycle and the four
disputes-and-holds tiles.

Nothing was deleted.

---

## 5. State → operator label mapping

H5's 25 operation stages and 11 liability buckets are unchanged. The operational
surfaces group them; they do not rename them in the database, and the
reconciliation surface still prints the accounting register.

### Payout cohorts (`PAYOUT_COHORTS`)

| Cohort | H5 stages |
|---|---|
| Needs attention | `blocked_or_failed`, `failed_or_returned`, `held`, `disputed`, `blocked`, `inconsistent` |
| Ready | `waiting_for_finance`, `claimed`, `eligible`, `scheduled` |
| Processing | `transfer_processing`, `transfer_sent`, `processing`, `connected_funds`, `connected_balance_pending`, `bank_processing`, `bank_in_transit`, `transfer_committed_or_unknown`, `sent` |
| Not due yet | `pre_delivery`, `protection`, `awaiting_release` |
| Paid | `settled` |

Every stage appears in exactly one cohort and no stage is dropped — asserted by
`test_every_h5_stage_lands_in_exactly_one_payout_cohort`.

The brief suggested four cohorts. There are five, because `pre_delivery`,
`protection` and `awaiting_release` are neither work nor history — folding them
into "Processing" would have said something false about money that is simply not
due yet.

### Manual DZD cohorts (`DZD_COHORTS`)

| Cohort | H5 stages |
|---|---|
| Waiting for Finance | `waiting_for_finance` |
| Claimed / in progress | `claimed`, `transfer_processing` |
| Sent / awaiting settlement | `transfer_sent` |
| Completed | `settled` |

Blocked, held and disputed dinar payouts are in none of the four. They are named
in a banner at the top of the queue with a link, rather than being quietly
absent.

### Wording (presentation only — no backend enum renamed)

| H5 / H5.1 register | Operator register |
|---|---|
| Gross funded volume | Money processed |
| Recognised ShipTrip revenue | ShipTrip earned |
| Outstanding Traveler liability | Owed to Travelers |
| At connected accounts | Held in Stripe |
| Bank payout in transit | Sent to bank |
| Bank payout processing | Bank transfer processing |
| Connected balance not yet available | Stripe balance not yet available |
| Transfer committed, outcome unconfirmed | Committed, outcome unconfirmed |
| Bank payout failed or returned | Returned by the bank |
| Rail | Payout method |
| Integrity | Finance health / Reconciliation |

---

## 6. Financial authority boundaries

Three rules, inherited from H5.1 and tightened by one.

1. **No arithmetic on money.** An amount is shown only where H5 published that
   exact figure. A cohort spanning more than one published figure carries a
   **count and no amount** — adding two of H5's amounts together would publish a
   total H5 did not. Asserted by
   `test_a_cohort_spanning_two_published_figures_shows_no_amount`.
2. **Counts may be grouped.** H5's stages and buckets are disjoint by
   construction, and a count of rows is not a financial total. Cohort badges are
   sums of counts and nothing else.
3. **Null is not zero, and read-only stays read-only.** Every view is GET; none
   reaches a service that can move money. `Pay now`, `Mark paid`, `Refund` and
   `Reverse` remain on the audited screens that own them.

### The one direct model read

`_operational_facts` in `finance_operations.py` reads exactly two columns —
`eligible_at`/`created_at` and `block_reason` — for the payouts already on
screen, keyed by the primary keys H5's own `row_reference` carries. A queue
needs how long something has waited and what is blocking it; H5 publishes
neither, and neither is money. It reads no amount, and no figure on any page
comes from it. It is the only direct model query in the module and is fenced and
documented as such.

### Query cost

One `build_snapshot` per page render (~70 queries, as H5.1), plus one bounded
`drilldown` per stage in the selected cohort (one or two), plus one
`Payout.objects.filter(pk__in=…).values(...)` over at most 50 rows, plus one
indexed `AdminAuditLog` read of 6 rows on the Overview. No polling, no
per-widget fetch, no JavaScript on any of the five pages.

---

## 7. Progressive disclosure

| Level | Where |
|---|---|
| 1 — is anything wrong, what do I do | Overview zones 1–3 |
| 2 — which payouts, in what state | Payouts, Manual DZD, Refunds & disputes |
| 3 — prove it reconciles | Reconciliation |
| 4 — the exact contributing rows | the H5 drilldown, from any stage group |

Finance health follows the operator onto every page as one line. The
six-comparison table is never rendered outside Reconciliation. A **mismatch** is
the one state permitted to escalate: it becomes a page-level alert on every
operational surface, because a total nobody can trust is worse than no total.

---

## 8. Filters

H5.1 opened every Finance page with ten controls. The Overview now carries
three: **Environment**, **Period** (four links — Today / 7 days / 30 days /
Custom, with the date inputs appearing only on Custom), and **Find payout or
Deal**.

The other seven were not folded into an accordion. They are gone from the
Overview and placed where they answer a question the operator is actually
asking:

| Page | Contextual filters |
|---|---|
| Payouts | Payout method, Holds and disputes |
| Manual DZD | Holds and disputes |
| Refunds & disputes | Funding provider |
| Reconciliation | none beyond scope |
| Drilldown (`finance-rows`) | the full H5 filter form, unchanged — it is the audit surface |

Lookup remains exact-reference only (`ST-…`, `TR-…`, or a payout/order UUID).
No PII search was added.

`cohort` is this module's own query key and is deliberately never passed to
`Scope.parse`, which refuses a filter it does not recognise rather than
answering a different question from the one asked.

---

## 9. Responsive strategy

A queue is rendered as a **list**, not a table, at every width. CSS grid aligns
the list items into columns from 1080px up, so a desktop reader gets the
scannable grid a table would have given them; below 760px each payout becomes a
card. Nothing on an operational page scrolls sideways.

The reconciliation page keeps wide tables with bounded horizontal scrolling,
because comparing down a column is exactly what its reader is doing.

At 375px the source order is the reading order and is therefore the contract:
**action needed → work queues → money → health/supporting**. Asserted by
`test_action_needed_comes_before_the_totals_in_source_order`.

---

## 10. Manual DZD detail (H4.1)

Every H4.1 safety property is preserved unchanged: masked account information,
the explicit audited reveal, chèque barré evidence, operator claim with an
optimistic lock, transfer instructions, the separate receipt, the sent-versus-
paid distinction, settlement attestation, the timeline, and the frozen
EUR/DZD/rate.

Two changes:

* **The current required step is now dominant.** The audit found the ordered
  step list at 3,031px on a phone — below the amount, the destination and the
  cheque photo, so a new operator met four cards of context before meeting a
  single instruction. The list stays where it is; a "Your next step" banner now
  states the current step directly under the page state, above the context that
  explains it.
* **Back to the queue, preserving the cohort.** The breadcrumb and a footer link
  return to the Manual DZD tab the operator came from. The cohort travels as a
  query parameter and is validated against the queue's own four keys before
  becoming a URL — an arbitrary `?next=` echoed back as a link would be an open
  redirect on the one screen in this product that must not have one.

**There is deliberately no "next waiting payout" control, and no batch
payment.** Chaining straight into the following transfer is how a person sends
the right amount to the wrong Traveler. Each payout stays independently
selected, reviewed and attested.

---

## 11. Permissions

Unchanged. All five destinations are gated by
`has_all_admin_permissions(user, "view_finance_summary")` and then by
`settings.FINANCE_DASHBOARD_ENABLED`, in that order — so a role without Finance
learns nothing about the flag's state, and a disabled dashboard is
indistinguishable from a route that was never built.

Finance and Super Admin reach all five. Ops, Support and Trust/Verification
reach none. No permission was added, broadened or re-scoped. Links out to
operational surfaces continue to be gated by those surfaces' own capabilities —
a queue row only becomes a link to payout detail when the reader holds
`view_payouts`.

---

## 12. Recent activity

The feed reads `AdminAuditLog`, the immutable record the console already writes
whenever an operator changes a payout or a refund. No new event model was
created and no financial total is derived from it.

Access events — `payout_evidence.viewed`, `payout_profile.revealed`,
`payout_account.dashboard_opened` — are deliberately excluded. They are
recorded, and they belong in the audit log; a dashboard line naming who opened a
Traveler's bank details is surveillance, not finance activity.

The feed is wrapped so that it can never break a page: if the log cannot be
read, the zone is omitted rather than faked.

---

## 13. Before / after

| Problem | Resolution |
|---|---|
| 8 screens at 1440×900 | Overview zones 1–3 above the fold; the whole page is short |
| 18 screens at 375px | list-based queues, three scope controls, no table explosion |
| 11 global filter controls | 3 on Overview; the rest moved to where they apply |
| ~30 equal-weight KPIs | 3 named amounts, plus counts that only appear when non-zero |
| Queues buried 3 screens down | two work lanes in zone 3, DZD one click from Overview |
| No "what needs my attention" | zone 2, strongest element on the page |
| Reconciliation on the homepage | its own destination, complete and unweakened |
| Stripe internals exposed | Overview shows processing / ready / action required only |
| Backend jargon everywhere | operator register on operational pages, accounting register on audit |
| Serious issues in the same beige as paid history | severity is tone + count weight + a stated owner |
| Manual DZD buried in a stage table | a first-class four-cohort queue with safe row detail |
| No next action on the DZD detail | "Your next step" banner above the context |

---

## 14. Remaining limitations

* **Payout profile / setup blockers are not separable on the Overview.** H5
  collapses every `block_reason` into the single `blocked` bucket and never
  serialises the reason string, so "payouts blocked by a profile problem" cannot
  be counted from the snapshot. The queue rows do show the blocker, read from
  the payout record via `_operational_facts`, and the Overview honestly says
  "Payouts blocked or failed" rather than inventing a split H5 does not publish.
  Publishing `block_reason` in the H5 payout drilldown would be a small backend
  change and is the right fix.
* **Claim ownership is cohort-level on the queue.** H5 exposes the `claimed`
  stage but not the claiming operator. The queue says a payout is claimed; the
  detail screen names who holds it.
* **`failed_or_returned` carries a count and no amount** on the Overview,
  because it can span both payout methods and H5 publishes no single figure for
  the pair. The Payouts hub shows the per-method amounts.
* **No provider balance and no provider cost figure** exists anywhere, because
  H5 makes no provider balance request. Those cards were removed from daily
  operations entirely; the limitation is stated on the reconciliation page,
  where it matters.
* **No trend, no chart.** H5 publishes no time series and a drawn trend would be
  an invention.

---

## 15. Tests

`apps/finance/tests/test_phase8fh52_finance_operator_ux.py` covers: the role
matrix across all five destinations; flag behaviour in both directions; the
five-section ceiling; the absence of the reconciliation table and metric
dictionary from the Overview; the three-control scope bar; one-click DZD; the
three amounts in operator words with the jargon absent; health as one line;
the calm state and the raised state; cohort completeness over every H5 stage;
the no-invented-amount rule; the payout hub cohorts and links; the DZD four
cohorts and safe row fields; exception ownership; all six comparisons and a
visible mismatch on Reconciliation; source order at narrow widths; no table on
any operational page; no sensitive field on any page; unknown rendered as words;
a bad filter answered rather than raised; and no polling.
