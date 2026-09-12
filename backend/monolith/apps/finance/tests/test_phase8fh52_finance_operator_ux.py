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

**Each test builds one world and asks it everything.** Every case here needs a
funded, delivered, payable Deal driven through the real services, and each page
render is a full control-plane snapshot — roughly seventy annotated queries, by
design. One assertion per test would be the clearer shape, and it put the CI
Django job over its thirty-minute cap: five surfaces now render where one did.
So related assertions share a fixture, and each test name says which promise
its group covers.
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
    r"\bccp[_ -]?(account|key|number)\b",
    r"\brip\b",
    r"\biban\b",
    r"\baccount[_ ]?number\b",
    r"\bsk_(test|live)_",
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


def staff(role, prefix):
    """A fresh operator per role.

    Reusing one account across the matrix does not work: elevating it to Super
    sets `is_superuser`, which `has_admin_permission` treats as a blanket yes,
    and every later role then passes every check.
    """

    from django.contrib.auth import get_user_model

    user = get_user_model().objects.create_user(
        username=f"{prefix}-{role}@example.com", email=f"{prefix}-{role}@example.com"
    )
    return signed_in(user, role)


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


def hold(payout, reference):
    return FinanceHold.objects.create(
        payout=payout, kind="manual", reason_code="qa", source_reference=reference
    )


# ---------------------------------------------------------------------------
# Cohorts are a regrouping of H5's own stages, not a new taxonomy.
# These two need no world: they assert the mapping itself.
# ---------------------------------------------------------------------------


def test_every_h5_stage_lands_in_exactly_one_payout_cohort():
    covered = [stage for _, _, _, _, stages in ops.PAYOUT_COHORTS for stage in stages]
    assert len(covered) == len(set(covered)), "a stage appears in two cohorts"
    assert set(covered) == set(OPERATION_STAGES), set(OPERATION_STAGES) ^ set(covered)


def test_no_cohort_invents_an_amount_h5_did_not_publish():
    """Adding two of H5's amounts together would publish a total H5 did not."""

    spanning = {
        "rail_operations": [
            {"rail": "stripe_eur", "operation_stage": "settled", "count": 2, "amount_eur_cents": 1000},
            {"rail": "manual_dzd", "operation_stage": "settled", "count": 1, "amount_eur_cents": 500},
        ]
    }
    paid = next(
        row for row in ops._cohorts(spanning, ops.PAYOUT_COHORTS) if row["key"] == "paid"
    )
    # Counts may be grouped: H5's stages are disjoint and a count is not a total.
    assert paid["count"] == 3
    assert paid["amount"] == ""
    assert [stage["amount"] for stage in paid["stages"]] == ["€10.00", "€5.00"]

    # One published figure behind the cohort, so that figure is shown verbatim.
    single = {"rail_operations": [spanning["rail_operations"][1]]}
    completed = next(
        row
        for row in ops._cohorts(single, ops.DZD_COHORTS, rail="manual_dzd")
        if row["key"] == "completed"
    )
    assert completed["amount"] == format_eur(500)


# ---------------------------------------------------------------------------
# Access, the flag, and what the navigation does in both of its states
# ---------------------------------------------------------------------------


def test_finance_and_super_reach_every_destination_and_the_flag_governs_all_five(world):
    s, _, _, _ = world

    for role, allowed in (
        ("finance", True),
        ("super_admin", True),
        ("support", False),
        ("ops", False),
        ("trust_verification", False),
    ):
        client = staff(role, "h52role")
        for path in PAGES:
            assert get(client, path).status_code == (200 if allowed else 403), (role, path)

    client = signed_in(s.admin)
    # A route that answers 404 is indistinguishable from one never built.
    for path in PAGES:
        assert client.get(path, {"mode": "test"}).status_code == 404, path

    with override_settings(**ENABLED):
        shell = body(client.get(OVERVIEW, {"mode": "test"}))
    assert DZD in shell and RECONCILIATION in shell

    # Off, the raw payout and refund queues come back rather than vanishing:
    # they are not part of the control plane and must not disappear with it.
    off = body(client.get(reverse("admin_console:payouts")))
    assert DZD not in off and OVERVIEW not in off
    assert reverse("admin_console:payouts") in off
    assert reverse("admin_console:refunds") in off
    assert reverse("admin_console:ledger") in off


# ---------------------------------------------------------------------------
# The Overview's shape, language and reading order
# ---------------------------------------------------------------------------


def test_overview_is_five_calm_zones_in_operator_words(world):
    s, _, _, _ = world
    client = signed_in(s.admin)
    markup = main(get(client, OVERVIEW))
    snapshot = build_snapshot(Scope.parse({"mode": "test"}))

    # At most five primary sections.
    assert len(re.findall(r'<section class="st-zone"', markup)) <= 5

    # Level-3 detail moved; it did not get a smaller font on the homepage.
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

    # Three scope controls, not eleven.
    controls = re.findall(r"<(?:select|input)(?![^>]*type=\"hidden\")", markup)
    assert len(controls) <= 3, controls
    for gone in ("Payout rail", "Rail stage", "Settlement currency", "Payout state"):
        assert gone not in markup, gone

    # The dinar queue is one click away.
    assert f'href="{DZD}"' in markup and "Open DZD queue" in markup

    # The three amounts that are routinely confused, named as different things.
    for key, label in (
        ("gross_funded", "Money processed"),
        ("recognized_revenue", "ShipTrip earned"),
        ("traveler_outstanding", "Owed to Travelers"),
    ):
        assert label in markup
        assert format_eur(snapshot["metrics"][key]["amount_eur_cents"]) in markup
    for jargon in ("Gross funded volume", "Recognised ShipTrip revenue", "Rail"):
        assert jargon not in markup, jargon

    # Health is one line, and it opens the audit surface.
    assert "Finance reconciled" in markup
    assert f'href="{RECONCILIATION}"' in markup

    # Nothing to do is a stated sentence, not an absence and not empty cards.
    assert "Nothing needs Finance right now" in markup
    assert "st-attn-list" not in markup

    # Nothing on this page can move money.
    assert "<form" not in markup.replace('<form method="get"', "")
    for banned in ("Pay now", "Mark paid", "Reverse", "Refund now", "Retry"):
        assert banned not in markup, banned

    # At 375px the DOM order is the reading order, so it is the contract.
    assert (
        markup.index("Needs attention")
        < markup.index("Open DZD queue")
        < markup.index("Money processed")
    )

    # One snapshot per view. No timer, no fetch loop, no per-figure request.
    assert "setInterval" not in markup and "fetch(" not in markup


def test_a_raised_state_is_drawn_more_strongly_and_names_its_owner(world):
    s, payout, _, _ = world
    hold(payout, "h52-hold")
    markup = main(get(signed_in(s.admin), OVERVIEW))

    assert "Payouts under a Finance hold" in markup
    assert "Nothing needs Finance right now" not in markup
    # Severity is a class, not a paragraph of the same beige as paid history.
    assert re.search(r'class="st-attn is-(attn|bad)"', markup)
    assert "Finance acts" in markup


# ---------------------------------------------------------------------------
# The payout operations hub
# ---------------------------------------------------------------------------


def test_payout_hub_groups_by_what_an_operator_asks_and_opens_the_real_screen(world):
    s, payout, _, _ = world
    client = signed_in(s.admin)

    markup = main(get(client, PAYOUTS))
    for label in ("Needs attention", "Ready", "Processing", "Not due yet", "Paid"):
        assert label in markup, label
    # Nobody should need H5's eleven-bucket taxonomy to find a payout.
    assert "Funded, not yet delivered" not in markup

    # The harness leaves its payout eligible, which is the `ready` cohort, and
    # a row opens the audited screen that owns it.
    ready = get(client, PAYOUTS, cohort="ready")
    assert ready.context["selected"] == "ready"
    assert reverse("admin_console:payout-detail", args=[payout.pk]) in main(ready)

    # `cohort` is this module's own key; H5 refuses a filter it does not know,
    # so it must never reach `Scope.parse`.
    assert get(client, PAYOUTS, cohort="attention").status_code == 200

    # And the hub opens on work when there is some.
    payout.status = Payout.Status.FAILED
    payout.save(update_fields=["status"])
    assert get(client, PAYOUTS).context["selected"] == "attention"


# ---------------------------------------------------------------------------
# The manual dinar queue
# ---------------------------------------------------------------------------


def test_dzd_queue_shows_four_cohorts_with_safe_rows_and_names_what_cannot_move(
    configured_h4,  # noqa: F811
):
    s, payout, _ = build_manual(prefix="h52dzd")
    client = signed_in(s.admin)
    markup = main(get(client, DZD, cohort="waiting"))

    for label in (
        "Waiting for Finance",
        "Claimed / in progress",
        "Sent / awaiting settlement",
        "Completed",
    ):
        assert label in markup, label

    # The row carries what an operator needs and nothing they must not have.
    assert str(payout.public_reference) in markup
    assert f"ST-{payout.deal_id}" in markup
    assert f"TR-{payout.traveler_id}" in markup
    assert format_eur(payout.amount_eur_cents) in markup
    assert "DZD" in markup
    for field in SENSITIVE:
        assert not re.search(field, markup, re.I), field
    assert "<form" not in markup.replace('<form method="get"', "")

    # Blocked, held and disputed dinar payouts are in none of the four cohorts
    # and must not be quietly missing from the page either.
    hold(payout, "h52-stuck")
    assert "cannot move" in main(get(client, DZD))


# ---------------------------------------------------------------------------
# Refunds and disputes
# ---------------------------------------------------------------------------


def test_exceptions_page_names_the_owner_and_stays_calm_when_there_is_nothing(world):
    s, payout, _, _ = world
    client = signed_in(s.admin)

    calm = main(get(client, EXCEPTIONS))
    assert "Why a payout is blocked" in calm
    assert "Refunds" in calm
    # "Nothing to do" and "not checked" must never look the same, and a zero is
    # not an exception worth a card every morning.
    assert "No payout is held or disputed" in calm
    assert "st-exception" not in calm

    hold(payout, "h52-owner")
    raised = main(get(client, EXCEPTIONS))
    assert "Finance hold" in raised
    assert "Finance acts next" in raised


def test_an_amount_h5_refuses_to_assert_is_words_and_never_zero(world, monkeypatch):
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


# ---------------------------------------------------------------------------
# Reconciliation: nothing was weakened by moving it
# ---------------------------------------------------------------------------


def test_reconciliation_keeps_every_comparison_and_a_mismatch_escalates(
    world, monkeypatch
):
    s, _, _, _ = world
    client = signed_in(s.admin)
    markup = main(get(client, RECONCILIATION))
    snapshot = build_snapshot(Scope.parse({"mode": "test"}))

    assert len(snapshot["integrity"]["comparisons"]) == 6
    for row in snapshot["integrity"]["comparisons"].values():
        assert format_eur(row["reported_eur_cents"]) in markup
        assert format_eur(row["authority_eur_cents"]) in markup
    assert "Rows that disagree" in markup
    assert "Transactions that do not balance" in markup
    assert "Metric dictionary" in markup
    assert "Stated limitations of this data" in markup
    assert "by rail and funding source" in markup

    real = ops.build_snapshot

    def broken(scope):
        snap = real(scope)
        snap["integrity"]["status"] = "mismatch"
        comparison = snap["integrity"]["comparisons"]["applied_funding"]
        comparison["difference_eur_cents"] = 1234
        comparison["row_mismatches"] = 2
        return snap

    monkeypatch.setattr(ops, "build_snapshot", broken)
    audit = main(get(client, RECONCILIATION))
    assert "Disagrees" in audit and format_eur(1234) in audit

    # The operator surfaces carry the alarm without carrying the evidence.
    overview = main(get(client, OVERVIEW))
    assert "investigation required" in overview
    assert "Rows that disagree" not in overview


# ---------------------------------------------------------------------------
# Contracts that hold for every destination
# ---------------------------------------------------------------------------


def test_no_destination_leaks_a_sensitive_field_or_explodes_into_tables(
    configured_h4,  # noqa: F811
):
    s, _, _ = build_manual(prefix="h52leak")
    client = signed_in(s.admin)

    for path in PAGES:
        text = body(get(client, path))
        for field in SENSITIVE:
            assert not re.search(field, text, re.I), f"{field} in {path}"

    # Wide tables are the audit surface's answer, never a queue's.
    for path in (OVERVIEW, PAYOUTS, DZD, EXCEPTIONS):
        assert "<table" not in main(get(client, path)), path
    assert "<table" in main(get(client, RECONCILIATION))

    # A bad filter is answered, not raised, and leaves no stale figure behind.
    with override_settings(**ENABLED):
        response = client.get(OVERVIEW, {"mode": "test", "period": "decade"})
    assert response.status_code == 400
    assert "could not be used" in body(response)
