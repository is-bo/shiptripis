# Waçla transactional email operations — V2 preparation

V2 performs no external activation. Keep `EMAIL_ENABLED=false`,
`EMAIL_ACTIVATION_APPROVED=false` and `EMAIL_SENDING_DOMAIN_VERIFIED=false`.
Do not create Sender credentials, change DNS/mailboxes, deploy, touch Railway or
run any of these commands against an existing environment during V2.
The commands below describe later, explicitly authorized operations.

## Architecture and configuration

Reuse PostgreSQL `OutboundMessage` and `ScheduledJob`. Django owns business
events, recipient/locale snapshots and multipart rendering. Ordinary messages
use Redis/Go SMTP; verification/reset/invitation/delivery codes bypass Redis and
use trusted Django SMTP. Both use a shared PostgreSQL send gate, the same From,
Reply-To, TLS policy, timeout and rate budget. No Sender SDK or REST dependency.

The [official Sender SMTP guide](https://www.sender.net/help/transactional-emails/getting-started/)
documents `smtp.sender.net:587`, STARTTLS, SMTP-user authentication and a From
address on a verified domain. SMTP credentials are distinct from the From email.
Use `EMAIL_PROVIDER=sender_net`; `smtp` remains the generic provider contract.

| Location | Settings |
| --- | --- |
| Private `stack.env` | `EMAIL_ENABLED=false`, `EMAIL_ACTIVATION_APPROVED=false`, `EMAIL_PROVIDER=sender_net`, `EMAIL_SMTP_HOST=smtp.sender.net`, `EMAIL_SMTP_PORT=587`, `EMAIL_USE_TLS=true` |
| Private `stack.env` | `EMAIL_FROM_NAME=Waçla`, owner-chosen `EMAIL_FROM_ADDR`, `EMAIL_SUPPORT_ADDR`, optional `EMAIL_REPLY_TO` (falls back to support); `FRONTEND_BASE_URL` must be the actual HTTPS public origin |
| Private `stack.env` | `EMAIL_SMTP_TIMEOUT_SECONDS=10` (1–10), `EMAIL_RATE_LIMIT_PER_MINUTE=60` (1–600; tune to the actual provider limit) |
| Private `stack.env` | `EMAIL_SENDING_DOMAIN_VERIFIED=false`, `EMAIL_ACTIVATION_NOT_BEFORE=`; the latter becomes a timezone-qualified ISO timestamp in V3 |
| Mounted `secrets/app.json` | `EMAIL_SMTP_USERNAME` and `EMAIL_SMTP_PASSWORD`, both empty in V2. Never put them in `stack.env`, Docker build args, images, logs or Git |
| Existing mounted secret | Preserve `TRANSACTIONAL_EMAIL_SECRET`; it decrypts queued capabilities and is unrelated to SMTP credential rotation |

Follow [ENVIRONMENT.md](ENVIRONMENT.md) for file ownership/modes. The runtime
injects secrets once into the shared supervisor environment; Django and Go
therefore consume identical values. Duplicate sources are refused. Both
services start without SMTP credentials while disabled. Production startup
validates enabled configuration without dialing Sender.

## Historical backlog: required before every activation

1. Keep both activation switches off; stop the application/consumer processes
   using the existing V1 maintenance procedure before reviewing shared state.
   Take and verify the normal backup. Do not restore or migrate production data
   as part of V2.
2. Choose and record the activation cutoff in UTC, for example an operator-chosen
   current timestamp in `YYYY-MM-DDTHH:MM:SSZ` format. Do not copy an old example
   date. Set the **same** `EMAIL_ACTIVATION_NOT_BEFORE` for Django and Go.
3. Run the read-only paginated inventory through the locked maintenance path:

   ```text
   infra/vps/vps email-audit --limit 100 --after-id 0
   ```

   Continue with the last reported ID. Results contain IDs, kind, status,
   creation/expiry/age, coarse Deal state, classification and a review digest.
   They omit recipients, message keys/context, bodies, URLs, tokens and codes.
   The audit never decrypts or sends. Include pending **and failed** rows in the
   review record; failed rows are already terminal and are not automatically
   retried. Review Redis lag/pending entries and any already accepted SMTP
   receipts too; SMTP acceptance must never be replayed as a new send.
4. Classify with the application state and permissioned operations console:

   | Class | Operator decision |
   | --- | --- |
   | Expired/used/superseded verification or reset | Cancel pending obligation; user requests a fresh code through the existing authenticated/public throttled contract |
   | Expired/revoked/used invitation | Cancel; privileged operator issues a fresh role-bound invitation if still needed |
   | Used/rotated/cancelled/buffered delivery code or changed recipient | Cancel obsolete obligation; reconcile current handover state through existing authorized services. Never reveal or regenerate a code in this command |
   | Historical payment, refund, payout, trust or lifecycle notice | Inspect current provider/domain state, superseding events, recipient authority and relevance. A success receipt may remain valid evidence; an old action prompt may be obsolete. Never alter ledger/payment state to make an email eligible |
   | SMTP receipt already accepted but outbox still pending | Reconcile through the existing receipt/sweep path; do not authorize another send. Review command refuses release |
   | Still-valid obligation | Explicit release for that exact row, after checking recipient, locale, context, current business state and expiry. Do not discard it merely because it is old |

5. Record one explicit decision at a time with the digest from a fresh audit:

   ```text
   infra/vps/vps email-review --id MESSAGE_ID --fingerprint REVIEW_DIGEST --operator-id ADMIN_USER_ID --action cancel
   infra/vps/vps email-review --id MESSAGE_ID --fingerprint REVIEW_DIGEST --operator-id ADMIN_USER_ID --action release
   ```

   These commands require `manage_admins`, check that the pending row has not
   changed, record immutable `AdminAuditLog` evidence and never send. Cancel
   retains both the row and its job history. Release refuses expired/obsolete
   capabilities, recorded acceptance and exhausted retry budgets. Uncertain
   acceptance requires reconciliation, not a blind retry-budget reset.
   A release authorizes that row for 24 hours, leaves its logical key, locale,
   recipient and retry budget intact, and replaces any old stream event handle.
   Old Redis entries then cannot name a sendable obligation.
6. Re-audit. Unreviewed pre-cutoff rows remain held. Independently, unreviewed
   rows older than 48 hours are held after an extended outage. Holds consume no
   SMTP attempts and do not delete valid obligations. Expired reviews require
   a new decision. The sweep filters held rows so they cannot starve new mail.

Classification is assistance, not proof that a financial/lifecycle notice is
still useful: review the current business record. Never bulk approve an entire
historical queue. Do not flush Redis to bypass the audit or reset all statuses.

## Domain, DNS and monitored business inboxes — V3 only

The owner supplies the actual Namecheap domain; none is assumed in code.
Choose a hosted mailbox provider, preferably Namecheap Private Email for a
small initial team. Use a real monitored `support@<domain>` mailbox;
`contact@<domain>` can be an alias into that mailbox if the same team handles
both, or a separate mailbox when access/ownership differs. Use
`notifications@<domain>` as the verified transactional From identity. It need
not have a separate paid inbox when replies go to support; an alias into the
monitored inbox is useful for replies sent directly to From. Never advertise
an unmonitored Reply-To. Do not host IMAP/SMTP mailboxes on the VPS.

[Namecheap supports hosted Private Email and third-party MX configurations](https://www.namecheap.com/support/knowledgebase/article.aspx/322/2237/how-can-i-set-up-mx-records-required-for-mail-service/).
[Aliases can route business addresses to the chosen mailbox](https://www.namecheap.com/support/knowledgebase/article.aspx/10791/2215/how-to-create-an-alias-for-namecheap-private-email/).
No mailbox purchase or subscription is part of V2.

In V3, verify ownership using a working address on the owner's domain. Obtain
the actual authentication records from Sender's Domains dashboard; that
dashboard is authoritative for names, selectors, tokens and targets. Do not
derive DNS values from examples in this repository.

* **SPF:** inventory the existing policy and every legitimate sender, including
  the mailbox provider. Merge authorized mechanisms into **one** SPF policy at
  each hostname. Check the SPF DNS lookup limit; do not add a second `v=spf1`
  record or blindly replace the mailbox provider's policy.
* **DKIM:** copy Sender's current dashboard-supplied records exactly. Keep the
  mailbox provider's independent selector/records. Confirm signing-domain
  alignment against the chosen From domain.
* **DMARC:** inventory any existing policy, establish an owner-approved report
  destination and rollout policy, verify SPF/DKIM alignment, then strengthen
  policy using observed legitimate traffic. Do not weaken an existing policy
  merely to pass a dashboard check.
* **MX:** incoming mail belongs to the mailbox provider. Sender relay settings
  do not justify replacing inbound MX. Use that provider's exact MX values.
* **Bounce/return path:** use Sender's supported envelope/return-path behavior;
  do not invent a custom bounce domain or DNS target. Confirm supported custom
  return-path options and actual alignment during V3 testing.

See [Sender domain authentication](https://www.sender.net/help/deliverability-compliance/spf-dkim-dmarc-setup/).
Verify authoritative/public DNS answers and dashboard status after propagation
using `dig TXT <domain>`, the actual DKIM hostname and `dig TXT _dmarc.<domain>`;
do not log verification links or private dashboard screenshots. Check that
support/contact can receive and send replies before activating transactional mail.

## Retry, health, alerts and credential rotation

`dispatched` and legacy `PublishedEvent.delivered_at` mean **SMTP accepted**,
not final inbox delivery. The application does not currently consume Sender
delivery/bounce webhooks. In V3 use Sender's transactional logs and supported
bounce events; verify authentication, replay protection, retention and account
capabilities before adding any inbound integration. Do not invent a webhook
signature contract. Keep optional open/click tracking disabled for sensitive
transactional mail; this code adds no tracking pixel or third-party resource.

PostgreSQL serializes the bounded last-mile send across Django/Go workers and
counts accepted/failed attempts for the shared minute budget. SMTP timeouts and
4xx failures remain retryable with exponential backoff (60 seconds to 6 hours)
and the existing bounded obligation budget (normally 10, recipient code 12).
5xx failures become durable terminal failures. Worker death releases database
locks; missing jobs and lost Redis entries are recovered by the outbox sweep.
The Go PEL sweeper reclaims abandoned work; duplicate entries consult the same
durable obligation/receipt before sending. Stable Message-ID values help
correlation. A crash **after SMTP acceptance but before database commit** can
still duplicate a message: SMTP supplies no idempotency transaction. Never
describe this boundary as exactly-once or as final delivery.

Monitor the private `/readyz` and `/debug/vars` email endpoints through existing
host/container checks; do not expose them publicly. Track `smtp_attempts_total`,
`smtp_accepted_total`, `smtp_retryable_failures_total`,
`smtp_permanent_failures_total` and `send_gate_skips_total` in `email_stats`.
The existing `ops_snapshot` includes overdue age/count, failed, retrying and
activation-held obligations plus Redis email lag/pending. Alert on:

* worker/process unhealthy or missing finance snapshots;
* actionable email overdue >10 minutes, growing Redis lag >100, or repeated
  SMTP timeouts/4xx failures;
* any new permanent failure/unconfirmed acceptance, and failed obligations
  requiring operator reconciliation;
* persistent activation holds approaching expiry or a released row that has
  not been sent. Holds need review, not automatic retry-budget resets.

V1 host monitoring retains its local systemd alert hook. The owner must connect
it to a monitored operational destination during V3; V2 sends no alerts
externally. Reconcile expected historical failures when setting alert baselines.

For SMTP credential rotation: disable both activation switches, stop/drain the
application, inspect pending/uncertain acceptance, obtain replacement SMTP
credentials in V3, atomically replace mounted `app.json` retaining its private
owner/group/mode, validate configuration and recreate the shared application
process. Both senders must load the same replacement. Complete a controlled
allowlisted test before revoking old credentials; re-enable only after the
normal backlog review. If compromise is suspected, revoke immediately and keep
sending off until review completes. Never rotate the outbox encryption root as
a side effect of SMTP password rotation.

## Eventual V3 activation checklist

* Owner confirms domain, HTTPS public origin, From/support/contact identities,
  mailbox access, native-language review and permitted test recipients.
* Verified ownership, SPF/DKIM/DMARC alignment, monitored Reply-To and inbound MX.
* Sender SMTP account capability/rate limits reviewed; credentials injected only
  through mounted secrets. Provider tracking settings reviewed for sensitive mail.
* Current backup, completed per-row backlog audit and a current activation cutoff.
* Apply V2's additive migrations through the existing single-owner V1 procedure;
  validate production startup with sending still disabled.
* Deploy only after separate owner authorization. Set both activation switches
  and the verified-domain flag only for the agreed V3 activation window.
* Controlled Gmail/Outlook/Apple Mail/mobile tests in EN/FR/AR; inspect headers,
  From/Reply-To, TLS, SPF/DKIM/DMARC, spam placement, one-time-use/expiry,
  acceptance, bounce behavior and received replies. These are not V2 results.
* Confirm backlog/retry/worker alerts; record evidence and disable sending again
  if any gate fails. Financial switches stay TEST/off throughout.
