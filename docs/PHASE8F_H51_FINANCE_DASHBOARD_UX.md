# Phase 8F-H5.1 — Finance control-plane dashboard and operator UX

Contract consumed: `h5.v1`. Starting main:
`c8c60a7dcc3e7e538f96e924bc08b4e4a3337015`.

H5.1 adds two read-only HTML pages over the H5 Finance control plane and the
words a Finance operator reads them in. It adds no accounting. Every amount,
count, bucket, stage and verdict on screen is a value
`apps/finance/control_plane` returned; nothing is summed, subtracted,
converted, estimated or re-derived in a view, a template, a filter or a script.
A total H5 does not publish does not appear.

## What was added

| File | Role |
|---|---|
| `apps/admin_panel/finance_dashboard.py` | The two views and the view model. Chooses which H5 values to show, builds drilldown links, formats cents and frozen minor units. No arithmetic on money. |
| `apps/admin_panel/finance_dashboard_labels.py` | Operator wording for H5's vocabulary: modes, rails, liability buckets, rail stages, reconciliation comparisons, warnings, data issues, drilldown fields. Unknown keys fall back to the de-underscored raw key, so a state this file does not know stays visible. |
| `templates/admin/console/finance_dashboard.html` | The snapshot page. |
| `templates/admin/console/finance_rows.html` | The drilldown page. |
| `templates/admin/console/_finance_filters.html` | The scope form, shared by both. |
| `templates/admin/console/_finance_kpis.html` | One row of KPI tiles. |
| `apps/core/static/shiptrip/admin.css` §12c | `st-ledger-strip`, `st-kpi*`, `st-integrity`, `st-fin-*`, `st-unknown`, `st-provider*`. |
| `apps/admin_panel/console_urls.py` | Two routes. |
| `apps/core/templatetags/shiptrip_admin.py` | The navigation entry and its flag gate. |
| `apps/finance/tests/test_phase8fh51_finance_dashboard.py` | 27 presentation, access, privacy and filter tests. |

The H5 JSON endpoint `/admin/finance/control-plane/` is unchanged and still
serves the same snapshot to any other consumer.

## Routes, permission and feature flag

| Route | Name | Purpose |
|---|---|---|
| `/admin/finance/dashboard/` | `admin_console:finance-dashboard` | One bounded snapshot. |
| `/admin/finance/dashboard/rows/` | `admin_console:finance-rows` | The contributing rows of one metric. |

Both are `GET`-only (`POST` answers 405), `never_cache`, and served
`Cache-Control: private, no-store`.

Access is the existing fresh `view_finance_summary` capability on an active,
non-banned staff account: **Finance and Super Admin allowed; Support, Ops and
Trust denied with 403.** The capability is checked *before* the flag, so a role
that may not see Finance data learns nothing from the flag's state.

`FINANCE_DASHBOARD_ENABLED=false` answers **404** on both routes — a disabled
dashboard is indistinguishable from a route that was never built — and
`FLAG_GATED_ROUTES` in `shiptrip_admin.py` removes the navigation entry, so the
console never advertises a destination that answers 404. The view's own check
stays authoritative; the navigation gate only keeps the shell honest.

No payout-execution flag is touched by H5.1.

## The scope form

Ten controls, all of them filters H5's `Scope` already validates. The form
sends nothing H5 does not accept, and H5 rejects an unknown or repeated filter,
which the page renders as a refusal rather than raising.

| Control | Sends | Notes |
|---|---|---|
| Environment | `mode` | Required by H5. Defaults to the deployment's own configured credential mode (`default_mode()`), falling back to `test` — the page never claims to be showing real money it cannot confirm. |
| Period | `period` | Today / Last 7 days / Last 30 days / Custom range. |
| From, To | `start`, `end` | Only with `period=custom`. |
| Funding provider | `provider` | Stripe / Chargily. |
| Payout rail | `rail` | Stripe EUR transfer / Manual DZD transfer / Unclassified rail. |
| Payout state | `state` | The Payout status enum, rendered with its own display labels. |
| Rail stage | `operation` | H5's `OPERATION_STAGES`, in lifecycle order, in operator words. |
| Holds and disputes | `held` | Any / Held or disputed / Not held and not disputed / Disputed only. |
| Settlement currency | `currency` | EUR / DZD. |
| Reference | `search` | Exact `ST-<Deal>`, `TR-<Traveler>` or payout/order UUID only. No name, email or account search — H5 supports none, and none was added. |

No date arithmetic happens in the browser or in the view. H5 resolves the range
in **Europe/Paris**, refuses a range over 366 days or one ending in the future,
and the page renders that refusal. The applied scope is echoed above the
figures as human-readable chips; an operator is never shown a stored enum.

## Metric → H5 definition mapping

Every tile names one key in `snapshot["metrics"]` and prints H5's own
`definition` sentence underneath it. The **Basis** column below is the only
authored classification on a tile: H5's `time_basis` names database columns,
which is the wrong register for a KPI, so a tile says whether the period
selector moves the number and the full `time_basis` string is printed verbatim
in the metric dictionary at the foot of the page and on the drilldown header.

| Section | Tiles (H5 metric keys) | Basis |
|---|---|---|
| Headline | `gross_funded`, `recognized_revenue`, `traveler_outstanding` | period, period, current |
| Funded volume | `gross_funded`, `net_funded`, `deposits_collected`, `boost_funded` | period |
| ShipTrip economics | `recognized_revenue`, `pending_earnings` | period, current |
| Traveler obligations | `traveler_outstanding`, `payouts_settled`, `payout_returns` | current, period, period |
| Exposure | `connected_funds`, `bank_in_transit`, `externally_committed`, `source_reserved` | current |
| Refunds | `refunds_outstanding`, `refunds_requested`, `refunds_processing`, `refunds_finalized`, `refunds_applied`, `refunds_failed`, `deposits_refunded` | current except the three finalised/applied/deposit figures |
| Disputes and holds | `user_disputed_payouts`, `held_payouts`, `provider_disputed_payouts`, `provider_disputes` | current |
| Posting deposits | `deposits_held`, `deposits_credited` | current, period |
| Liability by state | `liability_*`, all eleven exclusive buckets | current |
| Liability by rail | `snapshot["payouts"]` groups | current |
| Rail stages | `snapshot["rail_operations"]` groups | current |
| Providers | `snapshot["providers"][*]` | mixed, as H5 returns |
| Reconciliation | `snapshot["integrity"]` | current |

`net_funded` is the one tile with no drilldown: H5 composes it from
`gross_funded` and `refunds_applied` and drills through those two components.

### Volume is not revenue

The page opens with three named amounts, not a grid of equal tiles: **Money
processed**, **ShipTrip earned**, **Owed to Travelers**, each with a sentence
saying what it is and is not. Funded volume carries "This is volume, not
income" on its own tile; Traveler liability carries "Never ShipTrip income".
Traveler payable is never placed in the earnings section and never rendered in
the same group as recognised revenue.

## Rails

`rail_operations` is rendered as one section per rail, ordered along that
rail's real lifecycle rather than alphabetically, with a one-line meaning under
every stage.

* **Stripe EUR** keeps *Transfer committed*, *Money at the connected account*,
  *Connected balance not yet available*, *Bank payout processing*, *Bank payout
  in transit* and *Paid* as six distinct stages. Transfer and bank payout are
  never collapsed, and the connected-account stage says in words that the
  Traveler has not been paid.
* **Manual DZD** keeps *Waiting for Finance*, *Claimed by Finance*, *Being
  sent*, *Transfer sent*, *Paid*, *Blocked or failed*, *On hold* and
  *Disputed*, each with a count, a canonical EUR amount and the frozen DZD
  settlement amount.
* Both known rails always render; an idle one shows an empty state so it reads
  as checked rather than as a section that failed to load. The unclassified
  rail is an anomaly bucket and appears only when it holds something.

### DZD presentation

The dinar column is the sum of stored `payout_amount_minor` on the instructions
in that group, exactly as H5 returned it. It is never a conversion of the euro
column, no aggregate is priced at one rate, and euros and dinars are never
added. Where a group has an instruction with no stored amount, H5 returns
`amount_dzd: null` with a `dzd_missing_count`, and the cell reads **Partial**
with the count of instructions that have no stored amount. The frozen rate
belongs to an individual instruction and is shown on drilldown rows
(`1 EUR = 260 DZD`), not on an aggregate. Every rail section states that euro
is the canonical accounting currency and the dinar figure is what a person is
instructed to send.

## Providers, balances and costs

Each provider card shows only what H5 attributes to that provider by actual
source: funded, refunds outstanding, refunds finalised, funding reserved. The
`provider_filter_semantics` sentence H5 returns is printed above the cards, and
each card links to the same dashboard scoped to that provider, which is how the
platform-wide metrics (connected funds, transit, disputes) are narrowed.

**Provider balance is rendered as "Provider-reported balance unavailable"**,
with a sentence saying ShipTrip makes no balance request, because H5 returns
`{"status": "unavailable", "amount": null}`. No `€0` balance card exists.
**Provider costs render as "Not available"** with the same reasoning; no
percentage is assumed anywhere. Per-category earned revenue prints H5's own
`revenue_categories.reason`.

## Unavailable, partial and unknown

`value()` in the presenter is the single place a metric result becomes text.
`amount_eur_cents is None` becomes **Partial** when H5 says `status=partial`
and **Not available** otherwise, styled as a muted sentence rather than as a
number so it cannot be skimmed as a small amount. Where H5 supplies
`known_amount_eur_cents`, the tile adds "Known so far: €x". A genuine zero
prints as `€0.00`. No null is ever coerced to zero.

## Reconciliation

The verdict sits directly under the page title, before any amount, because a
total nobody can trust is worse than no total. `ok` / `warning` / `mismatch`
map to three toned banners with a plain-English summary; a mismatch is
bad-toned and the detail section repeats it. The detail table shows each
comparison's reported value, independent record, signed difference, mismatched
row count and an Agrees/Disagrees verdict, with a sentence explaining what each
comparison actually proves. Unbalanced transactions, record-level data issues,
conditional warnings, the revenue basis, the provider-cash statement, the
count of ledger rows attributed from an agreeing pair and H5's provenance block
are all surfaced. No SQL, model name or internal query appears.

A mismatch does **not** disable the dashboard or the application: the figures
stay on screen under an explicit warning that they are unreliable.

## Legacy / unknown disclosure

H5 publishes no residual count of legacy/unknown-mode rows per environment, and
the `legacy_refund_ledger_mode_attributed_from_agreeing_refund_and_capture`
warning cannot fire in the current deployed configuration. H5.1 therefore does
**not** invent a number for it and does not hard-code any attempt id or amount.
Instead the refunds section carries a standing, generic disclosure — "These
totals cover the *TEST* environment only. Historical rows whose environment was
never recorded are reported on their own and do not appear in any figure above"
— with a link that switches the whole dashboard to `mode=legacy_unknown`, where
a banner explains the cohort and H5's own `legacy_mode_not_test_or_live`
warning renders. H5's `limitations` list, which includes the legacy-mode
statement, is printed verbatim in the page footer.

**Recorded limitation:** a per-mode count of residual legacy/unknown rows would
make this disclosure quantitative rather than standing. That belongs in the H5
backend, not in frontend accounting logic.

## Drilldowns

Every KPI that H5 exposes as a contributing-row query links to
`/admin/finance/dashboard/rows/?metric=<key>` carrying the current scope. Rail
stages link with `metric=payout_operations` plus that group's `rail` and
`operation`, exactly as the H5 contract specifies. Liability buckets link with
`metric=liability_<bucket>`. No aggregation is repeated client-side; the
drilldown page loads only the drilldown.

Columns are built from the fields H5 returns for that row kind, ordered by a
fixed preference list and labelled in operator words. Payout rows carry the
payout UUID, Deal and Traveler display references, canonical amount, frozen
settlement, state, bucket, stage, rail, funding mix and hold/dispute markers.
The page prints the metric's total for the whole scope, H5's `time_basis`, and
H5's own exclusion sentence.

**Sensitive fields are absent by construction**: H5 never serialises them and
H5.1 requests nothing beyond H5's projection. No CCP, RIP, bank account,
provider payload, secret, evidence URL, identity document, delivery code, name
or email appears on either page. A test asserts this over four drilldowns and
the snapshot page.

### Link to operational detail

Where a row is a Payout and the viewer holds `view_payouts`, the row links to
the existing H3/H4.1 payout detail screen; where it is a refund and the viewer
may see refunds, it links to the refund detail screen. The primary key comes
from H5's own `<KIND>-<pk>` staff display reference, so the link costs no extra
query and exposes nothing new. **No execution action exists on either H5.1
page**: no create, refund, reverse, mark-paid, FX change, destination change,
ledger edit or provider mutation. The dashboard observes and navigates; the
dedicated payout screens act.

## Pagination

H5's bounds are used as-is: page 1–100, page size 1–100 (default 50), stable
primary-key ordering, `has_next`. The page shows the current page, the page
size, Previous/Next where they exist, and the metric's whole-scope total so an
operator is never left guessing whether the visible rows are all of them. An
out-of-range page size is refused by H5 and rendered as a 400 page.

## Empty, loading, error and unauthorised states

| Condition | Result |
|---|---|
| Invalid filter, bad date range, unknown or repeated key | 400 page with H5's message, the filter bar preserved with the offending values, a reset link, and **no stale figures on screen**. No traceback. |
| `OperationalError` from the bounded query | 503 page saying the snapshot did not finish and no financial state changed. |
| Empty drilldown | "Nothing contributes to this figure in this scope", naming the metric, environment and range. No zero-filled table. |
| Idle rail | Per-rail empty state. |
| Integrity mismatch | Bad-toned banner, figures kept, application untouched. |
| Not Finance or Super | 403. |
| Flag off | 404, and no navigation entry. |

There is no loading state because there is no client-side fetch: the server
renders one snapshot per request.

## Performance and refresh

One `build_snapshot` per dashboard request, one `drilldown` per rows request,
inside H5's own `REPEATABLE READ, READ ONLY` transaction with its 10-second
statement timeout. No per-KPI request, no N+1 browser call, no polling, no
`setInterval`, no meta refresh, no auto-reload; a test asserts all of that and
caps the dashboard at well under 160 queries. Refresh is an explicit link that
re-issues the same GET.

## Visual system and accessibility

The pages use the existing console design system — parchment surfaces, ink,
terracotta reserved for "a person must look at this", Fraunces on titles, DM
Sans on data, hairline borders, no gradients — and add one CSS section (§12c)
rather than a parallel style. No chart is drawn, because H5 publishes no
authoritative time series and a drawn trend would be an invention.

Verified: semantic `<main>`, one `<h1>`, `aria-labelledby` on every section,
`<th scope="col">` on every table, visible focus from the console's global
`:focus-visible` ring, filter labels bound with `for`/`id`, no two filter
options sharing a label, every state carried by text as well as by tone, and
**no click-only `<div>`**: a KPI tile that drills is an `<a>`, a table row that
opens carries a real anchor plus the console's existing delegated row surface,
and each drilldown row's open link names its Deal rather than repeating one
generic label.

Light and dark themes both verified. The console is English by product
decision, so H5.1 adds no translation; the RTL and FR/AR payout labels
inherited from H4.1 are untouched and continue to render on their own screens.

## Tests

`apps/finance/tests/test_phase8fh51_finance_dashboard.py` — 27 tests on
PostgreSQL, reusing H3's `build_stripe_payout` and H4's `build_manual` so the
pages are rendered against data the real services produced:

* Finance and Super allowed; Support, Ops and Trust denied, on both pages.
* Flag off ⇒ 404 on both routes and no navigation entry; flag on ⇒ 200 and the
  entry appears.
* Read-only: no form, no CSRF token and no button but Apply inside `<main>`;
  `POST` ⇒ 405; `no-store`.
* Headline, funded, revenue, pending, liability and bucket figures equal the
  snapshot's own values.
* Rail stages and frozen dinar amounts equal the snapshot's groups.
* A partial provider dispute renders **Partial** with its known subtotal; the
  provider balance and provider cost render as unavailable, never as `€0`.
* Integrity renders both `ok` and `mismatch`, the mismatch induced the same way
  H5's own reconciliation test induces it.
* Holds, ShipTrip disputes and provider disputes counted separately.
* Filters reach the backend, are echoed in words, and travel into every
  drilldown link.
* Five invalid filter shapes each answer 400 with a message and no stale figure.
* Drilldown totals, references, payout-detail link, pagination bounds, refused
  page size, unknown metric, empty drilldown.
* No sensitive field on the snapshot page or four drilldowns.
* Legacy cohort disclosed and reachable; the legacy banner renders in that mode.
* One snapshot per page, no mutation query, no polling primitive.
* Both known rails always present; no two filter options share a label.

H5's own 28 tests were re-run unchanged and pass. The console navigation
regression suites (`test_phase8d_console`, `test_phase8fg2_console_rows`,
`test_phase6a_admin`, 56 tests) pass. No accounting code changed, so the H3/H4
financial suites were not re-run.

## Known limitations

1. **No per-mode residual count for the legacy/unknown cohort.** The disclosure
   is standing rather than quantitative. See above.
2. **No time series.** H5 publishes none, so the dashboard has no trend chart.
3. **Provider balances and provider costs are unavailable, not zero.** They stay
   unavailable until an authoritative source exists.
4. **Per-category earned revenue is unavailable**, because the existing
   settlement corrections do not retain the category split.
5. **A mixed-funded Deal appears in both provider cohorts.** H5 says so and the
   page prints H5's non-additivity sentence rather than splitting the award.
6. **The metric dictionary prints H5's `time_basis` and `exclusion` strings
   verbatim**, which name database columns. They are fine print under an
   operator-worded label, and they are the authoritative text.
