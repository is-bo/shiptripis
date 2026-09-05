"""Explicit serializers used by the Phase 6A operations endpoints.

Kept separate from ``serializers.py`` which owns invitation/audit contracts.
"""

from __future__ import annotations

from rest_framework import serializers

from apps.accounts.models import User
from apps.boosts.models import BoostPurchase
from apps.core.models import BusinessSettingsVersion
from apps.deals.models import Deal
from apps.disputes.models import Dispute, DisputeEvidence
from apps.finance.models import (
    PaymentAttempt,
    PaymentOrder,
    PaymentProviderEvent,
    PaymentRefund,
    Payout,
    ScheduledJob,
)
from apps.kyc.models import KycSubmission
from apps.locations.models import Location
from apps.matching.models import Match, Offer
from apps.ratings.models import Rating
from apps.trips.models import Journey, JourneyLeg, JourneyLegProof

from .permissions import has_admin_permission, user_admin_roles


class AdminUserSerializer(serializers.ModelSerializer):
    admin_roles = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "full_name",
            "phone",
            "wilaya",
            "role",
            "is_staff",
            "is_superuser",
            "admin_roles",
            "is_email_verified",
            "is_kyc_verified",
            "is_banned",
            "date_joined",
            "last_login",
        )
        read_only_fields = fields

    def get_admin_roles(self, obj):
        return user_admin_roles(obj)

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if not has_admin_permission(user, "view_user_sensitive"):
            fields.pop("phone", None)
            fields.pop("wilaya", None)
        if not has_admin_permission(user, "manage_admins"):
            fields.pop("is_staff", None)
            fields.pop("is_superuser", None)
            fields.pop("admin_roles", None)
        return fields


class AdminUserDetailSerializer(AdminUserSerializer):
    kyc_count = serializers.IntegerField(read_only=True)
    request_count = serializers.IntegerField(read_only=True)
    journey_count = serializers.IntegerField(read_only=True)
    deal_count = serializers.IntegerField(read_only=True)
    dispute_count = serializers.IntegerField(read_only=True)
    completed_deal_count = serializers.IntegerField(read_only=True)
    no_show_count = serializers.IntegerField(read_only=True)
    ratings_received_count = serializers.IntegerField(read_only=True)
    average_rating = serializers.FloatField(read_only=True, allow_null=True)

    class Meta(AdminUserSerializer.Meta):
        fields = AdminUserSerializer.Meta.fields + (
            "kyc_count",
            "request_count",
            "journey_count",
            "deal_count",
            "dispute_count",
            "completed_deal_count",
            "no_show_count",
            "ratings_received_count",
            "average_rating",
        )

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get("request")
        actor = getattr(request, "user", None)
        if not (
            has_admin_permission(actor, "view_ratings")
            or has_admin_permission(actor, "record_no_show")
        ):
            for name in (
                "completed_deal_count",
                "no_show_count",
                "ratings_received_count",
                "average_rating",
            ):
                fields.pop(name, None)
        return fields


class AdminKycSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source="user.email", read_only=True)
    user_name = serializers.CharField(source="user.full_name", read_only=True)

    class Meta:
        model = KycSubmission
        fields = (
            "id",
            "user_id",
            "user_email",
            "user_name",
            "document_type",
            "front_image_key",
            "back_image_key",
            "selfie_image_key",
            "status",
            "rejection_reason",
            "reviewed_by_id",
            "reviewed_at",
            "expires_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class AdminLocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Location
        fields = (
            "id",
            "kind",
            "public_label",
            "city",
            "region",
            "country_code",
            "precision",
            "coordinates_trusted",
            "owner_id",
        )
        read_only_fields = fields


class AdminFlightProofSerializer(serializers.ModelSerializer):
    leg_position = serializers.IntegerField(source="leg.position", read_only=True)
    journey_id = serializers.IntegerField(source="leg.journey_id", read_only=True)
    traveler_id = serializers.IntegerField(
        source="leg.journey.traveler_id", read_only=True
    )

    class Meta:
        model = JourneyLegProof
        fields = (
            "id",
            "leg_id",
            "journey_id",
            "traveler_id",
            "leg_position",
            "bucket",
            "object_key",
            "kind",
            "content_type",
            "bytes",
            "metadata",
            "status",
            "reviewer_id",
            "reviewed_at",
            "rejection_reason",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class AdminRequestSerializer(serializers.ModelSerializer):
    sender_email = serializers.EmailField(source="sender.email", read_only=True)
    sender_name = serializers.CharField(source="sender.full_name", read_only=True)
    pickup_public_label = serializers.CharField(
        source="pickup_location.public_label", read_only=True, allow_null=True
    )
    delivery_public_label = serializers.CharField(
        source="delivery_location.public_label", read_only=True, allow_null=True
    )
    pickup_place_name = serializers.CharField(
        source="pickup_place.display_label", read_only=True, allow_null=True
    )
    delivery_place_name = serializers.CharField(
        source="delivery_place.display_label", read_only=True, allow_null=True
    )

    class Meta:
        model = __import__(
            "apps.parcels.models", fromlist=["DeliveryRequest"]
        ).DeliveryRequest
        fields = (
            "id",
            "sender_id",
            "sender_email",
            "sender_name",
            "status",
            "kind",
            "schema_version",
            "title",
            "description",
            "category",
            "actual_weight_kg",
            "length_cm",
            "width_cm",
            "height_cm",
            "declared_value_eur_cents",
            "traveler_reward_eur_cents",
            "pickup_location_id",
            "pickup_public_label",
            "pickup_place_id",
            "pickup_place_name",
            "delivery_location_id",
            "delivery_public_label",
            "delivery_place_id",
            "delivery_place_name",
            "ready_window_start",
            "ready_window_end",
            "deadline_at",
            "fragile",
            "ranking_boost_weight",
            "ranking_boost_expires_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class AdminJourneyLegSerializer(serializers.ModelSerializer):
    origin = AdminLocationSerializer(read_only=True)
    destination = AdminLocationSerializer(read_only=True)
    origin_place_name = serializers.CharField(
        source="origin_place.display_label", read_only=True, allow_null=True
    )
    destination_place_name = serializers.CharField(
        source="destination_place.display_label", read_only=True, allow_null=True
    )
    proof_count = serializers.IntegerField(read_only=True)
    pending_proof_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = JourneyLeg
        fields = (
            "id",
            "position",
            "mode",
            "origin",
            "destination",
            "origin_place_id",
            "origin_place_name",
            "destination_place_id",
            "destination_place_name",
            "depart_at",
            "arrive_at",
            "capacity_kg",
            "distance_meters",
            "route_duration_seconds",
            "flight_number",
            "proof_count",
            "pending_proof_count",
        )
        read_only_fields = fields


class AdminJourneySerializer(serializers.ModelSerializer):
    traveler_email = serializers.EmailField(source="traveler.email", read_only=True)
    traveler_name = serializers.CharField(source="traveler.full_name", read_only=True)
    start_location = AdminLocationSerializer(read_only=True)
    destination_location = AdminLocationSerializer(read_only=True)
    start_place_name = serializers.CharField(
        source="start_place.display_label", read_only=True, allow_null=True
    )
    destination_place_name = serializers.CharField(
        source="destination_place.display_label", read_only=True, allow_null=True
    )
    legs = AdminJourneyLegSerializer(many=True, read_only=True)

    class Meta:
        model = Journey
        fields = (
            "id",
            "traveler_id",
            "traveler_email",
            "traveler_name",
            "status",
            "schema_version",
            "start_location",
            "destination_location",
            "start_place_id",
            "start_place_name",
            "destination_place_id",
            "destination_place_name",
            "published_at",
            "notes",
            "legs",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class AdminMatchSerializer(serializers.ModelSerializer):
    sender_email = serializers.EmailField(source="sender.email", read_only=True)
    traveler_email = serializers.EmailField(source="traveler.email", read_only=True)
    offer_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Match
        fields = (
            "id",
            "parcel_id",
            "journey_id",
            "start_leg_id",
            "end_leg_id",
            "sender_id",
            "sender_email",
            "traveler_id",
            "traveler_email",
            "status",
            "matching_version",
            "matched_distance_meters",
            "compatibility_snapshot",
            "ranking_snapshot",
            "offer_count",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class AdminOfferSerializer(serializers.ModelSerializer):
    proposer_email = serializers.EmailField(source="proposer.email", read_only=True)

    class Meta:
        model = Offer
        fields = (
            "id",
            "match_id",
            "proposed_by",
            "proposer_id",
            "proposer_email",
            "status",
            "economics_version",
            "currency",
            "traveler_reward_minor",
            "commission_rate_bps",
            "platform_fee_minor",
            "sender_total_minor",
            "pricing_version",
            "business_settings_version_id",
            "terms_snapshot",
            "note",
            "expires_at",
            "responded_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class AdminDealSerializer(serializers.ModelSerializer):
    sender_email = serializers.EmailField(source="sender.email", read_only=True)
    traveler_email = serializers.EmailField(source="traveler.email", read_only=True)
    event_count = serializers.IntegerField(read_only=True)
    dispute_count = serializers.IntegerField(read_only=True)
    payout_status = serializers.SerializerMethodField()

    class Meta:
        model = Deal
        fields = (
            "id",
            "delivery_request_id",
            "journey_id",
            "match_id",
            "accepted_offer_id",
            "sender_id",
            "sender_email",
            "traveler_id",
            "traveler_email",
            "status",
            "is_legacy",
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
            "cancellation_reason",
            "no_show_party",
            "no_show_recorded_at",
            "event_count",
            "dispute_count",
            "payout_status",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_payout_status(self, obj):
        payout = getattr(obj, "payout", None)
        return payout.status if payout else None


class AdminDealDetailSerializer(AdminDealSerializer):
    terms = serializers.SerializerMethodField()
    timeline = serializers.SerializerMethodField()
    recipient_set = serializers.SerializerMethodField()

    class Meta(AdminDealSerializer.Meta):
        fields = AdminDealSerializer.Meta.fields + (
            "terms",
            "timeline",
            "recipient_set",
        )

    def get_terms(self, obj):
        terms = getattr(obj, "terms", None)
        return (
            None
            if terms is None
            else {
                "currency": terms.currency,
                "traveler_reward_minor": terms.traveler_reward_minor,
                "platform_fee_minor": terms.platform_fee_minor,
                "sender_total_minor": terms.sender_total_minor,
                "commission_rate_bps": terms.commission_rate_bps,
                "pricing_version": terms.pricing_version,
                "business_settings_version_id": terms.business_settings_version_id,
            }
        )

    def get_recipient_set(self, obj):
        return bool(getattr(obj, "recipient", None))

    def get_timeline(self, obj):
        blocked = (
            "code",
            "secret",
            "token",
            "handover_code",
            "delivery_code",
            "sealed_code",
        )

        def scrub(value):
            if isinstance(value, dict):
                return {
                    k: scrub(v)
                    for k, v in value.items()
                    if not any(part in str(k).lower() for part in blocked)
                }
            if isinstance(value, list):
                return [scrub(v) for v in value]
            return value

        return [
            {
                "id": e.id,
                "kind": e.kind,
                "actor_id": e.actor_id,
                "payload": scrub(e.payload or {}),
                "created_at": e.created_at,
            }
            for e in obj.events.all()
        ]


class AdminDisputeEvidenceSerializer(serializers.ModelSerializer):
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
            "created_at",
        )
        read_only_fields = fields


class AdminDisputeSerializer(serializers.ModelSerializer):
    evidence = AdminDisputeEvidenceSerializer(many=True, read_only=True)
    deal_status = serializers.CharField(source="deal.status", read_only=True)

    class Meta:
        model = Dispute
        fields = (
            "id",
            "public_reference",
            "deal_id",
            "deal_status",
            "opened_by_id",
            "opened_by_role",
            "status",
            "category",
            "reason_text",
            "evidence_bundle",
            "evidence",
            "protection_ends_at",
            "opened_at",
            "resolution",
            "sender_refund_eur_cents",
            "traveler_payout_eur_cents",
            "platform_fee_eur_cents",
            "collected_total_eur_cents",
            "resolution_note",
            "resolved_by_id",
            "resolved_at",
            "closed_at",
            "payout_frozen",
            "payout_already_settled",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get("request")
        if not has_admin_permission(getattr(request, "user", None), "view_evidence"):
            fields.pop("evidence", None)
            fields.pop("evidence_bundle", None)
            fields.pop("reason_text", None)
        return fields


class AdminPaymentOrderSerializer(serializers.ModelSerializer):
    outstanding_eur_cents = serializers.IntegerField(read_only=True)
    owner_email = serializers.EmailField(source="owner.email", read_only=True)

    class Meta:
        model = PaymentOrder
        fields = (
            "id",
            "public_reference",
            "owner_id",
            "owner_email",
            "purpose",
            "status",
            "currency",
            "amount_eur_cents",
            "credited_eur_cents",
            "paid_eur_cents",
            "refunded_eur_cents",
            "outstanding_eur_cents",
            "delivery_request_id",
            "deal_id",
            "boost_reference",
            "business_settings_version_id",
            "paid_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class AdminPaymentAttemptSerializer(serializers.ModelSerializer):
    order_reference = serializers.UUIDField(
        source="order.public_reference", read_only=True
    )

    class Meta:
        model = PaymentAttempt
        fields = (
            "id",
            "order_id",
            "order_reference",
            "provider",
            "payer_id",
            "guest_email",
            "amount_eur_cents",
            "payment_currency",
            "provider_amount_minor",
            "provider_amount_exponent",
            "fx_rate_micros",
            "fx_source",
            "provider_session_id",
            "provider_payment_id",
            "status",
            "failure_code",
            "is_unapplied",
            "expires_at",
            "succeeded_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class AdminProviderEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentProviderEvent
        fields = (
            "id",
            "provider",
            "provider_event_id",
            "event_type",
            "attempt_id",
            "order_id",
            "signature_verified",
            "processing_result",
            "processing_attempts",
            "last_error_code",
            "received_at",
            "processing_started_at",
            "next_retry_at",
            "processed_at",
        )
        read_only_fields = fields


class AdminRefundSerializer(serializers.ModelSerializer):
    order_reference = serializers.UUIDField(
        source="order.public_reference", read_only=True
    )

    class Meta:
        model = PaymentRefund
        fields = (
            "id",
            "order_id",
            "order_reference",
            "attempt_id",
            "amount_eur_cents",
            "provider",
            "provider_refund_id",
            "reason",
            "status",
            "failure_code",
            "requires_manual_action",
            "requested_by_id",
            "settled_by_id",
            "settlement_reference",
            "settlement_note",
            "succeeded_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class AdminPayoutSerializer(serializers.ModelSerializer):
    traveler_email = serializers.EmailField(source="traveler.email", read_only=True)

    class Meta:
        model = Payout
        fields = (
            "id",
            "deal_id",
            "traveler_id",
            "traveler_email",
            "amount_eur_cents",
            "method",
            "status",
            "eligible_at",
            "scheduled_for",
            "payout_currency",
            "payout_amount_minor",
            "payout_amount_exponent",
            "fx_rate_micros",
            "provider_payout_id",
            "reference",
            "receipt_url",
            "admin_actor_id",
            "notes",
            "failure_code",
            "paid_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class AdminScheduledJobSerializer(serializers.ModelSerializer):
    class Meta:
        model = ScheduledJob
        fields = (
            "id",
            "key",
            "kind",
            "run_at",
            "status",
            "attempts",
            "max_attempts",
            "locked_at",
            "locked_by",
            "completed_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class AdminRatingSerializer(serializers.ModelSerializer):
    class Meta:
        model = Rating
        fields = (
            "id",
            "deal_id",
            "rater_id",
            "ratee_id",
            "rater_role",
            "score",
            "tags",
            "comment",
            "review_window_ends_at",
            "revealed_at",
            "created_at",
        )
        read_only_fields = fields


class AdminBoostSerializer(serializers.ModelSerializer):
    class Meta:
        model = BoostPurchase
        fields = (
            "id",
            "public_reference",
            "delivery_request_id",
            "buyer_id",
            "payment_order_id",
            "package_code",
            "package_snapshot",
            "duration_seconds",
            "amount_eur_cents",
            "ranking_weight",
            "economics_version",
            "traveler_share_bps",
            "traveler_boost_eur_cents",
            "platform_boost_eur_cents",
            "deal_id",
            "status",
            "activated_at",
            "expires_at",
            "cancelled_at",
            "disposition_reason",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class AdminSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = BusinessSettingsVersion
        fields = (
            "id",
            "version",
            "status",
            "canonical_currency",
            "commission_rate_bps",
            "pricing_version",
            "policy",
            "created_by_id",
            "activated_at",
            "created_at",
        )
        read_only_fields = fields


class AdminReviewSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=("approved", "rejected"))
    reason = serializers.CharField(required=False, allow_blank=True, max_length=2_000)

    def validate(self, attrs):
        if attrs["decision"] == "rejected" and not attrs.get("reason", "").strip():
            raise serializers.ValidationError(
                {"reason": "A rejection reason is required."}
            )
        return attrs


class AdminSettingsCreateSerializer(serializers.Serializer):
    commission_rate_bps = serializers.IntegerField(min_value=0, max_value=10_000)
    pricing_version = serializers.CharField(max_length=32)
    policy = serializers.JSONField()
    activate = serializers.BooleanField(required=False, default=False)
    reason = serializers.CharField(max_length=500, trim_whitespace=True)

    def validate_policy(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("Policy must be a JSON object.")
        forbidden = ("secret", "password", "token", "private_key", "webhook")

        def walk(obj):
            if isinstance(obj, dict):
                for key, child in obj.items():
                    if any(word in str(key).lower() for word in forbidden):
                        raise serializers.ValidationError(
                            "Provider credentials and secrets are environment-only."
                        )
                    walk(child)
            elif isinstance(obj, list):
                for child in obj:
                    walk(child)

        walk(value)
        return value

    def validate(self, attrs):
        """Run every existing policy parser before a revision reaches storage."""

        from apps.core.phase4_policy import InvalidPhase4Policy, Phase4Policy
        from apps.finance.policy import InvalidPaymentPolicy, Phase3Policy
        from apps.matching.policy import InvalidPhase2Policy, Phase2Policy

        candidate = BusinessSettingsVersion(
            version=1,
            commission_rate_bps=attrs["commission_rate_bps"],
            pricing_version=attrs["pricing_version"],
            policy=attrs["policy"],
        )
        try:
            Phase2Policy.from_settings(candidate)
            Phase3Policy.from_settings(candidate)
            Phase4Policy.from_settings(candidate)
        except (InvalidPhase2Policy, InvalidPaymentPolicy, InvalidPhase4Policy) as exc:
            raise serializers.ValidationError(
                {
                    "policy": {
                        "code": getattr(exc, "code", "invalid_policy"),
                        "detail": str(exc),
                    }
                }
            ) from exc
        return attrs
