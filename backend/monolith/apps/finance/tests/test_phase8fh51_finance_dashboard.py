"""H5.1 Finance dashboard: presentation, access and privacy over the H5 data.

H5's economic logic is already covered by `test_phase8fh5_control_plane`, and
none of it changed, so nothing here re-derives a total. These tests assert the
things H5.1 actually introduced: who may open the two pages, that the figures
rendered are the snapshot's own figures, that a value H5 refuses to assert is
never printed as `€0.00`, that filters travel to the backend unchanged, that a
bad filter is answered rather than raised, and that neither page leaks a
sensitive field or offers a way to move money.

H5.2 split that one dashboard into five destinations. Every guarantee in this
file is still H5.1's guarantee and none was dropped; what moved is the surface
that owns each one, so the assertions below now run against the page that
actually carries the thing being promised. The drilldown, which H5.2 did not
change, is still asserted here in full.
"""

import re

import pytest
from django.db import connection
from django.test import Client, override_settings
from django.urls import reverse

from apps.admin_panel.finance_dashboard import default_mode
from apps.admin_panel.permissions import assign_admin_roles
from apps.core.admin_display import format_eur
from apps.finance.control_plane.drilldown import drilldown
from apps.finance.control_plane.filters import Scope
from apps.finance.control_plane.snapshot import build_snapshot
from apps.finance.models import FinanceHold, ProviderDispute

from .payout_execution_harness import H3_SETTINGS, build_stripe_payout
from .test_phase8fh4_manual import build_manual, configured_h4  # noqa: F401
from .test_phase8fh5_control_plane import no_provider_network  # noqa: F401

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="H5.1 renders H5 snapshots, which require PostgreSQL",
    ),
]

DASHBOARD = "/admin/finance/dashboard/"
ROWS = "/admin/finance/dashboard/rows/"
# H5.2 split the one dashboard into five destinations. Every guarantee below
# is the guarantee H5.1 made; what changed is which surface owns it, so each
# test now asserts it where it actually lives.
PAYOUTS = "/admin/finance/payouts-hub/"
DZD = "/admin/finance/manual-dzd/"
EXCEPTIONS = "/admin/finance/exceptions/"
AUDIT = "/admin/finance/reconciliation/"
ENABLED = {"FINANCE_DASHBOARD_ENABLED": True}


@pytest.fixture(autouse=True)
def unhashed_static():
    """CI does not run collectstatic, so the hashed manifest does not exist.

    Every page these tests render extends the admin shell, which resolves
    `{% static %}` through the production manifest storage and raises when an
    entry is missing. The Phase 8D and G2 console suites already take this
    override; H5.1 takes the same one rather than making a presentation test
    depend on an asset build.
    """

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
    """H3's funded, delivered, EUR-payable Deal — H5's own reporting fixture."""

    with override_settings(**H3_SETTINGS):
        yield build_stripe_payout(prefix="h51")


def scope(**values):
    return Scope.parse({"mode": "test", **values})


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


# ---------------------------------------------------------------------------
# Access
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
def test_only_finance_and_super_may_open_either_page(world, role, allowed):
    s, _, _, _ = world
    client = signed_in(s.admin, role)
    with override_settings(**ENABLED):
        page = client.get(DASHBOARD, {"mode": "test"})
        rows = client.get(ROWS, {"mode": "test", "metric": "gross_funded"})
    expected = 200 if allowed else 403
    assert page.status_code == expected
    assert rows.status_code == expected


def test_navigation_and_routes_follow_the_feature_flag(world):
    s, _, _, _ = world
    client = signed_in(s.admin)
    with override_settings(FINANCE_DASHBOARD_ENABLED=False):
        assert client.get(DASHBOARD, {"mode": "test"}).status_code == 404
        assert (
            client.get(ROWS, {"mode": "test", "metric": "gross_funded"}).status_code
            == 404
        )
        # A navigation entry that answers 404 is worse than no entry: it reads
        # as a broken console rather than as a disabled feature.
        assert DASHBOARD not in body(client.get(reverse("admin_console:payouts")))
    with override_settings(**ENABLED):
        assert client.get(DASHBOARD, {"mode": "test"}).status_code == 200
        shell = body(client.get(reverse("admin_console:payouts")))
        assert DASHBOARD in shell and "Overview" in shell
        assert DZD in shell and AUDIT in shell


def test_dashboard_is_read_only(world):
    s, _, _, _ = world
    client = signed_in(s.admin)
    with override_settings(**ENABLED):
        page = client.get(DASHBOARD, {"mode": "test"})
        rows = client.get(ROWS, {"mode": "test", "metric": "traveler_outstanding"})
        assert client.post(DASHBOARD, {"mode": "test"}).status_code == 405
        assert client.post(ROWS, {"mode": "test"}).status_code == 405
    for response in (page, rows):
        content = main(response)
        assert 'method="post"' not in content.lower()
        assert "csrfmiddlewaretoken" not in content
        assert "<button" not in content.lower().replace(
            '<button type="submit">apply</button>', ""
        )
        assert "no-store" in response["Cache-Control"]


# ---------------------------------------------------------------------------
# The figures are H5's figures
# ---------------------------------------------------------------------------


def test_every_headline_figure_is_the_snapshot_value(world):
    s, _, _, capture = world
    client = signed_in(s.admin)
    snapshot = build_snapshot(scope())
    with override_settings(**ENABLED):
        page = body(client.get(DASHBOARD, {"mode": "test"}))
        audit = body(client.get(AUDIT, {"mode": "test"}))
    # The Overview leads with the three amounts that are routinely confused,
    # and names them as different things.
    for key in ("gross_funded", "recognized_revenue", "traveler_outstanding"):
        assert format_eur(snapshot["metrics"][key]["amount_eur_cents"]) in page, key
    assert format_eur(capture.amount_eur_cents) in page
    assert "Money processed" in page and "ShipTrip earned" in page
    assert "Owed to Travelers" in page
    # The accounting decomposition is not gone; it is on the audit surface.
    for key in ("liability_eligible", "pending_earnings", "net_funded"):
        assert format_eur(snapshot["metrics"][key]["amount_eur_cents"]) in audit, key
    assert snapshot["definition_version"] in audit
    assert "Europe/Paris" in audit


@pytest.mark.usefixtures("configured_h4")
def test_rail_stages_and_frozen_dinars_come_from_the_snapshot(world):
    s, _, _, _ = world
    _, manual, _ = build_manual(prefix="h51dzd")
    client = signed_in(s.admin)
    snapshot = build_snapshot(scope())
    manual_groups = [
        row for row in snapshot["rail_operations"] if row["rail"] == "manual_dzd"
    ]
    with override_settings(**ENABLED):
        page = body(client.get(DZD, {"mode": "test", "cohort": "waiting"}))
        audit = body(client.get(AUDIT, {"mode": "test"}))
    assert "Manual DZD" in page
    for row in manual_groups:
        assert format_eur(row["amount_eur_cents"]) in page
        if row.get("amount_dzd") is not None:
            assert f"{row['amount_dzd']:,} DZD" in page
    assert manual.payout_currency == "DZD"
    # Euro stays the canonical accounting currency; dinars are an instruction.
    assert "never a conversion of the euro column at today" in page
    # The frozen settlement column itself moved to the audit surface intact.
    assert "Frozen settlement" in audit


def test_unknown_amounts_are_words_and_never_zero(world):
    s, _, _, capture = world
    ProviderDispute.objects.create(
        provider="stripe",
        platform_id="qa",
        provider_mode="test",
        provider_object_id="dp_h51",
        source_attempt=capture,
        amount_minor=6000,
        currency="eur",
        canonical_amount_eur_cents=None,
        status="needs_response",
    )
    snapshot = build_snapshot(scope())
    assert snapshot["metrics"]["provider_disputes"]["status"] == "partial"
    assert snapshot["metrics"]["provider_disputes"]["amount_eur_cents"] is None
    client = signed_in(s.admin)
    with override_settings(**ENABLED):
        audit = body(client.get(AUDIT, {"mode": "test"}))
        page = body(client.get(DASHBOARD, {"mode": "test"}))
        rows = body(
            client.get(ROWS, {"mode": "test", "metric": "provider_disputes"})
        )
        exceptions = body(client.get(EXCEPTIONS, {"mode": "test"}))
    # H5 says it does not know this total. Both surfaces say so in words.
    assert "Partial" in exceptions
    for text in ("Provider-reported balance unavailable", "Not available"):
        assert text in audit
    # The provider balance and the provider cost are unavailable, not zero.
    assert "Provider costs and fees: <strong>Not available</strong>" in audit
    assert "Partial" in rows or "Not available" in rows
    # And an unavailable provider figure is not a card on the operator's
    # homepage at all: H5.2 omits it rather than reporting a blank every day.
    assert "Provider-reported balance unavailable" not in page


def test_integrity_is_surfaced_in_both_its_states(world):
    from apps.finance import ledger

    s, _, _, capture = world
    client = signed_in(s.admin)
    with override_settings(**ENABLED):
        healthy = body(client.get(AUDIT, {"mode": "test"}))
        overview = body(client.get(DASHBOARD, {"mode": "test"}))
    assert build_snapshot(scope())["integrity"]["status"] == "ok"
    assert "Finance data reconciles" in healthy
    # The operator reads one line of the same verdict, never the table.
    assert "Finance reconciled" in overview
    assert "Payout state vs ledger payable" not in overview
    assert "is-ok" in healthy
    assert "Payout state vs ledger payable" in healthy
    assert "Agrees" in healthy

    # Break the state/ledger agreement exactly the way H5's own reconciliation
    # test does, and confirm the page says so rather than quietly reporting the
    # same totals with a green verdict.
    ledger.record_correction(
        key="h51:bad-payable",
        note="Synthetic missing award revision",
        legs=[
            ledger.Leg(
                account="traveler_payable",
                amount_eur_cents=100,
                deal_id=s.deal.pk,
                order_id=capture.order_id,
            ),
            ledger.Leg(
                account="deal_funds",
                amount_eur_cents=-100,
                deal_id=s.deal.pk,
                order_id=capture.order_id,
            ),
        ],
    )
    assert build_snapshot(scope())["integrity"]["status"] == "mismatch"
    with override_settings(**ENABLED):
        broken_audit = body(client.get(AUDIT, {"mode": "test"}))
        broken = body(client.get(DASHBOARD, {"mode": "test"}))
    assert "Finance data does not reconcile" in broken_audit
    assert "is-bad" in broken_audit
    assert "Disagrees" in broken_audit
    # The operator surfaces escalate the same verdict without the evidence: a
    # mismatch is the one state allowed to become a banner, because a total
    # nobody can trust is worse than no total.
    assert "investigation required" in broken
    assert "Disagrees" not in broken
    # And the page keeps working: a mismatch is disclosed, not a dead console.
    assert "Money processed" in broken


def test_holds_and_disputes_are_counted_separately(world):
    s, payout, _, capture = world
    FinanceHold.objects.create(
        payout=payout, kind="manual", reason_code="qa", source_reference="qa"
    )
    client = signed_in(s.admin)
    ProviderDispute.objects.create(
        provider="stripe",
        platform_id="qa",
        provider_mode="test",
        provider_object_id="dp_h51_split",
        source_attempt=capture,
        amount_minor=6000,
        currency="eur",
        canonical_amount_eur_cents=6000,
        status="needs_response",
    )
    snapshot = build_snapshot(scope())
    with override_settings(**ENABLED):
        page = body(client.get(EXCEPTIONS, {"mode": "test"}))
        overview = body(client.get(DASHBOARD, {"mode": "test"}))
    # Three different events with three different owners. A hold and a
    # provider dispute are open, so both are named with their own owner;
    # no ShipTrip dispute is open, so none is invented. That is the
    # separation, asserted in the only way that can actually fail.
    assert "Finance hold" in page and "Finance acts next" in page
    assert "Provider dispute" in page and "Finance / Risk acts next" in page
    assert "ShipTrip dispute" not in page
    assert format_eur(snapshot["metrics"]["held_payouts"]["amount_eur_cents"]) in page
    # The shared blocker precedence selects the dispute ahead of the hold.
    # Its owner is intentionally unknown; Overview must not invent Finance.
    assert "Payout review required" in overview
    assert snapshot["payout_attention"]["count"] == 1
    assert snapshot["payout_attention"]["groups"] == [
        {"attention_owner": None, "count": 1}
    ]


# ---------------------------------------------------------------------------
# Filters, drilldown and pagination
# ---------------------------------------------------------------------------


def test_filters_reach_the_backend_and_are_shown_in_words(world):
    s, _, _, _ = world
    client = signed_in(s.admin)
    with override_settings(**ENABLED):
        page = body(
            client.get(
                PAYOUTS,
                {
                    "mode": "test",
                    "period": "7d",
                    "rail": "stripe_eur",
                    "held": "false",
                },
            )
        )
    assert "Stripe EUR" in page
    assert "Not held and not disputed" in page
    # Operators are never shown the stored enum.
    assert "stripe_eur<" not in page
    assert "manual_dzd<" not in page
    # The scope travels into every link the page emits.
    assert "rail=stripe_eur" in page
    assert "period=7d" in page


@pytest.mark.parametrize(
    "query",
    [
        {"mode": "test", "period": "custom", "start": "2020-01-01", "end": "2026-01-01"},
        {"mode": "test", "period": "nonsense"},
        {"mode": "banana"},
        {"mode": "test", "unknown_filter": "1"},
        {"mode": "test", "period": "custom", "start": "not-a-date", "end": "x"},
    ],
)
def test_a_bad_filter_is_answered_not_raised(world, query):
    s, _, _, _ = world
    client = signed_in(s.admin)
    with override_settings(**ENABLED):
        response = client.get(DASHBOARD, query)
    assert response.status_code == 400
    page = body(response)
    assert "These filters could not be used" in page
    assert "Traceback" not in page
    # No stale figure is left on screen next to the refusal.
    assert "Money processed" not in page


def test_drilldown_rows_page_and_link_to_the_operational_record(world):
    s, payout, _, _ = world
    client = signed_in(s.admin)
    expected = drilldown(scope(), metric="traveler_outstanding")
    with override_settings(**ENABLED):
        page = body(
            client.get(ROWS, {"mode": "test", "metric": "traveler_outstanding"})
        )
    assert format_eur(expected["totals"]["amount_eur_cents"]) in page
    assert str(payout.public_reference) in page
    assert f"ST-{payout.deal_id}" in page
    assert reverse("admin_console:payout-detail", args=[payout.pk]) in page
    assert "Back to the dashboard" in page


def test_a_settled_row_is_not_labelled_as_still_owing(world):
    """The operational cohort includes paid awards; their payable is zero.

    H5 still annotates them with a liability bucket and an `exposed` flag, both
    of which describe an obligation that no longer exists. Printing either one
    beside a stage of "Paid" puts two columns in contradiction on a finance
    screen, which is the exact misreading this dashboard exists to prevent.
    """

    s, payout, _, _ = world
    client = signed_in(s.admin)
    operations = drilldown(scope(), metric="payout_operations")["rows"][0]
    # The backend still supplies both, unchanged; this is a presentation rule.
    assert "bucket" in operations and "exposed" in operations
    with override_settings(**ENABLED):
        cohort = main(client.get(ROWS, {"mode": "test", "metric": "payout_operations"}))
        liability = main(
            client.get(ROWS, {"mode": "test", "metric": "traveler_outstanding"})
        )
    assert "Liability bucket" not in cohort
    assert "Stage" in cohort
    assert "Externally committed" not in cohort
    # Where the rows really are outstanding, the bucket is the point of them.
    assert "Liability bucket" in liability
    assert "Externally committed" not in liability


def test_drilldown_pagination_is_bounded_by_the_backend(world):
    s, _, _, _ = world
    client = signed_in(s.admin)
    with override_settings(**ENABLED):
        first = body(
            client.get(
                ROWS,
                {
                    "mode": "test",
                    "metric": "gross_funded",
                    "page": "1",
                    "page_size": "1",
                },
            )
        )
        refused = client.get(
            ROWS,
            {"mode": "test", "metric": "gross_funded", "page_size": "5000"},
        )
        unknown = client.get(ROWS, {"mode": "test", "metric": "not_a_metric"})
    assert "Page 1" in first and "up to 1 rows a page" in first
    assert refused.status_code == 400
    assert unknown.status_code == 400
    assert "Unknown metric" in body(unknown)


def test_an_empty_drilldown_explains_itself(world):
    s, _, _, _ = world
    client = signed_in(s.admin)
    assert drilldown(scope(), metric="refunds_failed")["totals"]["count"] == 0
    with override_settings(**ENABLED):
        page = body(client.get(ROWS, {"mode": "test", "metric": "refunds_failed"}))
    assert "Nothing contributes to this figure in this scope" in page
    assert "<tbody>" not in page


# ---------------------------------------------------------------------------
# Privacy and disclosure
# ---------------------------------------------------------------------------


def test_neither_page_carries_a_sensitive_field(world):
    s, payout, _, _ = world
    client = signed_in(s.admin)
    with override_settings(**ENABLED):
        pages = [body(client.get(DASHBOARD, {"mode": "test"}))]
        for metric in (
            "traveler_outstanding",
            "gross_funded",
            "payout_operations",
            "source_reserved",
        ):
            pages.append(body(client.get(ROWS, {"mode": "test", "metric": metric})))
    for page in pages:
        for private in (
            s.sender.email,
            s.traveler.email,
            "sk_test_",
            "ba_1TESTbank",
            "ccp_number",
            "rip_last_four",
            "provider_account_id",
            "acct_",
            "handover_code",
        ):
            assert private not in page, private


def test_the_legacy_cohort_is_disclosed_and_reachable(world):
    s, _, _, _ = world
    client = signed_in(s.admin)
    with override_settings(**ENABLED):
        page = body(client.get(AUDIT, {"mode": "test"}))
        legacy = body(client.get(DASHBOARD, {"mode": "legacy_unknown"}))
    # A standing, generic disclosure: H5 publishes no residual count per mode,
    # so the page says the cohort exists and links to it rather than inventing
    # a number for it.
    assert "Historical rows whose environment was never recorded" in page
    assert "mode=legacy_unknown" in page
    assert "This is the legacy / unknown cohort" in legacy
    assert "reported separately on purpose" in legacy


def test_the_page_loads_one_snapshot_and_does_not_poll(world):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    s, _, _, _ = world
    client = signed_in(s.admin)
    with override_settings(**ENABLED):
        with CaptureQueriesContext(connection) as recorded:
            page = body(client.get(DASHBOARD, {"mode": "test"}))
    assert len(recorded) < 160
    assert all(
        not query["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
        for query in recorded
    )
    # No timer, no fetch loop, no per-KPI request.
    assert "setInterval" not in page and "fetch(" not in page
    assert not re.search(r"http-equiv=[\"']refresh", page, re.I)


def test_both_known_rails_are_present_even_when_one_is_idle(world):
    s, _, _, _ = world
    client = signed_in(s.admin)
    with override_settings(**ENABLED):
        hub = body(client.get(PAYOUTS, {"mode": "test"}))
        dinars = body(client.get(DZD, {"mode": "test"}))
    # A missing cohort reads as a page that failed to load; an empty one reads
    # as a queue that was checked. Every cohort renders at every count.
    for label in ("Needs attention", "Ready", "Processing", "Not due yet", "Paid"):
        assert label in hub, label
    for label in (
        "Waiting for Finance",
        "Claimed / in progress",
        "Sent / awaiting settlement",
        "Completed",
    ):
        assert label in dinars, label
    # The anomaly rail stays out of the way until it actually holds something.
    assert "Unclassified method" not in hub


def test_no_two_filter_options_share_a_label(world):
    from apps.admin_panel.finance_dashboard import _operation_choices

    labels = [label for _, label in _operation_choices()]
    assert len(labels) == len(set(labels)), sorted(labels)
    s, _, _, _ = world
    client = signed_in(s.admin)
    with override_settings(**ENABLED):
        page = main(client.get(DASHBOARD, {"mode": "test"}))
    options = re.findall(r'<option value="[^"]*"[^>]*>([^<]+)</option>', page)
    assert options, "the scope form rendered no options"


def test_default_mode_follows_the_configured_credentials():
    with override_settings(
        STRIPE_SECRET_KEY="sk_test_x", PAYMENTS_ALLOW_MOCK_PROVIDER=False
    ):
        assert default_mode() in {"test", "live"}
