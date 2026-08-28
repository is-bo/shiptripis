# ShipTrip V1 Phase 6A — Admin, Transactional Email, and Public Web

Status: engineering foundation implemented; external provider activation and legal review remain launch gates.

Phase 5 is separately **PAUSED / IN PROGRESS**. Its Flutter rebuild is not part
of this phase and must not be treated as complete.

Focused verification on 2026-08-28 covered the Phase 6A authorization,
invitation, outbox, code-secrecy, account-email and template contracts (56
Django tests), Django system and migration drift checks, Ruff, Go email/config
tests, localized public-page and Arabic RTL assertions, the frontend
anti-pattern detector, and repeat-stable PostgreSQL 16 schema export. This is
an engineering result, not provider activation, browser/device certification,
or legal approval.

## 1. Administrative identity and least privilege

Administrative access is implemented with five fixed Django groups. An
invitation carries one role slug, never an arbitrary permission list. Ordinary
staff accounts are not superusers; `is_staff` is only the boundary that permits
staff access, while every operations API also checks a named permission.

| Role | Primary scope |
|---|---|
| Ops | Requests, journeys, matches, offers, Deals, lifecycle incidents, ratings, and boosts |
| Support | User/support context, request/journey/Deal inspection, and supported cancellations |
| Finance | Payment orders/attempts/events, refunds, manual settlements, payouts, reconciliation jobs, and payment-provider health |
| Trust / Verification | User/KYC/flight-proof/evidence review, safety review, no-show verification, and relevant Deal context |
| Super Admin | All Phase 6A capabilities, settings, provider switches, FX, role administration, and invitations |

The canonical matrix is `apps.admin_panel.permissions.ROLE_PERMISSIONS` and is
seeded by the `admin_panel` data migration. Super Admin is the only fixed role
that receives the complete Phase 6A permission vocabulary. Existing Phase 4
dispute, no-show, and payout permissions remain authoritative for their domain
services and are mapped into the corresponding Phase 6A roles.

Roles are additive to unrelated, non-administrative groups. The migration and
role-management code also remove the four retired Phase 4 administrator groups
so a downgrade cannot retain their additive model permissions; unrelated
business groups are never silently erased.

## 2. Controlled Super Admin bootstrap

The initial Super Admin is provisioned with:

```text
python manage.py bootstrap_super_admin --settings=config.settings.prod
```

Required environment variables:

```text
SHIPTRIP_SUPER_ADMIN_EMAIL=
SHIPTRIP_SUPER_ADMIN_PASSWORD=
SHIPTRIP_SUPER_ADMIN_NAME=
```

`SHIPTRIP_SUPER_ADMIN_NAME` is optional. Credentials must be injected by the
deployment secret store and must never be committed. The command:

- looks up the account by normalized email under a transaction;
- creates it only when absent;
- assigns the fixed Super Admin role;
- does not overwrite an existing administrator's password on a routine rerun;
- records the original bootstrap in the immutable admin audit stream; and
- is not mounted as a public signup or invitation route.

After a successful controlled bootstrap, remove the password variable from any
long-lived process configuration where the deployment platform permits it.

## 3. Admin invitations

An invitation uses a 256-bit-class `secrets.token_urlsafe(32)` capability. Only
its SHA-256 digest is stored. It is bound to a normalized email and one fixed
role, expires after 24 hours by default, can be revoked, and is consumed once
under a row lock. Creation, revocation, and acceptance are audited without
persisting the plaintext token.

Only a principal with `manage_admins` can invite. Inviting a Super Admin
requires a current Super Admin. Acceptance never allows the recipient to
choose permissions. Rejected, expired, used, and revoked tokens share a generic
failure contract so callers cannot use the route as an invitation oracle.

The invitation link is sent through the durable transactional-message outbox.
`FRONTEND_BASE_URL` supplies its public origin; the plaintext token exists only
in the one-time email-render path and is not returned by list APIs.

## 4. Audit log

`AdminAuditLog` stores:

- actor (nullable only for a controlled system bootstrap);
- action;
- target type and identifier;
- timestamp;
- safe before/after fragments;
- a bounded reason and external reference; and
- additional safe metadata.

The service redacts secret-shaped keys recursively, including passwords,
tokens, credentials, private keys, sealed values, and codes. Callers must still
provide allowlisted fragments rather than arbitrary model dumps. The Django
admin exposes the records read-only. Operational mutations write their audit
row in the same transaction as the state transition where the domain boundary
allows it. No handover plaintext is accepted by the audit API.

Sensitive actions covered include invitations/roles, KYC and flight-proof
decisions, dispute resolution, refunds/manual refunds, payout evidence,
no-show resolution, and business/provider setting activation.

## 5. Operations API

The Phase 6A API is an inspection and explicit-action surface, not generic CRUD.
Lists are paginated and bounded, search parameters are narrow, relational
loads are selected/prefetched where needed, and serializers omit secrets,
storage credentials, sealed handover values, and delivery codes.

The surface includes:

- dashboard aggregates for users, marketplace states, trust queues, finance
  queues, jobs, email, and provider health;
- user search and account context, including roles, KYC, reliability, requests,
  journeys, Deals, disputes, and permission-appropriate financial references;
- pending KYC and flight-proof queues with explicit approve/reject/resubmit
  flows and reasons;
- read-only operational views for requests, journeys/legs, matches, offers,
  Deals, and immutable Deal timelines;
- dispute queue/evidence/timeline inspection and settlement actions delegated
  to the Phase 4 settlement service;
- payment orders, attempts, provider events, refunds, payouts, unapplied funds,
  and finance ScheduledJobs;
- manual refund and payout evidence flows delegated to the Phase 3/4 services;
- ratings and boost visibility; and
- versioned business-setting inspection and activation.

No endpoint directly edits money fields, bypasses payout eligibility, or
reimplements dispute arithmetic. Unsupported lifecycle mutations remain
read-only until a domain service exists.

## 6. Business settings and provider switches

Settings changes create and activate a new `BusinessSettingsVersion`; historical
versions are not rewritten. Existing cross-phase validation remains the gate
for payment timing, posting deposits, commission, pricing and weight bands,
detours, payment grace, cancellation, code buffer, protection duration, rating
window, boost packages, provider switches, and EUR-to-DZD FX.

The admin may control only business-level availability:

- provider enabled;
- new checkouts enabled; and
- the server-controlled EUR-to-DZD snapshot rate.

Stripe and Chargily API keys and webhook signing secrets stay environment-only.
Phase 6A does not register production webhooks or claim either rail is live.

## 7. Health and observability

The operations dashboard reports safe status, never raw configuration values:

- database reachability through the authenticated application request itself;
- due/running/retrying/failed ScheduledJobs and reconciliation backlog;
- payment-provider configured/available state and checkout switches;
- route-provider state;
- transactional-email configuration plus pending/failed/unconfirmed counts;
- pending/manual refunds, eligible/manual payouts, and unapplied external funds.

Provider exception class names may be reported as stable health codes; exception
messages, keys, credentials, authorization headers, and complete provider
payloads are not exposed.

## 8. Sender.net adapter and deployment configuration

Sender.net is integrated as an SMTP relay behind the existing provider-neutral
email boundary:

```text
domain transition
  -> PostgreSQL OutboundMessage + ScheduledJob
  -> trusted final renderer
  -> ordinary messages: email:send Redis Stream -> Go SMTP adapter -> Sender.net
  -> secret-bearing messages: trusted Django SMTP adapter -> Sender.net
```

Domain services do not import a Sender.net SDK. `EMAIL_PROVIDER=sender_net`
selects validated configuration but uses the generic TLS SMTP adapter, so the
provider can be replaced without changing marketplace state machines.

Production variables:

```text
EMAIL_ENABLED=true
EMAIL_PROVIDER=sender_net
EMAIL_SMTP_HOST=smtp.sender.net
EMAIL_SMTP_PORT=587
EMAIL_USE_TLS=true
EMAIL_SMTP_USERNAME=<secret>
EMAIL_SMTP_PASSWORD=<secret>
EMAIL_FROM_ADDR=noreply@<verified-domain>
EMAIL_FROM_NAME=ShipTrip
EMAIL_SUPPORT_ADDR=support@<verified-domain>
FRONTEND_BASE_URL=https://<public-origin>

# Optional worker topology overrides
EMAIL_STREAM=email:send
EMAIL_CONSUMER_GROUP=email-send-workers
EMAIL_CONSUMER_NAME=<unique-worker-name>
```

The credentials belong in the deployment secret store. Do not put them in
`.env.example`, source, images, client bundles, logs, or admin responses.

Before production sending, operations must verify the sending domain in
Sender.net and publish the provider-supplied SPF and DKIM records. A deliberate
DMARC policy must be published for the organizational domain, TLS must remain
enabled, and envelope/from alignment must be verified. These DNS and account
steps are external dependencies; this document does not claim they are done.

## 9. Transactional message contracts

The inventory covers these user-facing contracts:

| Area | Contracts |
|---|---|
| Account/security | Email verification, password reset, security/account event |
| Administration | Admin invitation |
| Trust | KYC status, flight-proof status |
| Payments | Payment required, processing, failure, success, guest payment, refund, payout |
| Delivery | Pickup status, recipient delivery code, delivery confirmation, protection ending/ended |
| Disputes | Dispute opened, evidence request, dispute resolved |
| Lifecycle | Cancellation, rating availability |

Templates minimize personal data and use stable context contracts. A template
contract being present does not imply every optional product event is currently
armed; domain wiring is recorded in tests and implementation status rather than
overclaimed here.

### Delivery-code secrecy

The delivery code is the exceptional message:

- `OutboundMessage.context` contains no plaintext code;
- `secret_ref` contains only `handover_code:<database-id>`;
- the sealed code is opened only by the trusted renderer immediately before
  transport;
- secret access creates a code-access audit row without revealing the value;
- published-event persistence stores a payload hash, not the payload;
- notification payloads, Deal timelines, admin audit, and logs contain no code;
- a used, rotated, cancelled, or otherwise non-live code refuses rendering.

Redis Stream delivery for ordinary messages is at-least-once. Secret-bearing
messages intentionally bypass Redis so their rendered code cannot enter a
stream payload; the same PostgreSQL row and scheduled sweep retry the trusted
SMTP adapter. Every obligation is keyed uniquely to prevent duplicate arming.
Consumer-group pending entries are reclaimed after worker failure, and ordinary
stream messages record a durable SMTP receipt before acknowledgement. A crash
in the unavoidable send/receipt gap can cause one byte-identical duplicate, but
must not silently lose a critical email.

## 10. Public website

The public site is a separate, lightweight static bundle. It does not import the
Flutter application or expose admin routes. Localized entry points are:

- `/fr/` — French;
- `/ar/` — Arabic with `lang="ar"`, `dir="rtl"`, mirrored layout, and logical
  CSS properties; and
- `/en/` — English.

The information architecture covers the two roles (send a parcel / carry while
travelling), request and journey flows, FLIGHT and DRIVE legs, compatibility
matching, protected exact locations, KYC and flight proof, secure payment and
protection, pricing, safety, FAQ, availability/download messaging, support, and
policy links. It does not describe ProductRequest/Kaba.

Payment copy says that funds are held pending delivery and payout waits for
confirmation/protection. It deliberately avoids the legally loaded word
“escrow,” regulatory guarantees, and claims that Stripe/Chargily are live. EUR
is canonical; a Chargily DZD amount is a platform-configured conversion, not a
guaranteed market exchange rate.

Commission is added on top of the reward. The canonical example is:

```text
Traveler reward: €30.00
ShipTrip fee: €7.50
Sender total: €37.50
```

The traveler receives the negotiated €30.00; the site does not describe this
as taking 25% from the traveler.

Semantic landmarks, ordered headings, visible focus, skip navigation, reduced
motion, sufficient touch targets, responsive layouts, localized titles and
descriptions, OpenGraph metadata, canonical/hreflang links, sitemap, and robots
form the accessibility/SEO baseline. No fabricated testimonials, user counts,
provider availability, or download links are included.

## 11. Policy and support pages

The public bundle provides product drafts for Terms of Service, Privacy Policy,
Prohibited Items / Acceptable Use, and Support/Contact. They describe the V1
data classes and workflow without inventing fixed retention periods:

- account and contact data;
- coarse/public versus exact/private location data;
- KYC and flight-proof evidence;
- recipient contact data;
- payment metadata and provider references;
- dispute evidence; and
- access, correction, deletion, portability, and legal-retention exceptions.

Final controller/processor identity, legal bases by processing purpose,
retention schedule, age/guardian rules, Algeria/EU transfer safeguards,
prohibited-item jurisdiction matrix, cancellation/refund language, cookie
classification, and support SLA are unresolved legal policy choices.

These pages are **product/legal drafts, not legal approval**. French/EU and
Algerian counsel must approve localized final text before launch. If analytics
or any non-essential cookies are later added, the static privacy notice is not
sufficient by itself; consent controls and a cookie inventory must be added.

## 12. Release boundary

Phase 6A does not perform any of the following:

- complete or re-architect Phase 5 Flutter work;
- install live Stripe or Chargily credentials;
- register production payment webhooks;
- call either provider for live verification;
- claim final legal approval;
- submit mobile apps; or
- perform the final production release.

Stripe and Chargily remain **CODE-CONTRACT VERIFIED** until the separate
provider-activation release is completed.
