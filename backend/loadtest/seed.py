"""Seed a realistic early-launch marketplace into the load-test database.

Run after ``manage_loadtest.py migrate`` and ``import_geography`` (the real
reviewed catalogue, so place search and matching locality rules run over the
56k-row production dataset rather than a toy one)::

    python backend/loadtest/seed.py --out backend/loadtest/.data/world.json

The world is built through the same V1 services the product uses where the
semantics matter (``create_sender_offer``/``accept_offer`` for every Offer and
Deal), and with direct inserts where only row volume matters (users, chat
messages, notification history). Funding is recorded the way the K4 profiler
records it -- ``status=FUNDED`` plus ``funded_at`` -- because a load world needs
funded read paths, not a replay of the payment webhook.

The output file holds everything the Locust traffic needs: one long-lived JWT
per user, their object ids, and admin session cookies. It is local-only data
and is gitignored.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import manage_loadtest  # noqa: E402

manage_loadtest.bootstrap()

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402
from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY  # noqa: E402
from django.contrib.auth.hashers import make_password  # noqa: E402
from django.contrib.sessions.backends.db import SessionStore  # noqa: E402
from django.db import transaction  # noqa: E402
from django.utils import timezone  # noqa: E402
from rest_framework_simplejwt.tokens import AccessToken  # noqa: E402

from apps.accounts.models import User  # noqa: E402
from apps.admin_panel.permissions import AdminRole, assign_admin_roles  # noqa: E402
from apps.chat.models import ChatMessage  # noqa: E402
from apps.deals.models import Deal  # noqa: E402
from apps.kyc.models import KycSubmission  # noqa: E402
from apps.locations.models import AirportLocalityMapping, Place  # noqa: E402
from apps.matching.v1_services import accept_offer, create_sender_offer  # noqa: E402
from apps.notifications.models import Notification  # noqa: E402
from apps.parcels.models import DeliveryRequest, ParcelRequest  # noqa: E402
from apps.trips.models import Journey, JourneyLeg, JourneyLegProof  # noqa: E402

EMAIL_DOMAIN = "loadtest.shiptrip.invalid"
REWARD_EUR_CENTS = 3_000

# Real diaspora corridors: French departure airports to Algerian arrival
# airports, then a road leg to a final Algerian locality.
FR_AIRPORTS = ("CDG", "ORY", "LYS", "MRS", "NCE", "TLS", "BOD", "LIL")
DZ_AIRPORTS = ("ALG", "ORN", "CZL", "AAE", "QSF", "BJA", "TLM")
DZ_DESTINATIONS = (
    "Jijel", "Tizi Ouzou", "Blida", "Setif", "Bejaia", "Constantine",
    "Batna", "Mostaganem", "Skikda", "Medea", "Bouira", "Tipaza",
)
# Queries a user actually types into the place picker.
PLACE_QUERIES = (
    "par", "lyo", "mars", "alg", "ora", "const", "tizi", "set", "bej",
    "nice", "toul", "jij", "bli", "anna", "tlem", "bord", "lil", "bat",
)
CHAT_LINES = (
    "Hello, I can pick it up on Saturday morning.",
    "Great, the parcel is ready and sealed.",
    "Which terminal are you flying from?",
    "I will send the recipient details tonight.",
    "Landed, heading to Algiers now.",
    "Thank you, see you tomorrow.",
)


def _airport_localities(codes: tuple[str, ...]) -> dict[str, tuple[Place, Place]]:
    """IATA -> (airport, its primary served locality) from the real catalogue."""

    found: dict[str, tuple[Place, Place]] = {}
    mappings = (
        AirportLocalityMapping.objects.filter(
            airport__iata_code__in=codes,
            is_primary=True,
            relationship_type=AirportLocalityMapping.RelationshipType.SERVED,
        )
        .select_related("airport", "locality")
        .order_by("airport__iata_code")
    )
    for mapping in mappings:
        found.setdefault(mapping.airport.iata_code, (mapping.airport, mapping.locality))
    missing = sorted(set(codes) - set(found))
    if len(found) < 2:
        raise SystemExit(
            "The geography catalogue is not imported (no served airport "
            f"mappings for {codes}). Run import_geography first."
        )
    if missing:
        print(f"note: catalogue has no served mapping for {missing}; skipping them")
    return found


def _destinations() -> list[Place]:
    places = list(
        Place.objects.filter(
            country__code="DZ",
            place_type=Place.PlaceType.LOCALITY,
            name__in=DZ_DESTINATIONS,
        )
    )
    if not places:
        raise SystemExit("No Algerian destination localities in the catalogue.")
    return places


def _bulk_users(prefix: str, count: int, password_hash: str) -> list[User]:
    users = [
        User(
            username=f"{prefix}{index:05d}@{EMAIL_DOMAIN}",
            email=f"{prefix}{index:05d}@{EMAIL_DOMAIN}",
            full_name=f"{prefix.title()} {index:05d}",
            password=password_hash,
            is_active=True,
            is_email_verified=True,
        )
        for index in range(count)
    ]
    User.objects.bulk_create(users, batch_size=500)
    return list(User.objects.filter(email__startswith=f"{prefix}0").order_by("pk"))


def _journey(traveler, *, origin, arrival, arrival_locality, destination, depart, now, reviewer):
    journey = Journey.objects.create(
        traveler=traveler,
        schema_version=2,
        start_place=origin,
        destination_place=destination,
        status=Journey.Status.ACTIVE,
        published_at=now,
    )
    flight = JourneyLeg.objects.create(
        journey=journey,
        position=0,
        mode=JourneyLeg.Mode.FLIGHT,
        origin_place=origin,
        destination_place=arrival,
        depart_at=depart,
        arrive_at=depart + timedelta(hours=3),
        capacity_kg=Decimal("10.00"),
        flight_number=f"AH{random.randint(1000, 9999)}",
    )
    drive = JourneyLeg.objects.create(
        journey=journey,
        position=1,
        mode=JourneyLeg.Mode.DRIVE,
        origin_place=arrival_locality,
        destination_place=destination,
        depart_at=depart + timedelta(hours=4),
        arrive_at=depart + timedelta(hours=9),
        capacity_kg=Decimal("10.00"),
        distance_meters=random.randint(40_000, 450_000),
        route_provider="catalogue_snapshot",
    )
    JourneyLegProof.objects.create(
        leg=flight,
        bucket="private",
        object_key=f"loadtest/{journey.pk}-ticket.jpg",
        status=JourneyLegProof.Status.APPROVED,
        reviewer=reviewer,
        reviewed_at=now,
    )
    return journey, flight, drive


def _request(sender, *, pickup, delivery, depart, title):
    return DeliveryRequest.objects.create(
        sender=sender,
        kind=ParcelRequest.Kind.DELIVERY,
        schema_version=3,
        pickup_place=pickup,
        delivery_place=delivery,
        ready_window_start=depart - timedelta(days=1),
        ready_window_end=depart + timedelta(hours=2),
        deadline_at=depart + timedelta(days=4),
        actual_weight_kg=Decimal("2.00"),
        length_cm=Decimal("30.00"),
        width_cm=Decimal("20.00"),
        height_cm=Decimal("15.00"),
        declared_value_eur_cents=random.choice((5_000, 12_000, 25_000)),
        traveler_reward_eur_cents=REWARD_EUR_CENTS,
        title=title,
        description="Family parcel, sealed",
        category=ParcelRequest.ItemType.DOCUMENTS,
        item_type=ParcelRequest.ItemType.DOCUMENTS,
        description_is_accurate=True,
        item_is_legal=True,
        no_prohibited_goods=True,
        declared_value_is_accurate=True,
        customs_responsibilities_understood=True,
        base_amount_dzd=None,
    )


def _admin_session(user: User) -> str:
    session = SessionStore()
    session[SESSION_KEY] = str(user.pk)
    session[BACKEND_SESSION_KEY] = "django.contrib.auth.backends.ModelBackend"
    session[HASH_SESSION_KEY] = user.get_session_auth_hash()
    session.set_expiry(86_400)
    session.create()
    return session.session_key


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--out", default=str(Path(__file__).parent / ".data" / "world.json"))
    parser.add_argument("--travelers", type=int, default=400)
    parser.add_argument("--senders", type=int, default=1_200)
    parser.add_argument("--journeys-per-traveler", type=int, default=2)
    parser.add_argument("--requests-per-sender", type=int, default=2)
    parser.add_argument("--deals", type=int, default=600)
    parser.add_argument("--pending-offers", type=int, default=300)
    parser.add_argument("--funded-share", type=float, default=0.7)
    parser.add_argument("--messages-per-deal", type=int, default=8)
    parser.add_argument("--notifications-per-user", type=int, default=25)
    parser.add_argument("--admins", type=int, default=5)
    parser.add_argument("--seed", type=int, default=20260923)
    args = parser.parse_args()
    random.seed(args.seed)

    if User.objects.filter(email__endswith=f"@{EMAIL_DOMAIN}").exists():
        raise SystemExit(
            "This database already holds a load world. Use a fresh "
            "LOADTEST_DB_NAME (see README) to seed another."
        )
    # All or nothing: a failed seed leaves no half world behind.
    with transaction.atomic():
        return seed_world(args)


def seed_world(args: argparse.Namespace) -> int:
    started = time.monotonic()
    now = timezone.now()
    fr = _airport_localities(FR_AIRPORTS)
    dz = _airport_localities(DZ_AIRPORTS)
    destinations = _destinations()
    password_hash = make_password("LoadTest-Only-Pass-1!")

    with transaction.atomic():
        travelers = _bulk_users("traveler", args.travelers, password_hash)
        senders = _bulk_users("sender", args.senders, password_hash)
        admins = _bulk_users("admin", args.admins, password_hash)
        KycSubmission.objects.bulk_create(
            [
                KycSubmission(
                    user=traveler,
                    document_type=KycSubmission.DocumentType.PASSPORT,
                    idempotency_key=f"lt-kyc-{traveler.pk:024d}",
                    front_image_key=f"kyc/loadtest-{traveler.pk}/front.jpg",
                    status=KycSubmission.Status.APPROVED,
                    reviewed_at=now,
                )
                for traveler in travelers
            ],
            batch_size=500,
        )
        for admin in admins:
            assign_admin_roles(admin, (AdminRole.SUPER_ADMIN,), elevate_super_admin=True)
    print(f"users: {len(travelers)} travelers, {len(senders)} senders, {len(admins)} admins")

    # Journeys: each traveler publishes a few departures over the next weeks.
    journeys: list[dict] = []
    with transaction.atomic():
        for traveler in travelers:
            for _ in range(args.journeys_per_traveler):
                origin_code = random.choice(list(fr))
                arrival_code = random.choice(list(dz))
                origin, origin_locality = fr[origin_code]
                arrival, arrival_locality = dz[arrival_code]
                destination = random.choice(
                    [place for place in destinations if place.pk != arrival_locality.pk]
                )
                depart = now + timedelta(days=random.randint(2, 45), hours=random.randint(0, 20))
                journey, flight, drive = _journey(
                    traveler,
                    origin=origin,
                    arrival=arrival,
                    arrival_locality=arrival_locality,
                    destination=destination,
                    depart=depart,
                    now=now,
                    reviewer=admins[0],
                )
                journeys.append(
                    {
                        "journey": journey,
                        "flight": flight,
                        "drive": drive,
                        "pickup": origin_locality,
                        "destination": destination,
                        "depart": depart,
                        "deals": 0,
                    }
                )
    print(f"journeys: {len(journeys)} ({time.monotonic() - started:.0f}s)")

    # Requests: each sender posts parcels shaped to fit a real journey, so
    # Find Travelers returns genuine candidates rather than an empty page.
    requests_by_sender: dict[int, list[tuple[DeliveryRequest, dict]]] = {}
    with transaction.atomic():
        for sender in senders:
            for index in range(args.requests_per_sender):
                target = random.choice(journeys)
                parcel = _request(
                    sender,
                    pickup=target["pickup"],
                    delivery=target["destination"],
                    depart=target["depart"],
                    title=f"Parcel {sender.pk}-{index}",
                )
                requests_by_sender.setdefault(sender.pk, []).append((parcel, target))
    total_requests = sum(len(rows) for rows in requests_by_sender.values())
    print(f"requests: {total_requests} ({time.monotonic() - started:.0f}s)")

    # Offers and Deals through the real V1 negotiation services.
    candidates = [
        (sender, parcel, target)
        for sender in senders
        for parcel, target in requests_by_sender[sender.pk]
    ]
    random.shuffle(candidates)
    deals: list[Deal] = []
    pending_offers = 0
    rejected = 0
    used_requests: set[int] = set()
    for sender, parcel, target in candidates:
        if len(deals) >= args.deals and pending_offers >= args.pending_offers:
            break
        if target["deals"] >= 4:
            continue
        try:
            # A savepoint per attempt, so one refusal cannot poison the world.
            with transaction.atomic():
                offer = create_sender_offer(
                    sender=sender,
                    delivery_request=parcel,
                    journey=target["journey"],
                    start_leg_id=target["flight"].pk,
                    end_leg_id=target["drive"].pk,
                    traveler_reward_eur_cents=REWARD_EUR_CENTS,
                )
                accepted = None
                if len(deals) < args.deals:
                    accepted = accept_offer(
                        pending_offer=offer, actor=target["journey"].traveler
                    )
            used_requests.add(parcel.pk)
            if accepted is not None:
                deals.append(accepted.deal)
                target["deals"] += 1
            else:
                pending_offers += 1
        except Exception as exc:  # the service refused; report, keep seeding
            rejected += 1
            if rejected <= 5:
                print(f"  offer refused: {type(exc).__name__}: {exc}")
            continue
        if (len(deals) + pending_offers) % 100 == 0:
            print(
                f"  offers: {len(deals)} deals, {pending_offers} pending "
                f"({time.monotonic() - started:.0f}s)"
            )
    funded_ids = [deal.pk for deal in deals[: int(len(deals) * args.funded_share)]]
    Deal.objects.filter(pk__in=funded_ids).update(
        status=Deal.Status.FUNDED, funded_at=now
    )
    funded = list(Deal.objects.filter(pk__in=funded_ids).select_related("match"))
    print(
        f"deals: {len(deals)} ({len(funded)} funded), pending offers: "
        f"{pending_offers}, refused: {rejected} ({time.monotonic() - started:.0f}s)"
    )

    # Chat history on funded Deals, where V1 makes it visible.
    messages = []
    for deal in funded:
        for index in range(args.messages_per_deal):
            author = deal.sender_id if index % 2 == 0 else deal.traveler_id
            messages.append(
                ChatMessage(
                    match_id=deal.match_id,
                    sender_id=author,
                    body=CHAT_LINES[index % len(CHAT_LINES)],
                )
            )
    ChatMessage.objects.bulk_create(messages, batch_size=1_000)
    print(f"chat messages: {len(messages)} ({time.monotonic() - started:.0f}s)")

    # Notification history: mostly informational, some actionable, a third unread.
    deals_by_user: dict[int, list[Deal]] = {}
    for deal in deals:
        deals_by_user.setdefault(deal.sender_id, []).append(deal)
        deals_by_user.setdefault(deal.traveler_id, []).append(deal)
    rows = []
    for user in [*travelers, *senders]:
        own = deals_by_user.get(user.pk, [])
        for index in range(args.notifications_per_user):
            payload: dict = {"index": index}
            channel = "system.notice"
            if own and index % 3 == 0:
                deal = random.choice(own)
                channel = random.choice(("deal.updated", "offer.accepted", "chat.message.new"))
                payload = {"deal_id": deal.pk, "match_id": deal.match_id}
            rows.append(
                Notification(
                    recipient=user,
                    channel=channel,
                    event_id=f"loadtest-{user.pk}-{index}",
                    payload=payload,
                    read_at=None if index % 3 == 0 else now,
                )
            )
    Notification.objects.bulk_create(rows, batch_size=2_000)
    print(f"notifications: {len(rows)} ({time.monotonic() - started:.0f}s)")

    # Everything the traffic generator needs, keyed by role.
    deal_ids_by_user = {uid: [d.pk for d in rows] for uid, rows in deals_by_user.items()}
    funded_match_by_user: dict[int, list[int]] = {}
    for deal in funded:
        funded_match_by_user.setdefault(deal.sender_id, []).append(deal.match_id)
        funded_match_by_user.setdefault(deal.traveler_id, []).append(deal.match_id)
    journeys_by_traveler: dict[int, list[int]] = {}
    for row in journeys:
        journeys_by_traveler.setdefault(row["journey"].traveler_id, []).append(row["journey"].pk)

    def token(user: User) -> str:
        return str(AccessToken.for_user(user))

    world = {
        "generated_at": now.isoformat(),
        "jwt_lifetime_seconds": int(settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"].total_seconds()),
        "place_queries": list(PLACE_QUERIES),
        "place_countries": ["FR", "DZ"],
        "senders": [
            {
                "id": sender.pk,
                "token": token(sender),
                "request_ids": [parcel.pk for parcel, _ in requests_by_sender[sender.pk]],
                "open_request_ids": [
                    parcel.pk
                    for parcel, _ in requests_by_sender[sender.pk]
                    if parcel.pk not in used_requests
                ],
                "deal_ids": deal_ids_by_user.get(sender.pk, []),
                "chat_match_ids": funded_match_by_user.get(sender.pk, []),
            }
            for sender in senders
        ],
        "travelers": [
            {
                "id": traveler.pk,
                "token": token(traveler),
                "journey_ids": journeys_by_traveler.get(traveler.pk, []),
                "deal_ids": deal_ids_by_user.get(traveler.pk, []),
                "chat_match_ids": funded_match_by_user.get(traveler.pk, []),
            }
            for traveler in travelers
        ],
        "admins": [
            {"id": admin.pk, "token": token(admin), "sessionid": _admin_session(admin)}
            for admin in admins
        ],
        "sample_deal_ids": [deal.pk for deal in deals[:200]],
        # Corridors a sender filters Journey search by (start airport, final
        # destination), as the Flutter search form sends them.
        "journey_routes": sorted(
            {
                (row["journey"].start_place_id, row["journey"].destination_place_id)
                for row in journeys
            }
        ),
    }
    world["access_tokens"] = [
        row["token"] for row in (*world["senders"], *world["travelers"])
    ]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(world), encoding="utf-8")
    print(f"wrote {out} in {time.monotonic() - started:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
