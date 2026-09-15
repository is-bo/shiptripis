"""Seed the J2 pricing, deposit and Boost-commission keys as a new revision.

J2 changes what Boost *is*: no longer a timed visibility package with a
Traveler/platform split of the sender's payment, but the sender's own extra
reward on the request, with its own commission charged on top exactly as the
base commission is. That needs three new commercial inputs, and they arrive the
way every other commercial input does — as a new immutable revision, copied
from whichever revision is active, leaving every earlier revision untouched so
historical commitments keep explaining themselves.

Nothing here rewrites a settled price. `boost.traveler_share_bps`,
`boost.minimum_amount_eur_cents` and `boost.packages` are deliberately left in
place: a historical `BoostPurchase` still reads them.
"""

from copy import deepcopy

from django.db import migrations
from django.db.models import Max
from django.utils import timezone


PRICING_VERSION = "v1-j2-boost-reward-1"

#: ShipTrip's commission on the Boost portion. Seeded equal to the base
#: commission so J2 ships with no silent price change; the Admin console can
#: move it independently from here, and it binds future commitments only.
BOOST_COMMISSION_RATE_BPS = 2_500
#: The smallest non-zero Boost. The retired package minimum was EUR 5 because
#: a package cost that much to run; a sender's extra reward has no such cost,
#: so the floor is the smallest amount that is a real offer rather than noise.
BOOST_MINIMUM_INTENT_EUR_CENTS = 100
#: The same ceiling every other sender-chosen money field on a request carries.
BOOST_MAXIMUM_INTENT_EUR_CENTS = 100_000_000
BOOST_RANKING_WEIGHT_STEP_EUR_CENTS = 500
BOOST_RANKING_WEIGHT_MAX = 30
#: The floor under a sender-chosen posting deposit. Equal to the recommendation
#: floor: EUR 3 was already the smallest deposit this platform takes.
DEPOSIT_CHOSEN_MIN_EUR_CENTS = 300


def seed_j2(apps, schema_editor):
    del schema_editor
    BusinessSettingsVersion = apps.get_model("core", "BusinessSettingsVersion")
    active = BusinessSettingsVersion.objects.filter(status="active").first()
    if active is None:
        raise RuntimeError("J2 pricing needs an active business settings version.")

    policy = deepcopy(active.policy)
    boost = policy.get("boost")
    if not isinstance(boost, dict):
        raise RuntimeError("The active business settings have no boost policy.")
    boost["commission_rate_bps"] = BOOST_COMMISSION_RATE_BPS
    boost["minimum_intent_eur_cents"] = BOOST_MINIMUM_INTENT_EUR_CENTS
    boost["maximum_intent_eur_cents"] = BOOST_MAXIMUM_INTENT_EUR_CENTS
    boost["ranking_weight_step_eur_cents"] = BOOST_RANKING_WEIGHT_STEP_EUR_CENTS
    boost["ranking_weight_max"] = BOOST_RANKING_WEIGHT_MAX

    payments = policy.get("payments")
    if not isinstance(payments, dict):
        raise RuntimeError("The active business settings have no payments policy.")
    deposit = payments.get("posting_deposit")
    if not isinstance(deposit, dict):
        raise RuntimeError("The active payments policy has no posting deposit.")
    deposit["chosen_min_eur_cents"] = DEPOSIT_CHOSEN_MIN_EUR_CENTS

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


def unseed_j2(apps, schema_editor):
    del schema_editor
    BusinessSettingsVersion = apps.get_model("core", "BusinessSettingsVersion")
    created = (
        BusinessSettingsVersion.objects.filter(
            pricing_version=PRICING_VERSION, created_by__isnull=True
        )
        .order_by("-version")
        .first()
    )
    if created is None or created.status != "active":
        # A later operator-owned revision inherits this pricing marker or has
        # replaced it. Never retire or overwrite that historical owner action.
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
    dependencies = [("core", "0009_seed_boost_economics")]

    operations = [migrations.RunPython(seed_j2, unseed_j2)]
