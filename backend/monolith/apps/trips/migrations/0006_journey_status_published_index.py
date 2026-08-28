from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("trips", "0005_journey_leg_route_snapshot")]

    operations = [
        migrations.AddIndex(
            model_name="journey",
            index=models.Index(
                fields=["status", "-published_at"],
                name="journey_status_published_idx",
            ),
        )
    ]
