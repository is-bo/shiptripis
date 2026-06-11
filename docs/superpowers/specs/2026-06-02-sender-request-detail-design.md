# Sender Request Detail — Design

Date: 2026-06-02
Owner: Claude A (Islam scope — Django + mobile)

## Problem

Sender "My Requests" doubles as a discovery surface (it offers a "Find travelers" CTA per posted parcel) and a status list, but it isn't a real management hub. Concrete user pain:

- Sender cannot find the **delivery code** anywhere obvious. The pickup code surfaces once via inbox banner but there's no persistent home for either code.
- "Find travelers" appears inside requests that already have a matched traveler — confusing because the matching decision is already made.
- No way to message the traveler, see their KYC status, or cancel the request from this screen.

Goal: a per-request page reached from My Requests, scaled like top-tier delivery apps, that consolidates everything about ONE request: status, codes, parcel info, the traveler, chat, and cancel.

## Out of scope

- Real chat (Django chat_message schema + Go publisher not yet wired) — stubbed.
- Cancel after payment (V1 has no dispute UI) — pre-payment only.
- Rating / dispute — V2.

## State machine (drives the layout)

A single `RequestDetailScreen` renders ordered sections that appear/disappear based on the request's derived state:

| Derived state | Trigger | Sections shown (top → bottom) |
|---|---|---|
| OPEN | `parcel.status == open` and no `accepted`/`in_transit`/`delivered` match | Header · Waiting card · Offers (if any pending) · Parcel info · Cancel |
| AWAITING PAYMENT | accepted match with no `acceptedOffer.paid_at` | Header · Pay CTA · Traveler card · Parcel info · Cancel (warns) |
| READY FOR PICKUP | accepted + paid, not yet in_transit | Header · **Pickup code card** · Traveler card · Parcel info · Help |
| ON THE ROAD | match `in_transit` | Header · Follow package · **Delivery code card** · Traveler card |
| DELIVERED | match `delivered` or `completed` | Header · Delivered hero · Receipt · Traveler card |
| CANCELLED | parcel cancelled or terminal cancelled match | Header · Cancelled banner · Parcel info |

## Sections in detail

### Header (every state)
Status chip (Live / Offer pending / Accepted / In transit / Delivered / Cancelled), route badge (`ALG → CDG`), parcel summary line: weight · kind · pickup window.

### Waiting card (OPEN, no offers yet)
"Waiting for travelers to apply." subtle pulse animation. Avoids feeling dead.

### Offers (OPEN with pending offers)
List of `MatchSummary` rows where `m.status == pending` and `m.latestOffer != null`. Each row:
- Traveler avatar + name + KYC badge if verified
- Trip route + date
- Latest offer total (DZD)
- "Review" → existing `/match/<id>`

### Pay CTA (AWAITING PAYMENT)
Big primary button: "Pay XXXX DZD to confirm" → `/payment/<offerId>?match=<matchId>`.

### Pickup code card (READY FOR PICKUP)
Big sun-yellow card with copy button. Reads from `GET /api/matches/<id>/handover/code?kind=pickup`. Subtitle: "Show this to the traveler at pickup."

### Follow package (ON THE ROAD)
Tile linking to `/tracking/<matchId>`.

### Delivery code card (ON THE ROAD)
Big emerald card with copy button. Reads from `GET /api/matches/<id>/handover/code?kind=delivery`. Subtitle: "Show this when the traveler delivers."

**Server requirement:** the DELIVERY code must already exist by the time match is `in_transit`. Today the verification module auto-issues PICKUP on payment; we need to **auto-issue DELIVERY when match transitions to in_transit** (`_advance_match_to_in_transit` in `apps/verification/services.py`). Single line addition: call `issue_code(match, kind=DELIVERY, issued_to=match.sender)` inside the same transaction.

### Traveler card
Avatar (initials fallback), name, KYC-verified badge, trip route + date, **Message** button → `/chat/<matchId>` (stub), tap card → `/match/<matchId>`.

### Chat stub (`/chat/<matchId>`)
NOT a fake chat. Placeholder screen with traveler info + "Call ${phone}" + "Contact support" fallback actions + one line: "Direct chat is coming soon."

### Cancel
- Footer button, low emphasis. Hidden once any match has `acceptedOffer.paid_at != null`.
- Confirm dialog: "Cancel this request? Any pending offers will be voided."
- Calls existing `DELETE /api/parcels/<id>`.
- On success: pop, list updates with greyed-out cancelled chip.

## My Requests list — changes

Cards become summary-only: route + status chip + sub-line + chevron. **No** inline action button, **no** inline code banner, **no** "Find travelers". Tap → `/sender/requests/<parcelId>`. Empty state unchanged.

## Routing

- New: `/sender/requests/:parcelId` → `RequestDetailScreen(parcelId: int)`
- New: `/chat/:matchId` → `ChatStubScreen(matchId: int)` (or update existing chat_list to redirect for now)

## Data providers (mobile)

- New `parcelByIdProvider(int parcelId)` — fetches `/api/parcels/<id>` and reuses `Parcel.fromJson`.
- Reuse `matchListProvider(role: 'sender')` filtered locally to `m.parcelId == parcelId`.
- Existing live event ticks already invalidate these.
- Existing `verificationRepositoryProvider.getActiveCode(matchId, kind)` used for both code cards.

## Files touched

**Backend (Django, small):**
- `apps/verification/services.py` — auto-issue DELIVERY on `_advance_match_to_in_transit`.
- `apps/verification/tests/test_handover.py` — assert DELIVERY code exists after pickup verify.

**Mobile (the bulk):**
- NEW `mobile/lib/features/sender/request_detail_screen.dart`
- NEW `mobile/lib/features/chat/chat_stub_screen.dart`
- EDIT `mobile/lib/features/sender/my_requests_screen.dart` — strip find-travelers and inline CTAs; pure list+chevron.
- EDIT `mobile/lib/core/router/app_router.dart` — register both routes.
- EDIT `mobile/lib/core/parcels/parcels_providers.dart` — add `parcelByIdProvider`.
- EDIT `mobile/lib/core/parcels/parcels_repository.dart` — add `getById(int)` method (if not present).

## Acceptance

1. `apps/verification.tests` green, including the new "DELIVERY auto-issued on in_transit" test.
2. `flutter analyze` clean.
3. UX walkthrough (manual):
   - Post a parcel → My Requests shows summary card with "Live" chip → tap → OPEN state with parcel info + Cancel.
   - Cancel → confirm → row chip becomes Cancelled.
   - Post again, traveler offers → My Requests shows "1 new offer" sub-line → tap → Offers section lists the offer.
   - Sender accepts → state flips to AWAITING PAYMENT → Pay CTA visible.
   - Sender pays → state flips to READY FOR PICKUP → pickup code card visible with copy button.
   - Traveler enters pickup code → sender's screen flips to ON THE ROAD → delivery code visible.
   - Sender taps Message → chat stub screen with traveler name + "Coming soon".
4. No "Find travelers" surface anywhere in My Requests or the detail page.
