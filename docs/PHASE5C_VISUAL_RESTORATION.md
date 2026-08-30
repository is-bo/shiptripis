# Phase 5C — Restoring the original ShipTrip visual identity

Status: **IMPLEMENTED / HARDWARE QA PENDING**

Phase 5 rebuilt the Flutter client against the real V1 contract and got the
engineering right. It got the *design* wrong: it replaced ShipTrip's visual
identity with a competent but generic one. Phase 5C puts the identity back
without giving up any of the engineering.

The rule throughout: **original visual identity + new V1 engineering**. Style
was restored; product behaviour was not.

## 1. The reference

`76ce129` — the last commit before the Phase 5 rebuild, extracted whole and
read rather than recalled. Its design language:

- **"Mediterranean transit"** — parchment ground, Algerian emerald, Saharan
  terracotta, gold, and a signature sun yellow.
- **Fraunces / DM Sans / JetBrains Mono**, with an eyebrow role (11pt, caps,
  1.6 tracking) used above every display headline.
- **Travel-paperwork decoration** — passport stamps with dashed borders set a
  few hundredths of a radian off true, boarding passes with notched sides,
  perforated postage stamps, wax seals, airmail borders.
- **Hand-painted illustration.** Not one raster asset existed; every mark was
  a `CustomPainter`.
- **`flutter_animate` entrance choreography** — staggered fade-and-rise on
  every screen, plus a looping 3.2 s flight-path tracer.

Two things the brief asked for that the original did not have, and which have
therefore **not** been invented:

- **Gradients.** There is no `LinearGradient`, `RadialGradient` or
  `SweepGradient` anywhere in `76ce129`. The depth comes from parchment
  layering, paper grain, hairlines, dashed borders and hard stamped shadows.
- **Image/SVG assets.** There are none. Every illustration is code.

## 2. What was restored

### Tokens (`design/tokens.dart`)

The Phase 5 token architecture was kept and its *values* re-pointed at the
original:

| Token | Was (Phase 5) | Now |
|---|---|---|
| `canvas` | `#F8F5EF` near-white sand | `#F4EFE6` parchment |
| `surface` | pure white | `#FAF6EE` parchment soft |
| `surfaceSunken` | `#F1ECE2` | `#EAE3D2` parchment deep |
| `textPrimary` | `#0B1A24` | `#0E1F2C` — the original ink |
| `textSecondary` | `#2B4353` | `#2A3B49` — the original ink soft |
| `attention` | `#C75E26` | unchanged — the original's *print* terracotta |
| `attentionVivid` | *absent* | `#E8763A` — the original's *fill* terracotta |
| `accent` / `accentStrong` | *absent* | `#FBBC04` / `#D89E00` — the sun |
| `seal` | *absent* | `#C9A961` gold |
| `grain` | *absent* | the paper speckle |

Ink was the single most consequential miss: it is the most-used colour in the
app, and a colder near-black shifted the temperature of every screen at once.

One value is deliberately **not** identical. The original's tertiary grey
`#6B7785` is 4.0:1 on parchment, which fails WCAG AA for small text — and
tertiary is exactly where eyebrows and captions live. `#616C79` is the
nearest step in the same family that clears 4.5:1.

Terracotta is split the way the original used it: `attentionVivid` `#E8763A`
fills wax seals, halos, airmail stripes; `attention` `#C75E26` prints words.
`#E8763A` is 2.6:1 on parchment and is never used for text.

### Theme (`design/theme.dart`)

- Primary buttons are **ink pills**, not emerald rounded rectangles. This is
  what lets the sun mean "this one, above all" on the two screens that use it.
- Ghost buttons are the same pill with a hairline.
- Fields sit **on** the paper as a lighter card with a hairline, rather than
  in a sunken grey trough; focus is an ink rule.
- Icon buttons are circles. Cards carry a hairline, because paper has an edge.

### The identity kit (`design/identity.dart`, new)

Ported from the original and tokenised: `PaperGrain`, `StampChip`, `WaxSeal`,
`PostageStamp`, `BoardingCard` (+ `DashedDivider`), `CountryPill`,
`ShipTripMark`, `PassportDots`, `PaperBackButton`, `RouteTrace`, and the
`Entrance` / `staggered` choreography helpers.

Three rules every widget in it obeys: tokens rather than hex, so it survives
dark mode; reduced motion honoured with a complete static frame; and marks are
`ExcludeSemantics` unless they carry a word a screen reader needs.

### Screens

- **Splash** — the original had none (it bootstrapped straight into the
  welcome page), so this is written *in* the original's language rather than
  recovered from it: parchment, grain, wordmark, route tracer.
- **Welcome** — restored: wordmark, "EST. 2026 · ALG ↔ FR" stamp, animated
  flight path, the two corridor cities with flag pills, eyebrow, serif
  headline, sun "Get started" + ghost "Sign in", trust line.
- **Benefits carousel** — restored as a new route (`/onboarding/benefits`):
  three chapters, each a hand-painted hero on an airmail-bordered card with a
  perforated postage stamp tacked to the corner. Chapter I flies a parcel
  across a postcard; II is a boarding pass with coins dropping; III lands a
  six-character handover code tile by tile under a certification flourish.
- **Sign in / sign up / forgot / verify** — the app bar is gone in favour of
  the original masthead: circular paper back button, passport stamp, two-line
  serif headline, one plain sentence (`features/auth/auth_header.dart`).

### Authenticated screens

Styled in the original's language rather than resurrected from it:

- Delivery and journey cards are **boarding passes** — notched sides landing
  on a dashed perforation that separates the journey from the agreement.
- Section headings are set in the display serif, as the original set them.
- Handover codes render as **split-flap tiles** with a hard stamped shadow.
- The navigation bar marks the current destination with a **sun lozenge**.
- Home's marquee action takes the sun; the role switch is a paper pill toggle.
- Paper grain is drawn by `AppScaffold`, so every screen inherits the ground.

## 3. Copy adaptations

The original carousel was an EN headline over a FR subtitle — charming, and
untenable in a trilingual product. The *composition* is preserved exactly
(eyebrow / serif headline / terracotta italic accent / two-weight body); the
accent line is now localised per catalogue, and English keeps the original
French lines verbatim.

`DZD` in the original's stamps and coin stack became `EUR` (V1 is
EUR-canonical), and the "four-digit pickup code" hero became six alphanumeric
characters, which is what `handover/codes.py` actually issues.

## 4. Obsolete logic NOT restored

Kaba/ProductRequest, DZD marketplace economics, airport-only trips,
traveller-first matching, legacy payment and handover endpoints, and the
legacy wallet surface all remain absent. `legacy_removal_test.dart` still
passes and still guards them. No `/api/admin/**` route is called.

## 5. Findings

### Fixed this phase

1. **MAJOR — the app defaulted to dark mode.** `ThemeMode.system` meant every
   user with dark mode switched on opened a dark navy app that looks nothing
   like ShipTrip, without ever choosing it. The original shipped no dark
   theme at all. Default is now `ThemeMode.light`; dark remains complete and
   selectable in Profile → Appearance.
2. **MAJOR — palette drift.** Ink and terracotta were the Phase 5 re-tuned
   ramps rather than the original values. Re-anchored (§2).
3. **MINOR — stamp overflowed by 17 px at 320 pt.** The welcome header's
   passport stamp ran off the right edge on a small Android phone. It now
   scales to fit rather than clipping.
4. **MINOR — the postage stamp covered the postcard's address block** in
   chapter I. Moved clear.
5. **MINOR — "Create an account" wrapped to two lines** in the welcome row
   beside "Sign in". Uses the original's shorter "Get started".

### Phase 7A mobile compatibility

Phase 7A did not change any user-facing response shape the client consumes.
Two bounded client-side adjustments were made, both mobile-only:

1. **`Retry-After` is now read.** Production throttles are Redis-backed and
   shared across instances, so a 429 is a genuinely reachable state. The
   client parses the header and says how long to wait instead of "wait a
   moment". A 429 remains deliberately non-retryable — the fix is for the
   user to wait, not for the client to hammer the endpoint.
2. **`X-Request-ID` is now captured** on failures, including on bodiless
   gateway errors, so a support report can be correlated with the server's
   structured logs.

Checked and already correct: 5xx (including a fail-closed `/readyz` 503) maps
to a retryable `server` failure; KYC and leg-proof uploads pre-check size and
MIME against the server's limits; dispute evidence reads its limits from the
server.

### Open — for Codex, unchanged from Phase 5

Handover/dispute/rating events publish no notifications; guest payers have no
post-payment status endpoint; `kyc_status` cannot distinguish "never
submitted" from "expired".

## 6. Verification

- `dart format` — clean (105 files)
- `flutter analyze --fatal-infos` — **No issues found**
- `flutter test` — **107 passed**, unchanged; no behavioural assertion was
  weakened to accommodate styling
- Catalogues: 968 keys × EN/FR/AR, parity verified, `l10n_untranslated.json`
  empty

### Rendering

There is still no Android/iOS/desktop toolchain on this machine
(`flutter doctor`: Windows + network only). Two surfaces were used:

- A **temporary web build**, which proved unreliable: the browser pane
  throttles `requestAnimationFrame` to zero when it is not on screen, which
  freezes every entrance animation part-way. Removed.
- A **`flutter test` screen renderer** — real device metrics, the real
  bundled variable fonts plus Material Icons, and a deterministic clock.
  Nine screens captured as PNGs across iPhone, small Android, large-text and
  landscape profiles, in EN/FR/AR and both themes. This is what found
  findings 3, 4 and 5. Removed after the review.

Neither is a substitute for hardware. Rendering on real Android and iOS
devices remains the outstanding gate.

## 7. Not done, deliberately

No provider activation, no webhook registration, no production credentials,
no deployment, no Phase 7 work. Stripe and Chargily remain **CODE-CONTRACT
VERIFIED** only.
