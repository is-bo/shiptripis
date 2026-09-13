# H8A — Production readiness and H8B cutover contract

Starting main: `7c67093e88ac9b89386674384158fddeb7147605`.
Branch: `codex/phase-h8a-production-readiness`.
Starting deployed release: `v1.0.0-rc.29+7c67093`.

**Implementation checkpoint, not production certification.** Gemini broad verification,
CI, merge, TEST deployment and deployed H5 acceptance remain pending. H8A performs
no LIVE provider call, checkout, transfer, payout, refund, real DZD settlement,
provider-dashboard change or external email. Local tests use synthetic keys and
synthetic records, including LIVE-labelled fixtures with network refused/mocked.
No schema, migration, backfill or historical financial rewrite is introduced.

## 1. Canonical production mode

`SHIPTRIP_ENVIRONMENT=production` selects the hosting/security profile; it does
**not** mean real money. `PAYMENTS_ENVIRONMENT=test|live` is the deployment's
money intent, defaulting to `test` for existing installations. LIVE requires
setting it explicitly, alongside coherent provider credentials and launch dependencies.
The operator cannot activate real money by replacing one secret.

| Surface | Canonical configuration / evidence |
| --- | --- |
| Stripe API and hosted Checkout | `STRIPE_SECRET_KEY` prefix must agree with `PAYMENTS_ENVIRONMENT`; only `https://api.stripe.com` in production. Hosted Checkout has no client publishable key or mobile provider key. |
| Stripe Connect | Same Stripe API key; `STRIPE_CONNECT_EXPECTED_MODE` must agree with deployment intent; platform `acct_` identity, API version, countries and separate signing secret remain required. |
| Stripe platform webhook | `STRIPE_WEBHOOK_SECRET`; raw-body signature and timestamp verification, then boolean event `livemode`; platform scope only. |
| Stripe Connect webhook | `STRIPE_CONNECT_WEBHOOK_SECRET`; separate raw-body verification, connected `account` scope, boolean mode and expected deployment scope. |
| Chargily | `CHARGILY_SECRET_KEY` (`test_sk_` / `live_sk_`) and exact `CHARGILY_API_BASE` must both agree with intent. `CHARGILY_WEBHOOK_SECRET` empty means the API key signs; a populated override must equal that key. |
| Automatic EUR payout | `PAYOUT_PROFILES_ENABLED`, `STRIPE_CONNECT_ENABLED`, `STRIPE_CONNECT_PAYOUTS_ENABLED`, and versioned `payments.payout.auto_stripe_enabled`; all must authorize execution. Frozen payout/source/account modes must agree. |
| Manual DZD | `PAYOUT_DZD_EXECUTION_ENABLED` plus existing Finance permissions, claim, transactional gates and exact settlement attestation. Mode must equal deployment intent. |
| Finance | `FINANCE_DASHBOARD_ENABLED` controls visibility, never money authority. All five H5.2 destinations default to deployment intent; explicit TEST and legacy audit scopes remain. |
| Email | `EMAIL_ENABLED` maps to Django `TRANSACTIONAL_EMAIL_ENABLED` and Go email worker enablement. Shared environment-only SMTP configuration. Required for LIVE. |
| Push | `FCM_ENABLED`, `FCM_PROJECT_ID`, credential file provisioned from `FCM_CREDENTIALS_JSON_BASE64`. Firebase project identity is independent of payment mode. |
| Public URLs | `PAYMENTS_PUBLIC_BASE_URL` is the hosted API/payment origin; `FRONTEND_BASE_URL` must match it for LIVE in the current combined deployment. |

Versioned business policy remains the source of provider enablement and monetary
rules. Deployment settings authorize a mode and integration; they do not replace
the business policy or snapshot FX. Unknown credential shapes fail closed.

Production startup validates the complete mode tuple without network calls.
Every Stripe/Chargily/Connect transport also checks the credential mode before
provider I/O. Even development cannot issue a LIVE-key request without explicit
LIVE intent. Availability reports `payment_environment_mismatch` for a contradictory
provider instead of offering a checkout that will fail.

## 2. H5.2 blocker consumption

H5 `build_snapshot` adds `payout_attention`, computed under the existing
PostgreSQL repeatable-read, read-only snapshot. The implementation calls the
PRE-H8 `payout_attention` classifier through the same batched related-row loader
as the H5 drilldown. It does not duplicate readiness logic, inspect raw bank
requirements in a template, or derive attention from an operation stage.

The headline is a **unique payout count**. Each payout contributes its one primary
safe `block_reason`, `needs_attention` and nullable `attention_owner`:

| Authoritative owner | Operator category |
| --- | --- |
| traveler | Traveler action required |
| finance | Finance review required |
| provider | Provider action required |
| null | Payout review required — no owner or “acts” label |

Setup/profile blockers count even before delivery/protection expiry. Multiple
holds, disputes, failure and setup conditions on one payout cannot increase its
headline contribution above one. Failed refunds are displayed as independent
issues and excluded from the payout headline. There is no summed “all issues”
number mixing refunds and overlapping payout metrics. No money amount is invented
for these groups.

Every payout category links to the complete `metric=payout_attention` H5
drilldown, which uses the same classifier and supports ordinary pagination and
scope filters; the category links currently share that full attention cohort,
not separate owner-filtered pages. Existing stage cohorts on Payouts/Manual DZD
retain their lifecycle meaning; the Overview blocker drilldown is the route to
profile-only attention that may coexist with a not-due stage.

Classification loads at most 200 payouts per batch, with a 5,000-payout scope
ceiling. Above the ceiling the snapshot reports attention **unavailable**, never
zero or a partial headline; the rest of reconciliation remains available. The
attention drilldown asks the operator to narrow filters. Date periods affect flows,
not current liabilities, so narrow large attention scopes by reference/rail/state.
No schema/index is added. Query and memory costs are bounded; classification does
additional batched database reads, never provider calls.

The recent activity feed includes only payout/refund targets whose persisted mode
matches the selected environment. Audit records targeting a hold, profile or other
object without direct mode authority are omitted from this short feed and retained
in the full audit log. It is contextual recent activity, not a period accounting metric.

## 3. Money history, webhooks and admin safety

PaymentAttempts, provider events, refunds, payout snapshots, source allocations,
disbursements and ledger transactions already preserve mode/provenance. H5's
mode-specific SQL and narrowly evidenced historical derivation are unchanged.
Unknown history never becomes LIVE because deployment credentials change.

H8A rejects cross-mode/unknown objects before checkout recovery, provider polling,
refund requests/execution/manual refund settlement, connected-account refresh,
payout reconciliation, automatic payout dispatch/retry, manual DZD execution and
legacy manual completion. Instruction confirmation/amendment and releasing a hold
also require the target's mode. Opening a safety hold remains possible on historical
records; it does not move money or grant new authority.

Before accepting a new checkout or applying a capture, the order and its related
deal, credited deposits and bound Boost funding must not contain attempts from
another/unknown environment. This prevents an old TEST session or partial funding
from being reused as LIVE payment authority. A funded EUR route must bind an account
in the current environment. Old accounts must be onboarded anew in LIVE; changing
a preference cannot relabel or redirect an already funded snapshot.

Verified wrong-mode platform events are durably recorded and classified
`ignored/mode_isolated` before any payout-domain handler or capture application.
TEST/LIVE event-to-attempt mismatches remain ignored. Missing/nonboolean mode
evidence and contradictory nested object evidence are refused in production.
Provider polling also verifies boolean mode evidence. Signature verification remains
mandatory; mode is checked after signature verification, never as a substitute.
Existing event fingerprint/replay identity, durable jobs and ledger idempotency remain.

Stripe's LIVE Connect endpoint may receive TEST events. Its classifier acknowledges
those without applying them or making cross-mode account reads, consistent with
[Stripe's Connect webhook contract](https://docs.stripe.com/connect/webhooks).
Stripe Checkout and payment-intent events stay separate from Connect bank events.
Chargily's raw HMAC and server-calculated EUR/DZD snapshots remain unchanged;
signed TEST event evidence already exists from H7. Its H8B LIVE webhook/evidence
contract must be confirmed against the provider dashboard. No LIVE validation was
performed in H8A. Reference: [Chargily webhook documentation](https://dev.chargily.com/pay-v2/handle-webhooks).

Money-affecting Finance detail screens explicitly label the object's persisted
TEST/LIVE/legacy mode above the actions. Existing roles, CSRF, optimistic versions,
claim ownership, confirmation and audit records remain in force. Cross-mode refusals
on manual/recovery pages render safely. Raw historical queues remain audit surfaces;
use H5.2 operational destinations for launch work.

## 4. Final payout gates

**Stripe EUR.** Funding freezes rail, amount, method version, account and source mode.
Dispatch rechecks delivery, the 48-hour protection window and I1's funded arrival
floor, holds/disputes, source availability, account ownership/platform/mode,
transfers capability and bank readiness under the existing aggregate lock.
Idempotency keys, exclusive source reservations, provider-operation commitment,
unique transfer/bank allocations and recovery-before-retry remain unchanged.
Bank settlement, not a platform Transfer, discharges traveler liability.

Before a LIVE transfer or bank-payout POST, the adapter retrieves the platform
account, verifies its configured identity and requires `details_submitted`,
`charges_enabled` and `payouts_enabled` to be true. Failure defers the operation;
no money POST is sent. This read is not part of startup or public readiness.
The real H8B account review remains necessary: code cannot prove contracts, legal
eligibility, dashboard terms acceptance or the correctness of human-supplied bank data.

**Manual DZD.** H4's TEST-only literal is replaced by comparison to the explicit
deployment mode. This makes future activation configurable without enabling it
now. Frozen profile/version, historical identity approval, FX and DZD amount,
Finance claim, request fingerprint, source reservation, receipt and explicit
sent-versus-settled attestation remain mandatory. Both the release gate and final
manual gate honor the funded arrival floor. No provider API is involved.

H8A keeps DZD execution **false**. A LIVE deal-balance checkout into a DZD route
is refused while execution is disabled, preventing an obligation with no enabled
settlement path. H8B should initially keep Chargily new checkouts disabled too;
enable the DZD/Chargily product route only after the owner approves an operational
Finance settlement process. DZD must never be rehearsed or marked settled as if
real money moved when none did.

## 5. Email, push and mobile

**Email is required for launch.** `DealRecipient` explicitly supports recipients
without a ShipTrip account. Handover release schedules their delivery-code email
after the 30-minute pickup buffer. Secret-bearing messages are rendered at send time
and sent by Django, not serialized as plaintext codes into Redis. Sender-only code
access remains; travelers cannot retrieve the code. Relying on the sender to forward
it is a workaround, not the contracted recipient delivery channel. Email also serves
sender verification, guest payment links/receipts, refund and payout/account alerts.

With `EMAIL_ENABLED=false`, dispatch returns disabled and leaves obligations pending;
the sender/recipient verification and delivery channels do not work as promised.
In-app lifecycle/financial state can continue, so a successful H7 handover does not
prove email readiness. LIVE startup therefore requires email enabled, and existing
production validation requires SMTP host/from and sending-domain verification.
Sender.net additionally requires credentials and TLS. Secrets stay in environment.

The read-only runtime audit found **77 pending and 28 cancelled outbox messages**.
Enabling email can dispatch that backlog. H8B must review it before enabling email,
cancel only confirmed obsolete/rehearsal obligations through
`apps.notifications.outbox.cancel_message(key=..., reason=...)`, retain records,
and record a reviewed key/ID manifest without publishing recipients/codes. Do not
delete the outbox or bulk-infer consent from an email suffix. Any uncertain message
is an activation blocker. This task cancelled or sent nothing.

**Push is optional.** FCM delivery failures retry/report feedback and do not settle
payments or change ledger authority. In-app notifications remain the durable product
channel. Existing launcher validates and writes the Firebase service-account file,
strips the base64 value, and the notification worker validates configuration. Invalid
enabled credentials can fail that worker's startup and hence the combined supervisor;
`FCM_ENABLED=false` is the explicit safe operational fallback. No credentials were
rotated. H8B must verify mobile Firebase project/package alignment and consented device
delivery separately; presence of credentials is not delivery proof.

**Mobile correction.** The previous deployment note was inaccurate: `AppConfig`
defaulted to `http://10.0.2.2:8080`. Debug retains that convenience; release defaults
to empty and calls explicit validation before any integration starts. Release
API/KYC origins must be supplied, HTTPS, without credentials/query/fragment/path,
and cannot be localhost/emulator/reserved test hosts. `KYC_BASE_URL` defaults to
API origin; WebSocket remains derived as `https -> wss`. There is no fixed Railway
origin in application configuration. H8B release command must supply
`--dart-define=API_BASE_URL=https://shiptrip-production-f7f7.up.railway.app`.
No release APK was built. The map tile provider/contact/attribution contract remains
a separate mobile release prerequisite, not a payment credential.

## 6. Origin matrix (current and H8B target)

Let `O = https://shiptrip-production-f7f7.up.railway.app`. A different host requires
reviewing this entire matrix before activation; it is not a one-secret change.

| Use | Exact origin or path |
| --- | --- |
| API / mobile / KYC default | `O`; mobile API routes append `/api/...` |
| WebSockets | `wss://shiptrip-production-f7f7.up.railway.app` plus existing WS routes |
| `PAYMENTS_PUBLIC_BASE_URL`, `FRONTEND_BASE_URL` | `O` |
| Platform webhook | `O/api/payments/webhooks/stripe` |
| Connect webhook | `O/api/payments/webhooks/stripe-connect` |
| Chargily webhook | `O/api/payments/webhooks/chargily` (sent in each checkout's `webhook_endpoint`) |
| Checkout success / failure | `O/pay/<order UUID>/return?result=success` / `?result=failure` |
| Connect return | `O/payouts/stripe/return` with server-signed state appended |
| Connect refresh | `O/payouts/stripe/refresh` with server-signed state appended |
| Email site links | `FRONTEND_BASE_URL=O`; secret links/codes retain their own authorization/expiry |
| Finance | `O/admin/finance/dashboard/` and sibling payout/manual/exceptions/reconciliation routes |
| Hosts / CSRF / CORS | Explicit hostname `shiptrip-production-f7f7.up.railway.app`; trusted origins include `O`, no wildcard |
| Mobile notification links | Existing app routes/deal references; payment mode is never derived from a deep link |

Railway variable audit confirmed the public/payment/frontend/return/refresh origin
matches and official Stripe API origin. H8B must separately confirm provider
dashboard URL subscriptions. A real HTTPS hostname is not intrinsically TEST or
LIVE; code rejects obvious reserved/local origins but cannot infer the operator's
intended production DNS ownership from its spelling.

## 7. Railway audit and flags

Read-only CLI inspection on 2026-09-13, CLI 5.35.2; no variable writes or deploys.
Project `d7aeffbc-05b0-4c62-86a6-43e8fc99de88`, environment
`e83d6196-1d8d-47a2-b210-dc391f7b6aaa`, service `shiptrip`
(`f56dc033-2989-4e2c-9fa5-809e989c2e90`). Runtime policy read confirmed the
starting release and all four enablement values below. Secret values were not emitted.

| Variable / source | Current H8A audit | Launch requirement / H8B action |
| --- | --- | --- |
| `PAYMENTS_ENVIRONMENT` | Missing; H8A code default TEST | Add explicit `test` at H8A TEST deployment; replace with `live` only in coherent H8B activation batch |
| `STRIPE_SECRET_KEY` | Present, TEST | Replace with platform LIVE secret/restricted key with required permissions |
| `STRIPE_WEBHOOK_SECRET` | Present, opaque | Replace with LIVE **platform** endpoint signing secret |
| `STRIPE_CONNECT_WEBHOOK_SECRET` | Present, opaque, distinct from platform secret | Replace with LIVE **connected-account** endpoint secret |
| `STRIPE_CONNECT_PLATFORM_ACCOUNT_ID` | Present | Verify LIVE platform identity; change only if different |
| `STRIPE_API_BASE` | Present, official origin | Retain |
| `STRIPE_API_VERSION` | Empty (platform default) | Explicitly pin reviewed contract, `2026-03-25.dahlia`, alongside both endpoint versions |
| `STRIPE_CONNECT_API_VERSION` | Present | Retain reviewed `2026-03-25.dahlia`; no incidental API upgrade |
| `STRIPE_CONNECT_ALLOWED_COUNTRIES` | Present | Verify approved LIVE countries within FR/DE/ES; never add DZ |
| `CHARGILY_SECRET_KEY` | Present, TEST | Replace with LIVE key in the activation batch, or remove all Chargily credentials while that rail stays disabled |
| `CHARGILY_API_BASE` | Present, TEST | Replace with `https://pay.chargily.net/api/v2` if LIVE key configured |
| `CHARGILY_WEBHOOK_SECRET` | Empty, API-key fallback | Retain empty; no Stripe-style separate secret invented |
| `EMAIL_SMTP_HOST`, username, password, `EMAIL_FROM_ADDR` | Empty | Supply verified sender SMTP configuration; secret values through secure Railway inputs |
| `EMAIL_SMTP_PORT`, `EMAIL_PROVIDER` | Present | Confirm SMTP port/provider matches both Django and Go configuration |
| `EMAIL_USE_TLS` | True | Retain TLS |
| `EMAIL_SENDING_DOMAIN_VERIFIED` | False | Set true only after provider DNS verification and sender review |
| `DEFAULT_FROM_EMAIL`, `EMAIL_SUPPORT_ADDR` | Empty | Set reviewed sender/support identity as applicable; do not leave a misleading default |
| `TRANSACTIONAL_EMAIL_SECRET` | Present | Retain; do not rotate capability-signing secrets during payment cutover |
| `FCM_PROJECT_ID`, `FCM_CREDENTIALS_PATH`, base64 service-account JSON | Present | Retain; verify alignment, no unnecessary rotation |
| Payout encryption keyring/active ID/fingerprint key | Present | Retain, required for frozen historical profiles |
| Payout private-storage access/secret keys | Present | Retain; confirm evidence read/write permissions separately |
| Origin/hosts/CSRF/CORS settings | Present, origin checks agree | Retain matrix above; provider-dashboard verification remains external |

Flag changes below belong to **Claude/H8B with the owner**, except the H8A TEST
deployment's explicit `PAYMENTS_ENVIRONMENT=test` addition after release gates.

| Flag | Current | Initial cutover / launch | Ordering | Safe stop / rollback |
| --- | --- | --- | --- | --- |
| Finance dashboard | true | true | Keep available throughout | true |
| Payment environment | implicit test | explicit live | All credentials/expected modes in one stopped-service batch | Retain live after any LIVE activity; test only in a proven no-LIVE-history rollback |
| Connect expected mode | test | live | Same batch as payment intent/key | Match chosen rollback mode |
| Payout profiles | true | true | LIVE boot prerequisite | true |
| Connect enabled | true | true | Complete LIVE account/config first | Keep on for servicing history |
| Connect payouts enabled | true | false for no-money smoke; true for payout launch | Enable only after account/webhook checks | false, retain reconciliation |
| DZD execution | false | false initially; true only for separately approved DZD operations | Never enable before staff/process/evidence readiness | false |
| Non-Stripe EUR funding | false | false | Always | false |
| Email enabled | false | true | Review 77-message backlog, verify sender, then activation | Keep true for LIVE servicing; disabling requires a deliberate outage decision |
| FCM enabled | true | true if verified, otherwise false | Independent of money activation | false if broken |
| Mock provider/webhook/legacy mutations | false / false / false | false / false / false | Always production boot guards | false / false / false |
| Business `providers.stripe_enabled` | true | false during cutover; true for collection launch | Enable last after no-money checks | false |
| Business `providers.chargily_enabled` / `chargily.new_checkouts_enabled` | true / true | false / false initially; enable with approved DZD route | After LIVE key/callback evidence and DZD readiness | false / false |
| Business `payout.auto_stripe_enabled` | true | false during cutover; true for payout launch | Both payout switches required | false |

## 8. Startup / readiness / feature behavior

* **Hard startup refusal:** production money-mode contradictions, unknown money mode,
  unsupported API origins, signing-key configuration contradictions, inconsistent
  Connect mode/URLs, existing mock/legacy safety flags, missing production secrets,
  and LIVE without payout profiles or email readiness. No provider I/O is done at boot.
* **`/readyz` unhealthy:** existing database, pending migrations, or shared rate-limit
  cache failures. `/healthz` is process liveness. Payment-provider/SMTP/FCM network
  outages do not become synchronous public readiness probes.
* **Feature refusal:** missing disabled provider, provider policy off, payout execution
  off, DZD flag off, foreign-mode object, missing readiness, expired code or absent
  permissions. Existing money history stays recorded. Mode mismatch cannot fall back
  to mock, another currency or another account.
* **Operator warning / degraded feature:** failed email/push delivery, missing provider
  balance/cost evidence, legacy provenance, or attention scope above the bound.
  Existing enabled-invalid FCM startup behavior is disclosed in section 5.

## 9. Exact H8B sequence — not performed by H8A

1. **Freeze the release record.** Use the final H8A main SHA only after Gemini, CI,
   TEST deployment and deployed H5 acceptance pass. Record full SHA, release,
   deployment ID, active business-settings version and current variable-name/class
   manifest. Do not substitute this starting SHA or an unreviewed worktree.
2. **Back up and verify recovery.** Take a restricted encrypted PostgreSQL snapshot;
   record timestamp/checksum and recent successful isolated restore evidence using
   `DEPLOYMENT_RUNBOOK.md`. Preserve all TEST rows, evidence keys and encryption keys.
3. **Freeze new work while still TEST.** Through a versioned settings revision disable
   new Stripe/Chargily collection and `payments.payout.auto_stripe_enabled`. Set both
   payout execution flags false. Stop new QA actions, drain/review in-flight TEST
   checkout/reconciliation/transfer/bank jobs and record unresolved TEST obligations.
   Do not relabel, delete or reset them. Any outstanding provider commitment must be
   reconciled in TEST before switching the single-mode service.
4. **Resolve email backlog.** While email remains disabled, inspect all pending outbox
   obligations in the permissioned environment. Record and cancel only explicitly
   reviewed obsolete rehearsal keys via `cancel_message`, preserving history. Verify
   no uncertain message will be sent at activation. Configure/verify sender domain,
   SPF/DKIM and SMTP TLS credentials in the email provider. Obtain owner approval for
   a real transactional-email validation in H8B; H8A grants no send authorization.
5. **Stripe dashboard LIVE setup.** Verify the platform legal entity, activation,
   bank, charge/payout readiness and Connect terms. Confirm the same platform ID or
   record the replacement. Confirm Express/application-controlled manual payout
   schedule and only approved FR/DE/ES country availability. Do not reuse TEST
   connected-account IDs or synthetic KYC. Create LIVE platform and Connect event
   destinations using the matrix and event lists below; pin the reviewed API version.
   Store their two separate secrets securely. Do not initiate a payment.
6. **Chargily dashboard LIVE setup.** Verify merchant LIVE activation, permitted
   settlement/refund process and LIVE key. Confirm the callback path in the matrix;
   the application supplies `webhook_endpoint` on each checkout. If the provider UI
   offers an account-level callback, set the same exact path. Verify signing uses the
   LIVE API secret; leave the override empty. Keep new checkouts disabled pending DZD
   operational approval. Do not create a checkout to test configuration in H8B.
7. **Stop the combined application before credentials change.** This stops Django,
   finance workers and Go children together. A rolling overlap of old TEST and new
   LIVE workers against the same database is forbidden. Preserve the current variable
   bundle in the secret manager. Stage the complete LIVE mode/key/webhook/API-origin/
   email configuration with Railway pending variables / `--skip-deploys`, without
   logging values or enabling execution. Review the resolved bundle before restart.
8. **One deploy/restart of the exact reviewed artifact.** `PAYMENTS_ENVIRONMENT=live`,
   all configured rails LIVE, Connect expected mode LIVE, email enabled and verified,
   Finance on, profiles on, mock/non-Stripe EUR/legacy off, execution flags initially
   off. An intentionally omitted rail must have no conflicting credentials and stay
   disabled in policy. Do not “fix” a startup guard by weakening it. Validate service
   SUCCESS, `/healthz` and `/readyz` 200, migration plan empty, process/worker health,
   and sanitized configuration classes. No queued TEST job may make a LIVE API call.
9. **No-money smoke first.** Check authenticated Finance defaults LIVE; explicit TEST
   and legacy audit history remain readable and visibly labelled. Reconciliation on
   fresh LIVE scope should be empty/zero and balanced, not TEST money presented as
   LIVE. Verify rejected signature and wrong-mode behavior without fabricating real
   provider authority; inspect provider-generated informational webhook deliveries,
   correct endpoint scopes/signatures, boolean mode, duplicate handling and durable
   processing. Verify email with the separately approved recipient and mobile release
   API/WebSocket config. Onboard real eligible Connect accounts only with consent;
   onboarding is not a money smoke. Confirm platform readiness through authorized
   H8B no-money provider reads/dashboard evidence.
10. **Enable collection and payout operations deliberately.** After checks, create a
    versioned policy revision enabling Stripe collection and, when approved,
    `auto_stripe_enabled`; enable `STRIPE_CONNECT_PAYOUTS_ENABLED`. For DZD launch,
    review Finance staffing, claims, payout evidence storage, real settlement account,
    receipts, FX and refund process, then explicitly enable DZD execution before
    allowing new Chargily/DZD collection. Otherwise keep that route disabled and
    disclose the launch limitation. No money movement is authorized merely by this
    document; H8C decision belongs to the owner.
11. **Close TEST endpoint overlap.** Keep TEST endpoints intact in H8A. In H8B, after
    TEST work is reconciled, record endpoint IDs/subscriptions and disable delivery to
    the shared production origin when switching secrets. New LIVE endpoints may
    temporarily return signature errors while old code runs; collection is frozen,
    and provider retries/redelivery must be reconciled after activation. The service
    supports one signing secret per scope, not simultaneous TEST/LIVE keys. Never
    merge secrets or skip verification to make overlap appear healthy. Retain endpoint
    records and history for audit/rollback; do not delete them.

Stripe platform events (16): `checkout.session.completed`,
`checkout.session.async_payment_succeeded`, `checkout.session.async_payment_failed`,
`checkout.session.expired`, `payment_intent.payment_failed`, `transfer.created`,
`transfer.reversed`, `balance.available`, `refund.created`, `refund.updated`,
`refund.failed`, `charge.dispute.created`, `charge.dispute.updated`,
`charge.dispute.closed`, `charge.dispute.funds_withdrawn`,
`charge.dispute.funds_reinstated`.

Stripe Connect events (11): `account.updated`, `capability.updated`,
`account.external_account.created`, `account.external_account.updated`,
`account.external_account.deleted`, `payout.created`, `payout.updated`,
`payout.paid`, `payout.failed`, `payout.canceled`, `balance.available`.
`account.application.deauthorized` is recorded/deferred if received, not an additional
money handler. Do not switch to v2 thin events or change scope/version incidentally.

Chargily checkout lifecycle: `checkout.paid`, `checkout.failed`, `checkout.canceled`,
`checkout.expired`; confirm actual provider delivery and boolean mode evidence.

## 10. Rollback contract

**Before any LIVE financial activity:** freeze business collection and both payout
flags; stop the combined service; restore the complete preserved TEST variable bundle
including payment intent, Connect expected mode, both Stripe endpoint secrets and
Chargily key/base. Restore email to the approved prior state only after reviewing
whether any legitimate LIVE communication obligations were created. Re-enable the
original TEST endpoints, disable the new LIVE destinations, restart the reviewed
H8A code, verify TEST health/readiness/H5 integrity and worker state, then restore the
approved TEST policy. Keep the new code's explicit `PAYMENTS_ENVIRONMENT=test`.

**After any LIVE capture, payout commitment or external settlement:** do **not**
flip the service back to TEST, restore an old database over new money, reset an
idempotency key or delete history. Disable new collection and payout execution,
retain LIVE credentials, webhook secrets and financial reconciliation, keep email
servicing legitimate obligations, and investigate/roll forward. A code rollback must
retain H8A's mode guards and support the recorded financial state; pre-H8A code is
not a safe LIVE rollback target. Export a restricted incident snapshot and reconcile
every uncertain provider operation before resuming. A TEST audit service, if needed,
must be separately isolated and must not write to this LIVE database.

## 11. H8C recommendation for owner review

Prefer **zero-money H8B validation followed by monitoring the first genuine customer
transaction**, rather than an artificial charge/refund cycle. H7 already exercises
the money state machines; LIVE account permissions, signatures and delivery evidence
can first be checked without moving money. This is not end-to-end LIVE certification:
record that qualification until a genuine LIVE capture and eventual settlement have
been reconciled.

If the owner requires a controlled tiny-money certification, authorize it separately:
one consenting sender, one real compliant delivery and real eligible traveler/account,
the smallest **server-valid** reward/fee/payment amount (not an arbitrary one-cent
bypass), one Stripe payment, normal pickup/code/protection/arrival timing, and a bank
payout only when legally and operationally appropriate. No forced refund unless a
genuine refund case requires it, no accelerated clocks and no simulated DZD settlement.
Observe provider event mode/signature, exactly-once ledger effects, funding/liability
reconciliation and eventual bank outcome. Decide costs and consent before executing.

## 12. Verification and remaining gates

Fast checks run by Codex: new mode/transport/Overview tests, selected pure Connect
configuration tests, production entrypoint smoke/refusal, one PostgreSQL blocker/
duplicate/owner/drilldown/signed-webhook/history regression, one synthetic LIVE DZD
claim/flag regression, final arrival-floor checks, Ruff and the mobile release-origin
unit test. Targeted Python runs finished in seconds; a three-file Flutter analysis
also passed, but took 34.9 seconds. No broader analysis or build was run by Codex.
Longer verification belongs to Gemini under the phase workflow.
The existing local PostgreSQL cluster required restart/recovery; the first attempted
test failed on connection setup and is not counted as passing. One test assertion
initially mistook H4 `prepare`'s returned payout for an attempt; corrected and rerun.

Latest focused evidence (2026-09-13, local only):

| Check | Result |
| --- | --- |
| `pytest -q apps/finance/tests/test_h8a_guards.py apps/finance/tests/test_phase8fh2_deployment.py::TestDisabledDeployment apps/finance/tests/test_phase8fh2_deployment.py::TestEnabledDeployment --ds=config.settings.test_local --tb=short` | 55 passed, 3.10s; one existing Django URLField deprecation warning |
| `pytest -q apps/finance/tests/test_h8a_finance.py::test_profile_attention_aggregate_drilldown_and_cross_mode_history --ds=pre_h8_settings --reuse-db --tb=short` | 1 passed, 8.95s; includes cancelled-row alignment |
| `pytest -q apps/finance/tests/test_h8a_finance.py::test_manual_dzd_explicit_live_intent_still_requires_execution_flag --ds=pre_h8_settings --reuse-db --tb=short` | 1 passed, 4.69s |
| `flutter test test/core/env/app_config_test.dart --no-pub` | 1 passed |
| `flutter analyze lib/core/env/app_config.dart lib/main.dart test/core/env/app_config_test.dart --no-pub` | No issues, 34.9s |
| Ruff on Finance, modified admin modules and settings; `git diff --check` | Passed |

Python commands run from `backend/monolith` with the existing `.venv`; PostgreSQL
commands use `PYTHONPATH=D:/Code/Shiptrip/.tmp` and the existing local cluster.
Flutter commands run from `mobile`. Historical-credit review also fixed null-deal
Boost selection: an unattached order cannot inherit unrelated unattached Boosts.

Gemini owns broad Finance/payment/auth/handover/notification/I1 compatibility,
migration/schema-drift verification, full Django suite if used, and longer mobile
analysis. Gemini must not fix, commit, deploy, call providers or send messages.
Codex analyzes the report and owns fixes. CI runs once after Gemini is clean; merge,
branch cleanup, TEST deployment and exactly one deployed read-only H5 snapshot follow.
No PASS claim is made before those gates.

Remaining prerequisites:

* **BLOCKER (release):** Gemini report, CI, reviewed main, TEST deployment health,
  migrations/workers and H5 zero differences/row mismatches/balanced ledger.
* **BLOCKER (H8B activation):** real LIVE provider activation and secrets/endpoints;
  email sender/SMTP verification and explicit disposition of the 77 pending messages;
  frozen TEST work/commitments reviewed; coherent stopped-service cutover bundle.
* **MAJOR (DZD product launch):** owner-approved real manual-settlement/refund process,
  staff and evidence readiness before enabling DZD and Chargily new collection.
* **MAJOR (mobile release):** correct API/KYC defines, actual device/push project
  validation and approved production map tile contract.
* **MINOR:** attention scopes above 5,000 require narrowing; owner groups share the
  full attention drilldown; profile/hold-target activity remains in the full audit log;
  provider balances/costs are not invented by H5.

H8B may use this contract only after H8A release gates pass. H8A does not perform H8B.
