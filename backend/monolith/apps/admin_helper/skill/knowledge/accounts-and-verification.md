# Accounts, Identity and Trust

Covers: how people sign up and sign in, account states, ban and restore, ID verification, ticket-proof verification, the staff verification inbox, payout identity checks, public profiles, privacy, and people without accounts.
Related files: admin-console.md, money.md, trips-and-matching.md, deliveries.md, messages-and-notices.md, app-walkthrough.md, settings-and-helper.md

## How does someone create an account?
- The app has one sign-up form: full name, email, password, phone number. The app sends the language the person is using as their email language.
- Rules (the server checks them):
  - Full name: 2 to 120 characters.
  - Email: must be new (compared ignoring upper/lower case). Error: "An account with this email already exists."
  - Password: 8 to 128 characters, not a very common password, not only digits.
  - Phone: required, 6 to 32 characters. It is not checked by SMS.
  - Region (wilaya): optional old field, 2-letter Algerian code. Not needed. EU users leave it empty. Error if wrong: "Invalid wilaya code."
  - Email language: `en`, `fr` or `ar`. Default English.
- Sign-up is limited to 30 per hour per network address (many people share one address on Algerian mobile networks; each sign-up still needs a new email, and an unconfirmed account cannot post). Then the person gets a 6-digit code by email (see below).
- Everyone gets the role "both" (sender and traveler). The app does not ask people to pick a role, and nothing in the app, the API or the operations console lets anyone change it. Only the technical Django admin (Technical records, Super Admin only) can edit it. Staff accounts made from an invitation get the role "admin".
<!-- src: backend/monolith/apps/accounts/serializers.py, views.py, config/settings/base.py, mobile/lib/features/auth/sign_up_screen.dart -->

## Which sign-in methods exist?
- Email and password. Wrong details: "Incorrect email or password." Limit 10 tries per minute per network address (kept tight: there is no per-account lockout, so a looser limit has no other bound; it stays at 10 even though many people share an address).
- Google sign-in and Sign in with Apple: the server has an endpoint for each (`/api/auth/oauth/google`, `/api/auth/oauth/apple`), and the app offers "Continue with Google" and "Continue with Apple" on the sign-in screen, the sign-up screen and the account screen (see "How does browsing without an account work?"). A button shows only when the build is set up for it: Google needs the Google client ids built into the app, Apple needs `APPLE_SIGN_IN_ENABLED=true` and shows on iPhone only (Android offers Google only). A build with neither shows email sign-up only. Both follow one rule:
  - A Google or Apple account already linked signs in to its Wassla account.
  - A token without an email (Apple, when the person did not share it) still signs in to an Apple account already linked; it cannot link or open an account: `email_missing` "Apple account has no verified email." (400). An email the token carries must be one the provider says is verified, else "Google account email is not verified." (Apple: "Apple account email is not verified."). Otherwise, if the email already has an account, the identity is linked to it. If that account never confirmed its email, the provider's proof wins, because whoever opened it never proved they own the address: its password stops working, every signed-in session ends and every phone stops getting its notifications, what was typed at sign-up is replaced as for a new account (name from the provider; phone, region and language from this sign-in; phone tick cleared), and the account becomes verified. The owner can set a password again with "reset password". A confirmed account is linked and nothing of it changes, except an empty name, which takes the provider's name. If no account exists, a new one is made with a password nobody can use, and the email is marked verified. One email can be linked to both Google and Apple.
  - A banned or disabled account gets no sign-in, whether its Google or Apple account was already linked or only the email matches: the answer is `account_disabled` "This account is disabled." (403), and nothing of the account changes. After a restore, the person can sign in again the same way.
  - The name comes from the provider. With no name, the name stays empty (it is never made from the email). An empty name is set once: by a later Google or Apple sign-in that brings a name, or by the person through `PATCH /api/me` (see "What is on a profile"). A name that is set is never overwritten by a sign-in. Apple gives the name to the app only on the first sign-in, never inside its token, so the app sends it with that request.
  - Phone, region and language can be sent when it creates a new account.
  - Two first sign-ins at the same moment make one account and one link, never an error.
  - Not set up on the server: `google_sign_in_unavailable` "Sign in with Google is not available right now." / `apple_sign_in_unavailable` "Sign in with Apple is not available right now." (503). Google or Apple cannot be reached: a retryable 503 with the same code. Limit 30 per minute each, per network address.
  - Apple checks: the token must be signed with one of Apple's published keys (RS256 only), issued by Apple, made for the Wassla iOS app (its bundle id, `APPLE_SIGN_IN_CLIENT_IDS`), not expired (30 seconds of clock tolerance), carry the value the app made for this sign-in (it binds the token to that sign-in; the token's short life bounds any replay, and a retry with the same token still works, because Apple gives the name only on the first try), and, when it carries an email, say that email is verified. Any failure is a 401 with a short fixed reason, for example "The Apple identity token is not valid." Google's refusals are fixed text too: "The Google ID token is not valid.", "The Google ID token is not for this app.", "The Google ID token was not issued by Google." If the person chose Apple's "Hide My Email", the email is Apple's relay address, so it matches no existing account.
- There is no phone/SMS sign-in.
<!-- src: backend/monolith/apps/accounts/social.py, apple.py, google.py, views.py (GoogleSignInView, AppleSignInView), models.py (OAuthIdentity), urls.py, config/settings/base.py -->

## How long does a sign-in last?
- Access token: 5 minutes (setting `JWT_ACCESS_TTL_SECONDS`, 300). Refresh token: 30 days (2,592,000 s). Each refresh gives a new refresh token and retires the old one.
- Sign out retires the refresh token and unregisters that phone from push notifications.
- These are server environment settings, not on the console Settings page.
<!-- src: backend/monolith/config/settings/base.py -->

## How does email verification work?
- After sign-up a 6-digit code is emailed. It is valid 15 minutes and allows 5 tries in total. Limit 10 attempts per hour. These are server environment settings, not on the console.
- A signed-in member can ask for a new code: `POST /api/auth/verify-email/resend` (limit 5 per hour, server setting `DRF_EMAIL_VERIFY_RESEND_THROTTLE_RATE`). It always answers "done". A verified account is sent nothing; otherwise every older unused code stops working, its email is withdrawn if still waiting, and a fresh code is emailed. The app's code screen has a "Send the code again" button for it, and says only the code in the newest email works. The same screen opens from Profile ("Verify email", shown while the email is not confirmed) and whenever posting a parcel or changing payout setup is refused with `email_verification_required`; the member returns to the form with what they typed still there.
- Any wrong code or unknown email gives the same answer: "Invalid code." (so nobody can find out which emails exist).
- Correct code sets "Email verified". Doing it again for a verified account is fine.
- Posting a parcel needs a verified email (V1 specification: sender verification is email-only). Until then creating a delivery request is refused with `email_verification_required` "Confirm your email address first." Changing payout setup needs it too (see money.md). Nothing else checks the tick: browsing, pricing, travelling, ID upload and everything else stay open. Google or Apple sign-up and invited staff accounts are marked verified automatically; signing in with Google or Apple on an unconfirmed account with the same email verifies it (see sign-in methods above).
- Staff see "Email verified" or "Email not verified" on the person page.
<!-- src: backend/monolith/apps/accounts/models.py, views.py (VerifyEmailView, ResendVerifyEmailView), social.py, parcels/views.py (DeliveryV1CreateView), console_people.py -->

## What if a user forgets the password?
- They enter their email. The answer is always "accepted" (202) even for unknown emails.
- A 6-digit code is emailed, valid 15 minutes, 5 tries. Limit 5 per hour, shared by asking for a code and using it. Only the newest code counts.
- With the code and a new password (same rules as sign-up) the password changes, every other signed-in session ends (refresh tokens revoked, phones stop getting notifications), and the email counts as confirmed, because the code went to it. A security email "password reset completed" is sent. Wrong or used code: "Invalid code." and nothing changes. A sign-in already open keeps working for at most 5 minutes (the access token's life, `JWT_ACCESS_TTL_SECONDS`).
- Google-only and Apple-only accounts have no password; they can set one this way.
<!-- src: backend/monolith/apps/accounts/views.py, models.py -->

## What is on a profile and what can the user change?
- Fields: id, email, full name, phone, region, role, email language, phone verified, email verified, ID verified, ID status, rejection reason, date joined.
- Through the API (`PATCH /api/me`) a user can change the email language (`en`, `fr`, `ar`) at any time, and set their name once while it is empty (an account opened with Google or Apple without a name): 1 to 120 characters, trimmed. Once a name is set, changing it is refused: `name_already_set` "Your name is already set." (400). The app asks for it on a "What should we call you?" screen: right after a Google or Apple sign-in that left the name empty, and otherwise on Home once per app launch until it is set. The person may close it. Phone and email cannot be changed.
- Support cannot change them either: the operations console has no edit page for a member's details. Only the technical Django admin (Technical records, Super Admin only) can edit name, phone, email, role and the verified ticks.
- App language (what they read in the app) is stored on the phone only. Email language is saved on the account. It covers payments, verification, deliveries, disputes and account security emails. Blank = English.
- "Phone verified" is shown but nothing in the code sets it; it stays "Phone not verified". Do not tell users the phone is checked.
<!-- src: backend/monolith/apps/accounts/serializers.py, core/languages.py, mobile l10n profileEmailLanguageHelp -->

## What account states exist?
| State (console) | Meaning |
|---|---|
| Active | Can sign in and use the app. |
| Banned | Staff banned them. Cannot sign in. |
| Sign-in disabled | Account switched off without a ban: a staff account disabled on Staff & access, or any account switched off in the technical Django admin. Cannot sign in. |
- A banned or disabled person who tries to sign in with a password sees "Incorrect email or password." The server refuses inactive accounts before its own "This account is disabled." check, so that message does not appear for a password. With Google or Apple they get `account_disabled` "This account is disabled." (see sign-in methods).
- A member can delete their own account (see "How does a member delete their account?"). A deleted account shows as Sign-in disabled. The helper reports `deactivated` for an inactive non-banned account.
- Users list filters: Active, Restricted (banned or disabled).
<!-- src: backend/monolith/apps/admin_panel/console_people.py (_header), console_views.py, admin_helper/resources.py, apps/accounts/deletion.py -->

## How does a member delete their account?
- In the app: Profile > "Delete account" (under Sign out). On the web: the page /delete-account (English, French, Arabic) gives the steps and the email route (contact@wassla.eu, subject "Delete my account").
- It is refused while anything is open, each listed in the app: a delivery not closed, an open dispute, a payout or refund not yet reached them, an open parcel request, a published or under-way trip. The member finishes or cancels those first; deletion never cancels anything or moves money.
- The password is asked when the account has one (`password_incorrect` if wrong). An account with Sign in with Apple confirms with Apple on an iPhone; the server revokes Apple's token first, and if Apple refuses or cannot be reached nothing is deleted. On Android such an account is told to delete from an iPhone or write to support.
- Deleting is immediate and permanent: every session ends; name, email (replaced by an address that cannot receive mail, so the real email can sign up again), phone, region, language, password, Google and Apple links, sign-in and email codes, push devices, inbox, notification settings, route alerts, public profile and profile photo (the stored image too) are erased; pending emails are cancelled.
- Kept, pointing at the emptied account: deliveries, payments, refunds, payouts and payout details, ID check decisions, reviews, problem reports, disputes and chat history. Other members see "Deleted account" in chat.
- Staff accounts cannot be deleted from the app (`staff_account`).
<!-- src: backend/monolith/apps/accounts/deletion.py, apple_revoke.py, views.py (AccountDeletionView), mobile/lib/features/profile/delete_account_screen.dart, web/delete-account.html -->

## What does a ban do, and what does restore do?
- Who: only roles with `manage_users` (Super Admin). Console: person page, button "Ban account" or "Restore account". A reason is required (up to 500 characters), kept in the audit log, never shown to the person.
- Ban sets banned and turns the account off. The console says the person "is signed out at once and cannot sign in, including in the middle of a delivery."
- A ban does NOT cancel deliveries, move money, refund or release/stop a payout. Staff must do those separately.
- Side effects found in code: banned people are not shown as travelers/senders in matching and lists, their public profile disappears, route alerts stop, they cannot be a payout traveler, and compatibility checks fail for their requests and journeys.
- Restore turns it back on: "The person can sign in again."
- Refusals: "You cannot ban or restore your own account." / "This is a staff account. Staff access is changed on Staff & access, not here." / "This account is already banned." / "This account is not banned." If a colleague changed it first: "... Nothing was changed."
- The AI helper can prepare the same change (`user.ban`, `user.unban`) with a change key; the admin must press Confirm.
- At a password sign-in a banned person sees "Incorrect email or password." (the same answer as wrong details); with Google or Apple, "This account is disabled."
<!-- src: backend/monolith/apps/admin_panel/console_account.py, staff_actions.py, matching/compatibility.py, discovery/profiles.py, finance/payout_profiles.py, admin_helper/actions.py -->

## What is ID verification and who needs it?
- A traveler must have a current approved ID before a journey can be published, listed, matched or accepted. App text: "You need to be verified before you can publish a journey." and "You're verified. You can publish journeys and carry parcels."
- Senders do not need ID verification: no sender action checks it.
- It is rechecked when offers are created or accepted, not only at publish. If the approval expires, the journey stops matching. Error code `traveler_kyc_not_approved`: "Current traveler KYC approval is required for this journey."
- Payout identity checks (below) also need an approved ID.
<!-- src: backend/monolith/apps/trips/services.py, matching/compatibility.py, mobile/lib/l10n/app_en.arb -->

## What does the user upload?
- Screen: Profile, Verification card, "Identity check".
- Document type: National ID card, Passport, or Driving licence.
- Photos: front of document (required), back (required for ID card and driving licence, not for a passport), selfie (always required, taken with the front camera, "checked against your document").
- Limits: JPEG or PNG only; each photo under 8 MB; total request 25 MB; large pixel counts refused. The file content is checked, not just the name.
- Upload limit: 6 uploads per person per hour by default. A per-network-address limit exists but is off by default. Over the limit: "Too many KYC upload attempts. Try again later." These are server environment settings (`KYC_UPLOAD_USER_LIMIT`, `KYC_UPLOAD_USER_WINDOW_SECONDS`, `KYC_UPLOAD_IP_LIMIT`), not on the console.
- Retrying the same submission does not make a duplicate (a one-time key is kept). Photos go to a separate private store; the main server never handles the image bytes.
- Errors the user may see: "That image is too large. Each photo must be under 8 MB.", "Only JPEG and PNG photos are accepted.", "Verification is temporarily unavailable. Please try again shortly."
- After sending: "Documents received. We'll review them shortly."
<!-- src: backend/services/internal/kyc/handler.go, backend/monolith/apps/kyc/grpc_server.py, mobile/lib/features/kyc/kyc_screen.dart -->

## What are the ID statuses?
| Status | Meaning | What the user sees |
|---|---|---|
| `pending` | Waiting for staff | "Being reviewed. This usually takes less than a day." (the "less than a day" is app text, not a guarantee in code) |
| `approved` | Accepted | "Verified" |
| `rejected` | Refused or "new upload requested" | "Not approved" plus the staff reason, can submit again |
| `expired` | Past its expiry date | Reads as "Not started" |
- The user sees their ID state as `verified`, `pending`, `rejected` or `unverified`. `unverified` means never submitted OR expired.
- A person can have many submissions over time. Only one approved per document type. While one is pending (or once verified) the app hides the form; the server itself does not refuse a second upload.
- Expiry: a submission has an expiry date field, but nothing in the app sets it and the technical admin shows submissions read only. So in practice an approval never expires.
- Staff person page shows: "ID approved", "ID waiting for review", "ID rejected", "ID expired", "No ID submitted".
<!-- src: backend/monolith/apps/kyc/models.py, accounts/serializers.py, console_people.py (_kyc_summary) -->

## Who reviews IDs, and how?
- Console: Verification (inbox) with two tabs, ID and Tickets. The nav total and tab counters count only rows in `pending`. Opening Verification lands on the first tab that has work.
- Tabs show only if the role has the right: ID tab needs `view_kyc`, Tickets tab needs `view_flight_proofs`.
- Roles: Trust & Verification and Super Admin can view and review. Ops, Support, Finance cannot review IDs. Support "cannot review private verification evidence". Finance "cannot read private evidence".
- Review page: shows the photos (front, back, selfie) with a preview, the person, how long it has waited, and earlier submissions. Decisions:
  1. Approve.
  2. Ask for a new upload (stored as rejected, but the person is told "we need a new upload"; staff see "New upload requested").
  3. Reject.
- Ask and Reject need a reason ("Say what is wrong, so the person knows what to send next time."), up to 2,000 characters, shown to the person exactly as written. A confirm box is required: "I reviewed the evidence and understand this decision is audited."
- After any decision the person's "ID verified" is recomputed: true while they have a current approved submission (an older approval keeps them verified). The person gets an email and a live notification for every decision (approve, new upload, reject). Everything is in the audit log.
- Only a pending row can be decided. A double click with the same decision is accepted quietly. A different decision on a decided row: "Only a pending KYC submission may be reviewed." (tickets: "Only a pending ticket proof may be reviewed.")
- Viewing a photo needs `view_evidence` (Trust, Super Admin) and every open is written to the audit log ("KYC evidence viewed"). If the private store is down the slot shows "temporarily unavailable, try again".
<!-- src: backend/monolith/apps/admin_panel/verification_inbox.py, services.py, console_forms.py, console_views.py, permissions.py -->

## What is ticket-proof verification?
- Every flight leg and every sea leg of a journey needs an approved ticket proof. Road (driving) legs need none. Nobody is exempt. Sea legs are switched off by default.
- Traveler screen: "Ticket proof". They upload a boarding pass, ticket or booking confirmation per leg. Kind options: Ticket, Boarding pass, Booking. Advice: show name, flight number, date and both airports (ferry: name, company, date, both ports).
- Limits: JPEG, PNG or WebP, up to 10 MB; file content checked. Upload limit 20 per hour (shared media upload limit). A retry sent with the same one-time key does not duplicate.
- Only the journey owner, and only while the journey is draft or pending verification. Errors: `journey_not_owned` "Only the journey owner can add ticket proof."; `proof_not_required` "This leg needs no ticket proof."; `journey_proof_upload_closed` "Proof can only be added before journey publication."; `proof_file_missing`; `proof_file_too_large` "File exceeds 10 MiB."; `proof_media_type_unsupported` "Only JPEG / PNG / WebP images are allowed."; `proof_kind_unknown`.
- Proof states shown per leg: Not uploaded (`missing`), Being reviewed (`pending`), Approved, Not accepted (`rejected`, with reason). Approved wins over pending, pending over rejected.
- Publish refusal if a leg lacks an approved proof: `flight_proof_not_approved` "Every flight leg requires a currently approved ticket proof." or `sea_proof_not_approved` (same, "sea leg"). Rechecked on offers and acceptance.
- If the traveler changes what the ticket proves (mode, from/to place, flight number, departure or arrival time) an approved or pending proof goes back to pending and must be reviewed again. Changing only capacity does not. A rejected proof stays rejected.
- Staff: Verification, Tickets tab. Filters: status, mode (Flight, Sea), search traveler or flight number. Same three decisions, same reason rule, permission `review_flight_proofs`. The page shows route nodes and "Flight ticket" or "Ferry ticket".
<!-- src: backend/monolith/apps/trips/proofs.py, views.py, services.py, console_views.py, admin_panel/services.py -->

## What does "verified" unlock and show?
- ID verified: travelers can publish and match journeys (see above).
- On a public profile card: "identity_verified" badge (true only with a current approved ID).
- Email verified: needed to post a parcel and to change payout setup (`email_verification_required`). Nothing else is gated on the "email verified" or "phone verified" ticks; the ID upload is not.
<!-- src: backend/monolith/apps/discovery/profiles.py -->

## What is a payout identity check?
- It is a Trust step before a Traveler's DZD payout method can be approved by Finance.
- Finance assigns the check to a reviewer (needs `review_payout_profiles` and `view_payout_sensitive`; the reviewer must have `attest_payout_identity`, i.e. Trust or Super Admin). The traveler must have a current approved ID: "This Traveler has no current approved ID. Their KYC submission has to be approved first."
- Console page: Payout identity checks (tab "mine" or "all"). The assigned reviewer opens the ID photos next to a two-field form: legal first name(s) and last name exactly as on the ID, optionally up to 10 other spellings. Only the assigned reviewer can confirm: "Only the assigned reviewer can confirm this identity."
- After confirming: "Identity confirmed for NAME. Finance can now approve or reject their payout method."
- The legal name is stored encrypted and is never shown back. Finance only sees a comparison with the payout account holder name: consistent, review alias or spelling, mismatch, or insufficient attestation. A person always makes the final decision.
- The attesting reviewer can revoke their own confirmation. A newer confirmation replaces the older one.
- Refusals: "Legal given and family names required." (max 160 characters each); "The identity check could not be recorded against a current approved ID. Reload the page and try again."
- Person page, Identity tab, lists ID submissions, confirmations (Current, Superseded, Revoked) and open checks.
<!-- src: backend/monolith/apps/finance/payout_profiles.py, payout_identity.py, admin_panel/console_identity_checks.py, console_payout_reviews.py -->

## What can staff see on a person, and what is private?
- The Person page has tabs: Overview, Identity, Activity, Deliveries, Payments, Payouts, Trust & support, Discovery, Audit. A tab only shows if the role may read it.
- Phone number and region only show with `view_user_sensitive` (Trust, Super Admin). Support cannot see them.
- No bank or payout account value appears on the person page, not even masked. No ID image is embedded; it is reached only through the audited KYC review. No chat content: the console has no support access to chats. Ratings show only after the blind reveal.
- AI helper rule: its person answers hold only id, name, console link, account status (active, banned, deactivated), member since (month and year), and counts of requests, trips and deliveries. It never gets documents, bank details, delivery codes, chats, phone, email, or exact addresses. Treat all of that as off limits and send the admin to the console page.
- Staff notes can be added on the person (Overview tab).
<!-- src: backend/monolith/apps/admin_panel/console_people.py, admin_helper/resources.py -->

## What is a public profile and what does it show?
- Optional. Off by default. The user turns it on in Profile, "Public profile" ("Show my public profile"), accepting the wording; the version agreed and the time are saved. They can turn it off any time, even if the feature is paused.
- Others see: first name only, ID verified or not, rating, completed deliveries, "member since" (month and year), and up to 3 usual routes (city to city).
- Never shown: last name, email, phone, exact address or position.
- Visible only when ALL hold: member turned it on, staff have not hidden it, account active and not banned, and the setting `profiles_enabled` is on. People are listed if they have a usual route or activity in the last 12 months (365 days).
- Switch: Settings, marketplace, discovery, `profiles_enabled` (default on). When off, users see "Public profiles are paused for now. Please check back later." and cannot turn theirs on ("Public profiles are not available right now.").
- Max usual routes 3 (fixed). Errors: "A public profile shows at most 3 usual routes.", "A usual route needs two different cities.", "Each usual route can be listed once."
- States the owner sees: visible, not visible, hidden ("Your profile is not currently visible to others." with no reason), disabled.
- Staff: person page, Discovery tab. State chips: Never set up, Turned off by the member, Visible, Hidden by staff. Button "Hide profile" or "Show profile again" (needs `manage_users`, reason up to 500 characters, audited, member not told the reason). Hiding someone with no profile makes any future profile start hidden. Showing again restores the member's own choice. The AI helper can prepare `profile.hide` / `profile.show`.
<!-- src: backend/monolith/apps/discovery/profiles.py, models.py, core/marketplace_policy.py, admin_panel/console_discovery.py, mobile l10n publicProfile* -->

## What are profile photos, and who sees them?
- Optional, one per member (owner decision of 2026-11-24). The server side is built; the app screens to add, change and remove a photo come in a later app update (package P3B), so until then nobody can add one from the app.
- Everyone who sees the person's first name sees the photo, people without an account included: trip and parcel cards, people cards and the person page, trip details, Find Travelers, route alerts and proposals. The chat list and the chat header show the other person's photo too, also on a blocked or closed thread (it shows their name), but the "Blocked people" list shows none and messages carry none. A photo of a banned or deleted account is never shown, and a banned or deactivated account cannot add one (it can still remove it).
- Nobody checks a photo first: it is visible as soon as it is saved. Staff remove an unsuitable one afterwards (see admin-console, "How do I remove a member's profile photo?").
- The server never keeps the uploaded file. It turns the picture upright, crops the centred square, makes it 512 x 512 and saves a new JPEG with no hidden data (no location, camera or date). Accepted: JPEG, PNG or WebP up to 10 MB; anything else is refused.
- Photos are shown through links that stop working after 30 minutes; the app fetches fresh ones. A removed or replaced photo's image is deleted by a background job (`profile_photo_object_delete`) that keeps retrying until storage confirms; a failed one shows in System > Background jobs and can be retried there.
- There is no "report this photo" button. A member can block someone from the chat or write to support; staff can remove the photo.
<!-- src: backend/monolith/apps/accounts/photos.py, apps/core/storage.py (square_jpeg_without_metadata) -->

## What trust signals do people see?
- ID verified badge, rating, completed deliveries, member since (month and year) on the public card.
- Ratings details (blind reveal, moderation) are in another file.
<!-- src: backend/monolith/apps/discovery/profiles.py (profile_card) -->

## What stays private, and when are exact details revealed?
- Exact pickup and delivery locations stay hidden until the deal is funded (product rule; the traveler sees them only after funding).
- The traveler cannot read the delivery code; it stays locked 30 minutes after pickup (product rule). The code is emailed to the recipient. See deliveries.md.
- ID documents, selfies and tickets: private storage, staff with `view_evidence` only, each view audited. Ticket images are shown to the owning traveler and reviewing staff only.
- Payout identity names: encrypted, never displayed.
- Passwords and one-time codes are stored hashed.
<!-- src: CLAUDE.md invariants, backend/monolith/apps/trips/models.py (JourneyLegProof), admin_panel/console_views.py -->

## How does browsing without an account work?
- Opening the app without a session shows the normal Home, not a welcome screen. There is no "Wassla welcome" screen any more. The three-chapter story is "How Wassla works", opened from Home; its last button starts the account screen.
- A visitor (a guest) can see: Home with trip and request listings and people (the same cards a member sees), Browse trips, Browse requests, Browse people, a person's page, public reviews, the place picker, How Wassla works, Language and Appearance, and Contact support (contact@wassla.eu). The Send and Carry switch works on Home.
- A visitor needs an account for: posting a request, posting a trip, "I can carry this", alerts, proposing, reporting a review, Deliveries, Chat, the notification bell, and everything about a deal, payouts or the ID check. Deliveries and Chat show an invitation to sign in and ask the server for nothing.
- The account moment: the first account-only action opens one full-screen account screen with the reason (for example "Create your account to send your parcel."), "Continue with Apple" (iPhone, when set up), "Continue with Google" (when set up), "Continue with email" and "I already have an account". When the person finishes, the screens close and the action they asked for goes on, on top of the screen they were on (filters and prefilled routes kept). Closing the screen cancels the action. A sign-up from it still goes through the email code. A person whose social sign-in left the name empty is then asked for a name once.
- A session that ends while on a private screen sends the person to sign-in ("Please sign in again"); on a public screen they stay as a guest and see "You were signed out. Sign in again." until they dismiss it or sign in.
- On the server, the six guest reads (listings of trips and requests, People, one person, a person's reviews, a trip's reviews) and the place and city lookups the app uses while browsing accept requests without a token. Matches, interest, own profile and alerts answer 401 without one. A guest is limited per network address on its own roomy scope, `discovery_guest`, 300 per minute (`DRF_DISCOVERY_GUEST_THROTTLE_RATE`), because Algerian mobile networks put hundreds of people behind one address; a signed-in member keeps 60 per minute for discovery and is never counted on the guest scope. Guests see only the public cards: no exact locations, no tracking numbers, no recipient details.
<!-- src: mobile/lib/app/router.dart (isPublicLocation), features/auth/account_gate.dart, account_name_screen.dart, guest_states.dart; backend discovery/views.py, core/throttles.py -->

## What about people without an account (recipient and guest payer)?
- Browsing: a visitor without an account can look around the app (see "How does browsing without an account work?" above).
- Recipient: has no account. The sender records their name, email, optional phone and a delivery note (note up to 1,000 characters), only after funding and before pickup is confirmed. Errors: `pickup_already_confirmed`, `deal_not_funded` "Recipient details are collected once the delivery is funded.", only the sender may do it. Saving the recipient is what moves the deal from `funded` to `pickup_ready`. The traveler sees only the recipient's name and note, and only once the parcel is with them. Nobody else sees the recipient details. The recipient gets the delivery code by email in the language chosen (sender's language by default).
- Guest payer: someone with no account who pays a sender's order from a link (for example a relative in Algiers). The order owner creates the link in the app (one live link per order; making a new one cancels the old one; can be shown again to share; can be revoked). Optional private label such as "Dad".
- The link lasts 3 days by default (`payments.guest.link_ttl_seconds`, 259,200 s; allowed 10 minutes to 30 days). Settings > Business settings shows it read only ("Guest payment link lifetime"); it changes only through a full new settings version on the staff API.
- The guest sees only: amount in EUR, a generic description, expiry, and the payment methods that allow guests. Not sender, traveler, recipient, addresses, parcel, or deal. Chargily is not offered to guests. A guest email may be asked only so Wassla can send a receipt, failure or refund notice. A guest cannot see the result inside the app after paying; the sender sees it. Paying does not make them a party: no chat, no disputes, no deal access. Invalid links give `guest_link_invalid`. Guest payment limit 20 per minute.
<!-- src: backend/monolith/apps/deals/recipient.py, finance/models.py (GuestPaymentLink), finance/services.py, finance/policy.py, finance/views.py, mobile/lib/features/guest/guest_pay_screen.dart -->

## What does staff see in the audit log for these actions?
- IDs: `kyc.approved`, `kyc.rejected`, `kyc.evidence_viewed`. Tickets (flight and sea): `flight_proof.approved`, `flight_proof.rejected`, `flight_proof.evidence_viewed`. Ask for new upload is a rejection with outcome "resubmission_requested". Accounts: `account.banned`, `account.restored`. Payout identity: `payout_identity.assigned`, `payout_identity.attested`, `payout_identity.compared`, `payout_identity.revoked`.
<!-- src: backend/monolith/apps/admin_panel/services.py, staff_actions.py, console_views.py, finance/payout_profiles.py -->

## Not covered here
- A guaranteed review time for IDs or tickets: the code has none ("less than a day" is only app text).
- Live values of the server environment limits above (sign-in lifetimes, code lifetimes, upload limits): only the shipped defaults are known here.
- Nothing ever sets "phone verified".
