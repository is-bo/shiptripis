from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("trips", "0004_journey_journeyleg_journeylegproof")]

    operations = [
        migrations.AddField(
            model_name="journeyleg",
            name="route_captured_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="journeyleg",
            name="route_duration_seconds",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="journeyleg",
            name="route_profile",
            field=models.CharField(blank=True, default="", max_length=32),
        ),
        migrations.AddField(
            model_name="journeyleg",
            name="route_provider",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddIndex(
            model_name="journeyleg",
            index=models.Index(
                fields=["journey", "depart_at", "arrive_at"],
                name="journey_leg_time_window_idx",
            ),
        ),
    ]

