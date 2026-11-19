# EGS: Sender.net email, guest browsing, Sign in with Google and Apple (2026-11-19)

Ismail's request of 2026-11-18, plan `docs/WASSLA_EMAIL_GUEST_SOCIAL_PLAN.md` (decisions in its section 1,
"Changes after review" at its end). Nothing is deployed and no provider was contacted; every switch ships
off. What Ismail must do himself is in `docs/WASSLA_SETUP_FOR_ISMAIL.md`.

## What was built

| Part | What | Where |
| --- | --- | --- |
| A | Sender.net REST transport on both email paths (Django secret-bearing mail, Go stream mail); `EMAIL_PROVIDER=sender_net` is the API, `smtp` stays generic; one address contact@wassla.eu (From, Reply-To, support); `EMAIL_TIMEOUT_SECONDS` replaces `EMAIL_SMTP_TIMEOUT_SECONDS`; `provider_permanent` and `provider_transient` replace the SMTP-named failure classes | `apps/notifications/sender_net.py`, `backend/services/internal/email/sender_net.go`, `config/settings/{base,prod}.py`, `pkg/config/config.go`, `infra/vps/` |
| B | One social sign-in rule (`apps/accounts/social.py`) for Google and Apple; Sign in with Apple (`apple.py`, `POST /api/auth/oauth/apple`); refusal of disabled accounts; six guest read endpoints | `apps/accounts/`, `apps/discovery/views.py`, `apps/locations/geography_views.py` |
| C | Guest mode: signed-out launch opens Home, public route list, the account moment (`ensureAccount`, `/auth/continue`), guest Deliveries, Chat and Profile, no private request while signed out, session-expiry notice | `mobile/lib/app/router.dart`, `core/session/session.dart`, `features/auth/account_gate.dart`, `guest_states.dart` |
| D | "Continue with Google / Apple" buttons, `SocialSignIn` interface with a fake, the name step, iOS and Android configuration | `core/auth/social_sign_in.dart`, `features/auth/social_sign_in_buttons.dart`, `account_name_screen.dart`, `ios/` |
| E | Copy review (EN, FR, AR), web support page, helper notes, these docs, Ismail's setup list | this part |

## Contracts

- `POST /api/auth/oauth/google` and `POST /api/auth/oauth/apple`: answer `{user, access, refresh}`. Apple
  takes `identity_token`, the raw `nonce`, optional `full_name`, `preferred_language`, `phone`, `wilaya`.
  Stable codes: `google_sign_in_unavailable`, `apple_sign_in_unavailable` (503, list empty or provider
  unreachable), `account_disabled` (403), `email_missing`, `email_not_verified` (400), `identity_invalid`.
  Limit 30 a minute per IP each.
- `PATCH /api/me` takes `full_name` (1 to 120) while it is empty; later `name_already_set` (400).
- Discovery: trips, requests, people, one person, a person's reviews, a trip's reviews, and the
  geography reads answer without a token; matches, interest, own profile and alerts stay 401. Guests are
  counted on `discovery_guest` (300 a minute per IP), members on `matching_discovery` (60 a minute).
- Sender API: `POST https://api.sender.net/v2/message/send`, bearer `SENDER_NET_API_TOKEN`. 400 and 422
  are permanent; 401, 403, 404, 408, 429, 5xx, timeouts and a 2xx without `success: true` are
  retryable.
- App routes: public list in `isPublicLocation`; `/how-it-works` replaces the deleted welcome screen;
  `/auth/continue?reason=<wire>` is the account screen; `continue=1` on the auth routes completes the
  flow and closes them in one step.

## Decisions

The sixteen decisions of plan section 1 stand, with the review changes listed at the end of the plan
(rates, set-once name, Apple without email, no single-use nonce, bearer withheld while signed out, 429
not retried, one `finishSignIn`). Judgment calls of this part:

- **One mailbox page.** `web/support.html` now shows one card, contact@wassla.eu, and asks for the
  topic in the subject line; the four placeholder `*.shiptrip.example` mailboxes and the "placeholders"
  notice are gone. `web/robots.txt` and `web/sitemap.xml` still name the placeholder host
  `shiptrip.example` (a domain, not a mailbox; it waits for the production domain).
- **French without gender.** "Vous avez été déconnecté" became "Votre session est fermée"; "en tant
  qu'invité" became "sans compte".
- **Payout wording.** Account-screen reasons say the payment is held and paid 48 hours after delivery.
- **Google server list.** Both platforms pass the Web client id as server client id, so tokens name it as
  audience; `GOOGLE_OAUTH_CLIENT_IDS` needs only the Web client id (the iOS id may be listed, harmlessly).
- **Server texts.** Google's unavailable text became "Sign in with Google is temporarily unavailable."
  to match Apple's. The other `detail` texts read well and were kept.

## Copy changes (Part E)

`accountReasonPostRequestBody`, `accountReasonCarryBody` (48 hours after delivery),
`guestWelcomeBody` (alerts and reports), `guestSignedOutNotice` and `guestProfileTitle` (French, no
gender), `socialAccountDisabled` (Arabic "موقوف"), `validationTooLong` ("at most {max}" in EN, "{max}
caractères au maximum", "{max} حرفًا على الأكثر"). Its three callers (form fields, the request notes,
the name step) read correctly with the new wording. The Arabic Apple and Google labels keep Apple's
and Google's official "المتابعة باستخدام ...". No test asserted the old text literally (they use the
generated getters).

## Tests, as they stand

| Suite | Count |
| --- | --- |
| Django, whole project | 3,567 collected; `apps/admin_helper` 160 passed in this part |
| Go (`backend/services`, `go test ./...`) | 348 passed including subtests; integration tests need services |
| `infra/vps/tests` | 32 test functions |
| Flutter | see the pull request for the final whole-suite count |

New or rewritten tests of the package are in `apps/notifications/tests/test_sender_net.py`,
`test_email_inventory_render.py`, `apps/accounts/tests/test_{apple_sign_in,social_sign_in,me_name,google_verifier}.py`,
`apps/discovery/tests/test_guest_access.py`, `apps/core/tests/test_throttles.py`,
`apps/locations/tests/test_guest_throttle.py`, `mobile/test/egs_guest_mode_test.dart`,
`egs_social_sign_in_test.dart`, `tools/check_ios_config.py` (CI).

## Screenshots

`/mnt/project-files/l-series-screens/EGS/` as `<screen>-<state>-<language>.png`, EN and AR at 360 px
(Part F), and one email of each family in EN, FR and AR.

## Known limits

- Account deletion inside the app is not built. The App Store requires it (5.1.1(v)); for Apple sign-in
  it also needs revoking the token with Apple's REST API using a `.p8` key.
- Apple on Android needs a Services ID and a server callback page: not built; Android offers Google only.
- Linking is by verified email: a new Google identity with the address of an existing account joins it.
  Accepted.
- A nameless social account is asked for a name once per app launch until it has one.
- When an Apple or Google sign-in claims an unconfirmed account and gives no name, an access token issued
  to the earlier holder stays valid for up to its 5-minute lifetime and could set the name once. Accepted:
  it needs a stranger who signed up with the victim's address inside that window; staff can correct a
  name in the Django admin.
- A `PATCH /api/me` that sends a name and a language together is refused whole once a name is set; the
  app sends them separately.
- The bundle and application id is still `com.shiptrip.shiptrip`; Google and Apple clients are tied to it.
- Everything stays off until Ismail sets the keys and switches; no email has ever been sent.
