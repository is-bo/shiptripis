# J1.3 — ParcelRequest lifecycle alignment

Completed 2026-09-15. **Gemini, CI and TEST release checks passed.
J1.3 PASS. J2 has not started.**

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

CI [35004301377](https://github.com/is-bo/shiptripis/actions/runs/35004301377)
passed all six jobs at `96a2d9a667aa9a1913e1b2f9ea6693a4e38ae305`.
Results were read only after the user reported completion. Full Django:
**1,984 passed, 34 skipped**; schema drift, Flutter, Go race/unit, real-Redis
integration and production/static checks passed. This release checkpoint adds
documentation only, preserving the CI-verified source.

## Completed TEST release

Main was fast-forwarded and pushed to
`8f4026ccc1dc812e03a4502e6bd24729eac5e83d`; the phase branch was deleted locally
and remotely. A clean Git archive of that SHA was uploaded to the existing
ShipTrip Railway service. The final release-evidence commit changes docs only.

Deployment `1c858eb7-fba3-4b88-883c-f61486a40f72` reached **SUCCESS**.
Release: `v1.0.0-rc.33+8f4026c`. Railway's environment is named `production`,
but application payments remain TEST.

* Public `/healthz`: **200**, correct release. The initial workstation request
  timed out at 20 seconds; a bounded retry passed.
* Public `/readyz`: **200**, correct release; database, migrations and rate-limit
  cache all `ok`.
* Remote migration graph: **zero pending migrations**.
* All ten expected process types present: Gunicorn, Caddy, Redis, finance worker,
  reservation releaser, Django KYC gRPC and Go chat/notification/KYC/email.
* SHA-256 hashes of all seven changed runtime files match the exact uploaded
  archive, including Windows archive newline conversion.
* A read-only database transaction found seven stored-MATCHED historical
  requests correctly projecting COMPLETED; all seven serializer samples agree.
  Two awaiting-deposit, two cancelled and three open requests retain their states.
  No historical row was rewritten and no payment or lifecycle event was created
  by the release probes.

Only `RELEASE_ID` changed in service configuration; other variables were compared
before/after. Runtime confirms PAYMENTS_ENVIRONMENT=test, Stripe TEST,
STRIPE_CONNECT_EXPECTED_MODE=test, Chargily TEST, DZD execution false and email
disabled. No LIVE operation, browser, subagents, mobile change, Finance H5 work
or J2 work. Ignored evidence: `.tmp/j13-upload.json`, `.tmp/j13-deployed.json`,
`.tmp/j13-public-health.json` and `.tmp/j13-public-health-retry.json`.

Remaining J1.3 BLOCKER: none. MAJOR: none known. MINOR: existing deprecation
warnings and the documented raw historical-field limitation. Prior device/FCM
acceptance and LIVE cutover prerequisites are outside this bounded phase and
are not certified by it. The request lifecycle prerequisite is ready for J2.

**J1.3 PASS**

**Ready for J2? YES — request lifecycle boundary; J2 not started.**

