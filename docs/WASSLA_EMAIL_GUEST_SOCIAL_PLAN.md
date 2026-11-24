# Plan: Sender.net email, guest browsing, Sign in with Google and Apple

Package id **EGS**. Written on 2026-11-18 for Ismail's request of the same day:

> I want to setup emails we will be using sender.net so we need the code to be ready everything that
> requires an email should work the email for support and for sending will be contact@wassla.eu make
> it ready so later I will set everything with the api key and stuff. Also another thing is I want the
> user when entering the app to be faced with the normal home screen and can look around but to post a
> request or a flight he needs to make an account. Also I want to add sign in with google and apple if
> you can get the code ready for that and tell me what else I need to do.

And, a few minutes later: make sure nothing breaks, take every step to avoid mistakes, aim for a
perfect implementation.

Nothing here is deployed and no provider is contacted. Every switch ships off; the code is ready for
Ismail's keys.

---

## 0. What exists today (read before building)

**Email.** Already built and hardened (V2, K-series): `OutboundMessage` rows in PostgreSQL are the
obligation; `apps/notifications/outbox.py` renders every kind in EN/FR/AR (text and HTML from one
`EmailDocument`, `email_layout.py`). Two transports:

- ordinary messages are XADDed to the `email:send` Redis stream and sent by the Go email service
  (`backend/services/internal/email`, `cmd/email`), which writes delivery receipts;
- secret-bearing messages (email verification, password reset, staff invitation, recipient delivery
  code) never enter Redis: Django sends them itself in `_send_email_via_provider` through Django's
  email backend.

Both paths speak SMTP only. `EMAIL_PROVIDER=sender_net` today means "SMTP to smtp.sender.net:587".
A shared PostgreSQL send gate (`delivery_policy.py`) bounds the rate. `EMAIL_ENABLED` is the kill
switch, `EMAIL_ACTIVATION_NOT_BEFORE` and the backlog review hold old rows. Production validation is in
`config/settings/prod.py` (Django) and `pkg/config/config.go` `LoadEmail` (Go). Infra: `infra/vps/`
(`runtime.py` secrets allowlist, `stack.env.example`, `app-secrets.example.json`, `EMAIL.md`,
`ENVIRONMENT.md`, `tests/test_email.py`).

**Google sign-in.** Backend done: `apps/accounts/google.py` (ID-token verification, bounded timeout),
`GoogleSignInView` at `POST /api/auth/oauth/google`, `OAuthIdentity` (provider `google` and `apple`
already in the model), L18A's claim of an unconfirmed account. Mobile has `signInWithGoogle` in
`data/auth_repository.dart` and `core/session/session.dart`, but **no package, no button, no native
configuration**. Known gap: the view issues tokens to a disabled (banned) account.

**Apple sign-in.** Nothing beyond the model's `apple` choice.

**Signed-out app.** The router sends a signed-out person to `/onboarding` (welcome screen, then the
three-chapter `BenefitsScreen`, then sign-up). Every discovery endpoint (`/api/discovery/*`) requires
an account. Home renders a skeleton when there is no account.

---

## 1. Decisions (judgment calls, recorded for Ismail's review)

1. **Sender.net through its REST API** (`POST https://api.sender.net/v2/message/send`, `Authorization:
   Bearer <API token>`), which Sender recommends and which is what "the api key" means. Provider
   `sender_net` now means the API. Provider `smtp` stays as the generic transport (MailHog in
   development, or any SMTP relay, including Sender's own SMTP relay if Ismail ever prefers SMTP
   users). The Sender-specific SMTP checks (`smtp.sender.net:587`) are removed: they are replaced.
2. **One address, contact@wassla.eu**, is From, Reply-To and support. It is the default in
   `config/settings/base.py` and in the shipped example configuration, so the app's "Contact support"
   and every email footer show it. Display name `Wassla`.
3. **Reply-To** is omitted when it equals From (the shipped case). If Ismail ever sets a different
   `EMAIL_REPLY_TO`, it travels as a `Reply-To` entry in the API's documented `headers` object.
4. **The API token is a secret**: `SENDER_NET_API_TOKEN`, only in the mounted `secrets/app.json`,
   never in `stack.env`, images, logs or Git. Django and Go read the same value. Production refuses
   `EMAIL_ENABLED=true` with `sender_net` and no token.
5. **Failure classes for the API** mirror the SMTP rules: `400` and `422` (the message itself is
   invalid) are permanent; `401`, `403`, `404`, `408`, `429`, any `5xx`, a timeout or a network error
   are retryable within the existing bounded budget (configuration errors must not burn messages).
   A `2xx` whose JSON does not say `"success": true` is retryable. Nothing logs the body, subject,
   recipient or token.
6. **`EMAIL_SMTP_TIMEOUT_SECONDS` becomes `EMAIL_TIMEOUT_SECONDS`** (same 1..10 range) because it now
   bounds both transports. Renamed everywhere it is read or documented as current (not in dated
   history files).
7. **Guests see the normal Home.** First launch, and any launch without a session, opens Home. The
   welcome screen (`OnboardingScreen`) is removed, because guest Home replaces it as the front page.
   The three-chapter story (`BenefitsScreen`) stays as "How Wassla works", opened from guest Home; its
   last button starts the account flow.
8. **What a guest can do without an account:** Home with the trip and request listings and people
   (the same cards members see), Browse trips, Browse requests, Browse people, a person's page, public
   reviews, the place picker, How Wassla works, Language and Appearance, Contact support.
   **What needs an account:** posting a request, posting a trip, "I can carry this", alerts, proposing,
   reporting a review, Deliveries, Chat, notifications, everything about a deal, payouts, ID check.
9. **The account moment.** Any account-only action opens one account screen ("Create your account to
   send your parcel", with the reason) offering Continue with Apple (iOS), Continue with Google,
   Continue with email (sign-up) and "I already have an account" (sign-in). When the person finishes,
   the account screens close and the action they asked for continues, on top of exactly the screen
   they were on (browse filters, the trip they picked, the route prefill). Closing the account screen
   cancels the action and leaves them where they were.
10. **Guest listings are the member cards, unchanged.** The six read endpoints (trips, requests,
    people, one person, a person's reviews, a trip's reviews) accept anonymous requests and answer the
    same allowlisted payloads. Personalised endpoints (matches, interest, own profile, alerts) stay
    member-only. Anonymous reads, and the geography reads a guest uses while browsing, are throttled
    by IP on their own roomy `discovery_guest` scope (300 a minute by default) instead of the shared
    anonymous rate, because mobile carriers put hundreds of people behind one IPv4 address; a member
    keeps the per-member `matching_discovery` (60 a minute) and `user` rates and is never counted on
    the guest scope (backend review). The privacy tests run for anonymous requests too.
11. **Apple on iOS only.** Apple's rule (App Store 4.8) applies to the iOS app, which offers Google.
    Apple's Android flow needs a Services ID and a server callback page; it is not built. Android shows
    Google only.
12. **One rule for social sign-in** (`apps/accounts/social.py`), used by Google and Apple: find the
    identity by provider and subject; otherwise link to the account with that verified email (claiming
    an unconfirmed one exactly as L18A does) or create one; refuse a disabled or banned account, before
    any token is issued, with `403 {"code": "account_disabled", "detail": "This account is
    disabled."}`. That is not the answer password sign-in gives (a switched-off account there gets
    "Incorrect email or password.", because Django refuses an inactive account before the check);
    a provider has already proved who the person is, so saying the account is disabled reveals
    nothing new. That closes the Google gap of section 0. A token with no email signs in to an
    identity already linked; it cannot link or open an account (`email_missing`).
13. **No name from the provider means an empty name**, never the email's local part (the existing rule
    in `apps/matching/find_travelers.first_name`: "the local part of an email address is not a name").
    Apple gives the name only on the very first authorization; the app sends it with that request.
    A blank name can be set once (backend review): by the member through `PATCH /api/me`
    (`full_name`, 1 to 120 characters; once set, `400 name_already_set`), or by a later Google or
    Apple sign-in that brings one. A set name is never overwritten.
14. **Apple nonce.** The app makes a random nonce, gives Apple its SHA-256, and sends the raw nonce to
    the server, which checks the token's `nonce` claim. The nonce binds the token to this sign-in
    request and the token's short expiry bounds replay; it is not single-use, so a retry with the same
    token after a failed first attempt (the only request that carries Apple's name) still works. The server accepts only RS256 tokens from
    `https://appleid.apple.com` whose `aud` is one of `APPLE_SIGN_IN_CLIENT_IDS` (the iOS bundle id).
15. **Buttons appear only when configured.** Google needs `GOOGLE_SERVER_CLIENT_ID` (and on iOS
    `GOOGLE_IOS_CLIENT_ID`) as build defines; Apple needs `APPLE_SIGN_IN_ENABLED=true` on an iOS build.
    A build without them shows email sign-up only. The server refuses each provider while its client
    id list is empty, with a stable code.
16. **App id unchanged**: `com.shiptrip.shiptrip` on Android and iOS (Firebase may already use it).
    Ismail's setup list says so and offers the change before he registers anything.

---

## 2. Work parts, models and effort

The rule of `CLAUDE.md` decides: the strongest model for anything that touches codes or security;
the lighter model for the rest; never low effort. Ismail asked for Opus and Sonnet agents with effort
chosen by difficulty.

| Part | What | Model, effort | Why |
| --- | --- | --- | --- |
| A | Sender.net API transport (Django and Go), settings, infra, contact@wassla.eu | Opus, high | Carries verification, reset and delivery codes; retries and idempotency |
| B | Sign in with Apple, one social sign-in rule, guest read API | Opus, xhigh | Token verification, account linking, a new public surface |
| C | Guest mode in the app: router, guest Home and tabs, the account moment | Opus, high | Session and routing logic every screen depends on |
| D | Google and Apple buttons in the app, native configuration | Opus, medium | Auth flow, but the server does every check |
| E | Copy review in EN/FR/AR, web support page, docs, helper notes, Ismail's setup list | Sonnet, medium | Writing and translation |
| F | Gate screenshots, EN and AR at 360 px | Sonnet, medium | Mechanical |
| R | Two independent reviews (backend; app) | Opus, high | Second pass on races, authorization, privacy, idempotency |

Order: A, B and C run in parallel (separate files). D starts after C is merged into the package branch
(both touch the auth screens and the ARB files). E, F and R run when A to D are in. The orchestrator
merges each part into the package branch, runs every check, and opens one pull request into `main`.

### Rules for every part

- Work only in your own git worktree and branch; commit there with clear messages; do not push and do
  not open a pull request. The orchestrator merges.
- Touch only the files your part names, plus their tests. If you must change a shared file not listed,
  say so in your report.
- Run every check of plan 1.4 that your part affects, **whole suites for the code you touched**
  (Django: the whole suite of every app you changed plus `apps/core`, `apps/notifications`,
  `apps/accounts`, `apps/discovery`; Go: everything; Flutter: everything). Report exact counts.
- Never skip, delete or weaken a test. A test that encoded a rule this plan changes is rewritten to the
  new rule, and your report names it and why.
- Remove what you replace. No commented-out code, no parameter for later.
- Every user-facing string in English, French and Arabic. Arabic uses Modern Standard Arabic with Western
  digits (0-9) and Algerian month names. Never the word "partner".
- Local services: PostgreSQL 16 on `localhost:5432` (user `shiptrip`, password `shiptrip-ci-pw`,
  superuser, so test databases are created for you) and Redis on `localhost:6379`. Load the
  environment with `source /tmp/claude-0/django-env.sh <your_db_name> <your_redis_db_number>`; it also
  puts Flutter 3.47.1 and Go on `PATH`. Use `python -m ruff` (0.8.4). Do not pass `-p no:logging`.
- Your final message is a report: what you built, files changed, decisions you made, tests added or
  rewritten, exact check results, anything you could not do.

---

## 3. Part A: Sender.net email (Opus, high)

**Goal.** With `EMAIL_PROVIDER=sender_net`, `EMAIL_ENABLED=true`, a verified domain and Ismail's API
token, every email the app writes is delivered through Sender.net's API from `Wassla
<contact@wassla.eu>`, on both transports, with the existing retry, rate, hold and kill-switch rules
unchanged. Nothing is sent while `EMAIL_ENABLED=false`.

**Django**

1. `apps/notifications/sender_net.py`: a Django email backend (`SenderNetEmailBackend`, subclass of
   `BaseEmailBackend`) that sends one `EmailMultiAlternatives` per request with `requests` (already a
   dependency): `from {email, name}` parsed from `DEFAULT_FROM_EMAIL`, `to {email}`, `subject`,
   `text` (the body), `html` (the alternative, when present), `headers` only for a `Reply-To` that
   differs from From. Bearer token from settings; `Accept` and `Content-Type: application/json`;
   timeout `EMAIL_TIMEOUT_SECONDS` for connect and read. Classify the answer per decision 5 into two
   exception types defined in that module, both log-safe (fixed text, no body, no address, no token):
   `SenderNetRejected` (permanent) and `SenderNetUnavailable` (retryable). `send_messages` returns the
   number accepted and raises on failure (`fail_silently=False` is the only mode used).
2. `outbox._dispatch_message_locked`: the permanent/transient classification recognises
   `SenderNetRejected` as permanent (`smtp_permanent` becomes a provider-neutral `provider_permanent`,
   `smtp_transient` becomes `provider_transient`; update every reader of those strings, including
   `backlog.py`, the console and tests). Everything else in the function is unchanged.
3. Settings: `EMAIL_BACKEND` follows the provider in `prod.py` (`sender_net` gives the new backend,
   `smtp` gives Django's SMTP backend). `SENDER_NET_API_TOKEN` read from the environment.
   `EMAIL_FROM_ADDR` and `EMAIL_SUPPORT_ADDR` default to `contact@wassla.eu`. `EMAIL_TIMEOUT_SECONDS`
   replaces `EMAIL_SMTP_TIMEOUT_SECONDS`. Production validation: `sender_net` and enabled needs the
   token (at least 20 characters), the From address and the verified-domain flag; `smtp` and enabled
   keeps today's host, TLS and credential checks. The Sender-specific SMTP host and port checks go.
4. The console's email-health view and `ops_snapshot` must not say "SMTP" where they mean the
   provider; read them and adjust wording only if they name SMTP as the only transport.

**Go**

5. `internal/email/sender_net.go`: `senderNetSender` implementing `EmailSender` with `net/http`
   (timeout from config, `MinVersion` TLS 1.2 via the default transport), the same JSON contract,
   the same classification (permanent = `*PermanentError` with the HTTP status in `Code`), log-safe
   `SendFailure` values (no recipient, subject, body or token in any error string or log). The endpoint
   URL is a constructor argument so tests use `httptest`; `cmd/email` passes the real constant.
6. `pkg/config/config.go` `LoadEmail`: provider `sender_net` requires the token and From address and
   no SMTP host; provider `smtp` keeps its rules. `cmd/email/main.go` picks the sender by provider.
   Metric names stay (`smtp_attempts_total` etc. are referenced by the runbook); if you rename them,
   update every reference.
7. Readiness (`/readyz`) keeps reporting configuration without dialing Sender.

**Infra and examples**

8. `infra/vps/runtime.py` allowlists `SENDER_NET_API_TOKEN`; `app-secrets.example.json` carries it
   empty. `stack.env.example`: `EMAIL_PROVIDER=sender_net`, `EMAIL_FROM_ADDR=contact@wassla.eu`,
   `EMAIL_SUPPORT_ADDR=contact@wassla.eu`, `EMAIL_REPLY_TO=` (falls back to support),
   `EMAIL_FROM_NAME=Wassla`, `EMAIL_TIMEOUT_SECONDS=10`, no SMTP host. `backend/.env.example` and
   `backend/docker-compose.yml` keep MailHog with provider `smtp`. `infra/vps/tests` updated.
9. `infra/vps/EMAIL.md` and `ENVIRONMENT.md`: rewrite the configuration parts for the API (what the
   token is, where it goes, the activation steps) and drop the V2-era "no REST dependency" line and
   the old brand spelling. Keep the backlog-review procedure, which is unchanged.

**Tests (new)**

- Django `apps/notifications/tests/test_sender_net.py`: request shape for a text+HTML message (mock
  `requests.post`), Reply-To header present only when different, token in the header and nowhere else,
  each status class (200 success, 200 without success, 400, 401, 422, 429, 500, timeout, connection
  error) maps to the right exception, nothing sensitive in `str(exc)` or in captured logs; an
  end-to-end dispatch of each secret-bearing kind through the backend marks the obligation dispatched
  and consumes the secret; a permanent rejection fails the row with `provider_permanent`, a transient
  one keeps it pending with backoff; `EMAIL_ENABLED=false` sends nothing.
- Django settings tests (`test_v2_configuration.py`) rewritten for the new provider rules.
- A render test that every `OutboundMessage.Kind` builds a document in `en`, `fr` and `ar` with no
  untranslated English in the French and Arabic subject and heading (use the `.po` catalogues), and
  that the footer shows contact@wassla.eu.
- Go: `sender_net_test.go` with `httptest` for the same classes; config tests for both providers.

**Done when**

- Every `OutboundMessage.Kind` renders in EN/FR/AR and is sent through Sender.net's API in a test with
  a mocked API, on the transport it uses today (Go stream or Django secret path).
- Provider `smtp` still works exactly as before (all existing SMTP tests green).
- Production settings refuse each incomplete `sender_net` configuration with a clear message.
- Whole Django suites of `notifications`, `accounts`, `core`, `admin_panel`, `finance`; all Go tests
  with `-race`; `infra/vps/tests`; ruff; all green.

---

## 4. Part B: Apple sign-in, one social rule, guest read API (Opus, xhigh)

**Social sign-in**

1. `apps/accounts/social.py`: `sign_in_with_identity(*, provider, subject, email, email_verified,
   name, data) -> User`. Order: identity by `(provider, subject)`; else (email required and verified)
   lock the account with that email (`select_for_update`), claim it if unconfirmed (move
   `_claim_unconfirmed_account` here unchanged), or create one (`is_email_verified=True`, unusable
   password, empty name when none is given); create the `OAuthIdentity`. A unique-constraint race on
   `OAuthIdentity` or `User.email` resolves to the row that won, never to a 500. Refuse an inactive
   account (banned or disabled) with `403 {"code": "account_disabled", "detail": "This account is
   disabled."}` before any token is issued, for a known identity and for a linked email alike.
   Google's view uses it (its behaviour otherwise unchanged; the email local-part name fallback is
   replaced by decision 13; rewrite any test that encoded it and say so).
2. `apps/accounts/apple.py`: `verify_identity_token(token, *, raw_nonce) -> dict`. PyJWT
   `PyJWKClient("https://appleid.apple.com/auth/keys")` with a bounded timeout (same budget as
   `google.py`) and key caching, one client per process; algorithm RS256 only; `iss` exactly
   `https://appleid.apple.com`; `aud` in `settings.APPLE_SIGN_IN_CLIENT_IDS`; `exp`, `iat` required,
   30 s leeway (G2); `nonce` equal to the SHA-256 hex of `raw_nonce` (constant-time compare);
   `email_verified` true (Apple sends `true` or `"true"`); `sub` required. Errors: `AppleAuthError`
   (401) and `AppleAuthUnavailable` (503), like Google's. Pin `PyJWT` explicitly in
   `requirements.txt` at a version within simplejwt's range.
3. `AppleSignInView` at `POST /api/auth/oauth/apple` (`AllowAny`, throttle scope `apple_signin` with
   `DRF_APPLE_SIGNIN_THROTTLE_RATE`, default like Google's). Body: `identity_token`, `nonce`, optional
   `full_name` (Apple's first-time name, max 120, stripped), `preferred_language`, optional `phone` and
   `wilaya` with Google's validation. Answer: the same `{user, access, refresh}` shape. An empty
   `APPLE_SIGN_IN_CLIENT_IDS` answers `503 {"code": "apple_sign_in_unavailable"}`; give Google the same
   stable code (`google_sign_in_unavailable`) when its list is empty. Add the new throttle variable to
   `.github/workflows/ci.yml` next to Google's.
4. Settings: `APPLE_SIGN_IN_CLIENT_IDS` (list, default empty); documented in `infra/vps/ENVIRONMENT.md`
   and `stack.env.example` next to `GOOGLE_OAUTH_CLIENT_IDS`.

**Guest read API**

5. `TripsView`, `RequestsView`, `PeopleView`, `PersonView`, `PersonReviewsView`, `TripReviewsView` in
   `apps/discovery/views.py` accept anonymous requests (`AllowAny`; JWT still authenticates a member
   who sends a token). For an anonymous viewer: no "exclude my own" filter; `people()` gets no viewer
   to exclude; reviews carry no "my report" state (do not run the subquery with a null id: branch
   explicitly); `trip_reviews_access` takes the public path only (an anonymous `request=` parameter
   answers as an unknown trip, never as a member's path). Keep `MatchesView`, `InterestView`,
   `OwnProfileView`, `AlertsView`, `AlertDetailView` member-only (split the base class so the rule is
   visible). Update the module docstring and `docs/PHASE_L2A_DISCOVERY_CONTRACT.md` ("every endpoint
   is authenticated" is no longer true).
6. Tests: the privacy test walks each of the six answers for an anonymous client too (same secrets and
   forbidden keys, plus `my_report`); anonymous answers equal a member's answer for a viewer who owns
   nothing; switches off answer the same disabled states anonymously; the member-only five answer 401
   anonymously; anonymous throttling uses the IP. Query-count tests for the anonymous path.

**Done when**

- Apple: a valid token (signed by a test RSA key served through a mocked JWKS) signs in, links by
  email, claims an unconfirmed account, creates an account with the given name or an empty one; wrong
  `aud`, `iss`, algorithm (`none`, HS256), expired, wrong nonce, unverified email, missing `sub` each
  refuse; JWKS unreachable answers 503; empty client list answers the stable code.
- Google and Apple both refuse a banned and an inactive account, for a known identity and by email.
- Concurrent first sign-ins for one subject create one identity and one account (a test with two
  threads or a forced IntegrityError path).
- The six guest endpoints pass their privacy tests anonymously; the five member endpoints still 401.
- Whole Django suites of `accounts`, `discovery`, `ratings`, `core`, `matching`; ruff; migrations
  check (no migration expected; if one is needed, run `task check-drift`).

---

## 5. Part C: guest mode in the app (Opus, high)

**Router and session** (`lib/app/router.dart`, `lib/core/session/session.dart`)

1. Public routes for a signed-out person: `/home` and the shell tabs (Deliveries, Chat and Profile show
   guest states, below), `/discover/*`, `/reviews/*`, `/location/pick`, `/how-it-works`,
   `/profile/language`, `/profile/appearance`, `/auth/*`, `/guest/pay/*`. One list, one function.
2. A signed-out person on any other route is sent to `/auth/sign-in?next=<that location>` (the
   existing `next` rule, which already returns them there after signing in).
3. Launch without a session opens `/home`. `OnboardingScreen` and its route are deleted; the
   `BenefitsScreen` moves to `/how-it-works` (public), and its last button opens the account moment
   instead of the sign-up screen. Remove every string, test and asset that only the welcome screen used.
4. A session that expires: on a private route, the person goes to sign-in with `next` and the existing
   "you were signed out" message; on a public route they stay, as a guest, and guest Home and guest
   Profile show a one-line notice "You were signed out. Sign in again." until they sign in or dismiss
   it (clear the flag in the session controller; no redirect loop).
5. Guest role: a guest may switch between Send and Carry on Home (kept in memory and in the token
   store's role key, so a new `both` account starts on the side they were browsing).

**The account moment** (`lib/features/auth/account_gate.dart`, new)

6. `Future<bool> ensureAccount(BuildContext context, AccountReason reason)`: returns true at once for
   a member; for a guest pushes the account screen `/auth/continue?reason=<wire>` and returns whether
   a session exists when that screen closes. `AccountReason`: `postRequest`, `postTrip`, `carry`,
   `alert`, `propose`, `report`, `deliveries`, `chat`, `notifications`, `generic`, each with its own
   headline and one-line reason in EN/FR/AR.
7. The account screen (`AccountGateScreen`, full-screen, close button) shows the headline and reason,
   then the provider buttons area (empty until part D; leave a single, documented widget slot that D
   fills, not a parameter for later), "Continue with email" (sign-up) and "I already have an
   account" (sign-in). Sign-in and sign-up opened from it carry `continue=1`.
8. Completion: an auth route with `continue=1` is never redirected when the session turns signed in;
   on success it closes every account-flow route (gate, sign-in, sign-up, forgot password,
   verify-email opened from them) in one step, by route name, so the caller's `await` resumes on the
   screen the person was on. Sign-up from the gate goes on to verify-email (as today); confirming or
   leaving it completes the flow. The switch between sign-in and sign-up inside the flow keeps
   `continue=1`. (go_router does not complete the future of a route replaced with `pushReplacement`;
   do not rely on it.)
9. Gating in one place: `AppNavigation.openRequestCreate` and `openJourneyCreate` call
   `ensureAccount` first (reasons `postRequest`, `postTrip`), so every call site is covered and the
   route prefill survives. Every other account-only action reachable by a guest calls `ensureAccount`
   with its reason before acting: "I can carry this" and the request preview, "Send with this
   traveler", alerts (Browse, person page, Profile), propose and Find Travelers entries, report a
   review, the notification bell, the Deliveries and Chat tabs' call to action. Inventory them by
   reading every screen a guest can reach; list them in the report.

**Guest screens**

10. Home for a guest: a top bar with the Wassla mark and a "Sign in" action (no bell); a short welcome
    card (headline, one line, "How Wassla works"); the Send/Carry switch; `ListingsSection` and
    `PeopleSection` for the chosen side; no Attention, In progress, My requests, My journeys,
    Matches or profile opt-in. The footer hero button ("Send a parcel" / "Post a trip") runs the
    account moment, then opens the form.
11. Deliveries and Chat for a guest: a designed empty state (icon, headline, one line, button "Sign in
    or create an account"), no request to the server. Profile for a guest: an account card (create /
    sign in), Language, Appearance, How Wassla works, Contact support (when the server gives an
    address).
12. No private request while signed out: every provider that reads private data returns its empty or
    signed-out value without a request when there is no session (audit `app_state.dart`,
    `discovery_state.dart`, the shell badges, push and live updates). Discovery previews read the
    public endpoints for a guest and re-read on sign-in (the cache identity includes "guest").
13. Loading, empty, error and offline states for every guest surface, in EN/FR/AR, accessible, at
    320 px, 1.6x text and right-to-left, never hidden behind the bottom navigation.

**Tests**

- A guard test: launch signed out lands on Home; each public route opens; each private route goes to
  sign-in with `next`; after sign-in `next` is honoured.
- A "no private request" test: a fake API that fails the test on any request outside the public list
  while the app is driven through every guest screen.
- The account moment: posting from Home, "Send with this traveler" from Browse (prefill kept),
  "I can carry this", an alert: guest taps, signs in (and separately signs up, verifies), and lands on
  the form or action on top of the screen they came from; closing the gate does nothing; Back after
  the form returns to the original screen.
- Session expiry on a public and on a private route.
- Rewrite, do not delete, tests that encoded "signed out goes to onboarding" (`k5_cold_start_test`,
  `safe_area_test`, `phase_j1_contract_test`, others the suite finds) and list them.

**Done when**

- Every line above holds in a test; the whole Flutter suite, format and analyze are green.

---

## 6. Part D: Google and Apple buttons in the app (Opus, medium)

1. Packages: `google_sign_in` (current major, 7.x API: `GoogleSignIn.instance.initialize(clientId,
   serverClientId)`, `authenticate()`), `sign_in_with_apple`, `crypto` (nonce hash). Exact versions
   that resolve with Flutter 3.47.1; record them.
2. `lib/core/auth/social_sign_in.dart`: one interface (`SocialSignIn`) with `google()` and `apple()`
   returning a credential or `null` when the person cancelled, and a typed failure otherwise; the real
   implementation and a fake for tests through a provider. Apple: random 32-byte nonce, SHA-256 to
   Apple, raw to the server; name parts joined for `full_name` when Apple gives them.
3. `AppConfig`: `googleServerClientId` (`GOOGLE_SERVER_CLIENT_ID`), `googleIosClientId`
   (`GOOGLE_IOS_CLIENT_ID`), `appleSignInEnabled` (`APPLE_SIGN_IN_ENABLED`). Buttons show only when
   configured for the platform (decision 15). Apple only on iOS.
4. Session: `signInWithApple` next to `signInWithGoogle`, same generation and snapshot rules;
   repository call to `/api/auth/oauth/apple`; the API client treats it as an auth endpoint (already
   covered by `/api/auth/oauth/`). The language sent is the app's current language, as sign-up does.
5. Buttons: "Continue with Apple" (Apple's style rules: black, or white in dark mode, Apple logo,
   same height as the other buttons) and "Continue with Google" (Google's rules: the four-colour "G"
   drawn with a `CustomPainter`, white or dark neutral fill, "Continue with Google") on the sign-in
   screen, the sign-up screen and the account screen's slot from part C. Busy state, cancel is silent,
   failures show the server's message or a translated generic one; `account_disabled` shows its own
   copy; the provider-unavailable codes show "Sign in with Google is not available right now".
6. Native configuration, ready for Ismail's values and inert without them (as built):
   - iOS: `ios/Flutter/SocialSignIn.xcconfig` (included by `Debug.xcconfig` and `Release.xcconfig`,
     empty values in Git) holds `GOOGLE_IOS_CLIENT_PREFIX`, the iOS client id without
     `.apps.googleusercontent.com`; it alone drives the `Info.plist` URL scheme
     (`com.googleusercontent.apps.<prefix>`). There is no `GIDClientID` in `Info.plist`, because the
     Dart client id (`GOOGLE_IOS_CLIENT_ID`) wins. `APPLE_SIGN_IN_ENTITLEMENTS` is empty by default and
     feeds `CODE_SIGN_ENTITLEMENTS`; Ismail sets it to `Runner/Runner.entitlements` (which carries
     `com.apple.developer.applesignin`) once the App ID has the capability. The Runner build phase
     `ios/scripts/check_social_sign_in.sh` fails a build whose defines and xcconfig disagree
     (`GOOGLE_IOS_CLIENT_ID` without the matching prefix, or `APPLE_SIGN_IN_ENABLED=true` without the
     entitlements). `tools/check_ios_config.py` parses the plist, entitlements and project in CI.
   - Android: nothing secret in the repository; `google_sign_in` on Android needs only the web
     (server) client id at runtime plus the app's SHA-1 registered by Ismail in Google Cloud.
     The debug, release and Play App Signing SHA-1 commands are in `docs/ANDROID_BUILD_RUNBOOK.md`.
     The Android release workflow reads the repository variable `GOOGLE_SERVER_CLIENT_ID`.
7. Tests: buttons hidden when unconfigured; shown per platform when configured; a successful Google
   and Apple sign-in through the fake signs in (and, from the account screen, completes the account
   moment); cancel does nothing; each failure shows its copy; the nonce sent to the server hashes to
   the one given to Apple.

8. **The name step (added in the build).** A social account can have no name (decision 13). The app
   asks once, on "What should we call you?" (`account_name_screen.dart`): as the last screen of the
   account moment right after such a sign-in, and otherwise on Home once per app launch while the name
   is empty. It can be closed; the action the person came for goes ahead. It calls `PATCH /api/me`
   (`full_name`); `name_already_set` counts as success.

**Done when**: the above in tests; whole Flutter suite, format, analyze green; iOS and Android
configuration files valid (`plutil -lint` is not available here: parse `Info.plist` and the
entitlements with Python's `plistlib` in a test or script).

---

## 7. Part E: copy, web, docs and Ismail's setup list (Sonnet, medium)

1. Read every new or changed string of parts A to D in EN, FR and AR; fix translation quality,
   tone (the app's existing voice), Modern Standard Arabic usage, and length at 320 px.
2. `web/support.html` (and any other web page with a placeholder mailbox): one address,
   contact@wassla.eu. `tools/check_static_web.py` passes.
3. Helper notes: update `backend/monolith/apps/admin_helper/skill/knowledge/` where email transport,
   sign-in methods or guest browsing are described (accounts-and-verification, messages-and-notices,
   app-walkthrough, architecture-and-diagrams, settings-and-helper as needed); regenerate with
   `python manage.py build_helper_instructions`; the helper tests pass.
4. `docs/PHASE_EGS_EMAIL_GUEST_SOCIAL.md` (what was built, contracts, decisions, test counts,
   screenshots), an entry at the top of `docs/IMPLEMENTATION_STATUS.md`, `HANDOFF.md` section 8
   (support address now set; what remains for Ismail), `ARCHITECTURE.md` lines on email transport.
5. `docs/WASSLA_SETUP_FOR_ISMAIL.md`: every step Ismail must do himself, in order, plain words, with
   where to click and which value goes in which variable: Sender.net (account, domain wassla.eu,
   DNS records SPF, DKIM, DMARC, the API token, where it goes, the activation switches, a first test);
   the contact@wassla.eu mailbox itself (Sender sends, it does not receive mail); Google Cloud (OAuth
   consent screen, Web, Android and iOS clients, SHA-1, the ids into `GOOGLE_OAUTH_CLIENT_IDS`,
   `GOOGLE_SERVER_CLIENT_ID`, `GOOGLE_IOS_CLIENT_ID`, the xcconfig); Apple Developer (App ID
   capability, `APPLE_SIGN_IN_CLIENT_IDS`, `APPLE_SIGN_IN_ENABLED`); the app id question; App Store
   rules that follow (account deletion in the app, which is not built); what stays off until he
   decides.

## 8. Part F: screenshots (Sonnet, medium)

EN and AR at 360 px for: guest Home (Send and Carry), guest Deliveries, guest Chat, guest Profile,
the account screen for two reasons, How Wassla works, sign-in and sign-up with the provider buttons
(configured), the signed-out notice, and one email of each family rendered as HTML (verification
code, delivery code, a status email) in EN, FR and AR. Saved to
`/mnt/project-files/l-series-screens/EGS/` as `<screen>-<state>-<language>.png`; the throwaway test
that makes them is not committed.

## 9. Part R: reviews (Opus, high)

Two independent reviewers, after A to D are merged into the package branch:

- **Backend**: token verification (algorithm confusion, audience, issuer, nonce, expiry, JWKS
  caching and timeouts), the social rule (races, claim, banned accounts, enumeration through error
  messages), the public endpoints (privacy, throttling, query counts, viewer-specific leaks), the
  Sender transport (secrets in logs or exceptions, retry classes, idempotency with the outbox, kill
  switch, both transports' parity).
- **App**: the guard (every route), the account moment (stack and futures, double taps, back and
  close, a session change mid-flow), no private request as guest, gating complete, the expired
  session, RTL and small screens.

Findings go back to the part's agent (or the orchestrator fixes them), then a second look confirms.

---

## Changes after review

What the two reviews (section 9) and the fixes that followed changed in the plan above:

- **Guest throttle.** Public discovery reads and the geography reads a guest uses are counted per IP on
  their own scope `discovery_guest`, 300 a minute (`DRF_DISCOVERY_GUEST_THROTTLE_RATE`), because many
  people share one mobile IPv4 address. A member keeps `matching_discovery` (60 a minute) and `user`,
  and is never counted on the guest scope.
- **Provider sign-in 30 a minute** per IP for Google and for Apple; **registration 30 an hour** per IP.
  **Login stays 10 a minute** per IP: password guessing has no other bound (no per-account lockout).
- **Set-once name:** `PATCH /api/me` sets `full_name` only while it is empty (`name_already_set`
  otherwise); a later Google or Apple sign-in that brings a name fills an empty one; a set name is
  never overwritten.
- **Apple token without an email** signs in to an identity already linked; it cannot link or open an
  account (`email_missing`).
- **No single-use Apple nonce.** The nonce binds the token to the request and the token's short life
  bounds replay; a retry with the same token must work because Apple's name travels only on the first
  request.
- **The bearer is withheld while signed out:** the app sends no `Authorization` header from a stale
  token, so a guest read never fails on an expired one.
- **A 429 is not retried** by the app's client.
- **One `finishSignIn`** ends every sign-in path (email, Google, Apple, sign-up), so the account moment
  completes the same way for all.
- **iOS configuration:** one `GOOGLE_IOS_CLIENT_PREFIX`, Apple entitlements off by default, and a build
  check (section 6, item 6).
- **Copy review (Part E):** payout wording says payout waits 48 hours after delivery; guest welcome
  names alerts and reports; French avoids gendered "connecté" and "invité"; `validationTooLong` reads
  "at most {max}".
- **Google sign-in audience:** both platforms pass the Web client id as the server client id, so the
  token's audience is the Web client id and the server list needs only that one
  (`GOOGLE_OAUTH_CLIENT_IDS`); the iOS and Android client ids stay in the app and in Google Cloud.

---

## 10. Gate for the pull request

- Every "Done when" line with its evidence; nothing outside this plan.
- Whole suites in CI: the four Django shards, migrations and lint, Go unit and integration,
  Flutter, production config and static web, Schema drift. All green before the merge.
- Review findings closed; screenshots saved.
- Never deployed. No key, token or provider call in the repository or the tests.
