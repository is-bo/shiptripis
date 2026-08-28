"""Wallet reactions to payments-app state changes.

We use Django's post_save signal on `PaymentIntent` and `Refund` rather
than subscribing to Redis directly — Django and the wallet live in the
same process, so an in-process signal is cheaper and keeps the wallet
ledger write inside the same transaction as the payment status update.

Idempotency is enforced at the ledger level (`WalletEntry.key`).
"""

from __future__ import annotations

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.payments.models import PaymentIntent, Refund
from apps.parcels.models import ParcelRequest

from .models import Hold
from .services import open_hold, reverse_hold_for_refund


@receiver(post_save, sender=PaymentIntent)
def _on_payment_intent_saved(sender, instance: PaymentIntent, created: bool, **_):
    """When a PaymentIntent flips to `succeeded`, open the escrow hold.

    Hold currency follows the payment's currency. The payee is determined
    later, when the handover confirms — wallet just locks the money now.
    """
    if instance.status != PaymentIntent.Status.SUCCEEDED:
        return
    offer = instance.offer
    if (
        offer.economics_version == "v1_eur"
        or offer.match.journey_id is not None
        or offer.match.parcel.kind == ParcelRequest.Kind.PRODUCT
    ):
        return
    open_hold(
        user=instance.payer,
        currency=instance.currency,
        amount_minor=instance.amount_minor,
        source="payment_intent",
        source_id=instance.id,
        note=f"Escrow for offer #{instance.offer_id}",
    )


@receiver(post_save, sender=Refund)
def _on_refund_saved(sender, instance: Refund, created: bool, **_):
    """When a Refund succeeds, reverse the matching hold (if still open)."""
    if instance.status != Refund.Status.SUCCEEDED:
        return
    hold = Hold.objects.filter(
        source="payment_intent", source_id=instance.intent_id
    ).first()
    if hold is None or hold.status != Hold.Status.OPEN:
        return
    reverse_hold_for_refund(
        hold=hold,
        refund_source="refund",
        refund_source_id=instance.id,
        note=f"Refund #{instance.id} for intent #{instance.intent_id}",
    )
