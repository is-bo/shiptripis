from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("locations", "0002_remove_location_locations_provider_place_uniq_and_more")
    ]

    operations = [
        migrations.AddField(
            model_name="location",
            name="coordinate_dataset_version",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="location",
            name="coordinates_trusted",
            field=models.BooleanField(db_index=True, default=False),
        ),
        migrations.AddConstraint(
            model_name="location",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        coordinate_dataset_version="",
                        coordinates_trusted=False,
                    )
                    | (
                        models.Q(coordinates_trusted=True)
                        & ~models.Q(coordinate_dataset_version="")
                    )
                ),
                name="locations_coordinate_trust_pair",
            ),
        ),
    ]
