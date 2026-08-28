from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("matching", "0006_match_phase2_snapshots")]

    operations = [
        migrations.AlterField(
            model_name="offer",
            name="economics_version",
            field=models.CharField(
                choices=[("legacy_dzd", "Legacy DZD"), ("v1_eur", "V1 EUR")],
                db_index=True,
                max_length=16,
            ),
        ),
    ]
