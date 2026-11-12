"""The discovery test world: the canonical CDG → ALG → Jijel geography.

Built on `CanonicalOfferFixture` so every tier is exercised against the same
shape matching is: legs described by catalogue places only, a flight leg with
an approved ticket, a request from Paris to Jijel.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.business_settings import activate_business_settings
from apps.core.models import BusinessSettingsVersion
from apps.discovery.models import PublicProfile, PublicProfileRoute
from apps.discovery.profiles import PROFILE_CONSENT_VERSION
from apps.matching.tests.test_phase8dr_offer_locks import CanonicalOfferFixture
from apps.matching.tests.test_v1_matching import _approve_kyc, _user
from apps.trips.models import Journey, JourneyLeg, JourneyLegProof


#: Console pages render admin static assets; tests have no collected manifest.
STATIC_STORES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


def client_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def activate_marketplace(section: dict) -> BusinessSettingsVersion:
    """Activate a new revision carrying ``section`` as its marketplace policy.

    Revisions are immutable once written, exactly as in production, so a test
    changes a switch the way an operator does: by activating a new revision.
    """

    active = BusinessSettingsVersion.objects.get(status=BusinessSettingsVersion.Status.ACTIVE)
    latest = BusinessSettingsVersion.objects.order_by("-version").first()
    policy = deepcopy(active.policy)
    policy["marketplace"] = section
    revision = BusinessSettingsVersion.objects.create(
        version=latest.version + 1,
        commission_rate_bps=active.commission_rate_bps,
        pricing_version=active.pricing_version,
        policy=policy,
    )
    return activate_business_settings(revision)


class DiscoveryWorld(CanonicalOfferFixture):
    def build_discovery_world(self) -> None:
        self.build_world()
        self.sender.full_name = "Samira Haddadine"
        self.sender.save(update_fields=["full_name"])
        self.traveler.full_name = "Yacine Bensalah"
        self.traveler.save(update_fields=["full_name"])

    # -- people -------------------------------------------------------------

    def opt_in(self, user, *routes) -> PublicProfile:
        profile, _ = PublicProfile.objects.get_or_create(user=user)
        profile.is_discoverable = True
        profile.consent_version = PROFILE_CONSENT_VERSION
        profile.consented_at = timezone.now()
        profile.save()
        for position, (origin, destination) in enumerate(routes):
            PublicProfileRoute.objects.create(
                profile=profile,
                position=position,
                origin_locality=origin,
                destination_locality=destination,
            )
        return profile

    def new_traveler(self, email: str, *, name: str = "Karim Test"):
        traveler = _user(email)
        traveler.full_name = name
        traveler.save(update_fields=["full_name"])
        _approve_kyc(traveler, uuid4().hex)
        return traveler

    # -- inventory ----------------------------------------------------------

    def drive_journey(self, traveler, *, origin=None, destination=None, days=3, capacity="8.00"):
        """A one-leg DRIVE journey, published, inside one road network."""

        origin = origin or self.algiers
        destination = destination or self.jijel
        depart = self.now + timedelta(days=days)
        journey = Journey.objects.create(
            traveler=traveler,
            schema_version=2,
            start_place=origin,
            destination_place=destination,
            status=Journey.Status.ACTIVE,
            published_at=self.now,
        )
        JourneyLeg.objects.create(
            journey=journey,
            position=0,
            mode=JourneyLeg.Mode.DRIVE,
            origin_place=origin,
            destination_place=destination,
            depart_at=depart,
            arrive_at=depart + timedelta(hours=5),
            capacity_kg=Decimal(capacity),
            distance_meters=320_000,
            route_provider="catalogue_snapshot",
        )
        return journey

    def unproven_flight_journey(self, traveler):
        journey, flight, _ = self._journey(traveler)
        JourneyLegProof.objects.filter(leg=flight).update(
            status=JourneyLegProof.Status.PENDING, reviewer=None, reviewed_at=None
        )
        return journey
