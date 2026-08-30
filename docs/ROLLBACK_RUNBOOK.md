# ShipTrip Rollback and Recovery Runbook

Rollback is an incident decision, not a reflex. Preserve financial and lifecycle history, keep inbound provider reconciliation running, and prefer a forward fix when database or real-money state has advanced beyond the previous application’s contract.

## Decision and containment

Declare incident owner, finance observer, database operator, communications owner, current/previous release IDs, start time, impact, and last known safe transaction. Capture health, logs/request IDs, deployment events, PostgreSQL locks/connections, scheduled-job/provider-event/outbound-message backlogs, and active business-settings version without copying secrets or PII.

Immediate reversible containment:

1. Activate a new audited business-settings version disabling affected providers/boosts or other optional new work. Do not delete credentials or webhook endpoints for money already in flight.
2. If abuse is involved, restrict the affected edge routes while preserving health, authenticated operations, and provider webhooks.
3. Pause only the specifically unsafe worker if it is causing repeat harm. Durable `ScheduledJob`/outbox rows preserve obligations; record the pause and continue monitoring backlog.
4. Do not edit ledger/provider-event/payment rows, mark jobs succeeded manually, clear Redis as a “fix,” or expose codes/tokens to diagnose.

## Application rollback

An application rollback is allowed only when the previous image is compatible with the **currently applied schema and data**.

- Compare migration state, release contract, environment variables, API compatibility, and provider event shapes.
- Redeploy the exact previously verified image digest, not a branch rebuild.
- Keep the current database and object storage; do not restore a database merely to roll back code.
- Require `/healthz` and `/readyz`, deep health, auth/read-only smoke, worker progress, and finance reconciliation after rollback.
- Static web/gateway can roll back independently only if routes/security headers/API expectations remain compatible. A future mobile artifact is never remotely rolled back; preserve backward API compatibility and use the release manifest to identify affected builds.

For the combined Railway topology, rolling back the application image also rolls back Django, all Go services/workers, Caddy, and static web. Verify every child, not just gateway liveness.

## Migration decision rules

Never automatically run `migrate <previous>` after a failed deploy. Financial, ledger, provider-event, audit, dispute, handover, payout, and job history must not be casually reversed after real transactions.

Use this order:

1. If no migration ran, roll back application only.
2. If only additive/backward-compatible migration ran, keep schema and roll back to a compatible application or forward-fix.
3. If a migration ran and the previous application cannot tolerate it, deploy a forward compatibility patch.
4. Consider a reverse migration only when its reverse operation was reviewed/rehearsed, no affected production data was written, it loses no evidence/history, and database plus finance owners approve.
5. If data corruption occurred, stop affected writes, preserve forensic copies, restore into a new database, reconcile transactions after the recovery point, then execute an approved cutover. Never overwrite the sole production database in place.

## Provider-safe rollback

- Disable Stripe/Chargily for **new checkout** through an audited settings version.
- Keep webhook verification secrets/routes and reconciliation workers active for existing attempts, late success, refunds, and duplicates.
- Do not change EUR canonical amounts or historical DZD FX snapshots.
- Compare provider dashboard settlements with `PaymentAttempt`, `PaymentProviderEvent`, `PaymentOrder`, ledger transactions, refunds, and payouts. Raise manual action rather than guessing.
- For Stripe refunds, retain stable idempotency keys and poll/retry the existing obligation.
- Chargily refunds remain an audited manual settlement with mandatory external reference.
- A dispute continues to freeze payout; a rollback must not shorten the 48-hour protection window or release a payout early.
- If email is unsafe, set `EMAIL_ENABLED=false` but retain `OutboundMessage`, `ScheduledJob`, and the transactional encryption secret until pending secret messages are resolved.

## Worker and Redis recovery

Stopping a worker does not cancel an obligation. After the safe application is running:

1. Requeue stale running jobs with the existing recovery command/path; do not create duplicate job keys.
2. Inspect pending, retrying, failed/manual-action jobs by kind and oldest age.
3. Restore Redis and restart stream consumers. PostgreSQL state remains authoritative.
4. Run the published-event/outbox sweep, inspect missing delivery receipts, and redrive only through idempotent domain handlers.
5. Verify delivery-code release, protection expiry, refund/reconcile, payout eligibility, rating reveal, boost expiry, and email queues advance.

## Database restore/cutover

Restore only from a verified encrypted backup into a **new** Railway/PostgreSQL database. Validate PostgreSQL version compatibility, migration state, row counts, foreign keys, unique provider-event IDs, balanced ledger transactions, payment order invariants, open disputes/payout freezes, scheduled jobs, and application smoke tests.

Calculate the recovery-point gap. Reconcile every provider payment/refund/payout and any handover/dispute event created after the backup. A restored database that omits a provider success can double-charge or strand money if exposed without reconciliation.

Cutover requires explicit database, finance, security, and incident approval. Update secrets/reference variables atomically, deploy the known-compatible application, require readiness/deep health, then reopen traffic gradually. Retain the old database read-only for the approved forensic/retention period.

## Validation and closure

- [ ] Correct release is visible in health/logging.
- [ ] Database/migrations ready; no abnormal locks/connection exhaustion.
- [ ] Provider events, jobs, refunds, payouts, and email obligations converge.
- [ ] No duplicate ledger facts or provider events; money totals reconcile.
- [ ] Exact locations, evidence, KYC, and codes remain authorization-protected.
- [ ] Admin changes are granular and audited.
- [ ] Public/API security headers and rate limits are restored.
- [ ] Controlled smoke test and soak period complete.

Record timeline, root cause, releases/settings versions, backup/recovery point, reconciliation evidence, residual manual actions, customer/legal communications, and follow-up owners. Rotate any credential only if exposure is suspected or policy requires it; coordinate rotation so verification/decryption of in-flight obligations is not destroyed.
