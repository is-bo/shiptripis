from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("notifications", "0005_notificationpreference_pushdevice")]
    operations = [
        migrations.AddField(
            model_name="outboundmessage",
            name="activation_reviewed_at",
            field=models.DateTimeField(blank=True, null=True),
        )
    ]
