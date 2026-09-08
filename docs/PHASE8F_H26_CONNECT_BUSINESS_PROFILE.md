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
own marketing site is not theirs to claim. `product_description` is provider-
facing risk copy that the platform is expected to supply on the account's
behalf, and it is never shown to the Traveler.

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
business, or an owner of ShipTrip. English because Stripe reads it; no Traveler
is ever shown it.

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
