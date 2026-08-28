"""Seed the four operational groups Phase 4's admin endpoints check against.

Phase 3's admin routes use DRF's `IsAdminUser`, which is `is_staff` and nothing
finer. Phase 4 adds two capabilities that should not be the same permission as
"can see the payout queue": reading a party's dispute evidence, which means
their photos and their chat references, and resolving a dispute, which moves
money. `apps.core.permissions` checks named Django permissions for those; this
migration creates the groups that grant them.

The groups match the roles the specification names. The full role and admin-UX
design is Phase 6 -- this is only the primitive it will be built on, established
now because retrofitting authorization is how authorization gaps happen.

**Why the permissions are created here rather than looked up.** Django creates
`Permission` rows from a `post_migrate` signal, which fires after the whole
`migrate` run. A data migration that merely looked them up would find nothing on
a fresh database and silently seed empty groups. `get_or_create` on the content
type and the permission makes the outcome the same whether this runs before or
after the signal.

Reverse removes the four groups. It deliberately does not remove the
permissions: they belong to the models, and the models are still there.
"""

from django.db import migrations

#: role name -> ((app_label, model, codename, human name), ...)
GROUPS = {
    "Operations Admin": (
        ("disputes", "dispute", "view_dispute", "Can view dispute"),
        (
            "disputes",
            "dispute",
            "view_dispute_evidence",
            "Can view dispute evidence files",
        ),
        (
            "deals",
            "deal",
            "record_no_show",
            "Can record an admin-reviewed no-show decision",
        ),
    ),
    "Support Agent": (
        ("disputes", "dispute", "view_dispute", "Can view dispute"),
    ),
    "Finance Admin": (
        ("disputes", "dispute", "view_dispute", "Can view dispute"),
        (
            "disputes",
            "dispute",
            "resolve_dispute",
            "Can resolve a dispute and settle its money",
        ),
        (
            "finance",
            "payout",
            "settle_payout",
            "Can record that a traveler has actually been paid",
        ),
    ),
    "Trust & Verification Admin": (
        ("disputes", "dispute", "view_dispute", "Can view dispute"),
        (
            "disputes",
            "dispute",
            "view_dispute_evidence",
            "Can view dispute evidence files",
        ),
        (
            "deals",
            "deal",
            "record_no_show",
            "Can record an admin-reviewed no-show decision",
        ),
    ),
}


def seed_phase4_admin_groups(apps, schema_editor):
    del schema_editor
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")

    for group_name, entries in GROUPS.items():
        group, _ = Group.objects.get_or_create(name=group_name)
        for app_label, model, codename, name in entries:
            content_type, _ = ContentType.objects.get_or_create(
                app_label=app_label, model=model
            )
            permission, _ = Permission.objects.get_or_create(
                content_type=content_type,
                codename=codename,
                defaults={"name": name},
            )
            group.permissions.add(permission)


def unseed_phase4_admin_groups(apps, schema_editor):
    del schema_editor
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name__in=list(GROUPS)).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0006_seed_phase4_business_settings"),
        ("deals", "0005_alter_deal_options"),
        ("disputes", "0002_alter_dispute_options"),
        ("finance", "0005_alter_payout_options"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [
        migrations.RunPython(
            seed_phase4_admin_groups,
            unseed_phase4_admin_groups,
        )
    ]
