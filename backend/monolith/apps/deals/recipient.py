"""Collecting and projecting the parcel recipient.

The recipient is the one person in a Deal who has no ShipTrip account. They are
reached once, by email, when the delivery-code safety buffer elapses, and they
hand that code to the traveler in person. That makes their contact details the
only third-party personal data the platform holds for a delivery, and it is why
this module is small, explicit and stingy:

* only the sender may record or change them,
* only after funding and only before pickup is confirmed -- afterwards the
  address the traveler is walking to has already been agreed, and a silent edit
  would be a way to redirect a parcel that is already in transit,
* the traveler is shown a name and a delivery note and nothing else, and only
  once the parcel is actually in their hands,
* nobody else sees them at all: not a guest payer, not a matching surface, not
  a public Journey payload.

Recording the recipient is also the gate into `pickup_ready`. The delivery-code
notification has nowhere to go without an email address, and discovering that
thirty minutes after the parcel has left the sender's hands is too late to fix.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction

from apps.core.financial_locks import lock_deal_lifecycle
from apps.core.languages import (
    DEFAULT_COMMUNICATION_LANGUAGE,
    normalize_communication_language,
)

from . import lifecycle
from .models import Deal, DealEvent, DealRecipient


class RecipientError(RuntimeError):
    """A recipient operation was refused. Carries a stable machine code."""

    code = "recipient_error"

    def __init__(self, message: str, *, code: str | None = None, **details):
        super().__init__(message)
        if code:
            self.code = code
        self._details = details

    def details(self) -> dict:
        return dict(self._details)


class NotAuthorized(RecipientError):
    code = "not_authorized"


@dataclass(frozen=True, slots=True)
class RecipientResult:
    deal_id: int
    created: bool
    revision: int
    deal_status: str


#: Statuses in which the sender may still record or change the recipient.
EDITABLE_STATUSES = (Deal.Status.FUNDED, Deal.Status.PICKUP_READY)


@transaction.atomic
def set_recipient(
    *,
    deal_id: int,
    actor_id: int,
    full_name: str,
    email: str,
    phone: str = "",
    delivery_note: str = "",
    communication_language: str | None = None,
) -> RecipientResult:
    """Record or replace the recipient, then open pickup if that was the gate.

    Enters through `lock_deal_lifecycle`, so the recipient row is taken after
    the Deal exactly like every other Phase 4 write. Both effects -- the
    recipient and the `funded -> pickup_ready` transition -- commit together, so
    there is no window in which a recipient exists and the Deal still says the
    sender has not finished setting up.
    """

    aggregate = lock_deal_lifecycle(deal_id)
    deal = aggregate.deal
    if actor_id != deal.sender_id:
        raise NotAuthorized("Only the sender can set the delivery recipient.")
    if deal.pickup_confirmed_at is not None:
        raise RecipientError(
            "The parcel has already been picked up; the recipient can no longer "
            "be changed here.",
            code="pickup_already_confirmed",
        )
    if deal.status not in EDITABLE_STATUSES:
        raise RecipientError(
            "Recipient details are collected once the delivery is funded.",
            code="deal_not_funded",
            deal_status=deal.status,
        )

    existing = aggregate.recipient
    if existing is None:
        selected_language = normalize_communication_language(
            communication_language or getattr(deal.sender, "preferred_language", "")
        )
        DealRecipient.objects.create(
            deal=deal,
            full_name=full_name.strip()[:120],
            email=email.strip()[:254],
            phone=phone.strip()[:32],
            delivery_note=delivery_note[:1_000],
            communication_language=selected_language,
            created_by_id=actor_id,
            revision=1,
        )
        created = True
        revision = 1
        lifecycle.record_event(
            deal,
            DealEvent.Kind.RECIPIENT_SET,
            {"revision": revision},
            actor_id=actor_id,
        )
    else:
        existing.full_name = full_name.strip()[:120]
        existing.email = email.strip()[:254]
        existing.phone = phone.strip()[:32]
        existing.delivery_note = delivery_note[:1_000]
        if communication_language is not None:
            existing.communication_language = normalize_communication_language(
                communication_language
            )
        existing.updated_by_id = actor_id
        existing.revision = int(existing.revision) + 1
        existing.save(
            update_fields=[
                "full_name",
                "email",
                "phone",
                "delivery_note",
                "communication_language",
                "updated_by",
                "revision",
                "updated_at",
            ]
        )
        created = False
        revision = existing.revision
        # The payload records that the details changed and which revision this
        # is. It deliberately does not record what they changed to: the
        # timeline is read by the traveler and by staff, and a diff of somebody
        # else's contact details is not theirs to keep.
        lifecycle.record_event(
            deal,
            DealEvent.Kind.RECIPIENT_CHANGED,
            {"revision": revision},
            actor_id=actor_id,
        )

    # Re-read the aggregate's view of the recipient so the transition sees it.
    aggregate = lock_deal_lifecycle(deal_id)
    lifecycle.apply_pickup_ready(aggregate, actor_id=actor_id)
    return RecipientResult(
        deal_id=deal_id,
        created=created,
        revision=revision,
        deal_status=aggregate.deal.status,
    )


def recipient_projection(
    *, deal: Deal, recipient: DealRecipient | None, viewer_id: int, is_staff: bool
) -> dict | None:
    """What one viewer may know about the recipient.

    Returns `None` for anybody who is not a party, so the field is absent rather
    than present-and-empty -- an empty object still confirms that a Deal exists
    and that its recipient has not been set.
    """

    if recipient is None:
        return None
    if is_staff or viewer_id == deal.sender_id:
        return {
            "full_name": recipient.full_name,
            "email": recipient.email,
            "phone": recipient.phone,
            "delivery_note": recipient.delivery_note,
            "communication_language": normalize_communication_language(
                recipient.communication_language
                or DEFAULT_COMMUNICATION_LANGUAGE
            ),
            "revision": recipient.revision,
            "updated_at": recipient.updated_at,
        }
    if viewer_id == deal.traveler_id:
        # The traveler needs to know who to hand the parcel to and any note
        # about the drop-off, and needs it only once they are carrying it. The
        # email address is never theirs: it is how the platform reaches the
        # recipient with a code the traveler must not have.
        if deal.pickup_confirmed_at is None:
            return {"recorded": True}
        return {
            "recorded": True,
            "full_name": recipient.full_name,
            "delivery_note": recipient.delivery_note,
        }
    return None
