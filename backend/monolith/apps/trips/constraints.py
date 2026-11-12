"""Authoritative V1 Journey input constraints shared by writes and publication."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from django.utils import timezone


# There is no product capacity cap for anyone (spec 5.5). These ceilings exist
# only to catch a typo — 20 tonnes is a full lorry, not a suitcase — and the
# mobile form mirrors them in L3B.
MAX_JOURNEY_LEG_CAPACITY_KG = Decimal("20000.00")
MAX_JOURNEY_LEG_CAPACITY_VOLUME_L = 200_000
MAX_JOURNEY_LEG_CAPACITY_PARCELS = 10_000

#: A stop's handover note is a sentence, not a document (spec 5.1).
MAX_HANDOVER_NOTE_LENGTH = 280

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
