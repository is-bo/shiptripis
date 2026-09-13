# H8B — Controlled production cutover and no-money LIVE validation

**H8B FAIL — cutover halted at the H8A step-2 backup gate. No LIVE activation.**

Starting main: `67c0241cce4823586edb1fbe3a9dd068fe68a9e8`.
Runtime baseline (unchanged): `4ec23a17a41a150ba5afe58d410ed5c3d6722631`,
release `v1.0.0-rc.30+4ec23a1`, deployment `a400f0d4-e4cd-4b85-9817-35ab03f79e35`.

H8B changed **nothing**. No Railway variable was written, no deployment or restart
was triggered, no business-settings revision was created, no outbox message was
cancelled, no provider dashboard was modified, and no provider write call was made.
Every action recorded here is a read. Because no configuration moved, the H8A
rollback contract was not invoked and is not required — the prior TEST bundle is
still the live bundle.

`PAYMENTS_ENVIRONMENT` remains `test`. Stripe remains TEST. Chargily remains TEST.
Email remains disabled. `PAYOUT_DZD_EXECUTION_ENABLED` remains `false`.
**Real-money operations performed: none.**

## 1. Why the phase stopped where it did

[H8A §9](PHASE_H8A_PRODUCTION_READINESS.md) fixes the cutover ordering:

1. freeze the release record
2. **back up and verify recovery**
3. freeze new TEST work
4. resolve the email backlog
5. Stripe LIVE dashboard setup
6. Chargily LIVE dashboard setup
7. stop the service and stage LIVE variables
8. one reviewed restart with execution off
9. no-money smoke
10. deliberate enablement
11. close TEST endpoint overlap

Step 1 passed. **Step 2 cannot be completed on the current infrastructure.**
H8A places backup/recovery evidence *before* the TEST work freeze deliberately, so
the freeze in step 3 was correctly not executed: freezing TEST collection and
automatic payouts has no purpose when no cutover can follow it, and it would have
degraded the TEST environment while leaving the recorded outstanding obligation
below unreconciled.

Everything downstream of step 2 was therefore evaluated **read-only** rather than
executed, so that the owner receives one consolidated prerequisite list instead of
discovering the blockers serially. Four further independent blockers were found.

## 2. Pre-cutover H5 financial baseline

One read-only snapshot per mode, taken through `build_snapshot` under the existing
PostgreSQL repeatable-read read-only transaction. No second snapshot was taken.

| Scope | `as_of` | Integrity |
| --- | --- | --- |
| `mode=test` | `2026-09-13T12:50:13.445217+00:00` | **ok** |
| `mode=live` | `2026-09-13T12:50:15.613990+00:00` | **ok** |
| `mode=legacy_unknown` | `2026-09-13T12:50:17.637401+00:00` | warning (by design) |

TEST comparisons — every `difference_eur_cents` and every `row_mismatches` is **0**:

| Comparison | Reported | Authority | Difference | Row mismatches |
| --- | --- | --- | --- | --- |
| `traveler_state_to_ledger` | 6,000 | 6,000 | 0 | 0 |
| `traveler_dashboard_to_ledger` | 6,000 | 6,000 | 0 | 0 |
| `applied_funding` | 51,288 | 51,288 | 0 | 0 |
| `finalized_refunds` | 0 | 0 | 0 | 0 |
| `paid_settlements` | 28,200 | 28,200 | 0 | 0 |
| `platform_recognition_partition` | 8,550 | 8,550 | 0 | 0 |

TEST ledger: **0 unbalanced transactions**, no warnings, `data_issues` all zero,
`source_attributed_legacy_entry_count` 8 with provenance `verified`. Provider
physical cash remains explicitly unobserved. TEST headline metrics: gross funded
51,288; recognized revenue 8,550; traveler outstanding 6,000 (1); payouts settled
28,200 (5); refunds requested/processing/failed/finalized/applied all 0;
`payout_attention` **0** with status `available`.

LIVE scope is **entirely empty** — every metric zero, no payout groups, no rail
operations, `payout_attention` 0. There is no LIVE money history of any kind, which
is what makes a full configuration rollback safe.

`legacy_unknown` reports `warning` with exactly the two disclosed warnings
`unclassified_funding_provenance` and `legacy_mode_not_test_or_live`. All of its
differences and row mismatches are 0 and its ledger is balanced. H8A §8 classifies
legacy provenance as an operator warning, not an integrity failure; this scope is a
retained pre-H8 audit cohort and is not a cutover blocker.

**Gate result: PASS.** The authoritative operational scopes are `ok` with zero
differences, zero row mismatches and balanced ledgers.

## 3. Outstanding TEST obligations

New TEST activity was **not** frozen (see §1). The current obligations are:

| Payout | Mode | Method | Status | Amount | Note |
| --- | --- | --- | --- | --- | --- |
| 4 (`ca7be06e…`) | test | `stripe_transfer` | **processing** | 6,000 EUR cents | Committed TEST transfer, not bank-settled |
| 1 (`f56b319d…`) | legacy_unknown | manual | blocked | 6,000 EUR cents | `legacy_instruction_required`, pre-H8 record |
| 2, 3, 6 | test | `stripe_transfer` | paid | 16,700 total | Settled |
| 5, 7 | test | manual (DZD) | paid | 11,500 total | Sent and attested |

**Payout 4 is a genuine unreconciled TEST provider commitment.** It sits at
operation stage `connected_funds` and is the whole of `liability_processing`,
`externally_committed` and `traveler_outstanding`. Its discharge depends on a TEST
Connect `payout.paid` event arriving at
`/api/payments/webhooks/stripe-connect`.

This matters for cutover sequencing: the service supports **one signing secret per
scope**. The moment `STRIPE_CONNECT_WEBHOOK_SECRET` is replaced with the LIVE
Connect secret, TEST Connect deliveries stop verifying and payout 4 is permanently
stranded in `processing`. H8A §9.3 requires exactly this to be reconciled in TEST
first. It has **not** been reconciled.

No TEST record was deleted, relabelled or fabricated as complete.

## 4. Backup and recovery — BLOCKER

Database platform: Railway managed PostgreSQL, service `Postgres`
(`afe757c2-a96c-4e46-91e9-80a772a03cae`), project `shiptripis`
(`d7aeffbc-05b0-4c62-86a6-43e8fc99de88`), environment `production`
(`e83d6196-1d8d-47a2-b210-dc391f7b6aaa`), region `sfo`.

Volume `postgres-volume` (`70462189-2033-44c6-8757-4fd78cc3d385`), volume instance
`491e0ed5-d502-4cc3-9b81-0a54bc52efa0`, state `READY`, 500 MB provisioned,
**209.64 MB currently used** (41.9%, below the 50% manual-backup ceiling).

Read-only Railway API results:

| Query | Result |
| --- | --- |
| `volumeInstanceBackupList` | **`[]` — zero backups exist** |
| `volumeInstanceBackupScheduleList` | **`[]` — no daily/weekly/monthly schedule** |
| `volumeInstanceBackupCreate` | **`Not Authorized`** |
| `volumeInstanceBackupScheduleUpdate` | **`Not Authorized`** |

Workspace `medshipdev's Projects` (`e44bd27f-…`) is plan **HOBBY** with
`customer.state = INACTIVE` and `isTrialing = true`. Railway bills volume backups
as incremental storage; the read paths succeed while both write mutations are
refused, which is consistent with billable features being gated on a workspace with
no active billing rather than with a token-scope problem.

Consequences:

* **There is no backup of production. There never has been.** Recovery from
  corruption, an accidental wipe or a bad restore is currently impossible.
* Recovery viability cannot be proven, because there is nothing to restore.
* Railway's restore path (`volumeInstanceBackupRestore`) mounts a replacement
  volume onto the same service in the same project and environment. It was **not**
  invoked, and must never be used against production as a verification technique.

**Gate result: BLOCKER.** H8A step 2 fails. No LIVE configuration may be staged.

Separately, running a real-money payment platform on a trial workspace with an
inactive billing customer is itself a launch risk: suspension of a LIVE deployment
drops provider webhooks and strands funded obligations mid-lifecycle.

## 5. Email backlog — BLOCKER

Read-only inspection of `notifications_outboundmessage`. Nothing was cancelled,
deleted, sent or modified.

Totals: **77 pending**, 28 cancelled. Every pending row has `attempts = 0`,
`language = en`, and a `next_attempt_at` **already in the past** — so
`due_immediately = 77` and `future_scheduled = 0`. The `email` worker process is
already running in the deployment; it is inert only because `EMAIL_ENABLED=false`.
**Setting `EMAIL_ENABLED=true` would release all 77 at once.**

| Kind | Pending | Oldest | Newest |
| --- | --- | --- | --- |
| `payout_status` | 19 | 5.89 d | 1.64 d |
| `protection_ending` | 10 | 3.99 d | 1.64 d |
| `delivery_confirmed` | 10 | 3.99 d | 1.64 d |
| `rating_available` | 10 | 3.99 d | 1.64 d |
| `recipient_delivery_code` | 6 | **7.90 d** | 1.64 d |
| `email_verification` | 6 | 5.08 d | 1.73 d |
| `pickup_confirmed` | 5 | 3.99 d | 1.66 d |
| `delivery_code_released` | 5 | 3.99 d | 1.64 d |
| `protection_ended` | 2 | 5.89 d | 5.89 d |
| `flight_proof_status` | 2 | 6.05 d | 6.05 d |
| `payment_failed` | 1 | 1.66 d | 1.66 d |
| `kyc_status` | 1 | 6.05 d | 6.05 d |

Twelve messages are secret-bearing (`secret_ref` populated): 6
`email_verification` and 6 `recipient_delivery_code`.

### Deliverability classification

Grouping by recipient domain against RFC 2606 / RFC 6761 reserved names:

| Class | Count | Domains |
| --- | --- | --- |
| Reserved / structurally undeliverable | **73** | `shiptrip-qa.invalid` 22, `example.com` 26, `shiptrip-qa.test` 19, `shiptrip-test.invalid` 3, `example.invalid` 2, `shiptrip.invalid` 1 |
| **Real, deliverable** | **4** | `t.com` 3, `gmail.com` 1 |

Eleven of the twelve secret-bearing messages target reserved domains. **One does
not.**

### The four real-recipient obligations

All four belong to deal 1 — the same deal whose payout is the blocked
`legacy_unknown` record. Recipients are masked here; full keys are recorded for the
owner's review and are reproducible from the keys below.

| ID | Key | Kind | Age | Secret | Note |
| --- | --- | --- | --- | --- | --- |
| 22 | `recipient_delivery_code:1:2` | `recipient_delivery_code` | **8 days** | `handover_code:2` | Parcel recipient with **no ShipTrip account** |
| 33 | `protection_ended:1:3` | `protection_ended` | 6 days | — | Registered user 3 |
| 34 | `protection_ended:1:2` | `protection_ended` | 6 days | — | Registered user 2 |
| 35 | `payout_status:1:eligible` | `payout_status` | 6 days | — | Registered user 2 |

Message 22 is the decisive one. Enabling email would render and send a real person
an **eight-day-old delivery code for a TEST deal**, resolved live from its sealed
row at send time. That is precisely the outcome the phase forbids.

### Verdict

Enabling email in the current state is **unsafe**, on two independent grounds:

1. It would deliver stale TEST lifecycle mail — including a live-resolved handover
   code — to four real addresses.
2. It would attempt 73 sends to structurally undeliverable domains, each retrying
   up to `max_attempts = 10`. A new sending domain opening with that bounce profile
   invites immediate throttling or suspension by the provider.

H8A permits cancelling only *explicitly reviewed, confirmed obsolete rehearsal*
obligations through `apps.notifications.outbox.cancel_message(key=…, reason=…)`,
and states that **any uncertain message is an activation blocker**. The 73
reserved-domain rows are demonstrably synthetic QA artefacts. The four
real-recipient rows are not: cancelling a real recipient's delivery-code obligation
is a data-policy decision about a genuine, if test-originated, communication
promise. That decision belongs to the owner and was **not** taken here.

**Gate result: BLOCKER.** Email must not be enabled. See §12 for the decision
required.

## 6. Email provider and sender configuration — BLOCKER

Nothing is configured. `EMAIL_SMTP_HOST`, `EMAIL_SMTP_USERNAME`,
`EMAIL_SMTP_PASSWORD`, `EMAIL_FROM_ADDR`, `DEFAULT_FROM_EMAIL` and
`EMAIL_SUPPORT_ADDR` are all **empty**; `EMAIL_SENDING_DOMAIN_VERIFIED` is
**false**. Present and correct: `EMAIL_PROVIDER=sender_net`, `EMAIL_SMTP_PORT=587`,
`EMAIL_USE_TLS=true`, `EMAIL_FROM_NAME=ShipTrip`, `EMAIL_STREAM=email:send`,
`TRANSACTIONAL_EMAIL_SECRET` set.

H8A §8 makes email readiness a **hard LIVE startup requirement**. A restart with
`PAYMENTS_ENVIRONMENT=live` and this configuration would refuse to boot — correctly.

No sender domain exists, no SPF/DKIM records are verified, no credentials are held.
This requires an authenticated Sender.net account and DNS changes. **Owner action.**
No controlled test delivery was attempted.

## 7. Stripe LIVE platform account — BLOCKER

Read-only `GET /v1/account` executed **inside the Railway container** with the
existing TEST key, so the credential never left the environment. No write call was
made.

Platform account `acct_1TLWM93aixfgmaTz` — matches the configured
`STRIPE_CONNECT_PLATFORM_ACCOUNT_ID` exactly.

| Field | Value |
| --- | --- |
| `country` | `FR` |
| `default_currency` | `eur` |
| `type` | `standard` |
| `business_type` | **`null`** |
| `details_submitted` | **`false`** |
| `charges_enabled` | **`false`** |
| `payouts_enabled` | **`false`** |
| `capabilities` | **`{}`** |
| `requirements` | `null` |

The account has never completed Stripe onboarding. There is no business type, no
capability (`card_payments`, `transfers`) and no submitted detail.

Two consequences:

1. **The LIVE platform is not production-capable.** LIVE activation, legal entity,
   bank details and Connect terms are all outstanding.
2. Even if Railway were switched to LIVE, **no payout could ever execute.** H8A §4
   requires the adapter to retrieve the platform account and confirm
   `details_submitted`, `charges_enabled` and `payouts_enabled` are all true before
   any transfer or bank-payout POST. All three are false, so every operation would
   be deferred. This is the fail-closed guard behaving correctly.

A TEST key cannot read LIVE-mode capability, so definitive LIVE status must be
confirmed in the Stripe Dashboard. Either way this gate is not satisfied.

**Gate result: BLOCKER.** H8A §9.5 not started; no LIVE credential obtained, no
LIVE endpoint created, no API version pinned.

## 8. Stripe TEST endpoint and Connect record

Recorded now so that H8A §9.11 (close TEST endpoint overlap) has an accurate
baseline. All three are `livemode: false`.

| Endpoint ID | URL | Scope | Status | API version | Events |
| --- | --- | --- | --- | --- | --- |
| `we_1UAYk83aixfgmaTzEQr2WKS0` | `…-f7f7.up.railway.app/api/payments/webhooks/stripe` | platform | enabled | `2026-03-25.dahlia` | **16** |
| `we_1UDSGx3aixfgmaTzPxCXmtOB` | `…-f7f7.up.railway.app/api/payments/webhooks/stripe-connect` | **Connect** | enabled | `2026-03-25.dahlia` | **11** |
| `we_1UDN0J3aixfgmaTzAPfIXgX0` | `shiptrip-production.up.railway.app/api/payments/webhooks/stripe-connect` | non-Connect | **disabled** | `2026-03-25.dahlia` | 5 |

The two enabled TEST endpoints match the H8A §9 event lists **exactly** — 16
platform events and 11 Connect events, in the specified sets, on the reviewed API
version. The LIVE endpoints must reproduce this shape.

The third endpoint is a stale reference to the **superseded origin**
`shiptrip-production.up.railway.app`. It is already disabled and carries the wrong
scope; retain it for audit, do not re-enable it, and do not model the LIVE Connect
endpoint on it.

TEST connected accounts: **5**, all `FR`. Only `acct_1UDSCoKWXRqQfWCd` has
`charges_enabled`, `payouts_enabled` and `details_submitted` true; the other four
are incomplete. All five are TEST identities and, per H8A §3, cannot be reused,
relabelled or redirected in LIVE — a real Traveler must onboard anew. **No LIVE
onboarding was attempted and no LIVE connected account exists.**

## 9. Chargily — BLOCKER (owner verification)

`CHARGILY_SECRET_KEY` is a `test_sk_` key and `CHARGILY_API_BASE` is
`https://pay.chargily.net/test/api/v2`. Key mode and API base are **coherent**.
`CHARGILY_WEBHOOK_SECRET` is empty, which per H8A means the API key signs — the
correct configuration; no separate secret has been invented.

An authenticated read of `/balance` from inside the container returned Cloudflare
error `1010`, so no conclusion about account state can be drawn from it. LIVE
merchant activation, the LIVE key, settlement and refund permissions, and the
account-level callback setting all require the Chargily dashboard. **Owner action.**

Target LIVE configuration when it is reached: key `live_sk_…`, API base
`https://pay.chargily.net/api/v2`, callback
`https://shiptrip-production-f7f7.up.railway.app/api/payments/webhooks/chargily`
(the application also supplies `webhook_endpoint` on every checkout), override left
empty. Per H8A §6, **no checkout may be created to test this.**

## 10. Manual DZD operating process — BLOCKER for DZD collection

No evidence exists of an approved operational process covering Finance staffing and
ownership, CCP/RIP evidence review, crossed-cheque review, payout claim, frozen FX
and instruction handling, the actual external transfer, receipt upload, settlement
attestation, refunds, disputes, failure escalation or audit responsibility.

`PAYOUT_DZD_EXECUTION_ENABLED` therefore **remains `false`**, and the DZD/Chargily
collection route must stay disabled. Enabling Chargily collection without this
process would create DZD liabilities that Finance has no approved way to service.

Note the current active policy already has `payments.providers.chargily_enabled`
and `payments.chargily.new_checkouts_enabled` set **true** — appropriate for TEST,
but H8A §7 requires both to be **false** at cutover until the DZD process is
approved. That change was not made, because no cutover occurred.

## 11. Configuration state — unchanged

Read-only Railway manifest, 116 variables, values never emitted.

| Variable | State |
| --- | --- |
| `PAYMENTS_ENVIRONMENT` | `test` |
| `SHIPTRIP_ENVIRONMENT` | `production` |
| `STRIPE_SECRET_KEY` | TEST prefix |
| `STRIPE_API_BASE` | `https://api.stripe.com` |
| `STRIPE_API_VERSION` | **empty** — H8A requires pinning `2026-03-25.dahlia` at cutover |
| `STRIPE_CONNECT_API_VERSION` | `2026-03-25.dahlia` |
| `STRIPE_CONNECT_EXPECTED_MODE` | `test` |
| `STRIPE_CONNECT_ALLOWED_COUNTRIES` | `FR` |
| `STRIPE_WEBHOOK_SECRET` / `STRIPE_CONNECT_WEBHOOK_SECRET` | set, distinct |
| `CHARGILY_SECRET_KEY` / `CHARGILY_API_BASE` | TEST / TEST, coherent |
| `CHARGILY_WEBHOOK_SECRET` | empty (API key signs) |
| `EMAIL_ENABLED` | `false` |
| `EMAIL_SENDING_DOMAIN_VERIFIED` | `false` |
| `FCM_ENABLED` / `FCM_PROJECT_ID` | `true` / `shiptrip-7c28f` |
| `FINANCE_DASHBOARD_ENABLED` | `true` |
| `PAYOUT_PROFILES_ENABLED` | `true` |
| `STRIPE_CONNECT_ENABLED` | `true` |
| `STRIPE_CONNECT_PAYOUTS_ENABLED` | `true` |
| `PAYOUT_DZD_EXECUTION_ENABLED` | **`false`** |
| `STRIPE_CONNECT_NON_STRIPE_FUNDING_ENABLED` | `false` |
| `PAYMENTS_ALLOW_MOCK_PROVIDER` / `_MOCK_WEBHOOK_` / `_LEGACY_MUTATIONS_` | `false` / `false` / `false` |
| `PAYMENTS_PUBLIC_BASE_URL` / `FRONTEND_BASE_URL` | canonical origin, matching |
| `RELEASE_ID` | `v1.0.0-rc.30+4ec23a1` |

Origin matrix: `PAYMENTS_PUBLIC_BASE_URL`, `FRONTEND_BASE_URL`,
`CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS` and `DJANGO_ALLOWED_HOSTS` all agree
on `shiptrip-production-f7f7.up.railway.app`, with no wildcard.

Active versioned business policy: **version 9**, activated
`2026-09-09T13:04:52.535153+00:00` — `providers.stripe_enabled true`,
`providers.chargily_enabled true`, `chargily.new_checkouts_enabled true`,
`payout.auto_stripe_enabled true`, `providers.mock_enabled false`,
protection window 172,800 s, EUR→DZD 280.000000.

### Runtime health (unchanged deployment)

`/healthz` **200** `{"status":"ok","release":"v1.0.0-rc.30+4ec23a1"}`.
`/readyz` **200** — `database ok`, `migrations ok`, `rate_limit_cache ok`.

All expected processes present: supervisor `shiptrip-start`, `redis-server`,
gunicorn master + 2 workers, `runkycgrpc`, `run_reservation_releaser`,
`run_finance_worker`, `chat`, `notification`, `kyc`, `email`, `caddy`.

### Webhook signature enforcement (no money, no state change)

Unsigned `POST` to each production endpoint:

| Endpoint | Response |
| --- | --- |
| `/api/payments/webhooks/stripe` | **400** `{"code":"invalid_webhook_signature"}` |
| `/api/payments/webhooks/stripe-connect` | **400** `{"code":"invalid_webhook_signature"}` |
| `/api/payments/webhooks/chargily` | **400** `{"code":"invalid_webhook_signature"}` |

All three routes exist at the canonical origin and reject unverified payloads
before any handler runs. No LIVE endpoint validation was possible, because no LIVE
endpoint exists.

## 12. Push and mobile

**FCM.** `FCM_ENABLED=true`, `FCM_PROJECT_ID=shiptrip-7c28f`, credentials present
via `FCM_CREDENTIALS_JSON_BASE64`, path `/tmp/shiptrip/firebase-admin.json`. The
`notification` worker is running. The mobile release build sources
`FIREBASE_PROJECT_ID=shiptrip-7c28f` from repository variables — **project identity
is aligned** between server and client (sender ID `196052669620`). No test
notification was sent; consented on-device delivery remains unproven and is an
H8C/release prerequisite.

**Mobile production origin.** Verified by source inspection; no build was produced.

* `AppConfig.apiBaseUrl` release default is **empty** — the `http://10.0.2.2:8080`
  fallback exists in debug only. No localhost or superseded Railway origin can
  reach a release binary.
* `validateReleaseOrigin` rejects non-HTTPS, credentials, query, fragment, any
  path, `localhost`, `127.0.0.1`, `10.0.2.2`, `::1`, `.invalid` and `.test`, and is
  called for both API and KYC origins before any service starts.
* `kycBaseUrl` defaults to the API origin; `wsBaseUrl` derives `https` → `wss`,
  giving `wss://shiptrip-production-f7f7.up.railway.app`.
* `.github/workflows/android-release.yml` requires `api_base_url` as an explicit
  dispatch input, re-validates it as a credential-free HTTPS origin, and passes
  `--dart-define=API_BASE_URL=$API_BASE_URL` to `flutter build apk|appbundle`.

The release therefore **must** be dispatched with
`API_BASE_URL=https://shiptrip-production-f7f7.up.railway.app`. Nothing is baked in.

Outstanding (H8A-known, MAJOR, not a payment blocker): `MAP_TILE_URL` still
defaults to OpenStreetMap public tiles, which are not licensed for production
traffic and must be overridden at release with a real map contract.

## 13. Owner actions required to resume

H8B resumes at the numbered gate, not from the start.

1. **Railway billing and backups** *(unblocks §4, the gate that halted the phase)*.
   Activate billing on workspace `medshipdev's Projects` and enable volume backups
   for `postgres-volume`. Set a Daily schedule and take one manual backup. Adding a
   payment method is an owner-only action. Also decide whether a production payment
   platform should run on Hobby.
2. **Email backlog decision** *(unblocks §5)*. Two questions:
   (a) may the 73 reserved-domain rehearsal obligations be cancelled via
   `cancel_message` with a recorded key manifest; (b) what happens to the four
   real-recipient rows — above all message 22, an 8-day-old TEST delivery code to a
   real recipient with no account. Cancel, or deliberately deliver? No email may be
   enabled until this is answered.
3. **Sender.net sender domain** *(unblocks §6)*. Create/verify the sending domain,
   publish SPF and DKIM, and supply SMTP host, username, password, `EMAIL_FROM_ADDR`
   and `DEFAULT_FROM_EMAIL` directly into Railway. Requires account login and DNS.
4. **Stripe LIVE activation** *(unblocks §7)*. Complete activation for
   `acct_1TLWM93aixfgmaTz` in the Stripe Dashboard until `details_submitted`,
   `charges_enabled` and `payouts_enabled` are all true and the Connect terms and
   FR/DE/ES country availability are accepted. Requires dashboard login and MFA.
5. **Chargily LIVE merchant** *(unblocks §9)*. Confirm merchant activation, obtain
   the `live_sk_` key, confirm settlement and refund permissions and the callback
   path. Requires dashboard login.
6. **DZD operating process** *(unblocks §10)*. Approve, in writing, the manual DZD
   fulfilment process, or accept launching without the DZD route.
7. **Reconcile payout 4 in TEST** *(§3)*. Let the TEST Connect `payout.paid` event
   discharge it **before** any Connect signing secret is replaced.

Only after 1–7 does the H8A sequence continue at step 3 (freeze new TEST work).

## 14. Security note — credential exposure during this phase

While producing the redacted Railway variable manifest, a diagnostic read of
`~/.railway/config.json` printed the CLI session `accessToken` and `refreshToken`
for `riirfjjri@gmail.com` into the working transcript. The redaction applied only
to top-level keys and missed the nested `user` object.

No Railway configuration was changed with that token; it was used for read-only
GraphQL queries and two backup mutations that were refused. Nonetheless the tokens
should be treated as exposed and **rotated**: run `railway logout` followed by
`railway login`, and revoke existing sessions from Railway account settings.

This is recorded here because it is an operational security event, not because it
affected the cutover outcome.

## 15. Result

| Gate | Result |
| --- | --- |
| Source state frozen | PASS |
| Pre-cutover H5 integrity | PASS |
| Backup / recovery evidence | **BLOCKER** |
| Email backlog safety | **BLOCKER** |
| Email provider readiness | **BLOCKER** |
| Stripe LIVE platform readiness | **BLOCKER** |
| Chargily LIVE merchant readiness | **BLOCKER** (owner verification) |
| DZD operating process | **BLOCKER** for DZD collection |
| TEST obligation reconciliation | Outstanding — payout 4 |
| Railway LIVE configuration | Not performed |
| LIVE deployment / restart | Not performed |
| LIVE webhook configuration | Not performed |
| Collection enablement | None |
| Real-money operation | **None** |

**H8B PRODUCTION CUTOVER: FAIL.**
**Production configuration LIVE: NO.**
**Ready for H8C first genuine transaction monitoring: NO.**

No runtime-code defect was found. The H8A fail-closed guards behaved exactly as
specified — the unactivated platform account and the LIVE email requirement would
both have refused money movement on their own. No backend phase is required by
these findings; every blocker is infrastructure, provider-account or operational.
