# J1.3 — ParcelRequest lifecycle alignment

Implementation checkpoint, 2026-09-15. **Gemini regression verification passed;
release acceptance pending CI, merge and TEST deployment. J2 has not started.**

Starting main: `32da931a8ae3ccb0187e96e0fd5c4af9d51e3721`.
Branch: `codex/j13-parcel-request-lifecycle`.

## Root cause and authority

Acceptance wrote `ParcelRequest.status=matched`; subsequent physical delivery
and completion transitions updated only Deal and capacity allocations. Direct
request consumers consequently kept seeing matched. J1.1's mobile workaround
reads Deal `activity_state`; it remains compatible and unchanged.

Deal lifecycle services and recorded handover facts remain the authority.
`apps.parcels.lifecycle.with_lifecycle` expresses the request projection once in
SQL. `sync_request_status` persists that same expression from Deal `_set_status`,
inside the existing request-graph/Deal lock and transaction. This adds no
independent transition service, timer, event, job, payout action, or state enum.

## Mapping and transition coverage

| Authoritative fact | Request status / effect |
| --- | --- |
| No linked Deal | Existing request status unchanged |
| Acceptance commits a Deal and reservations | Existing acceptance writes MATCHED |
| Payment required/retry, funded, recipient/pickup ready | MATCHED |
| Verified pickup; picked_up/in_transit/delivery_ready or pickup timestamp | IN_TRANSIT |
| Delivery confirmed/protection window or delivery timestamp | DELIVERED immediately |
| Existing Deal completion transition | COMPLETED |
| Dispute without delivery | Retain pickup-derived progress |
| Dispute after delivery | DELIVERED; dispute does not put the parcel back in transit |
| Dispute ruled performed, Deal COMPLETED without delivery timestamp | COMPLETED, matching I1 activity semantics |
| Funded cancellation/no-show/full or partial refund | CANCELLED, ahead of delivery/completion evidence |
| Unfunded cancelled/expired reservation without handover/completion evidence | Preserve existing request state; reservation release reopens MATCHED to OPEN |
| Explicit request cancellation/expiry | Remains terminal |

The shared Deal setter covers pickup, delivery, protection-to-completion, dispute
opening and resolution. Existing acceptance, reservation-release, funded
cancellation and no-show request writes remain in their established services.
Funding and delivery-code release require no additional request transition.

Delivery completion is separate from money settlement. Protection, payout
processing, payout setup and pending ratings never keep a delivered parcel in
IN_TRANSIT. COMPLETED uses the existing contractual completion decision, not
payout-paid or a new elapsed-time inference.

## Historical behavior and API/query consistency

No schema or data migration. No historical rows are mass-updated. Reads select
the latest Deal by creation time and primary key, so released older reservations
cannot override a subsequent match. Cancellation/refund precedence reuses I1
`CANCELLED_STATUSES`; delivery evidence reuses `COMPLETED_STATUSES`. Missing
funding alone does not erase a recorded handover when interpreting cancellation.
Recorded request progress is never downgraded by incomplete older Deal data.

Sender request list, public authenticated request detail, Django admin list and
status filters, and the admin request API use the projection. Status filters
run in SQL before pagination/limits. List annotations add no per-row application
queries; the correlated latest-Deal reads use the existing request foreign-key
index. Detail's existing coarse/exact location permissions are preserved.

Raw SQL and unannotated ORM historical reads still expose stored values; use
`with_lifecycle` for historical status consumers. New authoritative transitions
persist the aligned value for those direct consumers. Django admin edit forms
continue to expose the stored field; their list and filter show effective status.
Missing history is not fabricated or reconstructed from the current Journey.

Matching/discovery still requires stored OPEN; historical stuck MATCHED rows and
new IN_TRANSIT/DELIVERED/COMPLETED rows are excluded. Eligibility, capacity,
funding, pricing, provider code and Finance H5 performance are unchanged.

## Idempotency, races and review

Existing lifecycle guards handle duplicate pickup/delivery/completion events.
Equal projection values do not write `updated_at`. A stale in-memory Deal event
cannot replace current database authority or take ownership from a later Deal.
Refund/cancellation outranks prior delivery; incomplete data cannot regress
recorded request progress. Existing unfunded reservation reopening is intentional.
Repeated funded cancellation retains the existing safe refusal behavior.

The request is already locked before the Deal, so synchronization adds no new
lock order. The request update and immutable Deal event commit/roll back together.
No additional notifications, financial entries or delayed jobs are created.
Review covered authorization, exact-location privacy, replay, transaction
rollback, historical precedence, bounded query count and schema compatibility.

## J2 boundary

Unmatched eligibility remains the existing OPEN/compatibility contract.
Acceptance commits MATCHED atomically with the Deal/reservation. Cancellation
and explicit expiry retire the request; an unfunded reservation release may
reopen it under existing policy. J2 must decide its final Boost end rule at
match/commit, cancellation or expiry and explicitly account for rematching.
J1.3 neither implements Boost nor decides whether any prior Boost revives.

## Verification and release gates

Local focused PostgreSQL tests: **10 passed in 6.61 seconds** using existing
synthetic fixtures and TEST settings. Covers acceptance/rematch, real handovers,
delivery/completion, refund precedence, disputes before/after delivery, replay,
no regression, rollback, historical reads, API/admin filters and discovery
exclusion. The previously stopped local loopback PostgreSQL cluster was started;
no deployed database was used. Initial connection failures were infrastructure
setup failures. The final run has only the existing Django URLField deprecation.

Ruff checks pass; migration dry-run reports **No changes detected**; diff
whitespace check passes. No schema/sqlc contract regeneration is required.

Gemini verified exact implementation SHA
`75f82314555fef9e8a404482143fcef607fd754b`: **535 passed, 24 skipped, zero
failures/errors in 331.51 seconds**. The saved JUnit XML and execution log agree
with the returned report. Skips cover retired legacy matching writes. A fresh
local `shiptrip_j13_75f8231_verify` PostgreSQL database was created and migrated;
initial settings, airport and permission-group seed checks passed. Zero tracked
changes, no fixes, no provider calls and no deployed database access were
reported. Evidence: ignored `.tmp/j13-gemini-regressions.xml` and
`.tmp/j13-gemini-regressions.log`. This verification checkpoint changes docs only.

CI is now the next gate. After triggering CI, report its link and stop without
waiting or polling. Merge, branch cleanup and TEST deployment remain pending.
No current J1.3 healthz/readyz/worker/release result is claimed.

TEST only: no deployed runtime/configuration change, no LIVE action. Eventual
release must preserve PAYMENTS_ENVIRONMENT=test, Stripe TEST, Chargily TEST,
and DZD execution false. No browser, subagents, mobile changes, H5 work or J2.

Remaining BLOCKER: CI/release gates pending. No known implementation
MAJOR findings after focused review. MINOR: existing URLField deprecation and
the documented raw historical-field limitation.

**J1.3 FAIL — release acceptance incomplete at this checkpoint.**

**Ready for J2? NO**

