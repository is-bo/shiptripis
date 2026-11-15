# Messages, Notifications, Email and the Public Website

Covers: in-app chat, the notification bell, phone push, live updates, transactional email (including the recipient's delivery-code email), reminders, notification switches, languages, support contact, the public website, and the Go services.
Related files: deliveries.md (deal states, delivery code buffer, protection window), money.md (payment and payout emails), problems-and-disputes.md, accounts-and-verification.md, trips-and-matching.md (proposal deadlines), admin-console.md (console pages), settings-and-helper.md (Settings).

## How does chat work and who can chat with whom?
- Chat is 1:1 text between the two people on a match: the sender and the traveler. Nobody else can read or write in it (a non-party gets "Not a party to this match." and a 403).
- A chat thread is simply the match. There is no group chat, no chat before payment.
- Chat opens only once the deal is funded (money paid). Before that the app says "Chat isn't available yet. Chat opens for this delivery once payment is confirmed." and offers a "Go to payment" action to the sender.
- The inbox ("Chat" tab) only lists threads whose deal was funded at some point. Empty inbox text: "No conversations. Chat opens once a delivery is paid for."
- Matches on the old product-request type are refused with reason `product_request_retired` (not in the app).
<!-- src: backend/monolith/apps/matching/services.py, backend/monolith/apps/chat/views.py, mobile/lib/l10n/app_en.arb -->

## When can a user send a message, and when is the thread read-only?
Sending needs all of: the user is a party, the deal exists, the deal is funded, and the deal is not in a closed state.
- Closed (read-only) deal statuses: `completed`, `cancelled`, `expired`, `refunded`, `partially_refunded`.
- `disputed` is deliberately NOT closed: people can keep talking during a dispute (for example to arrange a return).
- After a deal closes the thread stays readable forever to both parties. The app shows "This conversation is closed. You can still read it, but new messages aren't possible."
- The thread list tells the app `can_send` true or false per thread so the composer is live or read-only.
- Reasons the server gives when sending is refused (field `reason`):

| reason | HTTP | meaning |
|---|---|---|
| `not_a_party` | 403 | user is not the sender or traveler of this match |
| `no_accepted_offer` | 402 | no deal yet (offer not accepted) |
| `payment_pending` | 402 | deal exists but is not funded |
| `match_closed` | 402 | deal is closed (see list above) |
| `product_request_retired` | 402 | retired request type |

Staff cannot unlock chat for an unfunded deal from the chat itself; the rule follows the deal's funded state.
<!-- src: backend/monolith/apps/matching/services.py (chat_eligibility, chat_history_visible), backend/monolith/apps/chat/views.py -->

## What limits apply to messages? Are attachments allowed?
- Text only. No images, files, voice or attachments exist in chat (the message has only a text body).
- Maximum 2000 characters per message; leading/trailing spaces are trimmed; an empty message is rejected.
- Rate limit: 60 messages per minute per user (a setting fixed by the deployment, default `60/min`).
- Duplicate protection: the app sends a `client_message_id`. Re-sending the same id with the same text returns the existing message (no duplicate). Same id with different text gives 409 `chat_idempotency_conflict`.
- The chat screen shows a permanent warning: "Never send a pickup or delivery code in chat."
- Messages cannot be edited or deleted by users.
<!-- src: backend/monolith/apps/chat/serializers.py, models.py, views.py, config/settings/base.py, mobile/lib/features/chat/chat_thread_screen.dart -->

## What is shown or hidden in chat? What does read / unread mean?
- Each message shows text, sender and time. A message becomes "read" when the other person's app fetches it (opens the thread); only the other party's messages are marked read.
- The inbox row shows the other person's name, a coarse route ("PickupCity → DeliveryCity", never a street address), the last message, last time, and an unread count. Threads sort by latest activity; threads with no message yet sort by match date.
- Reading a thread resolves its chat notifications in the bell, so the badge drops.
- History can be fetched in pages of 50 (up to 200) or by cursor ("latest", "after_id", "before_id"); bad cursors return 400 with a plain message.
- Exact addresses are not part of chat; the chat does not reveal anything the deal has not already unlocked.
<!-- src: backend/monolith/apps/chat/views.py, serializers.py -->

## Is chat moderated? Can staff read it?
- There is no automatic moderation, word filter, block or report-message button in the code.
- Staff have no screen to read chat. Neither the admin console nor the Django admin has a chat page, and the AI helper has no chat tool. Dispute evidence bundles only record that a conversation existed (message count, first and last message time), not the text; the text stays in the chat table.
- Users report abuse through support (see the support section) or by opening a problem report / dispute.
<!-- src: backend/monolith/apps/disputes/services.py (_chat_block), apps/admin_panel/console_urls.py (no chat page), apps/chat (no admin.py) -->

## How does the notification bell work?
- The bell is in the app header. It shows a count of active unread items. Screen reader label: "Notifications, N unread".
- Two lists: "Notifications" (active) and "history" (resolved). Page size 30 (max 100).
- Reading and resolving are different. An item can be read but still "active" if it needs action; it moves to history only when the thing it asks for is done.
- Items resolve automatically when the underlying task is done, for example:
  - offer accepted, payment required and payment failed notices: once the deal is funded
  - new offer, offer updated, response reminder: once the offer is no longer pending (answered, expired) or no longer waits for this user
  - rating prompt: once the user rated or the review window closed
  - dispute action: once a dispute exists or the window closed
  - recipient required: once a recipient is added
  - delivery code available (bell item for the sender): once delivery is confirmed
  - chat message: once the message is read
  - leg reminder: once the traveler reports that leg step
  - schedule change proposed: once the sender answered or it is no longer pending
  - early arrival reported: once the sender confirms or declines
  - payout setup needed: once payout setup is ready
  - `deal.updated` and `offer.economics_changed`: silent refresh hints, treated as already resolved
  - everything else stays active until the user reads it.
- "Mark all as read" marks every unread row read (does not delete anything). Rows are never deleted.
- Empty state: "Nothing new. Offers, payments and delivery updates show up here."
- Every notification is a stored row per recipient (the inbox), whether or not push is on. In-app notifications keep working if push is off.
<!-- src: backend/monolith/apps/notifications/views.py, resolution.py, mobile/lib/features/notifications -->

## When is a push notification sent to the phone?
- Push (Firebase, for a closed or background app) is sent per notification event to each recipient who has at least one active registered phone, if push is switched on for the platform (setting `FCM_ENABLED`, off by default) and the event type has push wording.
- Firebase is used ONLY for push to a closed app. Live in-app updates use the Go realtime services over a WebSocket, not Firebase.
- If the user has the app open (live connection), the Go push worker waits 2 seconds and skips the push when the live connection already delivered the event, to avoid a duplicate.
- Push text never contains names, routes, places, prices or codes: only generic wording plus ids. Lock screens never show sensitive data.
- The delivery code is never in a push, and the sender gets only "Delivery code available. Open Wassla when the recipient is ready." The traveler never gets that push.
- Push wording exists in English, French and Arabic, chosen from the user's saved email/communication language (blank or unknown falls back to English).
- Phones that Firebase reports as invalid are switched off (marked inactive). A maintenance command deactivates phones not seen for 180 days (default).
<!-- src: backend/monolith/apps/notifications/push.py, services/internal/notification/fcm.go, management/commands/prune_push_devices.py -->

## Which events send a push? (category decides if the user can switch it off)
Essential (cannot be switched off): offer accepted, payment received, payment failed, refund update, pickup confirmed, delivery confirmed (all three "match.completed / handover.delivery_confirmed" wordings: "The 48-hour protection window has started."), delivery code available (sender only), identity verification result (approved / needs attention / new upload needed), ticket (flight or ferry) result, traveler progress report, trip leg reminder, problem reported, schedule change proposed / answered / applied / withdrawn, delivery cancelled, early arrival reported / confirmed / not confirmed, dispute opened ("Payout is paused while the dispute is reviewed."), dispute resolved, payout update, request cancelled.

Marketplace (user can switch off): request published, new offer, offer updated (including "Proposal expired: It was not answered in time. Nothing was reserved or charged."), proposal response reminder, "New on your route" (route alert), "A traveler can carry your parcel", "A parcel fits your trip".

Messages (user can switch off): new chat message ("You have a new message on Wassla.", no text of the message).

Events with no push (bell/live only): deal refresh hints, offer economics changed.
Chat push goes only to the other person, never back to the sender.
<!-- src: backend/monolith/apps/notifications/push.py (_PUSH_SPECS), backend/monolith/apps/core/redis_bus.py -->

## What notification switches does the user have?
Screen: Profile > Notifications.
- Two switches: Messages ("New chat activity") and Marketplace activity ("Offers, matches, journeys and requests"). Both default ON.
- Essential updates ("Payment, delivery, dispute, verification and account-security updates stay on.") have no switch.
- The switches affect PUSH only. The bell inbox keeps every item either way. They are saved on the account, so they apply to all the user's phones.
- A separate phone-level permission is requested only when the user taps "Enable notifications". If the system permission is off the screen explains how to enable it; "Push is not configured in this build" shows when the app build has no push set up.
- Phones are registered per installation (an app-generated id). Signing out unregisters that phone.
- Staff can view these preferences and registered phones (platform, active, last success/failure; tokens are hidden) in the Django admin lists "Notification preferences" and "Push devices", read-only.
<!-- src: backend/monolith/apps/notifications/models.py, views.py, admin.py, mobile/lib/features/profile/notification_settings_screen.dart -->

## Which reminders exist and when do they fire?
Settings live in the business Settings revision, section "marketplace" (admin Settings); unknown keys are refused when saving.

| reminder | default | range | what happens |
|---|---|---|---|
| Proposal response deadline | on, 6 hours (`offers.response_hours`) | 1 to 168 h | every proposal/counter expires at send time + 6 h, or at pickup time if earlier |
| Proposal reminder | 1 hour before deadline (`offers.reminder_before_hours`) | 0 (none) up to 167, must be smaller than response hours | one push/bell item to the person who must answer: "A proposal is waiting for your answer. Answer soon: it expires shortly." Skipped if that moment is not after the offer was sent |
| Expiry | at the deadline | - | offer becomes `expired`; both are told "Proposal expired"; nothing reserved, charged or counted against anyone |
| Depart reminder | 30 min after planned departure (`reminders.depart_after_minutes`) | 5 to 1440 | asks the traveler "How is your trip going?" |
| Arrive reminder | 60 min after planned arrival (`reminders.arrive_after_minutes`) | 5 to 1440 | same question for arrival |
| Repeat | every 180 min (`repeat_after_minutes`), max 2 repeats (`max_repeats`) | 15 to 1440; 0 to 5 | repeats until the traveler reports |
| Master switch | `reminders.enabled` on | | off stops leg reminders |

- Leg reminders only go to a traveler whose leg carries a funded parcel, and stop when that step was reported, the journey is not live, the times changed, or an earlier step is still unreported.
- Turning the deadline switch off only stops new deadlines; offers already having one keep it.
- Trip-fit alerts ("A parcel fits your trip"): on by default; at most 30 travelers told per request and at most 5 per traveler per 24 hours (`discovery.trip_fit_max_travelers`, `trip_fit_daily_cap`). "I can carry this" signals: 10 per traveler per 24 hours (`discovery.interest_daily_cap`).
- Route alerts: at most one notification per alert every 6 hours (fixed in code; the app says "at most one notification per alert every few hours").
- Email reminder: "Payment protection ends soon" is emailed to sender and traveler 24 hours before the 48-hour protection deadline (86400 s, environment value `PROTECTION_ENDING_REMINDER_SECONDS`; 0 turns it off). It is not sent if that moment already passed, and is dropped as stale if protection is no longer current.
<!-- src: backend/monolith/apps/core/marketplace_policy.py, matching/offer_deadlines.py, trips/progress.py, discovery/alerts.py, handover/services.py, config/settings/base.py -->

## What emails does the app send, and when?
Every email is tied to a durable record (visible in Django admin "Outbound messages"). Kinds and triggers:

| email (subject) | to | when |
|---|---|---|
| Confirm your Wassla email (6-digit code) | new user | at signup; code valid 15 min (`EMAIL_VERIFY_CODE_TTL_SECONDS`), 5 attempts (`EMAIL_VERIFY_MAX_ATTEMPTS`) |
| Reset your Wassla password (code) | user | password reset request |
| Wassla security notice | user | after password reset completes |
| You have been invited to Wassla Operations (private one-time link) | invited staff | admin invites staff |
| Wassla identity verification update | traveler | staff approve, reject, or ask for new upload of ID |
| Wassla flight ticket update / Wassla ferry ticket update | traveler | staff decide on a ticket proof |
| Your Wassla payment needs attention (failed) | payer account | a payment attempt truly failed (not expiry/cancel); withdrawn if later success is proven |
| Your Wassla payment receipt / Your Wassla guest payment needs attention | guest payer (no account) | guest-link payment succeeded or failed |
| Wassla refund update | account owner (+ guest payer if they paid) | refund started or completed |
| Pickup confirmed | sender | traveler's pickup confirmed; mentions the delivery-code buffer minutes (default 30) |
| Your delivery code is now available (no code inside) | sender | buffer ended and code released: "The code is not in this email. Open the app to see it." |
| Your Wassla delivery code | parcel recipient | same moment; this is the only email that contains a code |
| Delivery confirmed | sender and traveler | recipient's code accepted; states protection end time |
| Payment protection ends soon | sender and traveler | 24 h before protection ends |
| Payment protection has ended | sender and traveler | protection closed with no dispute |
| A dispute has been opened | sender and traveler | dispute opened |
| Your dispute has been resolved | sender and traveler | resolution recorded (full sender refund, full traveler payout, partial split) |
| Payout update | traveler | payout becomes eligible, needs payout setup, is processing, sent, paid, needs attention, or the bank returned it |
| Delivery cancelled | sender and traveler | deal cancelled (reason: by sender, traveler, admin, or declined new times) |
| Leave a review | sender and traveler | at delivery confirmation (review window opens) |

- Not used by any code path today (templates exist but nothing arms them): "Payment needed for your Wassla delivery", "Your Wassla payment is processing", "Wassla payment confirmed" for account owners, and "More information is needed for your Wassla case" (evidence request). Do not promise these emails.
- Offers, chat, route alerts and similar marketplace events are NOT emailed; they are bell/push only.
- Emails are plain, branded layout with code box, fact rows (tracking number, payment reference, amount in EUR, dispute reference).
<!-- src: backend/monolith/apps/notifications/outbox.py (subjects), models.py; finance/payout_reconciliation.py (NOTIFIABLE_CODES); callers in accounts/views.py, admin_panel/services.py, handover/services.py, finance/*.py, disputes/services.py, deals/cancellation.py -->

## How does the recipient get the delivery code by email?
- The recipient (the person named by the sender after funding) does not need an account. Their email comes from the recipient details the sender entered ("The delivery code is sent here. Make sure it's right.").
- Timeline: traveler confirms pickup, then a 30-minute safety buffer (1800 s default, set by lifecycle policy), then the code is released. At release the system queues the recipient email (up to 12 send attempts) and the sender's "code available" email.
- Subject "Your Wassla delivery code", heading "Your parcel is on its way", box "Your delivery code", hint "Keep this code private until the parcel is in your hands." Includes tracking number and the sender's name ("Your sender" if blank).
- Language: the recipient's own chosen language (EN/FR/AR), set when the sender adds the recipient ("This is the language we'll use for the recipient's delivery email"); blank falls back to English.
- Safety: the code is never stored in the email record, never in push, bell, logs or the traveler's view. It is sealed and opened only at the moment the email is built. The traveler can never retrieve it.
- If the recipient email address is changed or the code is no longer active, the old email is obsolete and is not sent. If no recipient exists at release time (should not happen), the error is logged and the sender still holds the code.
- Staff cannot read the code from the console; the Outbound messages list only shows "Sealed secret: Yes" and the detail page "Carries a sealed secret: Yes".
<!-- src: backend/monolith/apps/handover/services.py, notifications/outbox.py, backlog.py -->

## What languages are used? How is Arabic / right-to-left handled?
- Three languages everywhere: English (en), French (fr), Arabic (ar). English is the fallback.
- App language: a per-phone setting (Profile > Language), default follows the device; applies instantly; stored on the phone only. Arabic switches the app to right-to-left.
- Email language ("what we write to you in": payments, verification, deliveries, disputes, account security): saved on the account (`preferred_language`), chosen at signup or Profile > Language. Blank = English.
- The language is frozen on each email at the moment it is queued; changing language later does not change emails already queued.
- Guest payers get emails in the language chosen on their guest link. Recipients get the language on the deal's recipient record.
- Emails in Arabic use right-to-left layout; amounts and references are wrapped so they do not flip.
- Push text is chosen from the user's saved language (en/fr/ar).
- Translations of email text live in the French and Arabic message catalogs; missing text falls back to English.
<!-- src: backend/monolith/apps/core/languages.py, accounts/models.py, notifications/email_layout.py, mobile/lib/app/app_settings.dart, features/profile/language_screen.dart -->

## What happens when an email fails to send?
- Each email is a durable row with status: `pending`, `dispatched` (accepted by the mail provider), `failed`, `cancelled`. Visible to staff in Django admin > Outbound messages (filter by status, kind, language; search by email, key or error). It is read-only; rows cannot be deleted or edited.
- Master switch: `EMAIL_ENABLED` (deployment setting, default off). While off, nothing is sent and rows stay pending; they can still be sent after activation. Email is required for going live with payments.
- Retries: wait 60 s, doubling each attempt, capped at 6 hours. Default max 10 attempts (12 for the recipient delivery code).
- Permanent provider refusal (a 5xx code such as a bad address) fails at once with `smtp_permanent`; temporary trouble is `smtp_transient` until attempts run out.
- A message that can never be built (missing secret, no longer valid) is marked failed with `email_context_or_capability_unavailable`.
- Sending is rate-limited to 60 emails per minute in total (`EMAIL_RATE_LIMIT_PER_MINUTE`, 1 to 600); Django and the Go email worker share the same limit.
- Old backlog guard: a message older than 48 hours (or created before the activation cutoff) is held (`activation_held`) and is not sent until an operator reviews it. Reviews are explicit and audited: "release" or "cancel" through a maintenance command that never sends mail itself; an audit command lists the backlog.
- Messages can be cancelled when superseded (e.g. payment failed notice cancelled after later success).
- The console System page shows an Email status (enabled, configuration complete or incomplete). The health check counts pending and failed outbound messages and the length of the email queue; push has its own status (disabled, configuration incomplete, ready, degraded).
- Delivery is "at least once": rarely a duplicate can occur after a crash. Provider acceptance is not proof the inbox received it.
<!-- src: backend/monolith/apps/notifications/outbox.py, delivery_policy.py, backlog.py, admin.py, admin_panel/health.py, console_views.py, config/settings/base.py -->

## How do live (real-time) updates work?
- The app keeps a live WebSocket to the Go notification service (`/ws/notifications`) and, in an open chat, to the Go chat service (`/ws/chat`). The login token is checked on connect.
- The server (Django) saves the event first, then publishes it after the database commit; Go only relays it to the user's open connections. If Go or Redis is down, Django keeps working and a retry job re-sends the event (first retry about 30 seconds later).
- When a live event arrives the app re-reads data from the server (the server stays authoritative), then updates the screen; events are merged within about 75 ms.
- Chat history is always reloaded from Django, so missed live messages are recovered by cursor on reconnect.
- Presence: a "user is online" marker lasts 15 seconds and is refreshed while connected; ping interval is 10 seconds.
<!-- src: backend/monolith/apps/core/redis_bus.py, notifications/transport.py, services/cmd/chat, services/cmd/notification, internal/notification/presence.go, mobile/lib/core/live/live_updates.dart -->

## What are the Go services in backend/services?
- `notification`: live WebSocket hub for bell/live events, plus the worker that sends Firebase push to closed apps (only if push is enabled and no live delivery happened within 2 s).
- `chat`: relays new chat messages to the two people's open chat sockets. Read-only relay; it never writes messages (Django does).
- `email`: reads the email queue and sends ordinary (non-secret) emails over SMTP, records delivery receipts. Gated by `EMAIL_ENABLED`. Code-bearing emails (verification, reset, invitation, recipient delivery code) are sent by Django directly so codes never go through the queue.
- `kyc`: accepts identity-document uploads (JPEG or PNG, max 8 MiB per image, rate-limited), stores them in object storage and records the submission in Django. See accounts-and-verification.md.
- Shared libraries (pkg) cover login-token checks, config, database, health checks, retries, metrics, Redis and storage.
<!-- src: backend/services/cmd/*, internal/*, HANDOVER.md -->

## What does the public website contain?
Static site in `web/` (no build step). Routes: `/en/`, `/fr/`, `/ar/` (Arabic is right-to-left), plus `/terms.html`, `/privacy.html`, `/prohibited-items.html`, `/support.html`. The root page links to the three languages. The legal and support pages are English only; their language links open the localized home page.
- Home page sections: hero ("Your package already has a ride"; trust chips: travelers pass identity checks, payment held until delivery, exact addresses private until funded); journeys as legs (flight legs need approved ticket proof, drive legs need no vehicle document at launch, capacity per leg); how to send (request, match, agree, pay, hand over, protection) and how to carry (verify, journey, offers, carry, confirm, payout); protections (private until funded, posting deposit credited not double charged, sender proposes first, two codes, deliberate delay, protection period, disputes freeze payout); price (example: €30.00 reward + €7.50 Wassla fee = €37.50 paid; the fee is added on top, so the traveler gets the full €30.00; EUR is canonical and a Chargily DZD figure at checkout is a platform conversion, not a second price); trust checks; FAQ (what can I send, who can carry, when does the traveler get paid, cancellations, why the traveler cannot see the delivery code, is Wassla available now); contact link.
- Terms (draft): use of Wassla, matching and agreements, payment and 48-hour protection, handoffs and prohibited use, cancellations/disputes/ratings, contact. Privacy (draft): data used, how, sharing, retention (periods not yet stated), user rights via support, cookies (no advertising cookies). Prohibited items (draft): weapons, illegal drugs and counterfeit goods, live animals/human remains/hazardous materials, stolen goods or cash equivalents or customs evasion, anything illegal in departure/transit/arrival country or by carrier; sender responsible for customs declarations; a match is not customs clearance.
- All legal pages say they are drafts pending French, EU and Algerian legal review. The site claims no payment provider is live.
- The in-app Profile has "Terms" and "Privacy" rows that open these web pages (web base address set in the build; shows "link could not be opened" if missing).
- The site's address in the sitemap/robots files is a placeholder (`shiptrip.example`) to be replaced at deploy.
<!-- src: web/*.html, web/en/index.html, web/README.md, mobile/lib/features/profile/profile_screen.dart -->

## How do users contact support?
- Website support page lists four mailboxes (placeholders marked "must be replaced with verified support mailboxes before launch"): general support, safety and disputes, privacy requests, payment questions. Users should include name, account email, and a deal or payment reference; never a handover code ("no one at Wassla will ever ask you for one"). Not an emergency service.
- In the app there is no support button or contact row. Profile's "Help and support" section holds only Terms of service and Privacy policy. Some screens only tell the user in text to contact support: the closed dispute window ("Disputes can be opened for 48 hours after delivery. Contact support if you still need help."; no button is drawn), the email-code screen if the code never arrives, and a journey paused by staff.
- Emails: the support address and reply-to are deployment settings (`EMAIL_SUPPORT_ADDR`, `EMAIL_REPLY_TO`, sender name default "Wassla"); the admin invitation email tells recipients to "contact Wassla support" if unexpected.
- The server tells the app the same address: `GET /api/support` (no sign-in, limit 30 a minute) answers `{"email": <EMAIL_SUPPORT_ADDR>}`, or `{"email": null}` while it is not set. No address is invented. The app's "Contact support" action opens an email to it (the delivery's tracking number goes in the subject when asked from a delivery). It appears in Profile, on the dispute screen, with the problem list on a delivery, and on a journey paused by staff, and is absent everywhere while the answer is null.
<!-- src: web/support.html, mobile/lib/l10n/app_en.arb, mobile/lib/features/profile/profile_screen.dart, mobile/lib/features/disputes/dispute_open_screen.dart, config/settings/base.py, notifications/outbox.py, notifications/views.py (SupportContactView) -->

## Worked examples
- Sender pays at 10:00 and the traveler confirms pickup at 14:00: pickup email to the sender at 14:00 saying the code appears in 30 minutes; at 14:30 the recipient gets "Your Wassla delivery code" by email and the sender gets "Your delivery code is now available" (no code inside). The traveler sees nothing with the code.
- Delivery confirmed at 09:00 Monday: protection ends 09:00 Wednesday; "protection ends soon" email goes at 09:00 Tuesday; "protection has ended" after Wednesday 09:00 if no dispute.
- Proposal sent 12:00 with default 6 h: expires 18:00, reminder to the answerer at 17:00. If pickup time is 15:00, expiry becomes 15:00 and the reminder 14:00.
- User turns Messages push off: new chat message still lands in the bell and the chat thread; no phone push. An offer accepted notice still pushes (essential).

## Not covered here
- Exact copy of the French and Arabic email texts (kept in the translation catalogs).
- The real support mailbox addresses and final live site domain (placeholders in the repo).
- Exact environment values in production for `FCM_ENABLED` and `EMAIL_ENABLED`.
- Retention periods for messages and notifications (privacy page says not yet defined; no automatic deletion found for chat or notifications).
