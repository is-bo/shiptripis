from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from .models import BusinessSettingsVersion


class NoActiveBusinessSettings(RuntimeError):
    """No activated settings row exists; every priced write must fail closed."""

    code = "business_settings_unavailable"


def get_active_business_settings() -> BusinessSettingsVersion:
    settings_version = BusinessSettingsVersion.objects.filter(
        status=BusinessSettingsVersion.Status.ACTIVE
    ).first()
    if settings_version is None:
        raise NoActiveBusinessSettings("No active business settings version exists.")
    return settings_version


@transaction.atomic
def activate_business_settings(
    settings_version: BusinessSettingsVersion,
) -> BusinessSettingsVersion:
    """Activate one immutable revision while serializing concurrent changes."""

    candidate = BusinessSettingsVersion.objects.select_for_update(no_key=True).get(
        pk=settings_version.pk
    )
    if candidate.status == BusinessSettingsVersion.Status.RETIRED:
        raise ValueError("A retired business settings version cannot be reactivated.")

    # Commercial configuration must not be able to reduce pre-funding location
    # privacy as a side effect. Imported lazily so `apps.core` keeps no
    # import-time dependency on the matching app.
    from apps.matching.policy import (  # noqa: WPS433 (deliberate late import)
        assert_pricing_bands_preserve_location_privacy,
    )

    assert_pricing_bands_preserve_location_privacy(candidate.policy)

    now = timezone.now()
    BusinessSettingsVersion.objects.select_for_update(no_key=True).filter(
        status=BusinessSettingsVersion.Status.ACTIVE
    ).exclude(pk=candidate.pk).update(
        status=BusinessSettingsVersion.Status.RETIRED
    )
    if candidate.status != BusinessSettingsVersion.Status.ACTIVE:
        candidate.status = BusinessSettingsVersion.Status.ACTIVE
        candidate.activated_at = now
        candidate.save(update_fields=["status", "activated_at"])
    return candidate


def calculate_offer_economics(
    traveler_reward_eur_cents: int,
    settings_version: BusinessSettingsVersion,
) -> dict[str, int]:
    if traveler_reward_eur_cents <= 0:
        raise ValueError("Traveler reward must be positive.")
    commission_bps = settings_version.commission_rate_bps
    platform_fee = (
        traveler_reward_eur_cents * commission_bps + 9_999
    ) // 10_000
    return {
        "traveler_reward_minor": traveler_reward_eur_cents,
        "commission_rate_bps": commission_bps,
        "platform_fee_minor": platform_fee,
        "sender_total_minor": traveler_reward_eur_cents + platform_fee,
    }
