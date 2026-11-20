"""Read and write contracts for sender Boost.

The client names an amount; the server prices it. A request body carries one
integer and nothing else. Bounds, the commission rate, the Traveler bonus and
the sender's cost are all computed server-side and returned, so no client ever
calculates a financial total and no client can propose one.
"""

from __future__ import annotations

from rest_framework import serializers

from .services import MAX_EUR_CENTS


class BoostIntentSerializer(serializers.Serializer):
    """The whole request body: what the sender wants the Boost to be.

    Zero is valid and means "remove it". The band is enforced by the service
    against the active settings revision rather than by a constant compiled into
    the image, because the band is an operator decision that changes without a
    deploy; the ceiling here is only the representation guard.
    """

    boost_eur_cents = serializers.IntegerField(min_value=0, max_value=MAX_EUR_CENTS)
