import django.db.models.deletion
from django.db import migrations, models


def drop_devices_without_a_sign_in(apps, schema_editor):
    # A device registered before sign-ins were recorded names none, so no
    # sign-out could ever switch it off. The app registers again after its next
    # sign-in, which every phone needs: a token without a sign-in no longer
    # refreshes.
    apps.get_model("notifications", "PushDevice").objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0008_sign_in_session"),
        ("notifications", "0008_l3a_leg_proof_status_kind"),
    ]

    operations = [
        migrations.CreateModel(
            name="PushInstallationBinding",
            fields=[
                (
                    "installation_id",
                    models.UUIDField(primary_key=True, serialize=False),
                ),
                ("sequence", models.BigIntegerField()),
                (
                    "operation",
                    models.CharField(
                        choices=[
                            ("register", "Registration"),
                            ("sign_out", "Sign-out"),
                        ],
                        max_length=8,
                    ),
                ),
                ("user_id", models.BigIntegerField()),
                ("session_id", models.UUIDField(blank=True, null=True)),
                (
                    "token_fingerprint",
                    models.CharField(blank=True, default="", max_length=64),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "notification_push_installation_binding",
            },
        ),
        migrations.RunPython(drop_devices_without_a_sign_in, migrations.RunPython.noop),
        migrations.AddField(
            model_name="pushdevice",
            name="binding_sequence",
            field=models.BigIntegerField(default=0),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="pushdevice",
            name="session",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="push_devices",
                to="accounts.signinsession",
            ),
        ),
        migrations.AlterField(
            model_name="pushdevice",
            name="session",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="push_devices",
                to="accounts.signinsession",
            ),
        ),
    ]
