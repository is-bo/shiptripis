from __future__ import annotations

from django.utils import timezone
from rest_framework import serializers

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
    origin = AirportSerializer(read_only=True)
    destination = AirportSerializer(read_only=True)
    media = ParcelMediaSerializer(many=True, read_only=True)

    base_amount_dzd = serializers.SerializerMethodField()
    product_url = serializers.SerializerMethodField()
    store_name = serializers.SerializerMethodField()
    product_price_dzd = serializers.SerializerMethodField()

    class Meta:
        model = ParcelRequest
        fields = (
            "id",
            "sender_id",
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
        return DeliveryRequest.objects.filter(pk=obj.pk).first()

    def _product(self, obj: ParcelRequest) -> ProductRequest | None:
        if obj.kind != ParcelRequest.Kind.PRODUCT:
            return None
        if isinstance(obj, ProductRequest):
            return obj
        return ProductRequest.objects.filter(pk=obj.pk).first()

    def get_base_amount_dzd(self, obj: ParcelRequest) -> int | None:
        d = self._delivery(obj)
        return d.base_amount_dzd if d else None

    def get_product_url(self, obj: ParcelRequest) -> str | None:
        p = self._product(obj)
        return p.product_url if p else None

    def get_store_name(self, obj: ParcelRequest) -> str | None:
        p = self._product(obj)
        return p.store_name if p else None

    def get_product_price_dzd(self, obj: ParcelRequest) -> int | None:
        p = self._product(obj)
        return p.product_price_dzd if p else None
