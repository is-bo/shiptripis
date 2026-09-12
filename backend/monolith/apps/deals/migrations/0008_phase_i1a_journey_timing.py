"""Phase I1A: the funded arrival basis, early-arrival claims, and the backfill.

Additive throughout. Three nullable Deal columns, one new table, four new
`DealEvent` kinds, and one data step that never invents a timestamp.

**The backfill, and its limits.** A Deal funded before I1A has no arrival
snapshot, so its payout floor would be null and its eligibility would keep the
pre-I1A rule. That is safe but it leaves the anti-abuse floor off exactly the
Deals that are in flight today, so where the funded schedule can be recovered
*deterministically* it is recovered, with its provenance recorded.

The one recoverable source is the accepted `Match.compatibility_snapshot`, whose
`delivery_at` was computed by the server when the match was made and is never
rewritten -- the same value `apps.deals.arrival` prefers for a new Deal. Journey
leg rows are deliberately **not** read: they are mutable in principle, so a leg
time today is not evidence of what was agreed at funding, and inferring one
would be the "blind bulk timestamp inference" this phase forbids.

Two guards keep the step from changing an outcome that has already been decided:

* only Deals whose payout has not been released (absent, `not_eligible` or
  `frozen`) are touched, so no eligible, scheduled, sent, paid or cancelled
  payout can move;
* only Deals that are not already closed are touched.

Where `delivery_at` is missing or unparseable the floor stays null and the
snapshot records `basis="unavailable"`. A null floor cannot make any payout
eligible *earlier* than it already was -- `payout_release_gate_at` takes a `max`
-- so the legacy fallback is strictly no-op in the dangerous direction.

Reverse is a no-op: the columns are dropped by the schema reversal, and there is
nothing to un-backfill.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.utils.dateparse import parse_datetime

#: Kept local to the migration on purpose. Importing the application constant
#: would make a historical migration follow a value that is allowed to change.
LEGACY_PROVENANCE = "legacy_match_snapshot_v1"
LEGACY_POLICY_VERSION = "i1a.v1"
LEGACY_THRESHOLD_SECONDS = 21_600
BASIS_MATCH_DELIVERY = "match_delivery_interpolation"
BASIS_UNAVAILABLE = "unavailable"

#: Payout states in which no release decision has been taken yet, so adding a
#: floor cannot contradict one.
UNRELEASED_PAYOUT_STATUSES = ("not_eligible", "frozen")

CLOSED_DEAL_STATUSES = (
    "cancelled",
    "expired",
    "refunded",
    "partially_refunded",
    "payment_failed",
)


def backfill_arrival_basis(apps, schema_editor):
    from django.utils import timezone

    Deal = apps.get_model("deals", "Deal")
    Payout = apps.get_model("finance", "Payout")

    released_deal_ids = set(
        Payout.objects.exclude(status__in=UNRELEASED_PAYOUT_STATUSES).values_list(
            "deal_id", flat=True
        )
    )
    now = timezone.now()
    candidates = (
        Deal.objects.filter(funded_at__isnull=False)
        .filter(funded_scheduled_arrival_floor_at__isnull=True)
        .exclude(status__in=CLOSED_DEAL_STATUSES)
        .exclude(pk__in=released_deal_ids)
        .select_related("match")
        .only("id", "journey_id", "match_id", "arrival_snapshot")
    )
    for deal in candidates.iterator(chunk_size=200):
        match = deal.match
        raw = (getattr(match, "compatibility_snapshot", None) or {}).get("delivery_at")
        parsed = parse_datetime(raw) if isinstance(raw, str) and raw else None
        if parsed is not None and timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed, timezone.get_default_timezone())
        deal.funded_scheduled_arrival_floor_at = parsed
        deal.arrival_snapshot = {
            "policy_version": LEGACY_POLICY_VERSION,
            "provenance": LEGACY_PROVENANCE,
            "snapshot_at": now.isoformat(),
            "stored_timezone": "UTC",
            "material_early_threshold_seconds": LEGACY_THRESHOLD_SECONDS,
            "journey_id": deal.journey_id,
            "journey_schema_version": None,
            "match_id": deal.match_id,
            "matching_version": str(
                getattr(match, "matching_version", "") or ""
            ),
            "basis": BASIS_MATCH_DELIVERY if parsed else BASIS_UNAVAILABLE,
            "scheduled_arrival_at": parsed.isoformat() if parsed else None,
            "arrival_leg_id": None,
            "arrival_leg_position": None,
            # Deliberately empty. The funded route cannot be recovered from
            # mutable leg rows, so the sender's route projection falls back to
            # the live Journey and says `basis="live_journey"` rather than
            # presenting a reconstruction as a frozen record.
            "route": [],
        }
        deal.save(
            update_fields=["funded_scheduled_arrival_floor_at", "arrival_snapshot"]
        )


def unbackfill(apps, schema_editor):
    """Nothing to undo: the columns themselves are reversed by the schema."""


class Migration(migrations.Migration):

    dependencies = [
        ('deals', '0007_dealtermssnapshot_boost_amount_minor_and_more'),
        ('finance', '0024_phase8fh4_manual_guards'),
        ('matching', '0007_offer_economics_version_required'),
        ('parcels', '0009_phase8fb_staged_parcel_media'),
        ('trips', '0008_journeylegproof_idempotency_key_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='DealArrivalReport',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('reported_at', models.DateTimeField()),
                ('reported_deal_status', models.CharField(max_length=24)),
                ('scheduled_arrival_at', models.DateTimeField()),
                ('early_by_seconds', models.PositiveIntegerField()),
                ('threshold_seconds', models.PositiveIntegerField()),
                ('basis', models.CharField(max_length=48)),
                ('status', models.CharField(choices=[('pending_confirmation', 'Awaiting sender confirmation'), ('confirmed', 'Confirmed by the sender'), ('declined', 'Declined by the sender')], db_index=True, default='pending_confirmation', max_length=24)),
                ('decided_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'db_table': 'deals_arrival_report',
                'ordering': ['-reported_at', '-id'],
            },
        ),
        migrations.AddField(
            model_name='deal',
            name='arrival_confirmed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='deal',
            name='arrival_snapshot',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='deal',
            name='funded_scheduled_arrival_floor_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='dealevent',
            name='kind',
            field=models.CharField(choices=[('created', 'Created'), ('status_changed', 'Status changed'), ('capacity_reserved', 'Capacity reserved'), ('capacity_released', 'Capacity released'), ('recipient_set', 'Recipient details set'), ('recipient_changed', 'Recipient details changed'), ('pickup_code_issued', 'Pickup code issued'), ('pickup_code_rotated', 'Pickup code rotated'), ('pickup_code_failed', 'Pickup code attempt failed'), ('pickup_code_locked', 'Pickup code locked'), ('pickup_confirmed', 'Pickup confirmed'), ('delivery_buffer_started', 'Delivery-code safety buffer started'), ('delivery_code_released', 'Delivery code released to the sender'), ('delivery_code_rotated', 'Delivery code rotated'), ('delivery_code_failed', 'Delivery code attempt failed'), ('delivery_code_locked', 'Delivery code locked'), ('recipient_notification_queued', 'Recipient delivery-code notification queued'), ('recipient_notification_sent', 'Recipient delivery-code notification dispatched'), ('delivery_confirmed', 'Delivery confirmed'), ('arrival_snapshot_frozen', 'Funded arrival basis frozen'), ('early_arrival_reported', 'Traveler reported an early arrival'), ('early_arrival_confirmed', 'Sender confirmed the early arrival'), ('early_arrival_declined', 'Sender declined the early arrival'), ('protection_started', 'Protection window started'), ('protection_expired', 'Protection window expired'), ('payout_eligible', 'Payout became eligible'), ('payout_status_changed', 'Payout status changed'), ('dispute_opened', 'Dispute opened'), ('dispute_evidence_added', 'Dispute evidence added'), ('dispute_status_changed', 'Dispute status changed'), ('dispute_resolved', 'Dispute resolved'), ('cancellation_requested', 'Cancellation requested'), ('cancelled_after_funding', 'Cancelled after funding'), ('compensation_applied', 'Cancellation compensation'), ('no_show_recorded', 'No-show recorded'), ('rating_submitted', 'Rating submitted'), ('rating_revealed', 'Ratings revealed')], max_length=32),
        ),
        migrations.AddConstraint(
            model_name='deal',
            constraint=models.CheckConstraint(condition=models.Q(('arrival_confirmed_at__isnull', True), ('funded_at__isnull', False), _connector='OR'), name='deals_arrival_requires_funding'),
        ),
        migrations.AddConstraint(
            model_name='deal',
            constraint=models.CheckConstraint(condition=models.Q(('funded_scheduled_arrival_floor_at__isnull', True), ('funded_at__isnull', False), _connector='OR'), name='deals_arrival_floor_requires_funding'),
        ),
        migrations.AddField(
            model_name='dealarrivalreport',
            name='deal',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='arrival_reports', to='deals.deal'),
        ),
        migrations.AddField(
            model_name='dealarrivalreport',
            name='decided_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='deal_arrivals_decided', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='dealarrivalreport',
            name='reported_by',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='deal_arrivals_reported', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddIndex(
            model_name='dealarrivalreport',
            index=models.Index(fields=['deal', '-reported_at'], name='deals_arrival_deal_idx'),
        ),
        migrations.AddIndex(
            model_name='dealarrivalreport',
            index=models.Index(fields=['status', '-reported_at'], name='deals_arrival_open_idx'),
        ),
        migrations.AddConstraint(
            model_name='dealarrivalreport',
            constraint=models.UniqueConstraint(condition=models.Q(('status', 'pending_confirmation')), fields=('deal',), name='deals_arrival_one_open_per_deal'),
        ),
        migrations.AddConstraint(
            model_name='dealarrivalreport',
            constraint=models.UniqueConstraint(condition=models.Q(('status', 'confirmed')), fields=('deal',), name='deals_arrival_one_confirmed_per_deal'),
        ),
        migrations.AddConstraint(
            model_name='dealarrivalreport',
            constraint=models.CheckConstraint(condition=models.Q(('early_by_seconds__gt', 0)), name='deals_arrival_positive_earliness'),
        ),
        migrations.AddConstraint(
            model_name='dealarrivalreport',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('decided_at__isnull', True), ('decided_by__isnull', True), ('status', 'pending_confirmation')), models.Q(('decided_at__isnull', False), ('decided_by__isnull', False), ('status__in', ['confirmed', 'declined'])), _connector='OR'), name='deals_arrival_decision_complete'),
        ),
        migrations.RunPython(backfill_arrival_basis, unbackfill),
    ]
