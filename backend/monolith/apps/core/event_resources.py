"""Allowlisted resource identities for authoritative client refetches.

These builders read foreign-key columns only. They never project locations,
recipient details, handover codes, financial credentials, or ORM serializers.
"""


def match_resources(match) -> dict:
    return {
        "match_id": match.pk,
        "parcel_id": match.parcel_id,
        "journey_id": match.journey_id,
    }


def deal_resources(deal) -> dict:
    return {
        "deal_id": deal.pk,
        "match_id": deal.match_id,
        "parcel_id": deal.delivery_request_id,
        "journey_id": deal.journey_id,
    }


def payment_resources(order) -> dict:
    return {
        "payment_order_id": order.pk,
        "deal_id": order.deal_id,
        "request_id": order.delivery_request_id,
    }
