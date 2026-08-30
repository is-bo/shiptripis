"""Deal API projections.

Two serializers, for two different jobs.

`DealSummarySerializer` is what a list returns. It stays deliberately cheap: the
Deal's own columns, its frozen terms and its leg allocations, all of which the
list view already prefetches. Nothing here may add a query per row -- the V1
matching regression asserts a bounded query count on `GET /api/deals`, and a
convenience field that costs one query per Deal is exactly how a list endpoint
degrades without anybody noticing.

`DealSerializer` is what the detail endpoint returns, and it is the contract the
Flutter client will build the whole delivery experience on. It carries every
authoritative timestamp the app needs -- pickup, the delivery-code buffer, the
protection deadline, the rating window -- so the client renders countdowns from
server instants and never computes a deadline or an amount of its own.

Both are read-only. A lifecycle field is written by `apps.deals.lifecycle` and
by nothing else, so there is no writable serializer for one anywhere.
"""

from __future__ import annotations

from rest_framework import serializers

from apps.core.languages import CommunicationLanguage

from apps.matching.public_contract import public_terms_snapshot

from .models import Deal, DealLegAllocation, DealTermsSnapshot
from .recipient import recipient_projection
from .timeline import deal_timeline


class DealTermsSnapshotSerializer(serializers.ModelSerializer):
    business_settings_version = serializers.IntegerField(
        source="business_settings_version.version", read_only=True, allow_null=True
    )
    policy_snapshot = serializers.SerializerMethodField()

    class Meta:
        model = DealTermsSnapshot
        fields = (
            "currency",
            "traveler_reward_minor",
            "commission_rate_bps",
            "platform_fee_minor",
            "sender_total_minor",
            "business_settings_version",
            "pricing_version",
            "policy_snapshot",
            "is_legacy",
            "created_at",
        )
        read_only_fields = fields

    def get_policy_snapshot(self, obj: DealTermsSnapshot) -> dict | None:
        # Storage keeps the full business policy, ranking factors and internal
        # compatibility geometry for reproducibility; a Deal party sees only
        # the agreed terms.
        return public_terms_snapshot(obj.policy_snapshot)


class DealLegAllocationSerializer(serializers.ModelSerializer):
    journey_leg_position = serializers.IntegerField(
        source="journey_leg.position", read_only=True
    )

    class Meta:
        model = DealLegAllocation
        fields = (
            "id",
            "journey_leg_id",
            "journey_leg_position",
            "allocated_weight_kg",
            "status",
            "reserved_at",
            "expires_at",
            "released_at",
            "release_reason",
        )
        read_only_fields = fields


#: Every server-authoritative instant the client renders a countdown from. They
#: are listed once and shared by both serializers so a list row and a detail
#: payload can never disagree about which deadlines exist.
LIFECYCLE_TIMESTAMP_FIELDS = (
    "funded_at",
    "agreed_pickup_at",
    "pickup_confirmed_at",
    "delivery_code_available_at",
    "delivery_code_released_at",
    "delivery_confirmed_at",
    "protection_ends_at",
    "rating_window_ends_at",
    "completed_at",
    "cancelled_at",
)


class DealSummarySerializer(serializers.ModelSerializer):
    """The list projection. Adds no per-row query."""

    terms = DealTermsSnapshotSerializer(read_only=True)
    leg_allocations = DealLegAllocationSerializer(many=True, read_only=True)

    class Meta:
        model = Deal
        fields = (
            "id",
            "accepted_offer_id",
            "match_id",
            "delivery_request_id",
            "journey_id",
            "sender_id",
            "traveler_id",
            "status",
            "is_legacy",
            "cancellation_reason",
            *LIFECYCLE_TIMESTAMP_FIELDS,
            "terms",
            "leg_allocations",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class DealSerializer(serializers.ModelSerializer):
    """The detail projection: everything one party may know about one Deal.

    The blocks below are computed rather than declared because each of them is
    viewer-dependent. The same Deal serialized for its sender and for its
    traveler is deliberately not the same document: the sender may be told a
    code can be revealed, the traveler may be told a submission would be
    accepted, and neither is ever told anything about the other's secrets.
    """

    terms = DealTermsSnapshotSerializer(read_only=True)
    leg_allocations = DealLegAllocationSerializer(many=True, read_only=True)
    timeline = serializers.SerializerMethodField()
    recipient = serializers.SerializerMethodField()
    handover = serializers.SerializerMethodField()
    protection = serializers.SerializerMethodField()
    dispute = serializers.SerializerMethodField()
    ratings = serializers.SerializerMethodField()
    cancellation = serializers.SerializerMethodField()
    no_show = serializers.SerializerMethodField()

    class Meta:
        model = Deal
        fields = (
            "id",
            "accepted_offer_id",
            "match_id",
            "delivery_request_id",
            "journey_id",
            "sender_id",
            "traveler_id",
            "status",
            "is_legacy",
            "cancellation_reason",
            *LIFECYCLE_TIMESTAMP_FIELDS,
            "terms",
            "leg_allocations",
            "timeline",
            "recipient",
            "handover",
            "protection",
            "dispute",
            "ratings",
            "cancellation",
            "no_show",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    # -- viewer -------------------------------------------------------------

    def _viewer_id(self) -> int | None:
        request = self.context.get("request")
        user = getattr(request, "user", None)
        return getattr(user, "id", None)

    def _is_staff(self) -> bool:
        request = self.context.get("request")
        return bool(getattr(getattr(request, "user", None), "is_staff", False))

    # -- computed blocks ----------------------------------------------------

    def get_timeline(self, deal: Deal) -> list[dict]:
        return deal_timeline(deal.events.all(), is_staff=self._is_staff())

    def get_recipient(self, deal: Deal) -> dict | None:
        recipient = getattr(deal, "recipient", None)
        return recipient_projection(
            deal=deal,
            recipient=recipient,
            viewer_id=self._viewer_id(),
            is_staff=self._is_staff(),
        )

    def get_handover(self, deal: Deal) -> dict:
        from apps.handover.services import handover_state

        return handover_state(deal=deal, viewer_id=self._viewer_id())

    def get_protection(self, deal: Deal) -> dict:
        """The payout gate, stated in server instants and states.

        Both parties see it. The traveler needs to know when they will be paid
        and the sender needs to know how long their payment stays protected, and
        neither number is something the client should be deriving.
        """

        payout = getattr(deal, "payout", None)
        return {
            "protection_ends_at": deal.protection_ends_at,
            "delivery_confirmed_at": deal.delivery_confirmed_at,
            "payout": (
                None
                if payout is None
                else {
                    "status": payout.status,
                    "amount_eur_cents": int(payout.amount_eur_cents),
                    "eligible_at": payout.eligible_at,
                    "method": payout.method,
                    "paid_at": payout.paid_at,
                }
            ),
        }

    def get_dispute(self, deal: Deal) -> dict | None:
        from apps.disputes.models import Dispute

        row = (
            Dispute.objects.filter(deal_id=deal.pk)
            .order_by("-opened_at", "-pk")
            .first()
        )
        if row is None:
            return None
        return {
            "id": row.pk,
            "public_reference": str(row.public_reference),
            "status": row.status,
            "category": row.category,
            "opened_at": row.opened_at,
            "opened_by_role": row.opened_by_role,
            "is_active": row.is_active,
            "resolution": row.resolution,
            "resolved_at": row.resolved_at,
        }

    def get_ratings(self, deal: Deal) -> dict:
        from apps.ratings.services import rating_state

        return rating_state(
            deal=deal, viewer_id=self._viewer_id(), is_staff=self._is_staff()
        )

    def get_cancellation(self, deal: Deal) -> dict:
        """Whether a cancel button should exist, without pricing it.

        Pricing a cancellation means reading locked financial state, which a
        serializer has no business doing. `GET /api/deals/<id>/cancellation`
        answers the amounts; this answers whether to offer the action at all.
        """

        from . import lifecycle

        viewer_id = self._viewer_id()
        is_party = viewer_id in (deal.sender_id, deal.traveler_id)
        if not is_party:
            return {"allowed": False, "refusal_code": "not_authorized"}
        if deal.status == Deal.Status.PAYMENT_REQUIRED:
            return {"allowed": True, "mode": "pre_funding", "refusal_code": ""}
        if deal.status in lifecycle.PRE_PICKUP_STATUSES:
            return {"allowed": True, "mode": "after_funding", "refusal_code": ""}
        if deal.pickup_confirmed_at is not None:
            return {
                "allowed": False,
                "mode": "",
                "refusal_code": "cancellation_not_available_after_pickup",
            }
        return {"allowed": False, "mode": "", "refusal_code": "deal_not_cancellable"}

    def get_no_show(self, deal: Deal) -> dict | None:
        if not deal.no_show_party:
            return None
        return {
            "party": deal.no_show_party,
            "recorded_at": deal.no_show_recorded_at,
            "note": deal.no_show_note,
        }


class DealRecipientWriteSerializer(serializers.Serializer):
    """The sender's recipient submission.

    Name and email are required because the delivery-code notification has
    nowhere to go without them. Phone and note are optional and are carried only
    so the traveler can reach the door; neither is ever shown to anyone outside
    the Deal.
    """

    full_name = serializers.CharField(max_length=120, trim_whitespace=True)
    email = serializers.EmailField(max_length=254)
    phone = serializers.CharField(
        max_length=32, required=False, allow_blank=True, default="", trim_whitespace=True
    )
    delivery_note = serializers.CharField(
        max_length=1_000, required=False, allow_blank=True, default=""
    )
    communication_language = serializers.ChoiceField(
        choices=CommunicationLanguage.choices,
        required=False,
    )
