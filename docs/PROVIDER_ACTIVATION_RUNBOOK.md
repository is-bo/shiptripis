# Provider Activation Runbook

This runbook is deliberately unexecuted. It contains placeholders only; never paste secrets into source, tickets, chat, logs, screenshots, or command history. Complete activation in a controlled test environment first, then obtain a separate production approval.

Use `https://<PUBLIC-API-ORIGIN>` below as the value of `PAYMENTS_PUBLIC_BASE_URL`. Exact webhook endpoints from the current URL configuration are:

- Stripe (platform / **Your account** scope): `https://<PUBLIC-API-ORIGIN>/api/payments/webhooks/stripe`
- Stripe Connect (**Connected accounts** scope): `https://<PUBLIC-API-ORIGIN>/api/payments/webhooks/stripe-connect`
- Chargily: `https://<PUBLIC-API-ORIGIN>/api/payments/webhooks/chargily`

The two Stripe endpoints are separate destinations with separate scopes and
**separate signing secrets**. Neither secret may be reused for the other: the
platform endpoint refuses a connected-account event and the Connect endpoint
refuses a platform one, and that separation is only meaningful if a compromise
of either secret cannot verify the other's traffic.

The endpoints are unauthenticated only at the HTTP layer. They verify the raw request body signature before database processing, record a unique `(provider, provider_event_id)`, scrub stored payloads, safely redrive incomplete duplicates, and return no order/customer details. Do not place a general authentication proxy in front of them.

## Shared preconditions

- [ ] Deployment and restore rehearsal are green; `/healthz`, `/readyz`, and deep health are green.
- [ ] `PAYMENTS_ALLOW_MOCK_PROVIDER=false`, `PAYMENTS_MOCK_WEBHOOK_ENABLED=false`, and `PAYMENTS_LEGACY_MUTATIONS_ENABLED=false`.
- [ ] Public API origin, TLS, allowed hosts, and callback URLs are final.
- [ ] A Finance Admin and Super Admin are available; all changes go through an audited `BusinessSettingsVersion`.
- [ ] Reconciliation worker and alerting for retryable/failed provider events are running.
- [ ] Test identities/orders contain no real customer or recipient data.

## Stripe

Environment placeholders:

```text
STRIPE_SECRET_KEY=<secret-manager reference>
STRIPE_WEBHOOK_SECRET=<secret-manager reference>
STRIPE_API_BASE=https://api.stripe.com
STRIPE_API_VERSION=<reviewed pinned version or intentionally blank>
STRIPE_WEBHOOK_TOLERANCE_SECONDS=300
```

The current backend does not consume a Stripe publishable key; checkout is provider-hosted. Do not invent or expose one unless a future client implementation actually uses it. Connected-account IDs are stored per traveler payout method, not as a global environment variable.

Configure these webhook events:

- `checkout.session.completed`
- `checkout.session.async_payment_succeeded`
- `checkout.session.async_payment_failed`
- `checkout.session.expired`
- `payment_intent.payment_failed`

Activation sequence:

1. In Stripe test mode, create an endpoint at the exact URL and store its signing secret in the environment secret store.
2. Set both Stripe secret variables in one deployment. A half-configured pair is rejected at boot.
3. Keep Stripe disabled in the active business settings. Verify readiness and provider-health reports credentials present but disabled.
4. Create a draft business-settings version enabling Stripe; record approver, effective time, and rollback version. Activate only after the deployment is healthy.
5. Run a normal EUR checkout and verify processing then success, one captured attempt, one balanced ledger transaction, funded Deal state, and no duplicate notification.
6. Run a hosted guest-payer checkout. Confirm the guest sees only amount/currency/generic purpose and gains no Deal/chat/address authority.
7. Replay the identical signed event at least twice. Verify one provider-event economic identity, a duplicate response, and no second capture/ledger/deal transition.
8. Exercise a delayed/processing checkout followed by `async_payment_succeeded`; also exercise `async_payment_failed` and expiry.
9. Issue a partial and full refund through the granular admin route. Verify stable idempotency, provider reconciliation, ledger correction, order totals, audit log, and duplicate retry safety.
10. Verify a provider timeout/unavailability refuses checkout without mock fallback and creates observable recovery work where appropriate.
11. Confirm payout capability is based on Stripe’s reported connected-account capability; no country heuristic may release money.
12. Review logs for request/provider references only—no secret, token, card, payer email, or webhook body leakage.

Rollback switch: activate a new audited settings version with Stripe disabled for **new** checkout. Do not remove the webhook secret or route while attempts/refunds are in flight; reconciliation must continue.

## Stripe Connect — Traveler payout accounts (Phase 8F-H2)

A separate capability from Sender Checkout above. It creates connected accounts
and reads their readiness; it moves no money, and H3 owns execution. Do not
convert Sender Checkout into direct or destination charges to serve it.

Environment placeholders:

```text
STRIPE_CONNECT_ENABLED=<false until the steps below pass>
STRIPE_CONNECT_EXPECTED_MODE=test
STRIPE_CONNECT_PLATFORM_ACCOUNT_ID=<the platform's own acct_ id>
STRIPE_CONNECT_API_VERSION=2026-03-25.dahlia
STRIPE_CONNECT_WEBHOOK_SECRET=<secret-manager reference, distinct from STRIPE_WEBHOOK_SECRET>
STRIPE_CONNECT_ALLOWED_COUNTRIES=<empty, then FR once FR is proven>
STRIPE_CONNECT_ONBOARDING_RETURN_URL=https://<PUBLIC-API-ORIGIN>/payouts/stripe/return
STRIPE_CONNECT_ONBOARDING_REFRESH_URL=https://<PUBLIC-API-ORIGIN>/payouts/stripe/refresh
```

`STRIPE_CONNECT_PAYOUTS_ENABLED` and `STRIPE_CONNECT_NON_STRIPE_FUNDING_ENABLED`
must stay false. Production refuses to boot with either on, because neither the
execution path nor the funding approval they describe exists.

Configure exactly these events, with **Events from: Connected accounts**:

- `account.updated`
- `capability.updated`
- `account.external_account.created`
- `account.external_account.updated`
- `account.external_account.deleted`

No wildcard subscription. Payout-execution events (`payout.*`) are already
ingested and stored without acting, so they may be added when H3 lands rather
than needing a second destination.

Activation sequence:

1. Rotate any Stripe TEST secret key that has been exposed, and install the
   replacement, before creating a single Connect object.
2. Activate Connect in Stripe test mode and complete the platform profile:
   marketplace model, platform pays Stripe fees, platform responsible for
   negative balances, Stripe-hosted requirement collection, Express Dashboard.
   An empty connected-account list does not prove this is done.
3. Enable Stripe-hosted onboarding with Stripe's own bank-account collection.
   ShipTrip must never render an IBAN form.
4. Deploy the route, then register the connected-accounts destination at the
   exact URL above with API version `2026-03-25.dahlia`, and store its own
   signing secret.
5. Set the variables above with `STRIPE_CONNECT_ALLOWED_COUNTRIES` empty, and
   confirm the service boots. A missing secret, a mode that disagrees with the
   credential's prefix, or a return URL off the public origin is a boot refusal.
6. Enable France only. Run one synthetic Traveler through account creation,
   Account Link, hosted onboarding, return, readiness refresh, resume after an
   expired link, and the Express Dashboard link.
7. Verify the retrieved account reports the expected controller hash,
   `capabilities.transfers`, `payouts_enabled`, an eligible EUR bank destination
   and `settings.payouts.schedule.interval=manual`.
8. Verify each of the five events arrives and refreshes readiness, that a
   redelivery is a no-op, and that a live-mode event against a test deployment
   is classified rather than applied.
9. Confirm a Traveler declaring Algeria is refused with
   `payout_country_unsupported` and offered the DZD rail, and that no French
   account was created for them.
10. Review logs and the audit trail: no Account Link, no login link, no bank
    holder name, no last four, no routing number, no secret.

Only after all ten may DE or ES be considered, one validated country at a time.

Rollback switch: set `STRIPE_CONNECT_ENABLED=false`. Onboarding stops; the
webhook route and its secret stay in place so readiness for existing accounts
keeps reconciling.

## Chargily

Environment placeholders:

```text
CHARGILY_SECRET_KEY=<secret-manager reference>
CHARGILY_WEBHOOK_SECRET=<optional independent secret; otherwise API secret signs>
CHARGILY_API_BASE=https://pay.chargily.net/test/api/v2   # test only
```

The current adapter uses a secret API key; it has no source-consumed public-key variable. Its supported events are `checkout.paid`, `checkout.failed`, `checkout.canceled`/`checkout.cancelled`, and `checkout.expired`.

**The key and the base URL must name the same environment.** `test_sk_` pairs only with `https://pay.chargily.net/test/api/v2`, and `live_sk_` only with `https://pay.chargily.net/api/v2`. Setting one without the other is the single most likely activation mistake — it is two variables, and only one of them is a secret, so they get changed at different times by different people.

A deployment that mixes them is reported as *Credential environment could not be identified*, is refused for new checkouts with `provider_configuration_invalid`, and shows in the app as **Not ready yet**. Repairing it means correcting whichever half is wrong; never rotate or replace the secret key to resolve a mismatch, because the key is usually the half that was right.

Activation sequence:

1. Configure the exact test webhook URL. Verify the provider sends the `signature` HMAC header over the raw body.
2. Add the test secret and test API base to the environment, deploy, and leave Chargily disabled in business settings.
3. Create a draft settings version that enables Chargily and sets the server-controlled EUR→DZD rate. Record rate source, timestamp, approver, and effective version.
4. Activate the version, create a checkout, and confirm the canonical order remains EUR while the attempt snapshots DZD amount and `fx_rate_micros`.
5. Complete paid, failed, cancelled, and expired test flows. Verify amount/currency/reference checks and duplicate-event idempotency.
6. Change the active FX rate, then redrive the old event. Confirm the historical attempt retains the original snapshot and ledger remains in canonical EUR.
7. Simulate a late `checkout.paid` after local expiry. Confirm recovery reconciles money safely without overcollection and raises manual review where the order can no longer accept it.
8. Verify manual refund workflow: Chargily has no programmatic refund API in the adapter. A Finance Admin records the bank/reference settlement through the granular audited route; the reference is mandatory and duplicate settlement is refused.
9. Verify provider polling/recovery and operator alert behavior with the API temporarily unavailable.
10. Replace the test base/key with reviewed live values only under a separate production change approval; repeat a low-value controlled checkout.

Rollback switch: disable Chargily for new checkouts via a new settings version. Keep credentials/webhook processing available for in-flight payments and manual refunds.

## Sender.net

Environment placeholders:

```text
EMAIL_ENABLED=true
EMAIL_PROVIDER=sender_net
EMAIL_SMTP_HOST=<Sender.net supplied SMTP host>
EMAIL_SMTP_PORT=587
EMAIL_USE_TLS=true
EMAIL_SMTP_USERNAME=<secret-manager reference>
EMAIL_SMTP_PASSWORD=<secret-manager reference>
EMAIL_FROM_ADDR=noreply@<verified-domain>
EMAIL_FROM_NAME=ShipTrip
DEFAULT_FROM_EMAIL=ShipTrip <noreply@<verified-domain>>
EMAIL_SUPPORT_ADDR=support@<verified-domain>
FRONTEND_BASE_URL=https://<PUBLIC-WEB-ORIGIN>
TRANSACTIONAL_EMAIL_SECRET=<dedicated 32+-character secret>
EMAIL_SENDING_DOMAIN_VERIFIED=true
```

Activation sequence:

1. Verify the exact sending domain and From address in Sender.net.
2. Publish and validate SPF and DKIM records. Publish a DMARC record in monitoring mode first, assign a monitored aggregate-report mailbox, then tighten policy only after reviewing legitimate traffic.
3. Store credentials in the deployment secret store. Never use a personal mailbox password.
4. With `EMAIL_ENABLED=false`, deploy the configuration except credentials flag and confirm the durable outbox remains visible and no external mail is sent.
5. Add credentials/domain-verification flag and enable email in one approved deployment. Production rejects an enabled, unverified or incomplete configuration.
6. Send a non-secret transactional test to controlled EN/FR/AR mailboxes; verify subject/body, links, From/Reply handling, SPF/DKIM/DMARC results, delivery, bounce visibility, and no PII in provider metadata.
7. Test email verification, password reset, and admin invitation. Confirm plaintext capabilities never enter Redis/logs and are invalid after use/expiry.
8. Fund a controlled Deal and test the recipient delivery-code email after the 30-minute buffer. Confirm the traveler cannot retrieve it, the message is backed by `OutboundMessage`/`ScheduledJob`, and retries do not issue a second code.
9. Stop Redis and repeat a durable test. Confirm obligations persist in PostgreSQL and deliver after recovery.
10. Define bounce/complaint suppression, incident ownership, daily sending limits, and domain-reputation monitoring before general launch.

Rollback switch: set `EMAIL_ENABLED=false`. Do not delete durable outbox rows or the transactional encryption secret while secret-bearing messages remain pending; investigate and replay after recovery.

## Activation evidence

Attach to the release ticket: provider dashboard configuration screenshots with secrets redacted, event list, test order/attempt/provider-event/refund identifiers, audit-log records, duplicate-event evidence, reconciliation/deep-health output, email authentication results, approver names, activation settings version, and rollback settings version.
