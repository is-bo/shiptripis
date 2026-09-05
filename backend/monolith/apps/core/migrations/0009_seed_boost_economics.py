"""Add the first economic boost policy as a new immutable settings revision.

The deployed database may already contain owner-created revisions after the
seeded pre-launch version, so this migration deliberately copies whichever
revision is active and allocates the next version number. Existing revisions
remain untouched and continue to explain historical commitments.
"""

from copy import deepcopy

from django.db import migrations
from django.db.models import Max
from django.utils import timezone


ECONOMICS_VERSION = "traveler_split_v1"
PRICING_VERSION = "v1-boost-economics-1"


def seed_boost_economics(apps, schema_editor):
    del schema_editor
    BusinessSettingsVersion = apps.get_model("core", "BusinessSettingsVersion")
    active = BusinessSettingsVersion.objects.filter(status="active").first()
    if active is None:
        raise RuntimeError("Boost economics needs an active business settings version.")

    policy = deepcopy(active.policy)
    boost = policy.get("boost")
    if not isinstance(boost, dict):
        raise RuntimeError("The active business settings have no boost policy.")
    boost["economics_version"] = ECONOMICS_VERSION
    boost["minimum_amount_eur_cents"] = 500
    # A deliberately configurable 75/25 default: clearly Traveler-majority,
    # and not a fixed interpretation of the brief's illustrative 80/20 split.
    boost["traveler_share_bps"] = 7_500
    packages = boost.get("packages")
    if not isinstance(packages, list) or not packages:
        raise RuntimeError("The active boost policy has no visibility packages.")
    for package in packages:
        if isinstance(package, dict):
            package.pop("price_eur_cents", None)

    latest = (
        BusinessSettingsVersion.objects.aggregate(value=Max("version"))["value"] or 0
    )
    BusinessSettingsVersion.objects.filter(status="active").update(status="retired")
    BusinessSettingsVersion.objects.create(
        version=latest + 1,
        status="active",
        canonical_currency=active.canonical_currency,
        commission_rate_bps=active.commission_rate_bps,
        pricing_version=PRICING_VERSION,
        policy=policy,
        activated_at=timezone.now(),
        created_by=None,
    )


def unseed_boost_economics(apps, schema_editor):
    del schema_editor
    BusinessSettingsVersion = apps.get_model("core", "BusinessSettingsVersion")
    created = None
    for row in BusinessSettingsVersion.objects.filter(
        pricing_version=PRICING_VERSION,
        created_by__isnull=True,
    ).order_by("-version"):
        boost = row.policy.get("boost") if isinstance(row.policy, dict) else None
        if (
            isinstance(boost, dict)
            and boost.get("economics_version") == ECONOMICS_VERSION
        ):
            created = row
            break
    if created is None or created.status != "active":
        # A later operator-owned revision may inherit this economics marker.
        # Never retire or replace that historical owner action during rollback.
        return
    created.status = "retired"
    created.save(update_fields=["status"])
    previous = (
        BusinessSettingsVersion.objects.filter(version__lt=created.version)
        .order_by("-version")
        .first()
    )
    if previous is not None:
        previous.status = "active"
        previous.activated_at = timezone.now()
        previous.save(update_fields=["status", "activated_at"])


class Migration(migrations.Migration):
    dependencies = [("core", "0008_seed_prelaunch_provider_settings")]

    operations = [
        migrations.RunPython(seed_boost_economics, unseed_boost_economics),
    ]
