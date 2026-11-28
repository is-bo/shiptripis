# ShipTrip operations console

Phase 8D adds a task-focused Django admin surface at `/admin/`. It is for the
owner and the fixed Phase 6A staff roles; the backend capability checks and
audited domain services remain authoritative.

## Navigation and roles

The header is filtered to the signed-in staff member's capabilities:

- **Overview** answers “what needs attention?” with live queue counts, most
  urgent first (rules below, under “AI helper”), and holds the AI helper
  card.
- **People** opens one complete profile per user: identity, requests, journeys,
  offers, Deals, payments, payout setup and payouts, disputes, revealed ratings,
  notifications and audit history, each section gated on the capability that
  owns it (J6.4), plus internal notes and, for a Super Admin, **Ban account** or
  **Restore account**. Names elsewhere in the console link to it.
- **Verification** is the staff verification inbox (ID and Tickets, with the
  number waiting shown on the entry), private evidence review, and the payout
  identity checks Finance asks Trust for.
- **Marketplace** contains Delivery requests, ordered Journeys and Deals.
- **Disputes** keeps the case, evidence, participants, protection and money in
  one review flow.
- **Finance** contains Exports, Payments, Refunds, Payouts and Ledger/reconciliation.
- **Staff** is for fixed-role invitations and access changes.
- **Settings** groups pricing, deposit, FX and provider availability in human
  units.
- **System** shows safe health, worker, outbox and readiness signals.

Ops, Support, Finance, Trust / Verification and Super Admin see only the
destinations granted by `apps.admin_panel.permissions`. Raw Django model pages
are deliberately hidden from the main mental model; Super Admin can reach
them through the owner-only **Technical records** escape hatch when required.

## Verification workflow

**Verification** is one inbox with two tabs (L6A, spec 13):

- **ID**: identity documents people send before they can publish a journey.
- **Tickets**: the ticket for each flight leg and each ferry crossing. A leg
  cannot be matched until its ticket is approved.

The number on the **Verification** entry in the header is the total waiting
across both tabs, and each tab shows its own number. Each tab opens its queue
filtered to exactly the rows it counted (state **Pending**); clear the filter
to see decided ones. Opening **Verification** lands on the first tab that has
something waiting, otherwise on ID. A staff role that can see only one of the
two kinds sees only that tab.

Open a row to review it. The review screen is the same for both kinds: who
sent it, the document or the leg (route, date, flight number), earlier
submissions, the evidence, and the decision. **View evidence** creates a
short-lived authorized object-store URL and writes an audit event; storage
keys are never displayed. Trust-capable staff choose one of three decisions:

| Decision | Use it when | What the person is told |
| --- | --- | --- |
| **Approve** | The evidence is good. | Approved; they can publish, or the leg can be matched. |
| **Ask for a new upload** | It is unreadable, incomplete or the wrong document. | "We need a new upload", with your reason. |
| **Reject** | It cannot be accepted. | It "needs attention", with your reason. |

The last two need a reason, which the person reads exactly as written, and
both let them send a new document; the new one arrives as a new row in the
same tab. Every decision is audited (the audit entry's `outcome` says which of
the three it was), and a decided row reads **New upload requested** or
**Rejected** in the queue and on its page. If two reviewers decide the same row
at once, the second is told it was already decided.

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

A payout on the **Stripe EUR rail is automatic and has no Pay button.** Its
detail page adds a Stripe panel: the canonical obligation, a masked account
reference and its readiness, how much is committed externally, which Stripe
charges support it, the platform transfer and its provider reference, the bank
payout with submitted/paid/arrival times, any active holds, and the full payout
timeline. Read it in that order — a transfer having succeeded means the money is
at the Traveler's connected account, not that they have been paid. Only the bank
payout reaching `paid` means that.

Three recovery actions, each on its own capability and each state-safe.
**Re-read Stripe state** asks the provider what is true and is always the first
thing to try. **Retry bank payout** appears only on a failed payout with no
active hold and no unresolved operation; it creates another bank payout, never
another transfer, and clearing the block reason is the recorded judgement that
the Traveler's bank details have actually been corrected. **Hold for Finance
review** stops the next stage and changes nothing about what has already been
reserved or sent. There is no Mark paid, no reset, no force, and no way to edit
an amount or a destination. When the page says an operation's outcome is
unknown, the money may already have moved: nothing new will be sent for that
payout, and no button on the page can resolve it — only a provider read can.

## Staff and settings

On **Staff**, enter a work email, choose one fixed role and an expiry. The
one-time invitation is sent through the durable email queue; its token is never
shown in the browser. Owners can see pending invitations, revoke/replace them,
change an existing role and disable sign-in. Self-disable and Super Admin
guardrails are enforced by the service layer.

## Two-step sign-in (L14)

Every staff sign-in has two steps: the password, then a 6-digit code from an
authenticator app. Nothing in the console, the technical records or the staff
API opens before the second step.

**First sign-in.** After the password, the console shows a QR code. Scan it
with an authenticator app (Google Authenticator, Microsoft Authenticator,
1Password or similar); if the phone cannot scan, type the key shown under it.
Enter the code the app shows. The console then shows **ten recovery codes,
once**. Save them in a password manager: each one replaces a code from the app
for a single sign-in if the phone is lost. They are never shown again.

**Every sign-in after that.** Enter the code the app shows. A code works once;
if it is refused, check that the phone sets its time automatically and use the
newest code. Five wrong codes lock the second step for 15 minutes (recovery
codes count too); the lock is written to the audit log. Signing out, or signing
in again on any browser, asks for a code again.

**Lost phone.** On the code page choose **Lost your phone? Use a recovery
code**. After using one, the console says how many are left. With three or
fewer left, ask a Super Admin to reset your two-step sign-in so you can set it
up again with a new phone and ten new codes.

**Changes that need a recent code.** Changing someone's role and resetting
someone's two-step sign-in need a code entered in the last 10 minutes. If yours
is older, the console asks for one and brings you back to the page; make the
change again. The Staff page shows until when your code counts.

**Reset (Super Admin).** On **Staff**, open the person's row, **Change role,
access or two-step**, write the reason (it goes in the audit log), tick the
confirmation and choose **Reset two-step**. Their app key and recovery codes
are deleted and they are signed out everywhere; at their next sign-in they set
it up again. Nobody can reset their own, and only a Super Admin can reset a
Super Admin. Their AI helper keys stop too (they were created behind the
second step being reset).

**The last Super Admin.** When no other Super Admin can sign in, the technical
team resets it on the server:
`python manage.py reset_admin_two_step <email> --reason "<why>"`. It does the
same reset, AI helper keys included, and writes the same audit row, marked as
done from the server.

## Finance exports (L14)

**Finance → Exports** (Finance and Super Admin only) downloads what was
recorded as a CSV file that opens in Excel:

- **Transactions:** one line per captured payment and one per refund. A
  payment the order could not absorb (it will be refunded automatically) is
  listed with the status `succeeded_unapplied`.
- **Commissions:** one line per funded delivery: the traveler reward, the
  Wassla fee, the sender total, what was refunded to the sender and the fee
  Wassla kept.
- **Payouts:** one line per traveler payout, with its eligible and paid dates
  and any failure reason.

Choose the money (live, test, or unknown for older records; they never share a
file) and a range of at most 366 days. Dates are whole UTC days, both included,
and each line belongs to the range by its own date (a payment by when it was
captured, a refund by when it was requested, a commission by when its delivery
was funded, a payout by when it was created). Amounts are the stored ones in
euros with two decimals, plus the dinar amount where the Algerian rail was used;
nothing is recalculated. People appear by their Wassla id and name only.

Every download writes one audit row (who, kind, money, range and number of
lines) before the file is sent; the page lists the ten most recent.

## AI helper

An admin can connect an AI assistant they use (for example Claude Code) to
their own work list and records. The assistant acts as that admin, with that
admin's rights at the moment of each call. It never sees documents, contact
details, addresses, payout or bank details, codes, chat, internal notes or
keys. Document reviews (ID, tickets, payout methods, payout identity) reach it
as a count and a link to the console.

There are two kinds of key. A **read key** reads only. A **change key** can
also add an internal note and acknowledge a problem report at once, and
**prepares** every other change it may make for you to confirm on the console;
nothing it prepares happens before you confirm it (see “Changes your assistant
prepares” below).

**Create a key.** On **Overview**, the **AI helper** card, choose **Create read
key (8 hours)** or **Create change key (30 minutes)**. If you have not entered
a two-step code in the last 10 minutes
the console asks for one first. The card then shows one line,
`/wassla <address> <key>`, with a **Copy** button: paste it into your assistant
as your first message. **It is shown once**; Wassla keeps only a scrambled form
of it. If you lose it, create a new one. Each admin has one key of each kind at
a time: creating a new one stops the old one of that kind. A key lasts the time
set in Business settings at the moment it was created (read key 1 to 8 hours,
change key 5 to 60 minutes) and is never extended by use.

**Stop a key.** **Stop key** on the card, or on **Overview → AI helper** (the
page linked from the card as “Keys and recent calls”). That page also lists
every call your keys made in the last 30 days: the time, the key's last four
characters, the address asked for and the result. What was searched for is
not kept. A Super Admin also sees every other admin's live keys there (never a
key itself, only its last four characters) and can stop one with a reason,
which goes to the audit log.

**What stops every key at once.** Switching the helper off in **Settings → AI
helper** stops every live key for good, with one audit row giving the number of
keys stopped; switching it back on does not bring them back. A two-step reset
stops that admin's keys. Stopping a change key early also expires the changes
it prepared; a key that was replaced or simply ran out leaves them for you to
decide. A two-step reset expires every change waiting for that admin, and
switching the helper off every waiting change, whichever key prepared them. A key also stops working at once, without
being stopped, when its admin is banned, deactivated or loses staff access, and
it answers only what their current role opens.

**Changes your assistant prepares.** They wait on **Overview → AI helper**,
under **Waiting for your confirmation**, and the Overview shows “Changes
waiting for your confirmation” with their number. Each shows Wassla's own
sentence for what will happen, the record as a link, the values in words, and
the assistant's reason in a box marked “Written by the AI helper, check it”.
**Review and confirm** opens the change: write your own reason (the
assistant's is filled in; change it if the words are not yours) and choose
**Confirm**. Wassla then checks again that your role allows it, that the page
would still offer it and that the record has not changed since it was
prepared (for a dispute decision, that the settlement engine gives the same
amounts), and does it as you, exactly as the console's own button would, with
the same audit row marked as via the AI helper. If anything differs it says
“This no longer applies” and does nothing. **Reject** needs no reason. Only
you can confirm the changes your keys prepared, only once, and only from a
console session that passed the second step. A change you do not decide
expires after the hours set in Business settings (24 by default). With the
helper switched off, the list stays readable but nothing can be confirmed or
rejected.

What a change key can never do or prepare: staff, roles and invitations;
settings; helper keys; two-step sign-in; identity, ticket, payout-method and
payout-identity reviews; revealing payout details; manual dinar payout steps,
re-reading Stripe or opening a Finance hold; payment reconcile and resolve;
settling a refund by hand; closing a problem report; deciding jobs in bulk;
adding a sea crossing; finance exports.

**Settings → AI helper** (`manage_settings`): on or off, read key hours (1 to
8), change key minutes (5 to 60), how long a prepared change waits (1 to 72
hours), and calls per key per minute (10 to 300; over it the assistant is told
to wait a minute). Saved as one audited settings revision with a reason.

**How the Overview orders work.** Raised items are shown most urgent first,
then by the longest wait. The urgency is a fixed rule per item, the same in the
console and for the assistant; it is never a guess:

| Item | Urgency |
| --- | --- |
| Open disputes | Always urgent (money is frozen and two people are waiting) |
| Problems to look at | Always urgent (a parcel may be moving now) |
| Payments needing finance review | Always urgent (money taken that no order absorbed) |
| Refunds requiring operator action | Always urgent (a person is owed money) |
| Background jobs needing attention | Always urgent (promised work stopped for good) |
| Provider configuration warnings | Always urgent (payments or email may fail for everyone) |
| Tickets to review | Today; urgent once the oldest waited over 2 hours (trips are mostly the same day) |
| ID checks to review | Today; urgent once the oldest waited over 24 hours |
| Payouts requiring action | Today; urgent once the oldest waited over 24 hours |
| Payout methods awaiting approval | Today; urgent once the oldest waited over 48 hours |
| Payout identity checks assigned to you | Today; urgent once the oldest waited over 48 hours |
| Reported reviews | Today; urgent once the oldest waited over 72 hours |
| Failed transactional email | Today |

An item with nothing waiting is not raised. Each item shows only to an admin
who can open the page it links to. These thresholds are a judgment call kept
for the owner's end review.

### Using the AI helper (L17)

The assistant needs the Wassla skill once, and a key each time.

1. **Install the skill.** On the **AI helper** card press **Download the skill** and unzip it into
   `~/.claude/skills/` (Claude Code). For another assistant, press **Copy the instructions** and paste
   them as its first message. Neither holds a key or an address.
2. **Create a key** (read key for questions and briefings; change key only when you want it to prepare
   something) and press **Copy** on the line that appears.
3. **Type `/wassla` and paste the line.** Alone, it gives your briefing: what needs you, most urgent
   first, with the link for each. Add a question after the line to get an answer instead, for example
   `what is WSL-... waiting for?`, `how do I refund someone?`, `why is this payout blocked?`.
4. **Ask anything about the app.** The skill carries notes written from the code: prices and fees,
   payments and payouts, the life of a delivery, trips and matching, problems and disputes, reviews,
   verification, messages, the console and roles, settings, and the structure of the system with
   diagrams. These need no key. If the notes do not hold an answer it says so; it does not guess.
   The live values of a setting are on **Settings**, not in the notes (they give the shipped
   defaults).
5. **A change.** With a change key the assistant prepares it and gives you a link; nothing happens
   until you open the link and press Confirm.

If the assistant says your key has stopped working, create a new one (a read key lasts 8 hours, a change
key 30 minutes). The notes become out of date as the app changes; developers regenerate the pasted
text with `manage.py build_helper_instructions` after editing `apps/admin_helper/skill/`.

## Internal notes

The delivery, dispute and person pages have **Internal notes**: what a
colleague needs to know, with the author and time. Anyone who can open the page
can add one. A note cannot be edited or deleted, is written to the audit log,
and is never shown to members or to an AI assistant. A note added by an
admin's assistant is marked “Added by their AI helper”.

## Banning an account

On the person page a Super Admin (`manage_users`) has **Ban account**, or
**Restore account** for a banned one. Both ask for a reason, which goes to the
audit log and is never shown to the person. A ban signs the person out at once
and stops them signing in; it does not cancel deliveries, move money or release
a payout. Staff accounts are changed on Staff & access, and nobody bans their
own account. The technical records no longer offer a bulk ban.

## Approving a Traveler's DZD payout method

**Finance → Payout method reviews** (and "Payout methods awaiting approval" on the
main Overview) lists what is waiting. A review page is Person, payout method
(masked, with one audited reveal), the crossed cheque and two controls: **Approve**
and **Reject**. "Ask for a correction" is under **More**.

A payout method can only be decided once someone has confirmed the Traveler's
legal name against their approved ID — the domain refuses every decision without
it. A **Super Admin** does that on the review page itself and may approve in the
same step. **Finance** cannot confirm an identity: the page says so and requests
the check from a Trust & Verification operator, who completes it under
**Verification → Payout identity checks**. Nothing here bypasses the gate; the
console simply composes the two audited commands that were always required.

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

The queues whose rows open are Users, Verification (ID and Tickets), Journeys,
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

### Held payments: "no money was taken" and "money returned"

A provider sometimes reports a payment Wassla cannot verify: no amount, a
fractional amount, a different amount, or a missing or different currency. That payment
is **held**. It shows in **Payments needing attention** as "Needs finance
review", the order takes no new payment (the payer is told a payment is being
checked and must not pay again), and no "payment failed" email is sent. The
settle job keeps reading the provider. A hold ends by itself when the provider
confirms the payment (it is credited once, or refunded if the order no longer
needs it) or confirms the checkout ended with no payment (it becomes an ordinary
failed attempt). Otherwise Finance ends it from the payment page with **Close
held payment**:

- **No money was taken**: you checked at the provider (Stripe dashboard or
  Chargily) that this checkout took no money. Write what you saw as the reason.
- **Money returned**: the money was taken and has gone back to the payer, for
  example a refund you made at the provider. Give the reason and the provider's
  payment reference (Stripe: the PaymentIntent id `pi_…`; Chargily: the
  checkout id). When the provider already reported one, the page refuses any
  other.

Both are audited with your name and reason, call no provider, and let the order
take a payment again. The page refuses to act if the payment changed since you
opened it; open it again. If the provider later reports a payment after you
closed the item, it is held again as `paid_after_disposition`, never credited
by itself: check the provider, return the money, and close it as **Money
returned**, the only way such a hold ends. A report of the very payment you
marked returned changes nothing.

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
