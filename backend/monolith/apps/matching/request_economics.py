"""J6.3 — a request's Boost-inclusive economics, before any Offer exists.

## Why this exists

The request pricing quote published the base economics (`chosen_economics`:
reward, commission, base sender total) and, separately, the Boost block. Nothing
on it said what the sender actually owes once they add a Boost, so the posting
screen showed "Total sender cost €37.50" for a €30.00 reward with a €5.00 Boost
whose Deal will be €43.75. The client could not fix that without adding money
up itself.

## What this publishes

`chosen_terms`: the terms a Deal at the request's chosen reward and current Boost
would freeze under the active policy -- under the same field names an Offer
(J6.1) and a Deal's `terms` already use, so one client vocabulary reads all three:

* `traveler_reward_minor`, `commission_rate_bps`, `platform_fee_minor`,
  `sender_total_minor` -- the **base** economics, same meaning as everywhere
* `boost_amount_minor`, `boost_traveler_bonus_minor`, `boost_platform_fee_minor`
* `traveler_total_minor` -- what the Traveler would be paid, Boost included
* `sender_total_with_boost_minor` -- what the sender would owe, Boost and its
  fee included
* `boost_economics_version`, `terms_status`

No arithmetic lives here. The base comes from `calculate_offer_economics` (what
an Offer freezes), the Boost from `resolve_committed_boost` (what acceptance
commits), the row from `build_terms` (what acceptance saves), and both totals
from `DealTermsSnapshot`'s own properties.

``provisional``
    A draft, or a request whose Boost the sender may still change. The figures
    are what committing right now would freeze; a later Admin revision or Boost
    edit may move them, exactly as it may move an open Offer.
``frozen``
    A committed request. Read from its Deal's immutable terms, never from the
    request columns, which funding clears.
``unavailable``
    No chosen reward yet, or a closed request with no Deal terms to report.
"""

from __future__ import annotations

from apps.deals.models import Deal, DealTermsSnapshot

from .offer_economics import (
    BOOST_TERMS_FROZEN,
    BOOST_TERMS_PROVISIONAL,
    BOOST_TERMS_UNAVAILABLE,
    build_terms,
)

REQUEST_TERMS_MONEY_FIELDS = (
    "traveler_reward_minor",
    "commission_rate_bps",
    "platform_fee_minor",
    "sender_total_minor",
    "boost_economics_version",
    "boost_amount_minor",
    "boost_traveler_bonus_minor",
    "boost_platform_fee_minor",
    "traveler_total_minor",
    "sender_total_with_boost_minor",
)

#: What a request with no retired paid package binds: nothing.
NO_PAID_BOOST = {
    "purchase_ids": [],
    "amount_eur_cents": 0,
    "traveler_boost_eur_cents": 0,
    "platform_boost_eur_cents": 0,
}

#: Deal states whose terms no longer describe anything the sender owes.
_DEAD_DEAL_STATUSES = (
    Deal.Status.CANCELLED,
    Deal.Status.EXPIRED,
    Deal.Status.PAYMENT_FAILED,
)


def project_request_terms(
    *,
    economics: dict,
    boost_intent_eur_cents: int,
    paid_boost: dict | None = None,
    policy_loader=None,
) -> DealTermsSnapshot:
    """The unsaved terms committing `economics` with this Boost would freeze.

    `economics` is a `calculate_offer_economics` result for the chosen reward.
    Raises what `resolve_committed_boost` raises when a Boost cannot be priced.
    """

    from apps.boosts.services import resolve_committed_boost  # noqa: WPS433

    boost = resolve_committed_boost(
        paid_boost=paid_boost or NO_PAID_BOOST,
        boost_intent_eur_cents=int(boost_intent_eur_cents or 0),
        policy_loader=policy_loader,
    )
    return build_terms(economics=economics, boost=boost)


def request_terms_payload(terms: DealTermsSnapshot, *, status: str) -> dict:
    return {
        "terms_status": status,
        "currency": str(terms.currency),
        "traveler_reward_minor": int(terms.traveler_reward_minor),
        "commission_rate_bps": int(terms.commission_rate_bps),
        "platform_fee_minor": int(terms.platform_fee_minor),
        "sender_total_minor": int(terms.sender_total_minor),
        # A saved row holds a plain string; an unsaved one the choice member.
        "boost_economics_version": str(terms.boost_economics_version),
        "boost_amount_minor": int(terms.boost_amount_minor),
        "boost_traveler_bonus_minor": int(terms.boost_traveler_bonus_minor),
        "boost_platform_fee_minor": int(terms.boost_platform_fee_minor),
        "traveler_total_minor": terms.traveler_total_minor,
        "sender_total_with_boost_minor": terms.sender_total_with_boost_minor,
    }


def unavailable_request_terms() -> dict:
    return {
        "terms_status": BOOST_TERMS_UNAVAILABLE,
        "currency": "EUR",
        **{field: None for field in REQUEST_TERMS_MONEY_FIELDS},
    }


def draft_request_terms(*, chosen_economics: dict | None, boost_eur_cents: int) -> dict:
    """`chosen_terms` for a request that does not exist yet."""

    if chosen_economics is None:
        return unavailable_request_terms()
    terms = project_request_terms(
        economics=chosen_economics, boost_intent_eur_cents=boost_eur_cents
    )
    return request_terms_payload(terms, status=BOOST_TERMS_PROVISIONAL)


def saved_request_terms(delivery_request, *, chosen_economics: dict | None) -> dict:
    """`chosen_terms` for a saved request, from the source that is authoritative.

    While the Boost is still the sender's to change, the figures are what
    acceptance would commit now -- including a retired paid package, exactly
    as `_accept_offer_locked` resolves it. Once committed, the Deal's frozen
    terms are the only truth; the request's own Boost column is not.
    """

    from apps.boosts.services import (  # noqa: WPS433
        EDITABLE_STATUSES,
        unbound_paid_boost_totals_by_request,
    )

    if delivery_request.status in EDITABLE_STATUSES:
        if chosen_economics is None:
            return unavailable_request_terms()
        paid = unbound_paid_boost_totals_by_request([delivery_request.pk])
        terms = project_request_terms(
            economics=chosen_economics,
            boost_intent_eur_cents=int(delivery_request.boost_eur_cents or 0),
            paid_boost=paid.get(delivery_request.pk),
        )
        return request_terms_payload(terms, status=BOOST_TERMS_PROVISIONAL)

    deal = (
        Deal.objects.filter(delivery_request_id=delivery_request.pk)
        .exclude(status__in=_DEAD_DEAL_STATUSES)
        .select_related("terms")
        .order_by("-created_at", "-pk")
        .first()
    )
    try:
        terms = deal.terms if deal is not None else None
    except DealTermsSnapshot.DoesNotExist:
        terms = None
    if (
        terms is None
        or terms.is_legacy
        or terms.currency != DealTermsSnapshot.Currency.EUR
    ):
        return unavailable_request_terms()
    return request_terms_payload(terms, status=BOOST_TERMS_FROZEN)
