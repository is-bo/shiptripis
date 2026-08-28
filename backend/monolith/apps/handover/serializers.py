"""Serialization contracts for Deal handover codes.

Two rules shape every serializer in this module:

**The traveler never sees an unsealed delivery code.** The
`RevealedCodeSerializer` exists strictly for sender reveal and rotate routes.
No traveler endpoint, response schema or error payload shares its fields.

**The submit boundary does not act as an oracle.** `HandoverSubmitSerializer`
accepts any non-empty string within reasonable length bounds and avoids
validating charset or layout. The service layer normalizes and compares codes
in constant time. Rejecting malformed inputs at the API edge would give an
attacker free format-probing without consuming an attempt from the Deal's
lockout budget.
"""

from __future__ import annotations

from rest_framework import serializers


class RevealedCodeSerializer(serializers.Serializer):
    """The sender's view of an unsealed handover code.

    Returned ONLY to the Deal sender from the reveal and rotate endpoints.
    The traveler must never receive an instance of this serializer or any
    payload containing plaintext code material.
    """

    code = serializers.CharField(read_only=True)
    formatted = serializers.CharField(read_only=True)
    kind = serializers.CharField(read_only=True)
    available_at = serializers.DateTimeField(read_only=True, allow_null=True)
    rotation = serializers.IntegerField(read_only=True)


class HandoverSubmitSerializer(serializers.Serializer):
    """A candidate code submitted by the traveler.

    We deliberately accept any string up to 64 characters and do not validate
    the alphabet, length or grouping here: the service normalises and compares
    in constant time, and rejecting malformed inputs early at the serializer
    layer would give an automated guesser a free oracle without burning an
    attempt.
    """

    code = serializers.CharField(max_length=64, trim_whitespace=True)


class SubmissionResultSerializer(serializers.Serializer):
    """Outcome of a successful code submission."""

    deal_id = serializers.IntegerField(read_only=True)
    kind = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    changed = serializers.BooleanField(read_only=True)
