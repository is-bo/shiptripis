# ShipTrip — product truth

Durable product context. `docs/SHIPTRIP_V1_SPEC.md` remains the authoritative
specification; this file is the condensed product reading that design work
depends on. Where the two disagree, the spec wins.

## What it is

A peer-to-peer parcel-delivery marketplace on the EU ↔ Algeria corridor. A
sender pays a traveler who already has spare luggage or boot capacity to carry
a parcel along a route they were taking anyway. V1 is delivery only.

## Platform

`adaptive` — one Flutter codebase shipping to Android and iOS hardware.
Material 3 governs structure and components on both; iOS additionally receives
its OS guarantees (safe-area insets, live edge-swipe back, Reduce Motion,
correct sheet dismissal). There is no web or desktop surface in V1.

## People

**Sender.** Frequently diaspora in France, Belgium or Spain sending documents,
medicine, clothes or gifts to family in Algeria. Motivated by cost and speed
against courier alternatives, and anxious about handing a valuable object to a
stranger. Often not a confident app user; often reading in French or Arabic
rather than English. Verification is email-only.

**Traveler.** Someone already flying Paris → Algiers, often continuing by road
to a wilaya like Jijel or Sétif. Motivated by covering part of the trip cost.
Must pass KYC before publishing anything matchable, and must supply flight
proof for flight legs. Drive legs need no transport proof.

**Both.** One account, one identity, two contexts. Not two apps.

**Recipient.** Never signs up. Receives the delivery code by email and hands it
to the traveler at the door.

**Guest payer.** Never signs up. Pays one obligation via one link and gains no
access to the deal, chat, or dispute.

## The two jobs

**Sender:** create a delivery request → pay a small posting deposit to publish
→ see compatible travelers → propose a reward → negotiate → pay the balance →
give the pickup code at handover → wait out the protection window → rate.

**Traveler:** pass KYC → build a journey from ordered legs → prove flight legs
→ see compatible requests → accept, decline or counter → collect with the
pickup code → deliver against the recipient's code → wait for payout → rate.

## Product truths a design cannot contradict

1. **EUR is the only marketplace currency.** DZD exists solely as what Chargily
   charges. The server computes every amount and every conversion.
2. **The sender proposes first.** There is no traveler-first offer.
3. **Capacity is per journey leg**, not per journey.
4. **Exact addresses stay hidden until the deal is funded.** Before that both
   sides see city-level information only.
5. **The traveler can never obtain the delivery code.** Not by any screen, any
   request, any cached object, any log line.
6. **The delivery code is locked for 30 minutes after pickup** — hidden from
   the sender and unsent to the recipient during that window.
7. **Payout waits 48 hours after delivery confirmation**, and any dispute
   freezes it.
8. **Boost improves visibility and funds delivery economics.** Most of the
   sender-chosen amount becomes a snapshotted Traveler bonus; the configured
   remainder is ShipTrip revenue. It can never create compatibility.
9. **Kaba / ProductRequest is not part of V1.**
10. **The backend is authoritative for every amount, deadline, permission and
    state transition.** The client renders; it does not decide.

## Content ranges the design must survive

| Thing | Min | Typical | Max |
|---|---|---|---|
| Legs in a journey | 1 | 2 | 5+ |
| Offers on a request | 0 | 1–3 | 20+ |
| Deliveries in Deliveries tab | 0 | 2–6 | 50+ |
| Parcel photos | 0 | 3 | 8 |
| Dispute evidence items | 0 | 2 | 10+ |
| Chat messages in a thread | 0 | 10–40 | 500+ |
| Reward | €7 (floor) | €15–45 | €200+ |
| Place-name length | "Sétif" | "Paris Gare du Nord" | Long Arabic wilaya + commune strings |

## States that are product behaviour, not edge cases

First run, empty, loading, offline, stale-because-the-other-side-just-acted,
payment processing, KYC rejected, flight proof rejected, capacity lost to a
race, offer expired, request expired, dispute open, payout frozen. Each of
these is something a real user hits on a normal week and each needs a real
screen with a real next action.

## Localization

French, Arabic and English are all launch languages. Arabic is genuine RTL,
not translated LTR. Money, dates, numerals and mixed Latin/Arabic strings must
all be correct. French and Arabic both expand relative to English, and the
layout must not overflow when they do.

## Non-goals for V1

Admin dashboard, landing site, provider production activation, app-store
submission, Kaba/ProductRequest, traveler-initiated offers, in-app wallet
top-ups.
