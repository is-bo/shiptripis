# K2 — Admin UX Foundation & Workflow Continuity

Status: **released to Railway TEST**. The application implementation reviewed by
Gemini and deployed is `c47eac7f62ceabda67981a4bcbc87225d974c970`.
The test-only CI compatibility follow-up is
`87a4c530eb2eb4cbb2863f40ccad4ca61235a086`; PR #12 merged to `main`
at `bf8dd8b2e92caa8737d1be289265e53aa4805b72`. Baseline was exact
`main` SHA `5f562a96c8176a5d3aa15ecf73234201520fae73`.

## Findings addressed

The Admin console now keeps operators at the relevant section after a normal
POST → redirect → GET, carries only known queue context, and uses one shared
pagination contract. Manual DZD payout and dispute detail have compact sticky
in-page navigation. The existing manual payout domain steps remain the source
of truth; the dispute guidance is page-specific and has no effect on actions.
Finance Scope Apply, controls, filters, reset links, file inputs, button
hierarchy, table overflow, focus/anchor positioning, and the Person subnav
receive scoped visual treatment. A console 403 explains lack of access while
retaining HTTP 403. No capability or domain service was changed.

## Server-rendered continuity

`apps.admin_panel.utils.admin_url`/`admin_redirect` reverse a named internal
route, accept route kwargs, validate a simple stable fragment, and copy only
caller-specified query keys whose values pass an explicit rule. They do not
accept a caller-provided destination, `next`, or arbitrary query string. The
rules are scoped per workflow: manual payout accepts only configured DZD
cohorts; verification accepts the applicable queue's known q/status/page
filters; disputes accept their known q/status/attention/user_id/page filters;
staff accepts a positive `edit` row id. Invalid or unknown values are dropped.

Manual payout redirects: review → `#st-proof-head`; prepare, begin, release →
`#st-transfer-head`; receipt → `#st-receipts-head`; hold and clear hold →
`#st-holds-head`. Forms also target their section for validation/error renders.
The queue return link and valid `?cohort=` survive each lifecycle redirect.
Sensitive destination reveal remains a deliberately request-scoped POST render:
PRG would require persisting decrypted destination data or putting it in a URL.
It is not cached or transferred to query/session state.

Dispute evidence, timeline, resolution, and ledger have stable IDs. Preview
stays on the resolution form through its form fragment; execute/state update
redirect near resolution; evidence actions return to evidence. KYC and Flight
Proof have evidence/decision/history IDs and return to decision after approval
or rejection. Detail links and return links carry safe queue filters; a
decision does not make the detail GET disappear when the old queue status no
longer matches. Settings saves redirect to the pricing, boost, FX, or provider
section. These sections are not native `<details>` elements, so no extra open
state is required. Staff role/access actions return to an anchored row with a
validated `edit` query that reopens that row's `<details>` panel.

## Shared controls and pagination

`shiptrip_admin.admin_querystring` clones the active `QueryDict`, replaces only
`page`, and delegates URL encoding to Django. `_pagination.html` supplies
accessible previous/next labels, the current page, disabled states, and
canonical button styling. It is used by the generic console table (including
verification, payments and disputes), People, payout reviews, and identity
checks. Finance's specialized pagination contract remains unchanged.

CSS remains under the ShipTrip console root for the broader button foundation;
it does not globally restyle Django Admin or plugin controls. Legitimate but
high-consequence workflow completion uses a strong confirmation style, while
reversal/revocation and KYC rejection retain danger semantics. Native file
pickers remain operable with associated labels. Focus styling and visible
horizontal overflow are retained. Person tabs scroll horizontally near laptop
width instead of wrapping into awkward rows.

## Verification and release gate

Codex short tests: 14 new K2 tests passed; 39 of 40 directly affected legacy
Admin/Finance tests initially passed, and the sole visibility regression was
corrected and its exact test rerun passed. Django `check`, 14 Admin template
compilations, Ruff on changed Python, Python compilation, static web/edge
check, Prettier CSS parsing, and diff checks passed.

Gemini independently returned **GREEN** on exact application SHA `c47eac7`,
reporting 85 Admin tests, 104 disputes/KYC/accounts/core tests, 46 deployment
safety tests, role-matrix checks, and 84 viewport plus 54 full-height
screenshots at 1440×900, 1280×800, and 1024×768. Its SQLite full suite had
2,119 passed, 173 skipped, and 29 PostgreSQL-vendor-only failures that it
classified as baseline-equivalent. This is Gemini's reported result, not a
Codex rerun.

PR #12's first PostgreSQL CI run exposed two test-only compatibility issues:
the new reveal test lacked the unhashed staticfiles test override, and a
legacy read-only Finance assertion recognized only the former unclassed Apply
markup. Commit `87a4c53` changed those two test files only; the application
tree remains exactly the Gemini-reviewed one. Fresh PR CI passed all six jobs,
including 2,287 Django tests (34 skipped), Ruff, migration/schema drift,
production/static/edge checks, Flutter, Go race/unit, and Go real-Redis
integration. PR #12 merged as `bf8dd8b`.

The existing Railway service received the clean `c47eac7` working tree as
TEST release `v1.0.0-rc.47+c47eac7`. Deployment
`5b0f10e6-2661-45af-8c92-ac930a8b6e10` reached **SUCCESS**. `/healthz`
returned HTTP 200 with that release; `/readyz` returned HTTP 200 with database,
migrations, and rate-limit cache ready. A read-only signed-cookie smoke against
the deployed container returned HTTP 200 for Admin, Finance Overview, Manual
DZD, Disputes, KYC, Flight Proof, People search, Payments, Staff, and Settings;
unauthenticated public GETs redirected to login. No financial POST was made.
The Railway environment is named `production`, but the existing ShipTrip
service remains TEST-configured: Stripe expected mode `test`, Chargily sandbox
base, mock payments off, DZD execution off, embedded Redis still deferred.

No migrations, payout eligibility/amount/instruction changes, KYC policy
changes, dispute economics changes, capability changes, provider-mode changes,
or Railway architecture changes were made. Persistent shared Redis remains
deferred under the K1 record.
