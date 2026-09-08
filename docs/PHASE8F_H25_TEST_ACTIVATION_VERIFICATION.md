# Phase 8F-H2.5 — TEST activation and verification

8 September 2026. **H2.5 FAIL. H3 prerequisites: NO.** H3 was not started.

The authorized setup and independent payment checks completed, but Stripe
refuses to create the first connected account until the sandbox signs up for
Connect. No readiness or delivery success is inferred from configuration or
local tests. No application code or schema fix was required or made.

## Release and configuration

- Starting and deployed application SHA:
  `5af0850f633c9a05d3f55205e95d405983da31b2`.
- Release: `v1.0.0-rc.13+5af0850`.
- Starting deployment: `a9325031-675a-4112-89ac-08cbf86e98df`.
- Activation deployment: `876827a0-836f-4ed9-9285-8bbdef2c45e5`, observed SUCCESS.
- Final restart deployment: `28b32d94-c761-4192-8721-36e08a75aaad`, observed SUCCESS.
- Existing project `shiptripis`, environment `production`, service `shiptrip`.
  No service or environment was created.
- H1/H2 migrations applied; migration executor reports zero pending migrations.
- `/healthz` and `/readyz`: HTTP 200 with the stated release, including after restart.
- Deep health: HTTP 200; database, Redis, storage and push worker healthy;
  no failed or retryable provider events. A finance worker process is running.
- Current rotated Stripe TEST key authenticated successfully. The completed
  Checkout further proves it works. No key was rotated during this run; the
  preceding rotation is supplied context, not an independently observed action.
- Authoritative platform: `acct_1TLWM93aixfgmaTz`, FR, default currency EUR.
- CLI was reauthorized and explicitly switched from the parent account to
  `ship-trip sandbox`, `acct_1TLWM93aixfgmaTz`, mode `test`. No parent-account
  mutation or LIVE mutation was performed.

| Variable | Verified installed state |
|---|---|
| STRIPE_CONNECT_ENABLED | true |
| PAYOUT_PROFILES_ENABLED | true |
| STRIPE_CONNECT_EXPECTED_MODE | test |
| STRIPE_CONNECT_PLATFORM_ACCOUNT_ID | acct_1TLWM93aixfgmaTz |
| STRIPE_CONNECT_API_VERSION | 2026-03-25.dahlia |
| STRIPE_CONNECT_ALLOWED_COUNTRIES | FR only |
| STRIPE_CONNECT_PAYOUTS_ENABLED | false |
| STRIPE_CONNECT_NON_STRIPE_FUNDING_ENABLED | false |
| PAYOUT_DZD_EXECUTION_ENABLED | false |
| FINANCE_DASHBOARD_ENABLED | false |
| EMAIL_ENABLED | false |

Return URL: `https://shiptrip-production.up.railway.app/payouts/stripe/return`.
Refresh URL: `https://shiptrip-production.up.railway.app/payouts/stripe/refresh`.
DE, ES and DZ were not enabled.

`PAYOUT_DATA_KEYRING`, `PAYOUT_DATA_ACTIVE_KEY_ID` and
`PAYOUT_ACCOUNT_FINGERPRINT_KEY` were generated and installed directly through
Railway stdin, with output captured. Active key ID is `k1`: a random 32-byte
AES key and a separate random 32-byte fingerprint key. Values were read back
and compared without displaying them. Django boots, validates the keyring and
passes an authenticated encryption round-trip. Ciphertext for a synthetic probe
created before restart still decrypts after restart. No secret values belong in
this report, repository or transcript.

## Webhooks

Created TEST destination `we_1UDN0J3aixfgmaTzAPfIXgX0` at
`https://shiptrip-production.up.railway.app/api/payments/webhooks/stripe-connect`,
using `connect=true` (Connected accounts scope), API version
`2026-03-25.dahlia`, and exactly:

- `account.updated`
- `capability.updated`
- `account.external_account.created`
- `account.external_account.updated`
- `account.external_account.deleted`

Read-back confirms enabled, TEST, the URL, API version and exact event list.
Its newly returned signing secret was transferred directly to Railway and
verified distinct from the existing platform secret. The existing platform
destination `we_1UAYk83aixfgmaTzEQr2WKS0` and its five events were not changed.

**Legitimate connected-account delivery is NOT verified.** There is no connected
account to generate such an event. Connect duplicate delivery, bank-payload
scrubbing against an actual provider event and Stripe-reported delivery success
remain blocked. Invalid signatures return 400 on both endpoints without adding
event rows. Missing state returns 400 on both hosted callback routes; this is
negative validation, not a successful onboarding return or resume.

## Synthetic Travelers and Connect blocker

FR QA Traveler: user `14`, display name `SYNTHETIC QA H25 FR Traveler`.
Second/DZ QA Traveler: user `15`, display name
`SYNTHETIC QA H25 DZ Traveler`. Both were registered through the actual public
signup API with synthetic example.invalid identities. No real user's financial
identity was used. Passwords and JWTs were generated/used in memory, not printed.

User 14's EUR/FR preference succeeded through the authenticated API (200).
Onboarding through ShipTrip returned 502, with the safe provider-error contract.
The creation operation `1` persisted as `account_create/failed`, and retries used
that same operation. Source inspection confirms committed local intent precedes
the provider call. Stripe's exact diagnostic rejection is:

> You can only create new accounts if you've signed up for Connect, which you can do at https://dashboard.stripe.com/connect.

This rejection was reproduced through ShipTrip's account-creation service.
Authoritative Stripe account listing returns zero accounts and `has_more=false`;
the local account count is also zero. The available Stripe CLI tools expose
branding operations but no Connect signup/activation operation. CLI authorization
does not itself activate Connect. Browser attempts could not supply an
authenticated controllable Dashboard session; later user direction restricted
continuation to CLI/backend checks. No alternative sandbox was created.

Consequently, there is **no connected-account reference** and no provider proof
of country/mode/controller, requested capabilities, immutable bound destination,
hosted Account Link, successful return/resume, readiness, payouts-enabled,
requirements, EUR external bank, manual schedule or Express Dashboard access.
The implemented contract requests Express, Stripe requirement collection,
application-paid fees/losses, transfers only and EUR; those remain source/test
evidence, not a successfully created provider object's properties.

DZ preference returns 400 `payout_country_unsupported`, supported countries
`[FR]`, alternative `{currency: DZD, rail: manual}`. A direct onboarding call
without an enabled preference returns generic setup-invalid 400. No second-user
provider operation or account was created. Account-ID/Traveler-ID injection
attempts from user 15 were refused (400); unauthenticated onboarding, refresh and
dashboard requests returned 401. **Cross-user access against an actual first
connected account remains untested**, because that account does not exist.

## Sender Checkout and duplicate durability

Used the existing controlled EUR 3 posting-deposit order `7`, QA Sender `13`,
Stripe attempt `12`. Confirmed the provider session was open, TEST, EUR 300 cents
and Adaptive Pricing disabled before completing exactly one hosted TEST card
payment. Authoritative final Checkout: `complete`, `paid`, EUR 300 cents,
`livemode=false`, Adaptive Pricing disabled, no currency conversion.

Platform event `evt_1UDN8W3aixfgmaTz5F9SOKbZ`, type
`checkout.session.completed`, was received naturally and stored as
`signature_verified=true`, `endpoint_scope=platform`, `provider_mode=test`,
`processing_result=applied`. Order `7` is paid EUR 300 cents; attempt `12` is
succeeded, TEST, EUR, and not unapplied. Two ledger entries sum to zero.

Retrieved the legitimate event from Stripe and replayed its body twice with a
fresh valid platform signature. Both returned 200 `duplicate=true`. Counts
remained one event and two ledger entries, and the paid total remained 300 cents.
Repeated those checks after restart with the same unchanged results. These are
locally signed replays of a real event, not claimed Stripe Dashboard redeliveries.

## Privacy, operational checks and retained history

The real deployed Finance payout-account view returned 200 for Finance and 403
for Support and Ops. Temporary synthetic role identities and sessions used in
this check were rolled back together. The view was empty; visibility of a
populated masked account row remains unverified. No secret/bank/link field
markers appeared in the checked responses.

Inspected running process environments by variable name only: chat,
notification, KYC and email Go services inherited none of the checked payment or
payout secrets. Django web and finance workers retain their required secrets.
The gateway environment was not readable in that inspection; the focused
launcher test covers its filtering, but runtime inspection is not claimed.

Restart preserved the failed account intent, payment settlement/event uniqueness
and encryption configuration. **Post-account-creation binding/readiness
durability remains blocked**, because no account exists.

Deep health reports 31 historical failed jobs: 28 `email_disabled` outbound jobs
and three `provider_session_unknown` reconciliation jobs. The newest was created
5 September, before this run. They were preserved rather than redriven or
discarded outside scope. Synthetic signup email obligations remain queued with
email disabled. Financial audit history and the two synthetic Travelers remain
for a later authorized continuation.

A dedicated local SSH key was generated and registered as `shiptrip-h25-qa` to
use authenticated Railway SSH. Its private value was not printed or committed.
Stripe CLI's tools plugin was installed to inspect non-public-operation
availability. Browser remote debugging was enabled during the unsuccessful
Dashboard-access attempt; browser changes were subsequently stopped at the
user's request. It is not claimed to have been disabled afterward.

## Tests and verdict

Focused H2 adapter, account, webhook and deployment tests:
**187 passed**, using `--ds=config.settings.test_local` on SQLite. Initial test
collection without the settings argument failed; the corrected invocation passed.
Warnings were existing Django deprecation/static-directory warnings. No
application code or migration changed, so no code-fix CI/merge/deploy is claimed.

- BLOCKER: sandbox Connect signup incomplete; account creation rejected.
- BLOCKER: connected-account hosted onboarding/readiness, legitimate Connect
  event delivery, populated admin view and actual-account ownership/durability
  gates cannot be completed without that signup.
- MAJOR operational finding, predating H2.5: three failed provider reconciliation
  jobs require separately scoped review; their financial effect was not diagnosed.
- MINOR: gateway runtime environment could not be inspected; test evidence only.
- No Stripe Transfer or connected-account bank Payout was created; their API
  endpoints, reversal and cancellation endpoints were not called.
- Existing EUR 60 QA payout `1` remains `blocked`, with no paid timestamp or
  provider payout reference.
- No Chargily money operation, LIVE money operation or email send was performed.
- No secret keys, private keys, signing secrets or hosted access URLs were printed
  or committed. The CLI pairing code was supplied solely for user authorization;
  Stripe's published synthetic card data was used for the TEST Checkout.

**H2.5 FAIL. Are H3 prerequisites now satisfied? NO.**
