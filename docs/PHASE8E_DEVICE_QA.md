# Phase 8E — private real-device QA checklist

This is an owner checklist for one Android phone against the deployed private
release candidate at `https://shiptrip-production.up.railway.app`. It is not a
launch approval, and nothing in it authorises a real payment.

Work top to bottom: the traveller path depends on KYC approval, and matching
depends on both sides existing.

**Before you start**

- [ ] The APK's filename short SHA matches the release SHA deployed to Railway.
      An artifact from another commit proves nothing about this release.
- [ ] Open **Operations → Geography catalogue** in the admin console and
      confirm an applied manifest digest and the country counts. If it says
      *No catalogue import is recorded*, stop: nobody can create a request or a
      journey until the catalogue lands.
- [ ] Open **Operations → System** and read each payment rail's line. It states
      configured/enabled and whether the credentials are **test** or **LIVE**.
      Write down what it says before you touch anything in the app.

## Authentication

- [ ] Onboarding and sign-in clear the status bar, the notch and the gesture
      bar; nothing is under the home indicator.
- [ ] Registration: the keyboard does not cover the field being typed into, and
      the submit control stays reachable.
- [ ] Sign out and back in; the session survives a cold start.

## Profile

- [ ] The passport presents real, current facts — no placeholder counts, no
      figure that contradicts the account.

## Traveller

- [ ] Publishing a journey is refused before KYC. The refusal names KYC, and
      does not look like a crash.
- [ ] KYC upload succeeds from the phone (camera and gallery).
- [ ] The submission appears in the admin KYC queue with viewable evidence.
- [ ] Approve it in the console; the phone reflects the change without a
      reinstall.
- [ ] Journey creation: **Country → place → optional preferred point** for each
      end. All four countries are searchable.
- [ ] A FLIGHT leg offers airports only. A DRIVE leg accepts localities and
      airports.
- [ ] A FLIGHT + DRIVE journey saves with its legs in the order entered.
- [ ] Arabic: the picker, the leg list and the review step all read
      right-to-left, and IATA codes stay left-to-right inside them.

## Sender

- [ ] Delivery request creation follows the same country → place flow.
- [ ] The preferred point is genuinely optional: *Decide later* and *Remove*
      both work, and the copy says matching runs on the place, not the pin.
- [ ] Exact addresses are not visible to the other party before funding.

## Matching

- [ ] A request and a journey in the same canonical city are compatible.
- [ ] An airport endpoint matches its served city (CDG ↔ Paris, ALG ↔ Alger).
- [ ] Moving a preferred pin inside the same city does **not** change
      compatibility. If it does, that is a backend defect — record it.
- [ ] The sender proposes first; a boost never makes an incompatible pair
      compatible.

## Chat

- [ ] An empty thread shows an empty state, not a spinner or a blank screen.
- [ ] A payment-required thread says so; it never shows a raw error.

## Notifications, payouts, ratings

- [ ] The bell shows unread state and opens a list with a real empty state.
- [ ] Payouts and ratings render at the phone's real text size, including the
      largest accessibility setting.

## Accessibility (new in Phase 8E)

Turn on TalkBack for this section.

- [ ] Every bottom-navigation destination can be **activated** by double-tap,
      not merely announced.
- [ ] Chat rows, notification rows, profile rows, appearance and language
      options, rating tag chips and payment-method cards all activate.
- [ ] The star rating can be changed with swipe up/down (it is a slider).
- [ ] A step indicator lets you go back to a completed step.

## Admin

- [ ] Overview, KYC, Marketplace, Disputes, Finance, Staff, Settings, System
      all load, in both light and dark.
- [ ] Commission and FX show a worked example, not a raw number.
- [ ] Provider statuses match what you wrote down at the start.

## Payment

Read the mode you recorded from **Operations → System** first.

**If a rail is TEST/SANDBOX**

- [ ] Create a checkout from the app and pay with the provider's documented
      test instrument.
- [ ] The deal moves to funded on its own, from the webhook — not from anything
      the app decided.
- [ ] Exact locations become visible to both parties only after funding.
- [ ] For Chargily, the DZD figure is a settlement of a EUR obligation at a
      frozen rate, and the EUR figure is the one that governs.
- [ ] Issue a test refund from the console (Stripe only; Chargily V2 has no
      programmatic refund and is an operator workflow).

**If a rail is LIVE**

- [ ] **STOP.** Do not create a payment. A live rail is a real charge, and
      end-to-end verification of it is a separate authorised step.

## Recording a finding

For anything that fails, capture the screen, the time, and — for a server-side
problem — the request id if the app shows one. Never paste a delivery code, a
KYC image, or a provider secret into a bug note.
