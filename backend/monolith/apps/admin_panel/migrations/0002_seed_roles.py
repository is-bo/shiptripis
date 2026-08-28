"""Seed the fixed Phase 6A role groups and their capability matrix."""

from django.db import migrations


ROLE_GROUP_NAMES = {
    "ops": "Ops",
    "support": "Support",
    "finance": "Finance",
    "trust_verification": "Trust / Verification",
    "super_admin": "Super Admin",
}

ALL = (
    "view_dashboard",
    "view_users",
    "view_user_sensitive",
    "manage_users",
    "view_requests",
    "manage_requests",
    "view_journeys",
    "manage_journeys",
    "view_matches",
    "manage_matches",
    "view_deals",
    "manage_deals",
    "manage_lifecycle",
    "view_operational_incidents",
    "view_support_context",
    "manage_cancellations",
    "view_kyc",
    "review_kyc",
    "view_flight_proofs",
    "review_flight_proofs",
    "view_evidence",
    "view_disputes",
    "manage_disputes",
    "resolve_disputes",
    "review_safety",
    "record_no_show",
    "view_payment_orders",
    "view_payment_attempts",
    "view_provider_events",
    "issue_refunds",
    "settle_manual_refunds",
    "view_payouts",
    "settle_payouts",
    "reconcile_finance",
    "view_scheduled_jobs",
    "view_ratings",
    "view_boosts",
    "view_provider_health",
    "view_settings",
    "manage_settings",
    "manage_admins",
    "manage_permissions",
    "view_audit_log",
)

MATRIX = {
    "ops": {
        "view_dashboard",
        "view_requests",
        "manage_requests",
        "view_journeys",
        "manage_journeys",
        "view_matches",
        "manage_matches",
        "view_deals",
        "manage_deals",
        "manage_lifecycle",
        "view_operational_incidents",
        "view_support_context",
        "view_ratings",
        "view_boosts",
        "view_audit_log",
        "record_no_show",
        "view_disputes",
        "manage_disputes",
        "view_provider_health",
    },
    "support": {
        "view_dashboard",
        "view_users",
        "view_requests",
        "view_journeys",
        "view_deals",
        "view_support_context",
        "manage_cancellations",
        "view_ratings",
        "view_audit_log",
        "view_disputes",
    },
    "finance": {
        "view_dashboard",
        "view_deals",
        "view_payment_orders",
        "view_payment_attempts",
        "view_provider_events",
        "issue_refunds",
        "settle_manual_refunds",
        "view_payouts",
        "settle_payouts",
        "reconcile_finance",
        "view_scheduled_jobs",
        "view_provider_health",
        "view_audit_log",
        "view_disputes",
        "resolve_disputes",
    },
    "trust_verification": {
        "view_dashboard",
        "view_users",
        "view_user_sensitive",
        "view_kyc",
        "review_kyc",
        "view_flight_proofs",
        "review_flight_proofs",
        "view_evidence",
        "review_safety",
        "record_no_show",
        "view_deals",
        "view_audit_log",
        "view_disputes",
        "manage_disputes",
    },
    "super_admin": set(ALL),
}

# Existing Phase 4 endpoints use model-specific codenames.  Keep those grants
# on the corresponding new groups while the endpoints migrate to Phase 6A
# capability checks.
LEGACY = {
    "ops": (
        ("disputes", "dispute", "view_dispute", "Can view dispute"),
        ("deals", "deal", "record_no_show", "Can record an admin-reviewed no-show decision"),
    ),
    "support": (("disputes", "dispute", "view_dispute", "Can view dispute"),),
    "finance": (
        ("disputes", "dispute", "view_dispute", "Can view dispute"),
        ("disputes", "dispute", "resolve_dispute", "Can resolve a dispute and settle its money"),
        ("finance", "payout", "settle_payout", "Can record that a traveler has actually been paid"),
    ),
    "trust_verification": (
        ("disputes", "dispute", "view_dispute", "Can view dispute"),
        ("disputes", "dispute", "view_dispute_evidence", "Can view dispute evidence files"),
        ("deals", "deal", "record_no_show", "Can record an admin-reviewed no-show decision"),
    ),
    "super_admin": (),
}

LEGACY_GROUP_TO_ROLE = {
    "Operations Admin": "ops",
    "Support Agent": "support",
    "Finance Admin": "finance",
    "Trust & Verification Admin": "trust_verification",
}


def seed_roles(apps, schema_editor):
    del schema_editor
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")

    audit_ct, _ = ContentType.objects.get_or_create(
        app_label="admin_panel", model="adminauditlog"
    )
    phase6_perms = {}
    for code in ALL:
        permission, _ = Permission.objects.get_or_create(
            content_type=audit_ct,
            codename=code,
            defaults={"name": "Can " + code.replace("_", " ")},
        )
        phase6_perms[code] = permission

    for slug, group_name in ROLE_GROUP_NAMES.items():
        group, _ = Group.objects.get_or_create(name=group_name)
        group.permissions.add(*(phase6_perms[code] for code in MATRIX[slug]))
        for app_label, model, codename, name in LEGACY[slug]:
            ct, _ = ContentType.objects.get_or_create(
                app_label=app_label, model=model
            )
            permission, _ = Permission.objects.get_or_create(
                content_type=ct, codename=codename, defaults={"name": name}
            )
            group.permissions.add(permission)

    # Move existing Phase 4 administrators onto their fixed Phase 6A role and
    # remove the compatibility group.  Without this reconciliation a later
    # role downgrade would leave additive model permissions behind forever.
    for legacy_name, slug in LEGACY_GROUP_TO_ROLE.items():
        legacy = Group.objects.filter(name=legacy_name).first()
        if legacy is None:
            continue
        replacement = Group.objects.get(name=ROLE_GROUP_NAMES[slug])
        for user in legacy.user_set.all():
            user.groups.add(replacement)
            user.is_staff = True
            user.role = "admin"
            user.save(update_fields=("is_staff", "role"))
        legacy.delete()


def unseed_roles(apps, schema_editor):
    del schema_editor
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name__in=tuple(ROLE_GROUP_NAMES.values())).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("admin_panel", "0001_initial"),
        ("core", "0007_seed_phase4_admin_groups"),
        ("deals", "0005_alter_deal_options"),
        ("disputes", "0002_alter_dispute_options"),
        ("finance", "0005_alter_payout_options"),
    ]

    operations = [migrations.RunPython(seed_roles, unseed_roles)]
