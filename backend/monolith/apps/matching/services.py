"""Reusable matching-domain rules shared across views + apps.

`chat_eligibility` is the single source of truth for "may these two parties
message each other on this match". Both `MatchChatEligibilityView` (the
pre-flight the mobile client + Go chat-service call) and the chat send view
gate on it, so the rule can never drift between the check and the write.

Two eras of match coexist here and they are gated differently:

* **V1** matches carry a `journey_id` and settle through `apps.deals` +
  `apps.finance`. Chat opens once the Deal is funded, per SHIPTRIP_V1_SPEC
  §24, and closes to new messages once the Deal reaches a terminal state.
* **Legacy** matches predate the Deal model and settle through the retired
  `apps.payments.PaymentIntent`. Their rule is unchanged so historical threads
  behave exactly as they did.
"""

from __future__ import annotations

from apps.parcels.models import ParcelRequest

from .models import Match, Offer

# Stable reason codes — surfaced verbatim to callers (mobile + Go relay).
REASON_OK = "ok"
REASON_NOT_A_PARTY = "not_a_party"
REASON_NO_ACCEPTED_OFFER = "no_accepted_offer"
REASON_PAYMENT_PENDING = "payment_pending"
REASON_MATCH_CLOSED = "match_closed"
REASON_V1_PAYMENT_UNAVAILABLE = "v1_payment_unavailable"
REASON_PRODUCT_RETIRED = "product_request_retired"

#: Deal states in which the conversation becomes read-only. History survives —
#: the client can still open and page the thread — but no new message is
#: accepted. `DISPUTED` is deliberately absent: while a dispute is open the two
#: parties often still need to arrange a return, and cutting the channel at
#: that moment pushes the coordination somewhere ShipTrip cannot evidence.
_CLOSED_DEAL_STATUSES = frozenset(
    {
        "completed",
        "cancelled",
        "expired",
        "refunded",
        "partially_refunded",
    }
)


def is_party(match: Match, user_id: int) -> bool:
    return user_id in (match.sender_id, match.traveler_id)


def chat_eligibility(match: Match, user_id: int) -> tuple[bool, str]:
    """Return (eligible, reason) for whether `user_id` may SEND on `match`.

    Chat is gated on money having actually moved: no funded obligation, no
    chat. That protects both parties from a pre-payment harassment funnel and
    enforces that counterparty contact details flow only once both sides have
    committed.
    """
    if not is_party(match, user_id):
        return False, REASON_NOT_A_PARTY

    if match.parcel.kind == ParcelRequest.Kind.PRODUCT:
        return False, REASON_PRODUCT_RETIRED

    if match.journey_id is not None:
        return _v1_chat_eligibility(match)

    return _legacy_chat_eligibility(match)


def _v1_chat_eligibility(match: Match) -> tuple[bool, str]:
    """V1: the Deal is the authority.

    `funded_at` — not `status` — is what says the money arrived. Status moves
    on past FUNDED as the parcel travels, so testing it for equality would
    close the thread the moment the traveler confirmed pickup.
    """
    # Lazy import: deals depends on matching, not the other way round.
    from apps.deals.models import Deal

    deal = (
        Deal.objects.filter(match_id=match.id)
        .only("id", "status", "funded_at")
        .first()
    )
    if deal is None:
        # An accepted offer creates the Deal in the same transaction, so no
        # Deal means no acceptance yet.
        return False, REASON_NO_ACCEPTED_OFFER
    if deal.funded_at is None:
        return False, REASON_PAYMENT_PENDING
    if deal.status in _CLOSED_DEAL_STATUSES:
        return False, REASON_MATCH_CLOSED
    return True, REASON_OK


def _legacy_chat_eligibility(match: Match) -> tuple[bool, str]:
    """Pre-Deal matches, gated on the retired PaymentIntent. Unchanged."""
    if match.status in (Match.Status.CANCELLED, Match.Status.EXPIRED):
        return False, REASON_MATCH_CLOSED

    accepted = (
        Offer.objects.filter(match_id=match.id, status=Offer.Status.ACCEPTED)
        .only("id")
        .first()
    )
    if accepted is None:
        return False, REASON_NO_ACCEPTED_OFFER

    # Lazy import: payments depends on matching, not vice versa.
    from apps.payments.models import PaymentIntent

    paid = PaymentIntent.objects.filter(
        offer_id=accepted.id, status=PaymentIntent.Status.SUCCEEDED
    ).exists()
    if not paid:
        return False, REASON_PAYMENT_PENDING

    return True, REASON_OK


def chat_history_visible(match: Match, user_id: int) -> tuple[bool, str]:
    """Whether `user_id` may READ this thread.

    Broader than :func:`chat_eligibility` on purpose. Once a conversation has
    legitimately existed it stays readable to its parties, because a closed or
    disputed delivery is exactly when someone needs to look back at what was
    agreed. Sending is still governed by `chat_eligibility`.
    """
    if not is_party(match, user_id):
        return False, REASON_NOT_A_PARTY

    if match.parcel.kind == ParcelRequest.Kind.PRODUCT:
        return False, REASON_PRODUCT_RETIRED

    if match.journey_id is None:
        # Legacy: readable if money ever moved, regardless of closure.
        accepted = (
            Offer.objects.filter(match_id=match.id, status=Offer.Status.ACCEPTED)
            .only("id")
            .first()
        )
        if accepted is None:
            return False, REASON_NO_ACCEPTED_OFFER

        from apps.payments.models import PaymentIntent

        paid = PaymentIntent.objects.filter(
            offer_id=accepted.id, status=PaymentIntent.Status.SUCCEEDED
        ).exists()
        return (True, REASON_OK) if paid else (False, REASON_PAYMENT_PENDING)

    from apps.deals.models import Deal

    funded = Deal.objects.filter(
        match_id=match.id, funded_at__isnull=False
    ).exists()
    return (True, REASON_OK) if funded else (False, REASON_PAYMENT_PENDING)
