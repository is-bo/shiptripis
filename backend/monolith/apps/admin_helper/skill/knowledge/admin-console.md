# Staff admin console

Covers: every page of the staff console (under /admin/), who can open it, what staff can do there, staff roles and capabilities, two-step sign-in, the overview work list, notes, bans, settings revisions and the technical admin.
Related files: settings-and-helper.md, accounts-and-verification.md, deliveries.md, problems-and-disputes.md, money.md, pricing.md, reviews.md, trips-and-matching.md

## How is the console organised, and who can do what?
- The console lives under `/admin/`. Staff sign in with email and password, then pass a second step (see two-step section).
- Access is by role. A role is a fixed list of capabilities. No one can give a person a custom list. One role per staff member.
- Every page checks a capability. A page a role cannot open answers "Your staff role does not include access to this area or action." (403). The side menu hides pages the role cannot open.
- A Super Admin (technical superuser flag) passes every capability check.
- A banned or disabled staff account loses access at once, on its next request.
- Every action that changes something writes an audit row (who, what, which record, reason, when). Audit rows cannot be edited or deleted.
<!-- src: backend/monolith/apps/admin_panel/permissions.py, console_views.py, models.py -->

## What roles exist and which capabilities does each have?
Five roles: Super Admin, Ops, Support, Finance, Trust / Verification. (No others.)

| Role | What it is for | Capabilities |
|---|---|---|
| Ops | Marketplace operations | view_dashboard, view_requests, manage_requests, view_journeys, manage_journeys, view_matches, manage_matches, view_deals, manage_deals, manage_lifecycle, view_operational_incidents, view_support_context, view_ratings, view_boosts, view_audit_log, record_no_show, view_disputes, manage_disputes, view_provider_health |
| Support | Helping members | view_dashboard, view_users, view_requests, view_journeys, view_deals, view_support_context, manage_cancellations, view_ratings, view_audit_log, view_disputes |
| Finance | Money | export_finance, view_finance_summary, view_payout_sensitive, view_payout_evidence, review_payout_profiles, manage_payout_holds, retry_payouts, view_dashboard, view_deals, view_payment_orders, view_payment_attempts, view_provider_events, issue_refunds, settle_manual_refunds, view_payouts, settle_payouts, reconcile_finance, view_scheduled_jobs, view_provider_health, view_audit_log, view_disputes, resolve_disputes |
| Trust / Verification | Identity, tickets, evidence, reviews | attest_payout_identity, manage_payout_holds, view_dashboard, view_users, view_user_sensitive, view_kyc, review_kyc, view_flight_proofs, review_flight_proofs, view_evidence, review_safety, record_no_show, view_deals, view_audit_log, view_disputes, manage_disputes, moderate_ratings, moderate_chat |
| Super Admin | Owner | Every capability, including the ones only Super Admin holds |

Capabilities only Super Admin holds: manage_users (account ban, hide profile), view_settings, manage_settings (settings, sea crossings), manage_admins and manage_permissions (staff management), plus technical records.
Role descriptions shown on the Staff page: Ops "Runs marketplace operations"; Support "Views users, Deals and disputes for support. Cannot review private verification evidence or change finance settings"; Finance "Cannot read private evidence"; Trust "Reviews KYC, ticket proofs and dispute evidence"; Super "Owner access to every console area, staff roles and business settings."
Important gaps: Finance cannot change a dispute's review state (no manage_disputes) but can resolve one. Ops and Trust can change a dispute's state but cannot resolve it. Only Trust and Super can open private evidence (view_evidence). Ops has no view_users, so no Users list (Ops can still open a person page from a Deal).
<!-- src: backend/monolith/apps/admin_panel/permissions.py, console_views.py (ROLE_DESCRIPTIONS) -->

## Where do I do X, and who can? (page map)
Menu sections: Overview, People, Verification, Marketplace, Disputes, Finance, Staff, Settings, System, Reference.

| Page (menu name) | URL under /admin/ | Gate (any one) | Roles | What staff do there |
|---|---|---|---|---|
| Overview ("What needs attention") | `` (empty) | view_dashboard | all | See the work list, provider status, last 6 audit rows, AI helper card |
| AI helper | `ai-helper/` | view_dashboard | all | Own helper keys, changes waiting for confirmation (see ai-helper) |
| Users | `users/` | view_users | Support, Trust, Super | Search/filter members, open a person |
| Person profile | `users/<id>/` | any of view_users, view_kyc, view_deals, view_disputes, view_payouts, view_finance_summary, review_payout_profiles, attest_payout_identity, view_payment_orders, view_payment_attempts | most roles | One page per member (tabs below) |
| Verification (ID tab) | `verification/kyc/` | view_kyc | Trust, Super | Decide ID checks |
| Verification (Tickets tab) | `verification/flight-proofs/` | view_flight_proofs | Trust, Super | Decide flight and ferry ticket proofs |
| Payout identity checks | `verification/payout-identity/` | attest_payout_identity | Trust, Super | Confirm a traveler's legal name for DZD payout approval |
| Reported reviews | `trust/reviews/` | moderate_ratings | Trust, Super | Decide reported reviews |
| Reported chat messages | `trust/chat-reports/` | moderate_chat | Trust, Super | Dismiss reports, remove or restore a reported message |
| Delivery requests | `marketplace/requests/` | view_requests | Ops, Support, Super | Read only list |
| Journeys | `marketplace/journeys/` | view_journeys | Ops, Support, Super | Read; pause/resume needs manage_journeys (Ops, Super) |
| Deals | `marketplace/deals/` | view_deals | Ops, Support, Finance, Trust, Super | Read; record no-show (Ops, Trust, Super); notes |
| Disputes | `disputes/` | view_disputes | Ops, Support, Finance, Trust, Super | Read; change state; resolve |
| Problems | `disputes/problems/` | view_disputes | same | Acknowledge or close reports (manage_disputes) |
| Finance Overview, Payouts, Manual DZD, Refunds & disputes, Reconciliation | `finance/dashboard/`, `finance/payouts-hub/`, `finance/manual-dzd/`, `finance/exceptions/`, `finance/reconciliation/` | view_finance_summary AND the server flag FINANCE_DASHBOARD_ENABLED | Finance, Super | Read-only workspace; the flag defaults to off (page then answers 404 and is hidden from the menu) |
| Payout method reviews | `finance/payout-reviews/` | review_payout_profiles; always in the menu, but works only when the server flag PAYOUT_PROFILES_ENABLED is on (default off; the page then says "Payout method reviews are not enabled") | Finance, Super | Approve, reject, ask correction |
| Exports | `finance/exports/` | export_finance | Finance, Super | Download CSV |
| Payments | `finance/payments/` | view_payment_attempts or view_payment_orders | Finance, Super | Read; reconcile, resolve |
| Refunds | `finance/refunds/` | issue_refunds or settle_manual_refunds | Finance, Super | Request; settle by hand |
| Payouts (raw list) | `finance/payouts/` | view_payouts | Finance, Super | Open a payout; recovery actions |
| Payout accounts | `finance/payout-accounts/` | view_finance_summary | Finance, Super | Read-only Stripe setup state |
| Ledger | `finance/ledger/` | reconcile_finance | Finance, Super | Read ledger transactions |
| Staff & access | `staff/` | manage_admins | Super | Invite, change role, enable/disable, reset two-step |
| Business settings | `settings/` | view_settings | Super | Read and change settings |
| Health | `system/` | view_provider_health, view_operational_incidents or view_scheduled_jobs | Ops, Finance, Super | Status of database, Redis, storage, providers, jobs, email |
| Background jobs | `system/jobs/` | view_scheduled_jobs or view_operational_incidents | Ops, Finance, Super | Retry or resolve failed jobs |
| Email queue | `system/email/` | view_provider_health | Ops, Finance, Super | See failed or pending email |
| Geography catalogue | `system/geography/` | view_operational_incidents or view_journeys | Ops, Support, Super | Read; sea crossings (Super) |
| Audit log | `audit/` | view_audit_log | Ops, Support, Finance, Trust, Super | Search who did what |
| Technical records | `technical/` | Super Admin (superuser) only | Super | Django model admin |
When the Finance flag is off, the raw Payouts, Refunds, Payout accounts and Ledger pages appear in the menu instead; when on, the five Finance workspace pages replace them in the menu (the raw pages still work by URL).
<!-- src: backend/monolith/apps/admin_panel/console_urls.py, apps/core/templatetags/shiptrip_admin.py, config/settings/base.py -->

## How does staff sign-in with two steps work?
- Every staff account signs in with password, then a 6-digit code from an authenticator app (time-based, new code every 30 seconds, one step of tolerance either side). Until the code is passed, every page under /admin/ redirects to the two-step page and returns to the requested page afterwards. Open without it: sign-in, sign-out, the two-step pages and invitation acceptance.
- First sign-in: "Set up two-step sign-in" shows a QR code and the same key as text. The person enters a code to prove the app has it. Then "Save your recovery codes" shows 10 recovery codes once (format xxxx-xxxx-xxxx-xxxx). They are never shown again.
- Later sign-ins: "Two-step sign-in" asks for the code. A code cannot be used twice (a code for an already-used or earlier step is refused).
- Wrong code message: "That code did not work. Check that the time on your phone is set automatically, then try the newest code."
- Lockout: 5 wrong codes in a row lock the second step for 15 minutes (audit row `admin.two_step_locked`).
- Recovery code: "Use a recovery code" page. Each works once. Wrong or used: "That recovery code did not work, or it was already used." After using one, the person is told how many of 10 are left; at 3 or fewer they are told to ask a Super Admin to reset their two-step.
- Every password sign-in asks for the code again; verification lives only in that session.
- In production the requirement cannot be switched off (the server refuses to start). The staff JSON API only answers inside a verified console session.
<!-- src: backend/monolith/apps/admin_panel/two_step.py, console_two_step.py, two_step_middleware.py, config/settings/prod.py -->

## What is the "fresh code" rule (10 minutes)?
- Some sensitive steps need a code entered in the last 10 minutes: changing a staff role, resetting someone's two-step, and creating an AI helper key.
- If the last code is older, the person is sent to the code page with the message "This change needs a code entered in the last 10 minutes. Enter one, then make the change again." The action is not replayed: they come back and do it again.
- The Staff page shows whether a fresh window is open and until when.
<!-- src: backend/monolith/apps/admin_panel/two_step.py (FRESH_MINUTES = 10), console_two_step.py -->

## How do I reset a staff member's two-step?
- Staff page, the member's row, "two-step reset". Super Admin only (manage_admins). Needs a fresh code, a written reason (max 500 characters) and a tick-box.
- Effect: their two-step and recovery codes are deleted, all their live sessions are ended, all their AI helper keys are stopped, one audit row is written. They enrol again at next sign-in.
- Refusals: you cannot reset your own; only a Super Admin may reset a Super Admin; target must be staff; reason required ("A reason is required.").
- Last Super Admin (nobody to reset for them): a server command `reset_admin_two_step <email> --reason "..."` does the same with no actor.
<!-- src: backend/monolith/apps/admin_panel/two_step.py, management/commands/reset_admin_two_step.py -->

## How are staff invited, and how is an invitation accepted?
- Staff & access page, invitation form (Super Admin only): work email, role, email language (English, French, Arabic), valid for 1 to 168 hours (default 24, max 7 days).
- The one-time link is queued as an email. It is never shown in the browser. Only a hash of it is stored.
- Only a Super Admin can invite the Super Admin role.
- The invited person opens the link (`/admin/invitations/accept`), sets a password and optional name (a new account), or signs in first if the email already has an account. Then the role is assigned, staff access is set, and they enrol in two-step at first sign-in.
- Invitation actions on the Staff page (confirm needed): "revoke" (an unused invitation can no longer be used) and "replace" (revokes the old one if still active and sends a new one, with the default 24 hours; an accepted one cannot be replaced).
- Failure message to the invitee is generic: "The invitation could not be accepted. Check the link and password, or contact your administrator."
- First Super Admin: created from the server environment by the bootstrap command (not from the console).
<!-- src: backend/monolith/apps/admin_panel/services.py, console_forms.py, invitation_web.py, models.py -->

## How do I change a staff role, or disable a staff account?
- Staff page, member row. Role change needs manage_permissions (Super only), a fresh code and a confirm tick. It replaces the member's role (one role at a time). Audited as `admin.role_changed`.
- Only a Super Admin may assign the Super Admin role. A Super Admin cannot demote their own account ("A Super Admin cannot demote their own active account."). Demoting another Super Admin removes their superuser flag.
- Disable/enable access (manage_admins): stops sign-in at once, keeps the role. You cannot disable yourself; only a Super Admin may change a Super Admin; only staff accounts.
<!-- src: backend/monolith/apps/admin_panel/services.py -->

## What does the Overview work list show, and what are the severities?
Items are shown only if the staff member can open the page the item links to. Raised items come first, most urgent first, then longest waiting. Items with nothing waiting go below under a "cleared" group so "nothing to do" is never confused with "not checked". Severity: Urgent, Today, or Info (Info means nothing is waiting).

| Item | Counts | Severity rule |
|---|---|---|
| ID checks to review | ID submissions pending | Today; Urgent once oldest waited over 24 hours |
| Tickets to review | Ticket proofs pending | Today; Urgent after 2 hours |
| Open disputes | Disputes open, awaiting evidence or under review | Always Urgent |
| Problems to look at | Problem reports in state Escalated | Always Urgent |
| Reported reviews | Reviews with an open report | Today; Urgent after 72 hours |
| Payout methods awaiting approval | DZD payout methods waiting for review | Today; Urgent after 48 hours |
| Payout identity checks assigned to you | Open checks assigned to this person | Today; Urgent after 48 hours |
| Payments needing finance review | Payment attempts needing attention (unapplied captures, amount or currency anomalies) | Always Urgent |
| Refunds requiring operator action | Refunds needing manual action, pending or processing | Always Urgent |
| Payouts requiring action | Failed payouts, plus eligible manual payouts | Today; Urgent after 24 hours |
| Failed transactional email | Email messages with status failed | Today (never urgent) |
| Background jobs needing attention | Failed, unresolved jobs | Always Urgent |
| Changes waiting for your confirmation | AI helper changes prepared for this admin | Today (never urgent; they expire) |
| Provider configuration warnings | Providers shown in red (enabled without valid configuration) | Always Urgent |
The Overview also shows provider status (for those with view_provider_health), the 6 latest audit rows (view_audit_log) and the AI helper card.
<!-- src: backend/monolith/apps/admin_panel/worklist.py -->

## How does search and filtering work in the console lists?
- Each list has a search box (max 200 characters) and a state filter. Lists show 50 rows per page.
- Searches match: Users by name or email; Tickets by traveler name, email or flight number; Journeys by traveler name or email; Delivery requests by title, sender name or email, or tracking number; Deals by sender or traveler email or tracking number; Disputes by dispute reference, party emails or tracking number; Payments by order reference, payer email, guest email, provider reference or tracking number; Refunds, Payouts by tracking number; Problems by participant email or tracking number; Audit log by action, record type, record id, reason, reference or actor email; Jobs by key, error code or result; Email by message key, kind or number.
- Users filter: Active or Restricted (disabled or banned). Disputes have an "attention" filter (active disputes only). Payments, Payouts, Refunds, Problems, Jobs have an attention view of what needs a person.
<!-- src: backend/monolith/apps/admin_panel/console_views.py, console_problems.py -->

## What does the Person profile show?
Tabs appear only if the role may read that data: Overview; Identity (view_users, view_kyc, review_payout_profiles or attest_payout_identity); Activity (requests, journeys, offers); Deliveries (view_deals); Payments (view_payment_orders or attempts); Payouts (view_payouts, view_finance_summary or review_payout_profiles); Trust & support (disputes, ratings, notifications); Discovery (view_users); Audit (view_audit_log). 20 rows per page.
- Header shows account state (Active, Banned, Sign-in disabled), ID state (ID approved, ID waiting for review, ID rejected, ID expired, No ID submitted) and staff role if any.
- Header actions: "Review payout method", "Review ID", "Ban account" or "Restore account" (Super only).
- No payout account number, ID image or chat content is on this page. Ratings appear only once the product's blind rule has revealed them.
- Discovery tab: public profile state (Visible, Hidden by staff, Turned off by the member, Never set up). "Hide profile" / "Show profile again" needs manage_users (Super) and a reason (max 500); the member is not shown the reason. Hiding overrides their choice until lifted.
<!-- src: backend/monolith/apps/admin_panel/console_people.py, console_discovery.py, people_links.py -->

## How do I ban or restore a member?
- Person profile header, "Ban account" / "Restore account" (`users/<id>/ban/`). Super Admin only (manage_users). Reason required, max 500, internal (the person is not shown it).
- A ban sets banned and disables sign-in: the person is signed out at once and cannot sign in, even mid-delivery. It does not cancel deliveries, move money or release payouts.
- Refusals: "You cannot ban or restore your own account."; "This is a staff account. Staff access is changed on Staff & access, not here."; "This account is already banned." / "This account is not banned."
- Audit actions `account.banned`, `account.restored`.
<!-- src: backend/monolith/apps/admin_panel/console_account.py, staff_actions.py -->

## What are internal notes?
- A card on the Deal, Dispute and Person pages. Staff only, never shown to members and never read by the AI helper.
- Append only: a note cannot be edited or deleted. Max 2000 characters. The newest 50 are shown.
- Who may add: anyone who may open that page (Deal: view_deals; Dispute: view_disputes; Person: any profile capability). Each note writes an audit row `admin_note.added`.
- Notes added through the AI helper are marked as via helper.
<!-- src: backend/monolith/apps/admin_panel/console_notes.py, staff_actions.py, models.py -->

## How do ID checks and ticket checks work in the console?
- Verification inbox, two tabs: ID and Tickets (flight and ferry). Counters show items with state pending (the only "waiting" state). Landing opens the first tab with work.
- Three decisions: Approve; Ask for a new upload (stored as rejected, shown as "New upload requested"); Reject. Ask and Reject need a reason; the person reads it exactly as written ("Say what is wrong, so the person knows what to send next time."). A confirm tick is required.
- Only a pending item can be decided. Repeating the same decision is accepted silently; a different decision on a decided item is refused ("Only a pending KYC submission may be reviewed." / "Only a pending ticket proof may be reviewed.").
- Capabilities: view to open, review_kyc / review_flight_proofs to decide (Trust, Super). Seeing the document images needs view_evidence; if storage cannot be reached the page shows evidence "temporarily unavailable".
- Effects: the member is emailed and notified. Approval of ID sets the member verified (while the approval has not expired).
- Payout identity check: Finance assigns a Trust or Super reviewer; the reviewer confirms the traveler's legal name from their approved ID; the name is stored encrypted and never shown back.
<!-- src: backend/monolith/apps/admin_panel/verification_inbox.py, services.py, console_identity_checks.py -->

## How do I handle Deals, no-shows, journeys and requests?
- Deals page lists tracking number, parties, route, Traveler reward, Wassla fee, Sender total, payment state, lifecycle status and protection ("Dispute open · payout frozen", "Protected until <time>", or the payout status). Deal statuses: Offer accepted, Payment required, Funded, Pickup ready, Picked up, In transit, Delivery ready, Delivery confirmed, Protection window, Completed, Cancelled, Expired, Payment failed, Disputed, Refunded, Partially refunded.
- Deal page shows route, money terms, events timeline, payments, problems, schedule changes, audit rows (if view_audit_log) and notes.
- Record a no-show: `marketplace/deals/<id>/no-show/`, capability record_no_show (Ops, Trust, Super). Offered only on a funded or pickup-ready deal with pickup not confirmed and no no-show already recorded. Needs who did not come (sender or traveler) and a note (required, max 255). Traveler no-show: by default the sender gets back everything collected, the delivery becomes Refunded (Cancelled if nothing was collected), the trip space is released and the codes stop working. Sender no-show: by default only the record is written; no money moves and the delivery status does not change. The console form has no override; the staff API can override the refund choice. Repeating changes nothing. Recording a no-show closes that delivery's open no-show reports.
- Journeys: pause or resume (manage_journeys: Ops, Super) with a reason (max 500, internal). A pause removes the journey from discovery and blocks new offers; pending offers cannot be accepted until resumed; funded deals are unaffected. The traveler only sees "contact support". A staff pause can only be lifted by staff. Allowed on active and not-yet-live journeys.
- Delivery requests and Journeys pages are read only lists (filters by status).
<!-- src: backend/monolith/apps/admin_panel/console_views.py, console_problems.py, console_journey_pause.py, apps/deals/cancellation.py -->

## How do disputes and problem reports work in the console?
- Disputes list: tracking number, parties, claim category, age, state, money at stake, evidence count. States: Open, Awaiting evidence, Under review (active: payout frozen) and Resolved, Closed.
- Change state (Open, Awaiting evidence, Under review): manage_disputes (Ops, Trust, Super), optional note.
- Resolve: resolve_disputes (Finance, Super). Resolutions: Full sender refund, Full traveler payout, Partial split (sender refund amount required; traveler payout optional). The page first shows a preview of the money, then needs an explicit confirm ("Confirm the financial consequence before resolving."). Audited as `dispute.resolved`.
- Open an evidence file: view_evidence (Trust, Super); each open is audited (`dispute.evidence_viewed`).
- Problems (reports parties made on a delivery): kinds sender did not come, traveler did not come, recipient unavailable, parcel does not match, parcel damaged, trip cancelled or delayed, customs delay, other. States: Open, Escalated to staff, Acknowledged, Closed. Escalated at once for parcel damaged, parcel mismatch, sender did not come, traveler did not come. Staff Acknowledge or Close with a reason (manage_disputes). Closing does not change the delivery or money. A live no-show report has a "Record a no-show" link.
<!-- src: backend/monolith/apps/admin_panel/console_views.py, console_forms.py, console_problems.py, apps/problems/models.py -->

## How do reported reviews work?
- Reported reviews page (moderate_ratings: Trust, Super): reviews with reports, open ones first. Report reasons: Offensive, Contains personal information, Not about this delivery, Untrue, Other.
- Four decisions, each with a required reason (max 500, internal): Dismiss the reports (review unchanged); Hide the comment (score still counts; text replaced by "Comment removed by Wassla"); Remove the rating (leaves public averages and lists; the rated person still sees it marked "Removed by Wassla, not counted"); Lift the decision (review shown as written again).
- The reporter's identity is visible to staff only; the author is never told who reported.
<!-- src: backend/monolith/apps/admin_panel/console_reviews.py, apps/ratings/moderation.py -->

## How do reported chat messages work?
- Reported chat messages page (moderate_chat: Trust, Super): messages members reported, open ones first. Only reported messages and the 5 before and after each are shown. See messages-and-notices for reasons and blocking.
- Three decisions, each with a required internal reason (max 500, audited as `chat.reports_dismissed`, `chat.message_removed`, `chat.message_restored`): Dismiss the reports; Remove the message (members see "Removed by Wassla"); Restore the message.
<!-- src: backend/monolith/apps/admin_panel/console_chat_reports.py, apps/chat/moderation.py -->

## How do payments, refunds and payouts work in the console?
- Payments (Finance, Super): list of payment attempts; canonical EUR leads, provider settlement (e.g. DZD) beside it. Attempt states: Created, Checkout pending, Processing, Succeeded, Failed, Expired, Cancelled. Actions (reconcile_finance): "Retry payment reconciliation" (queues a re-check; does not mark paid) and "Resolve payment attention item" (archives the queue item only; unapplied money cannot be dismissed until fully refunded).
- Refunds: "Request refund" (issue_refunds) on a succeeded payment that an order absorbed; amount in EUR (min 0.01) and a reason; refund states Pending, Processing, Succeeded, Failed. "Manual required" refunds are settled by hand (settle_manual_refunds): settlement reference (max 128), optional note, confirm tick that it was sent outside Wassla.
- Payouts: states Not eligible (protection window open, 48 hours), Blocked, Eligible, Scheduled, Processing, Sent, Paid, Failed, Cancelled, Frozen by a dispute. Open holds show as "On hold". The list shows "Waiting on" so staff see which rows need a person.
- Manual DZD payout steps (all four capabilities view_payouts, retry_payouts, view_payout_sensitive, view_payout_evidence: Finance, Super; also needs server flag PAYOUT_DZD_EXECUTION_ENABLED, default off): reveal destination (audited) and open the crossed cheque; "Claim" the instruction; "Begin transfer"; or "Release" the claim before it is committed; then upload the bank receipt with a confirm tick (and a settled tick) to reach Paid. Another operator who already claimed blocks you. Open or clear a hold: manage_payout_holds plus view_payouts (Finance, Super).
- Legacy EUR manual payout: "mark paid" form (settle_payouts) with currency, amount actually sent, reference, FX rate if not EUR, optional receipt URL and notes. Stripe payouts: "Refresh" (reconcile_finance), "Retry bank payout" (retry_payouts, only on a failed one with nothing in flight and no hold), "Flag" opens a Finance hold (manage_payout_holds).
- Payout method reviews (review_payout_profiles, only when PAYOUT_PROFILES_ENABLED): Approve, Reject, Ask for a correction. Approval needs an approved ID, a complete crossed-cheque photo and a confirmed legal name; a name mismatch needs an explicit accept. Account numbers show only in one audited reveal.
- Finance exports (export_finance): kinds Transactions, Commissions, Payouts; money mode Live, Test or Unknown (never mixed); date range up to 366 days, end not in the future. Streamed CSV with only ids and names, no emails or bank data. Each download is audited with kind, range and line count before sending.
<!-- src: backend/monolith/apps/admin_panel/console_views.py, console_manual_payout.py, console_payout_reviews.py, console_exports.py, exports.py, apps/finance/payout_manual.py -->

## How do background jobs, email and health work?
- Health page: database, Redis, release id, routing provider, storage per kind (parcel photos, ticket proofs, dispute evidence, ID evidence: Reachable, Unreachable, Not configured), payment providers (Enabled; Enabled but unavailable; Configuration incomplete; Configured but disabled; New checkouts disabled; Disabled; with test or LIVE credentials noted), email, job and email counters.
- Background jobs: durable tasks with attempts "n / max". States shown: Pending, Running, Succeeded, Cancelled, Needs attention (failed), Retrying (pending after a failed try), Deferred, or the archive outcome (Resolved, Dismissed, Superseded). Failed ones: "Retry now" or "Resolve or dismiss" with a reason (max 500). Money-related job kinds (deposit expiry refund, payment grace release, attempt expiry, provider reconcile, provider event processing, refund reconcile, payout release check) need reconcile_finance (Finance, Super); other kinds need manage_lifecycle (Ops) or reconcile_finance. Bulk retry or dismiss: 1 to 100 selected failed jobs. Dismissing an email job cancels its pending message.
- Email queue shows kind, state (Pending, Dispatched to the transport, Failed, Cancelled), attempts and next attempt. Bodies, tokens and raw errors are never shown.
<!-- src: backend/monolith/apps/admin_panel/console_views.py, staff_actions.py -->

## How do I change business settings? (settings revisions)
- Page `settings/`, Super Admin only (others cannot open it). Every save creates a new numbered, immutable version and activates it; the previous one is retired and never reactivated. Each save needs a reason (max 500) and a confirm tick, and writes the audit row `settings.version_created` with before and after values.
- Changes apply to future offers/requests from the next request. A Deal already agreed keeps the settings it was priced on.
- Validation runs all policy checks before saving; secrets and credentials cannot be put in settings.
- Forms and ranges:
  - Pricing: commission 0 to 100 percent; posting deposit percent 0 to 100, minimum and maximum EUR (maximum at least minimum); minimum Traveler reward at least 0.01 EUR; weight rate per kg EUR; recommendation multiplier 100 to 500 percent.
  - Boost commission: 0 to 100 percent, future boosts only (the traveler receives the whole boost; the commission is added on top).
  - Chargily exchange rate: DZD per 1 EUR (positive, up to 6 decimals), used for new Chargily attempts only.
  - Provider availability: accept new Stripe payments, allow Chargily, accept new Chargily checkouts. Does not change credentials.
  - Marketplace features: show trips and requests on Home; show public profiles on Home; "I can carry this" signals per traveler per day (1 to 100); tell travelers when a parcel fits (on/off), max travelers told (1 to 100), alerts per traveler per day (1 to 50); allow sea legs (off by default); let travelers set a price, with largest price per kg (1 to 1000 EUR) and largest minimum per parcel (1 to 10000 EUR); proposal response deadline on/off, hours to answer (1 to 168), reminder hours before deadline (0 to 167, shorter than the answer hours).
  - AI helper: on/off, read key hours (1 to 8, default 8), change key minutes (5 to 60, default 30), prepared change waits hours (1 to 72, default 24), calls per minute per key (10 to 300, default 60). Switching it off stops every key for good.
- Read-only on the page: protection and handover guardrails (delivery-code buffer after pickup, payout protection window, payment grace, free-cancellation cutoff, late-cancellation compensation and cap, rating review window, dispute evidence limit), boost minimum and maximum, retired visibility packages, and every stored value with its key. These are not editable on this page.
- The page shows a worked example of the commission using a 30.00 EUR traveler reward from the live engine.
<!-- src: backend/monolith/apps/admin_panel/console_views.py (business_settings), console_forms.py, apps/admin_helper/policy.py, apps/core/business_settings.py -->

## How do sea crossings work in the console?
- Geography catalogue page lists crossings (one direction of a ferry line between two catalogue cities, with kilometres) and the "Sea legs" switch state (set in Business settings, off by default).
- Add, turn on, turn off need manage_settings (Super only) and a reason (max 500). Add: from and to country and city (catalogue names), optional "turn it on straight away" (otherwise saved off). Add the return direction as its own crossing. Refusals include identical ports, missing coordinates, an existing crossing.
- Turning a crossing off stops new sea legs and new offers on journeys using it, from the next request; funded deals are never touched. Nothing changes for members until the crossing is on and the Sea legs switch is on.
<!-- src: backend/monolith/apps/admin_panel/console_sea.py, apps/locations/sea_crossings.py -->

## What is the audit log and the technical admin?
- Audit log page: who (or System), action, object, reason or reference, when. Immutable. Search by actor, action, object or reference. Secret-looking fields are redacted before storage.
- Technical records (`technical/`): the standard Django model admin, Super Admin only ("Technical records are limited to the owner/Super Admin."). Invitations and audit rows there are read only.
<!-- src: backend/monolith/apps/admin_panel/console_views.py, admin.py, services.py -->

## Not covered here
- Default values of business settings: see settings-and-helper.md.
- Whether FINANCE_DASHBOARD_ENABLED, PAYOUT_PROFILES_ENABLED and PAYOUT_DZD_EXECUTION_ENABLED are on in the live deployment (all default off in code).
- Full meaning of each audit action name and each background job kind label.
- Staff JSON API details (`/api/admin/...`) and the AI helper internals.
