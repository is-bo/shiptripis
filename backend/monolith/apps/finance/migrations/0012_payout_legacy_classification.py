"""Evidence-only classification. No current keys, FX, provider calls or approval."""

import uuid
from django.db import migrations


def classify(apps, schema_editor):
    alias = schema_editor.connection.alias
    Attempt = apps.get_model("finance", "PaymentAttempt")
    Event = apps.get_model("finance", "PaymentProviderEvent")
    Payout = apps.get_model("finance", "Payout")
    Method = apps.get_model("finance", "TravelerPayoutMethod")
    for model in (Payout, Method):
        for row in (
            model.objects.using(alias).filter(public_reference__isnull=True).iterator()
        ):
            model.objects.using(alias).filter(pk=row.pk).update(
                public_reference=uuid.uuid4()
            )
    for attempt in (
        Attempt.objects.using(alias).filter(provider_mode="legacy_unknown").iterator()
    ):
        modes = set()
        if attempt.provider == "stripe":
            if attempt.provider_session_id.startswith("cs_test_"):
                modes.add("test")
            elif attempt.provider_session_id.startswith("cs_live_"):
                modes.add("live")
        for event in Event.objects.using(alias).filter(
            attempt_id=attempt.pk, signature_verified=True
        ):
            payload = event.payload if isinstance(event.payload, dict) else {}
            flag = payload.get("livemode")
            if type(flag) is bool:
                modes.add("live" if flag else "test")
        if len(modes) == 1:
            Attempt.objects.using(alias).filter(pk=attempt.pk).update(
                provider_mode=modes.pop(), mode_evidence="historical_provider_evidence"
            )
    for payout in Payout.objects.using(alias).filter(snapshot_version=0).iterator():
        # Existing paid/manual history is untouched, including amount and FX.
        classification = (
            "legacy_paid"
            if payout.status == "paid"
            else "legacy_manual_review"
            if payout.method == "manual"
            else "legacy_unclassified"
        )
        Payout.objects.using(alias).filter(pk=payout.pk).update(
            legacy_classification=classification
        )


class Migration(migrations.Migration):
    dependencies = [("finance", "0011_paymentrefund_provider_mode")]
    operations = [
        migrations.RunPython(classify, migrations.RunPython.noop),
    ]
