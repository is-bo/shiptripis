# What Ismail does himself: email, Google and Apple sign-in

Written 2026-11-19 for package EGS. The code is ready and everything is switched off. Nothing is
deployed. Do the steps in this order. Each step says where to click and which value goes where.

The last section is a table of every variable and file.

## Decide first: the app id

The app id is still `com.shiptrip.shiptrip` (Android application id and iOS bundle id). Google and Apple
clients are tied to it. If you ever want a different id, change it **before** step 3. Changing it later
means creating new Google and Apple clients and rebuilding.

## 1. The contact@wassla.eu mailbox (do this before Sender)

Sender.net only **sends**. It never receives mail. Replies to our emails, and anyone writing to support,
arrive at contact@wassla.eu. So that address needs a real mailbox.

1. Pick any mail host (for example Namecheap Private Email, Google Workspace, Zoho, Proton).
2. Create the mailbox `contact@wassla.eu`.
3. Add the mail host's MX records at your DNS provider, exactly as the host gives them.
4. Send a test mail to the address from Gmail, and reply from it. Both must work.

Sender will email a link to an address on your domain to prove you own it (step 2), so the mailbox must
exist and work first.

## 2. Sender.net: account, domain, DNS, token

1. Create an account at sender.net and sign in.
2. **Account settings, Domains, Add domain.** Enter `wassla.eu`, click Next. Enter `contact@wassla.eu`,
   click **Verify ownership**. Open the email Sender sends to that mailbox and click its link.
3. Open the domain row. Sender shows the dialog "Authenticate your SPF, DKIM and DMARC records". It lists
   three DNS records. Create them at your DNS provider:

   | Purpose | Record type | Name (host) | Value |
   | --- | --- | --- | --- |
   | DKIM | CNAME | the selector Sender shows (currently `sender._domainkey`) | the target Sender shows |
   | SPF | TXT | `@` (the bare domain) | the SPF text Sender shows |
   | DMARC | TXT | `_dmarc` | the DMARC text Sender shows |

   Copy the values from **Sender's dashboard**, never from this document: Sender is the authority and may
   change them. Rules that cause most failures:
   - Type only the prefix in the Name field (`sender._domainkey`, not the full domain), unless your DNS
     provider asks for the full name.
   - A domain may have only **one** SPF record. If your mail host already gave you one, add Sender's
     `include:` part to it; do not create a second `v=spf1` record.
   - Keep the mail host's own DKIM records. They do not clash with Sender's.
   - DMARC must start with `v=DMARC1;`. Start with the policy Sender shows, and tighten it later once you
     see reports.
4. Click **Check SPF, DKIM and DMARC records** (or **Recheck DNS records**). Wait for three green ticks in
   the Authentication column. DNS can take minutes, sometimes up to 48 hours.
5. **Account settings, API access tokens, Create API token**, validity **Forever**. Copy the token once.
6. Put the token in the mounted secrets file `secrets/app.json` on the server, key
   `SENDER_NET_API_TOKEN`. **Never** in `stack.env`, in Git, in a chat or in a ticket. Both Django and the
   Go email service read the same value.
7. In `stack.env`, `EMAIL_PROVIDER=sender_net` (already the example's value) and
   `EMAIL_FROM_ADDR`, `EMAIL_SUPPORT_ADDR` = `contact@wassla.eu` (already set).

Details and the backlog procedure: `infra/vps/EMAIL.md`, `infra/vps/ENVIRONMENT.md`.

## 3. Turn email on (only when you are ready, with a deployment you approve)

Everything starts off. In `stack.env`, in this order:

1. `EMAIL_SENDING_DOMAIN_VERIFIED=true` (only after the three green ticks in step 2).
2. `EMAIL_ACTIVATION_NOT_BEFORE=` the moment you activate, as a UTC timestamp such as
   `2026-12-01T09:00:00Z`. Emails created before it are held for review, so old test rows are not sent.
3. Run the backlog audit (`infra/vps/vps email-audit`) as `EMAIL.md` describes.
4. `EMAIL_ACTIVATION_APPROVED=true`
5. `EMAIL_ENABLED=true` (the master switch, last).

Production refuses to start with `EMAIL_ENABLED=true` and a missing or too short token, an unverified
domain, or a missing cutoff, and names the setting it is unhappy with.

**First test send.** Create a test account with an address you own (Gmail, Outlook, Apple Mail) and sign
up. Check: the verification code arrives; From shows `Wassla <contact@wassla.eu>`; it is not in spam; in
the message source SPF, DKIM and DMARC say pass. Then try "forgot password". Replying must reach the
mailbox from step 1. Test in English, French and Arabic.

**What to watch.** Sender's dashboard logs (accepted, bounced, spam complaints); the console's email
health and `ops_snapshot` (overdue, failed, held rows); anything with `provider_permanent` (bad address)
or repeated `provider_transient` with 401 or 403 (token problem) or 429 (Sender's rate limit; lower
`EMAIL_RATE_LIMIT_PER_MINUTE` to match your Sender plan, default 60). "Dispatched" means Sender accepted
the message, not that it reached the inbox.

To turn email off in an emergency: `EMAIL_ENABLED=false`. Rows stay safe in the queue.

## 4. Google Cloud: Sign in with Google

1. console.cloud.google.com: create a project (for example "Wassla").
2. **APIs & Services, OAuth consent screen** (now under "Google Auth Platform"): app name Wassla, support
   email `contact@wassla.eu`, developer contact `contact@wassla.eu`, user type External. Scopes: only
   `email`, `profile`, `openid` (the defaults). Publish the app to **Production** when you launch;
   in Testing only listed test users can sign in.
3. **Credentials, Create credentials, OAuth client ID**, three times:
   - **Web application** (call it "Wassla server"). No redirect URIs needed. Its client id, ending in
     `.apps.googleusercontent.com`, is the important one:
     - server: `GOOGLE_OAUTH_CLIENT_IDS` in `stack.env`;
     - app build: `--dart-define=GOOGLE_SERVER_CLIENT_ID=<that id>` (iOS and local builds);
     - GitHub: repository variable `GOOGLE_SERVER_CLIENT_ID` (Settings, Secrets and variables, Actions,
       Variables). The Android release workflow reads it.
   - **Android**: package name `com.shiptrip.shiptrip` and a SHA-1. One client per signing key: the
     **debug** key, the **release** key, and the **Play App Signing** key (Play Console, Test and
     release, App integrity). Commands to read each SHA-1: `docs/ANDROID_BUILD_RUNBOOK.md`. Nothing from
     this client goes into the app or the server; Google just needs to know the keys.
   - **iOS**: bundle id `com.shiptrip.shiptrip`. Its client id (`<prefix>.apps.googleusercontent.com`)
     goes in two places that must match:
     - app build: `--dart-define=GOOGLE_IOS_CLIENT_ID=<prefix>.apps.googleusercontent.com`;
     - `mobile/ios/Flutter/SocialSignIn.xcconfig`: `GOOGLE_IOS_CLIENT_PREFIX = <prefix>` (the id without
       `.apps.googleusercontent.com`).
     The iOS build stops with a clear message if the two disagree.
4. Does the server list need the Android and iOS ids? **No.** The app passes the Web client id as the
   server client id on both platforms, so Google puts the Web id in the token and the server
   (`apps/accounts/google.py`) accepts only ids in `GOOGLE_OAUTH_CLIENT_IDS`. List the Web id. Adding the
   iOS id as well is harmless but not needed.
5. Until `GOOGLE_OAUTH_CLIENT_IDS` is set the server answers `google_sign_in_unavailable`, and until the
   app is built with `GOOGLE_SERVER_CLIENT_ID` the button is hidden.

## 5. Apple Developer: Sign in with Apple (iPhone only)

1. developer.apple.com, Certificates, Identifiers & Profiles, Identifiers: open the App ID
   `com.shiptrip.shiptrip`, tick **Sign In with Apple**, Save. Regenerate the provisioning profiles.
2. Server: `APPLE_SIGN_IN_CLIENT_IDS=com.shiptrip.shiptrip` (the bundle id) in `stack.env`.
3. App, **both together** (one without the other fails the iOS build on purpose):
   - build define `--dart-define=APPLE_SIGN_IN_ENABLED=true`;
   - `mobile/ios/Flutter/SocialSignIn.xcconfig`: `APPLE_SIGN_IN_ENTITLEMENTS = Runner/Runner.entitlements`.
4. Android does not offer Apple (it would need a Services ID and a web callback page; not built).

## 6. App Store rules that follow

- **Guideline 4.8:** an iOS app that offers Google must offer Sign in with Apple as an equal option.
  Already built: both buttons are shown together on iPhone.
- **Guideline 5.1.1(v): account deletion inside the app is required.** It is **not built yet**. Apple
  will reject an app that lets people create accounts without a way to delete them. For people who signed
  in with Apple, deletion must also **revoke the token with Apple's REST API**, which needs a Sign in
  with Apple private key (`.p8`, created under Keys in the Apple developer account) kept on the server.
  Ask for this package before the first App Store submission. Google Play has a similar rule
  (an in-app way to delete, plus a web link).

## 7. Rate limits you can tune, and why

Mobile carriers in Algeria put hundreds of people behind one public IP address (carrier-grade NAT), so a
tight per-IP limit would block honest people. Set in `stack.env`:

| Variable | Default | What it limits |
| --- | --- | --- |
| `DRF_DISCOVERY_GUEST_THROTTLE_RATE` | `300/min` | People browsing without an account, per IP |
| `DRF_MATCHING_DISCOVERY_THROTTLE_RATE` | `60/min` | Each signed-in member's discovery reads |
| `DRF_GOOGLE_SIGNIN_THROTTLE_RATE`, `DRF_APPLE_SIGNIN_THROTTLE_RATE` | `30/min` | Google and Apple sign-ins, per IP |
| `DRF_REGISTRATION_THROTTLE_RATE` | `30/hour` | Email sign-ups, per IP |
| `DRF_LOGIN_THROTTLE_RATE` | `10/min` | Password sign-ins, per IP |

Login stays at 10 a minute per IP on purpose: there is no per-account lockout, so this limit is the only
thing slowing password guessing. If real users behind one IP complain, prefer adding a per-account
lockout over raising it. Raise the others freely if you see 429 answers from honest traffic.

## 8. Known risks, in plain words

- **Linking by verified email.** If someone has a Wassla account with `a@x.com`, and a *new* Google
  identity with the same verified address signs in, it joins that account. This is accepted: Google
  proves the address belongs to them. An email account that never confirmed its address is taken over by
  the provider's proof (its old password stops working).
- **A nameless social account** (Apple's "hide my name", or Google with no name) is asked for a name once,
  on "What should we call you?". It can be skipped for now and is asked again on the next launch. A name
  can be set once and not changed.
- **Apple's "Hide My Email"** gives a relay address, so it never matches an existing account.
- **Email delivery** can in rare crashes send one message twice (neither Sender nor SMTP has an
  idempotency key).

## 9. What stays off until you decide

Nothing is deployed and nothing contacted Sender, Google or Apple.

| Switch | Off by | Turned on by |
| --- | --- | --- |
| Email | `EMAIL_ENABLED=false`, `EMAIL_ACTIVATION_APPROVED=false`, `EMAIL_SENDING_DOMAIN_VERIFIED=false` | Step 3 |
| Google button and server | empty `GOOGLE_OAUTH_CLIENT_IDS` and no `GOOGLE_SERVER_CLIENT_ID` define | Step 4 |
| Apple button and server | empty `APPLE_SIGN_IN_CLIENT_IDS`, no `APPLE_SIGN_IN_ENABLED` define, empty entitlements | Step 5 |
| Guest browsing | always on (no switch); the marketplace's own listing switches still apply | n/a |

## 10. Every variable and file

| Where | Name | Value | Step |
| --- | --- | --- | --- |
| `secrets/app.json` (server, mounted) | `SENDER_NET_API_TOKEN` | the Sender API token | 2 |
| `stack.env` | `EMAIL_PROVIDER` | `sender_net` | 2 |
| `stack.env` | `EMAIL_FROM_ADDR`, `EMAIL_SUPPORT_ADDR` | `contact@wassla.eu` | 2 |
| `stack.env` | `EMAIL_SENDING_DOMAIN_VERIFIED` | `true` after three green ticks | 3 |
| `stack.env` | `EMAIL_ACTIVATION_NOT_BEFORE` | UTC timestamp of activation | 3 |
| `stack.env` | `EMAIL_ACTIVATION_APPROVED` | `true` at activation | 3 |
| `stack.env` | `EMAIL_ENABLED` | `true` last | 3 |
| `stack.env` | `EMAIL_RATE_LIMIT_PER_MINUTE` | match the Sender plan (default 60) | 3 |
| `stack.env` | `GOOGLE_OAUTH_CLIENT_IDS` | the Web client id | 4 |
| App build define | `GOOGLE_SERVER_CLIENT_ID` | the Web client id | 4 |
| GitHub repository variable | `GOOGLE_SERVER_CLIENT_ID` | the Web client id (Android release workflow) | 4 |
| App build define (iOS) | `GOOGLE_IOS_CLIENT_ID` | `<prefix>.apps.googleusercontent.com` | 4 |
| `mobile/ios/Flutter/SocialSignIn.xcconfig` | `GOOGLE_IOS_CLIENT_PREFIX` | `<prefix>` | 4 |
| Google Cloud | Android clients | `com.shiptrip.shiptrip` + SHA-1 of debug, release, Play App Signing keys | 4 |
| `stack.env` | `APPLE_SIGN_IN_CLIENT_IDS` | `com.shiptrip.shiptrip` | 5 |
| App build define (iOS) | `APPLE_SIGN_IN_ENABLED` | `true` | 5 |
| `mobile/ios/Flutter/SocialSignIn.xcconfig` | `APPLE_SIGN_IN_ENTITLEMENTS` | `Runner/Runner.entitlements` | 5 |
| `stack.env` | `DRF_*_THROTTLE_RATE` | see section 7 | 7 |

Sources used for Sender's steps: Sender's help pages "How to set up SPF, DKIM and DMARC",
"Transactional sender identity and domain requirements" and "API access tokens", read 2026-11-19.
