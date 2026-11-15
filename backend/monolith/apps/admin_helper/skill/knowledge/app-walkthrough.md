# Wassla mobile app walkthrough

Covers: What a user sees and taps in the Wassla mobile app, screen by screen, with the English button labels and the loading, empty, error and offline states.
Related files: pricing.md, money.md (payments and payouts), deliveries.md (deals and handover codes), problems-and-disputes.md, trips-and-matching.md, accounts-and-verification.md (KYC and tickets), reviews.md, messages-and-notices.md, settings-and-helper.md

Wording below is quoted from the app's English strings. The app also exists in French and Arabic. Money amounts and statuses always come from the server; the app never decides that a payment, verification, delivery or payout succeeded.

## How is the app laid out?
- Four tabs at the bottom: **Home**, **Deliveries**, **Chat**, **Profile**. Chat shows a badge with unread chats.
- Notifications are not a tab. They are the bell in the top bar of the tab screens ("Notifications", with the unread count). Inside: "Mark all as read". Empty state: "Nothing new / Offers, payments and delivery updates show up here."
- Traveler "My journeys" and the parcels being carried are in the same Deliveries tab. There is no separate My Trips tab.
- Task screens (post a parcel, pay, enter a code, open a dispute) open full screen above the tab bar.
- Signed-out users land on a welcome screen with "Create an account" / "Sign in". An expired session sends the user to the sign-in screen ("Please sign in again").
- A guest payment link (`/guest/pay/...`) works without an account.
<!-- src: mobile/lib/app/router.dart, mobile/lib/features/shell/app_shell.dart -->

## What are the roles in the app (Sending / Traveling)?
- Every new account has the role `both` by default, so one account can send and travel.
- On Home an account that can do both sees a switch: **Sending** and **Traveling**. It changes the greeting, the big button and the lists. It never hides data.
- Sender Home: greeting "Send something home", big button "Send a parcel". Traveler Home: "Earn on a trip you're already taking", big button "Add a journey".
- A traveler who is not verified sees "Verify your identity / Travelers must be verified before a journey can go live."
<!-- src: backend/monolith/apps/accounts/models.py, mobile/lib/features/home/home_screen.dart -->

## What does the Home tab show?
- Sections in order: role switch, verify notice (travelers), **Needs you**, **In progress**, the user's own requests (sender) or journeys (traveler), **Matches for you**, an optional "Be found on Wassla" card, **Trips leaving soon** / **Parcels looking for a traveler**, and **Travelers on Wassla** / **Senders on Wassla**.
- "Needs you" items include: "An offer is waiting for your answer", "Pay to confirm this delivery", "Add who receives the parcel", "Show the pickup code to your traveler", "Enter the pickup code", "The delivery code is ready", "Enter the delivery code", "Rate this delivery". Empty: "Nothing needs you right now".
- Empty states: sender "Nothing on the way yet / Post what you want to send and travelers heading that way will see it."; traveler "No journeys yet / Add the trip you're taking and we'll show you parcels along your route."
- Pull down to refresh. Browsing trips/parcels or public profiles can be switched off by staff; the app then says "Not available right now ... Browsing trips and parcels is paused for now" (or "Public profiles are paused for now").
<!-- src: mobile/lib/features/home/*.dart, l10n app_en.arb -->

## How does a user sign up and sign in?
- **Create account** screen ("Create your passport."): Full name, Email, Password (at least 8 characters, "Use at least 8 characters"), Phone number (required). Button "Create account". Terms notice: "By creating an account you accept the Terms and the Privacy Policy."
- The app sends the user's current app language as the first email language. It can be changed in Profile > Language.
- After sign up the user is signed in and sent to "Confirm your email": enter the six-digit code from the email, button "Confirm". Success: "Email verified". Wrong code: "That code isn't right". There is no resend button in this screen: "Nothing arrived? Check your spam folder. If it still isn't there, contact support."
- **Sign in**: Email, Password (show/hide), "Sign in". Wrong details: "Email or password is incorrect". Link "New to Wassla?" goes to sign up.
- **Forgot your password?**: enter the email, "Send code"; the message is always "If that address has an account, we've sent it a six-digit code." Then enter the Six-digit code and New password (8+ chars), "Confirm". "Send a new code" resends. Success: "Password changed. You can sign in now."
- **Sign out** is in Profile, with the confirmation "Sign out? You'll need to sign in again to see your deliveries."
- Offline on start does not sign the user out; the app waits on the splash screen.
<!-- src: mobile/lib/features/auth/*.dart -->

## What do error, offline and empty screens say in general?
- Offline: "You're offline / Check your connection. We'll load this as soon as you're back."
- Timeout: "That took too long". Server error: "Something went wrong on our side". Not found: "Not found / This may have been removed, or it was never yours to see." Forbidden: "You can't do that here". Too many attempts: "Too many attempts / Wait a moment before trying again."
- Out of date app: "This version is out of date / Update Wassla to continue."
- A page that changed under the user shows "This has changed" with "Refresh". Examples: "This request isn't open any more.", "This offer has already been answered.", "There isn't enough space left on this journey.", "Your identity check needs attention before you can do this.", "Your reserved space expired.", "This delivery is closed."
- Buttons everywhere: "Try again", "Go back", "Contact support".
<!-- src: l10n app_en.arb (stateXxx, staleXxx) -->

## How does a traveler verify identity?
- Profile shows a Verification card with status: **Not started**, **Being reviewed**, **Verified**, **Not approved**. Button "Start identity check" (or "Try again" after a rejection). Home also links to it for travelers.
- Screen "Identity check": choose Document type (**National ID card**, **Passport**, **Driving licence**), add Front of document, Back of document (not needed for a passport: "A passport only needs its photo page."), and a Selfie. Photos: JPEG or PNG, under 8 MB each. Button "Submit for review".
- Messages: "Documents received. We'll review them shortly."; pending "We're reviewing your documents. This usually takes less than a day."; approved "You're verified. You can publish journeys and carry parcels."; rejected "We couldn't verify your documents. You can submit again."; unavailable "Verification is temporarily unavailable. Please try again shortly."
- Verification is needed to publish a journey (error "You need to be verified before you can publish a journey."). Saving a draft journey does not require it. Senders are never asked for an identity check: the server checks identity only for travelers (publishing a journey, and again when an offer on that journey is made or accepted).
<!-- src: mobile/lib/features/kyc/kyc_screen.dart, journeys/journey_detail_screen.dart, backend trips/services.py (validate_journey_verification_gates), backend/services/internal/kyc/handler.go -->

## How does a sender post a parcel request?
Home > "Send a parcel" (or Deliveries > Sending section). Four steps: **Route**, **Parcel**, **Timing**, **Review**. Next is blocked until the step is valid; a refused server field is marked on its step ("The server refused this request. The problem is on this step, marked below.").
1. **Route**: "Pickup from" and "Deliver to" (search localities and airports, or choose on map; countries offered: Algeria, France, Spain, Germany). Pickup and delivery must differ. A preferred meeting point is optional ("Decide later"). Only the city is shared until the delivery is paid.
2. **Parcel**: item photo (required; JPEG, PNG or WebP, up to 10 MB; "From gallery" / "Take a photo"), title "What are you sending?" (max 160 characters), Description (max 2000), Category (Documents, Small box, Electronics, Clothing, Something else), Weight (0.01 to 100 kg), Size length/width/height in cm (optional, but all three or none; "We charge on whichever is greater" weight or size), Declared value (EUR, what it would cost to replace), Handling notes, Fragile switch ("Handle with care").
3. **Timing**: Ready from / Ready until (a window), "Must arrive by" (deadline, must be in the future and not before the window closes; the date picker allows up to 365 days ahead).
4. **Review** ("Check this over"): the proposed reward ("What you propose to pay", a starting point; shown against a recommended and a minimum price, errors like "Offer must be at least X"), live totals (Traveler receives, Wassla fee, Total sender cost), and five required tick boxes: description accurate, item legal, no prohibited goods, declared value accurate, customs responsibility understood ("Confirm all five before you post."). Link "See what can't be sent". Button "Post this request".
- A request is created with no Boost. After posting, if a posting deposit is due the sender goes to "Publish your request" (deposit screen); otherwise to "Your request".
- Prices, deposit size and fee come from the pricing file; the app only displays what the server quotes ("Updating the price" while loading).
<!-- src: mobile/lib/features/requests/request_create_screen.dart -->

## What is the posting deposit and how does the sender pay it?
- Request status `awaiting_deposit` shows as **Deposit needed**; travelers cannot see it ("Travelers can't see this yet. Pay the deposit to publish it.").
- Screen "Publish your request": explainer "Paid now to list your request. 100% credited toward your final delivery payment." Presets: "Minimum (amount)", "Recommended (amount)", "Pay in full (amount)", "Custom". Limits: "The smallest deposit is X" / "That's more than the whole amount of X". Button "Pay deposit and publish".
- Refund: "If nobody takes it, or you cancel before accepting an offer, you get it back in full." Some requests need no deposit: "No deposit needed".
- After payment: "Your request is now published" and "Find a traveler going your way and send them an offer."
- Request statuses in the app: Deposit needed, **Finding a traveler** (`open`), Matched, On the way, Delivered, Completed, Cancelled, Expired.
- Cancel a request: "Cancel request" > "Cancel this request? It stops being visible to travelers. Any deposit you paid comes back to you." Not possible once a traveler is matched ("A traveler is already matched with this request, so it can't be cancelled here."); then cancel from the delivery.
<!-- src: mobile/lib/features/requests/deposit_screen.dart, request_detail_screen.dart, features/common/status_copy.dart -->

## How does a sender find a traveler and make an offer?
- On "Your request" tap "Find travelers" (screen "Travelers for this parcel"). Each card shows route fit ("Excellent route match", "Good route match", "Compatible route"), timing ("Arrives with time to spare", "Fits your delivery window"), room ("Has room for X kg"), badges ("Identity verified", "Flight ticket verified", "Ferry ticket verified"), rating or "New", deliveries count, detour ("Barely a detour", "Small detour", "Noticeable detour"), the traveler's listed price if any, and transfers. Sort: **Best match**, **Soonest trip**, **Lowest price**. "Show more travelers" pages more.
- Empty: "No travelers going your way yet / Your request stays active. We'll tell you as soon as somebody posts a trip along your route." If the request cannot be matched the reason is shown: pay the deposit, already has a traveler, closed, already on its way.
- A traveler can also be found from Browse: "Trips leaving soon" with filters From / To / From date and "Clear filters". Tapping a trip shows "You propose first. Nothing is booked from here." and "Choose one of your parcels".
- The sender always proposes first. Screen "Make an offer": "You choose what the traveler earns. They can accept, decline, or come back with a different amount." Field "Traveler's reward", "Use suggested", button "Send offer" (or "Offer {amount}" when the traveler listed a price; "Use their price" / "Offer a different amount"; below their price: "That is below their price, so they may decline or counter."). Below the minimum: "Offer at least X". Sent: "Offer sent".
- If the trip no longer fits the app says why: "There isn't enough space left on every leg.", "It would arrive after the deadline.", "The dates don't line up.", "The detour from the route is too large.", "One of them is no longer open.", "The traveler's verification isn't complete.", "This item can't be carried on this trip.", "The traveler has paused this trip.", "The traveler doesn't take handovers at the places you need.", "The traveler doesn't take this kind of item.", "There isn't enough room left for this parcel's size.", "The traveler has no parcel places left.", "A ferry line on this trip isn't available right now."
- A traveler browsing parcels can tap "I can carry this", pick a trip, and the sender gets one notification. It is not an offer: no price, nothing reserved. Daily limit message: "You have reached today's limit for "I can carry this". Try again tomorrow." Default limit 10 per 24 hours (setting).
<!-- src: mobile/lib/features/requests/discovery_screen.dart, discovery/*, offers/*; backend marketplace_policy.py -->

## How do propose, accept, counter and decline work?
- Offers live in Deliveries under "Open offers" and on the negotiation screen (history under "Offer history").
- Who moves: "Your move" / "Waiting for the traveler" / "Waiting for the sender". Statuses: **Waiting**, **Accepted**, **Declined**, **Withdrawn**, **Expired**.
- Buttons: **Accept**, **Decline** (confirm "Decline this offer? The other side will be told. You can still negotiate afterwards."), **Counter** ("Send counter-offer"; traveler: "Choose how much you receive for this delivery."), **Withdraw**.
- Accept confirmation: sender "Pay {amount} for this delivery?" (then asked to pay); traveler "Receive {amount} for this delivery?" ("Space on your journey is reserved as soon as you accept. The sender then has to pay.").
- Deadline: each proposal has an answer-by time. Default 6 hours (marketplace > offers > response_hours, 1 to 168 hours, can be switched off) with a reminder 1 hour before. The app shows "Answer by {time}", then in the last hour a minutes countdown, then "This proposal expired / No answer came in time. Nothing was reserved or charged." with "Propose to another traveler" or "Browse parcels".
- Money breakdown ("How this adds up"): Base delivery reward, Boost bonus (if any), Traveler receives, Wassla fee, Boost fee, total "You pay". "The traveler receives this full amount. The Wassla fee is added on top, not taken out of it." If amounts changed: "The amounts on this offer changed. Check the new figures before accepting."
- Boost: on a live request the sender can "Add Boost" (presets none, +EUR 5, +EUR 10, custom). "Travelers receive 100% of the Boost bonus. Boosted requests appear higher in traveler search." Boost never overrides compatibility. Cannot change once an offer is accepted or the request expired.
<!-- src: mobile/lib/features/offers/*, requests/boost_screen.dart, backend core/marketplace_policy.py -->

## How does the sender pay for a delivery?
- When an offer is accepted the deal is created as `payment_required` ("Payment needed"). The delivery screen shows "Pay before {time} or the space is released" and "Pay now". The space is held for 1 hour by default (3,600 s, Settings: reservation payment grace).
- Payment screen: "How would you like to pay?" **Stripe** (Visa, Mastercard and other cards) or **Chargily** (Algerian cards, CIB and Edahabia). Unavailable options say why: "Not available yet", "Temporarily switched off", "Not ready yet", "Below this method's minimum", "Not taking new payments right now".
- Chargily shows "Equivalent to {amount}", "Rate: EUR 1 = {rate} DA"; "The rate is locked when you start the payment. The delivery price stays in euros." The DZD figure is calculated by the server from EUR. Button "Pay {amount} with {provider}".
- The user is sent to the provider's secure page. Coming back is not proof: "We confirm every payment with the provider before marking it paid." The app shows "Checking your payment" and re-checks on a back-off schedule (3, 3, 5, 5, 10, 10, 20, 20, 20 seconds, about two minutes), then "We're still confirming your payment ... you won't be charged twice" with "Check again".
- If a checkout is open: "A checkout is already open / Continue your payment". Failed: "Payment didn't go through / Nothing was charged." Cancelled: "Payment cancelled". None available: "No payment method available / Payment is temporarily unavailable."
- A posting deposit already paid is shown as "Deposit already paid" and subtracted: "Remaining to pay". Paid in full: "Paid in full", "Payment protected". If more is owed: "Pay remaining {amount}"; "The traveler can't collect the parcel until it's paid."
- Paid statuses: deal **Paid and protected** (`funded`). Payment states: Payment needed, Paid, Refund on the way, Partly refunded, Refunded. A failed payment leaves the deal in `payment_required` so the sender can try again (no code sets `payment_failed`).
- Someone else can pay: "Someone else can pay" > "Create payment link" > "Share link" / "Copy link". The payer needs no account, enters an email for the receipt, and pays. The link only pays that amount. Link states: ready, expires {when}, "Someone is paying now", expired, revoked ("Revoke link"), "Payment received". Creating a new link stops the earlier one.
- Chat opens only after payment is confirmed ("Chat opens once a delivery is paid for.").
<!-- src: mobile/lib/features/deals/payment_screen.dart, requests/checkout_section.dart, guest/*, common/payment_result.dart; backend matching/v1_services.py (deal created in payment_required, payment grace), core/migrations/0004 -->

## What does the sender do after paying (recipient, tracking)?
- Delivery screen steps: Terms agreed, Payment held, Recipient added, Parcel collected, Delivered, Protected payment, Completed.
- "Add recipient" ("Who's receiving this?"): Recipient's name, email (the delivery code is emailed here), language, optional phone and note. "Save recipient". Required before pickup ("Add the recipient before pickup so we can send them the delivery code.").
- Exact addresses and handover notes appear only once the deal is paid: before that "Exact address available after payment". Route section: "The travel route appears here once the delivery is funded." Shown as "Frozen at booking" or "Live journey".
- Tracking number: label "Tracking number" with a copy button.
- Traveler progress shown to sender (marked "Reported by the traveler"): "Your traveler is at the port", "Your traveler has departed", "Your traveler has arrived". These never move money.
- Button "Message" opens the chat. Deal statuses: Offer accepted, Payment needed, Paid and protected, Ready for pickup, Picked up, On the way, Ready to deliver, Delivered, Payment protected, Completed, Cancelled, Under dispute, Refunded, Partly refunded, Payment failed, Expired.
<!-- src: mobile/lib/features/deals/deal_screen.dart, recipient_screen.dart, common/status_copy.dart -->

## How do pickup and delivery codes work in the app?
- **Pickup**: the sender taps "Pickup" > "Show pickup code" and says it in person ("Don't send this code in a message."). The traveler taps "Pickup", enters the "Pickup code" and "Confirm pickup". Result: "Pickup confirmed / You're carrying this parcel now."
- **Delivery code**: locked for 30 minutes after pickup ("Available in {countdown}", "For safety, the delivery code stays locked for 30 minutes after pickup. The recipient hasn't been emailed yet either."). After that Wassla emails the code to the recipient and the sender can "Show delivery code". The traveler is never shown it: "Only the recipient has this code. Ask them for it when you arrive." The traveler taps "Delivery", enters "Delivery code", "Confirm delivery". Result: "Delivery confirmed / Thank you. Your payout is being prepared."
- Code length is 8 characters (Crockford base32) by default. The welcome screen caption says 6 characters, which is old marketing text. 5 wrong attempts then a 15 minute lockout, up to 3 lockouts, 12 attempts per hour (seeded settings, handover section).
- Wrong code: "That code isn't right", "{n} attempts left". Locked: "Too many wrong attempts / Try again {when}." "Get a new code" (confirm "Issue a new code? The code you already shared will stop working immediately.") is for the sender only: the pickup code can be replaced before pickup (deal funded or ready for pickup), the delivery code only after the 30-minute lock and before delivery is confirmed.
- If the sender has not added the recipient: "The sender hasn't added the recipient yet. Ask them to do that, then try the code again."
- Chat shows "Never send a pickup or delivery code in chat."
- "I arrived early" (traveler): "Report early arrival" notifies the sender, who can "Confirm arrival" or "Decline". It does not confirm delivery or release payout earlier: "Arriving early does not make the payout available earlier than the protected payout date."
<!-- src: mobile/lib/features/deals/pickup_screen.dart, delivery_screen.dart; backend handover/services.py (rotate), core/migrations/0006_seed_phase4_business_settings.py -->

## What does the sender see during the protection window?
- After delivery: status Delivered then "Payment protected": "Your payment is held until {when}. If something's wrong with the delivery, open a dispute before then." Protection is 48 hours after delivery confirmation (setting, default 172800 seconds). Traveler: "Your payout is released after {when}, once the protection window closes."
- "Wassla releases them only after that period ends and no dispute is open."
<!-- src: mobile/lib/features/deals/delivery_screen.dart, backend deals/lifecycle.py -->

## How does a traveler add a journey, legs, tickets and a price?
Home > "Add a journey" (or Deliveries > "Post a trip"). Screen "Add a journey".
- **Your stops**: add where you start, where you end, and stops between ("Add a stop here"; move earlier/later, remove). Wassla works out the legs between stops. A stop cannot repeat the stop before it. Max 20 legs.
- Per leg: mode **Flight**, **Drive**, or **Ferry** (ferry only if staff switched sea legs on; off by default: "Ferry legs are switched off for now."). Algeria to Europe cannot be driven, so it must be a flight and the app asks "Which airport?". Ferry needs port cities and an existing line.
- Per leg: Departs, Arrives (arrival time is required to publish; the sender deadline is checked against it), Space you can carry in kg (0.01 to 20,000, two decimals; the top limit only catches typos), optional volume in litres (1 to 200,000) and number of parcels (1 to 10,000), optional flight number. Leg times must be in order and each leg must depart after the previous arrives.
- Per stop "Handover options": takes pickups and/or drop-offs, optional time window, note (only the traveler sees it until a delivery using the stop is paid, then that sender sees it).
- "What you carry": switch off item kinds you won't take; fragile can be refused; at least one kind must stay on.
- Notes: "Anything senders should know". Button "Save journey" saves a **Draft** ("Nothing is visible to senders yet").
- **Tickets**: every flight and ferry leg needs an approved ticket. On the journey page "Tickets to check" > "Upload proof" (Ticket, Boarding pass or Booking; JPEG, PNG, WebP up to 10 MB). Proof status: Not uploaded, Being reviewed, Approved, Not accepted (with "Reason: ..."). Driving legs need none.
- **Publish**: button "Publish journey" needs identity verified and all tickets approved ("Every flight and ferry leg needs an approved ticket before this can go live."). Then "Your journey is live." Journey statuses: Draft, Being checked, **Live**, Under way, Completed, Cancelled, Expired.
- **Your price** (optional, if enabled): "Price per kg" and "Minimum per parcel" (fill both or none). "Senders see your price plus Wassla's fee. Wassla's minimum for each parcel still applies." Defaults for limits: max EUR 100.00 per kg and EUR 500.00 minimum (setting marketplace > traveler_pricing). A new price applies to offers made from then on. Without a price: "No price set. Senders propose their own amount."
- **Edit**: only while the journey is a Draft (or Being checked), never once published ("This journey can no longer be edited because it is already published. Cancel it and create a new one if the route has changed."), and not if a sender is already proposing on it or a delivery is attached. Editing a flight leg's places, number or times sends its approved ticket back to review.
- **Pause / Resume**: "Pause journey": senders stop finding it, pending offers cannot be accepted, paid deliveries carry on. If staff paused it: "Wassla paused this journey. Contact support to have it resumed."
- **Cancel journey**: "Senders stop seeing it and any space they were holding is released. This can't be undone." Refused if a paid delivery depends on it ("A paid delivery is riding on this journey.").
- **Change times** on a live trip: "Change times", review, "Send new times". Senders who must agree (new arrival after their deadline, arrival moves more than the allowed margin, pickup moves) answer; default margin 360 minutes (setting marketplace > route_change). Senders see "Accept the new times" / "Decline"; a decline lets them cancel and "that cancellation is not counted as yours". Traveler can "Withdraw the new times". Others are just told.
- **Progress reports**: "I'm at the port", "I've departed", "I've arrived", opens 24 hours before the planned time, undo within 10 minutes; needs a connection ("Nothing is saved for later."). Reminders: 30 min after planned departure, 60 min after arrival, repeat every 180 min up to 2 times (settings, marketplace > reminders).
<!-- src: mobile/lib/features/journeys/*.dart, journey_route_draft.dart; backend trips/constraints.py, trips/services.py (journey_editability, EDITABLE_JOURNEY_STATUSES), trips/progress.py, core/marketplace_policy.py -->

## How does a traveler answer proposals and carry the parcel?
- Offers appear in Deliveries > "Open offers" and as "An offer is waiting for your answer". Accept / Decline / Counter as above. Travelers cannot offer on parcels ("Senders make the first move"), only signal with "I can carry this".
- After the sender pays: meet, ask for the pickup code, "Confirm pickup", travel, ask the recipient for the delivery code after the 30 minute lock, "Confirm delivery".
- Browse parcels: "Parcels looking for a traveler" with filters; empty "No open parcels right now" with "Add a journey".
- Route alerts (Profile > Route alerts): "Add alert" for a city pair, watch "New trips" or "New parcels"; "at most one notification per alert every few hours" (the server waits 6 hours between notifications for one alert); at most 10 active alerts per user ("You have reached the maximum number of active alerts."). Travelers may also get "A parcel fits your trip".
<!-- src: mobile/lib/features/discovery/*, deliveries/deliveries_screen.dart; backend discovery/alerts.py (ALERT_QUIET_PERIOD), discovery/models.py (MAX_ACTIVE_ALERTS) -->

## What does the Deliveries tab show?
- Filter chips: **Active**, **Needs you**, **History**. Sections: Open offers, "Sending" (requests, sender role) or "My journeys" (traveler role), and deals as cards ("Sending" / "Carrying", "with {name}").
- Empty states: "Nothing active / Deliveries you're sending or carrying will appear here."; "You're all caught up / Nothing is waiting on you."; "No history yet / Completed and cancelled deliveries stay here." History loads more pages as you scroll.
- A deal not visible to the account: "Delivery unavailable".
<!-- src: mobile/lib/features/deliveries/deliveries_screen.dart -->

## How does a user cancel a delivery?
- Delivery screen > "Cancel this delivery" > "Cancel delivery" (or "Keep it"). The button shows only if the server says cancellation is allowed. After pickup: "The parcel has already been picked up. If something's wrong, open a dispute instead."
- Outcome text: "You'll be refunded in full." or, close to pickup, "Because it's close to pickup, the traveler is compensated for holding the space." Seeded rule: sender cancels more than 24 hours before agreed pickup = full refund; inside 24 hours = traveler gets 10% of the reward, capped at EUR 15 (settings, cancellation section). Then "Your refund is on the way."
- If the traveler changed the times and the sender declined, the cancellation is counted against the traveler, not the sender.
<!-- src: mobile/lib/features/deals/cancel_screen.dart, backend core/migrations/0006_seed_phase4_business_settings.py -->

## How does a user report a problem or a no-show?
- On the delivery screen: "Report a problem" (sheet "What went wrong with this delivery?"). Kinds: "The sender did not come", "The traveler did not come", "The recipient is not available", "The parcel is not what was described", "The parcel is damaged", "The trip is cancelled or delayed", "Held up at customs", "Something else". Optional note up to 1,000 characters. Button "Send report". "The other person is told. Wassla staff look at damage and mismatches right away. Reporting does not cancel or refund anything."
- Available while the deal is `funded`, `pickup_ready`, or in carriage (`picked_up`, `in_transit`, `delivery_ready`).
- No-show buttons ("The sender did not come" shown to the traveler, "The traveler did not come" to the sender) only appear from the agreed pickup time until pickup is confirmed, on a funded deal without a staff decision. Before that time: "This can't be reported right now. The pickup time may not have come yet, or the parcel may already be collected." The other side sees "The traveler says you did not come" with "Reply in chat". "Wassla staff will look at it. Nothing is cancelled or refunded yet."
- Report statuses: Sent, With Wassla staff (escalated: damaged, mismatch, sender unavailable, traveler no-show), Being looked at, Closed. Offline: "No connection. Nothing was sent."
<!-- src: mobile/lib/features/problems/problem_widgets.dart, backend problems/services.py -->

## How does a user open a dispute?
- Delivery screen > "Open a dispute" (only if the server allows it). Either party can open one from pickup until protection ends (48 hours after delivery). No console page lets staff open one. Before pickup: "You can't open a dispute yet ... cancel the delivery instead." After: "The dispute window has closed ... Contact support if you still need help." The screen shows no support button there: the code passes a label but no action, so the button is not drawn.
- Form: "What happened?" (Never arrived, Arrived damaged, Wrong item, Arrived too late, The other person didn't show up, Something is wrong with the money, Something else), "Describe the problem". Warning: "The traveler's payout goes on hold / Nothing is paid out while we look into this." Button "Open dispute".
- Dispute screen: status Open, Waiting for evidence, Being reviewed, Resolved, Closed; timeline; Evidence (photo, video, note; JPEG, PNG, WebP, MP4, MOV; max 20 items, 25 MB each by default; "Add photo", "Add video", "Add a note"). Outcome: "Refunded to the sender", "Paid to the traveler", "Split between both sides". Amounts are Wassla's decision. If the payout already went out: "The payout had already gone out before this dispute was opened."
- One open dispute per delivery ("You already have a dispute open on this delivery. We've taken you to it.").
<!-- src: mobile/lib/features/disputes/*.dart, mobile/lib/design/components/feedback.dart (AppEmptyState), backend disputes/services.py (_assert_dispute_window_open) -->

## How do ratings and reviews work?
- After a delivery: "Leave a rating" ("How did it go?"): "Rate the traveler" / "Rate the sender", score 1 to 5, tags (from a server list: communication, punctual, careful handling, clear instructions, friendly, late, poor communication, damaged), optional comment (up to 1,000 characters). "Submit rating".
- Blind: "Neither of you sees the other's rating until you've both left one, or the window closes." Window default 14 days after delivery confirmation ("The rating window has closed.").
- Reviews appear on public profiles and trips ("Reviews"). Users can "Report" a review (offensive, shares personal information, not about the delivery, not true, other). Staff can remove a review or hide its comment ("Removed by Wassla, not counted", "Wassla hid the comment from others. The score still counts."). Reviews can be switched off by staff ("Reviews are not available").
<!-- src: mobile/lib/features/deals/rate_screen.dart, reviews/*; backend deals/lifecycle.py -->

## How does a user change profile, language, appearance, notifications?
- Profile tab: passport card (name, Verified status, "Email verified"/"Email not verified", role, Completed count, Recent rating, "With Wassla since"). Rows: Payouts, Payout methods, Ratings, Public profile, Route alerts, Notifications, Language, Appearance, Terms of service, Privacy policy (open in browser), Sign out, app version.
- **Language**: "App language" (stored on the phone; device language, English, French, Arabic with right-to-left) and "Email language" (saved to the account; used for payments, verification, deliveries, disputes, security emails).
- **Appearance**: Match device, Light, Dark.
- **Notifications**: "Enable notifications" asks for system permission. Toggles: Messages, Marketplace activity (offers, matches, journeys, requests). "Essential updates" (payment, delivery, dispute, verification, security) always stay on. The in-app bell keeps working without push.
- **Public profile**: off by default. Switch "Show my public profile" shows first name, verification, rating, completed deliveries, join month and up to three usual routes. Never shown: last name, email, phone, exact addresses.
- Profile has no support-contact row and no edit-name screen. Its "Help and support" section holds only Terms of service and Privacy policy.
<!-- src: mobile/lib/features/profile/*.dart -->

## How does a traveler set up a payout method and get paid?
- Profile > "Payout methods". Preference: **EUR only**, **DZD only**, **Both** (Both: "Stripe-funded deliveries are paid in EUR; Chargily-funded deliveries are paid in DZD."). "Preferences apply to future payouts only."
- **EUR (Stripe)**: "Set up EUR payouts" > pick the legal country (supported list from server; France shown by name; "If your country is not listed, use DZD payouts.") > Stripe onboarding in the browser. States: not set up, setup required ("Resume setup"), "Stripe is verifying your account details", ready ("Manage with Stripe"), needs attention. "Refresh status" rechecks.
- **DZD (CCP / BaridiMob)**: "Set up DZD payouts": First name, Last name, CCP account number (1 to 20 digits), CCP key (2 digits), RIP (20 digits), photo of the full crossed cheque. "Submit payout information". Staff review it: "being reviewed by our team"; ready; "not accepted ... submit a different account in your own name"; correction needed.
- Payout screens: "Payout" with history, detail ("Payout reference", "Associated delivery", "Eligible at", "Sent at", "Paid at", "Protection ends at", "Payout rail": Stripe EUR or CCP Transfer (DZD), and for DZD "Frozen rate: 1 EUR = {rate} DZD").
- Payout statuses: Not yet, Ready, Scheduled, On the way, Paid, Failed, Cancelled, On hold. Reasons: Payout setup required, Profile under review, Profile needs attention, Payout on hold, Dispute open on this delivery, Payout attempt failed, Bank payout was returned, Country not supported for Stripe EUR payouts. Delivery-side labels: Awaiting delivery, Protection period, Awaiting release, Payout ready, Payout sent.
- Timeline: delivery confirmed, 48 hour protection, then payout is released if no dispute is open. A dispute shows "A dispute is open on this delivery, so the payout is on hold until it's resolved." The payout rail follows how the sender paid (Stripe = EUR, Chargily = DZD) subject to the preference. Fee and amount rules: see payments file.
- Empty: "No payouts yet / Complete a delivery and your earnings appear here."
<!-- src: mobile/lib/features/profile/payout*.dart, dzd_setup_screen.dart -->

## How does a user contact support?
- The app has no support chat, email or phone button. Some screens only say "contact support" in text (dispute window closed, email code never arrived, journey paused by staff). Terms and Privacy open the website.
- Outside the app, the website's support page lists four mailboxes (general support, safety and disputes, privacy, payments). In the repo these are placeholders that must be replaced before launch. See messages-and-notices.md.
<!-- src: mobile/lib/features/profile/profile_screen.dart, disputes/dispute_open_screen.dart, l10n/app_en.arb, web/support.html -->

## Not covered here
- Exact fee, deposit and recommended price formulas (see pricing file).
- The server rules behind each "available action" (cancel allowed, dispute allowed, payout rail choice).
- Admin console pages (see console and helper files).
- Push notification delivery details and the full list of notification types.
