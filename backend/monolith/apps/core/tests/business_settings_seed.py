"""Restore the business settings a freshly migrated database has.

`TransactionTestCase` truncates `core_business_settings_version`, so the
revision chain the core migrations seeded is gone by the time a later test
reads the active policy. Re-running the migrations' own seed functions against
the live registry is what stops a test's idea of that policy from drifting
away from production's -- the same reasoning `_seed_admin_roles` gives for
replaying the admin role migrations instead of restating them.

Rebuilding from one document part-way along the chain is what used to make
`boost.minimum_amount_eur_cents` disappear: the Phase 3 revision predates
`0009_seed_boost_economics`, so any later test that read the boost policy
failed with `InvalidPhase4Policy` depending only on whether a transactional
test had run first.

A new migration that seeds another revision belongs in `SEED_MIGRATIONS`.
"""

from __future__ import annotations

from importlib import import_module

from django.apps import apps as registry

from apps.core.models import BusinessSettingsVersion

#: In migration order. Each function reads the revision the previous one left
#: active and creates the next, so the sequence is load bearing.
SEED_MIGRATIONS = (
    (
        "apps.core.migrations.0006_seed_phase4_business_settings",
        "seed_phase4_business_settings",
    ),
    (
        "apps.core.migrations.0008_seed_prelaunch_provider_settings",
        "seed_prelaunch_provider_settings",
    ),
    ("apps.core.migrations.0009_seed_boost_economics", "seed_boost_economics"),
    ("apps.core.migrations.0010_seed_j2_boost_commission", "seed_j2"),
)

#: The last seeded revision stamps this, so it is the honest "the chain is
#: complete" marker. Read from the migration rather than restated here, so it
#: cannot fall out of step with what the migration actually writes.
FINAL_PRICING_VERSION = import_module(SEED_MIGRATIONS[-1][0]).PRICING_VERSION


def seed_business_settings() -> BusinessSettingsVersion:
    """Return the active revision, rebuilding the whole chain if it is gone.

    A complete revision is left alone rather than re-seeded, so a test that
    has deliberately edited the active policy -- enabling the mock payment
    rail, say -- keeps its edit.
    """

    active = BusinessSettingsVersion.objects.filter(status="active").first()
    if active is not None and active.pricing_version == FINAL_PRICING_VERSION:
        return active

    for module_path, function_name in SEED_MIGRATIONS:
        getattr(import_module(module_path), function_name)(registry, None)

    return BusinessSettingsVersion.objects.filter(status="active").first()
