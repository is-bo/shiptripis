# KYC gating — design

**Date:** 2026-08-06
**Owner:** Claude A (Django + mobile)
**Status:** approved, ready for planning

## Goal

Accounts must be verified before they can transact. A sender verifies before
posting a request or applying to a trip; a traveler verifies before creating a
trip or applying to a parcel. Creating a trip additionally requires uploading
the flight ticket, and the trip stays hidden from senders until an operator
approves it.

Browsing, searching and viewing stay open to everyone — the gate is on
*posting and applying*, not on looking. An unverified user can see the
marketplace, which is what motivates them to verify.

This spec covers the **app only** (Django + Flutter). The admin dashboard is a
separate follow-up; until it exists, operators approve through the existing
Django admin, which already has working approve/reject actions.

## Decisions

| Question | Decision |
| --- | --- |
| What can a user do while their submission is pending? | **Nothing gated.** Hard block until approved. |
| Is a new trip live immediately? | **No.** Hidden from senders until the ticket is approved. |
| Ticket format | **Required**, image or PDF. |
| Rejected users | May resubmit, and must be shown the reason. |
| Existing ACTIVE trips | **Grandfathered** — stay live. Only new trips enter review. |
| Existing users | **Not** auto-verified. Everyone verifies before their next gated action. |
| Test accounts | Approved through the real Django admin path. No dev bypass command. |

Hard blocking is the strictest option and was chosen deliberately. It makes
two things load-bearing that are optional under a softer policy: the app must
be able to tell "in review" from "never submitted", and approval must reach
the user without a restart. Both are addressed below.

## Current state

Verified by exploration on 2026-08-06:

- `User.is_kyc_verified` (`apps/accounts/models.py:28`) is a plain boolean.
  `MeSerializer` (`apps/accounts/serializers.py:92`) exposes only that boolean.
- `KycSubmission` (`apps/kyc/models.py`, table `kyc_submission`) already has
  `status` (pending/approved/rejected/expired), `rejection_reason`,
  `reviewed_by_id`, `reviewed_at`, and a unique partial index allowing one
  approved submission per user per document type.
- The mobile wizard exists at route `/kyc`
  (`mobile/lib/features/kyc/kyc_screen.dart`) and submits to `POST /kyc/submit`.
  There is **no entry point to it** from anywhere in the UI.
- `TripMedia` (`apps/trips/models.py:142`) exists with `kind` defaulting to
  `"ticket"`, and `POST /api/trips/<id>/media`
  (`apps/trips/views.py:187`) already uploads and stores it.
- Trip search filters to `status=ACTIVE` (`apps/trips/views.py:122`).
- No custom DRF permission classes exist anywhere in the repo yet.
- `KYC_STATUS_CHANGED = "kyc.status_changed"` is declared in
  `apps/core/channels.py:36` but **never published**.

## Problem 1 — the app cannot see KYC status

`/api/me` returns a boolean, so a user who submitted yesterday is
indistinguishable from one who never started. Under a hard block the app would
show "Verify now" to someone already waiting, and they would re-upload
repeatedly to no effect.

Compounding it: **approval currently notifies nobody.** The admin approve
action (`apps/kyc/admin.py:43`) uses a bulk `.update()`, which bypasses Django
signals, and publishes nothing. An approved user's app has no way to learn it
was approved.

### Fix 1a — expose a derived status

Add `kyc_status` to `MeSerializer`, computed from the user's most recent
`KycSubmission`:

| Value | Meaning |
| --- | --- |
| `verified` | `is_kyc_verified` is true |
| `pending` | latest submission is `pending` |
| `rejected` | latest submission is `rejected` (send `kyc_rejection_reason` too) |
| `unverified` | no submission, or latest is `expired` |

`is_kyc_verified` remains the authority for *access* — `kyc_status` only drives
what the UI says. Keeping the boolean as the gate avoids two sources of truth.
No schema change; it is a serializer-level derivation.

### Fix 1b — publish on approve/reject

Replace the admin's bulk `.update()` with per-row saves so
`redis_bus.publish_after_commit(channels.KYC_STATUS_CHANGED, ...)` fires (G6),
targeted at the affected user. Payload: `{user_id, status, reason}`.

The Go notification service forwards any declared channel's payload raw
(confirmed in `internal/notification/dispatcher.go`), and the mobile
`live_event_router.dart` already handles `kyc.status_changed`. So the gate
flips live while the app is open — no restart, no polling.

## Problem 2 — nothing enforces verification

### Server (the real gate)

New `apps/core/permissions.py` — establishing a convention that does not exist
yet — with `IsKycVerified`, returning **403 with a machine-readable code**:

```json
{"detail": "Verify your identity to continue.",
 "code": "kyc_required",
 "kyc_status": "pending"}
```

The client keys off `code`, never the prose. Matching on English would break
the first time copy changes.

Applied to five endpoints (delivery and product are separate views):

| Action | View |
| --- | --- |
| Post delivery request | `apps/parcels/views.py:176` |
| Post product request | `apps/parcels/views.py:218` |
| Traveler creates a trip | `apps/trips/views.py:52` |
| Traveler applies to a parcel | `apps/matching/views.py:140` |
| Sender applies to a trip | `apps/matching/views.py:254` |

### Mobile (avoiding dead ends)

A `kycGateProvider` exposing the derived status, plus a
`requireKyc(context, ref)` helper called before each gated action:

- `verified` → proceed.
- `unverified` → route to `/kyc`.
- `pending` → show an "In review" sheet, **not** the wizard. Re-uploading
  achieves nothing and the user must not be invited to try.
- `rejected` → show the reason, then offer the wizard again.

The Dio interceptor also handles `code == "kyc_required"` centrally as a
backstop, so any call site missed degrades to a correct message rather than a
silent failure.

## Problem 3 — trips must wait for ticket review

Add `Trip.Status.PENDING_REVIEW`. New trips are created in it instead of
`ACTIVE`.

`DRAFT` already exists and is currently treated as bookable by
`TravelerApplyView`. It is **left alone** — nothing in the app creates a draft
trip today, so it is dead-but-harmless, and repurposing it for review would
overload one status with two meanings. `PENDING_REVIEW` is a distinct state
meaning "complete, awaiting an operator". If `DRAFT` is ever used for real
(save-and-finish-later), it will need its own decision then.

Sender search already filters to `ACTIVE` (`apps/trips/views.py:122`), so
pending trips vanish from search with **no change to search code**. Three
places do need changing:

1. `TravelerApplyView` accepts `DRAFT` or `ACTIVE`; it must reject
   `PENDING_REVIEW`, or a traveler could apply using an unapproved flight.
2. `SenderApplyView` likewise, so a sender cannot apply *to* a pending trip.
3. The traveler's own trip list must still show the trip, badged **"In
   review"**, so they aren't left wondering where their flight went.

The existing approve path only handles KYC. Approving a *trip* is an operator
action on `Trip.status` (`PENDING_REVIEW` → `ACTIVE`), available in Django
admin now and in the dashboard later.

### Ticket upload

Required to create a trip; image or PDF. `apps/core/storage.py` accepts only
`image/jpeg|png|webp` today, so `application/pdf` must be added to
`_EXT_BY_CT`. The 10 MiB cap stays.

Trip creation and ticket upload are **separate endpoints**, so a trip created
without a ticket would sit in `PENDING_REVIEW` forever with nothing to review.
The mobile flow therefore uploads the ticket immediately after creating the
trip and, if that upload fails, tells the traveler the trip is incomplete and
offers a retry rather than leaving it stranded.

## Migration of existing data

- **Trips:** the new status is additive. Existing `ACTIVE` trips are
  untouched and stay live (grandfathered). Only trips created after the change
  enter review. No data migration.
- **Users:** nobody is auto-verified. Existing accounts — including test
  accounts — must verify before their next gated action. This is deliberate:
  the gate gets exercised against the accounts actually used day to day.
- Both migrations must be reversible (`migrate` down and back up cleanly).

## Error handling

| Situation | Behaviour |
| --- | --- |
| Approval never comes | "In review" screen states review is manual. Not a bug. |
| User rejected | Reason shown; resubmission allowed. |
| Approved while app is open | `kyc.status_changed` flips the gate live. |
| Ticket upload fails after trip created | Trip flagged incomplete, retry offered. |
| Unverified user calls the API directly | 403 `kyc_required` from the permission class. |

## Testing

Django:
- Per gated endpoint: 403 + `kyc_required` when unverified **and** when
  pending; 201 when verified. Pending is the case a boolean-only check would
  wrongly admit, so it is asserted explicitly.
- A `PENDING_REVIEW` trip is absent from search and cannot be applied to from
  either side.
- Approving a submission publishes `kyc.status_changed` and flips
  `is_kyc_verified`.
- Rejecting records the reason and does **not** flip the boolean.
- Ticket upload accepts PDF and rejects a disallowed type.

Flutter:
- `requireKyc` covers all four branches (verified / unverified / pending /
  rejected).
- `flutter analyze` stays at 0 errors, 0 warnings; the info-lint count does not
  regress.

Verification is through the gateway (Caddy/ngrok), not just unit tests — green
tests and healthy containers have twice hidden real breakage on this project.

## Out of scope

- The admin dashboard (next session).
- Automated / third-party identity checks. Review stays manual.
- Re-verification expiry, though `KycSubmission.expires_at` exists for it.
- Any change to the KYC wizard's capture flow, which works.
