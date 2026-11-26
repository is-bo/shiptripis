# N2: the bell names the ticket decision (2026-11-26)

Phone test 2, finding 1.5 of `docs/WASSLA_PHONE_TEST_2_PLAN.md`: the owner's flight ticket was approved,
but the bell row only said "Verification update", so he noticed the email and not the app. App only.
No server, staff-decision or transport change; push delivery is the separate operations task (O3).
Nothing is deployed by this change.

## What the server already publishes

`review_flight_proof` (`apps/admin_panel/services.py`) publishes `leg_proof.status_changed` to the
traveler with `proof_id`, `journey_id`, `mode` (`FLIGHT`, `DRIVE` or `SEA`), `status` (`approved` or
`rejected`) and `outcome` (`approved`, `rejected` or `resubmission_requested`). "Ask for a new upload"
stores the rejected status, so only `outcome` tells it from a rejection. The inbox row stores that
payload. The reason, the evidence and the proof's document are not in it.

## What changed

| Piece | Change |
| --- | --- |
| `mobile/lib/domain/notification.dart` | `TicketMode`, `TicketDecision`, and `AppNotification.ticketMode` / `ticketDecision`, read from `mode` and from `outcome` (else `status`). Unknown or absent gives null. Other channels always give null. |
| `mobile/lib/features/notifications/notifications_screen.dart` | The row title for `leg_proof.status_changed` comes from mode and decision, and falls back to the existing "Verification update". `kyc.status_changed` keeps that label. |
| `mobile/lib/l10n/app_{en,fr,ar}.arb` | Six strings, worded as the push copy in `apps/notifications/push.py` so the bell and the phone banner agree. Localizations regenerated. |
| `mobile/test/n2_ticket_decision_bell_test.dart` | New. |

Titles: "Flight ticket approved", "Flight ticket needs attention", "We need a new flight ticket", and the
same three for "Ferry". A drive has no ticket, so it keeps the generic label.

## Tests

- Payload reading for approved flight, rejection, new upload asked (stored as rejected), approved
  ferry, no `outcome`, drive, unknown outcome, empty payload and another channel.
- The six titles at 320 px, the fallback for three unrecognized shapes, no reason or document
  identifier on the row, a tap still opening the journey, French, and Arabic with right-to-left.

## Not covered here

One review still produces one inbox event: the publisher is unchanged and none was added. Delivery
with FCM on is accepted on a physical phone in O3.
