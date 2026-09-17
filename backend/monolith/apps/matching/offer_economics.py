"""J6.1 — an Offer's Boost economics, published before they are committed.

## Why this exists

An Offer freezes the **base** economics when it is written: the reward, its
commission, and the base sender total. The Boost is not on the Offer. It lives
on the delivery request, stays the sender's to change while the request is open,
and is priced into `DealTermsSnapshot` at acceptance and nowhere earlier. So an
Offer that only carried `traveler_reward_minor` told a Traveler with a €30 base
and a €5 Boost "you receive €30" at the exact moment they decided whether to
accept €35.

## What this publishes

The same numbers `DealTermsSnapshot` carries, under the same names, so a client
renders an Offer and the Deal it becomes with one vocabulary:

* `traveler_reward_minor` — unchanged, and still the **base** reward
* `boost_amount_minor`, `boost_traveler_bonus_minor`, `boost_platform_fee_minor`
* `traveler_total_minor` — what the Traveler is paid, Boost included
* `sender_total_with_boost_minor` — what the sender owes, Boost and its
  commission included
* `boost_economics_version`
* `boost_terms_status` — where those numbers come from:

``provisional``
    A pending offer. The request's Boost is not frozen yet, so the numbers are
    what accepting **right now** would commit. They are computed by building
    the very `DealTermsSnapshot` acceptance would write — through the same
    `resolve_committed_boost` — and reading its own properties, so no second
    economics model exists. Acceptance re-derives them under the request lock
    and refuses if the acceptor confirmed different figures.

``frozen``
    An accepted offer. Read from its Deal's immutable terms and nothing else,
    never from the request, whose Boost column funding clears and an unfunded
    release can revive.

``unavailable``
    Nothing was ever committed for this offer and it can no longer be: it was
    countered, declined, withdrawn or expired, or it is a legacy DZD offer. The
    Boost at the time was never recorded on it, so no figure is invented. Every
    projected field is null; the base fields remain.
"""

from __future__ import annotations

from apps.deals.models import Deal, DealTermsSnapshot

from .models import Match, Offer

BOOST_TERMS_PROVISIONAL = "provisional"
BOOST_TERMS_FROZEN = "frozen"
BOOST_TERMS_UNAVAILABLE = "unavailable"

PROJECTION_FIELDS = (
    "boost_terms_status",
    "boost_economics_version",
    "boost_amount_minor",
    "boost_traveler_bonus_minor",
    "boost_platform_fee_minor",
    "traveler_total_minor",
    "sender_total_with_boost_minor",
)


def commitment_terms(offer: Offer, boost) -> DealTermsSnapshot:
    """The `DealTermsSnapshot` accepting `offer` with `boost` writes. Unsaved.

    Acceptance saves exactly this row. The projection reads it and discards it.
    """

    return build_terms(
        currency=offer.currency,
        economics={
            "traveler_reward_minor": offer.traveler_reward_minor,
            "commission_rate_bps": offer.commission_rate_bps,
            "platform_fee_minor": offer.platform_fee_minor,
            "sender_total_minor": offer.sender_total_minor,
        },
        boost=boost,
        business_settings_version_id=offer.business_settings_version_id,
        pricing_version=offer.pricing_version,
        policy_snapshot=offer.terms_snapshot,
    )


def build_terms(
    *,
    economics: dict,
    boost,
    currency: str = DealTermsSnapshot.Currency.EUR,
    business_settings_version_id: int | None = None,
    pricing_version: str = "",
    policy_snapshot: dict | None = None,
) -> DealTermsSnapshot:
    """One unsaved `DealTermsSnapshot` from base economics and a resolved Boost.

    The single place a base reward and a Boost become a terms row. Acceptance,
    the Offer projection, the request pricing quote (J6.3) and the deposit
    ceiling all come through here, and every total is then read from the model's
    own `traveler_total_minor` / `sender_total_with_boost_minor` -- so there is
    one `base + Boost + Boost fee`, not one per screen.
    """

    return DealTermsSnapshot(
        currency=currency,
        traveler_reward_minor=int(economics["traveler_reward_minor"]),
        commission_rate_bps=int(economics["commission_rate_bps"]),
        platform_fee_minor=int(economics["platform_fee_minor"]),
        sender_total_minor=int(economics["sender_total_minor"]),
        boost_amount_minor=boost.amount_eur_cents,
        boost_traveler_bonus_minor=boost.traveler_bonus_eur_cents,
        boost_platform_fee_minor=boost.platform_fee_eur_cents,
        boost_economics_version=boost.economics_version,
        boost_commission_rate_bps=boost.commission_rate_bps,
        business_settings_version_id=business_settings_version_id,
        pricing_version=pricing_version,
        policy_snapshot={
            **(policy_snapshot or {}),
            "boost_economics": boost.snapshot,
        },
        is_legacy=False,
    )


def terms_projection(terms: DealTermsSnapshot, *, status: str) -> dict:
    return {
        "boost_terms_status": status,
        # A saved row holds a plain string; an unsaved one holds the choice
        # member. Both publish the same value.
        "boost_economics_version": str(terms.boost_economics_version),
        "boost_amount_minor": int(terms.boost_amount_minor),
        "boost_traveler_bonus_minor": int(terms.boost_traveler_bonus_minor),
        "boost_platform_fee_minor": int(terms.boost_platform_fee_minor),
        "traveler_total_minor": terms.traveler_total_minor,
        "sender_total_with_boost_minor": terms.sender_total_with_boost_minor,
    }


def unavailable_projection() -> dict:
    return {
        field: (BOOST_TERMS_UNAVAILABLE if field == "boost_terms_status" else None)
        for field in PROJECTION_FIELDS
    }


def _request_boost_intent(match: Match) -> int:
    parcel = match.parcel
    delivery = getattr(parcel, "deliveryrequest", None)
    return int(getattr(delivery, "boost_eur_cents", 0) or 0)


class OfferEconomicsReader:
    """Projects Offers for one response at a constant query cost.

    One reader lives in a serializer context for the whole response. The Phase 4
    policy is read at most once, and only if some pending offer has a Boost to
    price; the retired paid-package rows are read once per request, or once for
    a whole list after `prime`.
    """

    def __init__(self) -> None:
        self._policy = None
        self._paid: dict[int, dict] = {}

    def _load_policy(self):
        if self._policy is None:
            from apps.core.phase4_policy import phase4_policy  # noqa: WPS433

            self._policy = phase4_policy()
        return self._policy

    def prime(self, matches) -> None:
        """Load paid-package totals for every pending negotiation in one query."""

        from apps.boosts.services import (  # noqa: WPS433
            unbound_paid_boost_totals_by_request,
        )

        request_ids = {
            match.parcel_id
            for match in matches
            if match.status == Match.Status.PENDING
            and match.parcel_id not in self._paid
        }
        if request_ids:
            self._paid.update(unbound_paid_boost_totals_by_request(request_ids))

    def _paid_boost(self, request_id: int) -> dict:
        if request_id not in self._paid:
            from apps.boosts.services import (  # noqa: WPS433
                unbound_paid_boost_totals_by_request,
            )

            self._paid.update(unbound_paid_boost_totals_by_request([request_id]))
        return self._paid[request_id]

    def project(self, offer: Offer, match: Match) -> dict:
        if (
            offer.economics_version != Offer.EconomicsVersion.V1_EUR
            or offer.traveler_reward_minor is None
        ):
            return unavailable_projection()

        if offer.status == Offer.Status.ACCEPTED:
            try:
                terms = offer.deal.terms
            except (Deal.DoesNotExist, DealTermsSnapshot.DoesNotExist):
                return unavailable_projection()
            if terms.is_legacy or terms.currency != DealTermsSnapshot.Currency.EUR:
                return unavailable_projection()
            return terms_projection(terms, status=BOOST_TERMS_FROZEN)

        if offer.status != Offer.Status.PENDING or match.status != Match.Status.PENDING:
            return unavailable_projection()

        from apps.boosts.services import resolve_committed_boost  # noqa: WPS433
        from apps.core.business_settings import (  # noqa: WPS433
            NoActiveBusinessSettings,
        )
        from apps.core.phase4_policy import InvalidPhase4Policy  # noqa: WPS433

        try:
            boost = resolve_committed_boost(
                paid_boost=self._paid_boost(match.parcel_id),
                boost_intent_eur_cents=_request_boost_intent(match),
                policy_loader=self._load_policy,
            )
        except (NoActiveBusinessSettings, InvalidPhase4Policy):
            # Acceptance would refuse on the same policy, so there is no figure
            # to promise. Saying nothing beats a number that cannot bind.
            return unavailable_projection()
        return terms_projection(
            commitment_terms(offer, boost), status=BOOST_TERMS_PROVISIONAL
        )
