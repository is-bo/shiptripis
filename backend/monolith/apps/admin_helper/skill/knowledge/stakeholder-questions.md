# Stakeholder questions: business model, privacy, security, safety and operations

Covers: Plain answers the Super Admin can read to an investor, accountant, lawyer, bank, regulator or new hire about how Wassla earns money, what is switched on, what data is kept, how it is secured, what protects users, what happens when things go wrong, and what the app does not do.
Related files: pricing.md, money.md, problems-and-disputes.md, deliveries.md, accounts-and-verification.md, settings-and-helper.md, admin-console.md, messages-and-notices.md, reviews.md, trips-and-matching.md, overview-and-glossary.md

Rule for the assistant: every answer here is what the CODE and shipped defaults say. Live values (current settings, which providers are switched on, user numbers) must be read on the console. When a stakeholder asks for something in the last section, say it is not in the app.

## How does Wassla make money?
- One source in the code: a commission added ON TOP of the traveler's reward. Shipped rate 25%, rounded up to the next cent. The Super Admin can change it (Settings, form "Commission, deposit and floors", 0 to 100%).
- Example: traveler reward 20.00 EUR, commission 5.00 EUR, the sender pays 25.00 EUR, the traveler receives 20.00 EUR, Wassla keeps 5.00 EUR.
- A Boost (extra reward the sender adds) carries its own commission, shipped at 25% (Settings, form "Boost commission"). Boost 10.00 EUR: sender pays 12.50 EUR extra, traveler gets 10.00 EUR extra, Wassla keeps 2.50 EUR.
- The commission is frozen on each deal when the offer is accepted. Later changes only affect future deals.
- Wassla keeps the commission only if the delivery completes. If a deal is refunded in full, Wassla keeps nothing. Late cancellation by the sender: the platform fee on it is 0% by default (the traveler gets compensation, the rest returns to the sender). In a disputed partial split the platform can keep a remainder (see problems-and-disputes.md).
- No subscription, listing fee, advertising, data sale or visibility package exists in the code. The old paid visibility packages are retired.
- Provider charges (Stripe, Chargily) and any VAT or tax treatment are NOT in the code. See the last section.
See pricing.md and money.md for the full formulas.
<!-- src: backend/monolith/apps/core/business_settings.py, apps/core/phase4_policy.py, apps/finance/settlement.py, apps/boosts/models.py -->

## Who pays what, and what does the traveler earn?
| Item | Who pays | Amount |
|---|---|---|
| Traveler reward | Sender | Agreed on the offer (sender proposes first). Never below Wassla's minimum for the route and weight |
| Commission | Sender | 25% of the reward, on top (shipped default) |
| Boost plus its commission | Sender | Optional, 1.00 EUR minimum when used, commission 25% on top |
| Posting deposit | Sender, at posting | Recommended 10% of the recommended total, between 3.00 and 7.00 EUR. It is credited to the deal later and refunded in full if nobody takes the request or the sender cancels before accepting. It is not an extra fee |
| Cost to the traveler | Nobody | The traveler pays no fee in the code |
- The traveler earns the whole reward plus the whole Boost. Nothing is deducted for Wassla.
- A traveler may list a price per kg and a minimum per parcel (on by default). The listed price is the largest of per-kg price x chargeable weight, the traveler's minimum, and Wassla's minimum. The commission is added on top.
- Wassla's minimum reward: a 3 kg parcel, 200 km, with the shipped numbers = 13.50 EUR (6.00 distance band + 3 x 2.50). Never under the 7.00 EUR global floor.
- Payouts: after delivery plus 48 hours with no dispute. EUR by Stripe, or DZD by a Finance person paying by hand to the traveler's CCP account.
<!-- src: apps/core/business_settings.py, apps/matching/listed_price.py, apps/finance/policy.py, apps/finance/payout_release.py -->

## Which markets, countries, languages and currencies are live?
- Countries in the app's place picker: Algeria, France, Spain, Germany. The website says the launch scope is Europe to Algeria.
- Rules: any leg between Algeria and a non-Algerian country must be a flight (or a sea leg, only if sea legs are switched on). Drives are only inside one road network (Algeria; or France, Spain and Germany together).
- Languages: English (default), French, Arabic (right to left) in the app and the home page. Emails follow the user's email language. The legal pages are English only for now.
- Currency: EUR is the real currency (stored in cents). Chargily shows a DZD amount converted by the server from EUR (rate typed by an admin, shipped placeholder 150 DZD per EUR, minimum 75 DZD). Stripe pays in EUR.
- Whether a country is actually "live" for users cannot be read from the code: signup asks for no country. Which payment rails are on is a setting (next section).
- Not offered: sea legs (off by default), a wallet, phone or SMS sign-in. Google sign-in and Sign in with Apple are built in the app and the server, and each stays off until its keys are set (Apple until the iOS bundle id is in `APPLE_SIGN_IN_CLIENT_IDS` and the build defines `APPLE_SIGN_IN_ENABLED=true`). Members delete their own account in the app (Profile > Delete account), as the App Store and Google Play require, and members can report a chat message and block someone. Visitors can browse without an account.
<!-- src: apps/core/languages.py, apps/trips/transport_rules.py, apps/finance/policy.py, web/en/index.html -->

## What is switched on or off in the shipped settings, and where do I change it?
| Thing | Shipped state | Where to change it |
|---|---|---|
| Stripe (EUR cards) | OFF in the pre-launch settings | Settings, "Provider availability" |
| Chargily (Algerian cards) | OFF | Settings, "Provider availability" (two switches: allow, and accept new checkouts) |
| Automatic Stripe payouts | OFF (payouts wait) | Setting `auto_stripe_enabled`; full settings version only, no console form |
| Sea legs | OFF | Settings, "Discovery, routes, prices and proposals" |
| Home discovery (trips and requests) and public profiles | ON (each member's own profile stays off until they opt in) | same form |
| Traveler pricing | ON | same form |
| Proposal answer deadline | ON, 6 hours | same form |
| Trip-fit alerts | ON | same form |
| AI helper for admins | ON | Settings, "Admins' own AI assistants" |
| Payment timing | `posting_deposit` (deposit when posting) | No console form; full settings version only |
| Finance dashboard pages, payout method reviews, manual DZD payout, Stripe Connect payouts | OFF by default in code | Server environment flags (`FINANCE_DASHBOARD_ENABLED`, `PAYOUT_PROFILES_ENABLED`, `PAYOUT_DZD_EXECUTION_ENABLED`, `STRIPE_CONNECT_*`), set by whoever runs the server, not on the console |
| Transactional email | OFF by default (`EMAIL_ENABLED`) | Server environment |
| Phone push notices (Firebase) | OFF by default (`FCM_ENABLED`) | Server environment |
| Payments mode | TEST by default (`PAYMENTS_ENVIRONMENT`) | Server environment |
- Staff two-step sign-in cannot be switched off in production (the server refuses to start).
- The test payment provider cannot run in production.
- The code only knows shipped defaults. For what is live today: Settings page (Super Admin) and the Health page (providers).
- Every settings change is a new numbered version with a reason and an audit row. Provider keys and webhooks are never in settings.
See settings-and-helper.md for every setting.
<!-- src: apps/core/migrations/0005, 0008; apps/core/marketplace_policy.py; infra/vps/stack.env.example; config/settings/prod.py -->

## What personal data does the app store?
- Account: name, email, phone (not checked by SMS), password (stored only as a one-way hash), email language, region (optional, old field).
- Traveler identity check: photos of the ID (front, back where needed) and a selfie, in a separate private store. Ticket proofs (boarding pass, ticket, booking) per leg.
- Parcels: title, description, category, weight, size, declared value, one photo, pickup and delivery places, handling notes.
- Locations: coarse place for everyone; exact addresses only for the parties after funding.
- Recipient (no account): name, email, optional phone, delivery note, collected after funding.
- Deals: terms, timeline, codes (hashed, see below), chat messages (text only), ratings, problem reports, dispute text, photos and videos.
- Money: payment and refund records, provider references, ledger, payout records. Payout destination for DZD: CCP account numbers and a cheque photo, numbers encrypted.
- Technical: a push token per phone, audit rows of staff actions, AI helper call log (30 days).
- Cards: Wassla never handles card numbers. The sender pays on the provider's hosted page.
See accounts-and-verification.md.
<!-- src: apps/accounts/models.py, apps/kyc/models.py, apps/parcels/serializers.py, apps/deals/recipient.py, apps/finance/payout_profiles.py, web/privacy.html -->

## What does the app never store or never show?
- Never shown to the traveler: the delivery code, the recipient's email and phone, the sender's exact address before funding.
- Never shown to staff: payout bank or CCP numbers on the person page (only one audited "reveal" for Finance), chat text (no screen exists), ID photos without an audited open, a legal name after an identity check (stored encrypted, never shown back).
- Never shown to the AI helper: files, document numbers, birth dates, emails, phones, addresses, coordinates, bank details, codes, chat, guest payer emails.
- Not collected: government ID of senders, sender bank details, card data, a phone verification (nothing sets "phone verified").
- Dispute evidence snapshots record that a chat existed (count, first and last time), not its words, and never the delivery code or recipient contact.
- Staff cannot see guest payment links (only a hash is stored).
<!-- src: apps/admin_panel/console_people.py, apps/admin_helper/resources.py, apps/disputes/services.py, apps/finance/models.py -->

## Who can see what? (privacy by role)
- Sender: own parcel, offers, deal, recipient details they entered, chat with the traveler.
- Traveler: sender's first name and public card; exact locations only after funding; recipient name and note only after pickup; never the delivery code.
- Recipient and guest payer: no account; the guest sees only amount, currency and a generic purpose.
- Public profile (each member opts in; off until they do): first name, ID-verified badge, rating, completed deliveries, member since (month and year), up to 3 usual routes. Never last name, email, phone or address.
- Staff by role: Super Admin everything; Trust sees ID, tickets, evidence and phone; Finance sees money and payout data but "cannot read private evidence"; Support and Ops see operational records, not documents.
- Every ID photo or evidence opening, bank reveal, export and setting change is written to the audit log, which cannot be edited or deleted.
See admin-console.md for the role table.
<!-- src: apps/admin_panel/permissions.py, apps/discovery/profiles.py -->

## How long is data kept? Can a user delete their account?
- Yes: Profile > "Delete account" in the app, or the /delete-account web page (steps and an email route). It waits until nothing is open, then erases the person's details at once; records others and the law rely on stay without them (see accounts-and-verification). Other privacy requests (access, correction) go to the support mailbox on the website (see legal pages below). The privacy page says retention periods are not yet decided and will be published before launch.
- Fixed in code: finished background-job rows are pruned after 90 days by default (never below 30; money records are never touched); AI helper calls kept 30 days; phones not seen for 180 days are switched off; unclaimed parcel photos are reclaimable after 48 hours; notifications, audit rows and ledger rows are never deleted.
- Financial, safety and dispute records are kept (the privacy page says they may need to stay for legal reasons).
- There is no data-retention policy in the code. The public privacy page states no retention periods. Say so, and say that it is an open business decision.
<!-- src: finance/management/commands/prune_scheduled_jobs.py, admin_helper/calls.py, notifications/management/commands/prune_push_devices.py, config/settings/base.py, web/privacy.html -->

## What security measures protect the system? (in plain words)
- Staff sign-in: password plus a 6-digit code from an authenticator app, every time. 5 wrong codes lock the second step for 15 minutes. 10 one-time recovery codes. Sensitive steps (change a role, reset two-step, create an AI key) need a code entered in the last 10 minutes. The staff data interface answers only inside a verified console session.
- Passwords: stored as a strong one-way hash (Argon2). Email codes: stored hashed, valid 15 minutes, 5 tries.
- Delivery codes: stored hashed and sealed under their own separate secret. 8 characters; 5 wrong tries lock it 15 minutes; after 3 lockouts it locks fully; at most 12 tries per hour. Only the sender can ask for a new one.
- Keys and links stored as fingerprints or hashes only: AI helper keys (fingerprint plus last four characters), staff invitation links, guest payment links.
- AI helper: a read key lasts at most 8 hours, a change key 30 minutes; it acts only with that admin's rights; every change it prepares needs the admin's own click after a fresh two-step; the Super Admin can stop any key.
- Rate limits (default per user or address): sign-up 30 per hour; sign-in 10 per minute; password reset 5 per hour; email verify 10 per hour; Google sign-in 30 per minute; Apple sign-in 30 per minute; Home discovery 60 per minute per member; a visitor without an account browsing Home and the place picker 300 per minute per address (Algerian mobile networks put hundreds of people behind one address, so visitors are not held to the general anonymous limit there); uploads 20 per hour; chat 60 per minute; checkout 20 per minute; guest payment 20 per minute; dispute evidence 20 per minute; handover codes 12 per minute; general API 60 per minute anonymous, 600 per minute signed in; AI helper 60 per minute per key (setting 10 to 300).
- Audit log: who, what, which record, reason, when; immutable; secret-looking fields redacted.
- Web: HTTPS only, secure cookies, HSTS for 30 days, no sniffing, strict referrer policy.
- Payments: provider events are verified by signature and stored once, so replays do nothing; the database refuses over-collecting or refunding more than was captured; money moves through an append-only ledger; test and live payments are never mixed.
- Hosted secrets: provider keys and database passwords live in the server's own protected files and environment, never in the settings page or the code. The staff settings interface refuses any name containing secret, password, token, private key or webhook. Plain truth for a stakeholder: on the shipped server layout these are protected files with strict permissions, not an encrypted vault.
- Server: only ports 80 and 443 are open; database and cache have no public port; the application runs as a non-root user; SSH hardening and a firewall are part of the server setup script.
<!-- src: apps/admin_panel/two_step.py, config/settings/base.py (throttle rates), config/settings/prod.py, apps/handover, apps/admin_helper/keys.py, infra/vps/README.md -->

## What safety and trust features protect users?
- Identity: travelers must have an approved ID check (document plus selfie, reviewed by a person) before a journey can be published or matched.
- Tickets: every flight leg (and ferry leg if enabled) needs an approved ticket proof; if the ticket details change it goes back to review. Drive legs need no proof.
- Location hiding: exact addresses stay hidden until the deal is funded.
- Delivery code: belongs to the recipient; the traveler cannot get it; locked 30 minutes after pickup.
- Money held: the sender pays before pickup; payout waits 48 hours after delivery; a dispute freezes payout.
- Blind two-way reviews (1 to 5, 14-day window, hidden until both rate or the window ends) plus staff moderation of reported reviews.
- Reports: problem reports, no-show reports (staff decide), disputes with photo and video evidence.
- Sender declarations: five ticks (description accurate, item legal, no prohibited goods, value accurate, customs understood).
- Staff can ban a user, hide a profile, pause a journey.
- Not claimed by the app: insurance or a guarantee. The home page says these checks "are not an insurance policy".
<!-- src: apps/trips/services.py, apps/handover, apps/disputes, apps/ratings, apps/parcels/serializers.py, web/en/index.html -->

## What happens when things go wrong? (one table)
| Situation | What happens | Money |
|---|---|---|
| Sender does not pay in time | Deal expires after 1 hour grace; the traveler's space is released; request reopens | Nothing charged |
| Payment fails | Attempt marked failed; the deal stays `payment_required`. The payer is emailed ("Your Wassla payment needs attention") and the app shows "Payment didn't go through"; sender can retry or switch method until the 1-hour grace ends | Nothing charged |
| Money captured but not usable | Refunded in full automatically (reason "Payment could not be applied"); shown to Finance | Full refund |
| Nobody takes the request | At the deadline the posting deposit is refunded | Deposit back |
| Sender cancels before paying | Free | None |
| Sender cancels after funding, more than 24 h before pickup | Deal ends `refunded` | Full refund |
| Sender cancels within 24 h of pickup | Deal ends `partially_refunded`: traveler gets 10% of the reward (cap 15.00 EUR); rest to sender; platform keeps nothing | Partial refund |
| Traveler cancels before pickup | Deal ends `refunded` | Full refund, no compensation |
| Traveler no-show | Staff record it (before pickup only): deal becomes `refunded`, space released | Sender refunded in full (default) |
| Sender no-show | Staff record it; nothing moves | None |
| Traveler late or trip changed | No automatic penalty or score. Traveler changes times; the sender must agree if the arrival moves more than 6 hours or misses the deadline; sender can cancel (counts as the traveler's cancellation, full refund) | Per cancellation rule |
| Parcel damaged, wrong item, not delivered, late | Problem report or, after pickup, a dispute: payout frozen, staff review evidence, Finance or Super Admin resolves | Full refund, full payout, or split; the three shares add up to what was collected |
| Dispute after the 48-hour window | Refused: "The payment protection window for this delivery has closed." Users are told to contact support | None |
| Refund by Stripe fails | Retried automatically; after 8 tries flagged for manual action | Sender still owed |
| Refund by Chargily | Chargily has no refund interface: Finance sends the money back by hand and records a reference | Manual |
| Payout fails | Stays owed (`failed`); staff retry a failed Stripe bank payout; a DZD payout is held for Finance | Traveler still owed |
| Payout already paid | A party's dispute window closes before any payout can be released, so this cannot happen through the app. Staff cannot open a dispute today. If a paid payout ever meets a settlement, the money is not taken back automatically; recovery is a staff matter | Exposure noted |
| Wrong delivery code | 5 tries then 15-minute lock; after 3 lockouts it locks; sender can ask for a new code | None |
See problems-and-disputes.md and money.md.
<!-- src: apps/deals/cancellation.py, apps/disputes/services.py, apps/finance/settlement.py, apps/finance/services.py -->

## What are the limits? (weights, values, amounts, deadlines)
| Limit | Value | Changeable |
|---|---|---|
| Parcel weight | 0.01 to 100 kg | Fixed |
| Parcel side length | 0.01 to 500 cm | Fixed |
| Declared value | 0 to 1,000,000.00 EUR (100,000,000 cents) | Fixed |
| Reward the sender proposes | 1 cent to 1,000,000.00 EUR; never below Wassla's minimum (global floor 7.00 EUR) | Floor: Settings |
| Boost | 1.00 EUR minimum when used; ceiling 1,000,000.00 EUR | Settings (minimum) |
| Traveler per-kg price | at most 100.00 EUR (guard) | Settings |
| Traveler minimum per parcel | at most 500.00 EUR (guard) | Settings |
| Posting deposit (recommended) | 3.00 to 7.00 EUR; chosen deposit from 3.00 EUR up to the full amount owed | Settings |
| Legs per journey | 20 | Fixed |
| Leg capacity | 0.01 to 20,000 kg (typo guard, not a business cap) | Fixed |
| Proposal answer time | 6 hours, or until pickup if sooner | Settings (1 to 168 h) |
| Payment grace after acceptance | 1 hour | Full version only |
| Checkout attempt life | 1 hour | Full version only |
| Guest payment link | 3 days | Full version only |
| Delivery code buffer after pickup | 30 minutes | Full version only |
| Payout protection | 48 hours | Full version only |
| Free-cancellation cutoff | 24 hours before pickup | Full version only |
| Review window | 14 days | Full version only |
| Dispute evidence | 20 items, 25 MB each | Full version only |
| Item photo and ticket photo | 10 MiB; ID photo 8 MB each | Fixed |
| Chat message | 2,000 characters, text only | Fixed |
| Chargily minimum | 75 DZD | Full version only |
| EUR payout minimum | 1.00 EUR | Server |
| Finance export range | at most 366 days | Fixed |
"Full version only" means a new settings version created through the staff interface, not a console form.
<!-- src: apps/parcels/serializers.py, apps/core/business_settings.py, apps/core/phase4_policy.py, apps/core/marketplace_policy.py, apps/admin_panel/exports.py -->

## What does Wassla NOT do?
- Not an insurer: no insurance, no value cover, no compensation guarantee beyond the refund and dispute rules above.
- No professional transporters, no courier handoff: not in the app. Only people already travelling.
- No Kaba (traveler buying products): not in the app.
- No same-day promise: fast delivery is the aim, nothing enforces it. The sender sets a deadline and the app checks the traveler's arrival against it.
- No scanning of parcel contents: the server has no prohibited-items list and does not inspect. The sender's five declarations are the control.
- No customs service: the sender declares and is responsible for legality, duties, import rules and the accuracy of the declared value. A match is not customs clearance.
- No wallet, no stored balance, no card storage.
- No payout in dinars by Stripe (Algerian travelers are paid in DZD by hand).
- No dynamic surge pricing; only a fixed urgency add-on for tight deadlines (3.00 EUR within 24 hours of slack, 1.50 EUR within 72 hours, in the suggested price).
- No chat moderation or message reading by staff; no vehicle proof for drive legs.
- Not an emergency service (support page).
<!-- src: apps/parcels/serializers.py, apps/matching/policy.py, web/prohibited-items.html, web/support.html, web/en/index.html -->

## How reliable is the system and how is it run?
- Design: one Django system holds all rules and money; three small Go services (notifications, chat, ID check) plus an email worker; PostgreSQL is the source of truth. If the Go services are down, the core still works.
- Background jobs (stored in the database, with retries): refunds on expiry, payment grace release, attempt expiry, provider reconciliation, refund and payout checks, payout release, protection expiry, delivery-code release, reminders, review reveal. Failed jobs show on the Overview and System, Background jobs pages for Finance or Ops to retry or resolve with a reason.
- Reconciliation: Finance, Reconciliation page (when its flag is on) and Payments page compare Wassla's records with Stripe and Chargily. The ledger states "Finance data reconciles", "Reconciled, with a stated limitation", or "Finance data does not reconcile".
- Monitoring: Health page (database, cache, storage, providers, jobs, email). On the server a check runs every 60 seconds (app, web edge, database, cache healthy; disk under 80%; memory; load; cache saving; error rates in logs). In the shipped setup an alert is only a system log line; no external pager is connected.
- Backups: a daily encrypted copy of the database at 02:15 UTC to an offsite storage, checked after upload; restore is rehearsed on a separate database, never over the live one. How many daily, weekly and monthly copies are kept is an owner decision (no number in code).
- Updates cause a short maintenance window (not zero downtime); rollback does not reverse database changes.
- Single server design: one application unit on one server (8 shared CPUs, 16 GB), deliberately one copy.
- Automatic checks on every code change (CI): Go build, vet and tests (including a real-cache run); Django tests, lint and a check for missing database migrations; production-configuration and website checks; Flutter format, analysis and tests; a check that the database schema and generated code have not drifted.
- The files describe how the server is set up. They do not say whether it is live, so do not say it is.
<!-- src: infra/vps/README.md, infra/vps/backup/backup.sh, infra/vps/monitor.py, infra/vps/systemd/*, .github/workflows/ci.yml, apps/admin_panel/worklist.py -->

## Which legal and public pages exist, and what is their status?
| Page | Content | Status |
|---|---|---|
| Home (`/en/`, `/fr/`, `/ar/`) | What Wassla is, how it works, trust statement | Live in three languages |
| Terms of Service | Use, matching, payment and 48-hour protection, handoffs, cancellations, disputes, ratings | Draft, marked "Review required before launch"; needs French, EU and Algerian legal review; English only |
| Privacy Policy | Data used, why, sharing, rights | Draft; retention periods deliberately not stated; English only |
| Prohibited items and acceptable use | Weapons, drugs, counterfeit, live animals, stolen goods, anything illegal in a country on the route; customs responsibility sits with the sender | Draft; not an exhaustive list per country |
| Support and contact | Four mailboxes: general, safety and disputes, privacy, payments | Addresses are placeholders to replace before launch |
- The footer says: "Product and policy pages are drafts pending final French, EU and Algerian legal review."
- The pages say funds held pending delivery is a description of the product flow, not a regulatory or custody guarantee.
- The app's Profile links only to Terms and Privacy; it has no support button.
- No effective date is published on the terms yet.
<!-- src: web/terms.html, web/privacy.html, web/prohibited-items.html, web/support.html, web/en/index.html -->

## How do I measure the business? Which pages and exports give numbers?
- Finance Exports (Finance, Super Admin): three CSV files. Pick kind, money mode (Live, Test or Unknown, never mixed), a date range up to 366 days, end not in the future. Each download is audited with its kind, range and line count.
  - Transactions: date, type, tracking number, payment and provider references, provider, purpose (deposit, delivery, boost), paid by, amount, currency, dinar amount, status, sender id and name.
  - Commissions: funded date, tracking number, traveler reward, Wassla fee, sender total, refunded to sender, fee kept, currency, deal status, sender and traveler ids and names. This is the revenue file.
  - Payouts: created date, tracking number, payout reference, method, status, amount, currency, dinar amount, eligible date, paid date, failure reason, traveler id and name.
  - Amounts are recorded values in EUR. No emails, phones, addresses, bank or card details.
  - Dates belong to a row by UTC date: payment by capture, refund by request, commission by funding, payout by creation.
- Finance dashboard pages (Overview, Payouts, Manual DZD, Refunds and disputes, Reconciliation): show liabilities, health and integrity, only when the server flag is on.
- Overview (all staff): work waiting, provider status, latest audit rows.
- Lists with filters: Users, Delivery requests, Journeys, Deals, Disputes, Payments, Refunds, Payouts, Ledger, Audit log, Background jobs.
- Not in the app: user growth charts, conversion funnels, revenue-over-time charts, a count of active users. Counts must be taken from lists or from the exports.
<!-- src: apps/admin_panel/exports.py, console_exports.py, console_urls.py, worklist.py, apps/finance/finance_dashboard.py -->

## What is parked, and what is a future item?
- Professional transporters, manifest dashboard, custody history and courier handoff: parked, not in this version.
- Kaba (traveler buys a product): not in this version.
- Sea legs: built, off by default; the owner must confirm legal and customs rules first.
- Any other roadmap statement: parked, not in this version.

## Questions I cannot answer from the app
Business facts that are not in the code. Do not guess; say "that is not in the app" and ask the owner.
- Company data: legal entity name, registration number, address, directors, shareholders (the home page footer says only "Wassla"; older docs say the platform entity is in France, not confirmed in code).
- Revenue, profit, costs, cash, funding, valuation, runway.
- User counts, delivery counts, growth, retention, churn, ratings averages across the platform.
- Whether any payment provider is live today and the live commission, rate or switches (read the Settings page).
- Provider fees (Stripe, Chargily), foreign-exchange spread, who bears payment fees.
- VAT, sales tax, income tax treatment, invoicing, accounting rules, tax reporting for travelers.
- Licences: payment institution or e-money licence, money transmitter status, courier or transport licence, customs authority approval. The terms only say funds are held pending delivery and this is not a regulatory or custody guarantee.
- Insurance: any cover of parcels, liability or cyber (the app states it is not insurance).
- Legal review outcome, final terms and privacy text, effective dates, retention periods, data protection officer, GDPR registration or Algerian data-law filings.
- Pricing outside the app: partner deals, discounts, promotions.
- Security audits, penetration tests, certifications.
- Support staffing, response times (the app promises none; "less than a day" for ID review is only app text), verified support mailboxes.
- Backup retention counts, recovery time and recovery point targets, uptime figures, and whether the server is live.
- Which countries and airports are actually active for real users.
- Incident history, complaints, fraud or dispute rates.

## Not covered here
- Exact live Settings values and deployment flags (read on the console or ask the operator).
- The ledger account postings per event and the full audit action list (see money.md and admin-console.md).
- Contract or custody classification of held funds (a legal question).
