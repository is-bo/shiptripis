# K2 — Admin UX Foundation & Workflow Continuity

Status: implemented on `codex/k2-admin-ux`; independent Gemini verification,
CI, merge, and Railway TEST deployment are pending. Baseline was exact `main`
SHA `5f562a96c8176a5d3aa15ecf73234201520fae73`.

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
check, Prettier CSS parsing, and diff checks passed. The full Django suite,
finance regression suite, role matrix, and independent 1440×900, 1280×800,
1024×768 screenshots belong to Gemini. No K2 screenshot or Gemini verdict is
claimed yet. CI, schema drift, merge, Railway TEST deployment, and post-merge
branch cleanup must follow owner-returned Gemini GREEN, not this handoff.

No migrations, payout eligibility/amount/instruction changes, KYC policy
changes, dispute economics changes, capability changes, provider-mode changes,
or Railway architecture changes were made. Persistent shared Redis remains
deferred under the K1 record.
