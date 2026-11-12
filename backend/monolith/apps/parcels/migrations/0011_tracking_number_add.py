"""L11A, step 1 of 3: add the tracking number, empty and not yet unique.

Django's documented way to add a unique column whose value is generated per
row: add it nullable, fill every row (0012), then make it required and unique
(0013).
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("parcels", "0010_j2_boost_reward"),
    ]

    operations = [
        migrations.AddField(
            model_name="parcelrequest",
            name="tracking_number",
            field=models.CharField(editable=False, max_length=12, null=True),
        ),
    ]
