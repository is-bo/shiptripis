from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("matching", "0005_remove_offer_offer_economics_consistent_and_more")]

    operations = [
        migrations.AddField(
            model_name="match",
            name="compatibility_snapshot",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="match",
            name="matched_distance_meters",
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="match",
            name="matching_version",
            field=models.CharField(blank=True, default="", max_length=32),
        ),
        migrations.AddField(
            model_name="match",
            name="ranking_snapshot",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddIndex(
            model_name="match",
            index=models.Index(
                fields=["journey", "matching_version", "status"],
                name="match_journey_version_idx",
            ),
        ),
    ]

