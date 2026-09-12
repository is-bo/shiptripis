# Pre-H8 Finance visibility and frozen DZD identity hardening

Starting main: `8311cd1ba6d235a9e4858405a5a2ab91d26d9f74`.
Branch: `codex/pre-h8-finance-identity-hardening`.
This closes the backend findings from H5.2 and H7. It does not enable H8,
change provider modes or authorize any money movement.

## Finance blocker contract

Every H5 payout drilldown row now includes these additive fields:

| Field | Contract |
| --- | --- |
| `block_reason` | Safe reason string or null; never the raw stored/provider message. |
| `needs_attention` | Boolean indicating an actionable blocking condition. Normal delivery/protection/arrival waiting and connected-balance deferral are not attention. |
| `attention_owner` | `traveler`, `finance`, `provider`, or null when the responsible actor cannot be determined safely. |

`payout_attention` in the existing backend mobile read module is the common
Finance/mobile classifier. It calls H2's `evaluate_readiness` for Stripe and
H4's `approved_profile` for DZD, using the payout's bound instruction rather
than the Traveler's current preference. Bank return/failure comes from the H3
disbursement allocation, never from a platform Transfer. Provider dispute status
uses the provider-event handler's existing open-status allowlist.

H5 loads only its already-selected page inside the same PostgreSQL repeatable-read,
read-only snapshot. Related accounts, review/identity records, bank allocations,
funding scopes and holds are loaded in batches. No provider API is called.
No schema, metric totals, ledger queries, filtering or authorization is changed.
Finance/Super permission and feature-flag gates remain in place.

### Precedence and ownership

One primary reason is returned deterministically:

1. Latest active (otherwise latest historical) bank allocation failed/returned:
   `payout_failed` / `payout_returned`, Finance-owned.
2. Final settlement/cancellation suppresses obsolete setup blockers.
3. Failed local payout: `payout_failed`, Finance-owned.
4. Active ShipTrip or provider dispute: `dispute_active`, owner unknown.
5. Frozen payout or scoped Finance hold: `payout_on_hold`, Finance-owned.
6. Other substantive stored gates: `payout_on_hold`, owner unknown. Stored text
   is deliberately not echoed, including unrecognized provider exceptions.
7. Bound destination readiness:
   - Stripe incomplete setup: `payout_setup_required`, Traveler-owned.
   - Stripe pending review: `payout_profile_under_review`, provider-owned.
   - Other Stripe readiness failure: `payout_profile_needs_attention`, owner unknown.
   - DZD profile awaiting review: `payout_profile_under_review`, Finance-owned.
   - DZD rejected/needs-attention/invalid reviewed authority:
     `payout_profile_needs_attention`, Finance-owned.
   - Missing destination: `payout_setup_required`, owner unknown; changing a current
     preference does not necessarily repair a frozen instruction.
8. `connected_balance_pending`: provider-owned waiting, `needs_attention=false`.
9. Unexplained blocked state: `payout_on_hold`, owner unknown. Otherwise null/false/null.

Profile/setup blockers are visible before delivery or protection expiry. Mobile
retains its temporal `protection_active` and `scheduled_arrival_pending` reasons
when there is no actionable blocker. Those normal waits are not Finance attention.
No new identity-specific reason code is necessary.

No bank details, CCP/RIP, masks, legal names, evidence references, identity documents,
Stripe raw requirements, provider exception strings, fingerprints or secrets are
added to H5. The three new fields contain only the closed safe vocabulary above.

### H5.2 compatibility

The existing queue presenter now reads `block_reason` from H5. The manual detail
presenter evaluates its approval badge against the funded snapshot too. Its direct Payout
read retains only waiting timestamps; it no longer reads a raw blocker column.
Templates, navigation, CSS and financial arithmetic are untouched.
This is the backend contract for a later truthful Overview count, not an Overview
redesign or a new aggregate counter. Consumers must respect H5 pagination and
`has_next`; a partial page must not be presented as a complete attention total.

## Funded DZD policy

The H7 failure occurred because `approved_profile` required the identity bound to
the review to have no successor today. Re-attestation appends a successor, so even
an unchanged funded destination stopped satisfying the same check used for current
profile setup. Release then wrote `payout_setup_required`, which the Traveler could
not repair through profile replacement.

`approved_profile(profile, funded_payout=payout)` now permits a narrow historical
interpretation. The payout must carry a timestamped versioned manual DZD snapshot;
the active instruction must still equal its original method version; the snapshot,
instruction and profile must agree on the original revision/method and Traveler.
The latest immutable review at or before `snapshot_at` must be approved, with an
attestation recorded by the review time and no successor at or before funding.
Successors recorded after funding alone do not invalidate that historical approval.
An intervening later approval does not erase the original approval-at-funding evidence.

The latest review must still be approved. An explicit adverse review, revocation
of the bound identity, invalid evidence, unapproved KYC or expired KYC still fails
closed. This exception distinguishes supersession from revocation; it does not
freeze every compliance check forever. An approved profile without qualifying
funded evidence continues to require current identity authority. Approval after
funding is supported under the existing current-identity rules, without inventing
an earlier approval time.

Release, manual preparation/execution and Finance/mobile projections use the same
funded interpretation. A stale stored setup blocker is cleared by the ordinary
locked release evaluator when its genuine cause is gone; the read model writes
nothing. Existing financial rows are not backfilled or rewritten by deployment.

## Current setup, replacement and security

Calls without a funded payout retain the latest valid identity requirement.
Funding now checks that live approval rather than trusting cached method status.
A successor already present at the new snapshot's timestamp cannot use the
historical exception. An inactive, unfunded or merely old profile gains no authority.

Replacement still creates an immutable method/profile version, requires new owned
evidence and current Finance review bound to an assigned Trust attestation. It cannot
make the old version current again or redirect existing payouts. Existing explicit,
audited precommit amendment rules remain unchanged; an amended instruction cannot
claim the original snapshot's historical exception.

The fix changes no financial amount, FX calculation, destination writer, provider
adapter, ledger writer, lock order, Trust capability, evidence permission or database
guard. Original method version, destination, EUR obligation and frozen FX are preserved.
H4 concurrency tests and H1 PostgreSQL history guards remain release evidence.

## Migration and verification

Schema/migration/backfill: **NO**. Existing append-only profile reviews, identity
attestations/supersession/revocation and immutable funding timestamp/version provide
the evidence. No approval timestamp is inferred or invented.

The focused test module reproduces the PAYOUT-7 sequence using synthetic evidence:
approve under A, fund, attest B, release with no setup blocker, replace the profile,
approve the replacement under B, and prepare/begin the original frozen instruction.
It checks future snapshots, rejection/revocation/expiry gates, Trust authorization,
database immutability, safe blocker precedence and bounded reads. Network calls are
refused by the test fixture; bank-return tests use the existing synthetic adapter.

The final local PostgreSQL batch passed **160 tests**: 21 new regressions, 26 H4,
28 H5, 40 mobile H6A, 34 H1 foundations and 11 H5.2 compatibility tests.
Ruff, Django system checks and diff whitespace checks passed. No full backend
suite was run locally. A recovered/stale local test database was replaced with
a dedicated task test database before the final consolidated run.

Release gates and deployed read-only verification results are recorded with the
implementation status and completion report. The real paid H7 payout is never
modified. H8 remains unstarted; this hardening removes these two backend prerequisites
without asserting that any LIVE payment configuration has been enabled.
