# Phase J6.1 — Offer Boost financial projection

Status: implemented, TEST only. Stripe TEST, Chargily TEST,
`PAYOUTS_DZD_EXECUTION_ENABLED` false, no LIVE provider activation and no
real-money operation.

Starting point: `a94cb97` (J6 PASS). Branch `claude/j61-offer-boost-projection`.

J6 found one MAJOR it could not fix from the client: the negotiation screen told a
Traveler deciding on an offer with a €30.00 base and a €5.00 Boost "You receive
€30.00", and told the Sender they pay €37.50 when they owe €43.75. J6.1 closes it
in the backend contract and renders the result. No schema change, no accounting
change, no change to how a Deal is frozen or funded.

---

## 1. Root cause

An `Offer` freezes the **base** economics when it is written —
`traveler_reward_minor`, `commission_rate_bps`, `platform_fee_minor`,
`sender_total_minor` — and nothing else. The Boost is not an offer property. It
lives on the delivery request (`DeliveryRequest.boost_eur_cents`), stays the
sender's to change while the request is open (J2), and is priced into
`DealTermsSnapshot` inside `_accept_offer_locked` and nowhere earlier.

So the offer serializer had no Boost to publish, and the one number a Traveler
accepts an offer on was the base reward. Two consequences, one visible and one
latent:

* **Visible:** every offer surface — negotiation hero, sender breakdown,
  acceptance dialog, Deliveries "Open offers" row, negotiation history —
  understated both sides whenever a Boost was set.
* **Latent race:** because acceptance read the request's *current* Boost, a
  Traveler could read an offer, the sender could change the Boost, and the Deal
  would freeze a figure the Traveler never saw. Nothing detected it.

## 2. The authoritative Offer economics

The offer now publishes the same numbers `DealTermsSnapshot` carries, under the
same names, beside the fields it already had:

| Field | Meaning |
|---|---|
| `traveler_reward_minor` | **Unchanged.** The base reward frozen on the offer. |
| `sender_total_minor` | **Unchanged.** Base reward + base commission. |
| `boost_amount_minor` | The Boost. |
| `boost_traveler_bonus_minor` | The part of it the Traveler receives (all of it under J2). |
| `boost_platform_fee_minor` | ShipTrip's commission on the Boost, charged to the sender. |
| `traveler_total_minor` | What the Traveler is paid: base + Boost bonus. |
| `sender_total_with_boost_minor` | What the sender owes: base total + Boost + Boost commission. |
| `boost_economics_version` | `additive_commission_v2` (J2) or `traveler_split_v1` (retired package). |
| `boost_terms_status` | `provisional`, `frozen` or `unavailable` — see §3. |

Names follow the existing contract rather than the brief's illustrative
`*_eur_cents` names: an Offer and a Deal are the same money at two moments, and
the Offer already speaks `*_minor`. A client renders both with one vocabulary,
and the mobile `DealTerms` model already parses exactly these keys.

**No second economics model exists.** The projection does not reimplement any
arithmetic. `apps/matching/offer_economics.py` builds the very
`DealTermsSnapshot` row acceptance would write — through the same
`resolve_committed_boost` acceptance calls — leaves it unsaved, and reads the
model's own `traveler_total_minor` and `sender_total_with_boost_minor`
properties. Acceptance saves that same row. "The figure shown" and "the figure
frozen" are one computation, not two that happen to agree.

`resolve_committed_boost` (new, `apps/boosts/services.py`) is the extraction of
the if/else that used to sit inline in acceptance: a bound retired paid package
wins and is `traveler_split_v1`; otherwise the request's J2 Boost is priced with
`calculate_boost_reward` under the active Phase 4 policy, read only when there is
a Boost to price. Behaviour is identical; it is now callable from two places.

## 3. Snapshot and freeze behaviour

J2's rule is unchanged: **the Boost freezes at acceptance and only there.** J6.1
does not move the freeze point to offer creation, because that would be a second
economics model — a sender who raised their Boost to attract a Traveler would see
it ignored by every open offer, and a Boost cut could leave a committed posting
deposit larger than the Deal it pre-pays, which is exactly what J2's
`boost_below_prepaid_deposit` exists to prevent.

`boost_terms_status` says which source a given offer's numbers come from:

**`provisional` — a pending offer on a pending match.** The numbers are what
accepting it *right now* would commit. The request's Boost is not frozen yet and
the sender may still change it, so these can change; the mobile screen says so in
one line ("Includes the sender's Boost of €5.00. The total is locked in when you
accept."). §4 is how the change is prevented from being silent.

**`frozen` — an accepted offer.** Read from `offer.deal.terms` and nothing else.
Never from the request: funding clears `boost_eur_cents` and an unfunded release
revives it, so the request column is not a record of what any Deal agreed.
Verified by funding a Deal and re-reading the accepted offer.

**`unavailable` — everything else.** A countered, declined, withdrawn or expired
offer; a legacy DZD offer; an accepted offer whose terms are legacy. No Boost was
ever recorded on such an offer, so none is invented. All seven projected fields
are null except the status; the base fields remain.

## 4. Concurrency — the Boost-edit race

The race: the sender edits their Boost while the Traveler accepts an offer.

The existing lock was already correct about *ordering*: `set_boost_intent` and
`_accept_offer_locked` both take the request row `FOR NO KEY UPDATE`, so one
commits first and the other reads its result. What was missing was any link
between what the acceptor *saw* and what acceptance *froze*.

J6.1 adds an optimistic confirmation on top of that lock:

1. `POST /api/offers/<id>/accept` takes an optional body:
   `{"traveler_total_minor": N, "sender_total_with_boost_minor": N}` — the totals
   the acceptor was shown.
2. Under the request lock, with the Boost purchase rows locked, acceptance
   resolves the committed Boost and builds the terms row **before creating the
   Deal**, then compares.
3. Any supplied total that differs refuses with **409
   `offer_economics_changed`** and `current_economics`. Nothing commits: no Deal,
   no allocation, no balance order, the request stays `open`, the offer stays
   `pending`, the Boost stays editable.
4. An offer that commits a Boost with **no** Traveler total confirmed refuses with
   **409 `offer_economics_confirmation_required`**.
5. After the Deal row exists, the retired-package bind is compared with the
   pre-Deal preview; a difference (an order turning paid in between) refuses with
   `offer_economics_changed` and the transaction rolls back.

Every ordering of the two writers now ends one of two ways:

| Order | Result |
|---|---|
| Traveler reads €35 → sender cuts to €0 → Traveler accepts confirming €35 | 409, nothing committed; screen re-reads €30 |
| Traveler reads €30 → sender adds €5 → Traveler accepts confirming €30 | 409, nothing committed; screen re-reads €35 |
| Traveler accepts confirming €35 → sender edits | acceptance commits €35; edit refused `boost_request_not_active` (J2) |
| Admin changes the Boost commission between read and accept | sender total differs → 409; re-read shows the new total |

"Traveler sees €35 → accepts → Deal freezes €30", and the reverse, are not
reachable through the API.

**Compatibility.** Both body fields are optional, so a client that sends nothing
is still well-formed. When there is no Boost such a client showed the base
reward, which *is* the whole reward, and acceptance proceeds exactly as before.
When there is a Boost, that client rendered a number that would not bind, and the
safe answer is to refuse — `offer_economics_confirmation_required` — rather than
commit it. Server-side callers of `accept_offer` (tests, internal services) pass
no confirmation and are not checked, which is why every J2 and H5 test still
calls acceptance unchanged. An idempotent replay on an already-accepted offer
returns the existing Deal as before, whatever it echoes.

No new lock was added and the canonical order is unchanged: request → matches →
offers → Boost purchases → journey → legs → eligibility → Deal → payment orders.
The only new read before the Deal exists is an **unlocked** read of retired
package payment orders, and only when such rows exist; locking them there would
have inverted the Deal → payment-order order.

## 5. API changes

All additive; no field changed meaning.

* **Offer representation** (`OfferSerializer` — match detail `latest_offer` /
  `accepted_offer`, match list, `GET /api/matches/<id>/offers`, propose, counter,
  decline and withdraw responses): the seven fields in §2.
* **`POST /api/offers/<id>/accept`**: optional body in §4; two new 409 codes.
* **Query cost.** The match list primes the retired-package read once for the
  whole page and joins `deal__terms` into its offer prefetch; the Phase 4 policy
  is read at most once per response and only if some pending offer has a Boost to
  price. A test asserts the list costs the same number of queries with one open
  negotiation as with four, each on a different boosted request.
* **Not changed:** `AdminOfferSerializer`, the Deal serializers, the J2 pricing and
  Boost endpoints, the J4 Find Travelers envelope, notifications.

### Authorization and privacy

Unchanged scope. The offer projection is served only where the offer already was:
to the match's sender and Traveler. An outsider receives 403 from match detail and
the offers list, an empty match list, and 403 on accept — all tested. Both parties
receive the same seven fields, which is the same exposure the Deal terms already
give both parties once the offer is accepted (`boost_amount_minor`,
`boost_platform_fee_minor`, `sender_total_with_boost_minor`), and the offer
already exposed `platform_fee_minor` and `sender_total_minor` to both. No provider
reference, payout detail, commission *rate* for the Boost, or settings
configuration is added. The Traveler already saw the request's Boost on the
traveler-side discovery payload (`boost_eur_cents`,
`total_offered_reward_eur_cents`).

### Notifications

Audited, unchanged. `offer.created`, `offer.updated` and `offer.accepted` carry
identifiers only; their push copy ("An offer needs your attention.", "Open
ShipTrip to review the changes.") names no amount, so there is no base-versus-total
choice to make.

## 6. Mobile changes

**`Offer` model.** Parses the seven fields. `amountFor(perspective)` now returns
`travelerTotal` / `senderTotalWithBoost` with **no fallback to the base** — that
fallback would be the original understatement. `hasBoost` and `hasTotals` read
server fields; nothing in Dart adds a Boost to a reward.

**Traveler, negotiation screen.** The hero is "You receive €35.00". With a Boost,
a two-line breakdown sits under it — "Base delivery reward €30.00", "Boost bonus
€5.00" — and the provisional note. With no Boost the screen is pixel-identical
to before: one hero, no breakdown, no Boost word anywhere (asserted).

**Sender, negotiation screen.** The same lines, in the same order, as the Deal
screen: Base delivery reward, Boost bonus, **Traveler receives €35.00**, ShipTrip
fee, ShipTrip boost share, **You pay €43.75**, then "Includes your Boost of €5.00,
locked in when this offer is accepted. Changing your Boost before then updates
this offer." With no Boost, the original three lines. An offer with no published
total shows Base delivery reward, ShipTrip fee and "Total before any Boost" —
never "You pay".

**Acceptance.** The dialog reads "Receive €35.00 for this delivery?" / "Pay €43.75
for this delivery?", and the request sends exactly the two totals the dialog
showed. `offer_economics_changed` and `offer_economics_confirmation_required` are
stale-state codes: the screen refreshes, and the snack says "The amounts on this
offer changed. Check the new figures before accepting." A test drives the whole
race: the Boost is removed while the dialog is open, the accept is refused, and
the hero re-renders at €30.00.

**Counter sheet.** The amount is always a base reward. With a Boost the field is
"Base delivery reward" and its helper names the Boost that is added on top — "The
sender's Boost of €5.00 is added on top of this." for a Traveler — so nobody
counters "€40" believing it is the whole payment.

**Offer history.** Past offers are closed and publish no total, so a row reads
"Sender's offer: base reward €30.00" instead of "You would receive €30.00".

**Deliveries, Open offers.** The row reads `amountFor`, so it now shows the total.
Compact, unchanged layout.

**Propose sheet (J5).** Two corrections so the sheet cannot contradict the offer
it sends:

* The Boost box ("Base €30.00 / Boost +€5.00 / Traveler receives €35.00") is the
  server's total for the request's *chosen* reward. It now shows only while the
  field still holds that reward. A different base would make its total wrong, and
  adding the Boost to the typed amount is not the client's to do; the "Your Boost
  of €5.00 is added on top of this." helper stays.
* The suggested-amount build-up prices the base only. With a Boost on the request
  its lines are now "Base delivery reward" and "Total before any Boost" instead of
  "Traveler receives" and "You pay".

Six new strings in EN, FR and AR; `l10n_untranslated.json` is empty.

**Visual check.** Rendered through the golden rig (not committed) at 390×844 in
English and Arabic, Traveler and Sender, Boost and no Boost: the €35.00 hero is
the dominant figure, the Sender breakdown adds up line by line, Arabic mirrors
correctly, and the zero-Boost Traveler screen is unchanged.

## 7. End-to-end consistency

The acceptance condition — proposal screen → submitted offer → Traveler offer
screen → accepted Deal all agree — is asserted across the stack:

| Hop | Evidence |
|---|---|
| Propose sheet → submitted offer | Backend: Find Travelers `request.total_offered_reward_eur_cents` == the proposed offer's `traveler_total_minor` at the chosen reward |
| Submitted offer → both parties' screens | Backend: identical projection for sender and Traveler across propose response, match detail, offers list and match list |
| Offer → Deal | Backend: every Boost field of the accepted offer == the Deal serializer's `terms`, for a J2 Boost, a counter accepted by the sender, and a retired paid package |
| Deal survives funding | Backend: funding clears the request Boost; the accepted offer still reports the frozen amount |
| Mobile | `amountFor` of a frozen offer == `DealTerms.totalFor` for both perspectives |

## 8. Historical compatibility

* **Legacy DZD offers** → `unavailable`, all projected fields null. Tested.
* **Closed V1 offers** → `unavailable`; base fields preserved. Tested for
  countered and declined.
* **Retired paid package on an open request** → projected as `traveler_split_v1`
  exactly as acceptance binds it: €7.77 package, €5.82 Traveler bonus, €1.95
  ShipTrip share, Traveler total €25.82, sender total €32.77, balance order still
  the €25.00 base total because the package was paid on its own order. Accepted,
  frozen, and compared field by field. Tested.
* **Pre-J2 Deals** keep their `traveler_split_v1` terms; an accepted offer reads
  them as they are.
* No stored row is rewritten, no migration runs, and `DealTermsSnapshot` rows are
  written with the same values as before.

## 9. Financial regression

No ledger, revenue-recognition, funding, payout, refund, settlement or Boost
commission code changed. Acceptance writes the same `DealTermsSnapshot` and the
same balance order (`sender_total + boost + boost fee` under J2, `sender_total`
under a retired package). The refactor moved the Boost resolution before the
Deal's creation and replaced three inline branches with one function; the write
order (Deal → package bind → terms → allocations → balance order) is unchanged.

The J2 suite (`apps/boosts/tests/test_j2_boost.py`: freeze, admin-rate change,
immutability after match, funding consumption, release revival, ledger
allocation, funded-cancellation refund, zero-Boost, replayed webhook), the retired
package suite (`apps/boosts/tests/test_boosts.py`: bind, payout, refunds) and the
H5 reconciliation regression (`apps/finance/tests/test_j2_h5_regression.py`) ran
unchanged and pass, inside the full backend suite.

A mutation check confirmed the new tests bite: with the confirmation call removed
from acceptance, four race tests fail.

## 10. Test evidence

**Backend** — `apps/matching/tests/test_phase_j61_offer_boost_projection.py`, 12
tests: zero Boost; positive Boost published identically to both parties across
five surfaces with outsider denial; propose-sheet total == offer total; Boost edit
before acceptance then freeze and survival past funding; Boost cut after read;
Boost added after read; commission change after read; unconfirmed accept with and
without a Boost plus idempotent replay and invalid body; sender accepting a
counter; closed offers; legacy DZD; retired paid package; constant list query
cost.

**Mobile** — `test/phase_j61_offer_boost_projection_test.dart`, 16 tests: contract
parsing; no base fallback; offer ↔ Deal totals; Traveler dominant total; Boost
breakdown; zero-Boost clean state; accept body; the refused-race refresh; counter
labelling; history wording; FR and AR RTL; Sender breakdown and dialog; Sender
zero-Boost; Sender base-only offer; propose sheet total visibility; propose sheet
base-only labels. `test/phase8ff3_money_perspective_test.dart` fixtures updated to
the J6.1 wire shape.

**Totals.** Full backend suite 2,111 passed, 34 skipped, 0 failed; full mobile
suite 653 passed; `ruff`, `flutter analyze --fatal-infos`, `dart format` clean; no
migration.

**CI and release.** Branch CI `35095380115` and main push CI `35097634293`, both
green on `31f8f40`, all six jobs. TEST Railway deployment
`eae6f929-5208-4c78-ac49-4412ec8c84ea` SUCCESS as `v1.0.0-rc.36+31f8f40`: healthz
200, readyz 200 with migrations `ok`, no migrations applied, all ten processes up,
only `RELEASE_ID` changed. APK `shiptrip-v1.0.0-rc.36-31f8f40-profile-arm64.apk`,
build run `35097732112`, SHA-256
`7449764591225bc0ef70886e2e0a98433585c519ba99121ef02d9582d4669aca`, 36,589,313
bytes, API origin `https://shiptrip-production-f7f7.up.railway.app`. Detail in
`docs/IMPLEMENTATION_STATUS.md`.

## 11. Findings

**BLOCKER** — none.

**MAJOR** — none remaining. J6's MAJOR (offer money projection has no Boost) is
closed.

**MINOR** — recorded, not fixed:

1. "ShipTrip boost share" (`moneyPlatformBoostRevenue`) is the retired
   split-model wording and is used on the Deal, payment and now offer screens. Under
   J2 the figure is a commission charged on top, which J6 renamed "ShipTrip fee"
   on the Boost screen. Kept here so the offer and Deal read identically; one copy
   change fixes all three.
2. The J4 Find Travelers envelope's `total_offered_reward_eur_cents` is `chosen
   reward + boost_eur_cents` and ignores a retired paid package. On such a request
   the propose sheet shows no Boost box while the submitted offer's total includes
   the package bonus. Legacy-only; the offer and Deal are correct.
3. A Boost edit does not push a live `offer.updated` to open negotiations, so a
   Traveler with the screen already open sees the new total on refresh or on the
   refused accept rather than immediately. Not silent — acceptance refuses — but a
   publish on `set_boost_intent` would remove the round trip. Left out to keep
   notification behaviour unchanged in this phase.
