# Money movement: payments, refunds, payouts, finance console

Covers: how senders pay, how deals get funded, refunds, how travelers are paid out (EUR and DZD), and who can do what in the finance console.
Related files: pricing.md (how the price and commission are set), deliveries.md (deal states, cancellation, delivery code), problems-and-disputes.md (dispute outcomes), admin-console.md (roles, console pages), settings-and-helper.md (Settings page), accounts-and-verification.md (identity checks)

## What currency is money held in?
- EUR is the real currency. Every amount is stored as whole euro cents (1250 = 12.50 EUR).
- DZD (dinars) only appears at the edges: Chargily charges the sender in DZD, and the DZD manual payout pays the traveler in DZD. Both are converted from EUR with the exchange rate setting.
- Conversion: `EUR cents x rate / 100`, always rounded UP to a whole dinar. Example: 12.00 EUR at rate 150 DZD per EUR = 1800 DZD. 12.34 EUR = 1851 DZD (1851.00 exactly, no rounding needed here); 10.01 EUR at 150.25 = 1504.0025 so 1505 DZD.
- The rate is a setting: Settings > "Chargily exchange rate" card, field "DZD for €1" (up to 6 decimals) with a required "Rate source or reason". Stored key `payments.chargily.eur_dzd_rate_micros`, shown read-only as "Chargily EUR→DZD rate". Seeded value 150 DZD per EUR is a placeholder; staff must set it. A rate above 100,000 DZD per EUR is refused as a typing error.
- The rate is frozen on each payment attempt when checkout starts. Changing it later changes nothing already started. The traveler's DZD payout amount is also frozen when the deal is funded (see the DZD payout section for which rate).
- Smallest Chargily charge: 75 DZD (setting `payments.chargily.min_amount_dzd`, no console form). Below it the server refuses with `amount_below_provider_minimum` and the app shows Chargily as "Below this method's minimum".
<!-- src: finance/money.py, finance/policy.py, finance/services.py settlement_amounts -->

## What does a sender pay in total?
- The sender pays the traveler's reward plus the platform commission on top. Commission is 25% (`commission_rate_bps` = 2500), rounded up to the cent.
- Example: reward 8.00 EUR gives commission 2.00 EUR, sender total 10.00 EUR. Reward 8.01 EUR gives commission 2.0025 so 2.01 EUR, total 10.02 EUR.
- The traveler is paid the full reward (plus the whole Boost, if any). The commission stays with the platform.
- A Boost is extra reward the sender adds; it carries its own commission (seeded 25%, `boost.commission_rate_bps`), and the Boost amount plus its commission is added to the single balance the sender pays. See pricing.md.
<!-- src: core/business_settings.py calculate_offer_economics, core/migrations/0003,0010 -->

## What payment obligations ("orders") exist?
Each obligation is a payment order in EUR with a purpose:
| Purpose | Meaning |
|---|---|
| `posting_deposit` | Money paid up front to publish a request |
| `deal_balance` | The deal total, after a traveler offer is accepted |
| `boost` | Not used. There is no paid boost: a Boost is folded into the deal balance. |

Order fields staff see: amount owed, credited (covered by a deposit, no new cash), paid (cash captured), refunded. Outstanding = owed - credited - paid. The database refuses over-collecting and refunding more than was captured.

Order statuses: `pending`, `partially_paid`, `paid`, `refund_pending`, `partially_refunded`, `refunded`, `cancelled`. New checkouts are only possible while `pending` or `partially_paid`.
<!-- src: finance/models.py PaymentOrder -->

## What is the posting deposit and how big is it?
- Default mode is `posting_deposit` (setting `payments.timing_mode`; the other value `after_acceptance` means no deposit). The sender pays the deposit to publish a request; the request stays `awaiting_deposit` until the deposit is paid, then becomes `open`.
- Recommended deposit = 10% (`percent_bps` 1000) of the recommended sender total, kept between 3.00 EUR (`min_eur_cents` 300) and 7.00 EUR (`max_eur_cents` 700). Example: total 20 EUR gives 2.00, raised to 3.00. Total 50 EUR gives 5.00. Total 100 EUR gives 10.00, capped at 7.00.
- The recommendation is based on the straight-line pickup-to-delivery distance with no detour or urgency; Boost does not change it.
- The sender may choose another amount: minimum 3.00 EUR (`chosen_min_eur_cents` 300), maximum the whole obligation (chosen reward + commission + any Boost with its commission). The 7 EUR cap is NOT a limit on a chosen deposit. Errors: `deposit_below_minimum` ("That deposit is below the minimum."), `deposit_above_obligation` ("A deposit cannot exceed the amount it is paid against.").
- A chosen deposit can only be changed while its order is pending, nothing paid, no open checkout (`deposit_checkout_in_progress`: "Finish or abandon the open checkout before changing the deposit.").
- When a traveler's offer is accepted, a paid deposit is credited 100% toward the deal balance (not an extra fee). The credit is used at most once. If the deposit equals the whole total, the deal is funded straight away.
- App text: "If nobody takes it, or you cancel before accepting an offer, you get it back in full." When the request deadline passes unmatched, a scheduled job refunds the deposit (reason "Request expired unmatched"; extra wait `expiry_grace_seconds`, seeded 0).
- Settings keys are in Settings, payments section. Quoted order amounts are frozen on the order, so later setting changes do not alter them.
<!-- src: finance/policy.py, finance/services.py quote_posting_deposit/ensure_posting_deposit_order/apply_posting_deposit_credit, mobile l10n depositRefundNote -->

## How does a sender pay (card, Chargily, guest)?
- Pay screen lists rails from the server; the app never sends an amount or currency (the server rejects that with `client_supplied_amount_rejected`).
- Stripe: pays in EUR, card (Visa, Mastercard, others). Chargily: pays in DZD, Algerian cards (CIB, Edahabia). The rail decides the currency; there is no Stripe-in-dinars.
- Tapping pay opens the provider's hosted page. Coming back from it is NOT proof of payment: the app shows "Checking your payment" and re-reads the order from the server (9 checks spread over about 1.5 minutes: 3, 3, 5, 5, 10, 10, 20, 20, 20 seconds), then offers "Check again". Only the provider's confirmation (webhook or reconciliation) marks it paid.
- Only one open checkout per order. Starting again with the same rail, amount and payer resumes the open one ("A checkout is already open"). Switching rail or amount cancels the old attempt with failure code `superseded`.
- Checkout attempt lifetime: 3600 s = 1 hour (setting `payments.checkout.attempt_ttl_seconds`, allowed 5 min to 7 days). A safety check against the provider runs 5 minutes after expiry.
- Rail availability reasons shown to sender: "Not available yet" (no credentials), "Temporarily switched off", "Not ready yet" (bad configuration), "Not taking new payments right now" (new checkouts off), "Below this method's minimum". If none: "No payment method available ... Nothing has been charged".
- Two Chargily switches: `payments.providers.chargily_enabled` removes it from the list; `payments.chargily.new_checkouts_enabled` stops new checkouts only while webhooks, reconciliation, refunds and history keep working (the incident switch). Same idea for `stripe_enabled`. A `mock` rail exists for tests only (`mock_enabled`, must be off in production).
- The shipped seed settings have both rails and new Chargily checkouts switched OFF (and automatic Stripe payouts off). The live values are on Settings > "Provider availability" (admins can change them: "Accept new Stripe payments", "Allow Chargily", "Accept new Chargily checkouts"; reason required).
- Environment safety: each payment records TEST or LIVE mode; mismatches are refused.
<!-- src: finance/services.py start_checkout, finance/providers/__init__.py, mobile checkout_section.dart, l10n, core/migrations/0008 -->

## What are the payment attempt statuses?
`created` (row made), `checkout_pending` (provider page open), `processing`, `succeeded`, `failed`, `expired`, `cancelled`. Open = created/checkout_pending/processing; the others are final. A truly failed attempt (not an expired or cancelled one) emails the order owner, and also the guest payer if a guest paid. App wording: "Payment didn't go through" / "Nothing was charged. You can try again or use a different method."
Unapplied payment: money captured that no order could take (for example the order was closed meanwhile). It is refunded in full automatically (refund reason "Payment could not be applied") and shown in the Payments attention queue.
<!-- src: finance/models.py PaymentAttempt, refunds Reason -->

## How does a guest (someone else) pay?
- The order owner creates a payment link (app: "Someone else can pay", "Create payment link"). The payer needs no account.
- One live link per order; creating a new one revokes the old. Link lifetime 3 days (259,200 s, setting `payments.guest.link_ttl_seconds`, 10 min to 30 days).
- The guest sees only amount, currency and a generic purpose. No access to delivery, chat, disputes or personal details. The guest gives an email for the receipt and refund notices (required only when Wassla's transactional email is switched on).
- Only the order owner can create or revoke a link. Only the guest-capable rails are offered. The owner sees "Someone is paying now" while a guest checkout is open; the link cannot be revoked then ("Someone is paying with this link right now, so it cannot be revoked."). App states: "Payment link ready", "Someone is paying now", "This payment link has expired", "This payment link is no longer active". Invalid link for the guest: "It may have expired, been cancelled, or already been paid."
- Staff cannot see or re-create the link; only a hash is stored. The owner cannot see it again either ("For security it can't be shown again."); they create a new one, which stops the old one.
<!-- src: finance/services.py create_guest_link etc., models GuestPaymentLink, l10n guest* -->

## When is a deal "funded"?
When the deal balance order is fully covered (cash paid plus deposit credit). Then: the deal moves to funded, the ledger records the sender's money as held (traveler part and platform commission part), a Boost's traveler/platform split is recorded, and the traveler's payout record is created (amount = traveler reward plus the whole Boost). Exact locations unlock after funding (see deliveries.md). If the grace time after acceptance runs out unpaid, the deal expires (`payment_grace_seconds`, seeded 3600 s = 1 hour, no console form; see deliveries.md).
Rule: when payout profiles are on (deployment flag `PAYOUT_PROFILES_ENABLED`), the sender cannot start paying the deal balance until the traveler has a payout method that fits the chosen rail ("Payout preference required before funding."). An EUR payout method also needs Stripe funding ("This payout requires Stripe funding.").
<!-- src: finance/services.py _fund_deal_if_covered, payout_snapshots.preflight, core/policy_display -->

## Who can request a refund and for what reasons?
- Only staff with capability `issue_refunds` (Finance and Super Admin) can request a refund by hand: Finance > Payments, open a succeeded payment, "Request refund". Form: "Refund amount (€)" (min 0.01), "Reason", plus the tick-box "I understand the provider may receive this refund request immediately." Users cannot request refunds themselves; refunds also start automatically from the platform.
- Reasons: Request expired unmatched (`deposit_expiry`), Sender cancelled before acceptance (`sender_cancelled`), Payment could not be applied (`unapplied_payment`), Deal cancelled before funding (`deal_cancelled`), Administrative refund (`admin`), Deal cancelled after funding (`deal_cancelled_funded`), Dispute resolution (`dispute_resolution`), Verified no-show (`no_show`).
- Only a `succeeded` payment that an order took can be refunded ("Only a succeeded attempt can be refunded.").
- Partial refunds are allowed. Total refunds on one payment can never exceed what it captured: "A refund cannot exceed the captured amount." Money already reserved for a traveler payout cannot also be refunded: "This capture is reserved for a Traveler payout and cannot also fund a refund of this size."
- Asking twice for the same payment and reason returns the existing refund (no double refund).
- Every manual action is written to the audit log.
<!-- src: finance/services.py request_refund, admin_panel/console_forms.py RefundRequestForm, staff_actions.py -->

## What are refund statuses and how do they settle?
Statuses: `pending`, `processing`, `succeeded`, `failed`.
- Stripe: the refund is sent to Stripe right away. Provider unreachable: retried with growing waits (1 min, doubling, at most 6 h apart). After 8 tries it is flagged as needing manual action. A refund the provider reports as still pending is re-checked after 5 minutes.
- Chargily has NO refund API. Its refund stays `pending` with "Manual required" until staff send the money back outside Wassla (bank transfer) and record it. Re-checked every 6 hours.
- A provider refusal does not cancel the sender's right to the money: it becomes pending with manual action required.
- Manual settlement: open the refund (Finance > Refunds, or "Refunds & disputes" when the finance dashboard flag is on), enter "Settlement reference" (required, max 128 chars), optional "Note", tick "I confirm the refund was sent outside Wassla and the reference is correct." Needs capability `settle_manual_refunds` (Finance, Super Admin). Allowed on a pending, processing or failed refund ("Only an unresolved refund can be settled by hand"). Without a reference: "A manual refund settlement requires a reference."
- Order status follows: refund in progress = `refund_pending`; some back = `partially_refunded`; all back = `refunded`.
- Sender gets refund status emails (pending / done).
<!-- src: finance/services.py _settle_refund_with_provider, settle_refund_manually, providers/chargily.py -->

## What refunds happen when a deal is cancelled or disputed?
- Before funding: any captured money is refunded; orders cancelled.
- After funding, sender cancellation: more than 24 h (86,400 s) before agreed pickup gets everything back (exactly 24 h or later counts as late). Inside that cutoff the traveler gets 10% of the base reward (`sender_late_compensation_bps` 1000, rounded up, boost not counted) capped at 15.00 EUR (1500 cents); the rest goes back to the sender; platform keeps nothing. These are stored settings shown read-only in Settings > "Lifecycle guardrails"; no console form changes them. They are copied onto each deal at funding. See deliveries.md for who can cancel.
- Dispute resolution: an admin enters a "Sender refund (€)" and optionally a "Traveler payout (€)". The three shares (sender, traveler, platform) must add up to what was collected, and money already paid out cannot be clawed back. If no traveler payout is entered, the remainder not returned is shared between traveler and platform in the original ratio (`partial_split_fee_mode` proportional). If a traveler payout is entered, the platform keeps whatever remains (a negative remainder is refused). Refunds are taken from the balance order first, then the deposit. Example: collected 10.00 EUR (reward 8, fee 2), sender refund 4.00 leaves 6.00; traveler gets 6 x 8/10 = 4.80, platform 1.20.
- Errors: `settlement_refund_out_of_range`, `settlement_payout_out_of_range`, `settlement_exceeds_paid_out`, `settlement_does_not_reconcile`.
<!-- src: finance/settlement.py, core/migrations/0006 -->

## How does a traveler get paid? The overall path
1. Funding creates the payout (status `not_eligible`). Its rail is fixed then, from the traveler's payout preference and how the sender paid.
2. Delivery confirmed by the delivery code starts the 48-hour protection window (172,800 s, setting `payments.payout.protection_window_seconds`, 0 to 30 days).
3. A release check runs when protection ends. All must hold: delivery confirmed, protection window passed, the funded arrival floor passed (the agreed arrival time frozen at funding; payout waits for the later of this and protection end), no active dispute, balance fully paid with nothing refunded or being refunded, no finance hold, payout method usable.
4. If all pass: `eligible`. If setup is missing: `blocked`. If a dispute is active: `frozen`.
5. EUR: paid automatically (if enabled). DZD: a Finance person sends the dinars by hand.
6. The deal is marked completed once protection ends cleanly; the payout then lives on its own.
Nothing here is client-side; the app only displays server state.
<!-- src: finance/payout_release.py, payout_snapshots.py, deals/arrival.py -->

## What are the payout statuses?
| Status | Meaning |
|---|---|
| `not_eligible` | Protection window or other release condition not yet met |
| `eligible` | Released, waiting for the rail (EUR: automatic; DZD: waiting for Finance) |
| `scheduled` | EUR: reserved for execution. DZD: claimed by a Finance operator |
| `processing` | Money instruction committed; EUR with provider, DZD transfer in progress |
| `sent` | EUR: bank payout in transit. DZD: operator says the transfer is sent, settlement not confirmed |
| `paid` | Done and recorded in the ledger |
| `blocked` | Cannot progress; see block reason |
| `failed` | Attempt failed or bank returned it; traveler still owed |
| `frozen` | An active dispute holds the money |
| `cancelled` | Closed, no payout |
A paid payout can go back to `failed` only on a genuine bank return. A freeze cannot recall money already committed externally; the note records the exposure for recovery review.
Traveler-app wording: Awaiting delivery, Protection period, Awaiting release, Payout ready, On the way, Payout sent, Paid, Needs attention, On hold ("A dispute is open on this delivery, so the payout is on hold until it's resolved.").
<!-- src: finance/models.py Payout, payout_domain.py TRANSITIONS, payout_mobile.py, l10n -->

## What are the payout block reasons?
- `payout_preference_required`: traveler has not chosen a payout method; nowhere to send.
- `payout_setup_required`: method chosen but not ready (EUR account not verified, or DZD profile not approved).
- `fx_snapshot_missing`: DZD amount cannot be fixed without a rate (rate missing at funding).
- `funding_route_unavailable`: EUR payout but the sender paid by Chargily or mixed funding (EUR needs Stripe funding).
- `provider_mode_mismatch`: payout account is in a different TEST/LIVE mode.
- `funding_mode_unknown`: old payment with unknown TEST/LIVE mode.
- `legacy_instruction_required`: old payout from before versioned instructions; not settled by this system.
- `payout_below_minimum`: EUR payout under 1.00 EUR (100 cents; deployment setting, minimum 1 cent); held as a treasury hold, retried later.
- `connected_balance_pending`: money reached the traveler's Stripe account but is not yet available to pay out; waits.
- Traveler-facing reasons: payout setup required, profile under review, profile needs attention, on hold, dispute open, attempt failed, bank payout returned, country not supported for Stripe EUR payouts.
- Finance holds (kinds: dispute, provider_dispute, fraud, refund, compliance, treasury, manual) also stop a payout; clearing a hold returns it to where it was.
<!-- src: payout_snapshots.py, payout_execution.py, console_manual_presenter.py BLOCK_REASONS/HOLD_REASONS -->

## How does the EUR payout (Stripe Connect) work?
- Changing payout setup (choosing a payout method, the DZD profile and its proof, Stripe onboarding, refresh and dashboard) needs a confirmed email since L18A: otherwise `email_verification_required`, nothing saved. Reading it does not. Reason: someone who opened an account under another person's email must not leave a payout method behind for the real owner to inherit.
- When payout setup cannot be changed, the Payout methods read still shows the saved choice and history, offers no button, and names the reason; a direct change is refused with the same code: `payout_profiles_disabled` (deployment flag off), `payout_traveler_required` (sender-only, deactivated or banned account), `email_verification_required`, `stripe_connect_unavailable` (EUR onboarding off), `stripe_connect_no_countries` (EUR on, no country enabled), `payout_country_unsupported` (that country not enabled; use DZD), `payout_evidence_unavailable` (private cheque store missing or down: no DZD form, choosing DZD still works), `payout_setup_in_progress` (a Stripe account is being created: the EUR country and EUR on/off wait, and "continue setup" finishes it). A Stripe outage is `stripe_connect_provider_error`, nothing changed.
- Traveler sets up a Stripe connected account (Profile, Payout methods, "Set up EUR payouts"), declares the legal country of the account. Allowed countries are FR, DE, ES at most, and only those the deployment lists as enabled (empty by default). Algeria is deliberately not allowed; those travelers use DZD ("If your country is not listed, use DZD payouts.").
- Two steps: (1) platform Transfer moves EUR into the traveler's Stripe account; (2) Stripe bank payout to their IBAN. Traveler counts as paid only when the bank payout is `paid`. A failed bank payout is retried by creating another bank payout, never a new Transfer.
- Automatic execution needs ALL: deployment flags (payout profiles, Stripe Connect, Connect payouts on) AND the setting `payments.payout.auto_stripe_enabled` (seeded false). Otherwise payouts wait (checked every 6 h). No manual "Pay" button exists on this rail.
- Account readiness is re-read before sending (reused up to 15 min). Not ready: deferred, retried.
- Unknown outcome (timeout) is never resent blindly; the same idempotency key is replayed within 23 h or Finance investigates.
- Retry by staff: capability `retry_payouts`, only on a `failed` bank payout with a completed transfer, no Finance hold, nothing unknown, no live bank payout. Errors: "Only a failed bank payout can be retried.", "A Finance hold is active.", "This payout changed while the page was open."
- Bank payout stages: planned, committed, unknown, pending, in_transit, paid, failed, canceled, returned.
<!-- src: finance/payout_execution.py, payout_accounts.py, config/settings/connect.py -->

## How does the DZD manual payout work?
- Traveler adds: first and last name, CCP account number (1 to 20 digits), CCP key (2 digits), RIP (20 digits), and a clear photo of the full crossed cheque. Must be in the traveler's own name. Applies to future payouts only; funded payouts keep their original destination.
- Review (Finance and Super Admin; needs `review_payout_profiles`, `view_payout_sensitive` and `view_payout_evidence`): Finance > "Payout method reviews". The cheque photo must be fully uploaded ("Full crossed cheque evidence required."). Outcomes: approved; needs attention (traveler asked to correct and resubmit); rejected ("This CCP account was not accepted for payouts. Submit a different account in your own name."). Approval needs a current identity attestation ("Current attested identity required.", see below). If the account name does not match the attested identity, approval needs an explicit "accept name difference" tick, else it is recorded as needs attention.
- Showing the real CCP/RIP numbers needs `view_payout_sensitive` and is audited. Numbers are encrypted; console shows only last four digits otherwise.
- Operator steps on the payout's "Manual DZD payout" page: "Claim and prepare transfer" (reserves source funds; one operator owns it) -> "Start the transfer" (commit) -> send the dinars outside Wassla -> "Record transfer evidence" (JPEG, PNG or WebP image, at most 8 MiB, plus an attestation tick; tick "The receipt proves the transfer completed" to record settlement as well) -> payout `sent` then `paid`. Only the claiming operator can continue. "Release the claim" works only before the transfer is started. Receipts are never replaced; a correction needs a new upload. "Reveal payout details" shows the CCP data (audited).
- Needs capabilities view_payouts, retry_payouts, view_payout_sensitive, view_payout_evidence, and the deployment flag PAYOUT_DZD_EXECUTION_ENABLED (off by default: "Manual DZD execution is disabled.").
- DZD amount = frozen EUR amount x frozen rate rounded up (see first section). Example: payout 8.00 EUR at 150 = 1200 DZD. If the sender paid by Chargily, the rate is that attempt's rate; if by Stripe, the setting rate at funding.
- Console refusals: "Another operator has already claimed this payout.", "Reviewed profile and crossed cheque are required.", "Delivery, protection or hold gate prevents progression.", "Committed instructions require recovery review." (use "Hold for correction or recovery review" instead).
- Marking paid writes the ledger entry discharging the traveler payable.
<!-- src: finance/payout_manual.py, payout_profiles.py, payout_manual_profiles.py, console_manual_payout.py -->

## What is a payout identity check?
Before a DZD profile can be approved, a reviewer with `attest_payout_identity` (Trust / Verification, Super Admin) must be assigned, and records the traveler's legal given and family names from an approved ID verification (KYC, not expired). Name comparison is only an aid: results consistent, review (alias/spelling/script difference) or mismatch; a human always decides. Only the attesting reviewer can revoke an attestation. If the ID expires or the attestation is revoked or replaced, the profile approval stops counting for new payouts (an already funded payout may keep its original approval unless revoked).
<!-- src: finance/payout_profiles.py, payout_identity.py, payout_manual_profiles.py -->

## Which console pages exist for money and who can open them?
All are in the console's Finance menu (path under the console).
| Menu item (path) | Purpose | Capability |
|---|---|---|
| Overview (finance/dashboard) | Landing: liabilities, health, integrity | view_finance_summary + flag |
| Payouts (finance/payouts-hub) | Payout queues | view_finance_summary + flag |
| Manual DZD (finance/manual-dzd) | Dinar payouts waiting for a person | view_finance_summary + flag |
| Payout method reviews (finance/payout-reviews) | DZD payout profile queue | review_payout_profiles (always shown) |
| Refunds & disputes (finance/exceptions) | Refund and dispute exceptions | view_finance_summary + flag |
| Reconciliation (finance/reconciliation) | Integrity checks | view_finance_summary + flag |
| Exports (finance/exports) | CSV: transactions, commissions, payouts | export_finance (always shown) |
| Payments (finance/payments) | Every payment attempt; reconcile, resolve, refund | view_payment_attempts or view_payment_orders |
| Refunds (finance/refunds) | Refund list | issue_refunds or settle_manual_refunds |
| Payouts (finance/payouts) | Raw payout list and detail | view_payouts |
| Payout accounts (finance/payout-accounts) | Stripe account state | view_finance_summary |
| Ledger (finance/ledger) | Double-entry records | reconcile_finance |
"+ flag" = only when the deployment flag `FINANCE_DASHBOARD_ENABLED` is on (default off; the page then answers "not found"). When that flag is on, the raw Refunds, Payouts, Payout accounts and Ledger items leave the menu (the new pages front them); when it is off they are the way in. Background jobs live under System > Background jobs (system/jobs; view_scheduled_jobs or view_operational_incidents). Payout identity checks are a Trust page (attest_payout_identity).
Payments search: tracking number, order reference, payer email, guest email, provider payment id. "Attention" filter shows items needing action.
<!-- src: admin_panel/console_urls.py, console_views.py, core/templatetags/shiptrip_admin.py NAVIGATION, FLAG_GATED_ROUTES, finance_dashboard.py -->

## Which roles may do which finance actions?
Roles: Ops, Support, Finance, Trust / Verification, Super Admin (all codes).
- Finance: `view_payment_orders`, `view_payment_attempts`, `view_provider_events`, `view_payouts`, `issue_refunds`, `settle_manual_refunds`, `settle_payouts`, `reconcile_finance`, `view_scheduled_jobs`, `export_finance`, `view_finance_summary`, `view_payout_sensitive`, `view_payout_evidence`, `review_payout_profiles`, `manage_payout_holds`, `retry_payouts`, `resolve_disputes`.
- Trust / Verification: `attest_payout_identity`, `manage_payout_holds`; no refunds or payout settlement.
- Ops, Support: no payment, refund or payout capabilities. (Ops and Trust can record a no-show, and Support can manage cancellations; those flows may start refunds automatically.)
- Super Admin: every capability.
- Exports and some actions need the staff two-step sign-in (see admin-console.md).
<!-- src: admin_panel/permissions.py ROLE_PERMISSIONS -->

## What do reconciliation and the money jobs do?
- Reconcile payment (Payments, open a payment that is not succeeded or is unapplied, "Retry reconciliation", page "Retry payment reconciliation"; needs `reconcile_finance`; "Reason for reconciliation" and the tick "Queue provider/refund reconciliation. This does not mark the payment paid."): queues a check against the provider. It never marks a payment paid by itself.
- "Resolve attention item" (page "Resolve payment attention item", `reconcile_finance`): archives it as resolved, dismissed or superseded; history kept. "Unapplied money cannot be dismissed before its full refund succeeds."
- Webhooks: each provider event is stored once (unique id); duplicates are no-ops; results received, processing, applied, ignored, retryable, failed.
- Jobs (durable): deposit expiry refund, payment grace release, attempt expiry, provider reconcile, provider event process, refund reconcile, payout release check, payout execute/reconcile/account refresh/sweep, protection expiry, delivery-code release. Statuses pending, running, succeeded, failed, cancelled; default 8 tries, most payment, refund and payout jobs 32. Failed jobs of kinds deposit expiry refund, payment grace release, attempt expiry, provider reconcile, provider event process, refund reconcile and payout release check: only `reconcile_finance` (Finance, Super Admin) can retry or resolve them, with a reason. Other jobs: `manage_lifecycle` (Ops) or `reconcile_finance`.
- Finance dashboard integrity states: "Finance data reconciles", "Reconciled, with a stated limitation", "Finance data does not reconcile" (treat totals as unreliable). Modes TEST, LIVE, Legacy/unknown are reported separately.
<!-- src: finance/operations.py, admin_panel/staff_actions.py FINANCE_JOB_KINDS, console_views.py payment_detail, console_forms.py, finance_dashboard_labels.py -->

## Is there a wallet?
No. All money uses orders, attempts, refunds, ledger and payouts. Do not tell users they have a wallet balance.
<!-- src: finance/models.py -->

## Not covered here
- Live values of settings (current rate, provider switches): the code only has the shipped defaults; the live values are on the Settings page.
- Which Stripe Connect countries are enabled in production (deployment setting).
- Provider fees (Stripe/Chargily charges to the platform) and whether sender pays any: not found in code.
- Detailed ledger account postings per event (accounts: provider clearing, sender deposit, deal funds, traveler payable, platform commission, connect funds, payout in transit).
- Export column layouts and date limits.
- Chargily bank-transfer refund timing for the sender.
- Boost payment rules in depth (see pricing.md / boosts file).
