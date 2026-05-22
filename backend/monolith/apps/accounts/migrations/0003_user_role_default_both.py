from django.db import migrations, models


def upgrade_existing_to_both(apps, schema_editor):
    """Flip existing pure-sender/pure-traveler users to 'both' so the demo
    build's in-app role toggle is functional for everyone signed up before
    this migration. Admins are left alone."""
    User = apps.get_model("accounts", "User")
    User.objects.filter(role__in=("sender", "traveler")).update(role="both")


def downgrade_back_to_sender(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    User.objects.filter(role="both").update(role="sender")


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_user_is_banned"),
    ]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="role",
            field=models.CharField(
                choices=[
                    ("sender", "Sender"),
                    ("traveler", "Traveler"),
                    ("both", "Both"),
                    ("admin", "Admin"),
                ],
                default="both",
                max_length=16,
            ),
        ),
        migrations.RunPython(upgrade_existing_to_both, downgrade_back_to_sender),
    ]
