# The life of a delivery

Covers: how a parcel request is created, proposed, accepted, paid, picked up, handed over, completed or cancelled, with every status, time window, code rule and who sees what.
Related files: pricing.md, money.md, problems-and-disputes.md, trips-and-matching.md, messages-and-notices.md, admin-console.md, settings-and-helper.md

Words used here: the sender posts a parcel request. The traveler carries it on a journey. A "deal" is created when a proposal is accepted. The recipient is the person who receives the parcel; they need no account.

## What are the steps of a delivery, start to finish?
1. Sender posts a parcel request (status `open`, or `awaiting_deposit` first if a posting deposit is required).
2. Sender proposes a price to a traveler (the sender always proposes first). Traveler accepts, declines, or counters.
3. When an offer is accepted a deal is created (`payment_required`) and the traveler's space is reserved for a payment grace period.
4. Sender pays. Deal becomes `funded`. Exact addresses are revealed to the traveler. Sender gets a pickup code.
5. Sender records the recipient (name and email). Deal becomes `pickup_ready`.
6. At pickup the traveler types the sender's pickup code. Deal becomes `in_transit`. A 30-minute safety wait starts.
7. After 30 minutes the delivery code is released: the recipient is emailed it, the sender can see it. Deal becomes `delivery_ready`.
8. At handover the recipient tells the traveler the code and the traveler types it. Deal becomes `delivery_confirmed`, then `protection_window` (48 hours).
9. If nobody disputes, the protection window ends and the deal becomes `completed`; the traveler's payout becomes eligible (see money.md).
<!-- src: backend/monolith/apps/deals/lifecycle.py, handover/services.py, matching/v1_services.py -->

## How does a sender create a parcel request? What is required?
Every request needs all of these (the server refuses otherwise):
- Pickup place and delivery place: an active locality or airport from the catalogue. They must differ. A place that cannot be matched is refused: "This place is temporarily unavailable for matching."
- Ready window start and end (start before end), and a deadline (at or after the window end, and in the future). Errors: "Ready window end must be after its start.", "Deadline must be at or after the ready window end.", "Deadline must be in the future."
- Weight: 0.01 to 100 kg.
- Declared value: 0 to 100,000,000 EUR cents.
- Sender's proposed reward for the traveler: 1 to 100,000,000 EUR cents. It is only the sender's intent, not a price; the agreed price is on the offer.
- Title (max 160 characters), description (max 2000), category (documents, small_box, electronics, clothing, other).
- One photo of the item (required). It is uploaded first, then used by the create call. JPEG, PNG or WebP only, max 10 MiB.
- Five declarations, all must be ticked: description accurate, item legal, no prohibited goods, declared value accurate, customs responsibilities understood. Refusal: "This safety declaration must be confirmed."
Optional:
- Length, width, height: 0.01 to 500 cm each, all three or none. Refusal: "Enter length, width and height together, or leave all three empty."
- Handling notes (max 2000), fragile flag.
- Preferred pickup/drop-off point (a saved location of the sender, inside the chosen place).
- Boost (extra reward, see pricing.md).
- Target traveler: makes the request private to one traveler (a sender cannot target themselves). A private request is not listed, and only the sender and that traveler can open it ("This targeted request is private.").
- Posting deposit amount (otherwise the server recommends one).
Not allowed: extra unknown fields ("This field is not accepted by the V1 delivery contract.").
<!-- src: backend/monolith/apps/parcels/serializers.py, parcels/views.py -->

## Which items are prohibited?
- The server has no list of prohibited items and does not check contents. The control is the sender's five declarations ("no prohibited goods", "item is legal", "customs responsibilities understood" and the others above). Item categories are only the five above.
- In the app, the posting form has a "See what can't be sent" link. It opens a sheet that only repeats "It contains no prohibited goods"; it shows no list.
- The public website has a draft "Prohibited items & acceptable use" page (marked "Review required before launch"). Never send: weapons, explosives, ammunition or items meant to harm people; illegal drugs, controlled substances or counterfeit goods; live animals, human remains, biological or hazardous materials; stolen goods, cash equivalents, or items meant to evade customs or sanctions; anything banned by the law of the departure, transit or arrival country, or by the airline, carrier or airport.
<!-- src: backend/monolith/apps/parcels/serializers.py, mobile/lib/features/requests/request_create_screen.dart, l10n/app_en.arb, web/prohibited-items.html -->

## Is there a minimum reward? What if the sender picks too little?
Yes. The reward may be above or below the recommended price, but never below the platform minimum for that route and weight. If lower, the create call is refused (HTTP 400) with code `price_below_minimum` ("The reward is below the minimum for this request."), the `minimum_reward_eur_cents` and the `recommended_reward_eur_cents`. The app shows "Offer must be at least {amount}". The minimum and recommendation are calculated in pricing.md. The app shows a price quote before posting.
<!-- src: backend/monolith/apps/parcels/views.py, parcels/urls.py (parcels/pricing-quote) -->

## What are the parcel request statuses?
| Status | Meaning |
|---|---|
| `awaiting_deposit` | Created but the posting deposit is not paid. Not visible to travelers, cannot be proposed on. |
| `open` | Published. Travelers can see it and the sender can propose. |
| `matched` | An offer was accepted; waiting for payment or pickup. |
| `in_transit` | Parcel picked up. |
| `delivered` | Delivery confirmed (protection window). |
| `completed` | Deal completed. |
| `cancelled` | Cancelled by the sender, or the deal was cancelled/refunded after funding. |
| `expired` | Nobody took it before the deadline (see below). |
The status shown is worked out from the latest deal: no deal = the request's own status; deal `payment_required`, `funded`, `pickup_ready`, `payment_failed` or `disputed` before pickup = `matched`; `picked_up`, `in_transit`, `delivery_ready` (or pickup confirmed) = `in_transit`; `delivery_confirmed`, `protection_window` (or delivery confirmed) = `delivered`; `completed` = `completed`; `cancelled`, `expired`, `refunded`, `partially_refunded` = `cancelled`. Exception: a deal that was cancelled or expired BEFORE funding (and before pickup) sends the request back to `open`. A request already stored as `cancelled` or `expired` stays so.
<!-- src: backend/monolith/apps/parcels/lifecycle.py, parcels/models.py -->

## Is a posting deposit needed?
It depends on the payment setting "timing mode" (`payments.timing_mode`, no console form). The seeded default is `posting_deposit`: the request starts as `awaiting_deposit` and becomes `open` only after a confirmed payment (the app never decides that itself). The other mode, `after_acceptance`, needs no deposit (app: "No deposit needed"). Recommended deposit: 10% of the recommended sender total, kept between EUR 3.00 and EUR 7.00; the sender may choose from EUR 3.00 up to the whole amount owed. The console Settings card "Commission, deposit and floors" has "Posting deposit (%)", "Minimum posting deposit (€)", "Maximum posting deposit (€)" (admins can change them). The deposit is credited against the deal balance when an offer is accepted. If the request ends unmatched or is cancelled, the deposit is refunded. See money.md and pricing.md.
<!-- src: backend/monolith/apps/core/migrations/0006_seed_phase4_business_settings.py, finance/policy.py, finance/jobs.py -->

## When does a request expire?
A request is listed to travelers only while the deadline and the ready-window end are in the future, it is `open`, has no active deal and is not targeted at one traveler.
- Expiry is done by the "Deposit expiry refund" background job. It is scheduled when the posting deposit is paid and the request is published, to run at the request's deadline plus the deposit expiry grace (seeded 0 seconds). It marks a still-`open` request `expired`, refunds the deposit in full (refund reason "Request expired unmatched") and ends its Boost.
- A request that found a traveler is not expired; its deposit is credited, not refunded.
- In the `after_acceptance` mode (no deposit) no such job is scheduled, and the code has no other job that marks a request `expired`. Such a request just stops being listed once its deadline passes.
<!-- src: backend/monolith/apps/discovery/listings.py, finance/services.py _publish_request_after_deposit, finance/jobs.py handle_deposit_expiry_refund -->

## Can the sender cancel a parcel request?
- Only the sender, only while `open` or `awaiting_deposit`, and only if the request has no deal.
- Pending proposals on it are withdrawn and the negotiations cancelled. The deposit (if paid) is refunded in full and the order cancelled. Any unpaid Boost ends.
- Errors: "Only the sender can cancel." (403); "A request with a Deal must use the Deal cancellation workflow." (409); "Cannot cancel a parcel in status '<status>'." (409).
<!-- src: backend/monolith/apps/parcels/services.py -->

## What is "I can carry this"?
A traveler tells a sender that one of the traveler's journeys could carry that request. The server first checks the traveler's journey really fits (the same check as Find Travelers). It creates no offer, no price, no reservation; the sender gets one notification and still proposes first.
- Limit: 10 signals per traveler per rolling 24 hours (setting: Marketplace features, "I can carry this signals per traveler per day", 1 to 100).
- Repeating a signal for the same request and journey returns the existing one.
- Refusals: "This request is no longer open." (404), "Choose one of your own journeys." (404), "This journey cannot carry this request." (409), "You have reached today's limit. Try again tomorrow." (429), "Browsing requests is not available right now." (listings switched off).
- Also, when a request opens, fitting travelers (max 30, each at most 5 such alerts per day, settings in Marketplace features) are told once. That is not an offer either.
<!-- src: backend/monolith/apps/discovery/interest.py, core/marketplace_policy.py, discovery/alerts.py -->

## How does a proposal work? Who proposes first?
- The sender proposes first, to a specific traveler's journey, with a reward in EUR cents. The traveler cannot start a negotiation.
- The other side (not the proposer) can accept, decline or counter. Counter creates a new offer with a new price; the old one becomes `countered`. The proposer can withdraw while it is pending.
- Only one pending offer per negotiation. A negotiation ("match") is `pending` until an offer is accepted, declined, withdrawn or expires.
- Checks at proposing: request is `open`; journey is active or in progress and not paused; the traveler is not the sender; a targeted request only accepts its target traveler; the journey must truly be compatible (route, timing, capacity). Boost cannot bypass compatibility. Price below minimum is refused (`reward_below_minimum`, with the minimum).
- Offer statuses: `pending`, `countered`, `accepted`, `declined`, `withdrawn`, `expired`.
- Common refusals: "Only the request sender may propose first.", "A sender cannot propose to their own journey.", "The delivery request is not open.", "The journey is not active.", "This private delivery request targets a different traveler.", "The proposer cannot accept their own offer.", "The offer is no longer pending."
<!-- src: backend/monolith/apps/matching/v1_services.py, matching/views.py, matching/models.py -->

## What is the proposal deadline?
- Each proposal and counter-proposal has a response deadline: the time it was sent plus 6 hours, or the pickup time of that match if that is sooner.
- One reminder goes to the person who must answer, 1 hour before the deadline (not sent if that moment is not after the offer was sent).
- From the deadline on, the offer cannot be accepted, countered, declined or withdrawn: refusal `offer_expired` ("The response deadline of this offer has passed."), even before the background job runs. The job then sets it `expired` and ends the negotiation like a decline; the request stays open so the sender can propose to someone else. Expiry reserves nothing, charges nothing and creates no reliability mark.
- Settings (console Settings, "Marketplace features"): "Give proposals a response deadline" (on by default), "Hours to answer a proposal" (default 6, 1 to 168), "Remind the person who must answer, hours before the deadline" (default 1; 0 = none; must be smaller than the hours). Applies to proposals sent from then on; an existing offer keeps its deadline. With the switch off new proposals have no deadline.
<!-- src: backend/monolith/apps/matching/offer_deadlines.py, core/marketplace_policy.py, admin_panel/console_forms.py -->

## What happens when an offer is accepted?
- Either party except the proposer accepts. The server rechecks compatibility, capacity (weight, volume, parcel count on every leg) and that the request is still open.
- If a Boost is included, the acceptor must confirm the total; if it changed they get `offer_economics_changed` and must review again.
- A deal is created with status `payment_required`. Prices, commission and Boost are frozen on the deal. Space on the traveler's legs is reserved for the payment grace period (seeded 3600 seconds = 1 hour, stored setting `reservation.payment_grace_seconds`, shown read-only in Settings; no console form). The balance to pay is created (any posting deposit is credited off it).
- Offer becomes `accepted`, negotiation `accepted`, request `matched`. Competing pending offers on the same request are expired.
- Accepting the same offer again returns the existing deal.
- Other refusals: `request_already_matched`, `journey_not_active`, `capacity_exceeded`, `incompatible_candidate`.
<!-- src: backend/monolith/apps/matching/v1_services.py, core/migrations/0006_seed_phase4_business_settings.py -->

## What are all the deal statuses and what do they mean?
| Status | Meaning |
|---|---|
| `offer_accepted` | Exists in the list but new deals start at `payment_required`. |
| `payment_required` | Waiting for the sender's payment; space reserved. |
| `funded` | Paid in full. Waiting for the sender to record the recipient. |
| `pickup_ready` | Recipient recorded; traveler may confirm pickup. |
| `picked_up` | Pickup code accepted (passes straight on to `in_transit`). |
| `in_transit` | Traveler carries the parcel; delivery code still locked. |
| `delivery_ready` | The 30-minute buffer passed; delivery code released. |
| `delivery_confirmed` | Delivery code accepted (passes straight to `protection_window`). |
| `protection_window` | 48 hours after delivery. Payout cannot be released; a dispute is possible. |
| `completed` | Protection ended cleanly, or a dispute was decided for the traveler. |
| `cancelled` | Cancelled before funding, or after funding with nothing collected. |
| `expired` | Not paid within the grace period; reservation released. |
| `payment_failed` | In the list but never set by any code: after a failed payment the deal stays `payment_required` and the sender retries. |
| `disputed` | A dispute is open; payout frozen. |
| `refunded` | Sender fully refunded (cancellation, no-show or dispute). |
| `partially_refunded` | Sender refunded part; traveler got compensation or a share. |
Only one active deal can exist per request at a time. For lists the server groups deals: active (anything still moving), completed (delivery confirmed, protection, completed), cancelled (cancelled, expired, refunded, partially refunded).
<!-- src: backend/monolith/apps/deals/models.py, deals/activity.py, deals/lifecycle.py -->

## What happens if the sender does not pay in time?
The reservation lasts the payment grace period (seed 1 hour). A background job and a sweep then release it: deal `expired`, negotiation `expired`, space freed, the balance order closed, request back to `open` (its unpaid Boost comes back with it). A payment that arrives after this is recorded and refunded; it does not revive the deal.
Before paying, either party can cancel: the deal becomes `cancelled`, space freed, request back to `open`, free of charge.
<!-- src: backend/monolith/apps/deals/services.py, finance/jobs.py -->

## What changes at funding?
- Deal `funded`; the funded time is stored. Prices stay as frozen at acceptance.
- The lifecycle rules are copied onto the deal (30-minute buffer, 48-hour protection, review window, cancellation rules, code limits). A later settings change does not affect this deal.
- Agreed pickup time is frozen (from the match's pickup time, else the request's ready-window start, else the leg departure). It is used for the cancellation cutoff and no-show window.
- The funded arrival time is frozen (used as a payout floor; see Early arrival).
- Any Boost paid is consumed (cleared from the request).
- The sender's pickup code is created.
- Exact locations become visible to the traveler. Before funding, a traveler (and everyone but the sender) sees only the coarse public location (public label, city, region, rough coordinates). After funding the traveler of the funded deal sees the sender's exact pickup and delivery locations. The funded route (legs and times for this parcel) is shown to both parties only after funding.
<!-- src: backend/monolith/apps/deals/services.py, parcels/serializers.py, deals/route.py -->

## Who is the recipient and when is it set?
- Recipient: full name (max 120), email (required), phone (max 32, optional), delivery note (max 1000, optional), language.
- Only the sender can set or change it, only after funding and before pickup is confirmed. Errors: "Only the sender can set the delivery recipient.", "Recipient details are collected once the delivery is funded.", "The parcel has already been picked up; the recipient can no longer be changed here."
- Setting it moves `funded` to `pickup_ready`. Without it the traveler's pickup code is refused (`recipient_required`).
- Who sees it: sender and staff see everything. The traveler sees only "recorded" before pickup, and after pickup the name and delivery note. The traveler never sees the email or phone. Nobody else sees anything. Changes are logged on the timeline without the new values.
<!-- src: backend/monolith/apps/deals/recipient.py, deals/serializers.py -->

## How does pickup work (the pickup code)?
- The sender gets an 8-character code when the deal is funded and can view it in the app any time before pickup (and rotate it for a new one). The traveler cannot view it; they must be given it in person by the sender and type it in.
- Code alphabet is letters and digits without I, L, O, U. Typing ignores case, spaces and dashes (I/L read as 1, O as 0).
- Pickup is accepted only when the deal is `pickup_ready`. On success: pickup time stored, deal `in_transit`, capacity marked in transit, sender emailed "Pickup confirmed", the 30-minute timer starts, and the delivery code is created in a locked state.
- After pickup the deal cannot be cancelled; use a dispute.
- Code errors: `recipient_required`, `deal_not_pickup_ready`, `pickup_already_confirmed`, `code_not_available`.
<!-- src: backend/monolith/apps/handover/services.py, handover/codes.py, core/phase4_policy.py -->

## How do wrong codes, lockouts and rotation work?
Defaults (stored per deal at funding; seed values):
- Code length 8.
- 5 wrong tries lock the code for 15 minutes (900 s). After 3 such lockouts the code is locked for good; only the sender rotating it gives a usable new one.
- At most 12 attempts per rolling hour per code kind; beyond that `handover_rate_limited` ("Too many attempts. Try again later.", HTTP 429).
- A wrong code always answers "That code is not valid for this delivery." plus attempts remaining and lock time. Messages never say how close the guess was.
- Only the traveler can submit codes ("Only the traveler can submit a handover code."); only the sender can view or rotate ("Only the sender can view a handover code.").
- Rotation replaces the old code. Pickup rotation: before pickup, funded deals only. Delivery rotation: only after the 30-minute buffer, while in carriage, before delivery; it re-sends the recipient's email with the new code.
- Every submission and every time the sender views a code is logged (never the code itself).
<!-- src: backend/monolith/apps/handover/services.py, core/phase4_policy.py -->

## Why can't the traveler see the delivery code? How is it sent?
The traveler has no way to view it at all (no screen, API or message returns it to them). The delivery code is created at pickup but locked for 30 minutes (1800 s; stored per deal). During the 30 minutes nobody can see it, including the sender; revealing or rotating is refused with `delivery_code_buffer_open` ("The delivery code is inside its safety window.").
When the 30 minutes pass (a scheduled job, or the sender opening the code, whichever is first):
- Deal becomes `delivery_ready`.
- The recipient is emailed the code (in the recipient's language, with tracking number, recipient name and sender name). The code is added only when the email is built, never stored in the message.
- The sender is emailed that the code is available and can view it in the app.
- The traveler only gets a refreshed deal; they learn the code only by the recipient reading it aloud.
If the email never reaches the recipient, the sender can read the code to them or rotate it.
<!-- src: backend/monolith/apps/handover/services.py, handover/codes.py, deals/recipient.py -->

## How is delivery confirmed?
The traveler types the delivery code the recipient gives them, while the deal is `delivery_ready`. On success: delivery time stored, deal `delivery_confirmed` then `protection_window`, protection ends 48 hours later (172,800 s, from payout setting "protection window", stored per deal), the review window opens (14 days, 1,209,600 s), both parties are emailed "Delivery confirmed", a reminder email goes 24 hours before protection ends (server setting PROTECTION_ENDING_REMINDER_SECONDS, default 86,400), and the rating invitation is sent. Refusals: `delivery_code_buffer_open`, `delivery_already_confirmed`, `pickup_not_confirmed`.
<!-- src: backend/monolith/apps/deals/lifecycle.py, handover/services.py -->

## How does a deal auto-complete?
When the protection window ends, a scheduled job evaluates the payout. The deal becomes `completed` automatically if: there is no active dispute and the time is past `max(protection end, funded arrival time)`. Then the payout becomes eligible and both parties are emailed "protection ended". If a dispute is active, the payout is frozen and the deal stays `disputed`. If the funded arrival time is later than the protection end (an unusually early delivery), the deal is still closed out as `completed` while the payout waits for that time. Payout details: money.md. A dispute resolved for the traveler can also complete a deal without a confirmed delivery; a dispute can also end as `refunded` or `partially_refunded`.
<!-- src: backend/monolith/apps/finance/payout_release.py, finance/jobs.py, deals/lifecycle.py -->

## Who can cancel a funded deal and what does it cost?
Allowed only for the sender or the traveler, only while `funded` or `pickup_ready`, and only before pickup. The server quotes first (`GET deals/<id>/cancellation`), then performs it (`POST deals/<id>/cancel`).
| Case | Result |
|---|---|
| Traveler cancels | Sender refunded in full. No compensation. Recorded as a reliability signal. |
| Sender cancels more than 24 hours before the agreed pickup | Sender refunded in full. |
| Sender cancels 24 hours or less before the agreed pickup (exactly 24 h counts as late) | Traveler is compensated 10% of the base traveler reward (rounded up), capped at EUR 15.00; the rest goes back to the sender. Platform fee on this: 0%. |
| Sender cancels after declining the traveler's new times | Treated as a traveler cancellation: full refund, no compensation. |
Worked example: base reward EUR 20.00, sender cancels 5 hours before pickup: 10% = EUR 2.00 to the traveler; the sender gets back everything collected minus EUR 2.00. If reward was EUR 200: 10% = EUR 20.00, capped to EUR 15.00. The Boost part is not included in the 10%.
- Cutoff defaults (Deal-frozen): 86,400 s, 1000 bps, EUR 15.00 cap, 0 bps platform fee. If no agreed pickup time exists, it counts as early (no penalty).
- Result status: `refunded` (all back), `partially_refunded` (compensation paid), `cancelled` (nothing had been collected). The parcel request becomes `cancelled` (not reopened; the sender must post a new request and pay a new deposit). Space is freed, codes cancelled, both emailed "deal cancelled".
- Refusals: `cancellation_not_available_after_pickup` ("This parcel has already been picked up. Open a dispute instead."), `use_pre_funding_cancellation` ("This delivery has not been funded yet; use the standard cancel action."), `deal_not_cancellable` ("This delivery can no longer be cancelled."), `not_authorized` ("Only a party to this delivery can cancel it.").
- Cancelling again after a cancellation returns the same answer, not an error.
<!-- src: backend/monolith/apps/deals/cancellation.py, deals/views.py, core/migrations/0006_seed_phase4_business_settings.py -->

## What if the traveler changes the journey times? Declined schedule change?
A traveler may re-time legs of an active journey. A parcel is "affected" if on that leg, and "material" if the new arrival is after its deadline or moves more than 360 minutes (6 hours; setting "route change material shift minutes", 30 to 10,080) from the last agreed arrival, or the pickup moves by the same amount (or earlier than agreed pickup). A collected parcel is only informed. With no material parcel the change applies at once. Otherwise each material sender accepts or declines; it applies when all accept, collected or inactive; the traveler can withdraw it. A sender who declines may cancel, and that cancellation is treated as the traveler's (full refund, reason `declined_schedule_change`). Funded arrival, payout floor and agreed pickup stay as frozen.
<!-- src: backend/monolith/apps/trips/schedule_changes.py, core/marketplace_policy.py, deals/cancellation.py -->

## What are no-show reports and what does staff do?
- Reporting (parties): the person left waiting reports. A traveler reports `sender_unavailable` ("The sender did not come"); a sender reports `traveler_no_show` ("The traveler did not come"). Allowed only from the agreed pickup time until pickup is confirmed, on a funded, active deal with no no-show already recorded. Refusal `no_show_report_not_allowed` with reason: `deal_not_funded`, `deal_not_active`, `pickup_time_unknown`, `pickup_time_not_reached` (with when), `pickup_already_confirmed`, `no_show_already_recorded`. Wrong person: "Only the person who was left waiting can report this."
- Other problem types any party can report from funding until delivery: recipient unavailable, parcel mismatch, parcel damaged, trip disrupted, customs delay, other (note max 1000 characters). After delivery use a dispute. Reports of no-show, damage or mismatch go to staff at once (`escalated`); statuses: open, escalated, acknowledged, closed. A report changes no deal status or money.
- Staff: Console, Disputes > Problems list shows the reports; a no-show report has a "Record a no-show" link to Marketplace > Deals > (deal) > no-show page. Needs the "record no-show" permission. Staff choose the party (sender or traveler) and add a note (max 255).
- Traveler no-show: sender refunded in full, deal `refunded` (or `cancelled` if nothing was collected), request cancelled, space freed, reason `traveler_no_show`. Sender no-show: recorded only, no refund by default (staff may override the refund choice). Not allowed after pickup, or if a no-show was already recorded (the second call returns the first).
<!-- src: backend/monolith/apps/problems/services.py, deals/cancellation.py, admin_panel/console_problems.py, admin_panel/console_urls.py -->

## What is the tracking number?
Format `WSL-` plus 8 characters from `23456789ABCDEFGHJKMNPQRSTVWXYZ` (no 0, 1, I, L, O, U), e.g. `WSL-7K3M9QXD`. Random, created with the request, never changes, never reused, identical across all deals of that request. It only identifies a parcel and authorises nothing. People may type it in lower case, without the hyphen or without `WSL`. Shown to: the sender on their request, both parties on the deal and in emails (pickup, delivery, cancellation, rating, protection and payout emails, recipient code email, and offer reminders); a traveler sees it through a deal or proposal they are part of, not on the open request. Console titles also use it (e.g. "Record a no-show · WSL-…").
<!-- src: backend/monolith/apps/parcels/tracking.py, parcels/serializers.py -->

## What progress updates and reminders does the traveler give?
- On each leg of a journey the traveler reports "departed" and "arrived" (and "at the port" on sea legs, which are off by default). Order is enforced (departed before arrived; each departure needs the previous leg's arrival; error `progress_out_of_order`). Not earlier than 24 hours before the planned time (`progress_too_early`). A report can be retracted within 10 minutes unless a later report exists.
- A report is copied to the timeline of every funded parcel on that leg, labelled "reported by the traveler", and tells the senders. It is a statement only: no status change, no money.
- Reminders to the traveler (stored setting `marketplace.reminders`, default on): ask "departed?" 30 minutes after planned departure and "arrived?" 60 minutes after planned arrival, only if the leg carries a funded parcel; repeat every 180 minutes, at most 2 repeats. These have no form on the console Settings page; they change only through a full new settings version posted through the staff settings API (needs `manage_settings`).
<!-- src: backend/monolith/apps/trips/progress.py, core/marketplace_policy.py -->

## What is early arrival?
If the traveler reaches the destination much earlier than the funded schedule, they can report it. "Material" means at least 6 hours early (21,600 s, fixed in code). Only the traveler may report, only while carrying the parcel. The sender then confirms or declines. It changes no status, releases no code, starts no protection window and does not move the payout floor: payout still waits for the funded arrival time. Refusals include `not_materially_early`, `arrival_report_pending`, `arrival_already_confirmed`, `delivery_already_confirmed`, `dispute_active`.
<!-- src: backend/monolith/apps/deals/arrival.py -->

## What does each person see at each step?
| Step | Sender | Traveler | Recipient |
|---|---|---|---|
| Request open | Full request, tracking number | Public card only (no address, no recipient) | Nothing |
| Offer | Offer, deadline | Offer, deadline, coarse locations | Nothing |
| Payment required | Deal, cancel option, pay | Deal, reserved | Nothing |
| Funded | Pickup code, can set recipient | Exact locations, funded route | Nothing |
| Pickup ready | Pickup code | Can enter pickup code | Nothing |
| In transit (first 30 min) | Countdown, no delivery code | Name and note of recipient | Nothing |
| Delivery ready | Delivery code (view/rotate) | Can enter code, never see it | Emailed delivery code |
| Protection window | Countdown, can dispute | Countdown, payout state | Nothing |
| Completed | Rating invite | Payout status, rating invite | Nothing |
Staff see the full stored timeline.
Each party's timeline shows only allowed fields (status, times, amounts, ids), never code material or contact details.
<!-- src: backend/monolith/apps/deals/serializers.py, deals/timeline.py, deals/recipient.py -->

## Where does staff see deals and requests?
- Console menu: Marketplace > "Delivery requests" (view_requests), "Journeys" (view_journeys), "Deals" (view_deals; each deal has a detail page with its timeline and a no-show page); Disputes > "Disputes" and "Problems" (view_disputes).
- Settings > "Business settings": the "Discovery, routes, prices and proposals" card (eyebrow "Marketplace features") holds the proposal deadline switches and the "I can carry this" cap. The page also has the pricing (commission, deposit, floors), Chargily exchange rate, provider availability and boost commission forms.
- The handover buffer (30 min), protection window (48 h), payment grace (1 h), free-cancellation cutoff, late-cancellation compensation and cap, and review window are shown read-only in the "Lifecycle guardrails" table. No console form changes them; they change only through a full new settings version posted through the staff settings API (needs `manage_settings`, a written reason, audited). A change never affects a deal already funded.
<!-- src: backend/monolith/apps/admin_panel/console_urls.py, admin_panel/console_forms.py, core/templatetags/shiptrip_admin.py NAVIGATION, templates/admin/console/settings.html, admin_panel/views.py AdminSettingsView -->

## Not covered here
- Mobile screen-by-screen wording for the delivery screens (see app-walkthrough.md).
- Boost bands, payment flow, refunds, payouts, disputes and ratings in depth (see pricing.md, money.md, problems-and-disputes.md, reviews.md).
