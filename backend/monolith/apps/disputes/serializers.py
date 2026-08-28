"""Read and write contracts for the dispute API.

Three projections, for three audiences.

`DisputeSerializer` is what a party sees about their own dispute: its state, its
category, the money it decided and the evidence they and the other side filed.
It does **not** carry `evidence_bundle`. The bundle is the platform's captured
index into everything -- payment attempt ids, provider references, handover
verification history, journey proof records -- and it exists to be read by the
people resolving the dispute, not by the people arguing it.

`AdminDisputeSerializer` adds exactly that field, for exactly those people.

`DisputeEvidenceSerializer` never exposes `storage_bucket` or `storage_key`. A
client learns that a file exists, what type it is and what its SHA-256 is; the
bytes are reached only through a short-lived signed URL issued after an
authorization check. Handing out a bucket path would make revocation impossible.

Event payloads are narrowed the same way `apps.deals.timeline` narrows the Deal
timeline: staff read the stored payload, a party reads an allowlist of keys. An
administrator's working note belongs in the audit record and not in the inbox of
the person it is about.
"""

from __future__ import annotations

from rest_framework import serializers

from apps.deals.models import Deal

from .models import Dispute, DisputeEvent, DisputeEvidence
from .services import ADMIN_SETTABLE_STATUSES

#: Event payload keys a party may read. Everything else -- above all a staff
#: `note` -- is dropped. An allowlist, so a key added by a future transition is
#: invisible to a party until somebody deliberately adds it here.
PARTY_VISIBLE_EVENT_KEYS = frozenset(
    {
        "category",
        "opened_by_role",
        "deal_status",
        "protection_ends_at",
        "status",
        "previous_status",
        "resolution",
        "evidence_id",
        "evidence_kind",
        "content_type",
        "size_bytes",
        "content_sha256",
        "payout_status",
        "bundle_version",
        "captured_at",
        "collected_eur_cents",
        "sender_refund_eur_cents",
        "traveler_payout_eur_cents",
        "platform_fee_eur_cents",
    }
)


class DisputeEvidenceSerializer(serializers.ModelSerializer):
    """One submission. Storage location is deliberately absent."""

    submitted_by_id = serializers.IntegerField(read_only=True)
    has_file = serializers.SerializerMethodField()

    class Meta:
        model = DisputeEvidence
        fields = (
            "id",
            "dispute_id",
            "submitted_by_id",
            "kind",
            "text",
            "content_type",
            "size_bytes",
            "content_sha256",
            "has_file",
            "created_at",
        )
        read_only_fields = fields

    def get_has_file(self, obj: DisputeEvidence) -> bool:
        return bool(obj.storage_key)


class DisputeEventSerializer(serializers.ModelSerializer):
    """One row of the dispute's own timeline, narrowed to its reader.

    Pass `is_staff=True` in the serializer context to return stored payloads
    unchanged; anything else gets the party allowlist.
    """

    actor_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = DisputeEvent
        fields = ("id", "kind", "actor_id", "payload", "created_at")
        read_only_fields = fields

    def to_representation(self, instance: DisputeEvent) -> dict:
        data = super().to_representation(instance)
        if self.context.get("is_staff"):
            return data
        payload = instance.payload or {}
        data["payload"] = {
            key: value
            for key, value in payload.items()
            if key in PARTY_VISIBLE_EVENT_KEYS
        }
        return data


class DisputeSerializer(serializers.ModelSerializer):
    """A party's view of a dispute on their own delivery.

    Carries the resolution and every amount it decided, because a party is
    entitled to know what happened to their money and why. Carries no
    `evidence_bundle`.
    """

    deal_id = serializers.IntegerField(read_only=True)
    opened_by_id = serializers.IntegerField(read_only=True)
    deal_status = serializers.CharField(source="deal.status", read_only=True)
    evidence = DisputeEvidenceSerializer(many=True, read_only=True)
    events = serializers.SerializerMethodField()

    class Meta:
        model = Dispute
        fields = (
            "id",
            "public_reference",
            "deal_id",
            "deal_status",
            "status",
            "category",
            "reason_text",
            "opened_by_id",
            "opened_by_role",
            "opened_at",
            "protection_ends_at",
            "resolution",
            "sender_refund_eur_cents",
            "traveler_payout_eur_cents",
            "platform_fee_eur_cents",
            "collected_total_eur_cents",
            "resolution_note",
            "resolved_at",
            "closed_at",
            "payout_frozen",
            "payout_already_settled",
            "evidence",
            "events",
        )
        read_only_fields = fields

    def get_events(self, obj: Dispute) -> list[dict]:
        return DisputeEventSerializer(
            obj.events.all(), many=True, context=self.context
        ).data


class AdminDisputeSerializer(DisputeSerializer):
    """The operations view: everything a party sees, plus the captured bundle."""

    resolved_by_id = serializers.IntegerField(read_only=True)

    class Meta(DisputeSerializer.Meta):
        fields = (
            *DisputeSerializer.Meta.fields,
            "resolved_by_id",
            "evidence_bundle",
        )
        read_only_fields = fields


# --- write contracts ---------------------------------------------------------


class DisputeOpenSerializer(serializers.Serializer):
    """What a party states when they open a dispute.

    A category and their own account of what went wrong. Nothing about money:
    the amounts a dispute can move are decided by an administrator against the
    Deal's collected total, never proposed by a client.
    """

    category = serializers.ChoiceField(choices=Dispute.Category.choices)
    reason_text = serializers.CharField(max_length=4_000, trim_whitespace=True)


class DisputeEvidenceCreateSerializer(serializers.Serializer):
    """One evidence submission: a statement, or a file with a declared type.

    The declared content type is checked against the file's actual bytes in
    `apps.disputes.services`, not here. This layer only enforces that the shape
    of the request matches the kind of evidence being claimed.
    """

    kind = serializers.ChoiceField(choices=DisputeEvidence.Kind.choices)
    text = serializers.CharField(
        required=False, allow_blank=True, max_length=4_000, trim_whitespace=True
    )
    file = serializers.FileField(required=False, allow_null=True)

    def validate(self, attrs):
        kind = attrs.get("kind")
        if kind == DisputeEvidence.Kind.TEXT:
            if not (attrs.get("text") or "").strip():
                raise serializers.ValidationError(
                    {"text": "Write something for a text statement."}
                )
        elif attrs.get("file") is None:
            raise serializers.ValidationError(
                {"file": "Attach a file for photo or video evidence."}
            )
        return attrs


class DisputeStatusSerializer(serializers.Serializer):
    """Admin-only move between the three live review states."""

    status = serializers.ChoiceField(choices=ADMIN_SETTABLE_STATUSES)
    note = serializers.CharField(
        required=False, allow_blank=True, max_length=4_000
    )


class DisputeResolveSerializer(serializers.Serializer):
    """Admin-only resolution. The amounts are audit evidence.

    `sender_refund_eur_cents` is required by a partial split and ignored by the
    two full resolutions, which are defined against the collected total rather
    than against a number an operator typed. The service refuses a "partial"
    split that is not partial.
    """

    resolution = serializers.ChoiceField(choices=Dispute.Resolution.choices)
    sender_refund_eur_cents = serializers.IntegerField(
        required=False, allow_null=True, min_value=0
    )
    traveler_payout_eur_cents = serializers.IntegerField(
        required=False, allow_null=True, min_value=0
    )
    note = serializers.CharField(
        required=False, allow_blank=True, max_length=4_000
    )


class NoShowSerializer(serializers.Serializer):
    """Admin-only no-show record.

    `refund_sender` is omitted in the normal case: launch policy refunds the
    sender in full for a verified traveler no-show and does not for a sender
    one. Sending it explicitly overrides that, and the override is stored on the
    Deal timeline next to the administrator's note.
    """

    party = serializers.ChoiceField(choices=Deal.NoShowParty.choices)
    note = serializers.CharField(required=False, allow_blank=True, max_length=255)
    refund_sender = serializers.BooleanField(required=False, allow_null=True)
