# What Ismail does himself: email, Google and Apple sign-in

Written 2026-11-19 for package EGS. The code is ready and everything is switched off. Nothing is
deployed. Do the steps in this order. Each step says where to click and which value goes where.

The last section is a table of every variable and file.

## Decide first: the app id

The app id is `eu.wassla.app` (Android application id and iOS bundle id). Google, Apple and Firebase
clients are tied to it, and the stores never let a published app change it. If you ever want a
different id, change it **before** step 4. Changing it later means creating new Google, Apple and
Firebase clients and rebuilding.

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
   - **Android**: package name `eu.wassla.app` and a SHA-1. One client per signing key: the
     **release** key, then the **Play App Signing** key (Play Console, Test and release, App
     integrity). Create it in the same Google Cloud project as Firebase: `waa-eefab`, project number
     `513341711450`. Commands to read each SHA-1: `docs/ANDROID_BUILD_RUNBOOK.md`. Nothing from this
     client goes into the app or the server; Google just needs to know the keys. Phone builds from
     GitHub that are `profile` or `debug` are signed with a key that changes on every run, so they
     never offer Google: to test it, build `release` (steps below).
   - **iOS**: bundle id `eu.wassla.app`. Its client id (`<prefix>.apps.googleusercontent.com`)
     goes in two places that must match:
     - app build: `--dart-define=GOOGLE_IOS_CLIENT_ID=<prefix>.apps.googleusercontent.com` (the iOS
       release workflow reads it from the repository variable `GOOGLE_IOS_CLIENT_ID`);
     - `mobile/ios/Flutter/SocialSignIn.xcconfig`: `GOOGLE_IOS_CLIENT_PREFIX = <prefix>` (the id without
       `.apps.googleusercontent.com`).
     The iOS build stops with a clear message if the two disagree.
4. Which ids go in the server list? **The Web id and the iOS id.** The server
   (`apps/accounts/google.py`) accepts a token only when its audience is in `GOOGLE_OAUTH_CLIENT_IDS`.
   On Android the token names the Web id. On iPhone, depending on the version of Google's library, the
   token can name the iOS id instead, so list both, separated by a comma. The Android client id is not
   needed there.
5. Steps to test Google sign-in on your Android phone, in order:
   1. Make the permanent release key on your own computer (so no password passes through a chat):
      `keytool -genkeypair -v -keystore wassla-release.jks -alias wassla -keyalg RSA -keysize 4096 -validity 10000`.
      Keep the `.jks` file and its password in a password manager plus one offline copy, never in the
      repository, a chat or an email.
   2. GitHub, Settings, Secrets and variables, Actions, **Secrets**: add `ANDROID_KEYSTORE_BASE64`
      (PowerShell: `[Convert]::ToBase64String([IO.File]::ReadAllBytes("wassla-release.jks")) | Set-Clipboard`,
      then paste), `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS` (`wassla`) and `ANDROID_KEY_PASSWORD`
      (the same password as the keystore's).
   3. Read the SHA-1: `keytool -list -v -keystore wassla-release.jks -alias wassla`.
   4. Create the **Android** OAuth client described above, with that SHA-1.
   5. OAuth consent screen: add your own Google account as a test user, or publish to Production.
   6. GitHub, Actions, Build Android, Run workflow: `build_type` **release**, `apk_architecture` arm64,
      `api_base_url` `https://wassla.eu`. Uninstall the old profile build first (different key).
      Later release builds install over it. A new client can take a few minutes; a configuration error
      at the account picker means the SHA-1 or the project is wrong.
6. Until `GOOGLE_OAUTH_CLIENT_IDS` is set the server answers `google_sign_in_unavailable`, and until the
   app is built with `GOOGLE_SERVER_CLIENT_ID` the button is hidden.

## 5. Apple Developer: Sign in with Apple (iPhone only)

1. developer.apple.com, Certificates, Identifiers & Profiles, Identifiers: open the App ID
   `eu.wassla.app`, tick **Sign In with Apple**, Save. Regenerate the provisioning profiles.
2. Server: `APPLE_SIGN_IN_CLIENT_IDS=eu.wassla.app` (the bundle id) in `stack.env`, **with the key
   that revokes Apple sign-in when a member deletes their account** (production refuses to start with
   the first and not the others). developer.apple.com, Keys: create a key, tick **Sign in with Apple**,
   configure it for the App ID `eu.wassla.app`, download the `.p8` file once. Then in `stack.env`:
   - `APPLE_TEAM_ID`: the 10-character team id (top right of the developer account);
   - `APPLE_SIGN_IN_KEY_ID`: the key's 10-character id;
   - `APPLE_SIGN_IN_PRIVATE_KEY`: the whole `.p8` content on one line, each line break written as `\n`.
3. App, **both together** (one without the other fails the iOS build on purpose):
   - build define `--dart-define=APPLE_SIGN_IN_ENABLED=true` (the iOS release workflow reads it from the
     repository variable `APPLE_SIGN_IN_ENABLED`);
   - `mobile/ios/Flutter/SocialSignIn.xcconfig`: `APPLE_SIGN_IN_CAPABILITY = YES`. The app is then signed
     with `Runner/RunnerAppleSignIn.entitlements` instead of `Runner/Runner.entitlements`; both carry push.
4. Android does not offer Apple (it would need a Services ID and a web callback page; not built).

## 6. App Store rules that follow

- **Guideline 4.8:** an iOS app that offers Google must offer Sign in with Apple as an equal option.
  Already built: both buttons are shown together on iPhone.
- **Guideline 5.1.1(v): account deletion inside the app.** Built: Profile, "Delete account". It waits
  until nothing is open (deliveries, disputes, payouts or refunds on their way, open requests, published
  trips), asks for the password, and for an Apple account asks Apple, then revokes the Apple token with
  the key from step 5.2 before deleting. In App Store Connect, the review notes can say: "Profile >
  Delete account".
- **Guideline 1.2: reporting and blocking in chat.** Built: press and hold a message to report it, the
  chat menu blocks, and staff decide reports in the console (Trust > Reported chat messages) within a day.
- **Google Play, Data safety, "Delete account" link:** `https://<your domain>/delete-account`. The page
  (`web/delete-account.html`, in English, French and Arabic) gives the steps in the app and the email
  route.

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
| Apple button and server | empty `APPLE_SIGN_IN_CLIENT_IDS`, no `APPLE_SIGN_IN_ENABLED` define, `APPLE_SIGN_IN_CAPABILITY = NO` | Step 5 |
| Guest browsing | always on (no switch); the marketplace's own listing switches still apply | n/a |

## 10. The iPhone app: App ID, push, signing and the App Store build

Android's release secrets (keystore and passwords) are in `docs/ANDROID_BUILD_RUNBOOK.md`. These are the
iPhone ones. Nothing here is deployed or uploaded until you run the workflow and tick the upload box.

1. **App ID.** developer.apple.com, Certificates, Identifiers & Profiles, Identifiers, **+**, App IDs,
   App, explicit bundle id `eu.wassla.app`. Tick **Push Notifications** (every build of the app is signed
   with push, so the App ID must have it) and, when you get to step 5, **Sign In with Apple**.
2. **Push key for Firebase.** Keys, **+**, tick **Apple Push Notifications service (APNs)**, Continue,
   Register, download the `.p8` (only once) and note its Key ID. In the Firebase console, add an **iOS
   app** with bundle id `eu.wassla.app`, then Project settings, Cloud Messaging, Apple app configuration,
   **APNs Authentication Key**: upload the `.p8` with its Key ID and your Team ID. Do not add
   `GoogleService-Info.plist` to the app: the build passes Firebase's values as defines.
3. **Firebase iOS app id.** Copy the iOS app's App ID (`1:…:ios:…`) into the repository variable
   `FIREBASE_IOS_APP_ID` (Settings, Secrets and variables, Actions, Variables). `FIREBASE_API_KEY`,
   `FIREBASE_PROJECT_ID` and `FIREBASE_MESSAGING_SENDER_ID` are the same variables Android uses. All four
   or none: with none, the build works and push stays off.
4. **Distribution certificate.** Certificates, **+**, **Apple Distribution**, upload a certificate
   signing request made in Keychain Access on a Mac (Certificate Assistant, Request a Certificate From a
   Certificate Authority, saved to disk). Download the certificate, double-click it, then in Keychain
   Access export it **with its private key** as a `.p12` with a strong password.
5. **Provisioning profile.** Profiles, **+**, Distribution, **App Store Connect**, App ID
   `eu.wassla.app`, the certificate from step 4. Download the `.mobileprovision`. Make a new profile
   whenever the App ID's capabilities change (for example when you turn on Sign in with Apple).
6. **The app record.** appstoreconnect.apple.com, Apps, **+**, New App, iOS, name Wassla, bundle id
   `eu.wassla.app`, a SKU of your choice.
7. **TestFlight upload key (optional).** App Store Connect, Users and Access, Integrations, App Store
   Connect API, Team Keys, **+**, access **App Manager**. Download the `.p8` (only once), note the Key ID
   and the Issuer ID shown above the list.
8. **GitHub secrets** (Settings, Secrets and variables, Actions, Secrets, New repository secret). On a
   Mac, `base64 -i <file> | pbcopy` copies a file as one base64 line.

   | Secret | Value |
   | --- | --- |
   | `IOS_DISTRIBUTION_CERTIFICATE_BASE64` | the `.p12` from step 4, base64 |
   | `IOS_DISTRIBUTION_CERTIFICATE_PASSWORD` | its password |
   | `IOS_PROVISIONING_PROFILE_BASE64` | the `.mobileprovision` from step 5, base64 |
   | `IOS_TEAM_ID` | the 10-character Team ID (developer.apple.com, Account, Membership details) |
   | `APP_STORE_CONNECT_API_KEY_ID` | the Key ID from step 7 (TestFlight upload only) |
   | `APP_STORE_CONNECT_API_ISSUER_ID` | the Issuer ID from step 7 (TestFlight upload only) |
   | `APP_STORE_CONNECT_API_KEY_BASE64` | the `.p8` from step 7, base64 (TestFlight upload only) |

   Never put these files or passwords in the repository, a variable, a chat or a ticket.
9. **Build.** GitHub, Actions, **Build iOS**, Run workflow. It runs only when you start it, never on a
   push or a pull request. Fill in `api_base_url` (the gateway origin, no path), a `build_number` higher
   than the last one you uploaded (App Store Connect refuses a repeated number; empty uses the pubspec's),
   and tick `upload_to_testflight` only if you want it sent to App Store Connect (it then needs the three
   API key secrets). The workflow refuses a profile that is not an App Store profile for `eu.wassla.app`
   with push, checks that the signed app carries production push, and keeps the IPA and its
   `SHA256SUMS.txt` as a workflow artifact for 30 days.
10. **Before the first submission**, in App Store Connect: App Privacy answers that match
    `mobile/ios/Runner/PrivacyInfo.xcprivacy` (no tracking; email, name, phone, user id, photos and
    videos, messages, other user content, payout details as payment info, purchase history and the
    push device id, all linked to the person and used only for the app's functions). Export compliance
    is answered by the app itself (it uses no encryption beyond Apple's HTTPS), so App Store Connect does
    not ask for each build.

## 11. Every variable and file

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
| `stack.env` | `GOOGLE_OAUTH_CLIENT_IDS` | the Web client id and the iOS client id, comma-separated | 4 |
| App build define | `GOOGLE_SERVER_CLIENT_ID` | the Web client id | 4 |
| GitHub repository variable | `GOOGLE_SERVER_CLIENT_ID` | the Web client id (Android release workflow) | 4 |
| App build define (iOS) | `GOOGLE_IOS_CLIENT_ID` | `<prefix>.apps.googleusercontent.com` | 4 |
| `mobile/ios/Flutter/SocialSignIn.xcconfig` | `GOOGLE_IOS_CLIENT_PREFIX` | `<prefix>` | 4 |
| Google Cloud | Android clients | `eu.wassla.app` + SHA-1 of debug, release, Play App Signing keys | 4 |
| `stack.env` | `APPLE_SIGN_IN_CLIENT_IDS` | `eu.wassla.app` | 5 |
| `stack.env` | `APPLE_TEAM_ID`, `APPLE_SIGN_IN_KEY_ID`, `APPLE_SIGN_IN_PRIVATE_KEY` | the team id, the Sign in with Apple key id and its `.p8` | 5 |
| App build define (iOS) | `APPLE_SIGN_IN_ENABLED` | `true` | 5 |
| `mobile/ios/Flutter/SocialSignIn.xcconfig` | `APPLE_SIGN_IN_CAPABILITY` | `YES` | 5 |
| GitHub repository variable | `GOOGLE_IOS_CLIENT_ID`, `APPLE_SIGN_IN_ENABLED` | as the iOS defines above (iOS release workflow) | 4, 5 |
| GitHub repository variable | `FIREBASE_IOS_APP_ID` | the Firebase iOS app id | 10 |
| GitHub secret | `IOS_DISTRIBUTION_CERTIFICATE_BASE64`, `IOS_DISTRIBUTION_CERTIFICATE_PASSWORD` | the Apple Distribution `.p12`, base64, and its password | 10 |
| GitHub secret | `IOS_PROVISIONING_PROFILE_BASE64` | the App Store profile for `eu.wassla.app`, base64 | 10 |
| GitHub secret | `IOS_TEAM_ID` | the Apple team id | 10 |
| GitHub secret | `APP_STORE_CONNECT_API_KEY_ID`, `APP_STORE_CONNECT_API_ISSUER_ID`, `APP_STORE_CONNECT_API_KEY_BASE64` | the App Store Connect API key (TestFlight upload only) | 10 |
| `stack.env` | `DRF_*_THROTTLE_RATE` | see section 7 | 7 |

Sources used for Sender's steps: Sender's help pages "How to set up SPF, DKIM and DMARC",
"Transactional sender identity and domain requirements" and "API access tokens", read 2026-11-19.
