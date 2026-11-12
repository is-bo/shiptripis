# L4A: Traveler pricing, backend (contract)

Package L4A of `docs/WASSLA_DISCOVERY_PRO_PLAN.md`, built against `docs/WASSLA_DISCOVERY_PRO_SPEC.md`
section 8. Everything here is enforced by the server; the app renders what it is told and does no price
arithmetic. A journey without a price, and every journey while the switch is off, behaves exactly as
before.

## 1. What exists after L4A

- **A price on a journey.** Any traveler may set a price per kg and a minimum per parcel, in EUR
  cents, both or neither, on create, on a route edit, or through its own endpoint.
- **One formula.** `apps/matching/listed_price.py::listed_reward` turns that price and one request's
  pricing quote into the **listed price**: the largest of ceil(price per kg × chargeable weight), the
  traveler's minimum, and Wassla's minimum for the match. Fee and sender total come from
  `calculate_offer_economics` at the quote's commission rate.
- **Find Travelers shows it and sorts by it.** Each candidate's `economics` gains `listed`. A new sort
  `listed_price` puts the cheapest first and unpriced journeys last.
- **The trip card shows the price itself** (per kg and minimum), never a listed reward.
- **Offers stay negotiable.** `create_sender_offer` accepts exactly what it accepted before: any
  reward at or above Wassla's minimum. Every V1 offer's `terms_snapshot` records the listed price at
  that moment, for audit only.
- **An audit trail.** Every change of a journey's price writes a `trips.JourneyPriceChange` row.
- **Admin control.** The console's Marketplace features form sets the switch and the two typo-guard
  ceilings; the console journey page shows the price and its last five changes.

Nothing in counter, accept, boost, fee, deposit, checkout, refund, protection or payout changed.

## 2. Schema (all additive)

| Table | Change |
| --- | --- |
| `trips_journey` | `price_per_kg_eur_cents` (int, null), `min_price_eur_cents` (int, null). CHECK `journey_price_complete`: both null, or both set and at least 1 (with explicit `IS NOT NULL`, because a CHECK that evaluates to NULL passes). |
| `trips_journey_price_change` | New, append-only. `journey` (PROTECT), `actor` (PROTECT), `price_per_kg_eur_cents_before`, `min_price_eur_cents_before`, `price_per_kg_eur_cents_after`, `min_price_eur_cents_after` (all int, null), `created_at`. Index on journey and time. |

Migration: `trips/0010_l4a_traveler_pricing`. `backend/contracts/sql/schema.sql` is regenerated in the
same change.

## 3. Setting a price (`apps/trips/pricing.py`)

`check_price(new, current=)` is the one rule, run by the serializer for a clear 400 and again under the
journey lock by every write:

1. Both or neither, else `journey_price_invalid` / `price_incomplete`.
2. Clearing the price, or sending the price already stored, is always allowed, so turning the switch
   off (or tightening a bound) never traps a traveler's route edit.
3. Otherwise the switch must be on, else `traveler_pricing_disabled`.
4. Each part at most the policy ceiling, else `journey_price_invalid` with reason
   `price_per_kg_above_maximum` (and `max_price_per_kg_eur_cents`) or `min_price_above_maximum` (and
   `max_min_price_eur_cents`). Each part is at least 1 cent (field validation).

The switch and bounds are `marketplace.traveler_pricing` (`enabled` default true,
`max_price_per_kg_eur_cents` default 10,000, `max_min_price_eur_cents` default 50,000), read through
`traveler_pricing_policy()` at the moment of the action. An unreadable settings revision reads as off,
logged, exactly like the sea switch. The ceilings are applied when a price is set; a stored price is
never rewritten when staff lower them.

`apply_journey_price` stores the pair and appends the `JourneyPriceChange` row only when something
changed. Every caller holds the journey row lock, which is the lock every offer write takes first.

### Endpoints

| Method and path | Body | Answer |
| --- | --- | --- |
| `POST /api/journeys` | route, plus optional `price_per_kg_eur_cents` and `min_price_eur_cents` | 201 journey |
| `PATCH /api/journeys/<id>` | whole route; leaving the two price fields out **clears** the price, exactly as a left-out stop or category clears | 200 journey |
| `PATCH /api/journeys/<id>/pricing` | both keys required; explicit nulls clear | 200 journey |
| `GET /api/journeys/pricing-policy` | | `{"enabled", "currency": "EUR", "max_price_per_kg_eur_cents", "max_min_price_eur_cents"}`; the two ceilings are null when off |

`PATCH .../pricing` refusals are flat JSON: `journey_not_owned` 403; `journey_price_invalid` 400 (with
`reason`); `traveler_pricing_disabled` 409; `journey_price_not_editable` 409 (with `status`) when the
journey's lifecycle is completed, cancelled or expired. It is allowed for draft, pending verification,
active and in progress, paused or not, and whether or not the route itself is still editable (a pending
offer or a deal locks the route, never the price). Route-write refusals come from the serializer, so
DRF wraps each value in a one-element list, as for every route refusal since L3A.

### The journey payload

`JourneySerializer` gains `price`: `{"price_per_kg_eur_cents", "min_price_eur_cents"}` or null. The
owner always sees what they stored (so the editor can show it with the switch off). Anyone else sees it
only while the switch is on; the switch is read once per serializer, and only for a priced journey.

## 4. The listed price (`apps/matching/listed_price.py`)

```
listed_reward(journey, pricing_quote, *, enabled) -> ListedPrice | None
```

`None` when the switch is off, the journey has no price, or there is no quote. Otherwise:

```
weighted = ceil(price_per_kg_eur_cents × chargeable_weight_kg)   # chargeable weight from the quote
reward   = max(weighted, min_price_eur_cents, minimum_reward_eur_cents)
```

`basis` names the winning term: `per_kg`, `traveler_minimum` or `wassla_minimum`. On a tie the
traveler's own terms are named first (per kg, then their minimum). `economics` is
`calculate_offer_economics(reward)` at the quote's `commission_rate_bps`, so it is exactly what an offer
of that reward freezes.

`evaluate_candidate` computes it for every compatible pair whose journey has a price, reading the
switch from the same settings revision that produced the quote (parsed, not queried), and stores it on
`CandidateEvaluation.listed`. Find Travelers, Matches on Home and offer creation therefore all read the
one answer.

The public block (Find Travelers and offer snapshots):

```
{"reward_eur_cents", "economics": {traveler_reward_minor, commission_rate_bps,
  platform_fee_minor, sender_total_minor}, "price_per_kg_eur_cents", "min_price_eur_cents", "basis"}
```

## 5. Find Travelers

- `results[].economics.listed`: the block above, or null.
- `sort=listed_price`: lowest listed reward first, then every unpriced journey. The sort is stable over
  the authoritative best-match order, so equal prices and unpriced rows keep best-match order and a
  page boundary is as deterministic as before. With the switch off it equals best match.
- Query count is unchanged: the price lives on the journey row the scan already loads, and the switch
  comes from the policy row the scan already holds (test: pricing every journey adds no query).

## 6. The discovery trip card

`price`: `{"price_per_kg_eur_cents", "min_price_eur_cents"}` or null (no price, or switch off). A card
is about no parcel in particular, so it never carries a listed reward or economics. Used by
`/api/discovery/trips` and the person page.

## 7. Offers

- `create_sender_offer` is unchanged in what it accepts. An offer below Wassla's minimum is refused
  with `reward_below_minimum`, exactly as before; an offer below the listed price and at or above the
  minimum is accepted for negotiation, and the traveler may accept it.
- `Offer.terms_snapshot.listed_price`: the listed block computed under the journey lock at the moment
  of the offer, or null. Counter offers record it too (they go through the same `_v1_offer_values`).
  It is copied into the deal's terms snapshot with the rest. It is not part of the party-visible
  `public_terms_snapshot`.
- A price change touches no offer or deal: their snapshots are byte-identical afterwards (test).

## 8. Console

- Settings, Marketplace features: "Let travelers set a price", "Largest price per kg a traveler may
  set (€)", "Largest minimum per parcel a traveler may set (€)", saved with the other switches as one
  audited settings revision (`manage_settings`, reason required).
- Journey page: a "Traveler's price" card with the current price and the last five changes (who,
  from, to).
- Django admin: the two price fields are read-only on Journey (only the audited service writes them)
  and the change history is a read-only inline.

## 9. Tests

- `apps/matching/tests/test_l4a_listed_price.py` (26): the formula at every boundary (rounding up, an
  exact product, each term winning, ties, economics), Find Travelers' `listed` and `listed_price` sort,
  switch off and unreadable policy, no extra query, offers below Wassla's minimum refused as before,
  below the listed price accepted and acceptable, snapshots unchanged by a price change, counters, and
  the done-when equivalence: every stored amount of a funded deal at the listed price (offer, terms,
  payment orders, attempts, ledger) equals the same deal with the amount typed by hand; and on an
  in-progress journey with a funded deal and a pending offer, a price change leaves every offer, deal,
  terms, order, attempt, ledger and payout row identical while the next listing and offer use the new price.
- `apps/trips/tests/test_l4a_journey_price.py` (23): create, edit, both-or-neither, bounds, the switch,
  the endpoint, the audit trail, visibility, the database constraint, the trip card, and the console.
- Two existing tests rewritten to the new contract: the J4 economics key set gains `listed`, and the
  L2A marketplace form test expects the `traveler_pricing` section the form now saves.

Django: 2,654 passed before (integration branch at de7d538); 2,703 passed after (49 added, none removed).

## 10. Not done here (L4B and later)

- The app: "Your price" in the route editor and journey detail, the listed price on Find Travelers
  cards and its sort, the pre-filled propose sheet, and "from €X per kg, minimum €Y" on trip cards.
- `POST /api/matches/quote` and the traveler-side compatible-requests rows carry no listed price; the
  propose sheet reads it from the Find Travelers row.
