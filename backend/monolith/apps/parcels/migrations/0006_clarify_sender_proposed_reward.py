"""Phase 2B MINOR-2: document that the posted reward is intent, not a price.

Help-text only. `sqlmigrate` emits `-- (no-op)`: no column, type, constraint or
index changes, so `contracts/sql/schema.sql` is unaffected. The column name is
retained for audit continuity; the API exposes it as
`sender_proposed_reward_eur_cents`.
"""

import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("parcels", "0005_delivery_request_ranking_boost"),
    ]

    operations = [
        migrations.AlterField(
            model_name="deliveryrequest",
            name="traveler_reward_eur_cents",
            field=models.PositiveBigIntegerField(
                blank=True,
                help_text=(
                    "Sender-posted intended reward in canonical EUR cents. "
                    "Non-binding and non-authoritative; "
                    "Offer.traveler_reward_minor is the agreed reward."
                ),
                null=True,
                validators=[django.core.validators.MinValueValidator(1)],
            ),
        ),
    ]
