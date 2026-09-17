# Phase J6.3 — Request-creation Boost total projection

Status: implemented, TEST only. Stripe TEST, Chargily TEST,
`PAYOUT_DZD_EXECUTION_ENABLED` false, no LIVE provider activation and no
real-money operation.

Starting point: `256a110` (J6.2 PASS). Branch `claude/j63-request-boost-total`.

J6.2 found one MAJOR it could not fix from the client: the request-creation price
card with a €30.00 reward and a +€5.00 Boost said "Traveler receives €35.00" but
"Total sender cost €37.50". The Deal that request becomes owes €43.75. J6.3 puts the
Boost-inclusive total on the pricing contract, built by the functions an Offer and
a Deal already use, and the card prints it. No schema change, no accounting change,
no change to how an Offer or a Deal is frozen or funded.

---

## 1. Root cause

The pricing quote (`POST /api/parcels/pricing-quote` and
`GET /api/parcels/<id>/pricing`) published two separate things:

* `chosen_economics` — the **base** economics for the chosen reward: reward,
  delivery commission, base sender total (`calculate_offer_economics`);
* `boost` — the Boost priced on its own (`calculate_boost_reward`), plus
  `total_offered_reward_eur_cents` = chosen reward + Boost.

Nothing on the response was the sender's whole obligation. The card took "Traveler
receives" from the Boost block (Boost-inclusive) and "Total sender cost" from
`chosen_economics` (base-only), so the two lines on one card described different
things. Summing the blocks in Dart would have been client-derived money, which the
product rules forbid.

Three further defects sat on the same path and are fixed here because they touch the
same figure:

1. **The deposit screen measured against the wrong total.** "Pay in full", the
   custom-amount ceiling and "Remaining balance at delivery" all used
   `estimated_sender_total_eur_cents` — the *recommended* base total the deposit
   recommendation is built on. It ignores both the sender's chosen reward and the
   Boost. The server's real ceiling (`maximum_eur_cents`, from
   `maximum_chosen_deposit`) was on the response and unused. A €30.00 reward with a
   €5.00 Boost on a route recommending €20.00 offered "Pay in full (€25.00)" against
   a €43.75 obligation.
2. **Two mobile parsers read the recommendation clamp as a ceiling.**
   `PostingDepositQuote` and `DepositQuote` fell back from `maximum_eur_cents` to
   `max_eur_cents`, which is only the upper clamp on the *recommendation* (€7.00 by
   policy). Dormant until a screen used the ceiling — which item 1 now does — so it
   is closed first.
3. **`PricingBoostQuote` read keys the server never sends** (J6.2 note):
   `commission_fee_eur_cents`, `sender_total_boost_eur_cents`, … all parsed as €0.00,
   and an absent `total_offered_reward_eur_cents` parsed as €0.00 instead of absent.

## 2. The contract: `chosen_terms`

Additive. Both pricing endpoints now return a `chosen_terms` object beside the
fields they already had. Its names are the Offer's (J6.1) and the Deal terms' —
the same money at an earlier moment, read by one client vocabulary:

| Field (brief's name) | `chosen_terms` field | Meaning |
|---|---|---|
| base reward | `traveler_reward_minor` | The chosen base reward. |
| delivery fee | `platform_fee_minor` | ShipTrip's commission on the base reward. |
| base sender total | `sender_total_minor` | Base reward + delivery fee. |
| Boost | `boost_amount_minor` | The Boost. |
| — | `boost_traveler_bonus_minor` | The part the Traveler receives (all of it under J2). |
| Boost fee | `boost_platform_fee_minor` | ShipTrip's commission on the Boost, charged to the sender. |
| Traveler total | `traveler_total_minor` | Base reward + Boost bonus. |
| sender total with Boost | `sender_total_with_boost_minor` | Base total + Boost + Boost fee. |
| — | `commission_rate_bps`, `boost_economics_version`, `currency` | As on the Deal terms. |
| — | `terms_status` | `provisional`, `frozen` or `unavailable` (§4). |

All values are canonical EUR cents. The brief's illustrative `*_eur_cents` names
were not used for the same reason J6.1 gave: an Offer and a Deal already speak
`*_minor`, and the mobile `DealTerms` model parses exactly these keys, so the
request quote now parses through it too.

The deposit block of the **draft** quote gains `maximum_eur_cents`: the
Boost-inclusive obligation, equal to `chosen_terms.sender_total_with_boost_minor`,
or null before a reward is chosen. The saved request's deposit block already had it.

**Unchanged:** `chosen_economics` still means base economics; the `boost` block and
`total_offered_reward_eur_cents` are byte-identical; the deposit *recommendation*
is still built on the recommended base total, deliberately not on the Boost (J2).
No old field changed meaning.

## 3. Reuse of J2 economics — one computation, not three

No arithmetic was written for J6.3.

* `apps/matching/offer_economics.py` gained `build_terms(economics, boost)`: the one
  place a base-economics dict and a resolved Boost become an unsaved
  `DealTermsSnapshot`. `commitment_terms(offer, boost)` — what acceptance saves —
  now delegates to it, so acceptance, the J6.1 Offer projection and the request
  quote build the same row.
* `apps/matching/request_economics.py` (new) resolves the Boost through
  `resolve_committed_boost` (the J6.1 extraction acceptance calls) and reads
  `traveler_total_minor` and `sender_total_with_boost_minor` from the model's own
  properties. The base is the quote's existing `calculate_offer_economics` result —
  the function an Offer freezes.
* `maximum_chosen_deposit` (the deposit ceiling creation enforces) used to add
  `sender_total_minor + boost + boost fee` inline. It now reads the same
  `DealTermsSnapshot` property. Its fail-closed fallback — a policy that cannot
  price the Boost must not *raise* the cap — is preserved.

Rounding is therefore unchanged by construction: `ceil` to the platform on both the
delivery fee and the Boost fee, Traveler never reduced, integer cents only.

## 4. Draft, open and committed requests

**Draft** (`POST /api/parcels/pricing-quote`). No row exists. Inputs: places,
weight, dimensions, dates, `chosen_reward_eur_cents`, `boost_eur_cents`.
`terms_status` is `provisional`. Without a chosen reward it is `unavailable`, every
money field is null, and the deposit `maximum_eur_cents` is null.

**Open or awaiting deposit** (`GET /api/parcels/<id>/pricing`). The request's chosen
reward and current Boost under the active policy, `provisional`. A retired paid
package, if one is still unbound, is resolved exactly as acceptance resolves it
(`traveler_split_v1`), so the figure is the Offer's figure. (The deposit ceiling
continues to ignore a paid package, as before: the package was paid on its own
order and is not part of the balance a deposit pre-pays.)

**Committed** (matched and later). The request's own Boost column is not a record —
funding clears it — so the response reads the request's Deal terms and reports
`frozen`. Cancelled, expired and payment-failed Deals are skipped; a closed request
with no usable Deal, or with legacy/non-EUR terms, reports `unavailable` rather
than a figure built from columns that no longer mean anything.

## 5. Request → Offer → Deal consistency

Asserted end to end in `RequestOfferDealConsistencyTests`:

| Hop | Evidence |
|---|---|
| Draft quote → saved request | Same `chosen_terms` money and same deposit ceiling; the deposit endpoint's `maximum_eur_cents` agrees. |
| Request quote → proposed Offer | Every J6.1 total on the Offer equals `chosen_terms` (`boost_amount_minor`, `boost_traveler_bonus_minor`, `boost_platform_fee_minor`, `traveler_total_minor`, `sender_total_with_boost_minor`), plus base fee and base total. |
| Offer → Deal | Every one of those fields on the frozen `DealTermsSnapshot` equals the request quote, and the balance order amount equals `sender_total_with_boost_minor`. |
| After commitment | Request pricing reports `frozen` with the same figures; an Admin Boost-rate change afterwards does not reach it; funding clears the request Boost and the frozen figures stand. |
| Rate change before commitment | Quote, pending Offer and the Deal all move to the new rate together. |

Example, default 25% delivery and Boost commission, €20.00 chosen reward, €5.00
Boost: quote Traveler €25.00 / sender €31.25 → Offer €25.00 / €31.25 → Deal €25.00 /
€31.25, balance order €31.25. And for the brief's example, €30.00 and €5.00: €35.00
/ €43.75 at every step (draft test).

## 6. Admin rate changes

Unchanged J2 semantics. Before commitment every fresh quote reads the active
revision (tested: 25% → 10% Boost commission moves €1.25 to €0.50 and €43.75 to
€43.00). After acceptance the Deal's snapshot is immutable and the request pricing
reports it (`frozen`).

## 7. Deposit impact

* **Draft ceiling** = `sender_total_with_boost_minor`. Creation with that exact
  deposit succeeds; one cent more is refused and nothing is written (tested).
* **Saved ceiling** (`maximum_chosen_deposit`) = the same terms property.
* **Boost counted once.** The ceiling is the terms row's total; nothing adds a
  Boost or its fee to it a second time (tested at €5.00, €10.00 and €7.77 at 15%).
* **Minimum €3** and the recommendation band are untouched.
* **Deposit screen (mobile):** the hero is now "Your total for this delivery" = the
  server ceiling; "Pay in full", the custom-amount "more than the whole amount"
  check and "Remaining balance at delivery" measure against it. The recommended
  base total still appears, as "ShipTrip suggested total", in the guidance card it
  explains. When the server states no ceiling the screen falls back to the previous
  layout and shows no "Pay in full" and no remaining balance rather than guessing.

## 8. Mobile presentation

**Request creation card.** Every figure is a `chosen_terms` field, in the Offer and
Deal order and with their labels:

With a Boost (+€5.00):

| | |
|---|---|
| Base delivery reward | €30.00 |
| Boost bonus | €5.00 |
| **Traveler receives** | **€35.00** |
| ShipTrip fee | €7.50 |
| Boost fee | €1.25 |
| **You pay** | **€43.75** |
| Posting deposit | €3.75 |

Without a Boost: Traveler receives €30.00 · ShipTrip fee €7.50 · **You pay €37.50**
· Posting deposit. No "Boost €0" or "Boost fee €0" lines.

"Total sender cost" is retired from this card in favour of "You pay", the word the
Offer, Deal and payment screens use for the same number. Two new strings, in EN, FR
and AR: `depositWholeAmount` and `pricingUpdating`.

**No figure is computed in Dart.** `ChosenTerms` parses through `DealTerms` and
exposes getters only; `hasTotals` is false unless both totals are published, and
the card then shows no total at all rather than a base total standing in for one.
The `effectiveEconomics` getters (chosen-or-recommended base economics, the source
of the old base-only "total") were removed so nothing can reach for them again.

## 9. Quote refresh

* **Reward typing** keeps J3's 350 ms debounce: five keystrokes inside it cost one
  read (tested).
* **Boost chips** are discrete choices and price immediately; re-tapping the chosen
  chip costs nothing.
* **Latest wins.** Each read carries a sequence number and cancels the previous
  in-flight request; any answer for an earlier sequence — success or failure — is
  dropped. A slow +€5 answer landing after a quick "No Boost" answer can no longer
  put €43.75 on screen (tested; removing the guard fails the test).
* **Never a stale total.** The card remembers which reward and Boost it was priced
  for. While the form holds anything else the figures are dimmed, excluded from
  screen readers, and a thin progress bar announces "Updating the price".
* **Prefill.** The first quote has no chosen reward, so the screen prefills the
  recommendation — and now reads the quote once more for it. Previously the card
  kept the reward-less answer, whose `total_offered_reward_eur_cents` was absent and
  parsed as €0.00.

No polling and no J1.2 amplification: at most one request in flight, one per
settled edit.

## 10. Client-side money audit

Active mobile consumers of pricing totals, audited:

| Consumer | Before | After |
|---|---|---|
| Request creation card | base-only total as "Total sender cost" | `chosen_terms` totals |
| Deposit screen | recommended base total as ceiling / full / remaining | server `maximum_eur_cents` |
| `PostingDepositQuote`, `DepositQuote` | `max_eur_cents` fallback as ceiling | `maximum_eur_cents` only |
| `PricingBoostQuote` | wrong keys, €0.00 | real keys; absent is null |
| Request detail (`RequestPricing.boost.amount`) | Boost amount only | unchanged, correct |
| Offer / Deal / payment screens | J6.1 totals | unchanged |

Remaining client-side derivations, both pre-existing and outside the posting card,
recorded as MINOR (§12): the deposit screen's "Remaining balance at delivery" is
server obligation − the deposit the sender is typing, a live subtraction of a
number the server has not seen yet; and the Boost screen still estimates an
unsaved Boost's fee from the published rate, labelled as an estimate, until the
Boost is saved.

## 11. Tests

**Backend** — `apps/parcels/tests/test_phase_j63_request_boost_total.py`, 10 tests:
zero Boost; +€5.00 with old fields unchanged and the deposit ceiling; no chosen
reward; a 15% Boost rate with rounding (€7.77 → €1.17) separate from the delivery
rate (€30.01 → €7.51); reward and Boost changes; Admin rate change reaching a fresh
quote; draft ceiling = creation's enforced ceiling = saved request = deposit
endpoint; request quote → Offer → Deal → funding with a later rate change; a rate
change before commitment moving quote, Offer and Deal together; pricing denied to
the Traveler and an outsider.

**Mobile** — `test/phase_j63_request_boost_total_test.dart`, 21 tests: contract
parsing for zero, +€5.00 and a custom €7.77 Boost; an inconsistent server answer
shown as is (no recomputation), in the model and on screen; unavailable terms;
the recommendation clamp never read as a ceiling; the Boost block's real keys; the
card's exact lines and order for zero, +€5.00 and +€10.00 at 15%; prefill then one
more read; removing the Boost; re-tapping costs no read; a slow older answer never
replaces a newer one, with the updating state; typing debounced into one read with
the new totals; FR and AR on a small phone with locale formatting and RTL; the
deposit screen's full amount, remaining balance and ceiling moving with the Boost.

The screen is opened on its pricing step through a `@visibleForTesting`
`RequestCreatePricingSeed`, because reaching that step through the UI means
driving three date-and-time dials; the app never passes it.

**Visual check.** Rendered through the throwaway golden rig with real fonts (not
committed): EN +€5.00 and zero Boost at 411 px, AR +€5.00 on a 320 px phone, FR
+€5.00 at 1.3× text, and the deposit screen with a Boost-inclusive ceiling. The
breakdown adds up line by line in the stated order, Arabic mirrors with amounts on
the leading edge, French wraps labels without truncating an amount, and the
deposit screen reads "Your total for this delivery €43.75" / "Pay in full (€43.75)"
/ "Remaining balance at delivery €40.00".

**Mutation checks.** Removing the sequence guard and cancellation fails the
slow-answer test. Measuring the deposit screen from the suggested total again fails
both Boost-inclusive deposit tests. Making `maximum_chosen_deposit` return the base
total plus the Boost without its fee fails the draft-ceiling and the request → Offer
→ Deal backend tests.

**Totals (local, before CI).** Full backend suite on embedded PostgreSQL: 2,126
passed, 34 skipped, 0 failed (J6.2's 2,116 plus these 10), including the unchanged J2
Boost, retired-package, J2 posting, J6.1 projection, J6.2 signal and H5
reconciliation suites. `ruff check` clean, `makemigrations --check` no changes. Full
mobile suite 695 passed (674 + 21), `flutter analyze --fatal-infos` clean,
`dart format` clean, `l10n_untranslated.json` empty.

**Existing fixtures updated to the real wire shape:** the J3 contract test (which
asserted the recommendation clamp as `maximumDeposit` and fake Boost keys) and the
J3 deposit preset test (which had no `maximum_eur_cents`).

## 12. Findings

**BLOCKER** — none.

**MAJOR** — none remaining. J6.2's request-creation total MAJOR is closed, and the
deposit-screen ceiling defect found on the same path is closed with it.

**MINOR** — recorded, not fixed:

1. **Boost screen estimate.** While a sender moves the Boost amount on the Boost
   screen, the fee and cost are projected in Dart from the published rate and marked
   as an estimate until saved. The numbers agree with the server's rounding, but it
   is still client-derived. A draft Boost quote on `GET /api/parcels/<id>/pricing`
   would remove it.
2. **Deposit remaining balance** is obligation − typed deposit in Dart (§10).
3. **Form footer at small widths (pre-existing, seen in the renders).** The Back
   button wraps its label mid-word ("Ret / our", "رجو / ع") on a 320 px phone in
   Arabic and at 1.3× text in French. Not introduced here; not changed.
4. Carried from J6.2, untouched by request: the Go dispatcher does not relay the
   three `deal.arrival_*` channels; the J4 envelope total ignores a retired paid
   package.
