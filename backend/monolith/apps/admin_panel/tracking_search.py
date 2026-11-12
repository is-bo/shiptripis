"""Staff search by tracking number, shared by the console and `/api/admin/`.

A typed number is read through `apps.parcels.tracking.normalize`, so case, the
``WSL`` prefix and the hyphen are optional, and it matches exactly: a partial
number finds nothing.
"""

from __future__ import annotations

from django.db.models import Q

from apps.parcels import tracking

#: Where each staff list finds the number of the parcel a row is about.
REQUEST = ("tracking_number",)
MATCH = ("parcel__tracking_number",)
DEAL = ("delivery_request__tracking_number",)
DISPUTE = ("deal__delivery_request__tracking_number",)
ORDER = (
    "delivery_request__tracking_number",
    "deal__delivery_request__tracking_number",
)
ATTEMPT = tuple(f"order__{path}" for path in ORDER)
REFUND = ATTEMPT
PAYOUT = ("deal__delivery_request__tracking_number",)


def tracking_number_condition(text: str, paths: tuple[str, ...]) -> Q | None:
    """A condition matching rows whose parcel has this number, or ``None``."""

    number = tracking.normalize(text)
    if number is None or not paths:
        return None
    condition = Q()
    for path in paths:
        condition |= Q(**{path: number})
    return condition
