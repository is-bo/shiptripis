# Railway → Hetzner runbook (V3 only — not executed in V1)

The authority is one PostgreSQL database, not a pair of independent live copies.
No DNS, Railway, provider or data-transfer action below is authorized by V1.
Assign a release operator, database operator, finance observer and rollback owner.
Record timestamps, SHA/digests, active BusinessSettingsVersion, counts and approvals
without logging credentials, personal data, signed URLs or delivery codes.

## 1. Inventory and rehearsal

* Confirm the actual deployed Railway SHA, PostgreSQL major/extensions, migrations,
  collation and volume/backup support. Repository history is not live evidence.
  This checkout's K6 report records embedded ephemeral Redis as an exception;
  inspect the actual topology in V3 rather than assuming a managed service exists.
* Inventory all database roles, jobs, queues/groups/pending work, FCM results, mail
  outbox, provider events, retry/manual-action items and unresolved financial work.
  Record row counts, migration leaves, unique provider references, ledger debit/
  credit invariants, account balances, reservation consistency and oldest due jobs.
  Use existing permissioned Admin/deep-health, Redis inspector and finance runbooks.
  Do not invent new authoritative SQL adjustments to balance differences.
* Securely transfer existing Django/JWT, handover/outbox encryption, payout keyring
  (including old keys), account fingerprint and provider signing secrets. Changing
  them can invalidate sessions or make historical evidence/codes unreadable. Keep
  old provider references/idempotency records and active policy versions unchanged.
* Keep private S3 objects and bucket references in place. Test private credential
  scopes and authorized short-lived evidence URLs from the VPS without bulk-copying
  customer files. Verify provider encryption/access policies and signed URL clocks.
* Confirm Firebase/OAuth project IDs and client audiences match the unchanged
  mobile app. Record the API URL baked into installed clients. If it is a Railway
  provider hostname, moving a new custom domain does **not** update those clients:
  mobile-origin changes/release are an explicit later approval gate. V1 does neither.
* In a disposable restored database rehearse the exact reviewed migrations and
  old-image compatibility, then run financial invariants, production checks, auth,
  KYC/proof, notification/email outbox and webhook dedup/replay tests with TEST-only
  credentials. Prove offsite backup upload/download, checksums, decryption and
  isolated restore from an independent operator host. Record achieved RPO/RTO.

## 2. Prepare idle destination

Provision only after owner approval. Bootstrap and prove SSH/console recovery,
firewall (IPv4/IPv6), resource/disk headroom and Docker restart behavior. Build/retain
reviewed images. Configure domain and secrets but leave the Hetzner application,
finance worker and daily timers **stopped**. A running restored app is a writer
even if DNS does not point to it. PostgreSQL and Redis may be initialized in
isolation. Do not import an old database over an existing live destination.

The gateway/domain/mobile/webhook plan must be resolved before cutover. Lower DNS
TTL in a separately approved window if applicable. Obtain certificates/connectivity
only during V3; local `tls internal` is not a public production certificate.
Record provider webhook URLs, both Stripe signature scopes, Chargily TEST base,
email sending status and Firebase state. No LIVE finance or email activation is
bundled with the move. V2 email preparation is a separate prerequisite.

## 3. Quiesce the single source

1. Freeze business policy changes, Admin money operations, manual payout/refund
   execution and external jobs. Announce a maintenance window. Disable ingress
   writes/checkouts and control webhook delivery/retry according to each provider’s
   contract. A nominal read-only UI is insufficient: HTTP reads may have effects.
2. Drain in-flight HTTP/provider work, inspect running DB transactions/jobs and
   record financial reconciliation points. Pause **all** source producers, consumers
   and schedulers, including finance/lifecycle/releaser, Go FCM/email, gRPC and
   external cron. Do not start a replacement worker on Hetzner during this drain.
3. Capture Redis transport consistently while it is still reachable. Preserve
   stream entries, group last-delivered IDs, pending-entry lists, retry metadata and
   FCM result stream; consumer names may change but pending work must be reclaimed.
   A Redis RDB/AOF transfer preserves these structures; copying only `XRANGE` rows
   does not. Verify Redis major compatibility before loading on the target.
4. If Railway still embeds Redis, **do not terminate its combined container before
   the queue checkpoint is secured**. Use an approved platform-supported private
   control/export procedure that pauses producers/consumers without losing Redis,
   or first complete the existing controlled shared-Redis cutover runbook. If no
   consistent export is available, require a proven drained queue (`XLEN`/`XPENDING`
   and recovery results) or remain NO-GO. Email PostgreSQL outbox survival does not
   justify discarding pending FCM work. Never expose Redis publicly or use FLUSH.
5. Stop the source application/remaining writers; confirm transactions settled or
   rolled back. Leave source PostgreSQL/Redis available to the approved export
   operation, but no application can write. Capture the **final** PostgreSQL custom
   dump and encrypted offsite snapshot, checksums and migration metadata. Take the
   platform snapshot too if supported; it is an additional checkpoint.

Exact Railway pause/export commands depend on its actual V3 plan and private
access capabilities. Absence of those capabilities is a migration blocker, not
permission to lose queue state. Rehearse the whole pause/export/restore sequence
on TEST with pending messages before the maintenance window.

## 4. Restore and compare

Verify backups using the standalone isolated restore first. Restore the final
dump into a **new, empty destination** with an approved explicit database import
procedure; the V1 `vps restore` command deliberately cannot target production.
It is a recovery-verification tool, not a production-overwrite switch.

Transfer the quiescent Redis checkpoint to the destination persistent volume using
a reviewed one-time restore with Redis stopped and correct ownership. Do not copy
live AOF files mid-rewrite. Verify AOF/RDB loading, stream/group/pending state and
authenticated `noeviction` config. Recovery clients must reclaim pending entries
and observe existing stale/retry policies, not reset consumer groups to `$`.

Before starting app processes compare source/destination financial totals,
provider-event/attempt/order uniqueness, frozen FX/economic snapshots, encryption
decryptability, customer/account counts, reservations, migration graph, queue
IDs/pending counts and outbox statuses. Document every intentional difference.
Run the migration plan exactly once, with the session advisory lock, and verify
catalogue digest without retiring missing rows. Source remains stopped.

## 5. Activate one writer and route traffic

Start only the destination application and check every child, `/healthz`,
`/readyz` status **and component checks**, permissioned deep health, Admin source
controls/authorization, static/legal routes and WebSockets. Enable the one set of
maintenance/backup/monitor timers after reviewing their schedule. Prove backup and
alert failure detection. No monitor/metrics port is opened publicly.

Use approved DNS/gateway and webhook cutover steps; account for cached DNS and
provider retries. The old Railway endpoint must remain non-writing throughout.
If old clients need a compatibility gateway, it must forward to the single
authoritative destination and its forwarded-header/security contract must be
reviewed; never reactivate an independent source app as a shortcut.

Watch scheduled job claims/recovery, notification stream lag/pending, email backlog,
provider event deduplication, auth/session continuity, storage evidence access,
connection pools, HTTP error rate and real resource/latency metrics. Use controlled
TEST identities and no real-money operations. Treat old undelivered SMTP/FCM work
as existing obligations; do not manually re-send or re-enqueue everything.

## 6. Rollback rules

Before any destination authoritative write, rollback may route back to the frozen
source after proving the final source DB/queues still represent the checkpoint.
Stop the destination’s app and timers first; then activate exactly one source.

**After any destination financial/database write, restarting the stale Railway
database is unsafe.** Quiesce destination and either fix forward or reconcile/
transfer the destination’s authoritative state back through a new reviewed window.
Include provider events, external side effects, Redis transport and outbox records;
an old dump cannot undo a refund/payout or a delivered message. Finance observer
and rollback owner must approve. Image rollback alone is possible only after
old-code/new-schema compatibility was rehearsed; never run reverse migrations or
restore over the live database as an automatic recovery.

Rollback/stop triggers include invariant/count mismatch, missing decryptability,
queue loss, wrong financial mode, missing workers, inaccessible private storage,
invalid TLS/hosts/origins, unauthorized Admin access, repeated 5xx, exhausted DB
connections, backup failure or materially worse latency. Keep source backups and
immutable images until an owner-approved retention decision. Decommissioning
Railway is a later explicit operation, never part of V1.
