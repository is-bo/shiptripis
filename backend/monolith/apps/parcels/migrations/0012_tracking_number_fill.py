"""L11A, step 2 of 3: give every existing request its own tracking number."""

from django.db import migrations

from apps.parcels import tracking


def fill(apps, schema_editor):
    ParcelRequest = apps.get_model("parcels", "ParcelRequest")
    taken = set(
        ParcelRequest.objects.exclude(tracking_number=None).values_list(
            "tracking_number", flat=True
        )
    )
    pending = list(ParcelRequest.objects.filter(tracking_number=None).only("pk"))
    for row in pending:
        number = tracking.generate()
        while number in taken:
            number = tracking.generate()
        taken.add(number)
        row.tracking_number = number
    ParcelRequest.objects.bulk_update(pending, ["tracking_number"], batch_size=500)


class Migration(migrations.Migration):

    dependencies = [
        ("parcels", "0011_tracking_number_add"),
    ]

    operations = [
        migrations.RunPython(fill, migrations.RunPython.noop),
    ]
