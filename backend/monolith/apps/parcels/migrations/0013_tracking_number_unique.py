"""L11A, step 3 of 3: every row has a number, so it becomes required and unique."""

import apps.parcels.tracking
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("parcels", "0012_tracking_number_fill"),
    ]

    operations = [
        migrations.AlterField(
            model_name="parcelrequest",
            name="tracking_number",
            field=models.CharField(
                default=apps.parcels.tracking.generate,
                editable=False,
                max_length=12,
                unique=True,
            ),
        ),
    ]
