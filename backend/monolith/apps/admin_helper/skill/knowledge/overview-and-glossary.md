# Wassla overview and glossary

Covers: What Wassla is, who uses it, the core product rules, one delivery told end to end with the money, a glossary of every status word an admin meets, what is not in the app, and how the technical pieces fit.
Related files: pricing.md, money.md (payments, refunds, payouts), deliveries.md (deal lifecycle, handover codes), problems-and-disputes.md, trips-and-matching.md (journeys, offers), accounts-and-verification.md, admin-console.md (console pages, roles), settings-and-helper.md, app-walkthrough.md, messages-and-notices.md

## What is Wassla?

- Wassla (older code and docs say "ShipTrip") is a peer-to-peer parcel delivery marketplace.
- A sender posts a parcel (a "delivery request"). A traveler who is already making a trip (a flight, or a drive) offers to carry it. Wassla handles matching, price agreement, payment, a handover code, a protection period and the traveler's payout.
- The aim is fast, even same-day, delivery. "Same day" is a goal, not a rule: nothing in the app promises or enforces it. The sender sets a deadline and the app checks the traveler's arrival against it.
- V1 is delivery only. The market is EU to Algeria (and within each side). Platform entity is in France.
<!-- src: docs/SHIPTRIP_V1_SPEC.md header (hint only), backend/monolith/apps/trips/transport_rules.py -->

## Who are the actors?

| Actor | Who | Notes |
|---|---|---|
| Sender | A user who posts a parcel and pays | Needs an account. Email verification exists, but the code does not require a verified email before posting or paying. |
| Traveler | A user who posts a journey and carries parcels | Gets paid out. Can be asked for KYC (ID check) and flight proof. |
| Recipient | The person who receives the parcel | Needs NO account. Reached by email. Gives the delivery code to the traveler. |
| Guest payer | Someone other than the sender who pays through a shared link | No account. The link works for 3 days (259,200 s, a Settings value). The page speaks the reader's language. |
| Staff | Admins using the admin console | Five roles, below. |

Staff roles (slugs in brackets):
- Ops [`ops`]: requests, journeys, matches, deals, lifecycle, no-shows, disputes (manage, not resolve), boosts and ratings (view), provider health. Ops cannot open the users list.
- Support [`support`]: read-only on users, requests, journeys, deals, disputes, ratings, audit log; can handle cancellations.
- Finance [`finance`]: payments, refunds, payouts, reconciliation, exports, payout profiles and holds; can resolve disputes.
- Trust / Verification [`trust_verification`]: KYC, flight proofs, evidence, safety review, no-shows, payout identity, payout holds, managing disputes (not resolving), rating moderation, sensitive user data.
- Super Admin [`super_admin`]: every permission, including managing admins and settings.
<!-- src: backend/monolith/apps/admin_panel/permissions.py (fixed in code, not a setting), backend/monolith/apps/core/languages.py -->

## Which countries, languages and currencies?

- Countries: the app offers four launch countries for pickup, delivery and journey stops: Algeria, France, Spain and Germany (DZ, FR, ES, DE; fixed in the app's place picker). Road (drive) networks are declared for Algeria and for France/Spain/Germany together. Signup asks for no country, so nobody is blocked at signup by country.
- Flights are allowed between any places; any leg between Algeria and a non-Algerian country must be a flight. Drives are only inside one road network (Algeria; or France/Spain/Germany together).
- Languages: English (default), French, Arabic. The Flutter app supports all three, including right-to-left Arabic. Each user has a preferred language used for emails and messages. If a stored value is bad, English is used.
- Currencies: EUR is canonical. All marketplace money is stored as whole cents in EUR. Chargily (Algerian card / Edahabia payments) shows a DZD amount that the server converts from EUR. Seeded rate: 150 DZD per 1 EUR (setting `eur_dzd_rate_micros` = 150,000,000; an operator must keep it current). Minimum Chargily payment 75 DZD. Stripe is used for EUR card payments and EUR payouts.
- Old DZD rows exist from before V1 ("legacy DZD" offers and deals). They are history; new business is EUR.
<!-- src: apps/core/languages.py, apps/trips/transport_rules.py, apps/accounts/serializers.py (SignUpSerializer), mobile/lib/features/location/canonical_place_picker_screen.dart, apps/finance/policy.py, apps/core/migrations/0005_seed_phase3_payment_settings.py; settings: Payments > Chargily -->

## What are the main product rules?

1. EUR is the canonical currency (cents). DZD is only a display conversion at Chargily.
2. The sender proposes first. A traveler cannot start a deal by naming a price on a parcel; the sender makes an offer on a match, the traveler can accept, counter or decline.
3. Boost cannot bypass compatibility. A boost is only extra reward; it never makes an incompatible parcel/journey pair match.
4. Exact locations stay hidden until the deal is funded. Before that, parties see only coarse places and distance bands.
5. The delivery code belongs to the recipient. The traveler cannot retrieve it. After pickup the code is created "buffered" and nobody can see it for 30 minutes (1,800 s, a Settings value, frozen on the deal at funding). Then it is released and the recipient is emailed.
6. Payout protection window is 48 hours (172,800 s, Settings: Payments > Payout) after delivery is confirmed.
7. A dispute freezes the payout while it is `open`, `awaiting_evidence` or `under_review`.
8. Backend state is the truth. The app never shows payment, verification, delivery or payout success on its own.
9. Sea legs exist in code but are switched off by default (`sea_legs_enabled` = false).
<!-- src: apps/core/phase4_policy.py, apps/handover/services.py, apps/finance/policy.py, apps/disputes/models.py, apps/core/marketplace_policy.py -->

## How does one delivery go, with the money?

A worked example. Sender in Paris wants a parcel carried to Algiers. A traveler flies Paris to Algiers.

1. Traveler publishes a journey (legs, dates, optional price per kg). Publishing needs an approved identity check (KYC) and an approved ticket for every flight and ferry leg, so staff review those first (Verification pages). A published journey goes straight from `draft` to `active`.
2. Sender posts a delivery request. In the default mode a posting deposit is required first: the request stays `awaiting_deposit` and is not visible until the deposit is paid. The recommended deposit is 10% of the recommended sender total, clamped between 3.00 EUR and 7.00 EUR. The sender may instead choose any amount from 3.00 EUR up to the full amount owed (seeded Settings: Payments > Posting deposit).
3. Match and offer. Sender offers a reward, say 20.00 EUR. Wassla adds its commission on top: 25% (2,500 bps) rounded up to a cent = 5.00 EUR. Sender total = 25.00 EUR. The traveler's reward stays 20.00 EUR. Offers wait for an answer for 6 hours by default (or until pickup time if sooner).
4. Traveler accepts. A deal is created directly in `payment_required`. Terms are frozen (reward, fee, boost, rates). The traveler's space is held for 1 hour by default (3,600 s, Settings: reservation payment grace); if the deal is not paid by then the space is released.
5. Sender (or a guest payer) pays the deal balance by Stripe (EUR) or Chargily (DZD shown, converted from EUR). The posting deposit already paid is credited. When money is confirmed by the provider the deal becomes `funded`. Exact locations unlock.
6. Recipient details are set; deal becomes `pickup_ready`. Pickup cannot be confirmed before that. Sender gives the parcel to the traveler, who confirms pickup with the pickup code: `picked_up`, then at once `in_transit`. The delivery code is created `buffered`.
7. Travel: `in_transit`. The traveler can report leg progress (at the port, departed, arrived).
8. After the 30-minute buffer the delivery code is released; deal is `delivery_ready`. Recipient gives the code, traveler enters it: `delivery_confirmed`, then `protection_window`.
9. Either party can open a dispute from pickup until the 48-hour protection ends (staff cannot open one). If none is open at the end, the deal is `completed` and the payout becomes eligible. Traveler gets 20.00 EUR (plus any boost); Wassla keeps the 5.00 EUR fee.
10. Payout goes to the traveler by Stripe transfer (EUR) or a manual settlement (e.g. DZD by CCP/RIP) that finance records. Automatic Stripe payout is off by default (`auto_stripe_enabled` false).
- Cancel or dispute paths: refund to the sender (full, partial or none), see the disputes and cancellation files.
- Boost example: boost of 10.00 EUR, Boost commission 25% = 2.50 EUR (its own Settings value, seeded equal to the base 25%). Traveler gets the whole 10.00 EUR extra; sender pays 12.50 EUR extra.
<!-- src: apps/core/business_settings.py (fee = ceil(reward x bps / 10000)), apps/matching/v1_services.py (deal created in payment_required, payment grace), apps/deals/lifecycle.py, apps/disputes/services.py (_assert_dispute_window_open), apps/trips/services.py (publish), apps/finance/policy.py, apps/core/migrations/0004, 0006, 0010 -->

## Glossary: deal statuses (`Deal.status`)

| Code | Meaning |
|---|---|
| `offer_accepted` | Exists in the status list, but a new deal is created straight in `payment_required`. |
| `payment_required` | Waiting for the sender (or guest) to pay the balance. |
| `funded` | Provider confirmed the money. Exact locations unlocked. |
| `pickup_ready` | Recipient details are on file; ready for pickup. |
| `picked_up` | Traveler confirmed pickup with the pickup code. |
| `in_transit` | Parcel is travelling. |
| `delivery_ready` | Delivery code is released; waiting for the handover. |
| `delivery_confirmed` | Recipient code accepted; parcel delivered. |
| `protection_window` | 48-hour hold after delivery; disputes allowed; payout not yet eligible. |
| `completed` | Closed normally; payout may be released. |
| `cancelled` | Deal cancelled. |
| `expired` | Not paid or not progressed in time. |
| `payment_failed` | In the status list but never set by any code: a failed payment leaves the deal in `payment_required` so the sender can retry. |
| `disputed` | A dispute is active; money frozen. |
| `refunded` / `partially_refunded` | Money went back to the sender in full or in part. |

Other statuses:
- Delivery request: `awaiting_deposit`, `open`, `matched`, `in_transit`, `delivered`, `completed`, `cancelled`, `expired`.
- Match: `pending`, `accepted`, `in_transit`, `delivered`, `completed`, `cancelled`, `expired`.
- Offer: `pending`, `countered`, `accepted`, `declined`, `withdrawn`, `expired`. Proposed by `sender` or `traveler`.
- Deal leg allocation (one slice of a deal per leg): `pending_payment`, `funded`, `in_transit`, `released`, `completed`, `cancelled`.
- Early arrival report on a deal: `pending_confirmation` (sender must answer), `confirmed`, `declined`. It never moves money or the delivery code.
- Boost today is a plain extra reward amount on the request (smallest non-zero Boost 1.00 EUR, Settings: boost). It has no status, timer or expiry of its own; it is frozen into the deal when an offer is accepted.
- There is no paid boost and no visibility package to buy.
<!-- src: apps/deals/models.py, apps/parcels/models.py, apps/matching/models.py, apps/boosts/models.py (module docstring), apps/core/migrations/0010_seed_j2_boost_commission.py -->

## Glossary: journeys and legs

- Journey: the traveler's whole trip, made of ordered legs (at most 20). Statuses: `draft`, `pending_verification` (in the list, but current code never moves a journey into it), `active` (live), `in_progress`, `completed`, `cancelled`, `expired`.
- Leg: one hop of a journey. Mode: `FLIGHT`, `DRIVE` or `SEA` (sea is off by default; refusal wording "sea legs are not available at the moment").
- Leg progress report: `at_port`, `departed`, `arrived`, given by the traveler or staff. It moves no money and no deal status; it is copied to the deal timeline.
- Proof (flight proof): evidence a leg is real. Status `pending`, `approved`, `rejected`; resubmitting keeps history. Reviewed in the console at Verification > flight proofs.
- Schedule change: the traveler changes times. Statuses `pending_senders`, `applied`, `withdrawn`. Each sender answers `pending`, `accepted`, `declined`. Needed when the new arrival misses the deadline (`deadline`), moves the arrival by more than 360 minutes (`shift`), or moves the pickup (`pickup`). 360 min is a Settings value (marketplace > route change).
- Legacy trip (`Trip`): older single-trip model with `draft`, `active`, `in_transit`, `delivered`, `completed`, `cancelled`. Journeys replace it.
- Leg reminders: traveler nudged 30 min after planned departure, 60 min after planned arrival, repeat every 180 min, max 2 repeats (Settings: marketplace > reminders). Only for legs carrying a funded parcel.
<!-- src: apps/trips/models.py, apps/trips/services.py, apps/trips/progress.py, apps/core/marketplace_policy.py -->

## Glossary: money terms

| Term | Meaning |
|---|---|
| Payment order | One amount to collect. Purpose: `posting_deposit`, `deal_balance` (`boost` exists but is not used). Status: `pending`, `partially_paid`, `paid`, `refund_pending`, `partially_refunded`, `refunded`, `cancelled`. |
| Payment attempt | One try to pay an order at a provider. `created`, `checkout_pending`, `processing`, `succeeded`, `failed`, `expired`, `cancelled`. Checkout attempt lives 3600 s (Settings: Payments > Checkout). |
| Provider | Stripe (EUR cards), Chargily (Algerian cards / Edahabia, DZD). A mock provider exists for tests only and is forbidden in production. |
| Refund | Money back. Status `pending`, `processing`, `succeeded`, `failed`. Reasons: request expired unmatched, sender cancelled before acceptance, payment could not be applied, deal cancelled before funding, administrative, deal cancelled after funding, dispute resolution, verified no-show. |
| Ledger | Append-only money journal. Entry kinds: customer payment, deposit credit, deal funding, boost allocation, refund, payout, correction. |
| Payout | What the traveler receives. Statuses below. |
| Payout method | How a traveler is paid: Stripe connected account or manual settlement. Status `setup_required`, `pending_review`, `ready`, `needs_attention`, `unavailable`, `disabled`. |
| Hold | Money locked for a deal (sender's funds in escrow until release or refund). Old wallet model: `open`, `released`, `reversed`. Also "payout hold" = finance blocks a payout manually. |
| Protection window | The 48 h after delivery confirmation before the payout can be released. |
| Reconciliation | Checking Wassla's records match what Stripe/Chargily say, and fixing differences. Runs as background jobs (provider reconcile, refund reconcile, payout reconcile). |
| Commission | Wassla fee charged on top of the reward (25% seeded, rounded up to a cent). |
| Posting deposit | Upfront payment when a request is posted; credited to the deal later; refunded if the request expires unmatched. |
| Cancellation compensation | If the sender cancels within 24 h of pickup (86,400 s), traveler may get 10% (1000 bps) capped at 15.00 EUR (seeded Settings: cancellation). |

Payout statuses (`Payout.status`):
- `not_eligible`: protection window still open.
- `frozen`: an active dispute holds the money.
- `blocked`: blocked by finance or a failed check.
- `eligible`: window passed, no dispute, books reconcile.
- `scheduled`, `processing`: queued or in flight.
- `sent`: the transfer was made but is not yet settled. For a manual (DZD) payout, finance recorded the transfer with a receipt but did not yet attest it as completed. The traveler's app also shows "On the way" while a Stripe bank payout is in transit.
- `paid`: settled. For a manual payout, finance attested the transfer as completed and the payout was written to the ledger. A genuine bank return can still move `paid` to `failed`.
- `failed`, `cancelled`.
Payout method kinds: `stripe_transfer`, `manual`, `undecided`.
Stripe disbursement (the bank leg of a Stripe payout): `planned`, `committed`, `unknown`, `pending`, `in_transit`, `paid`, `failed`, `canceled`, `returned` (returned after paid).
<!-- src: apps/finance/models.py, apps/finance/payout_models.py, apps/finance/payout_manual.py (confirm), apps/finance/payout_domain.py, apps/finance/payout_mobile.py, apps/core/phase4_policy.py -->

## Glossary: disputes, problems, handover

- Dispute statuses: `open`, `awaiting_evidence`, `under_review`, `resolved`, `closed`. The first three freeze the payout.
- Dispute categories: `not_delivered`, `damaged`, `wrong_item`, `late`, `no_show`, `payment`, `other`.
- Dispute opened by: `sender`, `traveler` or `admin`.
- Dispute resolutions: `full_sender_refund`, `full_traveler_payout`, `partial_split` (fee mode "proportional").
- Evidence kinds: `text`, `photo`, `video`. Up to 20 items and 25 MB each (26,214,400 bytes) by default (Settings: disputes).
- Problem (shipment problem): a lighter report on a deal. Kinds: `sender_unavailable`, `traveler_no_show`, `recipient_unavailable`, `parcel_mismatch`, `parcel_damaged`, `trip_disrupted`, `customs_delay`, `other`. Status: `open`, `escalated` (in front of staff), `acknowledged`, `closed`. Damaged, mismatch and both no-show kinds go to staff at once. A no-show can only be reported on a funded deal from the agreed pickup time until pickup is confirmed, and only once staff have not already recorded one.
- No-show: one party did not turn up. Staff record who (`sender` or `traveler`); there is no automatic risk scoring. A verified traveler no-show refunds the sender in full by default (staff can override).
- Handover code: pickup code (sender to traveler) and delivery code (recipient to traveler). Length 8 (Crockford base32), 5 wrong tries lock it for 900 s, up to 3 lockouts, then it locks; also at most 12 tries per hour (Settings: handover). Only the sender can ask for a new code. Statuses: `buffered`, `active`, `used`, `locked`, `superseded` (replaced by a rotation), `cancelled`. Attempt results: `succeeded`, `mismatch`, `not_available`, `locked`, `rate_limited`, `not_authorized`, `wrong_state`.
- Ratings: reviews can be left for 14 days (1,209,600 s), comment up to 1000 chars; ratings are revealed by a background job.
<!-- src: apps/disputes/models.py, apps/problems/models.py, apps/problems/services.py (no_show_window), apps/deals/cancellation.py (record_no_show), apps/handover/models.py, apps/core/phase4_policy.py, apps/core/migrations/0006 -->

## Glossary: other terms

- Tracking number: a parcel id like `WSL-7K3M9QXD` ("WSL-" plus 8 characters; no 0, 1, I, L, O, U). Random, identifies a parcel, never grants access. Users may type it in any case, with or without "WSL-".
- Boost: the sender's extra reward on a request to attract a traveler. Traveler receives all of it; commission 25% is added on top. It never overrides compatibility.
- Compatibility: whether a parcel fits a journey (route, dates, weight, deadline). Stored as an immutable snapshot on the match.
- Listed price: the pre-filled reward = the largest of traveler price per kg x chargeable weight (rounded up), the traveler's minimum per parcel, and Wassla's minimum. It is a default, not a floor.
- Recommended / minimum / chosen reward: Wassla suggests; the sender may go above or below the suggestion but never below the minimum.
- Business settings revision: the versioned Settings the admin console edits. Each deal freezes the values it uses, so later changes do not affect it.
- Scheduled job (obligation): a durable background task (expiries, reminders, payout release, notifications). Statuses `pending`, `running`, `succeeded`, `failed`, `cancelled`.
- KYC: ID check for travelers. Document types `id_card`, `passport`, `driving_license`. Statuses `pending`, `approved`, `rejected`, `expired`.
- AI helper: the admin assistant. Calls are logged and pruned; prepared changes expire.
<!-- src: apps/parcels/tracking.py, apps/matching/listed_price.py, apps/kyc/models.py, apps/finance/models.py -->

## What is NOT in the app?

- Professional transporters and courier handoff: not in the app.
- Kaba / ProductRequest (traveler buys a product): retired in V1. The old model still sits in code but is not an active feature.
- Sea legs: coded but off by default.
- Old wallet, payments and verification modules (DZD wallet, mock payment intents, match-based handover codes) are not routed in the API; the active money system is the finance module.
- Dynamic surge pricing: none. The suggested price has only a fixed urgency add-on for tight deadlines (see the pricing file).
- Vehicle or transport proof for drive legs: none. Only flight and ferry legs need a ticket proof.
- Staff screen to read chat messages: none.

## How do the technical pieces fit?

- Repository layout: `backend/monolith` (Django), `backend/services` (Go), `mobile` (Flutter app), `web` (static landing site), `docs`, `infra`.
- Django monolith: the brain. Holds all rules, money, deals, admin console and the AI helper API. Source of truth is PostgreSQL.
- Go services: three small helpers (notifications, chat, KYC), plus an email worker. They listen to events Django publishes through Redis; if they are down, Django still works.
- Flutter app: iOS and Android, three languages. Main tabs: Home, Deliveries, Chat, Profile. Notifications live in the header bell. Travelers see My Trips and Carrying inside Deliveries.
- Landing site: static pages (home, terms, privacy, prohibited items, support) in en, fr, ar.
- Admin console: Django pages (overview, AI helper, users, verification (KYC, flight proofs), trust > reviews, requests, journeys, deals, disputes, problem reports, payments, refunds, payouts, ledger, finance dashboard, payouts hub, manual DZD, exceptions, exports, staff, settings, system (jobs, email, geography), audit log, two-step login).
<!-- src: ARCHITECTURE.md, apps/trips/transport_rules.py, apps/matching/pricing.py, backend/services/HANDOVER.md, backend/monolith/config/urls.py, apps/admin_panel/console_urls.py, mobile/lib/features, CLAUDE.md -->

## Not covered here

- Cancellation rules per deal state (see the deals and problems-and-disputes files).
- The full pricing formula for the Wassla minimum and distance bands (see the pricing file).
