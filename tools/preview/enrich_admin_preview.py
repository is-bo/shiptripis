"""Add the operational states the base seed does not reach, for visual review.

Local review tooling only. Nothing imports it and CI does not run it. It runs
against the throwaway `config.settings.local_preview` database created by
`seed_admin_preview.py` and refuses anything else, because it writes rows.

What it adds, and why the base seed cannot: a canonical multi-leg Journey
(FLIGHT + DRIVE with real airport identities), a pending and a revoked staff
invitation, a handful of audit entries, and a review superuser used only with
`force_login`. No password is ever typed and no provider is contacted.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.utils import timezone

from apps.accounts.models import User
from apps.admin_panel.models import AdminInvitation
from apps.admin_panel.services import record_admin_action
from apps.kyc.models import KycSubmission
from apps.locations.models import Country, Place
from apps.trips.models import Journey, JourneyLeg, JourneyLegProof

if "admin_preview" not in str(settings.DATABASES["default"]["NAME"]):
    raise RuntimeError("Run this against the throwaway admin preview database only.")

now = timezone.now()


def country(code: str, name: str) -> Country:
    obj, _ = Country.objects.get_or_create(
        code=code,
        defaults=dict(
            name=name, source="review", source_id=code, source_version="review-1"
        ),
    )
    return obj


def place(source_id: str, **kwargs) -> Place:
    obj, _ = Place.objects.get_or_create(
        source="review",
        source_id=source_id,
        defaults=dict(source_version="review-1", **kwargs),
    )
    return obj


fr = country("FR", "France")
dz = country("DZ", "Algeria")

idf = place(
    "fr-idf",
    country=fr,
    place_type=Place.PlaceType.ADMIN_REGION,
    name="Île-de-France",
    admin_level="region",
)
paris = place(
    "fr-75056",
    country=fr,
    place_type=Place.PlaceType.LOCALITY,
    name="Paris",
    parent=idf,
)
cdg = place(
    "fr-cdg",
    country=fr,
    place_type=Place.PlaceType.AIRPORT,
    name="Charles de Gaulle",
    parent=idf,
    latitude=Decimal("49.009690"),
    longitude=Decimal("2.547925"),
    iata_code="CDG",
    icao_code="LFPG",
    airport_type="large_airport",
    passenger_use=True,
)
alger_w = place(
    "dz-16",
    country=dz,
    place_type=Place.PlaceType.ADMIN_REGION,
    name="Alger",
    admin_level="wilaya",
)
alg = place(
    "dz-alg",
    country=dz,
    place_type=Place.PlaceType.AIRPORT,
    name="Houari Boumediene",
    parent=alger_w,
    latitude=Decimal("36.691014"),
    longitude=Decimal("3.215408"),
    iata_code="ALG",
    icao_code="DAAG",
    airport_type="large_airport",
    passenger_use=True,
)
jijel_w = place(
    "dz-18",
    country=dz,
    place_type=Place.PlaceType.ADMIN_REGION,
    name="Jijel",
    admin_level="wilaya",
)
jijel = place(
    "dz-1801",
    country=dz,
    place_type=Place.PlaceType.LOCALITY,
    name="Jijel",
    parent=jijel_w,
)

traveler = (
    User.objects.filter(email="ok-traveler@example.com").first() or User.objects.first()
)

journey, created = Journey.objects.get_or_create(
    traveler=traveler,
    schema_version=2,
    start_place=cdg,
    destination_place=jijel,
    defaults=dict(
        status=Journey.Status.ACTIVE,
        published_at=now - timedelta(days=2),
        notes="Two suitcases; I can take a medium parcel on the drive from Algiers.",
    ),
)
if created:
    flight = JourneyLeg.objects.create(
        journey=journey,
        position=0,
        mode=JourneyLeg.Mode.FLIGHT,
        origin_place=cdg,
        destination_place=alg,
        depart_at=now + timedelta(days=5, hours=7),
        arrive_at=now + timedelta(days=5, hours=9, minutes=35),
        capacity_kg=Decimal("12.00"),
        flight_number="AH1005",
    )
    JourneyLeg.objects.create(
        journey=journey,
        position=1,
        mode=JourneyLeg.Mode.DRIVE,
        origin_place=alg,
        destination_place=jijel,
        depart_at=now + timedelta(days=5, hours=11),
        arrive_at=now + timedelta(days=5, hours=16),
        capacity_kg=Decimal("12.00"),
        distance_meters=352_000,
        route_duration_seconds=18_000,
        route_provider="review",
    )
    JourneyLegProof.objects.create(
        leg=flight,
        bucket="proofs",
        object_key="proofs/review/multileg-boarding-pass.jpg",
        kind="ticket",
        content_type="image/jpeg",
        bytes=402_118,
        status=JourneyLegProof.Status.PENDING,
    )

owner = User.objects.filter(email="review-owner@example.invalid").first()
if owner is None:
    owner = User.objects.create_superuser(
        username="review-owner@example.invalid",
        email="review-owner@example.invalid",
        full_name="Review Owner",
    )
    owner.set_unusable_password()
    owner.save(update_fields=["password"])

if not AdminInvitation.objects.exists():
    AdminInvitation.issue(
        email="new-support@example.invalid",
        role="support",
        invited_by=owner,
        ttl=timedelta(hours=24),
    )
    revoked, _token = AdminInvitation.issue(
        email="left-the-team@example.invalid",
        role="finance",
        invited_by=owner,
        ttl=timedelta(hours=24),
    )
    revoked.revoked_at = now - timedelta(hours=3)
    revoked.save(update_fields=["revoked_at"])

pending_kyc = KycSubmission.objects.filter(status=KycSubmission.Status.PENDING).first()
if pending_kyc is not None and not owner.admin_audit_actions.exists():
    record_admin_action(
        actor=owner,
        action="kyc.evidence_viewed",
        target=pending_kyc,
        reason="Opened the submitted document for review.",
    )
    record_admin_action(
        actor=owner,
        action="settings.version_created",
        target=None,
        reason="Raised the Chargily rate after the weekly bank check.",
    )

print("journeys", Journey.objects.count())
print("legs", JourneyLeg.objects.count())
print("invitations", AdminInvitation.objects.count())
print("audit", owner.admin_audit_actions.count())
print("owner", owner.email)
