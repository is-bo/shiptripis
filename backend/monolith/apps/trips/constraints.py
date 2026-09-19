"""Authoritative V1 Journey input constraints shared by writes and publication."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from django.utils import timezone


# The retired single-leg Trip contract already capped traveler capacity at
# 200 kg. V1 Journey legs inherit that server-side ceiling rather than letting
# a new client-only guess diverge from the established product boundary.
MAX_JOURNEY_LEG_CAPACITY_KG = Decimal("200.00")

DEPARTURE_NOT_FUTURE_CODE = "journey_departure_not_future"
DEPARTURE_NOT_FUTURE_MESSAGE = "The first leg departure must be in the future."


def first_departure_is_future(
    depart_at: datetime, *, at: datetime | None = None
) -> bool:
    """Return the strict V1 boundary: the first departure is after server time.

    ``at`` makes boundary tests deterministic. Runtime callers omit it and use
    Django's timezone-aware clock. There is intentionally no latency grace:
    the mobile rule is also strict, and a timestamp equal to the authoritative
    instant is not future inventory.
    """

    reference = timezone.now() if at is None else at
    return depart_at > reference
