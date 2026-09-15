# Phase J2 — Pricing, flexible deposit, universal guest payer, Boost economics

Status: implemented, TEST only. Stripe TEST, Chargily TEST, `PAYOUTS_DZD_EXECUTION_ENABLED`
false, no LIVE provider activation and no real-money operation.

J2 turns four product decisions the owner made during testing into backend
contract. It changes economics, so it is written to be checkable: every rule
below has a named test, and the H5 financial regression is part of the gate.

Starting point: `aa92cd7` (J1.3 PASS, release `v1.0.0-rc.33+8f4026c`).

---

## 1. Three prices, named apart

A sender used to be shown one number. J2 makes the distinction explicit and puts
all three on the wire together:

| Value | Meaning | Enforced? |
|---|---|---|
| `minimum_reward_eur_cents` | The lowest reward the platform permits for this route and weight. | **Yes** |
| `recommended_reward_eur_cents` | What ShipTrip suggests. | No — advice in both directions |
| `chosen_reward_eur_cents` | What the sender actually picked. | Must be ≥ minimum |

**Ordering matters.** The recommendation has to be visible *before* the sender
chooses, not returned as a correction afterwards. `POST /api/parcels/pricing-quote`
prices a draft — the fields the posting form has already collected — without
writing a row.

**How it is priced without a journey.** `apps/matching/posting_pricing.py` runs
the existing Phase 2 pricing engine over the request's own straight-line
pickup→delivery distance, with no detour and no urgency premium. That is a
deliberate lower bound: every real matched route is at least this long, so

* a posting-time refusal can never reject a price a real match would accept, and
* the deposit — a tenth of the recommended sender total — can never exceed a
  tenth of what the sender ends up owing.

A request whose canonical places publish no centroid prices at the global floor
rather than erroring. Refusing to price would leave a sender unable to post.

**Below the minimum** returns `400` with `code: "price_below_minimum"`, the
minimum, and the recommendation. Below the *recommendation* is allowed and is
not commented on beyond a `chosen_is_below_recommended` flag.

**The matched check still runs.** `apps.matching.v1_services` re-validates every
offer against the real sub-route. A sender who posts at the posting-time floor
may still find one particular long journey prices above it. That is correct and
J2 does not weaken it.

Canonical money is EUR cents throughout. No float touches any of it.

---

## 2. The posting deposit is a choice, not a fee

### Recommendation (unchanged)

`recommended = clamp(10% of the recommended sender total, €3, €7)`

Recommended sender total €50 → recommended deposit €5.

### What the sender may choose (new)

* **Minimum €3** — `payments.posting_deposit.chosen_min_eur_cents`.
* **No artificial €7 ceiling.** The €7 clamp bounds the *recommendation*, not
  the choice. €4, €5, €7, €10 and more are all valid.
* **Maximum = the obligation the deposit pre-pays**: the sender's own chosen
  reward, its commission, and — if they set one — their Boost with its own
  commission. Pre-paying more than the total would leave a credit with nothing
  to discharge.

`POST /api/parcels/<id>/posting-deposit` accepts an optional
`amount_eur_cents`. Omitting it takes the recommendation. Refusals are
`deposit_below_minimum` and `deposit_above_obligation`, both with the band.

### Repricing

One live deposit obligation per request, always — the existing partial unique
index. A chosen amount **reprices** that order rather than creating a second
one, and only while it is untouched: pending, nothing captured, nothing
credited, and **no checkout attempt open**. An open attempt refuses with
`deposit_checkout_in_progress`, because the provider was asked for a specific
amount and changing the obligation underneath that session would collect the
wrong number.

### A deposit already committed pins the total down

Lowering a Boost lowers the obligation, and `apply_posting_deposit_credit` only
ever credits `min(deposit paid, balance owed)`. A deposit larger than the new
total would leave the difference discharging nothing — neither credited nor
refunded. So a Boost reduction that would strand committed deposit money is
refused with `boost_below_prepaid_deposit`, naming the amount the Boost may not
go below. Raising a Boost is never restricted.

### A bigger deposit does not buy a bigger reward

Four values stay separate and are never conflated:

```
chosen reward          what the Traveler is offered for the carry
Boost                  extra reward on top of it
deposit already paid   money paid early, credited against the total
remaining balance      what is still owed
```

### Snapshot

Every deposit order freezes, in `terms_snapshot.posting_deposit_inputs`:
the recommended deposit, the chosen deposit, whether the sender chose it, the
chosen base reward, the Boost at that moment, the recommendation basis, the
band, and the remaining payable amount. `posting_deposit_quote_from_order`
rebuilds the guidance from that snapshot, never from live policy — a later
settings revision cannot restate what somebody was charged.

### Crediting

Unchanged and still structural: `PaymentOrder.credit_source` is a one-to-one
link, so a deposit can be the credit source of at most one balance order. A
second attempt to spend it fails on the unique index rather than discounting
twice. A deposit equal to the full obligation leaves `outstanding = 0` and funds
the Deal with no second charge.

---

## 3. Guest payer, on every sender obligation

The guest-payer rail already existed and already worked on any `PaymentOrder`.
J2 makes it complete rather than rebuilding it.

**One rail, not two.** A guest payment enters the identical `PaymentAttempt`,
provider verification, ledger, Deal funding, refund and reconciliation flow as
the sender's own. The only difference is payer authentication. There is no
second financial rail anywhere in J2.

**What the token buys.** Exactly one capability: paying this one obligation. Not
Deal access, not the sender's account, not chat, not the delivery code, not
dispute or rating rights, not the traveler's details, not the ability to alter
the amount or redirect the payment. The guest payload is the proof — amount,
currency, purpose, a generic description, an expiry and the available rails, and
nothing else. Only a SHA-256 hash of the token is stored.

**The link.** `POST /api/payments/orders/<ref>/guest-link` now returns a
server-generated `payment_link` (`/pay/guest/<token>`) alongside the token, so a
client copies or shares a URL rather than assembling one. The path carries the
opaque token and no internal identifier.

**The page.** `/pay/guest/<token>` renders a real page — amount, purpose,
expiry, a rail picker and an email field — and redirects to the hosted
provider. Without it the shared link answered raw JSON, which is not something
anyone can forward to a relative. Trilingual, because a guest has no ShipTrip
locale. Returning from the provider proves nothing: only the signature-verified
webhook moves money.

**Duplicate protection.**

* One live link per obligation (partial unique index). Issuing retires the
  previous one and the response says so (`reissued: true`).
* One open attempt per obligation. A second checkout — guest or sender —
  supersedes the first, so two live checkouts can never race to fund the same
  order.
* Money the obligation cannot absorb is recorded `is_unapplied` and refunded in
  full, never silently dropped and never used to fund anything twice.
* Once paid, every link to that order stops resolving: `resolve_guest_link`
  refuses an order with nothing outstanding.
* Reissuing while a guest checkout is open refuses with
  `guest_checkout_in_progress`, rather than invalidating a session someone is
  standing in front of. Revoking remains the owner's escape hatch.

**Uniform failure.** Unknown, expired, revoked, consumed and closed-order all
answer with the same `guest_link_invalid` in the same words, so a prober cannot
learn which obligations exist.

The one thing told apart from that is "the link is fine but no payment rail is
up right now", which answers 503 with its own wording. "Try again shortly" and
"ask for a new link" are different instructions, and giving a guest the wrong one
sends them back to the sender over a link that was never the problem. It
discloses nothing: whoever is reading it already holds a valid token.

---

## 4. Boost is extra reward

### What changed

The J1-era Boost was a **timed paid visibility package**: the sender bought a
24h/72h/7d window through its own payment order, and the money was *divided* —
75% to the eventual Traveler, 25% to ShipTrip.

J2 Boost is **extra reward the sender attaches to their own request**. No
package, no timer, no countdown, no visibility window, and no separate payment.

```
base chosen reward   €20
Boost               +€8
Traveler is offered  €28
```

### Economics — additive, with its own rate

The Traveler receives the **whole** Boost. ShipTrip's commission on it is
charged **on top**, exactly as the base commission is charged on top of the base
reward:

```
boost_traveler_bonus = boost
boost_platform_fee   = ceil(boost × boost_commission_rate_bps / 10_000)
sender pays          = boost + boost_platform_fee
```

This mirrors the platform's existing rule that commission is never silently
subtracted from what a Traveler believes they accepted, and it is what makes
"total offered reward = base + Boost" true.

`boost.commission_rate_bps` is **separate** from
`BusinessSettingsVersion.commission_rate_bps`. Nothing derives one from the
other. Seeded equal (2500) so J2 ships with no silent price change.

Rounding is integer cents, ceiling to the platform — the same rule as
`calculate_offer_economics`. Covered by tests: €0, €1, odd-cent (€3.33 → 84c),
€1,000,000, 0% rate, normal rate, 100% rate.

### Bounds

| | Value | Key |
|---|---|---|
| Zero | Always allowed — means "no Boost" | — |
| Minimum non-zero | €1 | `boost.minimum_intent_eur_cents` |
| Maximum | €1,000,000 | `boost.maximum_intent_eur_cents` |

The retired package's €5 minimum is gone with the package — it existed because a
timed package cost that much to run. €1 is the smallest amount that is a real
offer rather than noise. The maximum is the same ceiling every other
sender-chosen money field on a request carries; a larger number is a typo.

### Lifetime — no timer

A Boost lasts exactly as long as the request can still be matched. There is no
Boost expiry, no `BOOST_EXPIRY` job for it, and no countdown to render. The
ranking pair's `ranking_boost_expires_at` is the request's own `deadline_at`,
which is the instant the request stops being matchable anyway — that satisfies
the absolute `parcels_ranking_boost_pair` constraint without inventing a timer.

It ends when the request is committed/matched, cancelled, or expired.

### Editing

While the request is `open` or `awaiting_deposit`, the sender may add, increase,
decrease, or remove the Boost to €0. `PUT /api/parcels/<id>/boost`.

The instant an offer is accepted the request is `matched` and every edit is
refused with `boost_request_not_active`. A sender can never reduce compensation
a Traveler has already agreed to.

Every change appends a `BoostIntentEvent` — previous amount, new amount, reason,
actor, request status, settings version. Append-only, read-only in the admin.
A Boost moves money without a payment of its own, so the audit trail is the
whole evidence base for the figure that lands on a Deal.

That includes the first cent. A request posted with a Boost is written with the
column at zero and then moved by the same transition a later edit uses, so the
trail opens on a real `0 -> chosen` row rather than a `chosen -> chosen` one
that would make the origin of the money unreadable.

### Ranking

Unchanged in principle and still structural: a Boost changes where a
**compatible** request appears in a list and never makes an incompatible request
compatible. `apps.matching.ranking` raises if asked to rank a candidate that
failed compatibility, and the points bonus stays capped.

Weight is derived, never incremented:
`clamp(ceil(boost / ranking_weight_step_eur_cents), 1, ranking_weight_max)`,
seeded at €5 per point and a maximum of 30.

---

## 5. Freezing, funding, and the rematch question

### The commitment boundary

Acceptance copies onto `DealTermsSnapshot`:

* `boost_amount_minor`, `boost_traveler_bonus_minor`, `boost_platform_fee_minor`
* `boost_commission_rate_bps` — **new**
* `boost_economics_version` — **new**: `additive_commission_v2` or
  `traveler_split_v1`
* plus the existing base reward, base rate, base fee and sender total

A later Admin change to the Boost commission cannot move any of them. Verified
by test.

The Deal balance obligation is `sender_total + boost + boost_platform_fee`,
because a J2 Boost has no payment order of its own. If it were left out, the
Traveler would be promised a bonus nobody was ever charged for.

### Consumption — the rematch answer

**`fund_deal` clears `boost_eur_cents` on the request.**

That one line is the whole answer to the question J1.3 left open, and it is
structural rather than a policy someone has to remember:

* **Unfunded reservation released** → the request returns to `open` with its
  Boost **intact**. Nobody paid it; it belongs to the request, not to the
  traveler who walked away. It becomes editable again, its ranking weight is
  rebuilt, and a `released_with_reservation` event records the revival.
* **Funded Deal cancelled** → the Boost was paid for, and the column is already
  zero, so there is nothing to revive. The request is also terminal in this case
  (`apps/parcels/lifecycle.py` maps a cancelled funded Deal to `CANCELLED`), so
  the accounting provenance and the lifecycle agree. The frozen copy on
  `DealTermsSnapshot` remains the authority for that Deal's money.
* **Request cancelled or expired unmatched** → the unpaid Boost ends with the
  request, recorded as `request_closed`.

No Boost amount that has been financially consumed can reappear on a reopened
request, and no unpaid Boost is silently lost.

---

## 6. Accounting and revenue recognition

### Funding

Two ledger transactions, deliberately not one:

* `deal_funding:deal:<id>` — base reward → traveler payable, base commission →
  platform commission.
* `deal_boost_allocation:deal:<id>` — **new** — Boost → traveler payable, Boost
  commission → platform commission.

Both release from the same pooled `deal_funds` liability, which already contains
the Boost because it arrived inside the balance order. The pooled liability
nets to zero, and `assert_deal_reconciles` returns `net == 0`.

Keeping them apart is what lets H5 say how much platform commission came from
delivery and how much from Boost. Merging them would make that unanswerable.

Both are keyed per Deal, so a replayed webhook recognises each exactly once.

### H5

H5 reads ledger accounts generically — `platform_commission`,
`traveler_payable`, `provider_clearing`, `deal_funds` — and recognises platform
commission at the Deal's completion or settlement instant. A J2 Boost commission
entry carries the same account, the same `deal_id` and the same recognition
trigger as the base commission, so it reconciles without any change to H5's
definitions and without confusing gross funded volume, Traveler liability or
recognised revenue. No new revenue component was needed.

`apps/finance/tests/test_j2_h5_regression.py` is the gate rather than a
formality: it builds a whole J2 delivery through production services on the
Stripe TEST rail — chosen deposit, Boost, guest payer, funding, payout profile
— and then requires H5's own reconciliation to come back `ok` with every
comparison at a zero difference, zero row mismatches and no unbalanced
transaction.

One observation the test surfaced is worth recording because it is *not* a J2
effect. With `PAYOUT_PROFILES_ENABLED` off, a Payout row is stamped
`legacy_unknown` and falls outside H5's mode scope, so the traveler comparisons
read zero against a live ledger liability. That is legacy pre-H3 behaviour and
pre-dates J2 entirely; the regression runs with profiles on so the comparison it
makes is a real one.

### Refunds and settlement

`read_deal_money` already read `traveler_total_minor`,
`platform_total_minor` and `sender_total_with_boost_minor`, so settlement,
partial refunds, disputes and cancellation needed no change: under J2 the Boost
cash simply sits in `balance_cash_eur_cents` instead of
`boost_cash_eur_cents`. Boost follows the reward portion it belongs to through
every refund path. No orphan Boost revenue can exist, because there is no Boost
obligation that can outlive the Deal it belongs to.

`sender_total_with_boost_minor` is version-aware: under `traveler_split_v1` the
Boost commission came *out of* the Boost, so the sender owed the Boost and no
more; under `additive_commission_v2` they owe both.

---

## 7. Historical compatibility

Nothing settled is rewritten.

| Old artefact | Disposition |
|---|---|
| `BoostPurchase` rows | **Retained, unchanged.** Amount, split, package, duration, weight and settings version stay exactly as sold. |
| `purchase_boost` | **Retired.** Raises `BoostPurchaseRetired`; `POST /api/parcels/<id>/boosts` answers `410`. |
| `GET /api/boosts/packages`, `POST /api/boosts/preview` | **Retired**, `410` with `boost_package_retired` and a pointer to the replacement. 410 rather than 404 so an old client gets a named answer, not a network fault. |
| `GET /api/parcels/<id>/boosts` | **Retained.** A settled payment stays readable by the person who made it. |
| `boost.traveler_share_bps`, `boost.minimum_amount_eur_cents`, `boost.packages` | **Retained in policy**, parsed only so historical rows keep explaining themselves. |
| `activate_paid_boost`, `expire_boost`, `unwind_boosts` for purchases | **Retained.** A payment in flight when J2 shipped still reconciles, activates, expires and refunds correctly. |
| `deals_terms_boost_total_sum` constraint | **Now conditional** on `traveler_split_v1`; a second constraint covers `additive_commission_v2`. Existing rows default to `traveler_split_v1`, which is what they were. |

Both models are never active on one Deal. If a historical paid package binds at
acceptance it wins and the J2 branch is not taken, so no cent is counted twice.
`recompute_request_boost` derives the request's ranking columns from whichever of
the two is stronger, so the two cannot fight over the same column.

Migrations are additive: two new columns, one new table, one relaxed-and-split
check constraint, and one new settings revision copied from the active one.

---

## 8. Admin

`boost.commission_rate_bps` is editable in the operations console at
**Settings → Boosts**, gated by the existing `manage_settings` capability
(Super Admin), audited through `_save_settings_revision` like every other
commercial input, and authoritative for **future commitments only**. Finance and
operator roles do not own pricing settings and cannot reach it.

The console now also shows the boost band, the commission and — because it is a
consequence worth stating plainly — that the Traveler receives 100%.
`payments.posting_deposit.chosen_min_eur_cents`, the boost band and the boost
commission all appear in the read-only policy reference.

---

## 9. Authorization

| Actor | May |
|---|---|
| Sender | Edit their own open request's Boost; choose their own price and deposit; issue and revoke guest links on their own obligations |
| Traveler | Nothing that alters sender economics. Cannot read the request's Boost or pricing, cannot issue a link, sees only that a Deal is funded |
| Guest | Pay one opaque authorized obligation. Nothing else |
| Admin | Manage the Boost commission where `manage_settings` is held; read financial rows |
| Anyone else | Cannot inspect or modify a payment link or any financial field |

---

## 10. Concurrency

| Race | Resolution |
|---|---|
| Sender edits Boost while Traveler accepts | Both take the request row `FOR NO KEY UPDATE`. The second reads committed state; an edit after acceptance finds `matched` and is refused. |
| Sender changes deposit while a checkout is open | `deposit_checkout_in_progress`. The provider's session keeps the amount it was given. |
| Two guest payers on one link | One open attempt per obligation; the second supersedes the first. A late success is recorded `is_unapplied` and refunded in full. |
| Sender pays while a guest pays | Same invariant, same outcome. Verified end to end. |
| Link revoked mid-payment | Reissue refuses while an attempt is open; explicit revoke is the owner's decision and a late success refunds. |
| Duplicate provider webhook | Provider event idempotency ledger; ledger transactions keyed per Deal; funding is idempotent. |
| Reservation released while Boost is changed | Both enter through the request graph lock in canonical order. |

No new lock edge was added. `boost_eur_cents` lives on `DeliveryRequest`, which
`lock_request_graph` already acquires first.

---

## 11. The J3 mobile contract

Frozen here. J3 renders it; it does not compute money.

### `POST /api/parcels/pricing-quote`
Draft inputs → `minimum_reward_eur_cents`, `recommended_reward_eur_cents`,
`chosen_reward_eur_cents`, each with `*_economics`
(`traveler_reward_minor` / `platform_fee_minor` / `sender_total_minor`), plus
`boost` and `deposit` blocks.

### `GET /api/parcels/<id>/pricing`
The same, for a saved request, plus:

* `boost` → `boost_eur_cents`, `boost_commission_rate_bps`,
  `boost_traveler_bonus_eur_cents`, `boost_platform_fee_eur_cents`,
  `boost_sender_cost_eur_cents`, `base_reward_eur_cents`,
  **`total_offered_reward_eur_cents`**, `policy` (band, rate, `has_expiry: false`)
* `deposit` → `recommended_eur_cents`, `minimum_eur_cents`, `maximum_eur_cents`,
  `chosen_eur_cents`, `outstanding_eur_cents`, `order_status`
* `actions` → `can_edit_boost`, `can_choose_deposit`, `can_cancel`

### `GET` / `PUT /api/parcels/<id>/boost`
Read and set. `PUT {"boost_eur_cents": N}`; `0` removes it. Returns the amount,
priced economics, `can_edit`, `eligible_until` and the change history.

### `GET /api/boosts/policy`
Band, rate, `has_expiry: false`, `affects_compatibility: false`.

### `GET`/`POST /api/parcels/<id>/posting-deposit`
The band and the sender's choice; `POST {"amount_eur_cents": N}` optional.

### `POST /api/payments/orders/<ref>/guest-link`
`token`, **`payment_link`**, `expires_at`, `amount_eur_cents`, `purpose`,
`reissued`.

### Payment success — `settlement` on `GET /api/payments/orders/<ref>`
`is_settled`, `purpose`, `amount_eur_cents`, `paid_eur_cents`,
`deposit_credited_eur_cents`, `remaining_eur_cents`, `refunded_eur_cents`,
`deal_id`, `delivery_request_id`, `paid_by` (`self` / `guest`, never who),
`next_step`, `paid_at`.

No visual work was done in J2 and no mobile screen was redesigned.

---

## 12. Error codes

| Code | HTTP | Meaning |
|---|---|---|
| `price_below_minimum` | 400 | Chosen reward under the platform floor |
| `deposit_below_minimum` | 409 | Chosen deposit under €3 |
| `deposit_above_obligation` | 409 | Chosen deposit above what it pre-pays |
| `deposit_checkout_in_progress` | 409 | Cannot reprice with a checkout open |
| `boost_amount_below_minimum` | 409 | Non-zero Boost under the band |
| `boost_amount_above_maximum` | 409 | Boost over the band |
| `boost_request_not_active` | 409 | Request is committed or terminal |
| `boost_request_expired` | 409 | Past its deadline |
| `boost_package_retired` | 410 | The J1 paid package is not sold |
| `guest_link_invalid` | 404 | Unknown, expired, revoked, used, or closed |
| `guest_checkout_in_progress` | 409 | A payer is mid-checkout on the live link |
| `boost_below_prepaid_deposit` | 409 | The cut would strand committed deposit money |

---

## 13. Files

**New**
`apps/matching/posting_pricing.py`, `apps/parcels/pricing_api.py`,
`apps/finance/guest_web.py`, `templates/payments/guest.html`,
`apps/boosts/tests/test_j2_boost.py`,
`apps/finance/tests/test_j2_pricing_deposit_guest.py`,
`apps/parcels/tests/test_j2_posting.py`.

**Migrations**
`core/0010_seed_j2_boost_commission`, `parcels/0010_j2_boost_reward`,
`boosts/0003_j2_boost_reward`, `deals/0009_j2_boost_reward`.

**Changed**
`apps/core/phase4_policy.py`, `apps/core/policy_display.py`,
`apps/finance/policy.py`, `apps/finance/services.py`, `apps/finance/views.py`,
`apps/finance/serializers.py`, `apps/finance/ledger.py`, `apps/finance/jobs.py`,
`apps/boosts/*`, `apps/deals/models.py`, `apps/deals/services.py`,
`apps/matching/v1_services.py`, `apps/parcels/models.py`,
`apps/parcels/serializers.py`, `apps/parcels/views.py`,
`apps/parcels/services.py`, `apps/parcels/urls.py`,
`apps/admin_panel/console_forms.py`, `apps/admin_panel/console_views.py`,
`templates/admin/console/settings.html`, `config/urls.py`.

---

## 14. Known limits

* The H5 control plane's 85–100 queries and 4–6 s per page are unchanged. J2 did
  not make that functionally necessary to fix, and it has its own backend brief.
* The mobile app still calls the retired package endpoints, which now answer
  410. J3 replaces those calls; no mobile code was changed in J2.
* `DeliveryQuoteView` and `apps/core/pricing.py` remain the legacy DZD-era
  helpers. They are untouched, unreferenced by V1 pricing, and out of J2 scope.
