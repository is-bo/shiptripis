# Phase 8F-H2.6 — Traveler onboarding cleanup and business-profile prefill

## The problem

During Stripe-hosted payout onboarding, Traveler 14 was asked for a **business
website**. There is no truthful answer. A ShipTrip Traveler is an individual who
carries parcels for other people's deliveries and gets paid afterwards. They are
not a merchant, they do not sell anything, and they do not have a website.

The question was not a ShipTrip screen and not a Stripe bug. It was a real
Stripe requirement that ShipTrip had left for the Traveler to answer.

## What Stripe actually required, and why

Verified directly against the TEST platform `acct_1TLWM93aixfgmaTz`, not
inferred from documentation. A probe connected account was created with byte-
identical parameters to ShipTrip's own adapter — FR, EUR, `business_type=
individual`, `capabilities[transfers][requested]=true`, Express dashboard,
`requirement_collection=stripe`, `card_payments` unrequested.

Its `requirements.currently_due` came back as:

```
business_profile.url
external_account
individual.address.city, individual.address.line1, individual.address.postal_code
individual.dob.day, individual.dob.month, individual.dob.year
individual.first_name, individual.last_name
tos_acceptance.date, tos_acceptance.ip
```

That is exactly the list H2.5 recorded for Traveler 14 before hosted onboarding,
so the reproduction is faithful.

Two things in it are worth naming precisely:

* **`business_profile.url` was genuinely required.** It is not optional decor
  and ShipTrip cannot make Stripe stop caring about it. It is the field behind
  the website question.
* **`business_profile.mcc` was *not* required.** A separate pre-existing account
  on the same platform that requested `card_payments` *does* have
  `business_profile.mcc` in `currently_due`. The merchant-category question
  belongs to card acceptance, which ShipTrip never requests. Nothing needed to
  change there, and nothing did.

There was never a "business description" requirement as such. Stripe's hosted
form reaches `product_description` only as the fallback branch of the website
question — answer "no website" and it asks what service you provide instead.

## The documented remedy

Stripe's own hosted-onboarding guide states it plainly:

> If you onboard an account and your platform provides it with a URL, prefill
> the account's `business_profile.url`. If the business doesn't have a URL, you
> can prefill its `business_profile.product_description` instead.

And the API reference defines the two fields so that only one of them can
honestly be used here:

* `business_profile.url` — "The business's publicly available website."
* `business_profile.product_description` — "Internal-only description of the
  product sold by, or service provided by, the business. Used by Stripe for risk
  and underwriting purposes."

`url` means *the account holder's* website. A Traveler has none, and ShipTrip's
own marketing site is not theirs to claim. `product_description` is risk copy
that the platform is expected to supply on the account's behalf. Stripe calls it
"internal-only", meaning it is never shown to end customers — but the Traveler
does see it, pre-filled and editable, in hosted onboarding's Business details
step.

## Proven, not assumed

On the probe account, setting `business_profile.product_description` and nothing
else removed `business_profile.url` from `currently_due`, `past_due` and
`eventually_due`. A second probe created *with* the description in the creation
call never had `business_profile.url` in its requirements at all. No URL was
sent in either case, and `business_profile.url` remained `null` throughout.

## Prefill is a creation-time decision or it is nothing

One further provider fact decided the shape of the change. For an account where
`controller.requirement_collection` is `stripe`, once the first Account Link
exists:

* writes to `business_profile.product_description` return `200` and are silently
  discarded — no error, no effect;
* the field disappears from the retrieved Account object entirely.

Stripe documents the first half of this ("Prefill any account information before
generating the Account Link"). The silent-discard behaviour was confirmed on the
probe. It also explains an oddity in Traveler 14's readback: their
`business_profile` has no `product_description` key at all, because their account
has long since had an Account Link.

The consequence is that a later "provision the business profile" step would be
dead code for every account that has ever started onboarding, so the description
is sent in the `POST /v1/accounts` body and nowhere else.

## What changed

Two files, 88 added lines, no migration, no new endpoint, no new setting.

`apps/finance/providers/stripe_connect.py`

* `create_account` accepts `product_description` and sends it as
  `business_profile[product_description]`.
* `_business_description` normalises whitespace and refuses anything that is not
  short plain text. It refuses rather than truncating, because a silently
  shortened sentence is a different assertion to Stripe than the reviewed one.
* There is **no `url` parameter anywhere in the module**, and a test asserts the
  string `business_profile[url]` does not appear in its source. A field that
  cannot be passed cannot be faked or injected.
* No MCC is sent, because Stripe does not ask for one in this configuration.

`apps/finance/payout_accounts.py`

* `TRAVELER_PRODUCT_DESCRIPTION` — the sentence itself, a module constant in the
  finance domain. The adapter still decides nothing.
* It is passed on the one `create_account` call site, which is also the
  idempotent replay path, so a replay stays byte-identical.
* It is part of `_creation_identity`'s request fingerprint. Changing the sentence
  changes the fingerprint, which is correct: a different assertion to Stripe is a
  different request, and the existing conflict guard should say so rather than
  replay an old key against new words.

### The sentence sent to Stripe

```
Independent traveler providing parcel transportation services through the
ShipTrip marketplace and receiving compensation after completed deliveries.
```

Every clause is something ShipTrip can assert from its own records. It does not
call the Traveler a retailer, a merchant, a logistics company, a card-payment
business, or an owner of ShipTrip. The Traveler sees it pre-filled in Stripe's
Business details step and can correct it, so it has to read plainly to them as
well as usefully to Stripe's underwriting.

## What did not change

* `business_type` stays `individual`.
* `transfers` stays requested; `card_payments` stays unrequested.
* The controller hash, country allowlist, EUR default currency and manual payout
  schedule are untouched.
* `evaluate_readiness` is byte-for-byte unchanged. Prefilling a business profile
  is not evidence that money can move, and readiness still requires transfers
  active, payouts enabled, requirements clear, an eligible EUR bank, the manual
  schedule, the expected controller and the right mode and country.
* No business-profile value is persisted, projected, logged or audited.
  `ConnectedAccountSnapshot` still carries no business-profile field.
* Traveler 14's account is not recreated, reset or rewritten — and, per the
  provider constraint above, could not be even if it were desirable.

## ShipTrip's own copy

Audited and already correct. The hosted-return page, the API and the mobile
strings contain no "create your business", "register your company", "set up your
store" or "start accepting payments" language anywhere. Mobile has no Stripe
onboarding entry point at all, which is the separately tracked H2.5 product gap.
No copy change was needed and none was made.

## Where the boundary sits

| ShipTrip controls | Stripe controls |
|---|---|
| Which capabilities are requested | Which requirements those capabilities create |
| Account data prefilled before the first Account Link | The compliance questions themselves |
| ShipTrip screen and return-page copy | Every label and sentence inside hosted onboarding |
| Account Link creation and collection options | Regulatory rules for a French individual |

Removing the website question is a data change, not a wording change. The
questions Stripe still asks — legal name, date of birth, address, terms
acceptance, bank details, and an identity document eventually — are genuine
French regulatory requirements, and no attempt was made to route around them
with a custom form.

## Verified on the deployed release

`v1.0.0-rc.15+e00c6b7`, deployment `21b0fbb0-6bb9-43f7-88b0-c929d5d1516b`,
SUCCESS. `/healthz` and `/readyz` 200, migrations `ok`.

A fresh synthetic FR Traveler (user `37`) was created through the real ShipTrip
API — sign-up, EUR/FR payout preference, then `POST
/api/payouts/methods/stripe/onboarding`. No account was created by hand in the
Stripe Dashboard. Its connected account's `requirements` came back as:

```
external_account
individual.address.city, individual.address.line1, individual.address.postal_code
individual.dob.day, individual.dob.month, individual.dob.year
individual.first_name, individual.last_name
tos_acceptance.date, tos_acceptance.ip
```

`business_profile.url` is absent from `currently_due`, `eventually_due` and
`past_due`. Everything else is identical to Traveler 14's recorded list.

### Before and after

| Question | Traveler 14 (before) | Traveler 37 (after) |
|---|---|---|
| Business website | Asked — `business_profile.url` required | **Not asked** — requirement absent |
| What service do you provide | Asked, as the fallback branch of the website question | Asked, but **pre-filled** — one field to confirm |
| Business type | Not asked (already `individual`) | Not asked |
| Merchant category (MCC) | Not asked | Not asked |
| Legal name, DOB, address | Asked | Asked — unchanged, French regulatory requirement |
| Terms acceptance, bank details | Asked | Asked — unchanged |

The hosted TEST flow was opened and inspected rather than inferred. Its step list
is Business type (already satisfied), Personal details, Business details, Bank
details. The **Business details step contains exactly one field — "Product
description" — pre-filled with ShipTrip's sentence, followed by Continue. There
is no website field anywhere in the step.** Stripe's own phone-verification test
affordances were used; no CAPTCHA was solved or bypassed, no identity or bank
data was entered, and onboarding was deliberately left incomplete, so no
readiness result is claimed for the fresh account beyond the evaluator's
authoritative `setup_required` / `transfers_inactive`.

### Regression

* Traveler 14 unchanged: readiness `ready`, transfers active, payouts enabled,
  EUR bank present, manual schedule, requirements empty. Not recreated, reset or
  rewritten.
* Fresh account: `business_type=individual`, `capabilities={"transfers":
  "inactive"}` with `card_payments` absent, expected controller, FR/EUR, manual
  payout schedule provisioned. Local readiness `setup_required` /
  `transfers_inactive` — prefill did not manufacture readiness.
* Webhooks: the two natural connected events for the new account
  (`capability.updated`, `account.updated`) arrived signature-verified, scoped
  `connect`, TEST, API `2026-03-25.dahlia`, and applied. A signed duplicate
  replay returned `200 {"received":true,"duplicate":true}` twice with no new
  rows and no repeated effect. Stored payloads carry no bank, identity or
  business-profile values.
* Client injection refused live: `business_profile.url` and
  `product_description` in the onboarding request body both return
  `400 "Unexpected payout profile fields."`.
* DZ remains unsupported: `400 payout_country_unsupported` with the DZD manual
  alternative and `supported_countries: ["FR"]`.
* Unauthenticated onboarding returns `401`. Accounts stay owner-scoped and
  distinct.
* EUR 3 TEST Checkout unchanged: `paid`, 300/300 cents, 0 refunded, exactly one
  applied platform event, two balanced ledger entries. Platform event count
  unchanged at 10.
* No Stripe Transfer, no connected-account Payout on either account, no
  reversal, no cancellation, no Chargily money operation, no LIVE mutation. The
  EUR 60 QA payout `1` remains `blocked` with no paid, sent or settled timestamp
  and no provider payout reference. Email disabled.

### Retained TEST QA artifacts

Two throwaway connected accounts were created directly against the Stripe TEST
API to establish the requirement contract before any code was written:
`acct_1UDWlx3VljT9k3Z7` (baseline, no prefill) and `acct_1UDWmc441t5Pa3jV`
(created with the description). Both are labelled
`shiptrip_qa=h26_contract_probe_retained_test_qa` and are retained rather than
deleted, per this phase's instruction to preserve provider history.

They had one unplanned but useful side effect: because they belong to no ShipTrip
Traveler, their natural `account.updated` events reached the Connect webhook and
were stored as `ignored / unknown_connected_account`. That is live evidence that
an account outside ShipTrip's own binding cannot affect local state.
