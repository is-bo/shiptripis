# ShipTrip V1 Phase 1 API contract changes

This document is the breaking-contract handoff for the later Flutter redesign.
Legacy history is preserved, but new marketplace writes must use these V1
contracts.

## New contracts

| Method and path | Purpose | Important rules |
|---|---|---|
| `POST /api/locations` | Create an immutable Location | The server assigns owner/creator and derives public labels/coarse coordinates; caller-supplied public/coarse values are rejected. |
| `GET /api/locations` | Read the caller's Locations | Owner-only collection, capped at 100 records; exact/provider fields are private. |
| `GET /api/locations/{id}` | Read one Location | The owner receives private fields. Other authenticated callers receive only the public/coarse representation. |
| `POST /api/journeys` | Create a draft Journey with nested ordered legs | Modes are `FLIGHT` and `DRIVE`; positions start at zero and are contiguous. |
| `POST /api/journeys/{id}/legs/{leg_id}/proof` | Upload private flight proof | Flight legs only; storage references are owner-only. |
| `POST /api/journeys/{id}/publish` | Publish a Journey | Requires current approved KYC and approved proof for every FLIGHT leg. |
| `GET /api/journeys/search` | Search active Journeys | Supports `start_location_id`, `destination_location_id`, `mode`, `departure_after`, and `min_capacity_kg`; excludes the caller's Journeys and Journeys whose KYC/proof eligibility has expired. Capacity accounts for active Deal allocations. |
| `POST /api/parcels/delivery/v1` | Create a V1 DeliveryRequest | Location IDs, ready window/deadline, decimal weight/dimensions, EUR cents, item metadata, and all safety declarations are required as applicable. DZD/airport inputs are rejected. |
| `POST /api/matches/propose` | Sender creates the first V1 Offer | Requires a V1 DeliveryRequest, active Journey, covered start/end leg IDs, and `traveler_reward_eur_cents`. Server snapshots settings and computes the fee/total. |
| `POST /api/offers/{id}/counter` | Non-proposer counters a V1 Offer | Creates a new immutable EUR Offer and marks the parent countered. |
| `POST /api/offers/{id}/accept` | Non-proposer accepts | Atomically creates a `payment_required` Deal, immutable terms, timeline events, and segment allocations. Repeated acceptance returns the existing Deal. |
| `POST /api/offers/{id}/decline` | Non-proposer declines | Expires the pending V1 Match so the sender can make a fresh proposal. |
| `POST /api/offers/{id}/withdraw` | Proposer withdraws | Cancels the pending V1 Match so the sender can make a fresh proposal. |
| `GET /api/deals[/{id}]` | Party-only Deal read | Returns terms, leg allocations, and audit events. |

## Retired public writes

These endpoints return `410 Gone` for authenticated callers:

- `POST /api/trips`
- `GET /api/trips/search`
- `POST /api/trips/{id}/cancel`
- `POST /api/trips/{id}/media`
- `POST /api/parcels/delivery`
- `GET /api/parcels/quote/delivery`
- `POST /api/parcels/product`
- `POST /api/matches/apply`
- `POST /api/matches/apply-to-trip`
- `POST /api/matches/{id}/offers/counter`

Legacy Trip/Parcel/Offer records remain available only through explicit
historical/owner/admin reads. ProductRequest detail, cancel, media, matching,
payment, handover, and chat paths return `410 Gone`; Product history remains
read-only in admin. A legacy DZD Offer is rejected by the V1 counter/accept
service, and a Product-backed legacy Offer is rejected by both services.

## Response model changes

- `Offer` now includes `economics_version`, `currency`,
  `traveler_reward_minor`, `commission_rate_bps`, `platform_fee_minor`,
  `sender_total_minor`, `pricing_version`, `business_settings_version_id`, and
  a frozen `terms_snapshot`. For V1, `minor` means EUR cents.
- `Match` now includes `journey_id`, `start_leg_id`, `end_leg_id`, and
  `deal_id`. `trip_id` is nullable and legacy-only.
- `DeliveryRequest` V1 adds Location/timing/parcel/safety fields and
  `schema_version=2`. Legacy airport, integer-weight, and DZD fields are null.
- Exact pickup/delivery Location fields are visible to the sender immediately
  and to the assigned traveler only after `Deal.funded_at` is set. Offer
  acceptance is not funding.
- Non-owners never receive Journey proof rows; only the aggregate
  `has_approved_proof` flag is public. Proof object keys, route polylines, and
  provider metadata are never exposed to unrelated marketplace users.
- Cancelling a V1 request with an existing Deal is rejected and retains its
  allocations. Cancelling an unmatched open request expires pending Matches
  and withdraws pending Offers transactionally.
- V1 Deals deliberately cannot use legacy PaymentIntent, mock webhook,
  handover, wallet, or chat endpoints. Those integrations require the Phase 2
  Deal-native design.

## Flutter migration map

| Legacy client concept | V1 replacement |
|---|---|
| Airport-pair `TripModel` | `Journey` with ordered `JourneyLeg` values and Location summaries |
| Integer `weightKg` | Decimal `actual_weight_kg` and per-leg decimal capacity |
| DZD price/quote fields | EUR-cent Offer fields; format cents as EUR only |
| Traveler applies first | Sender proposes; traveler accepts/declines/counters |
| Match as fulfillment/payment | Deal as the durable lifecycle aggregate |
| Offer acceptance means paid | Deal remains `payment_required` until a later real provider succeeds |
| ProductRequest/Kaba tabs | Remove from V1 navigation; keep no new-write affordance |
| Immediate handover/payout UI | Do not connect to V1 Deals until Phase 2 code-delay/protection rules exist |

## Phase 2B read-contract changes

These are breaking read changes for the Phase 5 client. Nothing about writes,
authorization or state transitions changed; the payloads did.

| Was | Now |
|---|---|
| `compatibility` carried `pickup_route_position`, `delivery_route_position`, `pickup_detour_meters`, `delivery_detour_meters`, `estimated_added_distance_meters`, `distance_components`, `checks`, `capacity_remaining_by_leg`, `pickup_at`, `delivery_at` | `pickup_detour_band`, `delivery_detour_band`, `total_added_distance_band` (`under_5km` / `5_15km` / `over_15km`), `covered_legs`, `estimated_pickup_window`, `estimated_delivery_window`, `capacity_available_on_every_covered_leg` |
| `pricing.matched_distance_meters`, `pricing.matched_distance_method` | `matched_distance_band` (`{label, min_meters, max_meters}`), `matched_distance_precision` (`routed` / `estimated` / `mixed` / `unavailable`) |
| `pricing.detour_adjustment_cents`, `pricing.urgency_adjustment_cents` | `detour_adjustment_applied`, `urgency_adjustment_applied` (booleans) |
| `pricing.recommended_reward_eur_cents` everywhere | request owner only (`compatible-journeys`, `quote`); absent from `compatible-requests` and from Offer/Deal terms |
| `ranking` on every candidate | removed from all party-facing payloads; admin explain keeps it |
| `POST /matches/quote` returned the admin explain payload | narrow `{delivery_request, journey, compatibility, pricing}` |
| `Match.matched_distance_meters`, `Match.ranking_snapshot` | `matched_distance_band`; `ranking_snapshot` removed |
| `Offer.terms_snapshot.policy` was the whole business policy, plus `ranking` | `policy` is `{reservation: {payment_grace_seconds}}`; `ranking` removed |
| V1 Offer carried `base_amount_dzd`, `base_fee_dzd`, `commission_dzd`, `total_dzd` as `0` | absent on V1 EUR offers; legacy DZD offers keep them |
| `JourneyLeg.distance_meters`, `route_duration_seconds` public | owner only; non-owners get `distance_band` |
| `DeliveryRequest.traveler_reward_eur_cents` | `sender_proposed_reward_eur_cents` (read and write). Sender intent only — `Offer.traveler_reward_minor` is the agreed reward |
| `GET /api/parcels/open?origin=&destination=` returned an empty 200 | 400 `airport_filter_retired`; use `GET /api/matches/compatible-requests` |
| Client derived accept/counter/decline/withdraw from proposer and status | `Offer.awaiting_party`, `awaiting_user_id`, `allowed_actions` are computed server-side per caller |
| Discovery candidate omitted the leg IDs `propose` requires | `journey.start_leg_id`, `journey.end_leg_id`, `journey.covered_legs` |
| Failures returned `invalid_state` / `incompatible_candidate` with data in prose | distinct codes plus `rejection_codes`, `minimum_reward_eur_cents`, `journey_leg_ids`. See the failure table in `docs/PHASE2_MATCHING_PRICING.md` |
| Declining a V1 offer set the Match to `expired` | `cancelled`, matching withdraw. `expired` now means a system-driven ending |

Client rules that follow from this:

- Never compute a price, a distance, a detour or a negotiation action locally.
  Render `allowed_actions` and the published bands as given.
- Treat `detail` strings as display text. Branch on `code` and the structured
  fields only.
- Exact pickup/delivery timing and the exact address both appear after
  `Deal.funded_at`, not before.

---

# Phase 3 addendum — payment contracts

The full reasoning is in `docs/PHASE3_PAYMENTS.md`; this is the contract summary
the Flutter rebuild needs.

## New endpoints

| Method and path | Purpose | Important rules |
|---|---|---|
| `GET /api/payments/providers` | Which rails this caller may actually use | Server-authoritative. A provider is `available` only when policy enables it, credentials exist, and it takes new checkouts. Never render a rail the server did not list. |
| `GET /api/payments/orders` | The caller's own obligations | Owner-scoped. |
| `GET /api/payments/orders/{public_reference}` | One obligation in full | Addressed by random UUID, not primary key. Carries `outstanding_eur_cents` pre-computed, plus a `chargily_quote` when Chargily is enabled. |
| `POST /api/payments/orders/{public_reference}/checkout` | Open a hosted checkout | Body is `{"provider": "stripe"} or {"provider": "chargily"}` and nothing else. Supplying an amount, currency or rate is a **400**, not an ignored field. Returns the attempt with `checkout_url`. |
| `POST /api/payments/orders/{public_reference}/guest-link` | "Have someone else pay" | Returns the plaintext token **once**. It is never stored and cannot be re-read; reissue instead, which revokes the previous link. |
| `POST /api/payments/orders/{public_reference}/guest-link/revoke` | Kill a live link | Owner only. |
| `GET /api/parcels/{id}/posting-deposit` | Deposit quote and state | Sender only. Returns `deposit_required`, the server-calculated `quote`, and the `order` once one exists. |
| `POST /api/parcels/{id}/posting-deposit` | Create the deposit obligation | Idempotent — a repeat returns the same `public_reference`. |
| `GET /api/deals/{id}/payment` | The Deal's outstanding balance | Sender sees the full order; the traveler sees `status` and `outstanding_eur_cents` only. |
| `GET /api/payouts` | The traveler's own earnings | Always `not_eligible` in Phase 3; Phase 4 owns release. |
| `GET /api/payments/guest/{token}` | The guest surface | Unauthenticated. Amount, currency, generic description, expiry, rails. Nothing else, and no identifiers. |
| `POST /api/payments/guest/{token}/checkout` | Guest checkout | Same body rules as the owner checkout. |
| `POST /api/payments/webhooks/{stripe,chargily,mock}` | Provider events | Signature-verified, idempotent. Never called by the client. |
| `POST /api/admin/payouts/{id}/complete` | Manual payout settlement | Staff only; refused until Phase 4 releases the payout. |
| `POST /api/admin/payments/orders/{ref}/refund` | Administrative refund | Staff only. |
| `POST /api/admin/payments/refunds/{id}/settle` | Close an operator-settled refund | Staff only; reference mandatory. |

## Changed behaviour

* `POST /api/parcels/delivery/v1` now returns a `posting_deposit` object and
  creates the request as `awaiting_deposit` when the platform is in
  posting-deposit mode. The request is **not** discoverable until the deposit is
  reconciled — do not assume a created request is live.
* `ParcelRequest.status` gains `awaiting_deposit`.
* `POST /api/parcels/{id}/cancel` accepts `awaiting_deposit` as well as `open`,
  refunds any paid deposit, and now returns a machine code
  (`parcel_not_cancellable`) with `parcel_status` on refusal.
* `POST /api/offers/{id}/decline` and `/withdraw` now return
  `{code, detail, ...}` like every other V1 negotiation route.

## What the client must not do

The server calculates the deposit, the outstanding balance, FX, commission, the
sender total, the refund amount and payout eligibility. All of them arrive
pre-computed. A redirect back from a provider is **not** payment success — poll
the order or wait for the `payment.captured` event; `payment.failed` is a
separate channel and a failure never travels on the capture channel.

---

# Phase 6C addendum — communication language

All language inputs are explicit choices: `en`, `fr`, or `ar`. Unsupported
values are rejected at the API edge. Historical blank User/recipient values
resolve to English.

| Contract | Addition |
|---|---|
| `POST /api/auth/sign-up` | Optional `preferred_language`; default `en`. |
| `POST /api/auth/oauth/google` | Optional `preferred_language` for a newly created account; default `en`. Existing accounts keep their stored preference. |
| `GET /api/me` | Returns resolved `preferred_language`. |
| `PATCH /api/me` | Updates `preferred_language`; no other profile field becomes writable. |
| `PUT /api/deals/{id}/recipient` | Optional `communication_language`. New recipients omitted by an older client snapshot the sender's preference; updates that omit it preserve the existing choice. |
| `POST /api/payments/orders/{public_reference}/guest-link` | Optional `communication_language`; omission snapshots the owner's preference. The response returns the resolved value. |
| `POST /api/payments/guest/{token}/checkout` | Adds guest receipt `email`. It is required when transactional email is enabled and grants no account or Deal authority. |

The server snapshots the resolved locale onto every outbound obligation.
Clients must not expect a queued email to change language after a later profile
update.

