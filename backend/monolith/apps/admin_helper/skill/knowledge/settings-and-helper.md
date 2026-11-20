# Business settings and the AI helper

Covers: every business setting an admin can see or change (names, meanings, defaults, limits, who may change them, how a change is saved) and how the admin AI helper works (keys, what it reads, the 21 actions, confirmation, expiry, errors).
Related files: money.md, pricing.md, deliveries.md, problems-and-disputes.md, trips-and-matching.md, admin-console.md, reviews.md

Important for the assistant: the helper has NO endpoint that reads business settings. Values below are the defaults seeded by the migrations. An admin may have changed them since. For a live value say "the default is X; check Settings, then Business settings on the console".

## Who can see and change business settings?
- Console page: Settings, then Business settings. Page name in the task list: "Change the business settings".
- Seeing the page needs the permission `view_settings`. Changing anything needs `manage_settings`.
- Only the Super Admin role holds these two permissions. Ops, Support, Finance and Trust / Verification do not.
- Without `manage_settings` the forms are shown greyed out, and a save is refused: "Business settings management permission is required."
- The AI helper can never change settings (not even the AI helper switch). Settings is on its "never" list.
- Sea crossings (Geography catalogue) also need `manage_settings`.
<!-- src: backend/monolith/apps/admin_panel/permissions.py, admin_panel/console_views.py, admin_helper/actions.py, locations/sea_crossings.py -->

## How is a settings change saved, activated and audited?
- Settings are versions. Each save creates a NEW version (version number = latest + 1) and activates it at once. The old active one becomes retired.
- Exactly one version is active at any time. A retired version can never be activated again.
- A saved version can never be edited or deleted. Values are frozen at creation.
- Each console form copies the active version, changes only its own keys, validates the whole result, then saves. Every form needs a reason (max 500 characters) and a confirm tick.
- Validation runs all the strict readers (matching, payments, lifecycle, marketplace, AI helper). A bad value is refused and nothing is saved.
- The staff API refuses any setting name containing secret, password, token, private_key or webhook ("Provider credentials and secrets are environment-only."). The console forms only write fixed names.
- Activation also refuses pricing distance bands finer than the public distance privacy ladder (100, 300, 750, 1500, 3000, 5000 km maxima, then open). Finer bands would leak location.
- Audit: one audit entry "settings.version_created" with who, reason, before and after values.
- New values apply from the next request. They bind only FUTURE things. A deal, offer or payment already made keeps the numbers it was frozen with (handover, protection window, cancellation terms, review window are copied onto a deal when it is funded).
- A staff API also exists: list the last 50 versions (`view_settings`) and create a version (`manage_settings`). Create takes a full policy object, a commission in basis points, a pricing version label, "activate" and a reason (max 500). Sent without "activate", the version is saved as a draft, and no route activates a draft later.
- A missing or unreadable active version makes money and lifecycle actions refuse (fail closed, a 503-style "settings unavailable" answer).
<!-- src: core/models.py, core/business_settings.py, admin_panel/console_views.py (_save_settings_revision), admin_panel/ops_serializers.py, admin_panel/views.py -->

## Which forms does the Settings page have?
| Form (section on the page) | What it saves |
|---|---|
| Commission, deposit and floors | Commission %, posting deposit %, deposit min, deposit max, minimum traveler reward, weight rate per kg, recommendation multiplier |
| Chargily exchange rate | DZD for 1 EUR |
| Provider availability | Stripe on/off, Chargily on/off, Chargily new checkouts on/off |
| Discovery, routes, prices and proposals | The marketplace switches (below) |
| Admins' own AI assistants | The AI helper switch and its four numbers |
| Boost commission | Wassla commission on boosts |
The page also shows read-only "guardrails" (delivery-code buffer, payout protection window, payment grace, cancellation cutoff and compensation, rating window, dispute evidence limit, checkout and guest-link lifetimes). These are NOT editable on the console. They change only through a full new version via the staff API.
Not on any console form either: matching limits, ranking weights, distance bands, urgency adjustments, reminders, route-change threshold, handover, disputes, ratings tags.
<!-- src: admin_panel/console_forms.py, templates/admin/console/settings.html, core/policy_display.py -->

## Commission and pricing numbers (form "Commission, deposit and floors")
Percent fields are stored in basis points (1% = 100). Money is stored in euro cents.
| Setting | Meaning | Default | Console limits |
|---|---|---|---|
| Wassla commission | Added ON TOP of the traveler reward | 25% (2500 bps) | 0 to 100% |
| Posting deposit % | Recommended deposit = this % of recommended sender total, clamped between min and max | 10% | 0 to 100% |
| Minimum posting deposit | Lower clamp of the recommendation | 3.00 EUR | the form accepts 0, but the payment rules refuse anything under 0.01 EUR; must not be above max |
| Maximum posting deposit | Upper clamp of the recommendation | 7.00 EUR | not below min; at most 1,000.00 EUR |
| Minimum traveler reward (global floor) | No reward below this | 7.00 EUR | at least 0.01 |
| Weight rate per kg | Price per kg in the recommendation | 2.50 EUR | at least 0 |
| Recommendation multiplier | Scales the recommended price | 120% (12000 bps) | 100% to 500% on the form (engine allows 10000 to 100000 bps) |
Worked example (console shows this): traveler reward 30.00 EUR, commission 25% = fee 7.50 EUR, sender pays 37.50 EUR. The fee is rounded UP to the next cent (3.01 EUR reward at 25% gives fee 0.76 EUR).
- The chosen deposit floor (`chosen_min_eur_cents`, default 3.00 EUR) is the minimum a sender may choose for their own deposit. It has no ceiling except the amount owed. Not on a console form.
- Payment timing mode `payments.timing_mode`: `posting_deposit` (default, a deposit is paid when the request is posted) or `after_acceptance`. Not on a console form.
<!-- src: finance/policy.py, matching/policy.py, core/business_settings.py, migrations 0004-0010 -->

## Matching, pricing engine and ranking settings (full-version only)
Defaults (migration 0004 and later). All change only through a full new version.
- Matching: max pickup detour 15,000 m (limit 200,000); max drop-off detour 15,000 m (200,000); max total added distance 30,000 m (500,000); max total added time 3,600 s (86,400); candidates scanned 200 (max 1,000); results returned 50 (max 100, and not above candidates scanned); spatial fallback on.
- Pricing: volumetric divisor 5,000; weight step 0.5 kg; weight rate 250 cents/kg; global floor 700 cents; recommendation multiplier 12,000 bps; reward rounding step 50 cents (max 10,000); detour adjustment 25 cents per km.
- Distance bands (base reward by carried distance): up to 100 km 4.00 EUR; to 300 km 6.00; to 750 km 9.00; to 1,500 km 12.00; to 3,000 km 16.00; to 5,000 km 20.00; beyond 24.00 EUR. Maxima must strictly increase, only the last band is open, and each maximum must be on the privacy ladder.
- Urgency adjustments: slack up to 1,440 minutes adds 3.00 EUR; up to 4,320 minutes adds 1.50 EUR.
- Ranking weights (must be exactly these six, none negative, sum above 0): route fit 30, detour 25, time fit 20, verification 10, freshness 5, neutral reputation 10. Boost points per weight 25, max boost points 200.
- Reservation: payment grace 3,600 s after acceptance (max 7 days).
Rank only orders results after compatibility. A boost never bypasses compatibility.
<!-- src: matching/policy.py, core/migrations/0004_seed_phase2_business_settings.py -->

## Payment settings (section "payments")
| Key | Meaning | Default | Limits |
|---|---|---|---|
| timing_mode | When the sender pays | posting_deposit | posting_deposit or after_acceptance |
| providers.stripe_enabled | Stripe offered | OFF in the pre-launch version | on/off (console) |
| providers.chargily_enabled | Chargily offered to clients | OFF in the pre-launch version | on/off (console) |
| providers.mock_enabled | Test provider | off | works only if the server environment also allows it (`PAYMENTS_ALLOW_MOCK_PROVIDER`, off by default); not on a console form |
| chargily.new_checkouts_enabled | Incident switch: stops NEW Chargily checkouts only; webhooks, refunds, reconciliation continue | OFF in pre-launch | on/off (console) |
| chargily.eur_dzd_rate_micros | DZD per 1 EUR times 1,000,000 | 150.000000 (placeholder, must be set before real use) | up to 100,000 DZD per EUR |
| chargily.min_amount_dzd | Smallest Chargily payment | 75 DZD | 1 to 1,000,000 |
| checkout.attempt_ttl_seconds | Checkout attempt lifetime | 3,600 s (1 h) | 300 s to 7 days |
| guest.link_ttl_seconds | Guest payment link lifetime | 259,200 s (72 h) | 600 s to 30 days; read only on the console |
| payout.protection_window_seconds | Payout protection | 172,800 s (48 h) | 0 to 30 days |
| payout.auto_stripe_enabled | Automatic Stripe payouts | off (manual payout) | on/off |
| posting_deposit.expiry_grace_seconds | Extra time before an unmatched deposit expires | 0 | 0 to 30 days |
- Two Chargily switches differ: "Allow Chargily" removes it from the client list; "Accept new Chargily checkouts" only stops new ones (use in an incident).
- EUR is canonical. The DZD shown on Chargily is the EUR amount times the rate, set by the server. Each payment attempt keeps its own rate snapshot ("Used only for new Chargily attempts; old attempts keep their snapshot").
- The seeded live version (version 5 onward, "pre-launch") has Stripe, Chargily and new Chargily checkouts all OFF. An admin must switch them on in Provider availability ("I checked provider readiness"). Credentials and webhook setup are environment-only, never in settings.
<!-- src: finance/policy.py, core/migrations/0005, 0008, console_forms.py ProviderSettingsForm -->

## Lifecycle guardrails (handover, cancellation, disputes, ratings)
| Key | Meaning | Default | Limits |
|---|---|---|---|
| handover.delivery_code_buffer_seconds | Delivery code locked after pickup | 1,800 s (30 min) | 0 to 7 days |
| handover.code_length | Code characters | 8 | 6 to 16 |
| handover.max_failed_attempts | Wrong tries before a lockout | 5 | 1 to 20 |
| handover.attempt_lockout_seconds | Length of a lockout | 900 s (15 min) | 0 to 24 h |
| handover.max_lockouts | Lockouts allowed | 3 | 1 to 20 |
| handover.attempt_window_seconds | Window for counting tries | 3,600 s | 60 s to 24 h |
| handover.max_attempts_per_window | Tries per window | 12 | 1 to 200 |
| cancellation.sender_free_cutoff_seconds | Sender cancels free if more than this before pickup | 86,400 s (24 h) | 0 to 30 days |
| cancellation.sender_late_compensation_bps | Traveler compensation if later | 10% of traveler reward | 0 to 100% |
| cancellation.sender_late_compensation_cap_eur_cents | Cap on that compensation | 15.00 EUR | 0 to 10,000 EUR |
| cancellation.sender_late_platform_fee_bps | Wassla share of a late cancel | 0% | 0 to 100% |
| disputes.max_evidence_items | Files per dispute | 20 | 1 to 200 |
| disputes.max_evidence_bytes | Evidence size limit | 26,214,400 bytes (25 MB) | 1 KB to 512 MB |
| disputes.allowed_evidence_content_types | Allowed file types | jpeg, png, webp, mp4, quicktime | list, at most 64 |
| disputes.partial_split_fee_mode | Fee on a partial split | proportional | proportional or platform_waives |
| ratings.review_window_seconds | Time to review after delivery | 1,209,600 s (14 days) | 1 h to 365 days |
| ratings.max_comment_length | Comment characters | 1,000 | 1 to 4,000 |
| ratings.allowed_tags | Review tags | communication, punctual, careful_handling, clear_instructions, friendly, late, poor_communication, damaged | list |
- The traveler never gets the delivery code. A dispute freezes payout. The protection window is read from payments.payout.protection_window_seconds (one source for 48 h).
- A change here only touches deals funded after it.
<!-- src: core/phase4_policy.py, core/migrations/0006 -->

## Boost settings (section "boost")
- Boost is the sender's own extra reward on a request. The traveler receives the whole boost; Wassla's boost commission is charged on top. Default boost commission 25% (2500 bps). Editable on the console (0 to 100%, "applies to future commitments only").
- Smallest non-zero boost 1.00 EUR (limits 0.01 to 1,000 EUR); largest 1,000,000.00 EUR (the ceiling). Zero means no boost.
- Ranking weight: weight = boost amount divided by 5.00 EUR (rounded up, at least 1), capped at 30 (max allowed 100). Only affects ranking, after compatibility.
- Old "visibility packages" (24 h, 3 days, 7 days) and traveler_share_bps 75%, min amount 5.00 EUR are left over from the removed paid boost. They stay in the stored settings and are still checked when a settings version loads, but nothing uses them and no boost is sold.
<!-- src: core/phase4_policy.py, migrations 0009, 0010, console_forms.py -->

## Marketplace switches ("Discovery, routes, prices and proposals" form)
Section `marketplace`. Absent means the defaults below. Unknown names are refused. Everything ships ON except sea legs.
| Switch or number | Meaning | Default | Limits |
|---|---|---|---|
| listings_enabled | "Show trips and parcel requests on Home". Off: browsing and "I can carry this" refused ("Browsing requests is not available right now."). Own matches unaffected | on | on/off |
| profiles_enabled | "Show public profiles on Home". Off hides every public profile; members' own choices are kept | on | on/off |
| interest_daily_cap | "I can carry this" signals per traveler per 24 h; each signal notifies the sender once | 10 | 1 to 100 |
| trip_fit_alerts_enabled | Tell travelers when a new request fits their published trip (not an offer; sender still proposes first) | on | on/off |
| trip_fit_max_travelers | Travelers told about one request, best ranked first | 30 | 1 to 100 |
| trip_fit_daily_cap | "A parcel fits your trip" alerts per traveler per 24 h | 5 | 1 to 50 |
| sea_legs_enabled | Allow sea legs | OFF | on/off |
| traveler_pricing.enabled | Travelers may set a price per kg and a per-parcel minimum | on | on/off |
| max_price_per_kg | Typo guard on a traveler's per-kg price | 100.00 EUR | 1.00 to 1,000.00 |
| max_min_price | Typo guard on per-parcel minimum | 500.00 EUR | 1.00 to 10,000.00 |
| offers.response_deadline_enabled | Proposals need an answer by a deadline | on | on/off |
| offers.response_hours | Hours to answer | 6 | 1 to 168 |
| offers.reminder_before_hours | Reminder to the answerer this long before the deadline; 0 means none | 1 | 0 to 167; must be below response_hours |
Not on any console form (full version only):
- reminders: enabled on; depart_after_minutes 30 (5 to 1,440); arrive_after_minutes 60 (5 to 1,440); repeat_after_minutes 180 (15 to 1,440); max_repeats 2 (0 to 5). They ask the traveler "did you depart/arrive?" only for legs that carry a funded parcel.
- route_change.material_shift_minutes 360 (30 to 10,080): a changed arrival or pickup moved more than this needs the sender's consent.
Effects:
- Sea legs OFF: no sea leg can be created, published or matched; offers on a journey with one stop are refused. Funded deals are never touched. Owner must confirm legal and customs rules before ON. An unreadable setting counts as OFF.
- Traveler pricing OFF: no new price can be set, none shown or pre-filled. Wassla's minimum still applies and the fee is still added on top. Existing offers and deals keep their amounts.
- Proposal deadline: deadline = time sent plus response_hours, or the pickup time if sooner. Unanswered, the proposal expires for both; nothing was reserved or charged. After the deadline it cannot be accepted, countered, declined or withdrawn ("offer_expired"). Off: new proposals have no deadline; those that have one keep it.
- Daily cap reached: "You have reached today's limit. Try again tomorrow."
<!-- src: core/marketplace_policy.py, console_forms.py MarketplaceFeaturesForm, matching/offer_deadlines.py, discovery/interest.py, trips/progress.py -->

## What AI helper settings exist?
Section `admin_helper`, form "Admins' own AI assistants". Absent means defaults. The helper ships ON.
| Setting | Meaning | Default | Limits |
|---|---|---|---|
| enabled ("AI helper is on") | Master switch | on | on/off |
| read_key_hours | Life of a read key | 8 hours | 1 to 8 |
| change_key_minutes | Life of a change key | 30 minutes | 5 to 60 |
| prepared_action_valid_hours | How long a prepared change waits for its admin | 24 hours | 1 to 72 |
| requests_per_minute | Calls per key per clock minute | 60 | 10 to 300 |
- Read at each call. A new duration applies only to keys or changes created afterwards (a key's expiry is fixed at creation).
- Switching OFF stops every key at once and for good, and expires every waiting change. Switching ON again revives none of them. The success message says "The AI helper is off: every key stopped." One audit entry records how many keys stopped and changes expired.
- With the switch off, no key can be created, and prepared changes are read only (cannot be confirmed or rejected).
<!-- src: admin_helper/policy.py, admin_helper/console.py, admin_helper/keys.py -->

## What is the AI helper?
- An admin pastes a key into their own AI assistant. The assistant then calls Wassla's helper API as that admin, with exactly that admin's rights at the moment of each call (rights are re-read every call, so a downgrade or ban applies at once).
- A key opens only the helper API (seven routes: guide, briefing, queues, records, search, tasks, actions). It opens nothing else and a console session opens no helper route.
- Two key kinds:
  - Read key: starts with `wslr_`, lasts 8 hours by default. Reads only.
  - Change key: starts with `wslw_`, lasts 30 minutes by default. May do the 21 actions.
- Wassla stores only a fingerprint of the key and its last four characters. The key itself is shown once.
<!-- src: admin_helper/keys.py, models.py, views.py -->

## How does an admin create, copy and stop a key?
- Where: the "AI helper" card on the console Overview, or the AI helper page. Buttons: "Create read key (8 hours)", "Create change key (30 minutes)" (the numbers follow the settings), "Stop key".
- Anyone with console access (staff, active, not banned) can create their own keys. A key is always the creator's own.
- Creating needs a fresh two-step code entered in the last 10 minutes. If not: "Creating a key needs a two-step code entered in the last 10 minutes." and the admin is sent to enter a code, then must press again.
- After creating, the page shows once a single line `/wassla <helper address> <key>` with a Copy button and the expiry time. It is never shown again, stored or logged. If lost, create a new key.
- One live key per admin per kind. Creating a new one stops the old one of the same kind (reason "Replaced by a new key"). Changes the old key prepared stay waiting.
- Stop: the admin stops their own key from the card or page. A Super Admin (`manage_admins`) can stop any admin's key from the AI helper page, and must write a reason ("A reason is required."). Messages: "Your key ending xxxx is stopped. It no longer works."
- Stopped early (own or by a Super Admin): changes it prepared expire with it.
- A key also ends when: it expires (never extended by use); the admin's two-step is reset (reason "Two-step sign-in was reset"; also expires their waiting changes); the helper is switched off; the admin loses console access.
- Key states on the page: Active until time, Expired, or the stop reason.
- The AI helper page also lists: changes waiting, recent decisions (20), the admin's keys, their last 50 calls (time, method, path without query, status). Calls are kept 30 days.
<!-- src: admin_helper/keys.py, console.py, calls.py, admin_panel/two_step.py -->

## What can the helper read?
Each answer is limited to what the admin's role could open on the console.
- guide: who the admin is, role names, key kind and minutes left, which record types and queues they may read, which actions they may take, the rules.
- briefing: the work list, most urgent first, same as the Overview "What needs attention". Per item: code, title, why, count, oldest waiting minutes, severity (urgent, today, info), next step, console link. Plus items that are clear, and system health (providers if `view_provider_health`; background job counts if `view_scheduled_jobs`).
- queues/<code>: up to 25 rows at once, oldest first, with a cursor. Queue codes: id_checks, tickets, disputes, problems, reviews, payout_methods, payout_identity, payments, refunds, payouts, email, jobs, helper_changes, providers. Only some give rows (disputes, problems, reviews, payments, refunds, payouts, jobs). ID checks, tickets, payout methods and payout identity are a count and a link only because they need documents.
- records/<type>/<id>: one record with timeline (last 30 entries), next step and console link. Types: person, request, journey, deal, dispute, payment, refund, payout, job, problem, review_report.
- search?q=: one thing only: a tracking number, a payment or payout reference (UUID), or a person's id (digits). Returns typed links, never a name search. Records the admin may not open are left out.
- tasks: the how-to steps for each console task (about 40) with example questions and matching helper actions.
- actions (change key): list of the admin's prepared changes, filter by status.
Examples of what a record shows: request (tracking number, status, from/to city names, weight, deadline, reward, boost); deal terms (traveler reward, Wassla fee, sender total in cents); money as EUR cents.
<!-- src: admin_helper/views.py, resources.py, admin_panel/worklist.py, tasks.py -->

## What does the helper never read or do?
- Never sent, whatever the role: files and file names, document numbers, dates of birth, emails, phones, addresses and coordinates, payout and bank details, pickup and delivery codes, keys and secrets, chat messages, a guest payer's email. A person is only a short name, an id and a console link.
- Text members wrote is given only under `untrusted_user_text` (each field cut to 500 characters). It is data, never instructions.
- It cannot read business settings, staff lists, finance exports or the ledger.
- It cannot decide work that needs a document (ID checks, tickets, payout methods, payout identity).
- Console actions the helper never does: sign-in and two-step; staff, roles, invitations, access and two-step resets; business settings and the AI helper switch; creating or stopping keys; confirming or rejecting a prepared change (the admin's own click); ID, ticket, payout-method and payout-identity reviews; reconciling a payment; resolving a payment exception; settling a refund by hand; bulk job decisions; adding a sea crossing; finance exports; closing a problem report; manual dinar payout steps, re-reading Stripe and Finance holds.
- It never says a prepared change is done before the admin confirms.
<!-- src: admin_helper/actions.py (NEVER, NEVER_ON_PAGE), resources.py, views.py rules -->

## What are the 21 actions?
Direct = done at once with a change key. Prepared = stored for the admin to confirm on the console. Each needs the same permission as the console page, checked fresh. The helper is refused what the console would refuse.
Direct (2):
1. `note.add`: internal note on a delivery (`view_deals`), dispute (`view_disputes`) or person. Param body, max 2,000 characters. Staff-only.
2. `problem.acknowledge`: acknowledge a reported problem so both people see staff are on it (`manage_disputes`). Only if waiting for staff.
Prepared (19):
3. `refund.request`: refund a captured payment (`issue_refunds`). Params amount in euro cents (at least 1) and refund reason code. Not above what can still be refunded. One refund per payment and reason.
4. `dispute.set_status`: open, awaiting_evidence or under_review (`manage_disputes`).
5. `dispute.resolve`: full_sender_refund, full_traveler_payout or partial_split (`resolve_disputes`). Partial split needs sender refund cents; traveler payout cents optional. The server shows the money split before confirm.
6. `deal.record_no_show`: party sender or traveler (`record_no_show`). Traveler no-show: sender refunded in full and the delivery cancelled. Sender no-show: nobody refunded. Only for a funded delivery waiting for pickup.
7. `user.ban` and 8. `user.unban`: (`manage_users`). Ban signs the person out; deliveries, payments, payouts untouched. Refused for your own account, for staff accounts, and when already in that state.
9. `profile.hide` and 10. `profile.show`: public profile in discovery (`manage_users`). Show returns to the member's own choice.
11. `journey.pause` and 12. `journey.resume`: (`manage_journeys`). Paused: out of discovery, no new offers; paid deliveries unaffected. Resume only if staff paused it.
13. `sea_crossing.activate` and 14. `sea_crossing.deactivate`: (`manage_settings`).
15. `job.retry` and 16. `job.resolve`: failed background jobs (`reconcile_finance` or `manage_lifecycle`; Finance decides money jobs, Finance or Ops the rest). Resolve takes resolution resolved, dismissed or superseded. Only a failure nobody has decided yet.
17. `payout.retry`: retry a failed Stripe bank payout (`retry_payouts`). Only failed, nothing in flight, no Finance hold.
18. `review.hide_comment`, 19. `review.remove`, 20. `review.dismiss_report`, 21. `review.lift`: (`moderate_ratings`). Hide keeps the score; remove drops the rating from all averages; dismiss leaves it; lift shows as written.
Request body for POST actions: {"action", "target": {"type","id"}, "params", "reason"} and nothing else. Reason is required, max 500 characters, except `deal.record_no_show`, where the reason is the no-show note and is capped at 255 characters. Targets types: deal, dispute, person, problem, payment, journey, sea_crossing, job, payout, review_report.
<!-- src: admin_helper/actions.py, prepared.py, admin_panel/staff_actions.py -->

## How is a prepared change confirmed?
1. The assistant POSTs the action. Answer: status "waiting", an id, the server's own summary, `expires_at`, and a `confirm_url`. HTTP 201 (200 if the same change was already waiting with same values). Nothing has changed yet.
2. The admin opens the link (console page "AI helper", change page). It shows the server's summary, the record, values in words, and the helper's reason in a box marked as AI-written.
3. The admin writes their own reason (pre-filled, editable) and presses Confirm, or Reject (no reason needed). Only the admin whose key prepared it may decide.
4. On confirm the server re-checks: console session passed two-step, not expired, helper on, permission now, the console's own validation, and that the record is unchanged since preparation. Then it runs the same function the console runs, as that admin, and audits it "via ai_helper".
5. If anything differs the change is marked failed: "This no longer applies: <why>". For a dispute resolution, a different computed money split also fails it. Example reasons: "the record changed after the AI helper prepared this change. Look at it again.", "your role no longer allows this change."
Statuses: waiting, confirmed, rejected, expired, failed ("No longer applied").
- Only one waiting change per admin, action and record. Same values again returns the waiting one. Different values: 409 `admin_helper_action_already_waiting` until decided.
- Expiry: 24 hours by default (setting 1 to 72). After that: "Nobody confirmed it in time." / "This change expired before it was confirmed." No audit row for an expiry. A waiting change past its time is already shown as expired.
- Also expired when its key is stopped early, two-step is reset, or the helper is switched off (the page says why).
- Work list item "Changes waiting for your confirmation" is a count and a link (severity today).
<!-- src: admin_helper/prepared.py, views.py, console.py -->

## What do the helper's errors mean?
All JSON with `code` and `detail`.
| HTTP | code | Plain meaning |
|---|---|---|
| 401 | `admin_helper_key_invalid` | Key does not work: unknown, expired, stopped, helper off, bad format, missing header, or admin lost access. Never says which. Create a new key. |
| 403 | `admin_helper_forbidden` | The admin's role does not allow this; the console would refuse too. |
| 403 | `admin_helper_change_key_required` | A read key tried to use actions. A change key is needed. |
| 404 | `admin_helper_not_found` | No such record, queue or record type. |
| 400 | `admin_helper_bad_request` | Bad query (limit not 1 to 25, bad cursor, bad search text over 64 characters or not a reference). |
| 400 | `admin_helper_action_invalid` | Bad body, unknown fields, wrong parameter, reason missing or too long. |
| 400 | `admin_helper_action_unknown` | No such action. |
| 409 | `admin_helper_action_already_waiting` | Same action on the same record is already waiting with other values. |
| 409 | `admin_helper_action_not_offered` | The console would not offer this now (for example the dispute is already finished, or the profile is already hidden). |
| 409 | other domain code | The console's own rule refused it; the message is the staff-facing sentence. |
| 429 | `admin_helper_rate_limited` | Over the per-minute limit (default 60). "Wait one minute." A Retry-After header is sent. |
Other: only GET, plus POST on actions; other methods are refused. Every response is not cached. When the settings cannot be read, every key is refused as 401.
Key creation errors on the console: `admin_fresh_two_step_required`, `admin_helper_disabled` ("The AI helper is switched off."), `reason_required`.
<!-- src: admin_helper/api.py, views.py, keys.py, prepared.py -->

## Audit trail of the helper
- Rows: ai_helper.key_created, ai_helper.key_stopped, ai_helper.keys_stopped (switch-off), ai_helper.action_prepared, ai_helper.action_rejected, ai_helper.action_failed. Direct and confirmed actions write the console action's own rows plus a marker "via ai_helper" with the key id and prepared change id.
- Read the audit log on console page "See who did what" (`view_audit_log`).
<!-- src: admin_helper/keys.py, prepared.py, admin_panel/services.py -->

## Not covered here
- The live active settings values (the helper cannot read them; only defaults here).
- How each pricing, fee, payout and cancellation rule is applied inside a deal (see the pricing, payments and deals files).
- Which settings version number is live in production after the last edit.
- Sidebar wording for every page: see admin-console.md.
