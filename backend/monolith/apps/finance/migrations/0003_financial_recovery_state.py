from django.db import migrations, models


def migrate_event_states_forward(apps, schema_editor):
    event = apps.get_model("finance", "PaymentProviderEvent")
    event.objects.filter(processing_result="pending").update(
        processing_result="received"
    )
    event.objects.filter(processing_result="failed").update(
        processing_result="retryable"
    )


def migrate_event_states_reverse(apps, schema_editor):
    event = apps.get_model("finance", "PaymentProviderEvent")
    event.objects.filter(
        processing_result__in=("received", "processing", "retryable")
    ).update(processing_result="pending")


class Migration(migrations.Migration):
    dependencies = [("finance", "0002_paymentrefund_settled_by_and_more")]

    operations = [
        migrations.AddField(
            model_name="paymentproviderevent",
            name="last_error_code",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="paymentproviderevent",
            name="last_error_message",
            field=models.CharField(blank=True, default="", max_length=500),
        ),
        migrations.AddField(
            model_name="paymentproviderevent",
            name="next_retry_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="paymentproviderevent",
            name="normalized_event",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="Safe normalized fields required to re-drive processing.",
            ),
        ),
        migrations.AddField(
            model_name="paymentproviderevent",
            name="payload_fingerprint",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="paymentproviderevent",
            name="processing_attempts",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="paymentproviderevent",
            name="processing_started_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="paymentrefund",
            name="last_provider_check_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="paymentrefund",
            name="next_retry_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="paymentrefund",
            name="processing_attempts",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="paymentrefund",
            name="processing_started_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="paymentrefund",
            name="requires_manual_action",
            field=models.BooleanField(db_index=True, default=False),
        ),
        migrations.RunPython(
            migrate_event_states_forward,
            migrate_event_states_reverse,
        ),
        migrations.AlterField(
            model_name="paymentproviderevent",
            name="processing_result",
            field=models.CharField(
                choices=[
                    ("received", "Received"),
                    ("processing", "Processing"),
                    ("applied", "Applied"),
                    ("ignored", "Ignored"),
                    ("retryable", "Retryable"),
                    ("failed", "Failed"),
                ],
                default="received",
                max_length=12,
            ),
        ),
        migrations.AlterField(
            model_name="paymentrefund",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("processing", "Processing"),
                    ("succeeded", "Succeeded"),
                    ("failed", "Failed"),
                ],
                db_index=True,
                default="pending",
                max_length=12,
            ),
        ),
        migrations.AlterField(
            model_name="scheduledjob",
            name="kind",
            field=models.CharField(
                choices=[
                    ("deposit_expiry_refund", "Deposit expiry refund"),
                    ("payment_grace_release", "Payment grace release"),
                    ("attempt_expiry", "Checkout attempt expiry"),
                    ("provider_reconcile", "Provider reconciliation"),
                    ("provider_event_process", "Provider event processing"),
                    ("refund_reconcile", "Refund reconciliation"),
                    ("payout_release_check", "Payout release check"),
                ],
                db_index=True,
                max_length=32,
            ),
        ),
        migrations.AddIndex(
            model_name="paymentproviderevent",
            index=models.Index(
                fields=["processing_result", "next_retry_at"],
                name="fin_event_recovery_idx",
            ),
        ),
    ]
