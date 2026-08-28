"""The per-viewer projection of a Deal's immutable timeline.

`DealEvent` is written for the platform: it is the audit record a dispute is
resolved from, and it keeps every id and amount a later investigation needs. It
is also read by both parties through the Deal API, and those two audiences are
not the same audience.

The projection is an **allowlist of payload keys**, not a denylist of dangerous
ones. That direction matters more than it looks. A denylist protects only the
leaks somebody already thought of; an allowlist means a payload key added by a
future transition is invisible to a party until someone deliberately adds it
here. The same reasoning produced `apps.matching.public_contract`, and Phase 2B
found real leaks the other way round.

Nothing in a `DealEvent` payload is supposed to be secret in the first place --
`apps.deals.lifecycle.record_event` documents that rule and the services obey
it. This module is the second wall, for the day one of them stops obeying it.

Staff see the stored payload unchanged. That is deliberate: the audit record has
to be complete for the people resolving disputes, and admin access is itself an
audited, permission-gated surface.
"""

from __future__ import annotations

from .models import DealEvent

#: Payload keys a Deal party may see. Everything else is dropped.
#:
#: Grouped by what they describe. Every entry is either an identifier, an
#: integer amount in EUR cents, a status token, an ISO instant or a boolean --
#: never free text a service might have filled from user input, and never
#: anything derived from code material.
PARTY_VISIBLE_PAYLOAD_KEYS = frozenset(
    {
        # transitions
        "status",
        "previous_status",
        "reason",
        "changed",
        # handover
        "code_id",
        "superseded_code_id",
        "rotation",
        "permanent",
        "locked_until",
        "lockout_count",
        "pickup_confirmed_at",
        "delivery_code_available_at",
        "buffer_seconds",
        "released_at",
        "delivery_confirmed_at",
        "message_id",
        # protection and payout
        "protection_ends_at",
        "protection_window_seconds",
        "payout_id",
        "amount_eur_cents",
        # disputes
        "dispute_id",
        "resolution",
        "evidence_id",
        "evidence_kind",
        # money settlements
        "collected_eur_cents",
        "sender_refund_eur_cents",
        "traveler_payout_eur_cents",
        "platform_fee_eur_cents",
        "traveler_compensation_eur_cents",
        "payment_order_id",
        "basis",
        # cancellation and no-show
        "actor_role",
        "is_late",
        "cutoff_at",
        "agreed_pickup_at",
        "allowed",
        "refusal_code",
        "party",
        "refund_sender",
        # capacity
        "allocation_ids",
        # ratings
        "rating_id",
        "rater_role",
        # recipient (metadata only -- never a name, an email or a phone number)
        "revision",
    }
)

#: Event kinds a party never sees. Kept short on purpose: a party is entitled to
#: know what happened to their own delivery, and hiding transitions from them
#: makes the app harder to trust, not safer. Only the two purely operational
#: kinds are withheld.
STAFF_ONLY_EVENT_KINDS = frozenset(
    {
        DealEvent.Kind.RECIPIENT_NOTIFICATION_SENT,
    }
)


def project_payload(payload: dict | None) -> dict:
    """Narrow one stored payload to the keys a party may read."""

    if not isinstance(payload, dict):
        return {}
    return {
        key: value
        for key, value in payload.items()
        if key in PARTY_VISIBLE_PAYLOAD_KEYS
    }


def project_event(event: DealEvent, *, is_staff: bool) -> dict:
    return {
        "id": event.pk,
        "kind": event.kind,
        "actor_id": event.actor_id,
        "payload": (
            dict(event.payload or {}) if is_staff else project_payload(event.payload)
        ),
        "created_at": event.created_at,
    }


def deal_timeline(events, *, is_staff: bool = False) -> list[dict]:
    """The ordered timeline for one viewer.

    `events` is an already-fetched iterable (the Deal detail view prefetches
    them) so this stays a pure projection and adds no query of its own.
    """

    return [
        project_event(event, is_staff=is_staff)
        for event in events
        if is_staff or event.kind not in STAFF_ONLY_EVENT_KINDS
    ]
