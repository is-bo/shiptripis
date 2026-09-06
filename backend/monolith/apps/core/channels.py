"""Canonical Redis pub/sub channel names.

Centralized so Django publishers and Go consumers share one vocabulary.
Format: `<domain>.<event>` — lowercased dotted, no colons (colons are
reserved for Redis key namespaces like `presence:<uid>` and
`delivered:<event_id>:<user_id>`).
"""

from __future__ import annotations

# trips/parcels
TRIP_CREATED = "trip.created"
TRIP_UPDATED = "trip.updated"
TRIP_CANCELLED = "trip.cancelled"

PARCEL_CREATED = "parcel.created"
PARCEL_CANCELLED = "parcel.cancelled"

# matching
MATCH_CREATED = "match.created"
MATCH_IN_TRANSIT = "match.in_transit"
MATCH_COMPLETED = "match.completed"
OFFER_CREATED = "offer.created"
OFFER_UPDATED = "offer.updated"  # countered / accepted / declined
OFFER_ACCEPTED = "offer.accepted"

# payments / wallet
PAYMENT_CAPTURED = "payment.captured"
PAYMENT_REFUNDED = "payment.refunded"
#: A checkout attempt ended without money. Distinct from `payment.captured` on
#: purpose: a client that sees `payment.captured` may legitimately render
#: success, so a failure must never travel on that channel.
PAYMENT_FAILED = "payment.failed"

# verification (handover)
HANDOVER_CONFIRMED = "handover.confirmed"
HANDOVER_CODE_ISSUED = "handover.code_issued"
HANDOVER_DELIVERY_CODE_AVAILABLE = "handover.delivery_code_available"
HANDOVER_DELIVERY_CONFIRMED = "handover.delivery_confirmed"

# kyc (Go owns the API, Django reflects status updates)
KYC_STATUS_CHANGED = "kyc.status_changed"
FLIGHT_PROOF_STATUS_CHANGED = "flight_proof.status_changed"

# funded-delivery lifecycle
DEAL_CANCELLED = "deal.cancelled"
# Neutral in-app refresh; deliberately ineligible for FCM display.
DEAL_UPDATED = "deal.updated"
DISPUTE_OPENED = "dispute.opened"
DISPUTE_RESOLVED = "dispute.resolved"
PAYOUT_STATUS_CHANGED = "payout.status_changed"

# chat (Django owns persistence; Go chat-service relays this to live sockets)
CHAT_MESSAGE_NEW = "chat.message.new"
