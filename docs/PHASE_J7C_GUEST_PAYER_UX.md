# Phase J7C — Guest payer ("Someone else can pay") UX

Status: implemented, TEST only. Stripe TEST, Chargily TEST,
`PAYOUT_DZD_EXECUTION_ENABLED` false, no LIVE provider activation and no
real-money operation. **No APK was built** — deferred to the combined J7 build.

Starting point: `8461ff7` (J7B PASS). Branch `claude/j7c-guest-payer-ux`.
Backend **and** mobile change. One additive migration
(`finance.0026_guestpaymentlink_token_seed`). No payment accounting touched: no
ledger, funding, refund, attempt-lifecycle, verification or idempotency code
changed. Payment-success screens (J7D) were not redesigned.

Owner feedback: the "Someone else pays" experience had an email field whose
purpose was unclear, and the surface looked disconnected from ShipTrip.

---

## 1. The email field — what it actually did

Traced end to end before any UI change.

| Question | Answer |
|---|---|
| Where is it? | **Not on the Sender's surface at all.** The Sender's sheet never had an email field. It is on the **payer's** side: the public page `/pay/guest/<token>` ("Email for your receipt", HTML `required`) and the in-app anonymous `GuestPayScreen` ("Your email for the receipt", required). The owner met it by opening the shared link. |
| Whose email? | The **guest payer's** own address. |
| Required by the backend? | Only when `EMAIL_ENABLED` (`TRANSACTIONAL_EMAIL_ENABLED`) is true — `GuestCheckoutCreateSerializer` refuses a blank address then. **TEST runs with `EMAIL_ENABLED=false`**, so the server never required it there; the page and the app screen demanded it anyway. |
| Used to email the payment link? | **No.** Nothing in ShipTrip emails a payment link to anyone. |
| Stored? | Yes, on `PaymentAttempt.guest_email` only. Never returned by any guest read, never shown to the Sender (`paid_by` says `guest`, never who). |
| Sent to a provider? | Yes: passed to Stripe Checkout as `customer_email` (pre-fills Stripe's own email field). Chargily does not take guest payments (`supports_guest_payment=false`). |
| Used for receipts? | Yes — ShipTrip's own outbox sends the guest a success receipt, a failure notice and refund-status mail (`GUEST_PAYMENT` / `REFUND_STATUS`), in the link's snapshotted language. **With `EMAIL_ENABLED=false` none of these is ever sent.** |
| Does the public page need it? | Only for those receipts. |
| Does link creation / use work without it? | Yes. Link creation never takes an email; checkout works with a blank one whenever email is off. |

**Conclusion.** The field was the payer's receipt address, legitimately needed in
LIVE (which requires `EMAIL_ENABLED`) and entirely pointless in TEST, where it was
nevertheless shown as required. That — not a Sender-side field — is what read as
"unclear".

## 2. Email decision

* **Sender side — option A: no email.** The Sender is never asked for anyone's
  address. "Send by email" was considered and **not built**: ShipTrip has no
  link-mailing capability, and adding one would let any account make ShipTrip
  send branded mail carrying a payment link to an arbitrary address — a phishing
  amplifier. The phone's share sheet already includes the Sender's own mail app,
  and a request that arrives from someone the payer knows is more trustworthy
  than one from a platform they have never heard of.
* **Payer side — asked only when used.** The guest view now carries
  `receipt_email_required` (= `EMAIL_ENABLED`, the same function the checkout
  serializer uses, so the two cannot disagree).
  * Off (TEST today): no field on the page or in the app; an address posted by
    hand is discarded, not stored.
  * On (LIVE): the field is labelled **"Email for your receipt"** with one line —
    *"We'll send your receipt here, and tell you if a refund is ever due. It
    doesn't create an account."* The page now validates it server-side too (the
    web path previously accepted anything the browser let through) and keeps
    what was typed on error. It is placed **after** the amount, not before it.
* Duplication: with the field shown, Stripe receives it as `customer_email` and
  displays it pre-filled, so the payer types it once.

## 3. Defect found: opening the sheet broke the shared link

The J3 sheet called `POST .../guest-link` every time it opened, and issuing
**revokes the previous link**. A Sender who shared a link and then reopened the
sheet to check on it silently killed the link their relative was holding. (The
J3 document described a `GET` that did not exist.) Tokens were stored hash-only,
so the server could not show a live link again.

**Fix — recoverable, still not reconstructable from the database.** New links
store a random `token_seed`; the bearer token is
`HMAC-SHA256(SECRET_KEY-derived key, seed)` (`derive_guest_token`, Django
`salted_hmac` with its own salt). Lookup is unchanged: by SHA-256 of the token.
A database read alone still cannot produce a working link — it takes the
database **and** the deployment key. `recover_guest_token` checks the re-derived
token against the stored hash, so a rotated key hides the link instead of
showing a dead one. Pre-J7C links have no seed and are reported as "still works,
can't be shown again", replaceable only by explicit action.

## 4. Link contract (Sender)

One shape on every verb, so the app renders what the server last said:

`GET /api/payments/orders/<ref>/guest-link` — **new**, read-only, issues nothing.
`POST …/guest-link` — shares: returns the live link again (`reused: true`, 200)
or issues one (201; `reissued: true` if it replaced a live one).
`POST …/guest-link/revoke` — now also returns the state.

| Field | Meaning |
|---|---|
| `state` | `none` · `active` · `expired` · `revoked` · `paid` · `closed` — derived from the order and its newest link, never stored |
| `token`, `payment_link` | present only while `active` **and** showable |
| `expires_at` | for `active` / `expired` |
| `amount_eur_cents`, `currency`, `purpose` | the order's authoritative outstanding amount and machine purpose |
| `checkout_in_progress` | a payer holding the live link has an open attempt |
| `can_create`, `can_revoke` | what the server will permit right now |
| `communication_language` | receipt-language snapshot; an explicit value on re-share updates the live link |

Owner-only (traveler, outsider and staff get 403). Semantics preserved: one live
link per order (partial unique index), 72 h expiry (policy), replacement refused
mid-checkout, uniform `guest_link_invalid` for the guest.

**Revoke rule (deliberate change).** Revoking is now **refused while a payer is
mid-checkout** (`guest_checkout_in_progress`, 409). The owner's brief lists this
as existing behaviour; the code allowed it (J2 called revoke "the escape hatch").
It could not stop anything: the hosted session stays payable and the webhook
still applies the money, so allowing it told the Sender something untrue. The
Sender can still pay the obligation themselves, which supersedes the guest's
attempt exactly as before.

## 5. The Sender's sheet — information hierarchy

```
Someone else can pay                                   ✕
REMAINING DELIVERY PAYMENT          ← purpose, terracotta eyebrow
€42.50                              ← Fraunces hero, server figure
Share this secure payment link with someone you trust.
They can pay without a ShipTrip account.
[ ⤴ Share link ]                    ← ink pill, primary
[ ⧉ Copy link ]                     ← hairline pill → "✓ Copied" for 2 s
┌ 🔗 Payment link ready                        ⋯ ┐ ← sunken status panel
│    Expires Sep 21, 15:30                      │   (live region)
│ - - - - - - - - - - - - - - - - - - - - - - - │
│ shiptrip…/pay/guest/Xq3Z9…   (mono, LTR)      │
└───────────────────────────────────────────────┘
```

* **Amount first**: the server's outstanding figure; the sheet computes nothing.
* **Purpose in words**: *Deposit for your request* / *Delivery payment* /
  *Remaining delivery payment* (a balance with a credited deposit or a part
  payment) / *Boost payment* — from `purpose` plus the server's own figures.
* **Share** hands the phone a message with the link and amount plus a subject
  (for mail). **Copy** confirms in place — no dialog, and no snackbar (a snackbar
  renders *under* a modal sheet, so the J3 confirmation was never visible).
* **Revoke** lives behind **⋯ → Revoke link**, confirms with *Keep link* /
  *Revoke link*, then shows the revoked state in place.

| State | What the Sender sees | Actions |
|---|---|---|
| `active` | Payment link ready · expires | Share, Copy, ⋯ Revoke |
| `active` + paying | Someone is paying now · updates by itself | none |
| `active`, not showable | Your earlier link still works · can't be shown again | Create a new link (secondary) |
| `expired` | This payment link has expired | Create a new payment link — never silently |
| `revoked` | This payment link is no longer active | Create a new payment link |
| `paid` | wax seal ✓ · Payment received · "€42.50 was paid successfully." | Continue (closes the sheet onto the parent's authoritative success state) |
| `closed` | This payment can no longer be made by link | — |
| load failure | We couldn't load your payment link… | Retry |

Errors are words, never codes or server strings (the J3 sheet printed
`serverDetail`): busy link on create/revoke, refused revoke, already paid on
create (shows the paid result), network failure, share unavailable.

Only the **first** open issues a link (tapping the entry point is the request);
every later open reads.

## 6. Entry point

The Sender's payment section keeps **Someone else can pay** as a tertiary action
under the primary *Pay €X with Stripe* button. It now appears whenever **any**
usable rail accepts guest payment, not only when the Sender's own selected rail
does — previously selecting Chargily for yourself hid the option.

**Related defect fixed.** While a guest was mid-checkout, the Sender's section
offered *Continue your payment* with the **guest's** Stripe session URL. It now
says *Someone else is paying this now* with *Check again* and the sheet link,
and offers no way into the guest's session.

## 7. Realtime

No new realtime system. The sheet registers the existing `payment.*` resource
(`LiveResource.payment(deal)` / `deposit(request)`); an event re-reads the order
and the link, and a settled order moves the sheet to *Payment received* and
calls `onSettled` exactly once. The fallback poll now:

* runs **only while a link is live** (nothing to wait for otherwise);
* backs off 3, 3, 5, 5, 10 s then every 20 s;
* **stops after 10 minutes** of scheduled waits (counted, not wall-clock);
* restarts on return to the app and after a new link is issued;
* re-reads the link only when the order's latest attempt changes.

## 8. The public page `/pay/guest/<token>`

Rebuilt in the app's design system: `AppColorScheme` values verbatim
(parchment, ink `#0E1F2C`, terracotta), Fraunces for the amount, DM Sans for
the rest, Noto Sans Arabic in Arabic — the landing site's own subsets from
`/assets/fonts`, no external request, no script, no gradient; dark variant from
the app's dark tokens.

* Header: the wax-seal "S" mark + ShipTrip, and an **EN · FR · العربية** switch.
* Language: `?lang=` choice → the reader's browser language → the link's
  snapshot language → English. One language at a time (the old page stacked
  three).
* Card: eyebrow *Payment request* → **€42.50** → purpose (*Payment for a
  delivery* / *Deposit for a delivery request*) → one sentence of context.
  A ticket perforation, then the rail (a single rail is shown as a fact, several
  as radio cards), the email field only when required, **Pay €42.50 →** (ink
  pill, 54 px), and the hand-off line *"You'll finish on our payment partner's
  secure page. ShipTrip never sees your card details."*
* Facts: how long the link lasts in words (*"Link valid for 3 more days"*, with
  Arabic dual forms — no timezone to guess) and the scope sentence.
* A rail outage at the tap now shows *"Payments are paused for a moment — your
  link is fine"* (503) instead of the dead-link page.
* Dead links (unknown, expired, revoked, paid, closed) still get one uniform
  page, now in the reader's language.

Provider checkout is not redesigned; the POST still redirects to the hosted
provider, and returning proves nothing.

## 9. Privacy

The guest payload gained one field, `receipt_email_required` (server config).
The page and the API still carry no sender, traveler, recipient, address,
parcel, deal, order reference, request id, order id, seed or hash. The token is
the path only — never a query string (the language switch is `?lang=` on the
same path) — and the page sets `referrer: no-referrer`. The Sender's link
endpoints are owner-only.

## 10. Localisation

EN / FR / AR reviewed together. Sender entry and title: **Someone else can pay**
/ **Faire payer quelqu'un d'autre** / **اطلب من شخص آخر أن يدفع**. The payer
screen's title changed from the Sender's phrase to **Payment request / Demande
de paiement / طلب دفع**, and its warning was rewritten from the payer's
perspective (it said "your delivery"). Dead keys removed.
`l10n_untranslated.json` is empty. The URL preview is forced LTR in Arabic;
directional glyphs rely on `matchTextDirection` (no manual flips).

## 11. Tests

**Backend** — `apps/finance/tests/test_j7c_guest_link_ux.py` (25): read issues
nothing; first share creates, second reuses the same link; 72 h; revoked /
expired / paid / closed states; owner-only; mid-checkout freezes replace **and**
revoke; the Sender can still pay; DB-only reconstruction impossible; pre-J7C link
reported not invented; rotated key hides; email off → not asked, not stored;
email on → labelled, explained, validated, kept on error; the app checkout
applies the same rule; page amount/purpose/CTA; privacy withholding; language
order; deposit naming; uniform localised dead page; rail outage ≠ dead link;
provider hand-off unchanged; amount formatting; durations incl. Arabic duals.
Updated: the J2 guest tests (payload key, revoke now refused), the payload key
set in `test_guest_payment.py`, the 6C re-share language test, and the J2 page
privacy check, which searched raw HTML for a bare primary key and would have
matched a CSS size (`assert_page_withholds` now checks visible text).

**Mobile** — `test/phase_j7c_guest_payer_test.dart` (82): first open creates
once; reopen reuses; server amount wins; purpose naming (delivery / remaining /
deposit); non-showable link; no Sender email field; payer email hidden when off
and not sent; labelled and placed after the amount when on; copy (clipboard, in
place, no dialog, reverts); share (text + link + amount + subject); revoke behind
More, confirm/keep, revoked state; refused revoke in words; active / paying /
expired / revoked / paid states; already paid on create; busy on create;
network failure + retry; live event → Payment received, `onSettled` once, no
reads after; poll backs off, stays ≤ 36 reads in 10 min and then stops; no poll
without a live link; entry point is tertiary and independent of the selected
rail; guest mid-checkout never offers the guest's session; EN/FR/AR incl. RTL
and LTR URL; no overflow at 320×640, 390×844, 411×869, 844×390 landscape and
1.6× text in EN/FR/AR across states; 48 dp targets; amount and status
semantics.

## 12. Rendered QA

A throwaway golden rig (app fonts + icon font, not committed) rendered the real
sheet over a page at 390×844, 320×640 (FR), 411×869 (AR), 1.6× text and
844×390 for: active, remaining balance, paying, expired, revoked, not-showable,
paid (EN/AR), the open ⋯ menu, "Copied", the entry point (EN/AR), the
guest-paying section, and the payer screen with receipts on/off (EN/AR). Two
defects were found only by looking: the paid seal's "✓" rendered as an empty
box (the app faces have no check glyph — now an icon), and the menu needed an
explicit hairline shape. The public page's real template was rendered for 11
states/languages and inspected in a browser at 320, 390, 160 % text, light and
dark: no horizontal scroll anywhere; in Arabic the button's amount is isolated
LTR so it reads like the headline.

## 13. Verification and release

* Local: backend guest suites 82 passed (SQLite and PostgreSQL), full Django
  suite on PostgreSQL **2,199 passed / 34 skipped / 0 failed**, `ruff` clean,
  `manage.py check` clean, `makemigrations --check` no changes; mobile full suite
  **837 passed**, `flutter analyze --fatal-infos` and `dart format` clean,
  `l10n_untranslated.json` empty.
* CI [35375639693](https://github.com/is-bo/shiptripis/actions/runs/35375639693)
  at `311c804`: all six jobs green (Django 2,199 / 34 skipped, schema drift ok).
* `main` = `origin/main` = `311c804`; branch deleted locally and remotely.
* TEST deployment `99cc109d-751f-420a-9309-95a6c396bce9` SUCCESS, release
  `v1.0.0-rc.42+311c804`; `/healthz` and `/readyz` 200; migration 0026 applied;
  new public page and 401 owner endpoints verified from outside.
* Stripe TEST, Chargily TEST, `EMAIL_ENABLED=false`, DZD execution false, no LIVE,
  no real-money operation. **APK: not built** (deferred to the combined J7 build).

## 14. Remaining findings

* **MINOR (J7D)** — the post-provider return page `/pay/<ref>/return` still uses
  the old generic style; it is a payment-result surface and belongs to J7D.
* **MINOR (J7D)** — the in-app anonymous screen's post-handoff text says "The
  payment is confirmed" next to "a redirect is not proof"; payment-result copy,
  J7D. (No deep link reaches that screen today; shared links open the web page.)
* **MINOR** — pre-J7C live TEST links cannot be shown again; the sheet says so
  and replaces them only on request. They expire within 72 h.
* **Note** — the Arabic date inside the status line uses the app's existing
  `LocaleFormats` output (Arabic-Indic digits for dates), unchanged here.
