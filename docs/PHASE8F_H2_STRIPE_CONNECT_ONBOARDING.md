# Phase 8F-H2 — Stripe Connect TEST account onboarding and readiness

H2 implements the onboarding and readiness layer that
[H0](PHASE8F_H0_PAYOUT_FINANCE_ARCHITECTURE.md) selected, on top of the dormant
domain [H1](PHASE8F_H1_PAYOUT_FOUNDATIONS.md) built. Starting local `main` and
`origin/main` were `2a6aff4fd3c2514023cc324056c5818dd092decd`.

**No money moves in this phase, and no code path exists that could move it.**
There is no Transfer, no bank Payout, no reversal and no cancellation in the
Connect adapter; a test asserts the adapter's own source contains none of those
paths. H3 owns execution.

## What a Traveler can now do

1. Enable the EUR payout preference and declare an eligible **account** country.
2. Have ShipTrip create — or safely reuse — one Stripe connected account.
3. Open Stripe-hosted onboarding through a short-lived Account Link.
4. Complete or resume it, and come back.
5. Have ShipTrip retrieve authoritative account state and re-evaluate readiness.
6. See a safe setup status with no provider payload in it.
7. Have that status refresh automatically from connected-account webhooks.
8. Open the Stripe Express Dashboard to manage their own bank details.

## Provider contract verified against current Stripe documentation

Verified on 8 September 2026 against Stripe's served documentation. H0's
selections are **compatible with the current stable contract**; no redesign was
required.

| H0 decision | Current contract | Result |
|---|---|---|
| Accounts v1 with explicit controller properties | `POST /v1/accounts` accepts `controller[...]`; `type` is documented as deprecated in favour of `controller` | Confirmed |
| `stripe_dashboard.type=express`, `requirement_collection=stripe`, `fees.payer=application`, `losses.payments=application` | Documented as the Express-equivalent mapping; that exact combination is not in the unsupported list | Confirmed |
| Request `transfers` only, never `card_payments` | `capabilities` is required only when `stripe_dashboard.type=none` | Confirmed |
| Stripe-hosted onboarding | `POST /v1/account_links` with `type=account_onboarding`; response is `{url, expires_at}` | Confirmed |
| Express Dashboard access | `POST /v1/accounts/{id}/login_links`, single-use, Express only | Confirmed |
| Application-controlled payout schedule | `settings.payouts.schedule.interval=manual` on Accounts v1 | Confirmed, with a note below |
| Connected-account webhook scope | Connect events carry a top-level `account`; the scope is chosen per endpoint | Confirmed |
| Event names `account.updated`, `capability.updated`, `account.external_account.{created,updated,deleted}` | All present in the current snapshot event list | Confirmed |
| `2026-03-25.dahlia` | A real, stable, released version | Confirmed |

Two things worth recording rather than silently absorbing:

**Payout schedule.** Stripe's *Using manual payouts* guide now leads with the
Balance Settings API (`POST /v1/balance_settings` with a `Stripe-Account`
header) rather than `settings.payouts` on Accounts v1. The same page states
explicitly that an integration already using `settings.payouts` on Accounts v1
may continue to do so. H0 chose Accounts v1, so H2 implements
`POST /v1/accounts/{acct}` with `settings[payouts][schedule][interval]=manual`
and verifies the result with a subsequent retrieve. This is the smallest
correction consistent with H0's intent — none was actually needed — and the
Balance Settings path is the documented migration if H3 or a later phase moves
to Accounts v2.

**Dahlia breaking change touching Connect.** `2026-03-25.dahlia` adds risk
requirements to the Capability object's `requirements` hash. H2 reads capability
*status* from the Account object (`capabilities.transfers`), not the Capabilities
API, so nothing here assumed the old shape. No other Dahlia breaking change
touches `/v1/accounts`, account links, login links, external accounts or the
payout schedule.

## The Connect adapter

`apps/finance/providers/stripe_connect.py` is a new, focused HTTP boundary. It
is deliberately not the Checkout adapter with more methods bolted on.

- It pins its **own** API version (`STRIPE_CONNECT_API_VERSION`, sent as an
  explicit `Stripe-Version` header on every request) so the payout rail and the
  Sender payment rail can never re-version each other. `STRIPE_API_VERSION` for
  Checkout is untouched.
- It captures Stripe's `Request-Id` on every answer and never logs, returns or
  compares the secret key.
- It has a finite timeout on every call, distinguishes 4xx (definite rejection),
  429/5xx (retryable) and 401/403 (configuration fact), and turns a non-JSON or
  non-object body into `ProviderUnavailable` rather than a crash.
- It decides nothing: not earnings, not eligibility, not the Deal lifecycle, not
  FX, not rail routing. Those stay in the Django finance domain.
- Its projection of an Account is a fixed set of booleans, enum-shaped codes,
  Stripe's own requirement *keys*, and opaque provider ids. `requirements.errors`
  is never read: its `reason` field is prose that can quote a submitted value.

Account scope is always the caller's choice. Every H2 operation is
platform-scoped (the connected account is in the path, under the platform's own
credential); `_request` accepts an explicit `Stripe-Account` header for the
connected-scope reads H3 will need.

## Platform identity assertion

Before any Connect mutation the server calls `GET /v1/account` and refuses to
proceed unless the returned account id equals
`STRIPE_CONNECT_PLATFORM_ACCOUNT_ID`. A mismatch raises
`ConnectPlatformMismatch` and nothing is created. Mode comes from the
credential's documented prefix and must equal `STRIPE_CONNECT_EXPECTED_MODE` —
checked at boot, not at the first onboarding.

## Country eligibility

`STRIPE_CONNECT_ALLOWED_COUNTRIES` is the deployment list; `FR, DE, ES` is the
architecture ceiling, enforced at boot and again at request time. The default is
**empty**, and this release ships with **no country validated by a real TEST
onboarding** — see *Owner action required* below.

A country is a Traveler's declared **account/legal** country, never their
nationality. Declaring `DZ` returns a distinct machine code rather than a
generic validation failure:

```json
{
  "code": "payout_country_unsupported",
  "supported_countries": [],
  "alternative": {"currency": "DZD", "rail": "manual"}
}
```

The DZD manual setup path stays open and unchanged. Nothing in the product
suggests a residency the Traveler does not have, and no French account is ever
created for a Traveler who declared Algeria.

## Account creation and idempotency

Creation follows H0's *record intent → commit → provider call → reconcile*
protocol, using H1's `PayoutProviderOperation` with `kind="account_create"`
owned by the method:

- stable idempotency key `acct_create:{platform}:{mode}:{method uuid}:v{n}`;
- an immutable request fingerprint over platform, mode, method, country,
  currency and controller configuration;
- the operation row is written and moved to `committed` **before** the POST;
- a transport failure moves it to `unknown`, never `failed`;
- one active account per traveler/platform/mode is a database constraint.

Recovery from an ambiguous create has exactly two routes and no third:

1. **Inside 23 hours** — replay the byte-identical request under the same
   idempotency key; Stripe returns the original account.
2. **Past that window** — search a single bounded page of accounts created at or
   after the operation's first request, matching the internal method reference
   in metadata. Exactly one match resolves; zero or two do not.

If neither resolves it, the operation stays `unknown` and the request raises
`stripe_account_unresolved`. A fresh `POST /v1/accounts` is never issued because
a retry window expired.

Account metadata carries only opaque internal references
(`shiptrip_method`, `shiptrip_operation`, `shiptrip_env`). No name, no email, no
Deal contents.

## What is stored

Only safe projections on H1's `StripePayoutAccount`: connected account id,
country, mode, transfers capability, payouts-enabled, details-submitted,
requirement/past-due/pending-verification **keys**, requirements deadline,
disabled reason, controller summary, default currency, the eligible EUR bank
destination's `ba_` id and a boolean, payout schedule interval, readiness
timestamp and generation, status and a safe status reason.

Never stored: raw IBAN, the bank-account object, holder name or address, the
Account Link, the login link, the full Stripe Account response, identity or KYC
documents, or any raw provider PII.

H2 added six additive columns to `StripePayoutAccount`
(`status_reason`, `past_due_codes`, `pending_verification_codes`,
`requirements_deadline`, `controller_summary`, `default_currency`) and two to
`PaymentProviderEvent` (`object_type`, `object_id`) plus one index. Migration
`finance/0019_phase8fh2_connect_projections` is purely additive, performs no
network call and rewrites no H1 history.

### One deliberate deviation from H0's data model

H0's `PayoutMethodVersion` note allowed "one verified binding … when an
initially incomplete Stripe setup obtains its first account". H1 implemented
`PayoutMethodVersion` as strictly immutable — the queryset refuses `update()`
and a PostgreSQL trigger refuses a raw one. H1 is the implemented domain
authority, so H2 **always creates a new version** when an account is bound. The
version that recorded only the Traveler's country preference stays readable as
the record of what was consented to and when, which is the property H0 was
protecting.

## Readiness

One evaluator, `payout_accounts.evaluate_readiness`, is the only place readiness
is decided. The API, the mobile projection, the admin console and the webhook
handler all read it.

Evaluated in precedence order:

1. platform ownership, provider mode, account still active;
2. account country inside the allowlist;
3. local Finance holds scoped to the account — these outrank a happy provider;
4. a readiness observation actually exists;
5. controller configuration matches what this platform asked for;
6. default currency is EUR;
7. `requirements.disabled_reason` — rejected/listed/paused is `needs_attention`,
   under review is `pending_review`;
8. `capabilities.transfers` — unrequested, pending, inactive, active;
9. `details_submitted`;
10. past-due then currently-due requirements;
11. an eligible EUR bank external account exists;
12. pending verification;
13. `payouts_enabled`;
14. payout schedule is `manual`.

Mapped onto H1's statuses: `setup_required`, `pending_review`, `ready`,
`needs_attention`, `unavailable`. `details_submitted=true` alone is never
`ready`. `charges_enabled` is not consulted — no card-payment capability is
requested, so it is not an independent gate on being paid.

Raw Stripe requirement payloads never reach Flutter. The projection carries a
status, a safe reason code, a masked account reference, a bank-present boolean,
the supported countries and which actions make sense next.

## Hosted onboarding, return and refresh

`POST /api/payouts/methods/stripe/onboarding` authenticates the Traveler,
validates the flag, the country and the method's ownership, creates or reuses the
account, and returns one short-lived hosted URL. That URL appears in the response
body and nowhere else: not in the audit log, not in application logs, not in a
notification, and never in a database row.

Return and refresh targets are server-owned, configured, and validated at boot to
be HTTPS on the `PAYMENTS_PUBLIC_BASE_URL` origin with no query or fragment. Each
carries a signed, expiring state bound to user, method, account, platform and
mode. Signature validity alone is not authority — `resolve_state_account`
re-checks every binding against current configuration.

- **Return** (`GET /payouts/stripe/return`) does not mark anything ready. It
  retrieves current state from Stripe and re-evaluates readiness, behind a short
  per-account cooldown. A provider outage on the return leg reports the last
  known state rather than a failure.
- **Refresh** (`GET /payouts/stripe/refresh`) deliberately does **not** mint a
  replacement Account Link, which is what Stripe's guidance suggests. Doing so
  would make the signed state a credential for creating Stripe sessions. The page
  sends the Traveler back to the app, where *Resume setup* is an authenticated
  request.
- An invalid, tampered or expired state renders the same neutral page as a valid
  one, so a forwarded or guessed link discloses nothing.

## Express Dashboard

`POST /api/payouts/methods/stripe/dashboard` returns a single-use Express
Dashboard URL to the account's own authenticated owner, so a Traveler changes
their bank details at Stripe and ShipTrip never holds them. The URL is not
persisted, logged, audited, emailed or pushed. An account that has not completed
onboarding is sent to onboarding instead.

## Webhooks

A dedicated endpoint, `POST /api/payments/webhooks/stripe-connect`, with its own
signing secret (`STRIPE_CONNECT_WEBHOOK_SECRET`). The existing
`POST /api/payments/webhooks/stripe` and its secret are unchanged.

| Property | Behaviour |
|---|---|
| Signature | Verified on the raw body, constant-time, `v1` scheme only, with a timestamp tolerance and a body-size cap |
| Secret separation | The platform secret cannot verify a Connect event and the Connect secret cannot verify a platform event |
| Scope | A connected-account event on the platform endpoint is recorded, marked ignored with `connected_account_scope`, answered 200, and never handed to the payment reconciler. A platform-scoped event on the Connect endpoint is classified `platform_scope_event` |
| Mode isolation | `livemode` decides the record's mode; a wrong-mode event is durably classified `mode_isolated`, never applied and never endlessly rejected |
| Durability | The event row commits before the 2xx |
| Idempotency | `(provider, provider_event_id)` uniqueness; a redelivery is a no-op, and a reused id with a different safe payload is failed as a contradiction |
| Event set | `account.updated`, `capability.updated`, `account.external_account.{created,updated,deleted}` act. H3's payout events are accepted and stored as `deferred_to_execution_phase` without acting. Everything else is `event_not_subscribed`. No wildcard subscription |
| Authority | An event means *something changed*. Readiness always comes from a fresh `GET /v1/accounts/{acct}` |
| Out-of-order | The write is guarded on observation time, so a slower older fetch is recorded as `superseded_by_newer_observation` and cannot regress the stored generation |
| Unknown account | Classified `unknown_connected_account`. Nothing outside this server can introduce a connected account into the payout domain |
| Privacy | An `account.external_account.*` payload's holder name, last four, routing number and fingerprint are all dropped; only the object type and id survive |

## Admin visibility

One read-only console page, **Finance → Payout accounts**, gated on
`view_finance_summary` — Finance and Super Admin only; Support and Ops get 403.
It shows Traveler, masked connected-account reference, mode, country, readiness
status and safe reason, transfers capability, payouts-enabled, whether a EUR bank
destination exists, the payout schedule and the last check time. No bank data,
because none is stored. This is not the H5 Finance dashboard.

## Configuration

| Variable | Default | Notes |
|---|---|---|
| `STRIPE_CONNECT_ENABLED` | `false` | Gates account creation and every hosted link |
| `STRIPE_CONNECT_EXPECTED_MODE` | `test` | Must match the Stripe credential's prefix |
| `STRIPE_CONNECT_PLATFORM_ACCOUNT_ID` | empty | Asserted against `GET /v1/account` |
| `STRIPE_CONNECT_API_VERSION` | `2026-03-25.dahlia` | Connect adapter only |
| `STRIPE_CONNECT_WEBHOOK_SECRET` | empty | Connected-accounts endpoint only |
| `STRIPE_CONNECT_ALLOWED_COUNTRIES` | empty | Ceiling `FR,DE,ES` |
| `STRIPE_CONNECT_ONBOARDING_RETURN_URL` | empty | HTTPS on the public base origin |
| `STRIPE_CONNECT_ONBOARDING_REFRESH_URL` | empty | Same, and must differ |
| `STRIPE_CONNECT_STATE_TTL_SECONDS` | `3600` | Signed return-state lifetime |
| `STRIPE_CONNECT_PAYOUTS_ENABLED` | `false` | Production **refuses to boot** if true |
| `STRIPE_CONNECT_NON_STRIPE_FUNDING_ENABLED` | `false` | Production **refuses to boot** if true |

`config/settings/connect.py` holds the validator, called from
`config.settings.prod`. With `STRIPE_CONNECT_ENABLED=false` it asserts only the
country ceiling and the two execution flags, so existing production boots
unchanged and requires no new secret.

The combined-container launcher (`backend/railway/start.py`) now strips
`STRIPE_CONNECT_WEBHOOK_SECRET`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`,
`CHARGILY_SECRET_KEY` and `CHARGILY_WEBHOOK_SECRET` from the chat, notification,
KYC, email and gateway child environments, alongside the payout keys H1 already
stripped. Django's own children keep them. FCM credential-file handling is
untouched.

## Owner action required before external TEST

H2's local implementation and tests are complete and do not depend on any of
this. Nothing below has been performed, and **no real Stripe TEST connected
account was created**.

### 1. Rotate the exposed Stripe TEST secret key — do this first

H0 recorded that the existing Stripe **TEST** secret key was rendered in a tool
transcript during architecture inspection. It must be replaced before any
external Connect mutation. This requires Stripe Dashboard authentication, which
is an owner action.

1. Stripe Dashboard → **Developers → API keys**, with the **Test mode** toggle
   on. Confirm the header says Test mode before touching anything.
2. On the **Secret key** row, choose **Roll key…**, select an immediate
   expiry, and confirm. Copy the new `sk_test_…` value once.
3. Railway → project `shiptripis` → environment `production` → service
   `shiptrip` → **Variables**. Replace the value of **`STRIPE_SECRET_KEY`**
   with the new key. That is the only variable that changes for the rotation.
4. Redeploy the service so the running processes pick it up.

**Do not** touch any live-mode key. **Do not** paste the old or the new key into
this conversation, a commit, a document, or an issue. The only thing that should
come back is "rotated".

Afterwards the rotation can be verified without anyone seeing the key: open a
Sender Stripe TEST checkout in the QA app and confirm the hosted page loads and
the webhook still settles the order. `/api/admin/health/deep` also reports the
Stripe rail's `credential_mode` as `test` for an authenticated operator.

### 2. Stripe Connect TEST platform setup

Stripe Dashboard, Test mode:

- **Connect → Get started / Settings**: activate Connect in test mode and
  complete any platform profile Stripe presents. An empty connected-account list
  does not prove this is done.
- **Settings → Connect → Platform profile**: confirm the marketplace business
  model, and that the **platform** is responsible for Stripe fees and for
  negative balances / payment losses. `controller.losses.payments=application`
  requires acknowledging that responsibility in the Dashboard.
- **Settings → Connect → Onboarding options**: enable Stripe-hosted onboarding,
  enable Stripe's own external-bank-account collection (ShipTrip must never show
  an IBAN form), and set support and business URLs and branding.
- **Countries**: enable **France** first. Do not enable DE or ES yet.
- Confirm the platform account id is `acct_1TLWM93aixfgmaTz` (the value H0
  observed) before putting it in Railway.

### 3. Connected-accounts webhook destination

Only after this branch is deployed, since the route must exist first.

- Stripe Dashboard → **Developers → Webhooks → Add destination**.
- Endpoint URL:
  `https://shiptrip-production.up.railway.app/api/payments/webhooks/stripe-connect`
- **Events from: Connected accounts** (this is the scope, not the default).
- API version: **`2026-03-25.dahlia`**.
- Events, exactly these five: `account.updated`, `capability.updated`,
  `account.external_account.created`, `account.external_account.updated`,
  `account.external_account.deleted`. Do not select "all events".
- Copy the destination's **own** signing secret. It is a different value from
  the existing platform endpoint's secret and must never be reused across the
  two.

Leave the existing platform webhook destination exactly as it is.

### 4. Railway variables

Service `shiptrip`, environment `production`:

| Variable | Value | Secret? |
|---|---|---|
| `STRIPE_SECRET_KEY` | the rotated `sk_test_…` | **Secret** |
| `STRIPE_CONNECT_ENABLED` | `true` | Not secret |
| `STRIPE_CONNECT_EXPECTED_MODE` | `test` | Not secret |
| `STRIPE_CONNECT_PLATFORM_ACCOUNT_ID` | `acct_1TLWM93aixfgmaTz` | Not secret |
| `STRIPE_CONNECT_API_VERSION` | `2026-03-25.dahlia` | Not secret |
| `STRIPE_CONNECT_WEBHOOK_SECRET` | the new `whsec_…` from step 3 | **Secret** |
| `STRIPE_CONNECT_ALLOWED_COUNTRIES` | `FR` | Not secret |
| `STRIPE_CONNECT_ONBOARDING_RETURN_URL` | `https://shiptrip-production.up.railway.app/payouts/stripe/return` | Not secret |
| `STRIPE_CONNECT_ONBOARDING_REFRESH_URL` | `https://shiptrip-production.up.railway.app/payouts/stripe/refresh` | Not secret |
| `PAYOUT_PROFILES_ENABLED` | `true` (TEST only) | Not secret |

Do **not** set `STRIPE_CONNECT_PAYOUTS_ENABLED` or
`STRIPE_CONNECT_NON_STRIPE_FUNDING_ENABLED`; production refuses to boot with
either on. The two secret values must never be pasted back into a report,
conversation or commit — "set" is the whole answer needed.

### 5. What is verified afterwards, and how

Once steps 1–4 are done, the FR TEST run exercises, through ShipTrip's own
backend and with clearly synthetic Stripe test data:

account creation → Account Link → hosted onboarding → return → readiness refresh
→ resume after an expired link → `account.updated` and `capability.updated`
→ `account.external_account.created` → Express Dashboard link.

Evidence recorded safely: masked connected-account reference, platform
assertion, country, mode, readiness progression, transfers capability,
payouts-enabled, bank-present, schedule, event types observed and Stripe request
ids. Never the bank details, the keys, the Account Link, the full Account JSON or
any personal data.

## Countries actually validated

**None.** `STRIPE_CONNECT_ALLOWED_COUNTRIES` ships empty, and no country is
claimed as working. FR is the first to prove, and DE/ES are not enabled merely
because Stripe's documentation lists them.

## Remaining H3 gates

H3 may not create a Transfer or a bank Payout until all of these hold:

1. FR TEST onboarding is proven end to end against this implementation.
2. The exposed TEST key is rotated and the connected-accounts webhook
   destination is registered and observed delivering.
3. Source allocation and reservation accounting exist, bounded by refunds and
   by other allocations on the same source.
4. The dispatch-commitment protocol exists: a guarded transition to
   `dispatch_committed` immediately before provider I/O, with unknown-result
   recovery that never re-POSTs after an expired replay window.
5. Provider dispute and refund holds are ingested and freeze dispatch.
6. Bank-failure and late-return reconciliation exists, and a failed bank payout
   never re-creates the platform Transfer.
7. Payout minimums and same-account accumulation are modelled.
8. Fault-injection and two-process PostgreSQL race tests pass.
9. `STRIPE_CONNECT_PAYOUTS_ENABLED` is explicitly authorised, and the boot-time
   refusal in `config/settings/connect.py` is deliberately relaxed as part of
   that phase.
