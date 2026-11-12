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

# chat (Django owns persistence; Go chat-service relays this to live sockets)
CHAT_MESSAGE_NEW = "chat.message.new"
