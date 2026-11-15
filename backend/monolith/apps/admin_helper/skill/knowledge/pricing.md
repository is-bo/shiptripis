# Pricing and fees

Covers: how a delivery's price is built end to end (traveler reward, Wassla minimum, traveler's listed price, Wassla fee, boost, deposit, EUR to DZD display) and which of these settings an admin can change.
Related files: money.md, deliveries.md, trips-and-matching.md, settings-and-helper.md, problems-and-disputes.md

All money is stored in EUR cents. The numbers below are the defaults of the seeded settings; an admin can change some of them (see the last sections). Every offer and deal copies the numbers it used, so a later settings change never changes a price already agreed.

## What are the main price terms?
- Traveler reward: the amount the traveler earns for carrying the parcel. The sender proposes it first.
- Wassla fee (commission): added ON TOP of the reward. It is not taken out of the traveler's reward. The app says: "The traveler receives this full amount. The Wassla fee is added on top, not taken out of it."
- Sender total: reward + Wassla fee. This is what the sender pays.
- Wassla minimum: the lowest reward allowed for a given parcel and route. Enforced by the server.
- Recommended reward: a suggestion, never enforced.
- Listed price: the traveler's own price on a route (optional), shown pre-filled to the sender.
- Boost: extra reward the sender adds, goes whole to the traveler, with its own fee on top.
<!-- src: backend/monolith/apps/core/business_settings.py, matching/posting_pricing.py -->

## How is the Wassla fee calculated?
- Fee = reward x 25% (2,500 basis points), rounded UP to the next cent. Sender total = reward + fee.
- The 25% is the "commission" setting (Settings > "Commission, deposit and floors" > "Wassla commission (%)"). Changing it affects future offers only.
- Example: reward 13.33 EUR (1333 cents): fee = 333.25 -> 334 cents. Sender pays 16.67 EUR.
- Example: reward 30.00 EUR: fee 7.50, sender pays 37.50.
<!-- src: backend/monolith/apps/core/business_settings.py, core/migrations/0003_seed_v1_business_settings.py -->

## How is the Wassla minimum (lowest allowed reward) calculated?
Server-side, per parcel and per matched route:
1. Chargeable weight = the larger of actual weight and volumetric weight. Volumetric weight = length x width x height (cm) / 5,000. If no dimensions were entered, volumetric weight is 0. Then rounded UP to the next 0.5 kg step.
2. Distance base price by the matched distance:
   | Distance up to | Base |
   |---|---|
   | 100 km | 4.00 EUR |
   | 300 km | 6.00 EUR |
   | 750 km | 9.00 EUR |
   | 1,500 km | 12.00 EUR |
   | 3,000 km | 16.00 EUR |
   | 5,000 km | 20.00 EUR |
   | above 5,000 km | 24.00 EUR |
3. Weight part = chargeable kg x 2.50 EUR per kg (rounded up to the cent).
4. Calculated = base + weight part. Minimum = the larger of that and the global floor of 7.00 EUR.
- The detour and urgency amounts below are NOT part of the minimum; they only raise the recommendation.
- Worked example: 3 kg parcel, 30x20x15 cm (volumetric 1.8 kg, so 3.0 kg chargeable), 200 km: base 6.00 + 3 x 2.50 = 13.50 EUR. Minimum = 13.50 EUR.
- Worked example: 1 kg parcel, 50 km: 4.00 + 2.50 = 6.50, below the 7.00 floor, so minimum = 7.00 EUR.
- Worked example: 5 kg parcel measuring 60x40x40 cm: volumetric 19.2 kg, so chargeable 19.5 kg.
- Limits on a parcel: weight 0.01 to 100 kg; each side 0.01 to 500 cm; dimensions are all-or-none (length, width, height together or none).
<!-- src: backend/monolith/apps/matching/pricing.py, core/migrations/0004_seed_phase2_business_settings.py, parcels/models.py -->

## How is the recommended reward calculated?
- Recommended = minimum x 120% (rounded up to the cent) + detour amount + urgency amount, then rounded UP to the next 0.50 EUR, and never below the minimum.
- Detour amount: 0.25 EUR per km of extra distance the traveler must travel (rounded up). 0 at posting time.
- Urgency amount: depends on slack between the traveler's estimated arrival and the sender's deadline: 3.00 EUR if 1,440 minutes (24 h) or less; 1.50 EUR if 4,320 minutes (3 days) or less; otherwise 0.
- Worked example (continuing the 13.50 EUR minimum): 13.50 x 1.2 = 16.20 -> rounded up to 16.50 EUR recommended. Fee 25% = 4.13 (rounded up from 4.125). Sender total 20.63 EUR.
<!-- src: backend/monolith/apps/matching/pricing.py -->

## What price does the sender see when posting a request, and what is enforced?
- Before posting, the app asks the server for a quote: minimum, recommended and the chosen reward, each with "Traveler receives", "Wassla fee" and "Total sender cost". The app does no arithmetic itself.
- At posting time no journey exists yet. The estimate uses the straight-line distance between the pickup and delivery places and no detour. So the posting minimum is a lower bound; a real matched route can price higher.
- Urgency at posting time is measured from the end of the sender's ready window to the deadline. So a request whose deadline is 24 hours or less after its ready window ends gets the 3.00 EUR urgency amount in its recommendation (1.50 EUR for 3 days or less). It never changes the minimum.
- If a place has no coordinates the distance counts as 0, so the minimum falls to the lowest distance band (or the 7.00 EUR floor).
- The reward field is pre-filled with the recommended reward if empty. The sender can go above or below the recommendation.
- Refusal: a reward below the minimum is refused with code `price_below_minimum` ("The reward is below the minimum for this request."). The app shows "Offer must be at least {amount}".
- The reward the sender posts is only their intention (field `sender_proposed_reward_eur_cents`). The agreed reward is the one on the accepted offer.
- If the pricing settings cannot be read, posting prices fail with a 503 (service unavailable).
<!-- src: backend/monolith/apps/matching/posting_pricing.py, parcels/views.py, parcels/pricing_api.py -->

## What is the traveler's listed price (price per kg and minimum per parcel)?
- A traveler may set, on a route (journey), a price per kg and a minimum per parcel. Both or neither ("Set both a price per kg and a minimum per parcel, or neither."). It is optional; default is no price ("No price set. Senders propose their own amount.").
- The listed price for a given parcel = the largest of: (price per kg x chargeable weight, rounded up to the cent), the traveler's minimum per parcel, and the Wassla minimum for that match. The Wassla fee is then added on top, so the sender sees price plus fee.
- The listed result carries a "basis" saying which term won: `per_kg`, `traveler_minimum` or `wassla_minimum` (ties go to the traveler's terms first).
- Worked example: traveler lists 8.00 EUR/kg, minimum 15.00 EUR. Parcel 3 kg: 24.00 EUR (basis per_kg). Fee 6.00, sender total 30.00. A 1 kg parcel: 8.00 < 15.00, so 15.00 EUR (basis traveler_minimum), unless Wassla minimum is higher.
- It is a default, not a floor and not a ceiling. The sender sees it pre-filled ("Their price for this parcel", "Offer {amount}") and can tap "Offer a different amount". Any amount at or above the Wassla minimum is accepted. Below the listed price the app notes: "That is below their price, so they may decline or counter."
- Find Travelers can sort by "Lowest price" (listed price; unpriced journeys keep the normal order).
- The price can be changed while the journey is draft, pending verification, active or in progress. Otherwise: code `journey_price_not_editable`. A change applies only to offers made afterwards; existing offers and deals keep their amounts. Each change is logged.
- Limits (admin setting, Marketplace features): largest price per kg 100.00 EUR (min 1.00, max 1,000.00 on the form); largest minimum per parcel 500.00 EUR (max 10,000.00). Refusal code `journey_price_invalid` with reason `price_per_kg_above_maximum`, `min_price_above_maximum` or `price_incomplete` ("The price per kg is above the largest Wassla allows.").
- If the feature is switched off, a new price is refused with `traveler_pricing_disabled` ("Setting a price on a route is not available right now."), no listed price is shown, and clearing or re-sending an existing price still works.
- Only the journey owner can set it.
<!-- src: backend/monolith/apps/matching/listed_price.py, trips/pricing.py, core/marketplace_policy.py, mobile/lib/features/journeys/journey_price.dart, l10n/app_en.arb -->

## How does an offer, a counter-offer and acceptance affect price?
- The sender proposes first. A counter-offer may come from the other party (the one who did not propose the current offer). Each offer freezes reward, fee and sender total.
- The server re-prices the real matched sub-route and refuses a reward under the minimum: code `reward_below_minimum` ("Traveler reward must be at least {minimum} EUR cents for this match.").
- A pending offer shows the totals including the sender's current boost ("provisional"). If the sender changes the boost while an offer is open, the traveler is notified and acceptance refuses stale numbers with `offer_economics_changed` ("This offer's amounts changed. Review them before accepting."). The acceptor must confirm the total they were shown.
- Offers have a response deadline (setting, default on): 6 hours to answer, never after the pickup time; one reminder 1 hour before. Unanswered, it expires with nothing reserved or charged.
- At acceptance the numbers freeze into the deal. After that nobody can change them.
<!-- src: backend/monolith/apps/matching/v1_services.py, matching/offer_economics.py, core/marketplace_policy.py -->

## What is a boost, and how is it priced?
- A boost is extra reward the sender adds on a request. The traveler receives 100% of it. Wassla's fee on the boost is charged on top to the sender, at its own rate (default 25%, separate from the delivery commission), rounded up to the cent.
- Smallest boost 1.00 EUR, largest 1,000,000.00 EUR (100,000,000 cents). 0 means no boost. Refusals: `boost_amount_below_minimum`, `boost_amount_above_maximum` ("That boost is below the minimum." / "above the maximum.").
- Worked example: reward 24.00 EUR, boost 5.00 EUR. Boost fee = 1.25. Traveler gets 24.00 + 5.00 = 29.00. Sender pays 30.00 (reward + fee) + 5.00 + 1.25 = 36.25.
- Boost is not a timer or package. Its ranking effect lasts until the request's deadline, while the request is open for matching. The old paid visibility packages are retired: buying one answers `boost_package_retired`; old purchases only keep their effect until they expire.
- Editable only while the request is awaiting deposit or open, by the sender, before its deadline. After an offer is accepted: "This request's boost is no longer editable." (`boost_request_not_active`); after deadline `boost_request_expired`. If boosts are switched off: `boost_disabled` ("Boosts are not available at the moment.").
- Lowering a boost is refused if the posting deposit already paid would exceed the new total: `boost_below_prepaid_deposit`.
- In the app, a boost is added after publishing (presets +5 EUR, +10 EUR, custom). The server also accepts one at posting.
- Boost history (set, raised, lowered, removed, frozen, consumed, released) is recorded.
<!-- src: backend/monolith/apps/boosts/services.py, core/phase4_policy.py, parcels/pricing_api.py, l10n/app_en.arb -->

## How does a boost change ranking, and why can it not bypass compatibility?
- Compatibility (route, capacity, timing, verification, safety) is decided first. Ranking runs only on candidates that already passed; it refuses to rank an incompatible one. A boost cannot make an incompatible request compatible. The app says: "Only travelers who already match your parcel ever see it."
- Ranking weight = boost divided by 5.00 EUR, rounded up, minimum 1, maximum 30. Each weight point adds 25 score points, capped at 200 points total (reached at weight 8, i.e. any boost above 35.00 EUR; 35.00 EUR exactly is weight 7 = 175 points). The base score is about 0 to 1000.
- Boost never touches KYC, capacity, timing or safety.
<!-- src: backend/monolith/apps/core/phase4_policy.py, matching/ranking.py, boosts/services.py -->

## How do the total the sender pays and the traveler receives work with a boost?
- Traveler receives = reward + boost. (field `traveler_total_minor`)
- Wassla receives = reward fee + boost fee. (`platform_total_minor`)
- Sender pays = reward + reward fee + boost + boost fee. (`sender_total_with_boost_minor`) This is the amount of the deal's payment.
- Cancellation compensation uses only the base reward, not the boost.
<!-- src: backend/monolith/apps/deals/models.py, finance/settlement.py -->

## How does the posting deposit work?
- Default mode: sender pays a deposit up front to publish a request (status "Deposit needed" until paid). The setting `timing_mode` can be switched to pay-after-acceptance (then "No deposit needed").
- Recommended deposit = 10% of the recommended sender total (half-up rounding), kept between 3.00 and 7.00 EUR. It is based on the recommendation, not the sender's chosen reward and not the boost.
- The sender may choose their own amount: minimum 3.00 EUR, maximum = the whole sender total they will owe (chosen reward, fee, boost, boost fee). Refusals `deposit_below_minimum` ("That deposit is below the minimum."), `deposit_above_obligation` ("A deposit cannot exceed the amount it is paid against."). App presets: Minimum, Recommended, Pay in full, Custom.
- It is not an extra fee: when a traveler accepts, it is credited towards the sender total (credit = the smaller of deposit paid and amount owed). Remaining = sender total minus deposit.
- Worked example: recommended sender total 20.63 EUR -> 10% = 2.06 -> clamped up to 3.00 EUR.
- A deposit can be changed only while its order is untouched (pending, nothing paid, no open checkout): else "This deposit can no longer be changed." or `deposit_checkout_in_progress`.
- If the sender cancels the request, the deposit comes back ("Any deposit you paid comes back to you").
- If reward or boost is raised later after paying in full, extra balance can be due.
- Guest payer: someone else can pay an amount through a share link that only allows paying that amount (no access to the delivery). Link lifetime: 3 days (259,200 s, setting). Checkout attempt lifetime 1 hour (3,600 s, setting).
<!-- src: backend/monolith/apps/finance/services.py, finance/policy.py, core/migrations/0005_seed_phase3_payment_settings.py, 0010_seed_j2_boost_commission.py -->

## How does the DZD (Chargily) amount work?
- EUR is always the real amount. Stripe charges in EUR. Chargily charges in Algerian dinars (DZD) using a server-calculated conversion; the app shows "Rate: EUR 1 = {rate} DA" and "You'll be charged". The app never calculates it.
- DZD = EUR cents x rate / 100, rounded UP to a whole dinar (no fractions). The rate is a setting with 6 decimals. Example at a rate of 150 DZD per EUR: 30.00 EUR = 4,500 DZD; 30.01 EUR = 4,501.5 -> 4,502 DZD.
- The rate comes only from Wassla settings (admin types it, with a source or reason); there is no automatic rate feed. The seeded 150 DZD is a placeholder an operator must set before real use. Maximum accepted 100,000 DZD per EUR.
- A new rate applies only to Chargily attempts started afterwards. Each attempt keeps its own frozen rate and DZD amount; refunds use that frozen rate (full refund returns the exact dinars charged).
- Minimum Chargily charge 75 DZD; below that: "The converted amount is below the provider's minimum charge." (`amount_below_provider_minimum`).
- Default state: the shipped seed settings have Stripe, Chargily and new Chargily checkouts switched OFF until an admin enables them. The live values are on Settings > "Provider availability" (admins can change them: "Accept new Stripe payments", "Allow Chargily", "Accept new Chargily checkouts").
- DZD payouts to travelers also use a rate frozen at payout creation (rounded up whole dinars).
<!-- src: backend/monolith/apps/finance/money.py, finance/services.py, finance/policy.py, core/migrations/0008_seed_prelaunch_provider_settings.py, finance/payout_snapshots.py -->

## What does each person see, and where?
- Sender, posting: minimum, recommended, chosen reward, "Traveler receives", "Wassla fee", "Total sender cost", deposit guidance, boost breakdown (boost, boost fee, "You pay for the Boost").
- Sender, proposing to a traveler: listed price, "Use their price", "Use suggested" (recommended), total with boost.
- Traveler, on an offer: "You receive" / "Total you receive"; includes the sender's boost ("Includes the sender's boost of {amount}. The total is locked in when you accept").
- Deal money: "You pay", "Wassla fee", "Deposit already paid", "Remaining to pay", "Refund to you", "Traveler compensation".
- Staff: the console deal and export pages show traveler total, platform total, and sender total with boost.
<!-- src: backend/monolith/apps/deals/serializers.py, l10n/app_en.arb, admin_panel/exports.py -->

## Which price settings can an admin change, and where?
All in the admin console, Settings page. Each save creates a new audited settings version (needs a reason), affecting future offers/commitments only.
| Setting | Default | Where |
|---|---|---|
| Wassla commission | 25% | "Commission, deposit and floors" |
| Posting deposit % | 10% | same |
| Min / max posting deposit (recommendation band) | 3.00 / 7.00 EUR | same |
| Minimum Traveler reward (global floor) | 7.00 EUR | same |
| Weight rate per kg | 2.50 EUR | same |
| Recommendation multiplier | 120% (form allows 100 to 500) | same |
| Boost commission | 25% | "Boost commission" card (field "Wassla commission on boosts (%)", 0 to 100) |
| Chargily exchange rate | 150 DZD per EUR (placeholder) | "Chargily exchange rate" card (field "DZD for €1", plus "Rate source or reason") |
| Provider switches (Stripe, Chargily, new Chargily checkouts) | off in pre-launch seed | "Provider availability" |
| Let travelers set a price | on | "Discovery, routes, prices and proposals" (eyebrow "Marketplace features") |
| Largest price per kg / minimum per parcel | 100.00 / 500.00 EUR | same |
| Hours to answer a proposal / reminder before | 6 h / 1 h | same |
| Allow sea legs | off | same |
Stored in the settings but with no console form (some are shown read-only in the "Every guardrail in operator units" table): distance bands, urgency amounts, volumetric divisor (5,000), weight step (0.5 kg), rounding step (0.50 EUR), detour rate (0.25 EUR/km), smallest boost (1.00 EUR), largest boost (1,000,000.00 EUR), boost ranking step (5.00 EUR) and cap (30), boost points (25 per weight, 200 max), smallest sender-chosen deposit (3.00 EUR), Chargily minimum (75 DZD), payment timing mode. The only way to change these is a new settings version posted in full through the staff settings API (needs `manage_settings`, a written reason, and is audited). The Django admin page for settings versions is read-only.
- Distance bands cannot be made finer than the published privacy distance bands (activation is refused: `pricing_bands_reduce_location_privacy`).
- Fixed in code (not settings): ceiling rounding of fees, EUR as the canonical currency, deposit credit rule, boost goes whole to the traveler, "sender proposes first".
- If the active settings cannot be read, pricing fails closed (503), never guessing.
<!-- src: backend/monolith/apps/admin_panel/console_forms.py, admin_panel/views.py AdminSettingsView, core/admin.py, templates/admin/console/settings.html, core/policy_display.py, matching/policy.py -->

## Related price rules in other areas (summary)
- Late sender cancellation (inside 24 h of pickup): traveler compensation = 10% of the base reward (rounded up), at most 15.00 EUR; the rest is refunded. Platform takes nothing from it.
- Payout protection 48 hours after delivery; a dispute freezes payout. The traveler's payout equals reward + boost.
<!-- src: backend/monolith/apps/deals/cancellation.py, core/migrations/0006_seed_phase4_business_settings.py -->

## Not covered here
- The current live (production) values of every setting; only seeded defaults were confirmed.
- Exact refund and dispute split amounts (see cancellations and disputes files).
- How VAT, Stripe or Chargily provider fees, or customs are handled: not found in the pricing code.
- Whether any declared-value cap affects price: declared value is required and must be marked accurate, but no price effect was found.
