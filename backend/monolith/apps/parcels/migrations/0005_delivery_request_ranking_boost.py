from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("parcels", "0004_deliveryrequest_parcels_delivery_v1_no_dzd")]

    operations = [
        migrations.AddField(
            model_name="deliveryrequest",
            name="ranking_boost_expires_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="deliveryrequest",
            name="ranking_boost_weight",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddIndex(
            model_name="deliveryrequest",
            index=models.Index(
                fields=["schema_version", "ready_window_start", "ready_window_end"],
                name="parcels_v1_ready_window_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="deliveryrequest",
            index=models.Index(
                fields=["ranking_boost_expires_at"],
                name="parcels_boost_expiry_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="deliveryrequest",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        ranking_boost_expires_at__isnull=True,
                        ranking_boost_weight=0,
                    )
                    | models.Q(
                        ranking_boost_expires_at__isnull=False,
                        ranking_boost_weight__gt=0,
                    )
                ),
                name="parcels_ranking_boost_pair",
            ),
        ),
    ]

