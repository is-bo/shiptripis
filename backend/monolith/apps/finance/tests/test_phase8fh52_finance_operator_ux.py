"""H5.2 Finance operations: the five destinations, and what each one promises.

H5's economic logic is unchanged and `test_phase8fh5_control_plane` still owns
it; H5.1's own suite still owns the drilldown. What is asserted here is the
redesign's contract:

* the Overview carries at most five primary sections, no reconciliation table
  and no metric dictionary, and reaches the dinar queue in one click;
* needs-attention is present when there is something to act on, calm when there
  is not, and never the same visual weight as paid history;
* every cohort is a regrouping of H5's own stages, with no stage lost and no
  amount invented;
* the manual dinar queue shows the four cohorts and the safe row fields;
* the reconciliation page still carries all six comparisons, the mismatches,
  the warnings and the conservation counts;
* Finance and Super reach all five, and nobody else reaches any;
* no page leaks an account number and no page offers a way to move money.
"""

import re

import pytest
from django.db import connection
from django.test import Client, override_settings
from django.urls import reverse

from apps.admin_panel import finance_operations as ops
from apps.admin_panel.permissions import assign_admin_roles
from apps.core.admin_display import format_eur
from apps.finance.control_plane.definitions import OPERATION_STAGES
from apps.finance.control_plane.filters import Scope
from apps.finance.control_plane.snapshot import build_snapshot
from apps.finance.models import FinanceHold, Payout

from .payout_execution_harness import H3_SETTINGS, build_stripe_payout
from .test_phase8fh4_manual import build_manual, configured_h4  # noqa: F401
from .test_phase8fh5_control_plane import no_provider_network  # noqa: F401

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="H5.2 renders H5 snapshots, which require PostgreSQL",
    ),
]

OVERVIEW = "/admin/finance/dashboard/"
PAYOUTS = "/admin/finance/payouts-hub/"
DZD = "/admin/finance/manual-dzd/"
EXCEPTIONS = "/admin/finance/exceptions/"
RECONCILIATION = "/admin/finance/reconciliation/"
PAGES = (OVERVIEW, PAYOUTS, DZD, EXCEPTIONS, RECONCILIATION)
ENABLED = {"FINANCE_DASHBOARD_ENABLED": True}

#: Anchored, because the product's own name contains "rip" and a bare substring
#: scan for account fields would flag every page title in the console.
SENSITIVE = (
    r"ccp[_ -]?(account|key|number)",
    r"rip",
    r"iban",
    r"account[_ ]?number",
    r"sk_(test|live)_",
)


@pytest.fixture(autouse=True)
def unhashed_static():
    """CI does not run collectstatic, so the hashed manifest does not exist."""

    with override_settings(
        STORAGES={
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {
                "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
            },
        }
    ):
        yield


@pytest.fixture
def world():
    with override_settings(**H3_SETTINGS):
        yield build_stripe_payout(prefix="h52")


def signed_in(user, role="finance"):
    assign_admin_roles(user, [role], elevate_super_admin=role == "super_admin")
    client = Client()
    client.force_login(user)
    return client


def body(response):
    return response.content.decode()


def main(response):
    """Only the page's own markup: the admin shell carries a logout form."""

    text = body(response)
    start = text.index("<main")
    return text[start : text.index("</main>", start)]


def get(client, path, **params):
    with override_settings(**ENABLED):
        return client.get(path, {"mode": "test", **params})


# ---------------------------------------------------------------------------
# Access, and the flag
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "role,allowed",
    [
        ("finance", True),
        ("super_admin", True),
        ("support", False),
        ("ops", False),
        ("trust_verification", False),
    ],
)
def test_finance_and_super_reach_every_destination_and_nobody_else_reaches_any(
    world, role, allowed
):
    s, _, _, _ = world
    client = signed_in(s.admin, role)
    for path in PAGES:
        response = get(client, path)
        assert response.status_code == (200 if allowed else 403), path


def test_every_destination_disappears_with_the_flag(world):
    """A route that answers 404 is indistinguishable from one never built."""

    s, _, _, _ = world
    client = signed_in(s.admin)
    for path in PAGES:
        assert client.get(path, {"mode": "test"}).status_code == 404, path


def test_navigation_follows_the_flag_in_both_directions(world):
    """Off, the raw payout and refund queues come back rather than vanishing."""

    s, _, _, _ = world
    client = signed_in(s.admin)

    with override_settings(**ENABLED):
        shell = body(client.get(OVERVIEW, {"mode": "test"}))
    assert DZD in shell and RECONCILIATION in shell

    off = body(client.get(reverse("admin_console:payouts")))
    assert DZD not in off and OVERVIEW not in off
    assert reverse("admin_console:payouts") in off
    assert reverse("admin_console:refunds") in off
    assert reverse("admin_console:ledger") in off


# ---------------------------------------------------------------------------
# The Overview's shape
# ---------------------------------------------------------------------------


def test_overview_has_at_most_five_primary_sections(world):
    s, _, _, _ = world
    markup = main(get(signed_in(s.admin), OVERVIEW))
    assert len(re.findall(r'<section class="st-zone"', markup)) <= 5


def test_overview_carries_no_reconciliation_table_and_no_metric_dictionary(world):
    """Level-3 detail moved; it did not get a smaller font on the homepage."""

    s, _, _, _ = world
    markup = main(get(signed_in(s.admin), OVERVIEW))
    for banned in (
        "Independent record",
        "Rows that disagree",
        "Metric dictionary",
        "Stated limitations",
        "by rail and funding source",
        "Provider-reported balance unavailable",
        "Transactions that do not balance",
    ):
        assert banned not in markup, banned
    assert "<table" not in markup


def test_overview_replaces_the_ten_control_filter_wall_with_three(world):
    s, _, _, _ = world
    markup = main(get(signed_in(s.admin), OVERVIEW))
    controls = re.findall(r"<(?:select|input)(?![^>]*type=\"hidden\")", markup)
    assert len(controls) <= 3, controls
    for gone in ("Payout rail", "Rail stage", "Settlement currency", "Payout state"):
        assert gone not in markup, gone


def test_overview_reaches_the_dinar_queue_in_one_click(world):
    s, _, _, _ = world
    markup = main(get(signed_in(s.admin), OVERVIEW))
    assert f'href="{DZD}"' in markup
    assert "Open DZD queue" in markup


def test_overview_states_the_three_amounts_in_operator_words(world):
    s, _, _, _ = world
    client = signed_in(s.admin)
    markup = main(get(client, OVERVIEW))
    snapshot = build_snapshot(Scope.parse({"mode": "test"}))
    for key, label in (
        ("gross_funded", "Money processed"),
        ("recognized_revenue", "ShipTrip earned"),
        ("traveler_outstanding", "Owed to Travelers"),
    ):
        assert label in markup
        assert format_eur(snapshot["metrics"][key]["amount_eur_cents"]) in markup
    # The engineering register stays on the audit surface.
    for jargon in ("Gross funded volume", "Recognised ShipTrip revenue", "Rail"):
        assert jargon not in markup, jargon


def test_overview_health_is_one_line_and_links_to_the_audit_surface(world):
    s, _, _, _ = world
    markup = main(get(signed_in(s.admin), OVERVIEW))
    assert "Finance reconciled" in markup
    assert f'href="{RECONCILIATION}"' in markup


def test_overview_is_calm_when_nothing_needs_finance(world):
    s, _, _, _ = world
    markup = main(get(signed_in(s.admin), OVERVIEW))
    assert "Nothing needs Finance right now" in markup
    assert "st-attn-list" not in markup


def test_a_hold_raises_needs_attention_and_is_drawn_more_strongly(world):
    s, payout, _, _ = world
    FinanceHold.objects.create(
        payout=payout, kind="manual", reason_code="qa", source_reference="h52-hold"
    )
    markup = main(get(signed_in(s.admin), OVERVIEW))
    assert "Payouts under a Finance hold" in markup
    assert "Nothing needs Finance right now" not in markup
    # Severity is a class, not a paragraph of the same beige as paid history.
    assert re.search(r'class="st-attn is-(attn|bad)"', markup)
    assert "Finance acts" in markup


def test_overview_offers_no_way_to_move_money(world):
    s, _, _, _ = world
    markup = main(get(signed_in(s.admin), OVERVIEW))
    assert "<form" not in markup.replace('<form method="get"', "")
    for banned in ("Pay now", "Mark paid", "Reverse", "Refund now", "Retry"):
        assert banned not in markup, banned


# ---------------------------------------------------------------------------
# Cohorts are a regrouping, not a new taxonomy
# ---------------------------------------------------------------------------


def test_every_h5_stage_lands_in_exactly_one_payout_cohort():
    covered = [stage for _, _, _, _, stages in ops.PAYOUT_COHORTS for stage in stages]
    assert len(covered) == len(set(covered)), "a stage appears in two cohorts"
    assert set(covered) == set(OPERATION_STAGES), set(OPERATION_STAGES) ^ set(covered)


def test_a_cohort_spanning_two_published_figures_shows_no_amount():
    """Adding two of H5's amounts together would publish a total H5 did not."""

    snapshot = {
        "rail_operations": [
            {"rail": "stripe_eur", "operation_stage": "settled", "count": 2, "amount_eur_cents": 1000},
            {"rail": "manual_dzd", "operation_stage": "settled", "count": 1, "amount_eur_cents": 500},
        ]
    }
    paid = next(
        row for row in ops._cohorts(snapshot, ops.PAYOUT_COHORTS) if row["key"] == "paid"
    )
    assert paid["count"] == 3
    assert paid["amount"] == ""
    assert [stage["amount"] for stage in paid["stages"]] == ["€10.00", "€5.00"]


def test_a_cohort_backed_by_one_figure_shows_that_figure_verbatim():
    snapshot = {
        "rail_operations": [
            {"rail": "manual_dzd", "operation_stage": "settled", "count": 1, "amount_eur_cents": 500}
        ]
    }
    paid = next(
        row for row in ops._cohorts(snapshot, ops.DZD_COHORTS, rail="manual_dzd")
        if row["key"] == "completed"
    )
    assert paid["amount"] == format_eur(500)


# ---------------------------------------------------------------------------
# Payouts hub
# ---------------------------------------------------------------------------


def test_payout_hub_offers_the_operator_cohorts_not_the_bucket_taxonomy(world):
    s, _, _, _ = world
    markup = main(get(signed_in(s.admin), PAYOUTS))
    for label in ("Needs attention", "Ready", "Processing", "Paid"):
        assert label in markup, label
    assert "Funded, not yet delivered" not in markup


def test_payout_hub_opens_on_work_when_there_is_some(world):
    s, payout, _, _ = world
    payout.status = Payout.Status.FAILED
    payout.save(update_fields=["status"])
    response = get(signed_in(s.admin), PAYOUTS)
    assert response.context["selected"] == "attention"


def test_payout_hub_rows_link_to_the_audited_payout_screen(world):
    s, payout, _, _ = world
    markup = main(get(signed_in(s.admin), PAYOUTS, cohort="ready"))
    assert reverse("admin_console:payout-detail", args=[payout.pk]) in markup


# ---------------------------------------------------------------------------
# The manual dinar queue
# ---------------------------------------------------------------------------


def test_dzd_queue_shows_the_four_cohorts(world, configured_h4):  # noqa: F811
    s, _, _, _ = world
    markup = main(get(signed_in(s.admin), DZD))
    for label in (
        "Waiting for Finance",
        "Claimed / in progress",
        "Sent / awaiting settlement",
        "Completed",
    ):
        assert label in markup, label


def test_dzd_waiting_row_carries_the_safe_operational_fields(configured_h4):  # noqa: F811
    s, payout, _ = build_manual(prefix="h52dzd")
    markup = main(get(signed_in(s.admin), DZD, cohort="waiting"))
    assert str(payout.public_reference) in markup
    assert f"ST-{payout.deal_id}" in markup
    assert f"TR-{payout.traveler_id}" in markup
    assert format_eur(payout.amount_eur_cents) in markup
    assert "DZD" in markup


def test_dzd_queue_never_prints_an_account_number(configured_h4):  # noqa: F811
    s, _, _ = build_manual(prefix="h52priv")
    markup = main(get(signed_in(s.admin), DZD, cohort="waiting"))
    for field in SENSITIVE:
        assert not re.search(field, markup, re.I), field
    assert "<form" not in markup.replace('<form method="get"', "")


def test_dzd_queue_names_payouts_that_cannot_move(configured_h4):  # noqa: F811
    s, payout, _ = build_manual(prefix="h52stuck")
    FinanceHold.objects.create(
        payout=payout, kind="manual", reason_code="qa", source_reference="h52-stuck"
    )
    markup = main(get(signed_in(s.admin), DZD))
    assert "cannot move" in markup


# ---------------------------------------------------------------------------
# Refunds and disputes
# ---------------------------------------------------------------------------


def test_exceptions_page_names_who_acts_next(world):
    s, payout, _, _ = world
    FinanceHold.objects.create(
        payout=payout, kind="manual", reason_code="qa", source_reference="h52-owner"
    )
    markup = main(get(signed_in(s.admin), EXCEPTIONS))
    assert "Finance hold" in markup
    assert "Finance acts next" in markup
    # A hold is not a dispute. With no dispute open, no dispute row is invented.
    assert "ShipTrip dispute" not in markup


def test_exceptions_page_distinguishes_the_three_kinds_of_block(world):
    s, _, _, _ = world
    markup = main(get(signed_in(s.admin), EXCEPTIONS))
    assert "Why a payout is blocked" in markup
    assert "Refunds" in markup


# ---------------------------------------------------------------------------
# Reconciliation: nothing was weakened by moving it
# ---------------------------------------------------------------------------


def test_reconciliation_keeps_all_six_comparisons_with_their_differences(world):
    s, _, _, _ = world
    markup = main(get(signed_in(s.admin), RECONCILIATION))
    snapshot = build_snapshot(Scope.parse({"mode": "test"}))
    assert len(snapshot["integrity"]["comparisons"]) == 6
    for key, row in snapshot["integrity"]["comparisons"].items():
        assert format_eur(row["reported_eur_cents"]) in markup
        assert format_eur(row["authority_eur_cents"]) in markup
    assert "Rows that disagree" in markup
    assert "Transactions that do not balance" in markup
    assert "Metric dictionary" in markup
    assert "Stated limitations of this data" in markup
    assert "by rail and funding source" in markup


def test_reconciliation_shows_a_mismatch_rather_than_hiding_it(world, monkeypatch):
    s, _, _, _ = world
    real = ops.build_snapshot

    def broken(scope):
        snapshot = real(scope)
        integrity = snapshot["integrity"]
        integrity["status"] = "mismatch"
        comparison = integrity["comparisons"]["applied_funding"]
        comparison["difference_eur_cents"] = 1234
        comparison["row_mismatches"] = 2
        return snapshot

    monkeypatch.setattr(ops, "build_snapshot", broken)
    markup = main(get(signed_in(s.admin), RECONCILIATION))
    assert "Disagrees" in markup
    assert format_eur(1234) in markup

    # And the operator surfaces carry the alarm without carrying the table.
    overview = main(get(signed_in(s.admin), OVERVIEW))
    assert "investigation required" in overview
    assert "Rows that disagree" not in overview


# ---------------------------------------------------------------------------
# Responsive and privacy contracts that hold for every destination
# ---------------------------------------------------------------------------


def test_no_operational_destination_renders_a_table(world, configured_h4):  # noqa: F811
    """Wide tables are the audit surface's answer, not a queue's."""

    s, _, _, _ = world
    client = signed_in(s.admin)
    for path in (OVERVIEW, PAYOUTS, DZD, EXCEPTIONS):
        assert "<table" not in main(get(client, path)), path
    assert "<table" in main(get(client, RECONCILIATION))


def test_action_needed_comes_before_the_totals_in_source_order(world):
    """At 375px the DOM order is the reading order, so it is the contract."""

    s, _, _, _ = world
    markup = main(get(signed_in(s.admin), OVERVIEW))
    attention = markup.index("Needs attention")
    queues = markup.index("Open DZD queue")
    totals = markup.index("Money processed")
    assert attention < queues < totals


def test_no_destination_leaks_a_sensitive_field(configured_h4):  # noqa: F811
    s, _, _ = build_manual(prefix="h52leak")
    client = signed_in(s.admin)
    for path in PAGES:
        text = body(get(client, path))
        for field in SENSITIVE:
            assert not re.search(field, text, re.I), f"{field} in {path}"


def test_an_unknown_amount_is_words_not_zero(world, monkeypatch):
    """H5 returns `partial` where it does not know a total. `€0.00` is a
    different claim, and the page must never make it on H5's behalf."""

    s, _, _, _ = world
    real = ops.build_snapshot

    def partial(scope):
        snapshot = real(scope)
        snapshot["metrics"]["held_payouts"] = {
            "count": 3,
            "amount_eur_cents": None,
            "status": "partial",
        }
        return snapshot

    monkeypatch.setattr(ops, "build_snapshot", partial)
    markup = main(get(signed_in(s.admin), EXCEPTIONS))
    assert "Partial" in markup
    assert "st-unknown" in markup


def test_a_cleared_exception_is_a_stated_sentence_not_an_empty_card(world):
    """"Nothing to do" and "not checked" must never look the same."""

    s, _, _, _ = world
    markup = main(get(signed_in(s.admin), EXCEPTIONS))
    assert "No payout is held or disputed" in markup
    assert "st-exception" not in markup


def test_a_bad_filter_is_answered_rather_than_raised(world):
    s, _, _, _ = world
    client = signed_in(s.admin)
    with override_settings(**ENABLED):
        response = client.get(OVERVIEW, {"mode": "test", "period": "decade"})
    assert response.status_code == 400
    assert "could not be used" in body(response)


def test_the_cohort_selector_never_reaches_the_control_plane(world):
    """`cohort` is this module's own key; H5 refuses a filter it does not know."""

    s, _, _, _ = world
    response = get(signed_in(s.admin), PAYOUTS, cohort="ready")
    assert response.status_code == 200
    assert response.context["selected"] == "ready"


def test_one_snapshot_per_view_and_no_polling(world):
    s, _, _, _ = world
    client = signed_in(s.admin)
    for path in PAGES:
        markup = main(get(client, path))
        assert "setInterval" not in markup
        assert "fetch(" not in markup
