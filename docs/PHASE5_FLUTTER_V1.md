# Phase 5 — Flutter V1 rebuild

Handoff for the mobile client. Written for whoever picks this up next, whether
that is a release engineer, a translator, or Codex fixing a backend contract
this client depends on.

The premise, restated because it explains every decision below: **the backend
is authoritative and Flutter renders.** The client holds no business rule that
the server also holds. Where the two would disagree, the client is wrong by
construction.

---

## 1. What was replaced, and why it was a rebuild

The pre-Phase-5 Flutter app spoke a contract the backend had retired. Audited
against the live URL configuration, it used **zero** V1 endpoints: it posted to
the legacy traveller-first `matches/apply`, priced in DZD, modelled trips as
airport pairs, and drove handover through the Match-scoped `apps.verification`
routes — the ones whose Redis publish put **delivery-code plaintext in front of
the traveller**. None of that is a migration; it is a different product.

So the client was rebuilt against the real contracts, extracted endpoint by
endpoint from `config/urls.py`, the serializers and the service layer rather
than from documentation.

`test/legacy_removal_test.dart` is what keeps the old surfaces from creeping
back: it fails the build if any retired path, DZD marketplace field,
ProductRequest reference, admin endpoint or provider credential appears in
`lib/`.

---

## 2. Architecture

```
lib/
  core/          money, api client, error model, session, formatting, env
  domain/        models — parsing only, no widgets, no business rules
  data/          repositories — one path, one body, one parse
  design/        tokens, typography, theme, layout, components
  features/      screens, grouped by area
  app/           router, shared read model, settings, app root
  l10n/          ARB catalogues + generated localisations
```

The dependency direction is one-way: `features → data → domain → core`, with
`design` a leaf that `features` draws from. `domain` does not import Flutter
widgets — that is why `TransportMode` lives there and its icon lives in
`design/components/status.dart`.

### Money is operator-free on purpose

`core/money/money.dart` defines no `+`, `-`, `*` or `/`. "The client never
computes an authoritative amount" is therefore a **compile error**, not a code
review note. Every total, fee, refund, deposit credit and conversion is a
server field, rendered.

`Money.editableString` exists for pre-filling an input the user will type over.
It is integer-only and respects the currency exponent, so a dinar (exponent 0)
renders as `40500` rather than `405.00`.

### The bottom-navigation fix is structural

The old build floated a pill over `extendBody: true`, so every screen guessed
how much space the bar stole and every guess was wrong on some other phone.
The replacement, in `design/layout/app_scaffold.dart`:

1. the bar is a real docked `bottomNavigationBar`, so the framework subtracts
   its height from the branch viewport;
2. `AppScaffold` pins its footer in a `Column` above the body, never stacked
   over it;
3. `resizeToAvoidBottomInset` stays on, so the whole column lifts above the
   keyboard;
4. `AppScrollPadding` reads the real inset via `NavigationInsetScope` instead
   of a literal.

**No screen contains a hand-tuned bottom padding.**
`test/no_bottom_overlap_test.dart` asserts the geometric property — last row
above the bar, footer above the bar, footer above the keyboard — across six
device profiles including a 320-wide Android, an iPhone home indicator,
Android gesture navigation, landscape and 1.6× text.

### State

Riverpod 3, no codegen. Every read-model provider in `app/app_state.dart` is
`autoDispose`: capacity, money and lifecycle state go stale the moment the app
is backgrounded. The shell's `IndexedStack` keeps the four tabs mounted, so
this costs no refetch on a tab switch.

`ResumeRefresher` invalidates the volatile read model when the app returns to
the foreground, and `refreshVolatileState(ref)` is called after every mutation
that can move a deal.

> **Riverpod 3 note:** `AsyncValue` exposes `.value` (nullable). `valueOrNull`
> does not exist in this version.

---

## 3. Navigation

Bottom bar: **Home · Deliveries · Chat · Profile**. Four, fixed, labelled in
every language.

**Notifications are not a tab.** They hang off the header bell
(`NotificationBell` in `features/shell/app_shell.dart`), as a full-screen route
above the shell. A fifth tab would cost every screen the same permanent space
to serve a rare trip.

Anything that is a *task* rather than a *place* — creating a request, paying,
entering a handover code, opening a dispute — is pushed on the root navigator
and covers the bar, so a stray tab tap cannot lose work in progress.

One redirect in `app/router.dart` guards everything. It answers three
questions: are we still restoring, is there a session, is this route public.
`/onboarding`, `/auth/*` and `/guest/pay/:token` are the public set.

**Offline at launch stays on the splash rather than bouncing to sign-in** —
being offline is not being signed out.

---

## 4. Roles

One account, one identity. `AccountRole` may be `sender`, `traveler`, `both` or
`admin`; `RoleContext` is the *view* the user has chosen. The server's role
wins, and only `both` defers to the stored preference.

Switching role reorders Home and re-points the primary action. It does not hide
anything: Deliveries shows everything the account is party to in one list,
because an account that both sends and carries has one set of deliveries in
flight and splitting them would mean checking two places to answer one
question.

---

## 5. API mapping

| Surface | Endpoint | Notes |
|---|---|---|
| Account | `GET /api/me` | **No `PATCH`** — there is no profile-edit endpoint |
| Auth | `/api/auth/*` | Rotating refresh; `sign-out` blacklists |
| Locations | `GET/POST /api/locations`, `GET /api/airports` | Response is a **mixed** array: own rows exact, shared airports coarse |
| Journeys | `/api/journeys*`, `.../legs/<id>/proof` | Owner sees `distance_meters`; a counterparty sees `distance_band` **in its place** |
| Requests | `POST /api/parcels/delivery/v1`, `GET /api/parcels[/<id>]` | Strict body — unknown fields rejected |
| Discovery | `GET /api/matches/compatible-journeys` / `-requests` | Sender gets a recommendation; **traveller never does** |
| Quote | `POST /api/matches/quote` | Sender only |
| Negotiation | `POST /api/matches/propose`, `/api/offers/<id>/{counter,accept,decline,withdraw}` | Sender proposes first |
| Deals | `GET /api/deals[/<id>]`, `/recipient`, `/cancellation`, `/cancel` | Detail is the **whole aggregate** in one call |
| Handover | `GET .../handover`, `GET .../{pickup,delivery}-code`, `POST .../{pickup,delivery}` | Reveal is **GET**, submit and rotate are **POST** |
| Payments | `/api/payments/providers`, `/orders[/<ref>][/checkout]`, `/guest/<token>` | **No `POST /api/deals/<id>/payment`** — that route is read-only |
| Deposits | `GET/POST /api/parcels/<id>/posting-deposit` | |
| Disputes | `/api/deals/<id>/disputes`, `/api/disputes/<id>[/evidence]` | |
| Ratings | `/api/deals/<id>/ratings`, `/api/users/me/ratings` | |
| Boosts | `/api/boosts/packages`, `/api/parcels/<id>/boosts` | |
| Notifications | `/api/notifications*` | Paginated, `page_size` up to 100 |
| Chat | `/api/chat/threads`, `/api/matches/<id>/chat/messages` | |
| KYC | `POST /kyc/submit` on the **Go service** | Different host, different error envelope |

### Response-shape traps this client handles

- **Bare arrays vs paginated envelopes.** Most V1 lists return a bare array
  capped at 100; `GET /api/deals`, `/api/notifications` and the chat messages
  endpoint return `{count, next, previous, results}`. `ApiClient.getList`
  unwraps both.
- **Four error envelope shapes**, normalised in `ApiException`: the structured
  `{code, detail, …extras}`, a DRF field dict, a bare `{detail}` with no code,
  and the Go service's `{error}`.
- **`TransportMode` is the one uppercase enum** — `"FLIGHT"`/`"DRIVE"` on a
  leg, but lowercase `"drive"` inside `covered_legs`. Parsed case-insensitively.
- **Every unknown enum value degrades to `unknown`** rather than throwing. One
  unrecognised deal status must cost the user that row, not the tab.

---

## 6. Payments

- **EUR is canonical.** Chargily's dinar figure is the rail's charge, at a rate
  the server froze for that attempt. `eur_dzd_rate` arrives pre-formatted and
  is rendered **verbatim** — never re-derived from `fx_rate_micros`.
- **DZD has exponent 0.** Treating it as two-decimal would inflate every
  converted amount by a hundred.
- **A redirect is not a payment.** `PaymentOrder` has no `processing` status —
  the server has none. "In flight" is a property of the newest attempt.
  `CheckoutSection` (`features/requests/checkout_section.dart`) launches the
  hosted checkout externally, then polls `GET /api/payments/orders/<ref>` until
  `status` settles or the attempt dies. `PaymentOrder.isSettling` is the flag.
- **Amounts are never sent on checkout.** The server rejects the whole request
  with `client_supplied_amount_rejected` if an amount, currency or rate appears
  in the body.
- **The deposit is credit.** `deposit_credit_eur_cents` renders through
  `MoneyLine.credit` as a labelled subtraction in the success tone, so it can
  never read as a second fee.
- **The `mock` rail is filtered out of every list the UI renders.**

---

## 7. Handover — the release-critical invariant

**The traveller can never obtain the delivery code.**

Client-side guarantees, each independently testable:

1. `HandoverRepository.revealDeliveryCode` has **exactly one call site** in the
   whole app, inside `_SenderCodePanel`, which is instantiated only from the
   sender branch of `DeliveryScreen` and only when the server has said
   `can_reveal_delivery_code`.
2. The traveller's branch contains no reveal path at all — only
   `CodeEntryField` and `submitDeliveryCode`.
3. `RevealedCode.toString()` returns `RevealedCode(delivery, redacted)`, so a
   code cannot reach a crash report or an interpolated log line.
4. Nothing writes a code to storage. `TokenStore` writes exactly four keys —
   access token, refresh token, role, locale — and `purgeLegacyArtifacts()`
   deletes the retired build's `handover.codes` on **every** launch.
5. There is no `print` or `debugPrint` anywhere in `lib/`.

`test/handover_isolation_test.dart` asserts all five, including the call-site
count, because this invariant is one careless `if` away from being broken and a
grep is the only thing that catches that reliably.

### The 30-minute buffer

The countdown targets `delivery_code_available_at`, a **server** instant. When
it reaches zero the client does not unlock anything — it re-asks the server.
A wrong device clock or a screen left open cannot manufacture access.

### The 48-hour protection window

`protection_ends_at` lives on the **Deal**, not on the handover payload. The
traveller's payout waits for it, and an active dispute freezes it — both
rendered from server fields, never claimed as immediate.

---

## 8. Privacy

- Exact locations stay hidden until the server releases them. `AppLocation`
  models the two shapes separately and `isExact` is the only question a screen
  asks. Funding is the boundary; the client never assumes it has passed.
- The recipient's email and phone are **sender-only at every stage**. The
  traveller receives an existence flag before pickup and a name after it.
  `RecipientView.toString()` redacts.
- The guest payment token is opaque, never parsed, never stored, never logged.
  `GuestPaymentLink.toString()` redacts.
- Dispute evidence URLs are signed and expire in about five minutes, so a fresh
  one is fetched at the moment of viewing and never cached.

---

## 9. Localisation and RTL

`lib/l10n/app_en.arb` is the template and the source of truth for copy — 930
keys. Every user-visible string is a key; the analyzer's
`untranslated-messages-file` makes a gap visible rather than silent.

Arabic swaps the **entire type stack** rather than falling back glyph by glyph,
which is why the theme is rebuilt per locale.

`LocaleFormats.intlTag` maps `ar → ar_DZ`: bare `ar` renders Arabic-Indic
numerals, and the Maghreb reads Latin digits.

RTL rules the components already encode: directional insets throughout, an
arrow that mirrors, and codes, amounts and phone numbers pinned to LTR inside a
`Directionality` so a numeric string never reorders.

---

## 10. Accessibility

- Every tap target clears 48 dp; asserted for the navigation bar and buttons.
- **Status is never colour alone** — `StatusPill` *requires* an icon, and the
  lifecycle timeline uses shape (tick, cross, filled ring, hollow dot) so it
  reads in greyscale.
- Live regions on countdowns, remaining attempts and error notices.
- Amounts carry a `semanticPrefix` so a screen reader says what the number is.
- Codes are announced digit by digit — "four seven two nine" is transcribable.
- Text scales to 1.6×, clamped in `app.dart`; above that a money breakdown
  stops fitting on a small phone at all.
- Reduce Motion is honoured through `AppMotion.respecting`; the skeleton sheen
  stops entirely rather than looping.

---

## 11. Backend findings

### BLOCKER — fixed during Phase 5

**Chat was unreachable for every V1 deal.** `chat_eligibility` only understood
the legacy `PaymentIntent` path, so a funded V1 Deal returned "payment
pending" forever. Fixed in `apps/matching/services.py` by branching on the V1
`Deal` and gating on `funded_at` (not `status == FUNDED`, which advances). Also
added `chat_history_visible`, so read access outlives send access, and killed
an N+1 in `ChatThreadsView`.

### MAJOR

1. **Handover, dispute and rating events publish no notifications.**
   `apps.handover`, `apps.disputes` and `apps.ratings` never call
   `redis_bus.publish_after_commit`, so a pickup confirmation, a dispute
   opening or a rating reveal produces **no inbox row and no push**. The user's
   only signal is opening the app and polling. Email covers some of it, but a
   traveller waiting to be told the delivery code is ready currently is not
   told. The client compensates by making Deliveries — not the bell — the place
   attention lives, and says so in the inbox's own doc comment.

2. **No status endpoint for a guest payer.** After the provider redirect an
   anonymous payer has no way to ask whether the payment succeeded; the quote
   endpoint stops resolving once the link is consumed. The screen sets
   expectations before the redirect instead of promising a confirmation it
   cannot deliver, but a lightweight anonymous status echo would close a real
   gap.

3. **KYC status is ambiguous and unpushed.** `kyc_status` collapses "never
   submitted" and "expired, resubmit" into `unverified`, and
   `kyc.status_changed` is declared but never published. The client's copy says
   what to do next rather than asserting which case it is.

### MINOR

4. **Sign-up requires an Algerian `wilaya` from every account**, including a
   sender in Paris who has none. Real friction on the first screen a new user
   sees. See the note in `features/auth/wilayas.dart`.
5. **`PATCH /api/me` does not exist**, so the profile is read-only in the app.
6. **Inconsistent error envelopes** in the older matching views: `MatchDetailView`,
   `MatchCancelView` and `OfferListView` return a bare `{detail}` with no
   machine `code` on some paths, while `v1_views.py` always sends one.
7. **`POST /api/deals/<pk>/cancel` answers 409 for a non-party**, where every
   other "not a party" case is 403; and retrying on an already-cancelled deal
   is not the idempotent 200 the view's own docstring promises.
8. **`Offer.terms_snapshot` never carries the recommendation**, even for the
   sender who proposed. The client captures it from the quote instead.
9. **Dispute evidence policy mismatch:** the container sniffer recognises
   `video/webm` and `video/x-matroska`, but the seeded allowed list does not
   include them, so they are refused before that check runs.
10. **No email-verification resend endpoint.** The screen says what the user can
    actually try instead of offering a button that would do nothing.

---

## 12. Verification

```
dart format lib test
flutter analyze --fatal-infos      # clean
flutter test
```

Suites:

| File | Covers |
|---|---|
| `no_bottom_overlap_test.dart` | The structural nav fix, 6 device profiles, keyboard, insets |
| `handover_isolation_test.dart` | Delivery-code isolation, redaction, storage, logging |
| `contract_test.dart` | Wire parsing: enums, swapped keys, envelopes, offer gating, chat 402 |
| `money_test.dart` | Operator-free `Money`, exact decimal parsing, DZD exponent, Latin digits |
| `legacy_removal_test.dart` | Retired surfaces, DZD fields, admin endpoints, provider credentials |
| `navigation_and_rtl_test.dart` | Four tabs, RTL mirroring, LTR codes, a11y floors |
| `localisation_test.dart` | All three catalogues resolve, placeholders survive, Arabic's six plural categories, no embedded bidi marks |

---

## 13. Deliberately not done

Out of Phase 5 scope, and **not** attempted:

- No production Stripe or Chargily credentials. No webhook registration. No
  live-provider verification. Both rails remain **CODE-CONTRACT VERIFIED**.
- No admin frontend, no landing site, no Sender.net activation, no store
  submission — that is Phase 6/7.
- The client never calls `/api/admin/**`; asserted by test.

## 14. Rendering review

There is no Android SDK, Chrome or desktop toolchain on this machine, so the
app was temporarily built for **web** and served against a live local Django
backend in order to look at it. That harness has since been removed; only the
fixes it produced remain.

What it confirmed, on screen at 375x812:

- the bundled variable fonts load and render (Fraunces display, DM Sans body);
- the dark theme resolves and the brand tokens are applied;
- the splash's delayed indicator and its offline escape hatch behave as
  designed;
- onboarding lays out correctly with its footer pinned above the safe area.

**It found four real defects that no test had caught:**

1. **BLOCKER — `restore()` was never called.** `SessionController.build()`
   returned `SessionRestoring` and nothing ever started the restore, so the app
   sat on the splash forever. The only caller was the splash's own retry
   button. Fixed by starting it in `build()`, which is also the right place:
   the router's guard reads session state before any screen mounts.
2. **A non-exhaustive switch over `DioExceptionType`** — `transformTimeout`,
   added in dio 5.11, was unhandled. `flutter analyze` did not flag it; the
   dart2js front end did. A stalled upload would have surfaced as an
   unexplained failure.
3. **An unbounded wait on secure storage.** A platform channel that never
   answers held the app on its splash indefinitely. Now bounded, and a store
   that cannot be read is treated as an empty one — a recoverable sign-in
   rather than a dead end. This is a real Android failure mode after a backup
   restore, not only a web artefact.
4. **Onboarding copy was top-stranded** in a tall viewport because
   `mainAxisAlignment` does nothing inside a scroll view. Now centred and
   still scrollable.

A fifth defect was found by review rather than rendering: full-surface empty
and error states were not scrollable, so pull-to-refresh died exactly when a
user needed it. Fixed in `AppEmptyState`.

**Still owed:** rendering on real Android and iOS hardware. Interaction through
the web harness proved unreliable (a device-pixel-ratio mismatch made hit
testing inaccurate), so the authenticated flows were verified by widget test
and code review, not by driving them on screen.

## 15. Known gaps

- **No rendering on real Android or iOS hardware.** See above.
- French and Arabic catalogues are newly translated and have not been reviewed
  by a native speaker. Parity, placeholder survival, Arabic plural categories
  and the absence of embedded bidi marks are all machine-verified.
- Paging is not yet wired for the endpoints that support it (`/api/deals`,
  `/api/notifications`, chat history): the first page is fetched and the
  `next` cursor is parsed but unused. Fine at current volumes, needed before
  a user accumulates 20+ deliveries.
