"""Is this Deal still an active shipment? One answer, decided by the server.

The bug this module exists for: a delivered Deal kept appearing under the
sender's active "Sending" list, because the only thing the client had to go on
was `Deal.status`, and `delivery_confirmed` / `protection_window` are not in any
list of finished statuses. They are not finished *contractually* -- the money is
still protected and a dispute is still possible -- but the shipment is over. The
parcel is with the recipient. Nothing about it is in flight.

So the classification is three buckets, and the server owns them:

``active``
    The shipment is live. Somebody still has something to do about moving this
    parcel: fund it, hand it over, carry it, deliver it. `payment_failed` is
    deliberately here, because it means the sender must retry.

``completed``
    The parcel reached its destination. Protection, disputes and payout all
    continue inside this bucket -- they are *post-delivery* states, and the app
    surfaces them in the delivery/payout experience, not by keeping a finished
    shipment on the active list. Nothing is hidden: a Deal whose payout is still
    processing is still readable, still carries its full payout projection, and
    is still where the traveler goes to watch their money.

``cancelled``
    The delivery did not happen, or its money went back. A refund outranks the
    delivery fact: if the sender has been refunded, the platform did not deliver
    this parcel for them, whatever the handover log says.

`delivery_confirmed_at` -- not the status column -- decides between active and
completed, because `disputed` overwrites the status and a dispute can be opened
either side of a delivery. The timestamp cannot be ambiguous.
"""

from __future__ import annotations

from django.db.models import Q

from .models import Deal

ACTIVE = "active"
COMPLETED = "completed"
CANCELLED = "cancelled"

ACTIVITY_STATES = (ACTIVE, COMPLETED, CANCELLED)

#: Terminal statuses that mean the delivery did not happen or was unwound.
CANCELLED_STATUSES = (
    Deal.Status.CANCELLED,
    Deal.Status.EXPIRED,
    Deal.Status.REFUNDED,
    Deal.Status.PARTIALLY_REFUNDED,
)

#: Statuses that are unambiguously post-delivery. `completed` is included for
#: the one path that reaches it without a delivery confirmation: a dispute
#: resolved in the traveler's favour, where the platform has ruled that they
#: performed.
COMPLETED_STATUSES = (
    Deal.Status.DELIVERY_CONFIRMED,
    Deal.Status.PROTECTION_WINDOW,
    Deal.Status.COMPLETED,
)


def activity_state(deal: Deal) -> str:
    """The bucket one Deal belongs in. Pure; adds no query."""

    if deal.status in CANCELLED_STATUSES:
        return CANCELLED
    if deal.status in COMPLETED_STATUSES or deal.delivery_confirmed_at is not None:
        return COMPLETED
    return ACTIVE


def activity_q(state: str) -> Q:
    """The same rule as a database predicate, for the list endpoint.

    Written as one expression rather than three, so the SQL and
    `activity_state` cannot drift into disagreeing about a Deal.
    """

    if state not in ACTIVITY_STATES:
        raise ValueError(f"Unknown Deal activity state {state!r}.")
    cancelled = Q(status__in=CANCELLED_STATUSES)
    completed = ~cancelled & (
        Q(status__in=COMPLETED_STATUSES) | Q(delivery_confirmed_at__isnull=False)
    )
    if state == CANCELLED:
        return cancelled
    if state == COMPLETED:
        return completed
    return ~cancelled & ~completed
