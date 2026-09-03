"""Make flight-proof upload retry-safe.

A phone on a weak connection retries; without a key to recognise the retry
by, each attempt writes another row and a reviewer sees three copies of one
boarding pass. The key is client-supplied, scoped to the leg, and optional —
a client that sends none keeps today's behaviour, so the partial unique index
excludes the empty string rather than treating every unkeyed row as a clash.

Additive: a nullable-equivalent column with a default and a partial index. No
backfill, no rewrite, no lock beyond the metadata change.
"""

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('trips', '0007_remove_journey_journey_distinct_endpoints_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='journeylegproof',
            name='idempotency_key',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
        migrations.AddConstraint(
            model_name='journeylegproof',
            constraint=models.UniqueConstraint(condition=models.Q(('idempotency_key', ''), _negated=True), fields=('leg', 'idempotency_key'), name='journey_proof_unique_idempotency_key'),
        ),
    ]
