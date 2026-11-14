"""Canonical Redis pub/sub channel names.

Centralized so Django publishers and Go consumers share one vocabulary.
Format: `<domain>.<event>` — lowercased dotted, no colons (colons are
reserved for Redis key namespaces like `presence:<uid>` and
`delivered:<event_id>:<user_id>`).
"""

from __future__ import annotations

# parcels
PARCEL_CREATED = "parcel.created"
PARCEL_CANCELLED = "parcel.cancelled"

# matching
MATCH_IN_TRANSIT = "match.in_transit"
MATCH_COMPLETED = "match.completed"
OFFER_CREATED = "offer.created"
OFFER_UPDATED = "offer.updated"  # countered / accepted / declined
OFFER_ACCEPTED = "offer.accepted"
#: J6.2. The sender changed their Boost under a pending offer, so the offer's
#: provisional totals moved. A neutral refresh hint carrying identifiers only --
#: never an amount -- so the client re-reads the offer from the API that owns
#: the figures. Resolved on arrival and deliberately ineligible for FCM display:
#: it moves no badge and wakes no phone.
OFFER_ECONOMICS_CHANGED = "offer.economics_changed"
#: L12A. A pending proposal's response deadline is near; sent once to the
#: person who must answer it. Carries the match and offer ids and the tracking
#: number, never an amount or a time. An expiry travels on `offer.updated`
#: with `status: "expired"`, to both people.
OFFER_RESPONSE_REMINDER = "offer.response_reminder"

# payments / wallet
PAYMENT_CAPTURED = "payment.captured"
PAYMENT_REFUNDED = "payment.refunded"
#: A checkout attempt ended without money. Distinct from `payment.captured` on
#: purpose: a client that sees `payment.captured` may legitimately render
#: success, so a failure must never travel on that channel.
PAYMENT_FAILED = "payment.failed"

# verification (handover)
HANDOVER_DELIVERY_CODE_AVAILABLE = "handover.delivery_code_available"
HANDOVER_DELIVERY_CONFIRMED = "handover.delivery_confirmed"

# kyc (Go owns the API, Django reflects status updates)
KYC_STATUS_CHANGED = "kyc.status_changed"
#: A flight or sea leg's ticket proof was reviewed (L3A; was
#: `flight_proof.status_changed`). Carries the leg's mode so copy can name it.
LEG_PROOF_STATUS_CHANGED = "leg_proof.status_changed"

# funded-delivery lifecycle
DEAL_CANCELLED = "deal.cancelled"
# Neutral in-app refresh; deliberately ineligible for FCM display.
DEAL_UPDATED = "deal.updated"
#: Phase I1A journey timing. Three distinct facts, three channels: a client
#: that sees `deal.arrival_confirmed` may legitimately render "the traveler is
#: here", and that must never travel on a channel a mere report also uses.
DEAL_ARRIVAL_REPORTED = "deal.arrival_reported"
DEAL_ARRIVAL_CONFIRMED = "deal.arrival_confirmed"
DEAL_ARRIVAL_DECLINED = "deal.arrival_declined"
#: L5A. The traveler reported progress on a leg carrying the sender's parcel
#: ("departed", "arrived", "at the port"). A statement by the traveler: it
#: moves no deal status. Carries deal ids and the report kind, nothing else.
DEAL_PROGRESS_REPORTED = "deal.progress_reported"
#: L9A. A party reported a problem with the parcel; sent to the other party.
#: Carries deal ids, the problem id and kind and the tracking number. A report
#: moves no deal status.
DEAL_PROBLEM_REPORTED = "deal.problem_reported"
DISPUTE_OPENED = "dispute.opened"
DISPUTE_RESOLVED = "dispute.resolved"
PAYOUT_STATUS_CHANGED = "payout.status_changed"

# discovery (L2A). Marketplace-class pushes: both honour `marketplace_enabled`
# and carry identifiers only, so a lock screen never shows a route or a name.
#: A route alert's watched route has a new trip or request. Carries
#: `alert_id` and one of `journey_id` / `request_id`.
DISCOVERY_ROUTE_ALERT = "discovery.route_alert"
#: "I can carry this": a traveler says one of their journeys fits the
#: sender's request. Carries `request_id` and `journey_id`, never a price.
DISCOVERY_TRAVELER_INTERESTED = "discovery.traveler_interested"
#: L12A trip-fit alert: a newly open request really fits one of the
#: traveler's published trips (spec 17.2). Carries `request_id` and
#: `journey_id` only: no place, no price, no person.
DISCOVERY_REQUEST_FITS_TRIP = "discovery.request_fits_trip"

# journey progress (L5A)
#: "Did you depart from {city}?": asked of the traveler when a leg that carries
#: a funded parcel passes its planned time with no report. Carries ids and the
#: report kind asked about, never a city, a schedule or a parcel.
JOURNEY_LEG_REMINDER = "journey.leg_reminder"

# journey schedule changes (L9A). Each carries the journey and change ids;
# those sent to a sender also carry their deal ids and tracking number. Never a
# time, a place or the traveler's reason, so nothing reaches a lock screen.
#: New times need this sender's answer (accept or decline).
JOURNEY_SCHEDULE_CHANGE_PROPOSED = "journey.schedule_change_proposed"
#: A sender accepted or declined; sent to the traveler.
JOURNEY_SCHEDULE_CHANGE_ANSWERED = "journey.schedule_change_answered"
#: The new times are in force; sent to every affected sender and the traveler.
JOURNEY_SCHEDULE_CHANGE_APPLIED = "journey.schedule_change_applied"
#: The traveler withdrew the change, or it no longer fit the trip.
JOURNEY_SCHEDULE_CHANGE_WITHDRAWN = "journey.schedule_change_withdrawn"

# chat (Django owns persistence; Go chat-service relays this to live sockets)
CHAT_MESSAGE_NEW = "chat.message.new"
