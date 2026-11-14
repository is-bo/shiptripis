"""K3 parity and query budgets for the Finance and Admin hot paths.

Wall-clock measurements live in the K3 implementation report because they are
machine-dependent.  These tests pin the two durable properties behind those
measurements: the operational projection agrees with the comprehensive
accounting snapshot, and query counts remain bounded as data or staff grows.
"""

from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.contrib.auth.models import Permission
from django.db import connection
from django.test import Client, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.admin_panel.permissions import (
    assign_admin_roles,
    users_with_admin_permission,
)
from apps.finance.control_plane.attention import attention_projection
from apps.finance.control_plane.filters import Scope
from apps.finance.control_plane.operations import build_operational_snapshot
from apps.finance.control_plane.snapshot import build_snapshot, consistent_read
from apps.finance.tests.factories import make_user
from apps.parcels.models import DeliveryRequest, ParcelRequest
from apps.trips.models import Journey, JourneyLeg

from .test_phase8fh4_manual import build_manual, configured_h4  # noqa: F401
from .test_phase8fh5_control_plane import no_provider_network  # noqa: F401
from .test_phase_j12_finance_route_performance import (
    build_profile,
    console_staticfiles,  # noqa: F401
    detail_url,
)
from apps.admin_panel.tests.two_step_helpers import staff_login

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="K3 Finance snapshots require PostgreSQL",
    ),
]

ENABLED = {"FINANCE_DASHBOARD_ENABLED": True}
OVERVIEW_METRICS = (
    "gross_funded",
    "recognized_revenue",
    "traveler_outstanding",
    "refunds_failed",
)


def scope():
    return Scope.parse({"mode": "test"})


def measured_get(client, url, params=None):
    client.get(url, params or {})
    with CaptureQueriesContext(connection) as captured:
        response = client.get(url, params or {})
    assert response.status_code == 200, url
    return response, len(captured.captured_queries), captured.captured_queries


def sorted_groups(rows):
    return sorted(rows, key=lambda row: (row["rail"], row["operation_stage"]))


def test_operational_snapshot_is_an_exact_subset_of_reconciliation(configured_h4):  # noqa: F811
    build_manual(prefix="k3-parity")

    comprehensive = build_snapshot(scope())
    with consistent_read():
        operational, _queries = build_operational_snapshot(
            scope(),
            metric_names=OVERVIEW_METRICS,
            include_rail_operations=True,
            include_payout_attention=True,
        )

    assert operational["metrics"] == {
        name: comprehensive["metrics"][name] for name in OVERVIEW_METRICS
    }
    assert sorted_groups(operational["rail_operations"]) == sorted_groups(
        comprehensive["rail_operations"]
    )
    assert operational["payout_attention"] == comprehensive["payout_attention"]
    assert operational["definition_version"] == comprehensive["definition_version"]
    # The deep accounting product remains intact and exclusive to reconciliation.
    assert comprehensive["integrity"]["comparisons"]
    assert comprehensive["definitions"]
    assert comprehensive["providers"]


def test_finance_and_admin_routes_have_explicit_query_ceilings(configured_h4):  # noqa: F811
    scenario, payout, _profile = build_manual(prefix="k3-budgets")
    _review_scenario, pending_profile = build_profile(
        "k3-budgets-review", attested=False
    )
    assign_admin_roles(scenario.admin, ["super_admin"], elevate_super_admin=True)
    client = Client()
    staff_login(client, scenario.admin)

    surfaces = {
        "Finance Overview": (
            reverse("admin_console:finance-dashboard"),
            {"mode": "test"},
            35,
        ),
        "Payout Hub": (
            reverse("admin_console:finance-payouts"),
            {"mode": "test"},
            30,
        ),
        "Manual DZD list": (
            reverse("admin_console:finance-dzd"),
            {"mode": "test"},
            30,
        ),
        "Manual DZD detail": (
            reverse("admin_console:payout-detail", args=[payout.pk]),
            {},
            28,
        ),
        "Payout reviews": (
            reverse("admin_console:payout-reviews"),
            {},
            16,
        ),
        "Payout review detail": (detail_url(pending_profile), {}, 32),
        "Payments": (reverse("admin_console:payments"), {}, 10),
        "Reconciliation": (
            reverse("admin_console:finance-reconciliation"),
            {"mode": "test"},
            95,
        ),
        "People": (reverse("admin_console:users"), {}, 8),
        "Person detail": (
            reverse("admin_console:user-detail", args=[scenario.traveler.pk]),
            {},
            30,
        ),
        "Admin Overview": (reverse("admin_console:overview"), {}, 22),
        "Disputes": (reverse("admin_console:disputes"), {}, 10),
    }

    observed = {}
    with override_settings(**ENABLED):
        for name, (url, params, ceiling) in surfaces.items():
            _response, count, _queries = measured_get(client, url, params)
            observed[name] = count
            assert count <= ceiling, {
                "surface": name,
                "count": count,
                "ceiling": ceiling,
            }

    assert observed["Finance Overview"] < observed["Reconciliation"]
    assert observed["Payout Hub"] < observed["Reconciliation"]
    assert observed["Manual DZD list"] < observed["Reconciliation"]


def test_payout_review_detail_cost_does_not_grow_with_reviewer_population(
    configured_h4,  # noqa: F811
):
    scenario, profile = build_profile("k3-reviewers", attested=False)
    client = Client()
    staff_login(client, scenario.admin)

    _response, small, _queries = measured_get(client, detail_url(profile))
    for index in range(24):
        reviewer = make_user(f"k3-reviewer-{index:02d}@example.com", is_staff=True)
        assign_admin_roles(reviewer, ["trust_verification"])
    response, large, _queries = measured_get(client, detail_url(profile))

    assert large == small
    assert large <= 32
    reviewer_ids = {user.pk for user in response.context["reviewers"]}
    assert len(reviewer_ids) == 24


def test_reviewer_selection_preserves_fresh_capability_and_revocation_rules():
    permission = Permission.objects.get(
        content_type__app_label="admin_panel",
        codename="attest_payout_identity",
    )
    group_user = make_user("k3-group-reviewer@example.com", is_staff=True)
    assign_admin_roles(group_user, ["trust_verification"])
    direct_user = make_user("k3-direct-reviewer@example.com", is_staff=True)
    direct_user.user_permissions.add(permission)
    owner = make_user("k3-owner-reviewer@example.com", is_staff=True)
    owner.is_superuser = True
    owner.save(update_fields=["is_superuser"])

    banned = make_user("k3-banned-reviewer@example.com", is_staff=True)
    assign_admin_roles(banned, ["trust_verification"])
    banned.is_banned = True
    banned.save(update_fields=["is_banned"])
    inactive = make_user("k3-inactive-reviewer@example.com", is_staff=True)
    assign_admin_roles(inactive, ["trust_verification"])
    inactive.is_active = False
    inactive.save(update_fields=["is_active"])
    nonstaff = make_user("k3-nonstaff-reviewer@example.com")
    nonstaff.user_permissions.add(permission)

    candidates = {
        group_user.pk,
        direct_user.pk,
        owner.pk,
        banned.pk,
        inactive.pk,
        nonstaff.pk,
    }
    selected = set(
        users_with_admin_permission("attest_payout_identity")
        .filter(pk__in=candidates)
        .values_list("pk", flat=True)
    )
    assert selected == {group_user.pk, direct_user.pk, owner.pk}


def _grow_same_person_activity(scenario, count):
    """Give one account both high-cardinality sides of the People summary."""

    request = scenario.delivery_request
    leg = scenario.leg
    for index in range(count):
        DeliveryRequest.objects.create(
            sender=scenario.sender,
            kind=ParcelRequest.Kind.DELIVERY,
            schema_version=2,
            status=ParcelRequest.Status.OPEN,
            pickup_location=request.pickup_location,
            delivery_location=request.delivery_location,
            ready_window_start=request.ready_window_start,
            ready_window_end=request.ready_window_end,
            deadline_at=request.deadline_at,
            actual_weight_kg=Decimal("1.00"),
            declared_value_eur_cents=5_000,
            traveler_reward_eur_cents=1_500,
            title=f"K3 parcel {index}",
            description="Synthetic K3 performance row",
            description_is_accurate=True,
            item_is_legal=True,
            no_prohibited_goods=True,
            declared_value_is_accurate=True,
            customs_responsibilities_understood=True,
            category=ParcelRequest.ItemType.DOCUMENTS,
            item_type=ParcelRequest.ItemType.DOCUMENTS,
        )
        journey = Journey.objects.create(
            traveler=scenario.sender,
            start_location=scenario.journey.start_location,
            destination_location=scenario.journey.destination_location,
            status=Journey.Status.ACTIVE,
            published_at=timezone.now(),
        )
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


def test_people_counts_do_not_form_a_cartesian_join(configured_h4):  # noqa: F811
    scenario, _payout, _profile = build_manual(prefix="k3-people")
    assign_admin_roles(scenario.admin, ["super_admin"], elevate_super_admin=True)
    client = Client()
    staff_login(client, scenario.admin)
    url = reverse("admin_console:users")

    _response, small, _queries = measured_get(client, url)
    _grow_same_person_activity(scenario, 12)
    response, large, queries = measured_get(client, url)

    assert large == small
    assert large <= 8
    body = response.content.decode()
    assert "13 requests · 12 journeys · 1 Deals" in body
    user_sql = next(
        row["sql"] for row in queries if 'FROM "accounts_user"' in row["sql"]
    )
    assert 'JOIN "parcels_request"' not in user_sql
    assert 'JOIN "trips_journey"' not in user_sql


class _IdsQuery:
    def __init__(self, ids):
        self.ids = ids

    def exclude(self, **_kwargs):
        return self

    def order_by(self, *_fields):
        return self

    def values_list(self, *_fields, **_kwargs):
        return self

    def distinct(self):
        return self

    def __getitem__(self, key):
        return self.ids[key]


def test_attention_projection_loads_one_bounded_graph_past_old_batch_boundary():
    ids = list(range(1, 402))
    rows = [SimpleNamespace(pk=value) for value in ids]
    facts = {"needs_attention": True, "attention_owner": "finance"}
    with (
        patch(
            "apps.finance.control_plane.attention.Payout.objects.filter",
            return_value=rows,
        ) as payout_filter,
        patch(
            "apps.finance.control_plane.attention.payout_read_rows",
            side_effect=lambda value: value,
        ) as read_rows,
        patch(
            "apps.finance.control_plane.attention.page_context", return_value={}
        ) as context,
        patch(
            "apps.finance.control_plane.attention.payout_attention",
            return_value=facts,
        ) as classify,
    ):
        projected = attention_projection(_IdsQuery(ids))

    assert set(projected) == set(ids)
    payout_filter.assert_called_once_with(pk__in=ids)
    read_rows.assert_called_once()
    context.assert_called_once()
    assert classify.call_count == len(ids)
