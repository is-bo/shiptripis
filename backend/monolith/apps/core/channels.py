"""Canonical Redis pub/sub channel names.

Centralized so Django publishers and Go consumers share one vocabulary.
Format: `<domain>.<event>` — lowercased dotted, no colons (colons are
reserved for Redis key namespaces like `presence:<uid>` and
`delivered:<event_id>`).
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
OFFER_CREATED = "offer.created"
OFFER_UPDATED = "offer.updated"  # countered / accepted / declined
OFFER_ACCEPTED = "offer.accepted"

# payments / wallet
PAYMENT_CAPTURED = "payment.captured"
PAYMENT_REFUNDED = "payment.refunded"

# verification (handover)
HANDOVER_CONFIRMED = "handover.confirmed"

# kyc (Go owns the API, Django reflects status updates)
KYC_STATUS_CHANGED = "kyc.status_changed"
