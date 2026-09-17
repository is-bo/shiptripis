"""Phase J6.4 — the Person profile as the operational page for a user.

Four things are pinned here.

* **It is complete.** From one page an operator reaches a person's identity,
  requests, journeys, offers, Deals, payments, payout setup and payouts,
  disputes, revealed ratings, notifications and audit history — through real
  records produced by the real services, not hand-made rows.
* **It is bounded.** One tab loads at a time, every history list pages, and the
  query count of the Overview and of each history tab does not grow with the
  history. A wall clock measures the machine; a query count measures the code.
* **It is role-scoped.** Reaching the page needs a capability that already
  shows the person's name; every tab below the header needs the capability
  that owns its data. Support never sees payment, payout or phone data.
* **It exposes nothing new.** No payout account value (masked or not), no
  hidden rating and no notification payload appears on any tab.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.admin_panel.permissions import assign_admin_roles
from apps.admin_panel.services import record_admin_action
from apps.deals.tests.phase4_factories import delivered_scenario, freeze_at
from apps.disputes.services import open_dispute
from apps.finance.tests.factories import make_user
from apps.notifications.models import Notification
from apps.parcels.models import DeliveryRequest, ParcelRequest
from apps.ratings.models import Rating
from apps.ratings.services import submit_rating
from apps.trips.models import Journey, JourneyLeg

TABS = ("overview", "identity", "activity", "deliveries", "payments", "payouts", "trust", "audit")


def staff(email, role):
    user = make_user(email, is_staff=True)
    assign_admin_roles(user, [role])
    return user


def client_for(user):
    client = Client()
    client.force_login(user)
    return client


def profile_url(user, **params):
    url = reverse("admin_console:user-detail", args=(user.pk,))
    if params:
        url += "?" + "&".join(f"{key}={value}" for key, value in params.items())
    return url


@pytest.fixture
def world(client):
    """A delivered Deal with both ratings, an open dispute and an audit trail."""

    scenario = delivered_scenario(client, prefix="j64p")
    deal = scenario.deal
    with freeze_at(deal.rating_window_ends_at - timedelta(minutes=5)):
        submit_rating(deal_id=deal.pk, actor_id=scenario.sender.pk, score=5)
        submit_rating(deal_id=deal.pk, actor_id=scenario.traveler.pk, score=4)
    open_dispute(
        deal_id=deal.pk,
        actor_id=scenario.sender.pk,
        category="damaged",
        reason_text="Corner crushed on arrival.",
    )
    record_admin_action(
        actor=scenario.admin,
        action="admin.access_disabled",
        target=scenario.traveler,
        reason="QA synthetic audit entry",
    )
    return scenario


# ---------------------------------------------------------------------------
# Completeness, through a Super Admin
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_super_admin_sees_the_whole_person_from_one_page(world):
    owner = staff("j64-owner@example.com", "super_admin")
    client = client_for(owner)
    traveler, sender, deal = world.traveler, world.sender, world.deal

    page = client.get(profile_url(traveler))
    assert page.status_code == 200
    body = page.content.decode()
    header = page.context["header"]
    assert header["email"] == traveler.email
    assert f"account #{traveler.pk}" in body
    assert "ID approved" in body
    assert [tab["key"] for tab in page.context["tabs"]] == list(TABS)

    overview = page.context["body"]
    facts = {fact["label"]: fact for fact in overview["facts"]}
    assert facts["Journeys"]["detail"] == "1 in total"
    assert facts["Disputes"]["value"] == 1
    assert facts["Rating received"]["value"] == "5.0"
    assert overview["deals"]["traveler"] == 1 and overview["deals"]["sender"] == 0
    assert "Traveler" in overview["uses"]
    assert any("open dispute" in item["label"] for item in overview["attention"])

    def tab(user, name, **params):
        response = client.get(profile_url(user, tab=name, **params))
        assert response.status_code == 200, name
        return response

    identity = tab(traveler, "identity").context["body"]
    assert identity["kyc_list"]["rows"], "KYC submissions are listed"

    requests = tab(sender, "activity", view="requests")
    assert f"Request {world.delivery_request.pk}" in requests.content.decode()
    journeys = tab(traveler, "activity", view="journeys")
    assert f"Journey {world.base.journey.pk}" in journeys.content.decode()
    offers = tab(sender, "activity", view="offers")
    offer_row = offers.context["body"]["list"]["rows"][0]
    labels = [cell["label"] for cell in offer_row["cells"]]
    assert labels[-3:-1] == ["Boost", "Traveler total"]
    assert offer_row["cells"][labels.index("Traveler total")]["primary"] != "—"

    deliveries = tab(sender, "deliveries").content.decode()
    assert f"Deal {deal.pk}" in deliveries
    # The counterparty is a link to their own profile.
    assert reverse("admin_console:user-detail", args=(traveler.pk,)) in deliveries

    payments = tab(sender, "payments").context["body"]["list"]["rows"]
    assert any(row["cells"][0]["primary"] == "Deal balance" for row in payments)
    tab(traveler, "payouts")

    disputes = tab(traveler, "trust", view="disputes").context["body"]["list"]["rows"]
    assert len(disputes) == 1
    ratings = tab(traveler, "trust", view="ratings").context["body"]["list"]["rows"]
    assert {row["cells"][0]["primary"] for row in ratings} == {"Received", "Given"}
    tab(traveler, "trust", view="notifications")

    audit = tab(traveler, "audit").context["body"]["list"]["rows"]
    assert any(row["cells"][1]["primary"] == "Admin access disabled" for row in audit)

    # An unknown tab is the Overview, never an error.
    assert client.get(profile_url(traveler, tab="chat")).context["tab"] == "overview"


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_every_role_sees_only_the_tabs_its_capabilities_own(world):
    traveler = world.traveler
    traveler.phone = "+213555123456"
    traveler.save(update_fields=["phone"])

    expected = {
        "support": {"overview", "identity", "activity", "deliveries", "trust", "audit"},
        "ops": {"overview", "activity", "deliveries", "trust", "audit"},
        # Finance and Trust hold `view_deals`, so Activity shows them the offers
        # behind a Deal; requests and journeys stay Ops/Support views.
        "finance": {"overview", "identity", "activity", "deliveries", "payments", "payouts", "trust", "audit"},
        "trust_verification": {"overview", "identity", "activity", "deliveries", "trust", "audit"},
    }
    for role, tabs in expected.items():
        client = client_for(staff(f"j64-{role}@example.com", role))
        page = client.get(profile_url(traveler))
        assert page.status_code == 200, role
        assert {tab["key"] for tab in page.context["tabs"]} == tabs, role
        # A tab outside the role is not rendered even when asked for by URL.
        for hidden in set(TABS) - tabs:
            assert client.get(profile_url(traveler, tab=hidden)).context["tab"] == "overview"
        body = page.content.decode()
        if role != "trust_verification":
            assert traveler.phone not in body, role

    # Trust holds `view_user_sensitive`, so the phone is theirs to see.
    trust = client_for(staff("j64-trust2@example.com", "trust_verification"))
    assert traveler.phone in trust.get(profile_url(traveler)).content.decode()

    # Support can read the person but never the money.
    support = client_for(staff("j64-support2@example.com", "support"))
    overview = support.get(profile_url(traveler)).context["body"]
    assert overview["payout"] is None and overview["issues"] is None

    # A signed-in non-staff user is not an operator.
    assert client_for(world.sender).get(profile_url(traveler)).status_code == 302


@pytest.mark.django_db
def test_no_payout_value_hidden_rating_or_notification_payload_reaches_the_page(world):
    from apps.finance.tests.test_phase_j12_finance_route_performance import (
        SECRET_CCP,
        SECRET_RIP,
    )

    traveler = world.traveler
    Notification.objects.create(
        recipient=traveler,
        channel="deal.funded",
        event_id="j64-private-payload",
        payload={"deal_id": world.deal.pk, "note": "PRIVATE-PAYLOAD-SENTINEL"},
    )
    owner = client_for(staff("j64-owner2@example.com", "super_admin"))
    pages = [owner.get(profile_url(traveler, tab=name)).content.decode() for name in TABS]
    pages.append(owner.get(profile_url(traveler, tab="trust", view="notifications")).content.decode())
    flat = "\n".join(pages)
    for forbidden in ("PRIVATE-PAYLOAD-SENTINEL", SECRET_CCP, SECRET_RIP, "••••"):
        assert forbidden not in flat
    assert "Deal funded" in flat


@pytest.mark.django_db
def test_ratings_inside_the_blind_window_stay_hidden(client):
    scenario = delivered_scenario(client, prefix="j64blind")
    with freeze_at(scenario.deal.rating_window_ends_at - timedelta(hours=1)):
        submit_rating(deal_id=scenario.deal.pk, actor_id=scenario.sender.pk, score=2)
    owner = client_for(staff("j64-owner3@example.com", "super_admin"))
    page = owner.get(profile_url(scenario.traveler, tab="trust", view="ratings"))
    listing = page.context["body"]["list"]
    assert listing["rows"] == []
    assert "1 rating is still inside the blind review window" in listing["note"]
    overview = owner.get(profile_url(scenario.traveler)).context["body"]
    assert next(f for f in overview["facts"] if f["label"] == "Rating received")["value"] == "New"
    assert Rating.objects.filter(ratee=scenario.traveler).count() == 1


# ---------------------------------------------------------------------------
# Cost
# ---------------------------------------------------------------------------


def _grow_history(scenario, count):
    """Cheap, valid history rows for the lists whose growth is measured."""

    base = scenario.delivery_request
    for index in range(count):
        DeliveryRequest.objects.create(
            sender=scenario.sender,
            kind=ParcelRequest.Kind.DELIVERY,
            schema_version=2,
            status=ParcelRequest.Status.OPEN,
            pickup_location=base.pickup_location,
            delivery_location=base.delivery_location,
            ready_window_start=base.ready_window_start,
            ready_window_end=base.ready_window_end,
            deadline_at=base.deadline_at,
            actual_weight_kg=Decimal("1.00"),
            declared_value_eur_cents=5_000,
            traveler_reward_eur_cents=1_500,
            title=f"Growth parcel {index}",
            description="Synthetic growth parcel",
            description_is_accurate=True,
            item_is_legal=True,
            no_prohibited_goods=True,
            declared_value_is_accurate=True,
            customs_responsibilities_understood=True,
            category=ParcelRequest.ItemType.DOCUMENTS,
            item_type=ParcelRequest.ItemType.DOCUMENTS,
        )
        journey = Journey.objects.create(
            traveler=scenario.traveler,
            start_location=scenario.base.journey.start_location,
            destination_location=scenario.base.journey.destination_location,
            status=Journey.Status.ACTIVE,
            published_at=timezone.now(),
        )
        leg = scenario.base.leg
        JourneyLeg.objects.create(
            journey=journey,
            position=0,
            mode=leg.mode,
            origin=leg.origin,
            destination=leg.destination,
            depart_at=leg.depart_at + timedelta(days=index + 1),
            arrive_at=leg.arrive_at + timedelta(days=index + 1),
            capacity_kg=leg.capacity_kg,
            distance_meters=leg.distance_meters,
        )
        Notification.objects.create(
            recipient=scenario.traveler,
            channel="deal.updated",
            event_id=f"j64-growth-{scenario.traveler.pk}-{index}-{count}",
            payload={"deal_id": scenario.deal.pk},
        )
        record_admin_action(
            actor=scenario.admin, action="admin.access_enabled", target=scenario.traveler
        )


MEASURED = (
    ("traveler", {}),
    ("sender", {}),
    ("sender", {"tab": "activity", "view": "requests"}),
    ("traveler", {"tab": "activity", "view": "journeys"}),
    ("sender", {"tab": "activity", "view": "offers"}),
    ("sender", {"tab": "deliveries"}),
    ("sender", {"tab": "payments"}),
    ("traveler", {"tab": "payouts"}),
    ("traveler", {"tab": "identity"}),
    ("traveler", {"tab": "trust", "view": "disputes"}),
    ("traveler", {"tab": "trust", "view": "ratings"}),
    ("traveler", {"tab": "trust", "view": "notifications"}),
    ("traveler", {"tab": "audit"}),
)


def _measure(client, world):
    counts = {}
    for who, params in MEASURED:
        url = profile_url(getattr(world, who), **params)
        client.get(url)  # warm the session and permission caches
        with CaptureQueriesContext(connection) as captured:
            assert client.get(url).status_code == 200
        counts[(who, tuple(sorted(params.items())))] = len(captured.captured_queries)
    return counts


@pytest.mark.django_db
def test_overview_and_every_history_tab_cost_the_same_as_history_grows(world):
    """Flat, and bounded. Twenty-five more requests, journeys, notifications
    and audit rows must not add a single query to any tab, and a page holds a
    page."""

    owner = client_for(staff("j64-owner4@example.com", "super_admin"))
    _grow_history(world, 2)
    small = _measure(owner, world)
    _grow_history(world, 25)
    large = _measure(owner, world)
    assert large == small, {key: (small[key], large[key]) for key in small if small[key] != large[key]}
    # A generous regression ceiling, not a target: the Finance dashboard beside
    # this page costs ~90 queries for one snapshot, and no profile tab may
    # become that.
    assert max(small.values()) <= 40, small

    requests = owner.get(profile_url(world.sender, tab="activity", view="requests"))
    listing = requests.context["body"]["list"]
    assert listing["page_obj"].paginator.count == 28
    assert len(listing["rows"]) == 20
    second = owner.get(profile_url(world.sender, tab="activity", view="requests", page=2))
    assert len(second.context["body"]["list"]["rows"]) == 8
