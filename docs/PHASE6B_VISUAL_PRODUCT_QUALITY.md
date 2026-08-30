# ShipTrip V1 Phase 6B — Public web, admin and email presentation

Status: **IMPLEMENTED / LEGAL AND PROVIDER GATES UNCHANGED**

Phase 6A built the public website, the operations admin and the transactional
outbox as engineering: correct, dependency-light, and deliberately not designed.
Phase 6B is the design pass over those three surfaces, and nothing else. No
payment provider was activated, no webhook was registered, no legal text was
approved, and the Flutter client was not touched.

The governing constraint is that these surfaces have to look like the same
product as the app. Phase 5C restored ShipTrip's original visual identity in
Flutter from commit `76ce129`; this phase ports **the same token values** — not
a web interpretation of them — out of `mobile/lib/design/tokens.dart` and
`mobile/lib/design/typography.dart`.

---

## 1. Landing site, before the work

Rendered rather than read. The Phase 6A site was structurally sound and
visually a different product:

| Finding | Severity |
|---|---|
| Palette was not ShipTrip's. `--ink: #17352f` (a green-black), ground `#f8f5ef` — the *rejected* Phase 5 sand, not parchment — emerald-dominant, no sun, no gold, no grain, no terracotta beyond a hairline | BLOCKER |
| Display face was `"Iowan Old Style", Palatino, serif`; `"DM Sans"` and `"Noto Sans Arabic"` were named with **no `@font-face`**, so every visitor without them installed — effectively all of them — got a system fallback | BLOCKER |
| At ≤840px, `.nav-links a:not(.button)` hid the section anchors **and the language switcher**, leaving an empty bordered dot. On a French/Arabic product whose audience is mobile-first, there was no way to change language on a phone | BLOCKER |
| The hero route board was incoherent: the line touched none of its three nodes, the arrowhead ended in empty space, and `.board-note` overlapped the third stop | MAJOR |
| Arabic RTL was **double-mirrored**. The layout already used logical properties, which mirror on their own; the `[dir="rtl"]` block then mirrored them again, so the corridor ran left-to-right on a right-to-left page, with `جيجل` colliding with the board note | MAJOR |
| Terracotta `#c95e42` at 0.72rem for every eyebrow, stamp and mode chip: 3.6–3.8:1, below AA for small text | MAJOR |
| Build-process comments (`THESIS:`, `OWN-WORLD:`, `FORM: … seed 7accc8d5`) shipped in the production HTML of all three locales | MINOR |
| No favicon of any kind; `backdrop-filter` on the sticky header for no visual gain | MINOR |
| Legal pages were a single undifferentiated column; the language pill implied translations that do not exist | MINOR |

---

## 2. Identity adaptation

`web/assets/site.css` is rebuilt on the app's semantic tokens, ported verbatim
from `AppColorScheme.light`: parchment `#F4EFE6`, ink `#0E1F2C`, printed
terracotta `#C75E26`, vivid terracotta `#E8763A` (shapes only, never text), sun
`#FBBC04`, gold `#C9A961`, emerald `#0E5A4F`, lapis `#2A62A6`.

**One token is added that the app does not have.** `#C75E26` is 3.6:1 on
parchment — right for a rule or a border, short of AA for a word. Terracotta
*text* (eyebrows, stamps, links) therefore takes `--attention-print: #9B4318`,
which is `clay1`, an existing step on the app's own ramp rather than a new
colour. `#C75E26` remains the border, marker and rule colour.

The four faces the app bundles are subset and served from the same origin by
`tools/web/build_fonts.py` (fontTools instancer + subsetter → woff2):

| Face | Role | Size |
|---|---|---|
| Fraunces (`wght`+`opsz` variable, `SOFT=0 WONK=1` pinned, as `typography.dart` sets them) | display headings | 66 KiB |
| DM Sans (`wght` variable) | all Latin UI text | 36 KiB |
| Noto Sans Arabic (`wght` variable) | Arabic, incl. display — Fraunces has no Arabic coverage, and the app answers this the same way | 154 KiB |
| JetBrains Mono (digits + capitals only) | the handover-code tile | 7 KiB |

`unicode-range` keeps the Arabic face off the EN and FR routes entirely.

Marks are drawn with borders, gradients and inline SVG. The original had **no
raster or SVG assets** — every mark was a `CustomPainter` — and the production
CSP is `default-src 'self'`, which blocks `data:` URIs, so an image would have
been both off-identity and non-loading. What exists: paper grain (two offset
speckle gradients on a fixed layer), airmail chevron borders, perforated postage
stamps, dashed passport stamps, wax seals, boarding passes with a dashed
perforation and punched notches, hard stamped shadows, and split-flap code
tiles.

---

## 3. Hero

Left: eyebrow, serif display headline with one terracotta italic accent, lede,
sun primary + ghost secondary, three quiet trust lines. Right: an
airmail-bordered postcard carrying the corridor.

The postcard's illustration is inline SVG: a parcel at the origin, a dashed
lapis flight arc Paris → Alger with a plane sitting on the arc's own tangent at
its midpoint, an emerald road Alger → Jijel, three nodes, and a terracotta halo
on arrival — the moment the product exists for, and the only vivid terracotta on
the drawing. A `stroke-dashoffset` tracer (normalised with `pathLength="100"`)
runs the whole journey on a 3.2 s loop, matching the original's flight-path
tracer, and resolves to a completed static route under `prefers-reduced-motion`.

No metric, testimonial, user count, download link or provider availability is
claimed anywhere on the page.

---

## 4. Sender and traveler

Two boarding passes, side by side, sharing one card language so the site never
reads as two products. Each is a head (seal, role, the flow in one line) over a
dashed perforation with punched notches, then the ordered steps on the same
numbered-route motif the app uses.

* **Sender** — describe → publish with a posting deposit → compare compatible
  travelers → propose a reward and negotiate → pay, funds held, addresses unlock
  → hand over with the pickup code → delivery confirmed, protection period.
* **Traveler** — verify identity → build the journey from ordered legs → prove
  the flight legs → review requests that fit → collect with the pickup code →
  deliver against the recipient's code → payout after the protection period.

Every step is real V1 behaviour. The sender proposes first; boost is described
as changing ranking only.

---

## 5. Product explanation

A "journey is a list of legs" section (FLIGHT, DRIVE, per-leg capacity,
compatibility-before-display) and an eight-card mechanics section: private until
funded, a deposit to publish, the sender proposes, two codes / two moments, the
deliberate delay before the delivery code, the protection period, disputes
freezing payout, then payout.

Security-sensitive specifics are deliberately vague where the exact number is an
attacker's parameter: the site says "a short buffer after pickup" and "a
protection period" in the mechanics cards, while the Terms — which is where a
term of service belongs — states the 48-hour figure. The delivery code is
explained as unobtainable by the traveler, with the reason, because that is a
trust argument rather than an implementation detail.

---

## 6. Payment language

EUR is the marketplace currency; every amount is described as server-calculated.
The ledger reads as addition toward what the sender pays, with an explicit `+`:

```
Traveler receives    €30.00
ShipTrip fee       + €7.50
─────────────────────────────
You pay              €37.50
```

Nothing anywhere says or implies the traveler loses 25%. A posting deposit is
described as credited against the total, never as a second fee. Chargily's DZD
figure is described as a platform-configured conversion of the EUR amount — a
payment-rail settlement, not a market rate and not a second price. The word
*escrow* does not appear; the site says funds are **held pending delivery
confirmation** and payout waits for confirmation and the protection period. No
provider is described as live.

---

## 7. Localization

Three complete catalogues, not a translated shell. FR and AR carry the same
information architecture, the same illustrations and the same fee ledger with
locale-correct number formatting (`30,00 €` in French).

**Arabic.** The double-mirroring bug is removed: the layout mirrors once,
through logical properties. The illustration mirrors as geometry
(`.mirror { transform: scaleX(-1) }`) with each `<text>` counter-flipped about
its own box, so the corridor runs right-to-left — parcel and Paris on the right,
Jijel on the left, plane pointing left — while every label stays legible.
Currency and Latin runs are wrapped in `.ltr` with `unicode-bidi: isolate` so
`€30.00` cannot reorder. `<em>` is neutralised in Arabic headings, because a
synthesised oblique is a distortion of the letterforms rather than an emphasis.

A Phase 6A copy error was fixed: the Arabic pages said *مزوّجات الدفع*
("married ones of payment") where they meant *مزوّدي الدفع* ("payment
providers"), twice.

Policy pages remain English-only, which is now **stated on the page** rather
than implied away by a language switcher: the switcher is labelled for screen
readers as opening the localized home page, and each draft notice says policy
pages are published in English until legal approval. Translating them would mean
publishing legal text no lawyer has read in that language.

---

## 8. Responsive

Verified by rendering, not by reading media queries. Headless Edge on Windows
refuses to lay out below ~492 CSS px, so phone widths were checked in a browser
that emulates the viewport properly; `tools/web/shot.sh` documents that limit.

At 375 px: no horizontal overflow on any locale, and the sticky header is
**114 px in two rows** — identity plus the language switcher and contact on the
first, the section anchors on a single horizontally scrolling line on the
second. The old build reached three stacked rows and hid the switcher entirely.

Interactive targets were raised: nav links 38→44 px, language links 34→40 px,
FAQ summaries 26→48 px, footer links 24→35 px.

---

## 9. Accessibility

Landmarks, skip link, ordered headings (`H1 H2 H3…`, no skipped level), visible
`:focus-visible` outlines in lapis (5.4:1 on parchment, 3.6:1 on the sun
button), `prefers-reduced-motion` honoured with a complete static frame, `lang`
and `dir` correct, `hreflang` on every language link, decorative marks
`aria-hidden`, and a `<caption class="sr-only">` on the fee table.

Contrast was computed rather than eyeballed. Every text pair now clears AA;
`--attention-print` and moving the footer labels off `--text-tertiary` were the
two fixes that required it. The wax seal's letter changed from white (2.96:1) to
ink (5.66:1) on vivid terracotta.

---

## 10. Performance

| | |
|---|---|
| EN first view | ~118 KiB over the wire, 5 requests, 0 third-party |
| AR first view | ~171 KiB (Arabic face included) |
| JavaScript | 257 bytes, one file, `defer` — a copyright year |
| Framework | none |
| Fonts | self-hosted, subset, `font-display: swap`, the two Latin faces preloaded |

`backdrop-filter` was removed from the sticky header: it cost compositing work,
broke offscreen capture, and bought nothing on an opaque parchment bar.

---

## 11. Policy and support pages

Terms, Privacy, Prohibited Items and Support are rebuilt on a document layout —
a sticky section index, a measured column, a rotated "Product / legal draft"
stamp and a dashed terracotta review notice — without changing what they claim.
The status is unchanged and now harder to miss: **final legal review required**.
No retention period, legal basis, controller identity, jurisdiction matrix or
support SLA was invented. Support addresses remain marked as
deployment-configured placeholders.

---

## 12. Operations admin

The admin is a tool, not a postcard. Django's admin already carries a complete
CSS-variable theme with a working dark scheme and a user toggle, so
`apps/core/static/shiptrip/admin.css` re-points those variables at the ShipTrip
palette and leaves the DOM Django ships alone. `templates/admin/base_site.html`
adds the seal-and-wordmark masthead and loads that one stylesheet.

Beyond the theme, three things were added because a queue needs them.

**Money is money.** Every amount in this system is stored as an integer number
of cents, and the operations columns listed that integer raw. A refund queue
that reads `3750 12000 950` makes a hundred-fold misread an ordinary mistake,
and the consequence is a wrong refund. `apps/core/admin_display.py` renders the
stored integer as `€37.50` with tabular figures and right alignment, sorting
still on the underlying field. Nothing is recomputed, converted or rounded: the
server remains authoritative for every value, and the tests pin the arithmetic,
including negative ledger entries and the absence of floating point.

**Status is a chip.** Statuses now carry the word *and* a tone keyed to what an
operator should do — terminal-good, waiting, needs-a-human, failed, inert.
Colour is never the only signal. An unmapped status is inert rather than
alarming, because inventing an alarm nobody meant trains operators to ignore
alarms.

**Consequence has weight.** The amount that carries the financial consequence of
a row — a refund's amount, a payout's amount, an order's outstanding balance,
a dispute's collected total — is set apart from its components.

Applied to: payment orders, attempts, provider events, refunds, payouts, payout
methods, the ledger, scheduled jobs, disputes, deals, boosts, KYC submissions and
business settings.

### Authorization finding — fixed

`BusinessSettingsVersionAdmin` was a second, unaudited door into commercial
configuration. It offered an **"Activate selected business-settings revision"**
action and an ordinary add form, both of which:

* ran on Django's generic `core.change_businesssettingsversion` model
  permission rather than the Phase 6A `manage_settings` capability;
* wrote **no** `AdminAuditLog` row, unlike `POST /api/admin/settings`;
* skipped `AdminSettingsCreateSerializer`, so an arbitrary `policy` document the
  API would reject was accepted; and
* required no reason.

It also called `activate_business_settings` — a `select_for_update` under
`@transaction.atomic` — from an admin action, which is the sort of path that
works until it does not.

Commission, deposits, pricing bands, FX, cancellation terms, the pickup buffer,
the protection window and boost packages are exactly the settings that must not
be changeable through an unaudited path. The model is now inspection-only in the
Django admin, and the changelist and change form say so, along with the rule
that matters operationally: **activating a revision changes the snapshot taken by
new Deals only; amounts already snapshotted on an existing Deal are never
rewritten.** `apps/core/tests/test_admin_surface.py` holds that door shut.

### Not changed

`apps/payments` and `apps/wallet` are the legacy pre-V1 surfaces that V1 routes
are deliberately mounted ahead of. They were left alone: re-dressing a retired
surface adds risk without giving an operator anything.

---

## 13. Transactional email

Every message was plain text — a block of lines from an unfamiliar address,
carrying a six-character code and a request to hand a parcel to a stranger. That
is indistinguishable from the phishing mail this audience receives weekly, and
the recipient of a delivery code has no account and no session to check it
against. Recognisable branding is the only signal they have.

`apps/notifications/email_layout.py` introduces an `EmailDocument` — eyebrow,
heading, paragraphs, at most one highlighted value, at most one callout, an
optional action, reference rows — and renders it two ways. `to_text` produces
the plain-text body the transport has always carried; `to_html` produces the
alternative. **Both come from one object**, so the two parts of a multipart
message cannot disagree about what the message says.

The HTML is email HTML: tables, presentation attributes, inline styles, one
600 px column collapsing to full width, 16 px body text, a hidden preheader, no
web font, no external stylesheet, and **no image at all** — the masthead is a
wordmark set in type, because a blocked remote image is the normal case. The
handover code renders monospaced at 30 px with 6 px letter-spacing, which is the
size it needs to be when one person reads it aloud to another at a doorway.
Every footer repeats that ShipTrip never asks for a code.

Transport:

* secret-bearing messages (verification, reset, invitation, delivery code) now
  send through `EmailMultiAlternatives` at the same trusted Django SMTP boundary,
  with HTML attached as an alternative and plain text primary;
* ordinary messages gain an `html` field on the `email:send` stream payload, and
  the Go worker attaches it as an alternative when present — `internal/email`
  still does no templating and decides only multipart-or-not.

### Delivery-code secrecy — re-confirmed

Nothing about the Phase 4/6A boundary moved. `OutboundMessage.context` still
holds no plaintext; `secret_ref` still names `handover_code:<id>`; the seal is
still opened only inside `build_document`, in the trusted renderer, immediately
before transport; secret-bearing messages still bypass Redis entirely; the
published-event row still stores a hash; the code still never reaches a stream
payload, a log line, an audit row or the `last_error` column; a rotated or used
code still refuses to render.

`apps/notifications/tests/test_email_presentation.py` re-checks all of that
against the part that did not exist before — including that the HTML alternative
carries the code only at the trusted renderer, that `xadd` is never called for a
secret kind, and that an ordinary stream payload containing an `html` field
still contains no code.

### Deployment note

The `email:send` payload gained a field, so its `PublishedEvent.payload_hash`
changes shape. A message already transported and awaiting an SMTP receipt across
the deploy boundary would fail its retry with *"Outbound email event payload
changed between retries."* Email is not activated in production
(`EMAIL_ENABLED=false`, no provider live), so there are no in-flight messages
today; if that changes before this ships, drain the stream before deploying.

---

## 14. Verification

| Gate | Result |
|---|---|
| `python tools/check_static_web.py` | pass — 8 HTML files, 1 stylesheet |
| Django `manage.py check` | no issues |
| `pytest apps/` (SQLite, `test_local`) | see §16 |
| `ruff check apps/ config/` | all checks passed |
| `go build ./...`, `go test ./internal/email ./pkg/config` | pass |
| Contrast | computed for every text pair; all clear AA |
| Rendering | see §16 |

`tools/check_static_web.py` was extended: it now also fails on a stylesheet
asset that does not exist (an `@font-face` source is invisible to an HTML-only
crawl, and a missing face degrades silently to a system fallback), on `@import`,
on a `url(data:)`, and on a page that forgets the stylesheet or either favicon.
The new rules were negative-tested.

---

## 15. Second pass — rendered review after the stabilization work

The first pass built these surfaces; this one looked at them at the sizes and
in the states they will actually be met in. Everything below was found by
rendering, not by reading source: three locales at six widths, the admin against
a seeded database carrying every operational state it is supposed to surface,
and all twenty-four transactional messages rendered to files.

### 15.1 Public site

| Finding | Severity | Fix |
|---|---|---|
| The hero's italic display accent collided with the following word — Fraunces' italic exit strokes overhang their advance width, so "already on" set solid at display size and read as a typo in the first line of the page | MAJOR | `.hero h1 em` carries `padding-inline-end: .06em` |
| The Arabic FAQ disclosure arrow pointed **up** while closed and down while open. The arrow is drawn from two logical borders, so in RTL the corner it forms starts bottom-left rather than bottom-right; the compensating rotations were the wrong way round | MAJOR | RTL rotations swapped; closed points down in both directions |
| Six trust items in a four-column `auto-fit` grid left a hole two cells wide under the second row at desktop | MAJOR | Pinned to three columns above 62rem — 3 + 3 |
| The FAQ occupied the left half of a full-width band and left the right half empty, so the page ended thin | MAJOR | At ≥62rem the section is the same two-column figure the price section uses: heading rail, then the list |
| At 320px the sticky header grew to three rows — 149px, a quarter of an iPhone SE, permanently | MAJOR | Tightened below 360px; two rows, 113px, with the language switcher and contact button both kept |
| The eyebrow rule sat between the lines of a wrapped eyebrow. `align-items: center` looked right while every eyebrow fit on one line and slid to the gap the moment a longer French or Arabic string wrapped | MINOR | Aligned to the first line |
| On a phone the policy pages' table of contents reflowed into a wrapping row where each entry carried its own underline; six of them read as damage | MINOR | Stays a vertical rail above the document, with a rule under it |
| The English-only policy pages marked the current language `aria-current="true"` while the landing pages use `page`, so the pill was styled on one and not the other | MINOR | Selector widened to `[aria-current]` |
| French wraps the boarding-pass head to two lines where English does not, so the two tickets' perforated seams sat at different heights | MINOR | `.roles` gives both passes the same two rows through `grid-template-rows: subgrid` |

**Sizes actually inspected.** 320, 375, 430, 768, 1024, 1440 and 1600 CSS px,
for `/en/`, `/fr/` and `/ar/`, plus the four document pages at 375 and 1440.
Phone widths were measured in an emulated viewport at 2× — headless Edge on
Windows will not lay out below ~492 CSS px, which is why `tools/web/shot.sh`
says so. At every width and locale: `scrollWidth == clientWidth` (no horizontal
overflow), and no element outside the viewport except the deliberately
scrollable navigation row.

**Arabic.** Reviewed as rendered, not only structurally. The corridor mirrors
and runs right to left, ending on the arrival halo at the left; the labels
inside the drawing counter-flip and stay legible; the postage stamp moves to the
top-left of the postcard; currency stays `€30.00` inside its `.ltr` isolation in
both the ledger and the running text; the trust grid, FAQ rail and footer all
mirror once and only once. Mechanical RTL is correct. **Linguistic quality is
not claimed** — no native Arabic speaker reviewed the copy in this pass.

**French.** Reviewed as rendered. Text expansion is absorbed everywhere:
"Envoyer ou transporter" and "Fonctionnement" fit the navigation to 320px, the
hero headline breaks to four lines on a phone without a hyphen, and the mechanic
cards keep equal heights with the longest card running three lines past the
shortest. **Native French approval is not claimed.**

### 15.2 Operations admin, against seeded data

The seed, dump and render scripts are committed under `tools/preview/` with a
README; they write into the git-ignored `backend/monolith/build/`. Admin pages
are produced with `force_login` server-side rather than by posting the login
form, so no credential is typed anywhere.

Reviewed against a database carrying four deals driven through the real
services, an open dispute with evidence and a timeline, a resolved dispute, a
failed payment attempt, an unapplied payment, a refund needing manual action, an
unverified provider event, three scheduled jobs in three states, pending and
rejected KYC, three flight proofs, and a failed outbound email.

| Finding | Severity | Fix |
|---|---|---|
| The dashboard was an alphabetical directory of every registered model. It answered "where do I go" and never "is anything wrong" — an operator had to open nine changelists to find out | MAJOR | A **Needs attention** panel above the app list: nine queues, each a count, a name, a consequence and a link to the changelist already filtered to exactly those rows |
| `OutboundMessage` — the durable obligation behind every transactional email — had no admin at all. "Did the verification email go out, and why is that address bouncing" was answerable only from logs | MAJOR | Registered read-only, with the transport error and the attempt budget on the list. It renders no secret and does not display `secret_ref` |
| Every boolean on the user queue drew Django's red cross. Under IS BANNED a red cross means the account is **fine**; under IS KYC VERIFIED the same mark means it is not | MAJOR | Worded chips with the tones used everywhere else in the admin |
| `ban_users` was a bulk action reached from a dropdown beside a select-all checkbox. It sets `is_active=False`, signing the person out of an account they may be mid-delivery on, with no confirmation and no audit row | MAJOR | An interstitial listing exactly who is affected and stating the consequence, before a second deliberate click |
| The scheduled-job change form left `status`, `run_at` and `max_attempts` editable, so a `payout_release_check` could be marked succeeded by hand — cancelling a scheduled money action with nothing recorded. The module's own docstring says requeue is the one mutation offered | MAJOR | Every field read-only; the object page renders as a view; `requeue_jobs` remains, and remains limited to failed and stuck jobs |
| The settings revision printed its policy as one eighty-key JSON blob. An operator asked "is protection still 48 hours" had to find `payments.payout.protection_window_seconds` and divide by 3600 | MAJOR | A **Key values** table above the document: every knob §12 names, in operator units, each row naming the key it read. The document stays underneath and remains the authority |
| A dispute page carried evidence and a timeline but not the money it was about to be decided against — payment, payout and refund state were three filtered changelists away | MAJOR | A **Where the money is** panel: order status and amount, refunds, payout status, plus the frozen / already-settled warning |
| Dispute evidence printed all 64 characters of its SHA-256, taking a third of the row from the columns that are read | MINOR | First twelve characters, whole hash on the title attribute |
| A job's `attempts` was a bare number with its budget on another page | MINOR | `5 / 8` |

Two things were deliberately **not** changed. Legacy and out-of-scope models
(`payments`, `verification`, `wallet`, `ProductRequest`, token blacklist) stay
registered: de-registering them removes operator access to historical rows,
which is a functional decision rather than a visual one. And several models
carry Django's auto-pluralised names — "O auth identitys", "Matchs", "Ledger
entrys", "Wallet entrys", "Handover code accesss", "Kyc submissions" — which are
wrong English on an operator surface but are fixed in model `Meta`, and that
generates migrations. Left as a MINOR for a bounded Codex change.

### 15.3 Transactional email

All twenty-four documents were rendered to files and reviewed, at desktop and at
375px. Audited mechanically across every document: no images of any kind, no web
fonts, no `background-image`, no flexbox, grid or positioning, no `calc`, no
`rem`/`em` sizing, no script, no form, one progressive `<style>` block whose
every rule has a working inline default. Table layout with `role="presentation"`,
a 600px shell declared as both attribute and style, a hidden `mso-hide:all`
preheader, and `color-scheme` metadata.

| Finding | Severity | Fix |
|---|---|---|
| The plain-text part carried no footer. The anti-phishing line — *ShipTrip will never ask you for a pickup or delivery code* — and the transactional-message notice were HTML-only, so the part a plain-text reader receives said less about the one thing it most needed to | MAJOR | `_footer_lines` is shared; both parts carry it |
| Two documents interpolated a context value into the middle of a sentence with an empty-string fallback. The outbox is durable, so a row queued before a deploy is rendered after it: a missing `resolution_label` produced *"has resolved this dispute as: ."* in a customer's inbox | MINOR | Both sentences now stand alone without the value; regression-tested with an empty context |

**Client evidence.** The documents were rendered in a Chromium engine at 375px
and at desktop. **No real email client was used**, and no compatibility claim is
made from HTML inspection: Gmail (web and Android), Outlook desktop (Word
engine), Outlook.com, Apple Mail and a narrow Android client all remain
unverified. The construct audit above is what the design is built to survive,
not evidence that it did.

**Delivery-code secrecy — re-confirmed against the new surface.** The plaintext
code appears in no outbox context, no Redis payload, no event payload, no audit
row, no log line and no admin screen. Registering the outbox admin is the first
time these rows have been rendered to a person, so it is tested directly:
`apps/notifications/tests/test_outbox_admin.py` drives a real deal to a released
code and asserts the code and its `secret_ref` are absent from both the
changelist and the detail page, that `secret_ref` is not a field the page can
render, search or list, and that the row cannot be added, changed or deleted.
The renderer boundary is unchanged.

### 15.4 Email localization — decision

> Phase 6C implemented this follow-up. The durable language model, catalogues,
> event wiring, fallbacks, security constraints, and mobile handoff are recorded
> in `docs/PHASE6C_TRANSACTIONAL_EMAIL_LOCALIZATION.md`. The text below is kept
> as the Phase 6B decision record.

**Not implemented in this pass, because it is not presentation work.** The
groundwork does not exist: `USE_I18N` is on but there is no `LANGUAGES`, no
`LOCALE_PATHS`, no `locale/` catalogue and no `gettext` call anywhere in the
codebase; `User` has no language field and `OutboundMessage` has no language
column. Localizing email therefore needs migrations, a value captured at enqueue
time on a durable row, changes at thirteen call sites across six apps, and an
answer for recipients who have no account at all. Per the brief, it is specified
here for a focused Codex task rather than half-built.

**Required launch behaviour.** Every user-facing transactional email must render
in **French, Arabic and English**. This is a French- and Arabic-speaking
corridor; an English-only transactional stream is not a rough edge, it is a
delivery that cannot be completed. The one exception is `ADMIN_INVITATION`,
which goes to operations staff and may stay English, matching the admin itself.

Ordered by what breaks without it:

1. `RECIPIENT_DELIVERY_CODE` — **first**. It goes to someone with no account, no
   app and no setting to change, and it carries the instruction that makes the
   handover safe. A recipient who cannot read *give this code only once the
   parcel is in your hands* is a security failure, not an inconvenience.
2. `EMAIL_VERIFICATION`, `PASSWORD_RESET` — they gate account creation and
   account recovery.
3. `PICKUP_CONFIRMED`, `DELIVERY_CODE_RELEASED` — they explain the 30-minute
   buffer, which is the moment users most often believe something is broken.
4. `DELIVERY_CONFIRMED`, `PROTECTION_ENDED` — they state when money moves and
   until when a problem can still be raised.
5. `DISPUTE_OPENED`, `DISPUTE_RESOLVED`, `DEAL_CANCELLED` — deadlines and
   outcomes with financial effect.
6. `RATING_AVAILABLE`, `PAYOUT_STATUS` — last; both states are visible in-app.

**What the Codex task needs to cover.**

* A language on `User`, set through the existing profile route, and a `language`
  column on `OutboundMessage` **captured at enqueue time** — the outbox is
  durable, and a preference that changes between enqueue and dispatch must not
  change a message already promised.
* A resolution rule for recipients with no account: the deal, not a user row.
  The sender chooses the recipient's language when they enter the recipient's
  details, defaulting to the sender's own.
* Catalogues for `fr` and `ar`, plus **RTL rendering** for Arabic: `dir="rtl"` on
  the shell, `align="right"` on the text cells, the callout's accent border
  mirrored — and the code tile pinned `dir="ltr"`, because a handover code must
  never reorder.
* A fallback rule: unresolvable language sends English. Never a half-translated
  message.
* Native French and Arabic review of the copy before the first production send.

### 15.5 Templates that exist but are not wired — classification

Thirteen kinds are enqueued by a service. Eleven have documents and no caller.
Reviewed one by one; **no backend event was wired in this pass**.

| Template | Class | Why |
|---|---|---|
| `KYC_STATUS` | **LAUNCH REQUIRED** | A rejection blocks the traveler from every journey, and the rejection *reason* is the actionable part. With no push channel, silence leaves a rejected traveler waiting indefinitely. The highest-value unwired template. |
| `FLIGHT_PROOF_STATUS` | **LAUNCH REQUIRED** | Same shape: a rejected proof makes a published leg unmatchable. Silence reads as a broken marketplace. |
| `SECURITY_EVENT` | **LAUNCH REQUIRED** | `PasswordResetConfirmView` sets a new password and notifies nobody. An attacker with mailbox access resets the password and the owner is never told — the standard account-takeover path, with the template already written. |
| `PAYMENT_FAILED` | **LAUNCH REQUIRED** | An unfunded deal sits on a grace timer and is lost if the sender does not retry. In-app recovery does not reach a user who has closed the app. |
| `REFUND_STATUS` | **LAUNCH REQUIRED** | Refunds settle asynchronously and some settle manually. Money moving back with no notification is the largest generator of support contact and of disputes. |
| `GUEST_PAYMENT` | **LAUNCH REQUIRED if guest payment is enabled at launch** | The guest payer has no account and no app; email is the only channel that exists. If the guest rail is off at launch, this drops to NOT NEEDED. |
| `PROTECTION_ENDING` | **NICE TO HAVE (recommended)** | The last chance to raise a dispute. `DELIVERY_CONFIRMED` already states the end of the window, so it is not strictly required — but the job kind to hang it on already exists, and it removes a class of "I found out too late" cases. |
| `PAYMENT_SUCCEEDED` | NICE TO HAVE | The deal state changes visibly in-app immediately and `PICKUP_CONFIRMED` follows. |
| `PAYMENT_REQUIRED` | NICE TO HAVE | Overlaps the acceptance flow, which is in-app and immediate; risks reading as duplicate next to `PAYMENT_FAILED`. |
| `EVIDENCE_REQUEST` | NICE TO HAVE | Only meaningful once operations have a "request more evidence" action; today the dispute status change covers it. |
| `PAYMENT_PROCESSING` | **NOT NEEDED** | A transient provider state. Emailing it is noise, and it invites action during a window in which no action is possible. |

### 15.6 A local toolchain note, not a product defect

This machine runs Python 3.14.3; CI and the container image both pin 3.12.
Django 5.1.4 copies a template context with `copy(super())`, which returned a
real instance up to 3.13 and returns the proxy from 3.14, so every admin
changelist and change form raises inside `InclusionAdminNode`. Two admin tests
were failing here for that reason alone before this pass. `conftest.py` restores
the pre-3.14 behaviour behind a version guard, so an admin test means what it
says on either interpreter; on 3.12 the shim does nothing.

## 16. What is still open

* Policy pages are English-only and remain unapproved drafts.
* Support mailboxes are placeholders.
* `sitemap.xml` and `robots.txt` still carry the `shiptrip.example` placeholder
  origin, to be set by the deployment template.
* Emails were rendered and reviewed in a browser, not in a client matrix. Gmail,
  Outlook desktop, Outlook.com, Apple Mail and a narrow Android client should be
  checked before the first production send. See §15.3.
* **Historical Phase 6B limitation, resolved in Phase 6C:** transactional email
  was English only. The durable language model, catalogues and fallback are now
  documented in `docs/PHASE6C_TRANSACTIONAL_EMAIL_LOCALIZATION.md`.
* **Historical Phase 6B inventory, resolved in Phase 6C:** six templates were
  launch-required and had no caller: `KYC_STATUS`,
  `FLIGHT_PROOF_STATUS`, `SECURITY_EVENT`, `PAYMENT_FAILED`, `REFUND_STATUS`,
  and `GUEST_PAYMENT` if the guest rail ships. `PasswordResetConfirmView`
  notifying nobody is the sharpest of them. See §15.5.
* Model `verbose_name_plural` is unset on several models, so the admin reads
  "O auth identitys", "Matchs", "Ledger entrys", "Wallet entrys", "Handover code
  accesss" and "Kyc submissions". Fixing it touches model `Meta` and generates
  migrations, so it was left for a bounded change rather than folded into a
  visual pass.
* Neither the French nor the Arabic copy has been reviewed by a native speaker.
  Mechanical RTL is verified; linguistic quality is not claimed.
* No provider was activated, no webhook registered, no production deploy
  performed, and the Flutter client was not modified.
