"""Fail closed before provider I/O or using historical money in another mode."""

from django.conf import settings

from config.settings.payments import payment_mode
from .providers.base import ProviderConfigurationInvalid


def enforced():
    return (
        settings.SHIPTRIP_ENVIRONMENT == "production"
        or payment_mode(settings) == "live"
    )


def require_provider_mode(mode):
    # Local adapter fixtures may use synthetic credentials. A LIVE key always
    # requires explicit intent, including outside the production settings profile.
    if (enforced() or mode == "live") and mode != payment_mode(settings):
        raise ProviderConfigurationInvalid(
            "Provider mode does not match deployment payment intent."
        )


def require_object_mode(mode):
    if enforced() and mode != payment_mode(settings):
        raise ProviderConfigurationInvalid(
            "Financial object belongs to another or unknown payment environment."
        )


def event_mode_allowed(payload):
    if not enforced():
        return True
    live = payload.get("livemode")
    if type(live) is not bool or live != (payment_mode(settings) == "live"):
        return False
    data = payload.get("data")
    if isinstance(data, dict):
        obj = data.get("object", data)
        if isinstance(obj, dict) and "livemode" in obj:
            return type(obj["livemode"]) is bool and obj["livemode"] == live
    return True


def require_order_mode(order):
    """A new LIVE attempt must not reuse TEST captures, credits or open sessions."""
    if not enforced():
        return
    from django.db.models import Q
    from .models import PaymentAttempt
    from .payout_snapshots import source_order_ids

    sources = Q(order_id__in=source_order_ids(order)) | Q(order__credited_into=order)
    if order.deal_id:
        sources |= Q(order__deal_id=order.deal_id) | Q(
            order__credited_into__deal_id=order.deal_id
        )
    if (
        PaymentAttempt.objects.filter(sources)
        .exclude(provider_mode=payment_mode(settings))
        .exists()
    ):
        raise ProviderConfigurationInvalid(
            "Order has financial history from another or unknown environment; use a new order."
        )
