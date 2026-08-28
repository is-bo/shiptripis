from decimal import Decimal

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("locations", "0001_initial"),
        ("parcels", "0002_parcel_target_traveler"),
    ]

    operations = [
        migrations.AlterField(
            model_name="parcelrequest",
            name="origin",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="parcels_from",
                to="trips.airport",
            ),
        ),
        migrations.AlterField(
            model_name="parcelrequest",
            name="destination",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="parcels_to",
                to="trips.airport",
            ),
        ),
        migrations.AlterField(
            model_name="parcelrequest",
            name="weight_kg",
            field=models.PositiveSmallIntegerField(
                blank=True,
                help_text=(
                    "Legacy integer weight. V1 uses "
                    "DeliveryRequest.actual_weight_kg."
                ),
                null=True,
                validators=[django.core.validators.MinValueValidator(1)],
            ),
        ),
        migrations.AlterField(
            model_name="deliveryrequest",
            name="base_amount_dzd",
            field=models.PositiveIntegerField(
                blank=True,
                help_text="Legacy proposed payout in DZD. Null for V1 EUR requests.",
                null=True,
                validators=[django.core.validators.MinValueValidator(100)],
            ),
        ),
        migrations.AddField(
            model_name="deliveryrequest",
            name="schema_version",
            field=models.PositiveSmallIntegerField(
                default=1,
                help_text=(
                    "1 is the legacy airport/DZD contract; "
                    "2 is the V1 location/EUR contract."
                ),
                validators=[
                    django.core.validators.MinValueValidator(1),
                    django.core.validators.MaxValueValidator(2),
                ],
            ),
        ),
        migrations.AddField(
            model_name="deliveryrequest",
            name="pickup_location",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="delivery_requests_from",
                to="locations.location",
            ),
        ),
        migrations.AddField(
            model_name="deliveryrequest",
            name="delivery_location",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="delivery_requests_to",
                to="locations.location",
            ),
        ),
        migrations.AddField(
            model_name="deliveryrequest",
            name="ready_window_start",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="deliveryrequest",
            name="ready_window_end",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="deliveryrequest",
            name="actual_weight_kg",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                max_digits=6,
                null=True,
                validators=[
                    django.core.validators.MinValueValidator(Decimal("0.01")),
                    django.core.validators.MaxValueValidator(Decimal("100.00")),
                ],
            ),
        ),
        migrations.AddField(
            model_name="deliveryrequest",
            name="length_cm",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                max_digits=6,
                null=True,
                validators=[
                    django.core.validators.MinValueValidator(Decimal("0.01")),
                    django.core.validators.MaxValueValidator(Decimal("500.00")),
                ],
            ),
        ),
        migrations.AddField(
            model_name="deliveryrequest",
            name="width_cm",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                max_digits=6,
                null=True,
                validators=[
                    django.core.validators.MinValueValidator(Decimal("0.01")),
                    django.core.validators.MaxValueValidator(Decimal("500.00")),
                ],
            ),
        ),
        migrations.AddField(
            model_name="deliveryrequest",
            name="height_cm",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                max_digits=6,
                null=True,
                validators=[
                    django.core.validators.MinValueValidator(Decimal("0.01")),
                    django.core.validators.MaxValueValidator(Decimal("500.00")),
                ],
            ),
        ),
        migrations.AddField(
            model_name="deliveryrequest",
            name="declared_value_eur_cents",
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="deliveryrequest",
            name="traveler_reward_eur_cents",
            field=models.PositiveBigIntegerField(
                blank=True,
                help_text="Sender-proposed traveler reward in canonical EUR cents.",
                null=True,
                validators=[django.core.validators.MinValueValidator(1)],
            ),
        ),
        migrations.AddField(
            model_name="deliveryrequest",
            name="title",
            field=models.CharField(blank=True, default="", max_length=160),
        ),
        migrations.AddField(
            model_name="deliveryrequest",
            name="category",
            field=models.CharField(
                blank=True,
                choices=[
                    ("documents", "Documents"),
                    ("small_box", "Small box"),
                    ("electronics", "Electronics"),
                    ("clothing", "Clothing"),
                    ("other", "Other"),
                ],
                default="",
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name="deliveryrequest",
            name="handling_notes",
            field=models.TextField(blank=True, default="", max_length=2000),
        ),
        migrations.AddField(
            model_name="deliveryrequest",
            name="fragile",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="deliveryrequest",
            name="description_is_accurate",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="deliveryrequest",
            name="item_is_legal",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="deliveryrequest",
            name="no_prohibited_goods",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="deliveryrequest",
            name="declared_value_is_accurate",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="deliveryrequest",
            name="customs_responsibilities_understood",
            field=models.BooleanField(default=False),
        ),
        migrations.AddIndex(
            model_name="deliveryrequest",
            index=models.Index(
                fields=["schema_version", "pickup_location", "delivery_location"],
                name="parcels_v1_route_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="deliveryrequest",
            constraint=models.CheckConstraint(
                condition=models.Q(("schema_version__in", (1, 2))),
                name="parcels_delivery_schema_ver",
            ),
        ),
        migrations.AddConstraint(
            model_name="deliveryrequest",
            constraint=models.CheckConstraint(
                condition=models.Q(("schema_version", 1))
                | (
                    models.Q(("pickup_location__isnull", False))
                    & models.Q(("delivery_location__isnull", False))
                    & models.Q(("ready_window_start__isnull", False))
                    & models.Q(("ready_window_end__isnull", False))
                    & models.Q(("actual_weight_kg__isnull", False))
                    & models.Q(("declared_value_eur_cents__isnull", False))
                    & models.Q(("traveler_reward_eur_cents__isnull", False))
                ),
                name="parcels_delivery_v1_required",
            ),
        ),
        migrations.AddConstraint(
            model_name="deliveryrequest",
            constraint=models.CheckConstraint(
                condition=models.Q(("pickup_location__isnull", True))
                | models.Q(("delivery_location__isnull", True))
                | ~models.Q(("pickup_location", models.F("delivery_location"))),
                name="parcels_delivery_locations_differ",
            ),
        ),
        migrations.AddConstraint(
            model_name="deliveryrequest",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(("ready_window_start__isnull", True))
                    & models.Q(("ready_window_end__isnull", True))
                )
                | (
                    models.Q(("ready_window_start__isnull", False))
                    & models.Q(("ready_window_end__isnull", False))
                    & models.Q(("ready_window_start__lt", models.F("ready_window_end")))
                ),
                name="parcels_delivery_ready_window",
            ),
        ),
        migrations.AddConstraint(
            model_name="deliveryrequest",
            constraint=models.CheckConstraint(
                condition=models.Q(("actual_weight_kg__isnull", True))
                | (
                    models.Q(("actual_weight_kg__gt", 0))
                    & models.Q(("actual_weight_kg__lte", 100))
                ),
                name="parcels_delivery_weight_range",
            ),
        ),
        migrations.AddConstraint(
            model_name="deliveryrequest",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(("length_cm__isnull", True))
                    & models.Q(("width_cm__isnull", True))
                    & models.Q(("height_cm__isnull", True))
                )
                | (
                    models.Q(("length_cm__gt", 0), ("length_cm__lte", 500))
                    & models.Q(("width_cm__gt", 0), ("width_cm__lte", 500))
                    & models.Q(("height_cm__gt", 0), ("height_cm__lte", 500))
                ),
                name="parcels_delivery_dimensions",
            ),
        ),
        migrations.AddConstraint(
            model_name="deliveryrequest",
            constraint=models.CheckConstraint(
                condition=models.Q(("schema_version", 1))
                | (
                    models.Q(("description_is_accurate", True))
                    & models.Q(("item_is_legal", True))
                    & models.Q(("no_prohibited_goods", True))
                    & models.Q(("declared_value_is_accurate", True))
                    & models.Q(("customs_responsibilities_understood", True))
                ),
                name="parcels_delivery_v1_safety",
            ),
        ),
    ]
