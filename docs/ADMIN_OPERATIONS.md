# ShipTrip operations console

Phase 8D adds a task-focused Django admin surface at `/admin/`. It is for the
owner and the fixed Phase 6A staff roles; the backend capability checks and
audited domain services remain authoritative.

## Navigation and roles

The header is filtered to the signed-in staff member's capabilities:

- **Overview** answers “what needs attention?” with live queue counts.
- **Users** covers identity, verification state, restrictions and safe account
  context.
- **Verification** contains KYC and flight-proof queues and private evidence
review.
- **Marketplace** contains Delivery requests, ordered Journeys and Deals.
- **Disputes** keeps the case, evidence, participants, protection and money in
  one review flow.
- **Finance** contains Payments, Refunds, Payouts and Ledger/reconciliation.
- **Staff** is for fixed-role invitations and access changes.
- **Settings** groups pricing, deposit, FX and provider availability in human
  units.
- **System** shows safe health, worker, outbox and readiness signals.

Ops, Support, Finance, Trust / Verification and Super Admin see only the
destinations granted by `apps.admin_panel.permissions`. Raw Django model pages
are deliberately hidden from the main mental model; Super Admin can reach
them through the owner-only **Technical records** escape hatch when required.

## Verification workflow

Open **Verification → KYC review** or **Flight proofs**, filter to **Pending**,
and open a row. The detail page puts the applicant/Traveler, document or
flight metadata, canonical route, history and evidence together. **View
evidence** creates a short-lived authorized object-store URL and writes an
audit event; storage keys are never displayed. Trust-capable staff choose
**Approve** or **Reject**. A rejection requires a reason and every decision is
audited through the existing review service.

Image evidence is also previewed directly in the review screen through the
same authorized endpoint. PDFs and original-size images open in a separate
tab. General Support pages do not expose KYC documents or private dispute
statements. Historical rejected flight proofs do not override a valid
approval, but every flight leg must have an approval.

### Evidence stores are not all owned by the same key

KYC documents live in their own private bucket, and that bucket belongs to the
**Go KYC service's** credential — not to Django's. Everything else Django
writes (parcel item photos, flight proof, dispute evidence) lives in the private
media bucket Django's own key owns. Django reads the KYC bucket through the
`KYC_S3_*` credential the deployment already supplies to the KYC process; it is
not a new secret, and the KYC bucket stays private.

This mattered more than it sounds, because getting it wrong was invisible.
Producing a signed evidence URL is *local signing* — it never contacts the
store, so it succeeds with a credential that has no grant on the bucket. Django
was signing KYC objects with its own key, the URL was well-formed, and the
reviewer's browser was then refused. The console showed a broken image, which
looks exactly like a submission with no document attached.

So the review screen now **checks that the object can actually be fetched**
before it renders anything, and says which of the two situations it is in:

- *No evidence file was attached to this submission* — nothing was submitted.
- *Evidence is temporarily unavailable* — something was submitted and the
  document store could not be reached. The submission is intact, and a request
  reference is shown for engineering.

Neither message names a bucket, an object key, an access key or a provider
error; those stay in the logs with the same request reference.

## Disputes and finance

The **Disputes** queue shows age, Deal, parties, evidence count, status and
money at stake. The detail view includes the timeline, statements/evidence,
pickup/delivery and protection state, payment context and audit history.
Resolution is two-step: choose a resolution and **Preview consequence**; the
server settlement planner returns the exact Sender refund, Traveler payout and
ShipTrip fee; then explicitly confirm. The final write re-locks and re-plans
through the existing settlement service.

**Payments** separates provider charge/currency from the canonical EUR
obligation. **Refunds** show reason, requested/returned amounts, provider and
automatic/manual state. **Payouts** show reward, eligibility, hold reason and
method; manual settlement records external evidence rather than pretending to
send money. **Ledger** presents append-only transactions before technical
entries. No page changes V1 money rules or exposes a handover/delivery code.

## Staff and settings

On **Staff**, enter a work email, choose one fixed role and an expiry. The
one-time invitation is sent through the durable email queue; its token is never
shown in the browser. Owners can see pending invitations, revoke/replace them,
change an existing role and disable sign-in. Self-disable and Super Admin
guardrails are enforced by the service layer.

On **Settings**, pricing accepts percentages and EUR amounts rather than basis
points/cents. The page explains commission, deposit bounds, floors, boosts and
the calculated €30.00 example. The Chargily field is `1 EUR = ___ DZD`; the
server stores micros and snapshots the rate only on new attempts. Policy rows
also read out the 30-minute delivery-code buffer and 48-hour payout protection
window. Every change creates an immutable, audited settings version. Provider
and email cards report Disabled, Configuration incomplete, Configured but
disabled or Enabled/Ready from authoritative configuration only; credentials,
webhook secrets and SMTP passwords never render.

## System and audit expectations

**System & operations** reports database and Redis probes, routing readiness,
KYC limiter mode, private object storage, durable background jobs, email
outbox, finance worker signals and release metadata. Failed work is surfaced
with a safe status; stored errors remain in logs/records for investigation.

**Evidence stores** are listed one per line — parcel media, flight proof,
dispute evidence and identity evidence — and each is probed with the credential
that actually owns it. One combined verdict would be worse than none: the media
bucket answering says nothing about the KYC bucket, and for weeks it was
allowed to. A row reads *Reachable* only when that store's own key got an
answer from that store. The row names the environment prefix supplying the key
(`S3_*` or `KYC_S3_*`) and never any part of the key itself. Verdicts are cached
for a minute so polling this page cannot amplify into object-store traffic. **Audit log** reads as WHO / WHAT /
WHICH OBJECT / WHEN and includes KYC, proof, dispute, finance, staff and
settings actions without logging secrets or full sensitive evidence.

Each payment rail's line states three separate facts, because conflating them
is how a rail gets transacted against by mistake: whether the deployment has
**credentials**, whether business settings have it **enabled**, and whether
those credentials are **test** or **LIVE**. The third is derived from the
credential's documented shape — Stripe's key prefix, and for Chargily the key
prefix cross-checked against the API base — so it never requires anyone to read
or copy a secret to answer it. A configured rail reading *Credential
environment could not be identified* means the key is not a shape this code
recognises, or Chargily's key and API base disagree; treat that as a stop
condition rather than as test.

Since Phase 8F-C the console does more than describe that state — the server
refuses it. A rail whose environment cannot be identified reads **Enabled, but
unavailable**, and `resolve_gateway_for_checkout` raises
`provider_configuration_invalid` before any provider call, so no money moves
through an environment nobody can name. The wording is deliberate: *Disabled*
would send an operator to the business-settings switch, and the switch is not
the problem. Webhooks, reconciliation and refunds for payments that already
exist keep working throughout, because refusing those would strand real money
rather than prevent a bad checkout.

The payer sees the same fact in the app: the rail is listed, greyed, and
labelled *Not ready yet* — not silently removed, which reads as a bug, and not
tappable, which reads as a lie.

**Geography catalogue** reports the reviewed manifest digest this database was
built from, when it was applied, and by which release, above the per-country
counts. Counts alone cannot tell a complete catalogue from a superseded or
partial one; the digest can. *No catalogue import is recorded* means canonical
place selection is unavailable and neither senders nor travellers can create
anything — check the deployment log for `geography catalogue import FAILED`.

Failed-job and failed-email counts link to filtered record queues with safe
references. Queue counts are not live worker heartbeats: the current platform
does not expose reliable per-worker liveness telemetry. No “worker online”
claim is inferred from a pending or empty queue.

The console is desktop-first. Navigation is one row of sections with a second
band for the current section's destinations; the overview additionally lists
every destination the signed-in role can open. Tables scroll horizontally
inside their own card and cards/forms stack at narrower laptop and tablet
widths.

## Opening a record

Where a row stands for one record, the whole row opens it: click anywhere on it
that is not another control. A row that opens something carries a chevron at
its right edge, pinned there so it stays visible when a wide table scrolls
sideways, and lifts under the pointer. This is deliberate — before Phase 8F-G2
a KYC submission opened only from the applicant's name, and there was nothing
to say so.

The record's own name is still the link. Tab reaches it, Enter follows it,
right-click offers the usual menu, and Ctrl/Cmd-click or middle-click opens it
in a new tab, exactly as before. Nothing about opening a record depends on
JavaScript; only the wider pointer target does.

Controls inside a row keep their own behaviour. Clicking the bulk-select
checkbox on Background jobs only ticks it, and clicking a job's related object
opens that object rather than the job. Selecting text in a row does not
navigate.

The queues whose rows open are Users, KYC review, Flight proofs, Journeys,
Deals, Disputes, Payments, Refunds, Payouts and Background jobs. Delivery
requests, Ledger, Transactional email, Audit log and Staff have no per-record
page, so their rows are deliberately inert rather than pretending otherwise. Status is always a word plus a mark, never colour alone, and the
palette meets WCAG AA in both the light and dark themes. Empty queues explain that
they are clear; action failures preserve a request reference and never claim a
state change when the audited service refused the operation.

## Finance operations and failed-job recovery

The Overview counters are action queues, not lifetime failure totals. **Payments
needing attention** includes an unapplied capture until its purpose-bound full
refund succeeds, plus amount/currency verification anomalies that require a
Finance decision. A normal provider decline that moved no money remains visible
in payment history but is not an incident. **Background jobs needing attention**
counts only unresolved terminal failures. Automatically retrying or deliberately
deferred jobs and resolved history are reported separately under **System &
operations**.

Open a payment or background-job row through **Review**. The page shows safe
identifiers, the related domain object, attempts, last/next attempt, and a
classified error code; payloads, raw provider errors, tokens, and credentials
are not rendered.

Background-job outcomes have these meanings:

- **Deferred** means a known time/configuration gate is closed, such as the
  transactional-email kill switch. It is scheduled again without consuming an
  attempt.
- **Retrying** means a transient provider or availability failure. Retries use
  bounded exponential backoff and stop at the job's configured maximum.
- **Failed** means a permanent failure or exhausted retry budget and requires
  review. Invalid payload/configuration failures dead-letter on the first
  attempt.
- **Superseded** means authoritative state proves the work already succeeded or
  no longer exists. The worker self-heals these terminal rows before claiming
  new work.

**Retry now** resets the current retry cycle and invokes the existing
idempotent handler; it never directly marks a payment paid. **Resolve** and
**Dismiss** remove an unresolved terminal job from the active queue while
retaining its execution row, attempts, timestamps, safe error category, actor,
and required reason. Dismissing an outbound-email job also cancels its still
pending message obligation so it cannot be sent later. Bulk retry/dismiss is
limited to 100 unchanged terminal rows and requires confirmation plus one
reason applied to every individually audited row. Finance can manage financial
jobs, Ops can manage lifecycle/email jobs, Super Admin can manage both, and
Support cannot perform recovery actions.

For a payment attention item, **Queue reconciliation** schedules the existing
provider/refund reconciliation path. Chargily attempts without a provider
checkout reference are refused because blindly creating another checkout could
charge twice. Unapplied money is never changed to paid from the console: the
automatic full-refund obligation must reconcile to success before its attention
item can be resolved. Reconciliation re-locks canonical domain rows and relies
on the existing unique provider IDs, stable idempotency keys, event application,
ledger, refund, and payout constraints.

Never delete a PaymentAttempt, PaymentOrder, provider event, ledger transaction,
refund, payout, audit event, or reconciliation evidence to clear a counter.
`prune_scheduled_jobs` is the only physical cleanup introduced here. It is a
dry-run by default, refuses retention shorter than 30 days, defaults to 90 days,
and can delete only old succeeded job-execution rows or old terminal rows that
already have a recorded resolution. It never selects an unresolved failure.
Run `python manage.py prune_scheduled_jobs` to inspect the candidate count and
add `--execute --days N` only after review.

## Review and verification

Use Python 3.12 with the pinned requirements, matching the application image.
The local Python 3.14 runtime is incompatible with Django 5.1.4's template
context copying; it is not a valid substitute for admin regression testing.

`tools/preview/dump_console_pages.py` renders every console screen from the
throwaway preview database into `build/adminshots/console-*.html`, with the
stylesheet cache-busted so a review always sees the current pass. Private
evidence is never exported: any authorized object-store image is replaced with
a visibly synthetic placeholder.

`tools/preview/dump_console.py` creates review HTML from an isolated in-memory
database and explicitly synthetic evidence. It refuses an existing file-backed
database. See the preview README for the command. No live provider activation
or email delivery is involved.

The Phase 8D SQLite task/regression slice is green. PostgreSQL admin, staff,
settings and verification checks pass, but wider finance/dispute integration
remains blocked by the existing nullable-join lock in matching offer creation;
see the Phase 8D handoff in `IMPLEMENTATION_STATUS.md`. This is not a release
approval and Phase 8E has not started.
