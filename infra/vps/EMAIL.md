# Wassla transactional email operations

Wassla sends through **Sender.net's REST API** from one address,
**Wassla <contact@wassla.eu>**, which is also Reply-To and the support address.
Everything ships switched off: keep `EMAIL_ENABLED=false`,
`EMAIL_ACTIVATION_APPROVED=false` and `EMAIL_SENDING_DOMAIN_VERIFIED=false`
until the owner approves activation. Do not deploy, create provider
credentials or change DNS without that approval. The commands below describe
later, explicitly authorized operations.

## Architecture and configuration

PostgreSQL `OutboundMessage` and `ScheduledJob` are the obligation. Django owns
business events, recipient/locale snapshots and multipart rendering (text and
HTML from one document, in English, French and Arabic). Ordinary messages
travel Redis `email:send` to the Go email worker; verification, reset,
invitation and delivery-code messages bypass Redis and are sent by Django's
trusted email backend. Both paths use the provider `EMAIL_PROVIDER` names, the
shared PostgreSQL send gate, the same From, Reply-To, timeout and minute rate
budget.

| `EMAIL_PROVIDER` | Transport | Used for |
| --- | --- | --- |
| `sender_net` | `POST https://api.sender.net/v2/message/send` with `Authorization: Bearer <token>` (Django `apps/notifications/sender_net.py`, Go `internal/email/sender_net.go`) | Production |
| `smtp` | Any SMTP relay (`EMAIL_SMTP_*`, `EMAIL_USE_TLS`) | MailHog in local development, or any relay if ever preferred |

**The API token.** Create it in Sender.net (Account settings, API access tokens, validity "Forever"). It is
a secret: it goes only in the mounted `secrets/app.json` as
`SENDER_NET_API_TOKEN`, never in `stack.env`, Docker build args, images, logs,
tickets or Git. The runtime injects it once into the shared supervisor
environment, so Django and Go read the same value; a duplicate source is
refused. No log line, exception, stored error or metric carries the token, a
recipient, a subject or a body.

**The From address.** Sender only sends from an address on a domain verified in
its dashboard, so `wassla.eu` must be verified (see the DNS section) before
`EMAIL_SENDING_DOMAIN_VERIFIED=true`.

| Location | Settings |
| --- | --- |
| Private `stack.env` | `EMAIL_ENABLED=false`, `EMAIL_ACTIVATION_APPROVED=false`, `EMAIL_PROVIDER=sender_net`; no `EMAIL_SMTP_*` (production refuses an SMTP host with `sender_net`) |
| Private `stack.env` | `EMAIL_FROM_NAME=Wassla`, `EMAIL_FROM_ADDR=contact@wassla.eu`, `EMAIL_SUPPORT_ADDR=contact@wassla.eu`, `EMAIL_REPLY_TO=` (blank: the support address); blank From or support values also mean contact@wassla.eu. `FRONTEND_BASE_URL` must be the actual HTTPS public origin |
| Private `stack.env` | `EMAIL_TIMEOUT_SECONDS=10` (1–10; bounds one send on either provider), `EMAIL_RATE_LIMIT_PER_MINUTE=60` (1–600; tune to the Sender account's limit) |
| Private `stack.env` | `EMAIL_SENDING_DOMAIN_VERIFIED=false`, `EMAIL_ACTIVATION_NOT_BEFORE=`; the latter becomes a timezone-qualified ISO timestamp at activation |
| Mounted `secrets/app.json` | `SENDER_NET_API_TOKEN`, empty until activation |
| Existing mounted secret | Preserve `TRANSACTIONAL_EMAIL_SECRET`; it decrypts queued capabilities and is unrelated to token rotation |

With `EMAIL_ENABLED=true`, production startup refuses (and names the setting):
a missing token, one shorter than 20 characters or one containing spaces, any
`EMAIL_SMTP_HOST` under `sender_net`, an invalid From/support/Reply-To address,
an unverified domain or a missing activation cutoff. With provider `smtp` it
keeps requiring a host and TLS. Both services start without credentials while
disabled, and configuration is validated without calling Sender; `/readyz`
reports PostgreSQL and Redis only.

Follow [ENVIRONMENT.md](ENVIRONMENT.md) for file ownership/modes.

## Invitation browser access

Invitation links resolve to `/admin/invitations/accept?language=<locale>#token=…`.
The fragment is transferred into a CSRF-protected POST and cleared from the
address bar. GET does not consume it; link scanners cannot accept invitations.
Existing accounts must authenticate with their current password (or the matching
Django session); new accounts use the existing password validators. No automatic
login or returned credentials. EN/FR/AR follows the invitation's explicit locale.
The page uses same-origin existing branding assets and no third-party scripts.
Keep admin CIDRs enforced; provide invited staff the approved VPN/admin network
before sharing the link. Do not expose the administration surface to bypass this
boundary. Both VPS proxy layers (`Caddyfile` and `gateway.Caddyfile`) preserve the
page's no-referrer policy with `?Referrer-Policy`. Disable provider
click/open tracking for capability mail, as described below.

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
   retried. Review Redis lag/pending entries and any already accepted provider
   receipts too; a provider acceptance must never be replayed as a new send.
4. Classify with the application state and permissioned operations console:

   | Class | Operator decision |
   | --- | --- |
   | Expired/used/superseded reset | Cancel pending obligation; user requests a fresh code through the existing public throttled reset contract |
   | Expired/superseded signup verification | Cancel pending obligation; preserve the account's verification state. Registration is currently the only issuance endpoint; arrange a separately authorized fresh issuance through the existing trusted account helper in V3 or explicitly scope a resend support/API workflow. Do not promise a nonexistent resend endpoint, re-register an existing email, or mark it verified |
   | Expired/revoked/used invitation | Cancel; privileged operator issues a fresh role-bound invitation if still needed |
   | Used/rotated/cancelled/buffered delivery code or changed recipient | Cancel obsolete obligation; reconcile current handover state through existing authorized services. Never reveal or regenerate a code in this command |
   | Historical payment, refund, payout, trust or lifecycle notice | Inspect current provider/domain state, superseding events, recipient authority and relevance. A success receipt may remain valid evidence; an old action prompt may be obsolete. Never alter ledger/payment state to make an email eligible |
   | Provider acceptance already recorded but outbox still pending | Reconcile through the existing receipt/sweep path; do not authorize another send. Review command refuses release |
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
   send attempts and do not delete valid obligations. Expired reviews require
   a new decision. The sweep filters held rows so they cannot starve new mail.

Classification is assistance, not proof that a financial/lifecycle notice is
still useful: review the current business record. Never bulk approve an entire
historical queue. Do not flush Redis to bypass the audit or reset all statuses.

## Domain, DNS and the contact mailbox

The domain is `wassla.eu`. Sender sends mail; it does **not** receive it. The
address `contact@wassla.eu` is From, Reply-To and support, so it must be a real
monitored mailbox at a mailbox provider (for example Namecheap Private Email),
with that provider's MX records. Replies and support requests land there. Never
advertise an unmonitored address. Do not host IMAP/SMTP mailboxes on the VPS.

[Namecheap supports hosted Private Email and third-party MX configurations](https://www.namecheap.com/support/knowledgebase/article.aspx/322/2237/how-can-i-set-up-mx-records-required-for-mail-service/).

Add `wassla.eu` in Sender's Domains dashboard and obtain its authentication
records there; that dashboard is authoritative for names, selectors, tokens
and targets. Do not derive DNS values from examples in this repository.

* **SPF:** inventory the existing policy and every legitimate sender, including
  the mailbox provider. Merge authorized mechanisms into **one** SPF policy at
  each hostname. Check the SPF DNS lookup limit; do not add a second `v=spf1`
  record or blindly replace the mailbox provider's policy.
* **DKIM:** copy Sender's current dashboard-supplied records exactly. Keep the
  mailbox provider's independent selector/records. Confirm signing-domain
  alignment against the From domain.
* **DMARC:** inventory any existing policy, establish an owner-approved report
  destination and rollout policy, verify SPF/DKIM alignment, then strengthen
  policy using observed legitimate traffic. Do not weaken an existing policy
  merely to pass a dashboard check.
* **MX:** incoming mail belongs to the mailbox provider. Sending through Sender
  does not justify replacing inbound MX. Use that provider's exact MX values.
* **Bounce/return path:** use Sender's supported envelope/return-path behavior;
  do not invent a custom bounce domain or DNS target.

See [Sender domain authentication](https://www.sender.net/help/deliverability-compliance/spf-dkim-dmarc-setup/).
Verify public DNS answers and dashboard status after propagation using
`dig TXT wassla.eu`, the actual DKIM hostname and `dig TXT _dmarc.wassla.eu`;
do not log verification links or private dashboard screenshots. Check that
contact@wassla.eu can receive and send replies before activating transactional
mail.

## Retry, health, alerts and token rotation

`dispatched` and `PublishedEvent.delivered_at` mean **the provider accepted the
message** (Sender answered `2xx` with `"success": true`, or the SMTP relay
accepted DATA), not final inbox delivery. The application does not consume
Sender delivery/bounce webhooks. Use Sender's transactional logs; verify
authentication, replay protection and retention before adding any inbound
integration. Keep open/click tracking disabled for sensitive transactional mail;
this code adds no tracking pixel or third-party resource.

PostgreSQL serializes the bounded last-mile send across Django/Go workers and
counts accepted and failed attempts for the shared minute budget. Failure
classes, the same on both paths:

| Answer | Outcome | Stored `last_error` |
| --- | --- | --- |
| Sender `400` or `422`; SMTP 5xx refusal of recipient, sender or data | Terminal failure at once (the message itself is invalid) | `provider_permanent` |
| Sender `401`, `403`, `404` (token or account configuration), `408`, `429`, any `5xx`, a redirect, a `2xx` without `"success": true`; SMTP 4xx, auth, TLS; any timeout or network error | Retry with exponential backoff (60 seconds to 6 hours) within the obligation's budget (normally 10, recipient code 12) | `provider_transient` |

Configuration failures stay retryable so they do not burn messages; alert and
repair configuration before releasing more work. Worker death releases database
locks; missing jobs and lost Redis entries are recovered by the outbox sweep.
The Go PEL sweeper reclaims abandoned work; duplicate entries consult the same
durable obligation/receipt before sending. A crash **after provider acceptance
but before the database commit**, or a timeout after Sender accepted, can still
duplicate a message: neither the API nor SMTP offers an idempotency key. Never
describe this boundary as exactly-once or as final delivery.

Monitor the private `/readyz` and `/debug/vars` email endpoints through existing
host/container checks; do not expose them publicly. Track `smtp_attempts_total`,
`smtp_accepted_total`, `smtp_retryable_failures_total`,
`smtp_permanent_failures_total` and `send_gate_skips_total` in `email_stats`
(the names predate the API sender and count both providers). Failure log lines
carry `failure`, `provider`, `http_status` or `smtp_code`, and the API or relay
host, never an address. The existing `ops_snapshot` includes overdue age/count,
failed, retrying and activation-held obligations plus Redis email lag/pending.
Alert on:

* worker/process unhealthy or missing finance snapshots;
* actionable email overdue >10 minutes, growing Redis lag >100, or repeated
  timeouts, `401`/`403` (token) or `429` (rate) answers;
* any new permanent failure/unconfirmed acceptance, and failed obligations
  requiring operator reconciliation;
* persistent activation holds approaching expiry or a released row that has
  not been sent. Holds need review, not automatic retry-budget resets.

V1 host monitoring retains its local systemd alert hook. The owner must connect
it to a monitored operational destination before relying on it.

For token rotation: disable both activation switches, stop/drain the
application, inspect pending/uncertain acceptance, create the replacement token
in Sender, atomically replace mounted `app.json` retaining its private
owner/group/mode, validate configuration and recreate the shared application
process. Both senders load the same replacement. Complete a controlled
allowlisted test before deleting the old token; re-enable only after the normal
backlog review. If compromise is suspected, delete the token in Sender
immediately and keep sending off until review completes. Never rotate the
outbox encryption root as a side effect of token rotation.

## Activation checklist

* Owner confirms the HTTPS public origin, the contact@wassla.eu mailbox access,
  native-language review and permitted test recipients.
* `wassla.eu` verified in Sender; SPF/DKIM/DMARC aligned; contact@wassla.eu
  receives mail (inbound MX at the mailbox provider).
* Sender account limits reviewed against `EMAIL_RATE_LIMIT_PER_MINUTE`; the API
  token injected only through `secrets/app.json`. Tracking settings reviewed
  for sensitive mail.
* Current backup, completed per-row backlog audit and a current activation
  cutoff.
* Validate production startup with sending still disabled.
* Deploy only after separate owner authorization. Set `EMAIL_ENABLED=true`,
  `EMAIL_ACTIVATION_APPROVED=true` and `EMAIL_SENDING_DOMAIN_VERIFIED=true`
  only for the agreed activation window.
* Controlled Gmail/Outlook/Apple Mail/mobile tests in EN/FR/AR: a verification
  code, a password reset and an ordinary status email; inspect From and
  Reply-To, SPF/DKIM/DMARC, spam placement, one-time-use/expiry, acceptance in
  Sender's logs, bounce behavior and received replies.
* Confirm backlog/retry/worker alerts; record evidence and disable sending again
  if any gate fails. Financial switches stay TEST/off throughout.
