from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import serializers

from apps.locations.models import Location
from apps.locations.serializers import (
    PrivateLocationSerializer,
    PublicLocationSerializer,
)
from apps.trips.models import Airport
from apps.trips.serializers import AirportSerializer

from .models import DeliveryRequest, ParcelMedia, ParcelRequest, ProductRequest


class ParcelMediaSerializer(serializers.ModelSerializer):
    """Public parcel media metadata.

    We deliberately do NOT expose `bucket` or `object_key` — those are
    internal storage paths. The Go media-service issues short-lived
    presigned URLs on demand; the client never sees the raw S3 key.
    """

    class Meta:
        model = ParcelMedia
        fields = ("id", "content_type", "bytes", "created_at")
        read_only_fields = fields


class _ParcelBase(serializers.Serializer):
    origin = serializers.CharField(min_length=3, max_length=3)
    destination = serializers.CharField(min_length=3, max_length=3)
    pickup_city = serializers.CharField(
        required=False, allow_blank=True, max_length=80, default=""
    )
    delivery_city = serializers.CharField(
        required=False, allow_blank=True, max_length=80, default=""
    )
    weight_kg = serializers.IntegerField(min_value=1, max_value=100)
    item_type = serializers.ChoiceField(
        choices=ParcelRequest.ItemType.choices,
        default=ParcelRequest.ItemType.OTHER,
    )
    description = serializers.CharField(
        required=False, allow_blank=True, max_length=2000, default=""
    )
    deadline_at = serializers.DateTimeField(required=False, allow_null=True)
    # Optional: when present, this request is aimed at one specific traveler
    # (e.g. sender hit "Request this trip" on a trip tile). The traveler can
    # then counter-offer; on broadcast requests the price is sender-set and
    # the traveler only accepts/declines. See CounterOfferView.
    target_traveler_id = serializers.IntegerField(required=False, allow_null=True)

    def validate(self, attrs: dict) -> dict:
        if attrs["origin"].upper() == attrs["destination"].upper():
            raise serializers.ValidationError(
                {"destination": "Origin and destination must differ."}
            )
        deadline = attrs.get("deadline_at")
        if deadline is not None and deadline <= timezone.now():
            raise serializers.ValidationError(
                {"deadline_at": "Deadline must be in the future."}
            )
        codes = {attrs["origin"].upper(), attrs["destination"].upper()}
        known = set(
            Airport.objects.filter(iata__in=codes).values_list("iata", flat=True)
        )
        missing = codes - known
        if missing:
            raise serializers.ValidationError(
                {"airports": f"Unknown IATA code(s): {', '.join(sorted(missing))}"}
            )
        attrs["origin"] = attrs["origin"].upper()
        attrs["destination"] = attrs["destination"].upper()
        return attrs


class DeliveryCreateSerializer(_ParcelBase):
    base_amount_dzd = serializers.IntegerField(min_value=100, max_value=10_000_000)


class DeliveryV1CreateSerializer(serializers.Serializer):
    """Strict V1 write contract; legacy airport and DZD inputs are not accepted."""

    pickup_location_id = serializers.PrimaryKeyRelatedField(
        source="pickup_location",
        queryset=Location.objects.all(),
    )
    delivery_location_id = serializers.PrimaryKeyRelatedField(
        source="delivery_location",
        queryset=Location.objects.all(),
    )
    ready_window_start = serializers.DateTimeField()
    ready_window_end = serializers.DateTimeField()
    deadline_at = serializers.DateTimeField()
    actual_weight_kg = serializers.DecimalField(
        max_digits=6,
        decimal_places=2,
        min_value=Decimal("0.01"),
        max_value=Decimal("100.00"),
    )
    length_cm = serializers.DecimalField(
        max_digits=6,
        decimal_places=2,
        min_value=Decimal("0.01"),
        max_value=Decimal("500.00"),
    )
    width_cm = serializers.DecimalField(
        max_digits=6,
        decimal_places=2,
        min_value=Decimal("0.01"),
        max_value=Decimal("500.00"),
    )
    height_cm = serializers.DecimalField(
        max_digits=6,
        decimal_places=2,
        min_value=Decimal("0.01"),
        max_value=Decimal("500.00"),
    )
    declared_value_eur_cents = serializers.IntegerField(
        min_value=0,
        max_value=100_000_000,
    )
    # The sender's non-binding posted intent. The authoritative reward is the
    # Offer's server-validated `traveler_reward_minor`; naming this
    # `traveler_reward_*` made it read like a second source of truth.
    sender_proposed_reward_eur_cents = serializers.IntegerField(
        source="traveler_reward_eur_cents",
        min_value=1,
        max_value=100_000_000,
    )
    title = serializers.CharField(max_length=160, trim_whitespace=True)
    description = serializers.CharField(max_length=2000, trim_whitespace=True)
    category = serializers.ChoiceField(choices=ParcelRequest.ItemType.choices)
    handling_notes = serializers.CharField(
        max_length=2000,
        required=False,
        allow_blank=True,
        default="",
    )
    fragile = serializers.BooleanField(required=False, default=False)
    target_traveler_id = serializers.PrimaryKeyRelatedField(
        source="target_traveler",
        queryset=get_user_model().objects.all(),
        required=False,
        allow_null=True,
    )
    description_is_accurate = serializers.BooleanField()
    item_is_legal = serializers.BooleanField()
    no_prohibited_goods = serializers.BooleanField()
    declared_value_is_accurate = serializers.BooleanField()
    customs_responsibilities_understood = serializers.BooleanField()

    def validate(self, attrs: dict) -> dict:
        unexpected = set(self.initial_data) - set(self.fields)
        if unexpected:
            raise serializers.ValidationError(
                {
                    field: "This field is not accepted by the V1 delivery contract."
                    for field in sorted(unexpected)
                }
            )
        request = self.context["request"]
        pickup = attrs["pickup_location"]
        delivery = attrs["delivery_location"]

        # A parcel owner receives exact nested location data. Requiring ownership
        # here prevents a sender from using a guessed Location ID to disclose
        # another user's private address through the parcel response.
        location_errors = {}
        if pickup.owner_id != request.user.id:
            location_errors["pickup_location_id"] = (
                "Pickup location must belong to the authenticated sender."
            )
        if delivery.owner_id != request.user.id:
            location_errors["delivery_location_id"] = (
                "Delivery location must belong to the authenticated sender."
            )
        if location_errors:
            raise serializers.ValidationError(location_errors)
        if pickup.pk == delivery.pk:
            raise serializers.ValidationError(
                {"delivery_location_id": "Pickup and delivery locations must differ."}
            )

        ready_start = attrs["ready_window_start"]
        ready_end = attrs["ready_window_end"]
        deadline = attrs["deadline_at"]
        if ready_start >= ready_end:
            raise serializers.ValidationError(
                {"ready_window_end": "Ready window end must be after its start."}
            )
        if ready_end > deadline:
            raise serializers.ValidationError(
                {"deadline_at": "Deadline must be at or after the ready window end."}
            )
        if deadline <= timezone.now():
            raise serializers.ValidationError(
                {"deadline_at": "Deadline must be in the future."}
            )

        dimensions = [
            attrs.get(name) for name in ("length_cm", "width_cm", "height_cm")
        ]
        if any(value is not None for value in dimensions) and any(
            value is None for value in dimensions
        ):
            raise serializers.ValidationError(
                {"dimensions": "Length, width, and height must be supplied together."}
            )

        declaration_fields = (
            "description_is_accurate",
            "item_is_legal",
            "no_prohibited_goods",
            "declared_value_is_accurate",
            "customs_responsibilities_understood",
        )
        declaration_errors = {
            field: "This safety declaration must be confirmed."
            for field in declaration_fields
            if attrs[field] is not True
        }
        if declaration_errors:
            raise serializers.ValidationError(declaration_errors)

        target = attrs.get("target_traveler")
        if target is not None and target.pk == request.user.pk:
            raise serializers.ValidationError(
                {"target_traveler_id": "A sender cannot target their own account."}
            )
        return attrs


class ProductCreateSerializer(_ParcelBase):
    product_url = serializers.URLField(
        required=False, allow_blank=True, max_length=500, default=""
    )
    store_name = serializers.CharField(
        required=False, allow_blank=True, max_length=120, default=""
    )
    product_price_dzd = serializers.IntegerField(min_value=100, max_value=10_000_000)


class ParcelRequestSerializer(serializers.ModelSerializer):
    """Read serializer — picks subtype-specific fields off the concrete row."""

    sender_id = serializers.IntegerField(source="sender.id", read_only=True)
    target_traveler_id = serializers.IntegerField(read_only=True, allow_null=True)
    origin = AirportSerializer(read_only=True)
    destination = AirportSerializer(read_only=True)
    media = ParcelMediaSerializer(many=True, read_only=True)

    base_amount_dzd = serializers.SerializerMethodField()
    product_url = serializers.SerializerMethodField()
    store_name = serializers.SerializerMethodField()
    product_price_dzd = serializers.SerializerMethodField()
    schema_version = serializers.SerializerMethodField()
    pickup_location = serializers.SerializerMethodField()
    delivery_location = serializers.SerializerMethodField()
    ready_window_start = serializers.SerializerMethodField()
    ready_window_end = serializers.SerializerMethodField()
    actual_weight_kg = serializers.SerializerMethodField()
    length_cm = serializers.SerializerMethodField()
    width_cm = serializers.SerializerMethodField()
    height_cm = serializers.SerializerMethodField()
    declared_value_eur_cents = serializers.SerializerMethodField()
    sender_proposed_reward_eur_cents = serializers.SerializerMethodField()
    title = serializers.SerializerMethodField()
    category = serializers.SerializerMethodField()
    handling_notes = serializers.SerializerMethodField()
    fragile = serializers.SerializerMethodField()
    description_is_accurate = serializers.SerializerMethodField()
    item_is_legal = serializers.SerializerMethodField()
    no_prohibited_goods = serializers.SerializerMethodField()
    declared_value_is_accurate = serializers.SerializerMethodField()
    customs_responsibilities_understood = serializers.SerializerMethodField()

    class Meta:
        model = ParcelRequest
        fields = (
            "id",
            "sender_id",
            "target_traveler_id",
            "kind",
            "origin",
            "destination",
            "pickup_city",
            "delivery_city",
            "weight_kg",
            "item_type",
            "description",
            "deadline_at",
            "status",
            "media",
            "base_amount_dzd",
            "schema_version",
            "pickup_location",
            "delivery_location",
            "ready_window_start",
            "ready_window_end",
            "actual_weight_kg",
            "length_cm",
            "width_cm",
            "height_cm",
            "declared_value_eur_cents",
            "sender_proposed_reward_eur_cents",
            "title",
            "category",
            "handling_notes",
            "fragile",
            "description_is_accurate",
            "item_is_legal",
            "no_prohibited_goods",
            "declared_value_is_accurate",
            "customs_responsibilities_understood",
            "product_url",
            "store_name",
            "product_price_dzd",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def _delivery(self, obj: ParcelRequest) -> DeliveryRequest | None:
        if obj.kind != ParcelRequest.Kind.DELIVERY:
            return None
        if isinstance(obj, DeliveryRequest):
            return obj
        try:
            return obj.deliveryrequest
        except DeliveryRequest.DoesNotExist:
            return None

    def _product(self, obj: ParcelRequest) -> ProductRequest | None:
        if obj.kind != ParcelRequest.Kind.PRODUCT:
            return None
        if isinstance(obj, ProductRequest):
            return obj
        try:
            return obj.productrequest
        except ProductRequest.DoesNotExist:
            return None

    def get_base_amount_dzd(self, obj: ParcelRequest) -> int | None:
        d = self._delivery(obj)
        return d.base_amount_dzd if d else None

    def get_schema_version(self, obj: ParcelRequest) -> int | None:
        d = self._delivery(obj)
        return d.schema_version if d else None

    def _location(self, obj: ParcelRequest, field: str) -> dict | None:
        d = self._delivery(obj)
        location = getattr(d, field, None) if d else None
        if location is None:
            return None
        request = self.context.get("request")
        may_see_exact = False
        if request is not None and request.user.is_authenticated:
            may_see_exact = d.sender_id == request.user.id
            if not may_see_exact:
                # Funding is the privacy boundary. Offer acceptance alone must
                # never disclose a sender's exact pickup/delivery location.
                may_see_exact = any(
                    deal.traveler_id == request.user.id and deal.funded_at is not None
                    for deal in d.deals.all()
                )
        if may_see_exact:
            return PrivateLocationSerializer(location, context=self.context).data
        return PublicLocationSerializer(location, context=self.context).data

    def get_pickup_location(self, obj: ParcelRequest) -> dict | None:
        return self._location(obj, "pickup_location")

    def get_delivery_location(self, obj: ParcelRequest) -> dict | None:
        return self._location(obj, "delivery_location")

    def get_ready_window_start(self, obj: ParcelRequest):
        d = self._delivery(obj)
        return d.ready_window_start if d else None

    def get_ready_window_end(self, obj: ParcelRequest):
        d = self._delivery(obj)
        return d.ready_window_end if d else None

    def get_actual_weight_kg(self, obj: ParcelRequest) -> str | None:
        d = self._delivery(obj)
        return str(d.actual_weight_kg) if d and d.actual_weight_kg is not None else None

    def _decimal(self, obj: ParcelRequest, field: str) -> str | None:
        d = self._delivery(obj)
        value = getattr(d, field, None) if d else None
        return str(value) if value is not None else None

    def get_length_cm(self, obj: ParcelRequest) -> str | None:
        return self._decimal(obj, "length_cm")

    def get_width_cm(self, obj: ParcelRequest) -> str | None:
        return self._decimal(obj, "width_cm")

    def get_height_cm(self, obj: ParcelRequest) -> str | None:
        return self._decimal(obj, "height_cm")

    def _delivery_value(self, obj: ParcelRequest, field: str):
        d = self._delivery(obj)
        return getattr(d, field, None) if d else None

    def get_declared_value_eur_cents(self, obj: ParcelRequest) -> int | None:
        return self._delivery_value(obj, "declared_value_eur_cents")

    def get_sender_proposed_reward_eur_cents(self, obj: ParcelRequest) -> int | None:
        """Sender's posted intent only; Offer.traveler_reward_minor is agreed."""

        return self._delivery_value(obj, "traveler_reward_eur_cents")

    def get_title(self, obj: ParcelRequest) -> str | None:
        return self._delivery_value(obj, "title")

    def get_category(self, obj: ParcelRequest) -> str | None:
        return self._delivery_value(obj, "category")

    def get_handling_notes(self, obj: ParcelRequest) -> str | None:
        return self._delivery_value(obj, "handling_notes")

    def get_fragile(self, obj: ParcelRequest) -> bool | None:
        return self._delivery_value(obj, "fragile")

    def get_description_is_accurate(self, obj: ParcelRequest) -> bool | None:
        return self._delivery_value(obj, "description_is_accurate")

    def get_item_is_legal(self, obj: ParcelRequest) -> bool | None:
        return self._delivery_value(obj, "item_is_legal")

    def get_no_prohibited_goods(self, obj: ParcelRequest) -> bool | None:
        return self._delivery_value(obj, "no_prohibited_goods")

    def get_declared_value_is_accurate(self, obj: ParcelRequest) -> bool | None:
        return self._delivery_value(obj, "declared_value_is_accurate")

    def get_customs_responsibilities_understood(
        self, obj: ParcelRequest
    ) -> bool | None:
        return self._delivery_value(obj, "customs_responsibilities_understood")

    def get_product_url(self, obj: ParcelRequest) -> str | None:
        p = self._product(obj)
        return p.product_url if p else None

    def get_store_name(self, obj: ParcelRequest) -> str | None:
        p = self._product(obj)
        return p.store_name if p else None

    def get_product_price_dzd(self, obj: ParcelRequest) -> int | None:
        p = self._product(obj)
        return p.product_price_dzd if p else None
