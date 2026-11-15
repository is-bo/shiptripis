# Problems, no-shows, disputes, route changes and cancellations

Covers: what happens when a delivery goes wrong: problem reports, "did not come" reports and the staff no-show decision, disputes and their money settlement, traveler time changes, and cancellation consequences.
Related files: money.md (payout protection, how payouts are released, refunds), pricing.md (commission, reward, boost), deliveries.md (statuses, pickup and delivery codes), trips-and-matching.md (journeys, schedule changes), admin-console.md (roles, capabilities), settings-and-helper.md (settings page, how the helper prepares actions)

## What is the difference between a problem report, a no-show report and a dispute?
- A problem report is a statement. It is recorded, the other person is told, and the serious kinds go to staff. It never changes the delivery and never moves money.
- A "did not come" report is a problem report of a special kind, for a missed pickup. Only staff can turn it into a decision (the no-show action).
- A dispute is the only thing that can stop a payout and the only thing that can move money after pickup. Only staff decide it.
- Before pickup there is no dispute: the answer is cancelling or a no-show decision. After pickup there is no cancelling: the answer is a dispute.
<!-- src: backend/monolith/apps/problems/models.py, backend/monolith/apps/deals/cancellation.py, backend/monolith/apps/disputes/services.py -->

## Which problem kinds exist, and which go straight to staff?
| Kind (label in app) | Goes to staff at once? |
|---|---|
| `sender_unavailable` (The sender did not come) | Yes |
| `traveler_no_show` (The traveler did not come) | Yes |
| `parcel_damaged` (The parcel is damaged) | Yes |
| `parcel_mismatch` (The parcel is not what was described) | Yes |
| `recipient_unavailable` (The recipient is not available) | No |
| `trip_disrupted` (The trip is cancelled or delayed) | No |
| `customs_delay` (Held up at customs) | No |
| `other` (Something else) | No |
- "Goes to staff" means status `escalated` from the start. The others start as `open`: the other person is told, but staff are not asked to act. Staff can still open, acknowledge and close an `open` report from the Problems page.
<!-- src: backend/monolith/apps/problems/models.py, mobile/lib/l10n/app_en.arb -->

## Who can report a problem, and when?
- Only the sender or the traveler of that delivery. Anyone else gets "No such delivery." (404, `not_a_party`).
- General kinds: while the delivery is `funded`, `pickup_ready`, `picked_up`, `in_transit` or `delivery_ready`. Not before funding, not after delivery.
- Refusal wording: "Problems can be reported from funding until delivery. After delivery, open a dispute instead." (`problem_report_not_allowed`).
- Note: optional, up to 1,000 characters (`problem_note_too_long`: "A note can be 1000 characters at most."). Both people and staff read the note.
- One live report per person, per delivery, per kind. Sending the same one again returns the existing report instead of making a second one.
- The other person gets a live notification ("A problem was reported on a delivery").
- App: the delivery screen shows a "Problems reported" list and a "Report a problem" button. The sheet says: "The other person is told. Wassla staff look at damage and mismatches right away. Reporting does not cancel or refund anything."
<!-- src: backend/monolith/apps/problems/services.py, backend/monolith/apps/problems/views.py, mobile/lib/l10n/app_en.arb -->

## When can someone report "the other person did not come"?
- Only the person left waiting: the traveler can report `sender_unavailable`, the sender can report `traveler_no_show`. Anyone else gets 403 "Only the person who was left waiting can report this." (`problem_kind_not_allowed_for_role`).
- The window opens at the agreed pickup time and stays open until pickup is confirmed. The delivery must be funded and in `funded` or `pickup_ready`.
- If not allowed now the answer is "This cannot be reported right now." (`no_show_report_not_allowed`) with one reason:
  - `pickup_already_confirmed`: pickup was confirmed.
  - `deal_not_funded`: not paid yet.
  - `deal_not_active`: not in funded or pickup_ready.
  - `no_show_already_recorded`: staff already decided.
  - `pickup_time_unknown`: no agreed pickup time.
  - `pickup_time_not_reached`: too early; the app also gets the time it opens.
  - `already_reported`: this person already has a live report (sending it again just returns that report).
- App wording when refused: "This can't be reported right now. The pickup time may not have come yet, or the parcel may already be collected."
- The app never works out the window itself: the server says whether the button shows.
- The other person sees a banner: "The traveler says you did not come" / "The sender says you did not come", with a "Reply in chat" button, and "Nothing is cancelled or refunded yet."
<!-- src: backend/monolith/apps/problems/services.py, mobile/lib/features/problems/problem_widgets.dart, mobile/lib/l10n/app_en.arb -->

## What do the problem statuses mean?
| Status | Meaning | What users see |
|---|---|---|
| `open` | Recorded, other person told, not in front of staff | "Sent" |
| `escalated` | In front of staff, nobody has looked yet | "With Wassla staff" |
| `acknowledged` | A staff member looked and is on it | "Being looked at" |
| `closed` | Finished | "Closed" |
- Staff reasons (for acknowledging or closing) are internal and are never shown to members. Members see only the new state.
- Acknowledging and closing send only a silent screen refresh, no push.
<!-- src: backend/monolith/apps/problems/models.py, backend/monolith/apps/problems/services.py, mobile/lib/l10n/app_en.arb -->

## How does staff handle a problem report? (console)
- Console page: Disputes, then "Problems" (path `disputes/problems/`). Detail page shows the report, the delivery, and the audit trail.
- Seeing the queue needs `view_disputes`. Acknowledging or closing needs `manage_disputes` (staff roles with it: ops, trust, super admin; support and finance only view).
- The queue shows escalated first, then open, acknowledged, closed; oldest first inside each. The "attention" filter shows only `escalated`. It can be searched by tracking number or participant email.
- Acknowledge: a reason is required (up to 500 characters; the form refuses longer). Allowed on `open` or `escalated`. Acknowledging an already acknowledged report changes nothing. A closed report gives "This report is already closed."
- Close: a reason is required (up to 500 characters). Message: "The problem is closed. The delivery is unchanged." A closed report gives `problem_already_closed`.
- Both are audited and add an entry to the delivery timeline.
- A staff role without `manage_disputes` is refused: "Your staff role cannot handle problem reports."
- A no-show report on the detail page carries a "Record a no-show" link (needs `record_no_show`) with the party pre-selected.
<!-- src: backend/monolith/apps/admin_panel/console_problems.py, backend/monolith/apps/problems/services.py, backend/monolith/apps/admin_panel/permissions.py -->

## How does staff record a no-show, and what happens to the money?
- Console page: the delivery's "Record a no-show" page (`marketplace/deals/<id>/no-show/`). Capability: `record_no_show` (ops, trust, super admin).
- Only on a funded delivery whose pickup was never confirmed (`funded` or `pickup_ready`) with no no-show already recorded. Otherwise the page says it cannot take a decision.
- The form needs "Who did not come" (sender or traveler) and a required note (up to 255 characters), stored on the timeline and audit log.
- Traveler did not come: the sender is refunded in full (everything collected, including boost and any deposit credit), the delivery is cancelled, the reserved space is released, live handover codes are cancelled, the match and the request are cancelled. Delivery status becomes `refunded` (or `cancelled` if nothing was collected). The sender must create a new request and pay a new deposit to ship again. Message: "The no-show is recorded and the sender was refunded in full."
- Sender did not come: only the no-show is recorded. No refund, no cancellation. Message: "The no-show is recorded." The delivery keeps its status (`funded` or `pickup_ready`); nothing in the code then blocks a later pickup or a normal cancellation (with the usual early/late rules). Both kinds count on the person's console page as "No-shows recorded".
- Open no-show reports on that delivery (both kinds) are closed with the reason "No-show recorded by staff: <party>." and point at the audit entry.
- Recording the same no-show twice changes nothing. A no-show after pickup is refused: "A no-show cannot be recorded once pickup was confirmed."
- The staff API (`POST /api/admin/deals/<id>/no-show`) also accepts a `refund_sender` override; the console page has no such option.
- No automatic scoring decides who did not come. It is a manual staff decision.
<!-- src: backend/monolith/apps/deals/cancellation.py, backend/monolith/apps/admin_panel/services.py, backend/monolith/apps/admin_panel/console_problems.py -->

## Who can open a dispute, and when?
- Only the sender or the traveler of the delivery (staff cannot open one from any console page or staff API).
- Window: from the moment the parcel is picked up (`picked_up`, `in_transit`, `delivery_ready`) until the protection deadline after delivery confirmation. The default protection window is 48 hours. It is a stored business setting, shown read-only as "Payout protection window" in the "Lifecycle guardrails" table of the console Business settings page; no console form changes it. Each delivery keeps the deadline it got at delivery confirmation.
- Before pickup: "This parcel has not been picked up yet. Cancel the delivery instead." (`dispute_not_available`).
- After the protection deadline: "The payment protection window for this delivery has closed." (`dispute_window_closed`). The app says: "Disputes can be opened for 48 hours after delivery. Contact support if you still need help."
- If a dispute was already resolved on that delivery, a party cannot open another: "This delivery has already had a dispute resolved. Contact support if something is still wrong." (`dispute_already_resolved`).
- Only one active dispute per delivery. Opening again returns the existing one.
- Needs a category and a description (up to 4,000 characters). Missing description: "Describe what went wrong so the dispute can be reviewed."
- Categories (app label): `not_delivered` (Never arrived), `damaged` (Arrived damaged), `wrong_item` (Wrong item), `late` (Arrived too late), `no_show` (The other person didn't show up), `payment` (Something is wrong with the money), `other` (Something else).
- What opening does at once: the traveler's payout is frozen, a snapshot of evidence references is captured (timeline, offers, terms, payments, handover facts, chat and journey references, no-show record; never the delivery code or recipient contact details), the delivery status becomes `disputed`, protection reminders are cancelled, and both people get an email and live notification.
- Staff cannot open disputes from the console, so a dispute is always opened by the sender or traveler, before protection ends.
- App text: "Opening a dispute puts the traveler's payout on hold while we look into it."
<!-- src: backend/monolith/apps/disputes/services.py, backend/monolith/apps/disputes/models.py, mobile/lib/l10n/app_en.arb -->

## What do the dispute statuses mean?
| Status | Meaning | Party sees | Payout |
|---|---|---|---|
| `open` | Just opened | "Open" | Frozen |
| `awaiting_evidence` | Staff wait for evidence | "Waiting for evidence" | Frozen |
| `under_review` | Staff are deciding | "Being reviewed" | Frozen |
| `resolved` | Decided, money moved | "Resolved" | Per decision |
| `closed` | Filed away, no money decision | "Closed" | Stays as left |
- The first three are "active": evidence is accepted and the payout stays frozen.
- Staff can move a dispute only between open, awaiting evidence and under review. `resolved` and `closed` cannot be reopened ("This dispute is already finished and cannot be reopened.", `dispute_already_finished`). Moving to the same status changes nothing.
- Staff have no way to close a dispute without resolving it: the code has a close step, but no console page, staff API route or helper action uses it. In practice every dispute ends as `resolved`.
<!-- src: backend/monolith/apps/disputes/models.py, backend/monolith/apps/disputes/services.py -->

## What evidence can be added?
- Who: either party, and staff with the evidence capability. Only while the dispute is active ("This dispute is no longer accepting evidence.").
- Kinds: text statement (up to 4,000 characters), photo, video.
- Limits (stored business settings; the item count shows read-only as "Dispute evidence limit" in the console Business settings "Lifecycle guardrails" table, with no form to change it): 20 items, 25 MiB (26,214,400 bytes) per file, types JPEG, PNG, WebP, MP4, MOV (QuickTime). Files are also checked against their real content.
- Evidence cannot be edited or removed. Files open only through a short-lived link (5 minutes).
- Staff view of evidence files needs `view_evidence` and is audited.
- Refusals: "That file type is not accepted as dispute evidence.", "That file is larger than the evidence size limit.", "This dispute already holds the maximum number of evidence items."
<!-- src: backend/monolith/apps/disputes/services.py, backend/monolith/apps/core/migrations/0006_seed_phase4_business_settings.py -->

## How does staff handle a dispute? (console and capabilities)
- Console: Disputes list (filter by status, "attention" shows active ones, search by reference, tracking number or email). The list shows money at stake: the collected total, or the sender total before a decision.
- Dispute detail page: review-state form, resolution form with Preview then Confirm, evidence, timeline, notes.
- `view_disputes`: see (ops, support, finance, trust, super admin).
- `manage_disputes`: change review state (ops, trust, super admin).
- `resolve_disputes`: decide and move money (finance, super admin). Ops and trust cannot resolve.
- Changing the review state has an optional note (up to 4,000 characters). Staff notes stay internal and are removed from what parties see.
- Staff API: `GET /api/admin/disputes`, `POST .../status`, `POST .../resolve`.
<!-- src: backend/monolith/apps/admin_panel/console_views.py, backend/monolith/apps/admin_panel/permissions.py, backend/monolith/apps/disputes/views.py -->

## What resolutions exist and how are the amounts worked out?
Three outcomes. All amounts are in EUR cents; every cent collected is refunded, paid to the traveler, or kept by Wassla, and the three always add up to the collected total.
- `full_sender_refund` ("Refunded to the sender"): sender gets everything back, traveler 0, Wassla 0.
- `full_traveler_payout` ("Paid to the traveler"): no refund. Traveler gets their reward and Wassla keeps its commission, split by the fee mode below.
- `partial_split` ("Split between both sides"): staff enter the sender refund (required, must be more than 0 and less than the total: "A partial split must return some, but not all, of the money."). The traveler payout is optional.
  - If the payout is given, Wassla keeps what is left. A payout bigger than what is left is refused.
  - If not given, the rest is shared by the fee mode.
- Fee mode `partial_split_fee_mode` (frozen on each delivery at funding): `proportional` (default) shares the rest in the ratio the traveler reward and commission were agreed; the traveler takes the rounded-down share, Wassla gets the leftover cent. `platform_waives`: the traveler is made whole first (up to their reward), Wassla absorbs the shortfall.
- Money already paid to the traveler (or committed to a transfer) cannot be taken back. The refund is limited to what the platform still holds ("The sender refund must be between zero and the amount the platform still holds.").
- Worked example (default 25 percent commission on top, no boost): traveler reward 20.00, commission 5.00, sender paid 25.00.
  - Full sender refund: 25.00 / 0 / 0.
  - Full traveler payout: 0 / 20.00 / 5.00.
  - Partial, refund 10.00, no payout entered: remaining 15.00, traveler 15 x 20 / 25 = 12.00, Wassla 3.00.
  - Partial, refund 10.00, payout 10.00: 10.00 / 10.00 / 5.00.
- Delivery status after: refund 0 gives `completed`; refund equal to everything collected gives `refunded`; otherwise `partially_refunded`.
- Live handover codes are cancelled. Both people get an email and live notification. The staff note is shown to parties as "Note from Wassla".
<!-- src: backend/monolith/apps/disputes/services.py, backend/monolith/apps/finance/settlement.py, backend/monolith/apps/core/business_settings.py -->

## What is the settlement planner preview?
- Before resolving, the console asks the same planner that does the real thing what the amounts would be. Nothing is written. It shows: collected from the sender, back to the sender, paid to the traveler, kept by Wassla.
- The real decision re-plans under a fresh lock, so the preview is a guide. The console requires an explicit confirmation ("Confirm the financial consequence before resolving.").
- Resolving twice does nothing the second time: the first decision stands.
- Staff fields are entered in euros (up to 2 decimals); they are converted to cents.
<!-- src: backend/monolith/apps/disputes/services.py, backend/monolith/apps/admin_panel/console_forms.py -->

## What freezes the payout, and what happens to it afterwards?
- Opening a dispute freezes the payout (status `frozen`). A payout still in its 48-hour protection wait, or ready, is pulled back. Nothing is paid while the dispute is active.
- A payout already paid cannot be frozen; the dispute is marked "payout already settled". A transfer already accepted by the payment provider cannot be recalled either; the record notes the exposure for recovery review.
- Resolving sets the payout to the decided traveler amount. A traveler amount of 0 cancels it. If the protection window is still running, the payout waits as not yet eligible; otherwise it becomes eligible (or blocked if it has a block reason).
- The unused close step would not unfreeze anything (no screen calls it, see above).
<!-- src: backend/monolith/apps/finance/payout_release.py, backend/monolith/apps/finance/settlement.py -->

## What is "resolve" versus "set status"?
- Set status (`dispute.set_status`) only moves the review step between open, awaiting evidence and under review. No money moves.
- Resolve (`dispute.resolve`) is the decision: moves money, finishes the dispute, cannot be undone.
<!-- src: backend/monolith/apps/disputes/services.py -->

## What happens when a traveler changes times on a live trip?
- Only times can change (not stops or places). Allowed on a trip that is `active` or `in_progress`.
- Rules: a leg already reported arrived cannot change; a leg reported departed keeps its departure; a new departure must be in the future; a change with no difference is refused ("These are the times already in force."); only one waiting change at a time ("New times are already waiting for senders. Withdraw them first.").
- Every parcel on a changed leg is "affected". It is "material" (the sender must answer) when:
  - the new arrival is after the request's deadline and later than agreed, or
  - the arrival moves more than the margin from the arrival the sender last agreed, or
  - (parcel not collected yet) the pickup departure moves more than the margin, or moves earlier than the agreed pickup time.
- The margin is `material_shift_minutes`, default 360 minutes (6 hours), allowed 30 minutes to 7 days. It is a stored marketplace setting (`route_change`) with no form on the console Business settings page.
- If no parcel is material, the new times apply at once and senders are told. Otherwise the change waits. It applies when every material sender has accepted (or their parcel was collected or is no longer active).
- A sender whose parcel is already collected is informed only, never asked. They can report a problem or open a dispute.
- The traveler can withdraw a waiting change. It is also dropped by itself ("no longer valid") if the trip moves on. A waiting change is re-checked every 30 minutes.
- The sender can accept or decline, and change their answer while it waits.
- The funded arrival, the agreed pickup time and the payout floor stay as frozen at funding.
<!-- src: backend/monolith/apps/trips/schedule_changes.py, backend/monolith/apps/core/marketplace_policy.py, mobile/lib/l10n/app_en.arb -->

## What if the sender declines the new times? (declined change = traveler cancellation)
- Declining cancels nothing by itself. The sender can then cancel through the normal cancel flow.
- While the declined change is still waiting, that cancellation counts as the traveler's: full refund, no compensation, recorded with the reason `declined_schedule_change`. If the traveler withdraws the change, the ordinary rules apply again.
- App: "Counted as the traveler's cancellation, because they changed the times."
<!-- src: backend/monolith/apps/deals/cancellation.py, backend/monolith/apps/trips/schedule_changes.py -->

## What are the cancellation consequences?
- Before payment (`payment_required`): free, nothing to refund. New deals start directly in `payment_required`; the current code never puts a deal in `offer_accepted`. A deal left in `offer_accepted` from old data is refused with "This delivery can no longer be cancelled."
- After funding and before pickup (`funded`, `pickup_ready`): the quote is computed by the server (`GET /api/deals/<id>/cancellation`) and the app only shows it.
  - Traveler cancels: sender refunded in full, no compensation.
  - Sender cancels early (more than 24 hours before the agreed pickup): full refund. The cutoff is a stored business setting, shown read-only as "Sender free-cancellation cutoff" in the Business settings "Lifecycle guardrails" table; default 86,400 seconds (24 hours). Exactly 24 hours before or later counts as late.
  - Sender cancels late (inside the cutoff): the traveler gets 10 percent of their base reward, rounded up, capped at 15.00 EUR; everything else goes to the sender; Wassla keeps nothing. Both are stored business settings shown read-only in the same table ("Late-cancellation compensation", default 10 percent; "Late-cancellation compensation cap", default 15.00 EUR); no console form changes them. The boost bonus is not counted. No agreed pickup time means treated as early.
  - Example: reward 20.00, collected 25.00, cancelled late: compensation 2.00, sender refunded 23.00. Reward 200.00: 10 percent is 20.00, capped to 15.00.
  - The values are frozen on the delivery at funding, so a later change in settings does not alter a quote.
- After pickup: no cancellation. "This parcel has already been picked up. Open a dispute instead." (`cancellation_not_available_after_pickup`).
- Other refusals: `use_pre_funding_cancellation` ("This delivery has not been funded yet; use the standard cancel action."), `deal_not_cancellable` ("This delivery can no longer be cancelled."), `not_authorized` ("Only a party to this delivery can cancel it.").
- After a funded cancellation: status `refunded` (full refund), `partially_refunded` (compensation paid) or `cancelled` (nothing collected). Space is released, live codes cancelled, match and request cancelled (the sender must post a new request and pay a new deposit). Both people get an email.
- A cancellation in progress while pickup is confirmed: whoever commits first wins; the other is refused.
<!-- src: backend/monolith/apps/deals/cancellation.py, backend/monolith/apps/deals/views.py, backend/monolith/apps/core/phase4_policy.py, mobile/lib/l10n/app_en.arb -->

## What can the AI helper do in this area?
| Action | Mode | Needs | What it does |
|---|---|---|---|
| `note.add` | Direct (runs at once) | `view_deals` for a delivery, `view_disputes` for a dispute, a person-page capability for a person | Adds an internal note, up to 2,000 characters. Notes cannot be edited or deleted. Staff only. |
| `problem.acknowledge` | Direct | `manage_disputes` | Acknowledges a report that is `open` or `escalated`; needs a reason (max 500). Both people then see that staff are on it. |
| `dispute.set_status` | Prepared: admin confirms on the console | `manage_disputes` | Moves an active dispute to open, awaiting evidence or under review. |
| `dispute.resolve` | Prepared | `resolve_disputes` | Resolution `full_sender_refund`, `full_traveler_payout` or `partial_split` (with `sender_refund_eur_cents`, optional `traveler_payout_eur_cents`). Shows the planner preview; if amounts change by the time of confirmation it says "This no longer applies". |
| `deal.record_no_show` | Prepared | `record_no_show` | Records `party` sender or traveler; the reason fills the note (max 255). |
- The helper never closes a problem report; staff close it on the console.
- The helper never cancels a delivery, opens a dispute or answers for members.
- Refusals use the console's own rules (for example "This report is not waiting for staff", "This dispute is already finished.").
<!-- src: backend/monolith/apps/admin_helper/actions.py -->

## Is a traveler's cancellation or no-show held against them?
- Nothing scores it. Ranking uses a fixed neutral reputation and no reliability signal.
- What is kept: who cancelled each delivery and any no-show decision. The person's console page shows "No-shows recorded" and "Cancelled by this person" counts.
<!-- src: backend/monolith/apps/matching/ranking.py, backend/monolith/apps/admin_panel/console_people.py, templates/admin/console/person.html -->

## Not covered here
- Exact DZD amounts shown for refunds (DZD conversion is server-calculated at payment; see money.md).
