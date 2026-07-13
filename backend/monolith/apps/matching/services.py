"""Reusable matching-domain rules shared across views + apps.

`chat_eligibility` is the single source of truth for "may these two parties
message each other on this match". Both `MatchChatEligibilityView` (the
pre-flight the mobile client + Go chat-service call) and the chat send view
gate on it, so the rule can never drift between the check and the write.
"""

from __future__ import annotations

from .models import Match, Offer

# Stable reason codes — surfaced verbatim to callers (mobile + Go relay).
REASON_OK = "ok"
REASON_NOT_A_PARTY = "not_a_party"
REASON_NO_ACCEPTED_OFFER = "no_accepted_offer"
REASON_PAYMENT_PENDING = "payment_pending"
REASON_MATCH_CLOSED = "match_closed"


def is_party(match: Match, user_id: int) -> bool:
    return user_id in (match.sender_id, match.traveler_id)


def chat_eligibility(match: Match, user_id: int) -> tuple[bool, str]:
    """Return (eligible, reason) for whether `user_id` may chat on `match`.

    Chat is gated on a succeeded payment for the match's accepted offer:
    no payment, no chat. Protects both parties (no pre-payment harassment
    funnel) and enforces that counterparty PII flows only after both have
    committed money + acceptance.
    """
    if not is_party(match, user_id):
        return False, REASON_NOT_A_PARTY

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
