from django.db import migrations

FINANCE = (
    "view_finance_summary",
    "view_payout_sensitive",
    "view_payout_evidence",
    "review_payout_profiles",
    "manage_payout_holds",
    "retry_payouts",
)
TRUST = ("attest_payout_identity", "manage_payout_holds")


def seed(apps, schema_editor):
    alias = schema_editor.connection.alias
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")
    Group = apps.get_model("auth", "Group")
    ct, _ = ContentType.objects.using(alias).get_or_create(
        app_label="admin_panel", model="adminauditlog"
    )
    for code in set(FINANCE + TRUST):
        permission, _ = Permission.objects.using(alias).get_or_create(
            content_type=ct,
            codename=code,
            defaults={"name": "Can " + code.replace("_", " ")},
        )
        for name, codes in {
            "Finance": FINANCE,
            "Trust / Verification": TRUST,
            "Super Admin": FINANCE + TRUST,
        }.items():
            if code in codes:
                group, _ = Group.objects.using(alias).get_or_create(name=name)
                group.permissions.add(permission)


def reverse(apps, schema_editor):
    Permission = apps.get_model("auth", "Permission")
    Group = apps.get_model("auth", "Group")
    permissions = Permission.objects.using(schema_editor.connection.alias).filter(
        content_type__app_label="admin_panel", codename__in=set(FINANCE + TRUST)
    )
    for group in Group.objects.using(schema_editor.connection.alias).filter(
        name__in=["Finance", "Trust / Verification", "Super Admin"]
    ):
        group.permissions.remove(*permissions)


class Migration(migrations.Migration):
    dependencies = [("admin_panel", "0004_alter_adminauditlog_options")]
    operations = [migrations.RunPython(seed, reverse)]
