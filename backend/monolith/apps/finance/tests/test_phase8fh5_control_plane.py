"""H5 economic/query regressions on PostgreSQL; no real provider operations."""

from datetime import datetime, timedelta, timezone as dt_timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import RequestFactory, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.admin_panel.finance_control_plane import finance_control_plane
from apps.admin_panel.permissions import assign_admin_roles
from apps.deals.models import Deal
from apps.finance import ledger, payout_accounting
from apps.finance.control_plane.definitions import DEFINITIONS
from apps.finance.control_plane.drilldown import drilldown
from apps.finance.control_plane.filters import Scope
from apps.finance.control_plane.snapshot import build_snapshot
from apps.finance.models import (
    FinanceHold,
    LedgerEntry,
    PaymentAttempt,
    PaymentOrder,
    PaymentProviderEvent,
    PaymentRefund,
    Payout,
    ProviderDispute,
)
from apps.finance.payout_release import evaluate_payout_release
from apps.finance.services import reconcile_attempt
from .payout_execution_harness import H3_SETTINGS, build_stripe_payout
from .factories import build_scenario
from .test_phase8fh4_manual import configured_h4, build_manual  # noqa: F401

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        connection.vendor != "postgresql", reason="H5 requires PostgreSQL snapshots"
    ),
]


@pytest.fixture(autouse=True)
def no_provider_network():
    from copy import deepcopy
    from importlib import import_module
    from apps.core.models import BusinessSettingsVersion
    from .test_phase8fh3_concurrency import _seed_admin_roles, _seed_settings

    active = _seed_settings()
    if "boost" not in active.policy:
        policy = deepcopy(
            import_module(
                "apps.core.migrations.0006_seed_phase4_business_settings"
            ).PHASE4_POLICY
        )
        policy["boost"].update(
            economics_version="traveler_split_v1",
            minimum_amount_eur_cents=500,
            traveler_share_bps=7500,
        )
        for package in policy["boost"]["packages"]:
            package.pop("price_eur_cents", None)
        BusinessSettingsVersion.objects.filter(pk=active.pk).update(status="retired")
        BusinessSettingsVersion.objects.create(
            version=active.version + 1,
            status="active",
            policy=policy,
            commission_rate_bps=2500,
            pricing_version="h5-fixture",
            activated_at=timezone.now(),
        )
    _seed_admin_roles()
    with (
        patch(
            "requests.sessions.Session.request",
            side_effect=AssertionError("H5 must not call provider APIs"),
        ),
        patch("apps.core.redis_bus.publish_after_commit"),
    ):
        yield


@pytest.fixture
def world():
    with override_settings(**H3_SETTINGS):
        yield build_stripe_payout(prefix="h5")


def scope(**values):
    return Scope.parse({"mode": "test", **values})


def cents(snapshot, key):
    return snapshot["metrics"][key]["amount_eur_cents"]


def record_capture(
    owner,
    *,
    amount,
    purpose="posting_deposit",
    mode="test",
    provider="stripe",
    unapplied=False,
):
    from uuid import uuid4

    extra = build_scenario(prefix=f"h5extra-{uuid4().hex[:8]}")
    if purpose == "deal_balance":
        extra.accept()
        order = extra.balance_order()
        PaymentOrder.objects.filter(pk=order.pk).update(amount_eur_cents=amount)
        order.refresh_from_db()
    else:
        order = PaymentOrder.objects.create(
            owner=extra.sender,
            delivery_request=extra.delivery_request,
            purpose=purpose,
            amount_eur_cents=amount,
        )
    attempt = PaymentAttempt.objects.create(
        order=order,
        provider=provider,
        provider_mode=mode,
        amount_eur_cents=amount,
        payment_currency="EUR",
        provider_amount_minor=amount,
        idempotency_key=f"h5-{order.pk}",
        status="succeeded",
        is_unapplied=unapplied,
        succeeded_at=timezone.now(),
    )
    ledger.record_customer_payment(
        attempt_id=attempt.pk,
        order_id=order.pk,
        owner_id=order.owner_id,
        amount_eur_cents=amount,
        purpose=purpose,
    )
    return order, attempt


def test_funding_payable_recognition_and_read_only_snapshot(world):
    s, payout, _, capture = world
    before = LedgerEntry.objects.count()
    with CaptureQueriesContext(connection) as recorded:
        snapshot = build_snapshot(scope())
    assert cents(snapshot, "gross_funded") == capture.amount_eur_cents
    assert cents(snapshot, "traveler_outstanding") == 6000
    assert cents(snapshot, "liability_eligible") == 6000
    assert cents(snapshot, "recognized_revenue") == 0
    assert cents(snapshot, "pending_earnings") == capture.amount_eur_cents - 6000
    assert snapshot["integrity"]["status"] == "ok"
    assert len(recorded) < 100
    assert all(
        not q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
        for q in recorded
    )
    assert LedgerEntry.objects.count() == before
    assert set(snapshot["metrics"]) <= set(DEFINITIONS)
    evaluate_payout_release(deal_id=s.deal.pk)
    recognized = build_snapshot(scope())
    assert cents(recognized, "recognized_revenue") == capture.amount_eur_cents - 6000
    assert cents(recognized, "pending_earnings") == 0
    assert recognized["integrity"]["status"] == "ok"
    assert drilldown(scope(), metric="recognized_revenue")["rows"][0]["effective_at"]


def historical_capture(amount=300, mode="test", provider="stripe"):
    order, attempt = record_capture(
        None, amount=amount, mode="legacy_unknown", provider=provider
    )
    PaymentAttempt.objects.filter(pk=attempt.pk).update(
        provider_mode=mode, mode_evidence="historical_provider_evidence"
    )
    event = PaymentProviderEvent.objects.create(
        attempt=attempt,
        order=order,
        provider=provider,
        provider_event_id=f"h501-{attempt.pk}",
        signature_verified=True,
        processing_result="applied",
        payload={"livemode": mode == "live"},
    )
    return attempt, event


def test_h501_proven_funding_reconciles_without_economic_mutation():
    from apps.finance.control_plane.queries import mode_ledger

    attempts = [
        historical_capture(amount, provider=provider)[0]
        for amount, provider in (
            (300, "stripe"),
            (438, "stripe"),
            (663, "chargily"),
            (6837, "stripe"),
        )
    ]
    before = list(LedgerEntry.objects.values())
    snapshot = build_snapshot(scope())
    assert cents(snapshot, "gross_funded") == cents(snapshot, "net_funded") == 8238
    assert snapshot["integrity"]["status"] == "ok"
    assert snapshot["integrity"]["provenance"][
        "derived_from_authoritative_payment_attempt"
    ] == {
        "status": "verified",
        "entry_count": 8,
    }
    assert (
        snapshot["integrity"]["comparisons"]["applied_funding"]["difference_eur_cents"]
        == 0
    )
    assert mode_ledger("legacy_unknown").filter(attempt__in=attempts).count() == 0
    assert mode_ledger("live").filter(attempt__in=attempts).count() == 0
    assert (
        drilldown(scope(), metric="gross_funded")["totals"]["amount_eur_cents"] == 8238
    )
    assert list(LedgerEntry.objects.values()) == before
    assert all(
        row.transaction.provider_mode == "legacy_unknown"
        for row in LedgerEntry.objects.all()
    )


@pytest.mark.parametrize(
    "case",
    [
        "unrelated",
        "unsigned",
        "missing",
        "conflict",
        "wrong_order",
        "ambiguous",
        "live",
    ],
)
def test_h501_unknown_and_conflicting_provenance_stays_isolated(case):
    from apps.finance.control_plane.queries import mode_ledger

    attempt, event = historical_capture(mode="live" if case == "live" else "test")
    if case == "unrelated":
        PaymentAttempt.objects.filter(pk=attempt.pk).update(mode_evidence="")
    elif case == "unsigned":
        PaymentProviderEvent.objects.filter(pk=event.pk).update(
            signature_verified=False
        )
    elif case == "missing":
        PaymentProviderEvent.objects.filter(pk=event.pk).update(payload={})
    elif case == "conflict":
        PaymentProviderEvent.objects.create(
            attempt=attempt,
            order_id=attempt.order_id,
            provider="stripe",
            provider_event_id="h501-conflict",
            signature_verified=True,
            payload={"livemode": True},
        )
    elif case == "wrong_order":
        PaymentProviderEvent.objects.filter(pk=event.pk).update(order=None)
    elif case == "ambiguous":
        # Fixture a malformed legacy link without altering amounts/accounts.
        LedgerEntry.objects.filter(attempt=attempt, account="sender_deposit").update(
            attempt=None
        )
    before = list(LedgerEntry.objects.values())
    assert not mode_ledger("test").exists()
    if case == "live":
        assert mode_ledger("live").count() == 2
        assert not mode_ledger("legacy_unknown").exists()
        assert build_snapshot(scope(mode="live"))["integrity"]["status"] == "ok"
    else:
        assert mode_ledger("legacy_unknown").count() == 2
        assert build_snapshot(scope())["integrity"]["status"] == "mismatch"
    assert list(LedgerEntry.objects.values()) == before


def test_deposit_credit_boost_and_duplicate_attempts_do_not_add_funding(world):
    s, _, _, original = world
    deposit, attempt = record_capture(s.sender, amount=500)
    balance, balance_attempt = record_capture(
        s.sender, amount=5500, purpose="deal_balance"
    )
    PaymentOrder.objects.filter(pk=balance.pk).update(
        amount_eur_cents=6000, credited_eur_cents=500, credit_source=deposit
    )
    ledger.record_deposit_credit(
        deposit_order_id=deposit.pk,
        balance_order_id=balance.pk,
        owner_id=s.sender.pk,
        amount_eur_cents=500,
        deal_id=s.deal.pk,
    )
    boost, boost_attempt = record_capture(s.sender, amount=800, purpose="boost")
    ledger.record_boost_binding(
        deal_id=s.deal.pk, order_id=boost.pk, purchase_id=999, amount_eur_cents=800
    )
    # Replayed ledger posting and provider success are idempotent. A corrupt
    # duplicate succeeded attempt without a posting must not inflate volume.
    ledger.record_customer_payment(
        attempt_id=attempt.pk,
        order_id=deposit.pk,
        owner_id=s.sender.pk,
        amount_eur_cents=500,
        purpose="posting_deposit",
    )
    reconcile_attempt(
        attempt_id=original.pk,
        outcome="succeeded",
        provider_payment_id=original.provider_payment_id,
        provider_amount_minor=original.provider_amount_minor,
        provider_currency="EUR",
    )
    snapshot = build_snapshot(scope())
    assert cents(snapshot, "gross_funded") == original.amount_eur_cents + 6000 + 800
    assert cents(snapshot, "deposits_collected") == 500
    assert cents(snapshot, "deposits_credited") == 500
    assert cents(snapshot, "deposits_held") == 0
    assert cents(snapshot, "boost_funded") == 800
    assert snapshot["integrity"]["status"] == "ok"
    PaymentAttempt.objects.create(
        order=balance,
        provider="stripe",
        provider_mode="test",
        status="succeeded",
        amount_eur_cents=5500,
        payment_currency="EUR",
        provider_amount_minor=5500,
        succeeded_at=timezone.now(),
        idempotency_key="duplicate-without-ledger",
    )
    duplicate = build_snapshot(scope())
    assert cents(duplicate, "gross_funded") == cents(snapshot, "gross_funded")
    assert duplicate["integrity"]["status"] == "mismatch"


def test_refunds_net_funding_and_unapplied_cash(world):
    s, _, _, original = world
    order, capture = record_capture(s.sender, amount=1000)
    _, unapplied = record_capture(s.sender, amount=700, unapplied=True)
    for attempt, amount in ((capture, 400), (unapplied, 700)):
        refund = PaymentRefund.objects.create(
            order=attempt.order,
            attempt=attempt,
            provider="stripe",
            provider_mode="test",
            amount_eur_cents=amount,
            reason="admin",
            idempotency_key=f"refund-{attempt.pk}",
            status="succeeded",
            succeeded_at=timezone.now(),
        )
        ledger.record_refund(
            refund_id=refund.pk,
            order_id=attempt.order_id,
            owner_id=s.sender.pk,
            amount_eur_cents=amount,
            purpose="posting_deposit",
        )
    snapshot = build_snapshot(scope())
    assert cents(snapshot, "gross_funded") == original.amount_eur_cents + 1000
    assert cents(snapshot, "refunds_finalized") == 1100
    assert cents(snapshot, "refunds_applied") == 400
    assert cents(snapshot, "net_funded") == original.amount_eur_cents + 600
    assert snapshot["integrity"]["status"] == "warning"
    assert (
        snapshot["integrity"]["comparisons"]["finalized_refunds"][
            "difference_eur_cents"
        ]
        == 0
    )
    assert snapshot["integrity"]["source_attributed_legacy_entry_count"] == 2
    for index, status in enumerate(("pending", "processing", "failed")):
        PaymentRefund.objects.create(
            order=order,
            attempt=capture,
            provider="stripe",
            provider_mode="test",
            amount_eur_cents=100,
            reason="admin",
            idempotency_key=f"open-{index}",
            status=status,
        )
    pending = build_snapshot(scope())
    assert cents(pending, "refunds_outstanding") == 200
    assert cents(pending, "refunds_failed") == 100
    assert pending["integrity"]["status"] == "warning"


def test_multiple_holds_and_provider_disputes_do_not_multiply_payable(world):
    s, payout, account, capture = world
    for kwargs in (
        {"payout": payout},
        {"deal": s.deal},
        {"account": account},
        {"source_attempt": capture},
    ):
        FinanceHold.objects.create(
            **kwargs, kind="manual", reason_code="qa", source_reference="qa"
        )
    snapshot = build_snapshot(scope())
    assert cents(snapshot, "held_payouts") == 6000
    assert snapshot["metrics"]["held_payouts"]["count"] == 1
    assert cents(snapshot, "liability_held") == 6000
    ProviderDispute.objects.create(
        provider="stripe",
        platform_id="qa",
        provider_mode="test",
        provider_object_id="dp_qa",
        source_attempt=capture,
        amount_minor=6000,
        currency="eur",
        canonical_amount_eur_cents=None,
        status="needs_response",
    )
    disputed = build_snapshot(scope())
    assert cents(disputed, "liability_disputed") == 6000
    assert cents(disputed, "liability_held") == 0
    assert disputed["metrics"]["provider_disputes"]["status"] == "partial"
    assert cents(disputed, "provider_disputes") is None
    assert (
        drilldown(scope(held="disputed"), metric="traveler_outstanding")["totals"][
            "count"
        ]
        == 1
    )


def test_stripe_lifecycle_and_late_return(world):
    from apps.finance.payout_execution import execute_payout
    from apps.finance.payout_reconciliation import reconcile_payout
    from .payout_execution_harness import FakeConnect, authorise_auto_stripe

    _, payout, _, _ = world
    authorise_auto_stripe()
    gateway = FakeConnect()
    execute_payout(payout.pk, gateway=gateway)
    connected = build_snapshot(scope())
    assert cents(connected, "connected_funds") == 6000
    assert cents(connected, "bank_in_transit") == 0
    assert cents(connected, "liability_processing") == 6000
    assert cents(connected, "externally_committed") == 6000
    execute_payout(payout.pk, gateway=gateway)
    pending = build_snapshot(scope())
    assert cents(pending, "connected_funds") == 0
    assert cents(pending, "bank_in_transit") == 6000
    gateway.payout_status = "in_transit"
    reconcile_payout(payout.pk, gateway=gateway)
    assert cents(build_snapshot(scope()), "liability_sent") == 6000
    gateway.payout_status = "paid"
    reconcile_payout(payout.pk, gateway=gateway)
    paid = build_snapshot(scope())
    assert cents(paid, "traveler_outstanding") == 0
    assert cents(paid, "payouts_settled") == 6000
    assert paid["integrity"]["status"] == "ok"
    gateway.payout_status = "failed"
    reconcile_payout(payout.pk, gateway=gateway)
    returned = build_snapshot(scope())
    assert cents(returned, "traveler_outstanding") == 6000
    assert cents(returned, "payouts_settled") == 6000
    assert cents(returned, "payout_returns") == 6000
    assert cents(returned, "connected_funds") == 6000
    assert cents(returned, "liability_blocked") == 6000
    assert returned["integrity"]["status"] == "ok"


def test_failed_bank_payout_is_not_paid(world):
    # A pre-paid failure moves the asset back without discharging liability.
    from uuid import uuid4

    _, payout, _, _ = world
    operation = SimpleNamespace(public_reference=uuid4())
    disbursement = SimpleNamespace(public_reference=uuid4(), pk=999)
    allocations = [SimpleNamespace(payout=payout, amount_eur_cents=6000)]
    payout_accounting.record_transfer_accepted(
        operation=operation, payout=payout, amount_eur_cents=6000
    )
    payout_accounting.record_bank_payout_submitted(
        disbursement=disbursement, allocations=allocations
    )
    payout_accounting.record_bank_payout_failed(
        disbursement=disbursement, allocations=allocations
    )
    snapshot = build_snapshot(scope())
    assert cents(snapshot, "payouts_settled") == 0
    assert cents(snapshot, "traveler_outstanding") == 6000
    assert cents(snapshot, "bank_in_transit") == 0
    assert cents(snapshot, "connected_funds") == 6000


@pytest.mark.usefixtures("configured_h4")
def test_manual_frozen_fx_claimed_sent_settled():
    from apps.finance.payout_manual import prepare, begin, confirm
    from apps.finance.payout_evidence import upload_evidence
    from .test_phase8fh4_manual import image_upload

    s, payout, _ = build_manual(prefix="h5dzd")

    def manual_snapshot():
        result = build_snapshot(scope(rail="manual_dzd"))
        assert result["integrity"]["status"] == "ok"
        groups = result["rail_operations"]
        assert len(groups) == 1 and groups[0]["amount_eur_cents"] == 6000
        assert groups[0]["amount_dzd"] == 15600
        details = drilldown(
            scope(rail="manual_dzd", operation=groups[0]["operation_stage"]),
            metric="payout_operations",
        )
        assert details["totals"]["amount_eur_cents"] == 6000
        assert details["totals"]["amount_dzd"] == 15600
        assert details["rows"][0]["fx_rate_micros"] == 260000000
        return result, groups[0]["operation_stage"]

    assert manual_snapshot()[1] == "waiting_for_finance"
    prepare(
        actor=s.admin, payout_id=payout.pk, expected_state_version=payout.state_version
    )
    assert manual_snapshot()[1] == "claimed"
    begin(actor=s.admin, payout_id=payout.pk, sequence=1)
    assert manual_snapshot()[1] == "transfer_processing"
    receipt = upload_evidence(
        actor=s.admin, upload=image_upload(), purpose="transfer_receipt"
    )
    confirm(
        actor=s.admin,
        payout_id=payout.pk,
        sequence=1,
        evidence_reference=receipt.public_reference,
        confirmed=True,
    )
    sent, stage = manual_snapshot()
    assert stage == "transfer_sent" and cents(sent, "traveler_outstanding") == 6000
    receipt2 = upload_evidence(
        actor=s.admin, upload=image_upload(), purpose="transfer_receipt"
    )
    confirm(
        actor=s.admin,
        payout_id=payout.pk,
        sequence=1,
        evidence_reference=receipt2.public_reference,
        confirmed=True,
        settled=True,
    )
    settled, stage = manual_snapshot()
    assert stage == "settled" and cents(settled, "traveler_outstanding") == 0
    assert cents(settled, "payouts_settled") == 6000


def test_protection_pre_delivery_and_bucket_conservation(world):
    s, payout, _, _ = world
    Payout.objects.filter(pk=payout.pk).update(status="not_eligible", eligible_at=None)
    Deal.objects.filter(pk=s.deal.pk).update(
        protection_ends_at=timezone.now() + timedelta(hours=24)
    )
    protected = build_snapshot(scope())
    assert cents(protected, "liability_protection") == 6000
    Deal.objects.filter(pk=s.deal.pk).update(
        status="funded", delivery_confirmed_at=None, protection_ends_at=None
    )
    before_delivery = build_snapshot(scope())
    assert cents(before_delivery, "liability_pre_delivery") == 6000
    assert (
        sum(
            value["amount_eur_cents"]
            for key, value in before_delivery["metrics"].items()
            if key.startswith("liability_")
        )
        == 6000
    )


def test_mode_provider_rail_state_search_and_pagination(world):
    s, payout, _, capture = world
    record_capture(s.sender, amount=900, mode="live")
    record_capture(s.sender, amount=800, mode="legacy_unknown")
    record_capture(s.sender, amount=700, provider="chargily")
    test = build_snapshot(scope())
    assert cents(test, "gross_funded") == capture.amount_eur_cents + 700
    assert cents(build_snapshot(scope(mode="live")), "gross_funded") == 900
    assert cents(build_snapshot(scope(mode="legacy_unknown")), "gross_funded") == 800
    assert cents(build_snapshot(scope(provider="chargily")), "gross_funded") == 700
    for filters in (
        {"provider": "stripe"},
        {"rail": "stripe_eur"},
        {"currency": "EUR"},
        {"state": "eligible"},
        {"search": str(payout.public_reference)},
        {"search": f"ST-{s.deal.pk}"},
        {"search": f"TR-{s.traveler.pk}"},
    ):
        rows = drilldown(scope(**filters), metric="traveler_outstanding", page_size=1)
        assert rows["totals"]["amount_eur_cents"] == 6000
        assert len(rows["rows"]) == 1 and not rows["has_next"]
    assert (
        drilldown(scope(rail="manual_dzd"), metric="traveler_outstanding")["rows"] == []
    )
    assert drilldown(scope(held="true"), metric="traveler_outstanding")["rows"] == []
    assert drilldown(scope(), metric="gross_funded", page_size=1)["has_next"]
    assert (
        len(drilldown(scope(), metric="gross_funded", page=2, page_size=1)["rows"]) == 1
    )
    with pytest.raises(ValidationError):
        drilldown(scope(), metric="gross_funded", page_size=101)


def test_dates_are_paris_calendar_days_and_balances_are_current(world):
    now = datetime(2026, 3, 29, 18, tzinfo=dt_timezone.utc)
    paris = Scope.parse({"mode": "test", "period": "today"}, now=now)
    assert (
        paris.end.astimezone(dt_timezone.utc) - paris.start.astimezone(dt_timezone.utc)
    ).total_seconds() == 23 * 3600
    old = timezone.localdate() - timedelta(days=7)
    report = build_snapshot(scope(period="custom", start=str(old), end=str(old)))
    assert cents(report, "gross_funded") == 0
    assert cents(report, "traveler_outstanding") == 6000
    for values in (
        {"mode": "unknown"},
        {"provider": "sql"},
        {"search": "x' OR 1=1"},
        {"unexpected": "x"},
    ):
        with pytest.raises(ValidationError):
            scope(**values)


def test_revenue_correction_keeps_original_period_and_final_settlement_evidence():
    past = timezone.now() - timedelta(days=7)
    with (
        override_settings(**H3_SETTINGS),
        patch("django.utils.timezone.now", return_value=past),
    ):
        s, payout, _, capture = build_stripe_payout(prefix="h5period")
        evaluate_payout_release(deal_id=s.deal.pk, at=past)
    original = capture.amount_eur_cents - 6000
    ledger.record_correction(
        key="h5:later:platform_adjustment",
        note="Synthetic retained-fee correction",
        legs=[
            ledger.Leg(
                account="platform_commission",
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
    paris_date = past.astimezone(scope().start.tzinfo).date()
    historical = build_snapshot(
        scope(period="custom", start=str(paris_date), end=str(paris_date))
    )
    assert cents(historical, "recognized_revenue") == original
    today = build_snapshot(scope(period="today"))
    assert cents(today, "recognized_revenue") == -100
    assert cents(today, "pending_earnings") == 0
    assert today["integrity"]["status"] == "ok"


def test_f1_boost_is_funded_once_and_recognised_only_at_close():
    """A J2 Boost reconciles without confusing any existing H5 definition.

    It has no payment order of its own, so it reaches H5 inside the Deal
    balance: `gross_funded` counts it once, `traveler_outstanding` carries the
    Traveler's bonus, and its commission sits in `pending_earnings` until the
    Deal closes -- exactly like the base commission, and never twice.

    `boost_commission` reports that commission apart from the delivery
    commission, which is the one thing a merged `platform_commission` total
    cannot answer. It is a display metric: it is not added to gross funded
    volume and it is not a reconciliation input.
    """

    from apps.boosts.services import set_boost_intent
    from apps.finance.models import LedgerTransaction

    with override_settings(**H3_SETTINGS):
        s = build_scenario(prefix="h5boost")
        set_boost_intent(
            delivery_request_id=s.delivery_request.pk,
            actor_id=s.sender.pk,
            amount_eur_cents=777,
        )

        def pay(order, label):
            amount = order.outstanding_eur_cents
            capture = PaymentAttempt.objects.create(
                order=order,
                provider="stripe",
                provider_mode="test",
                amount_eur_cents=amount,
                payment_currency="EUR",
                provider_amount_minor=amount,
                idempotency_key=label,
                status="checkout_pending",
            )
            reconcile_attempt(
                attempt_id=capture.pk,
                outcome="succeeded",
                provider_payment_id=label,
                provider_amount_minor=amount,
                provider_currency="EUR",
            )
            return amount

        s.accept(reward_eur_cents=2000)
        # base 2000 + base commission 500 + boost 777 + boost commission 195
        balance_amount = pay(s.balance_order(), "h5boost-balance")
        assert balance_amount == 3472

    payout = Payout.objects.get(deal=s.deal)
    # The Traveler is owed the reward plus the whole boost.
    assert payout.amount_eur_cents == 2777
    before = build_snapshot(scope())
    # Counted once, and only from the balance capture.
    assert cents(before, "gross_funded") == balance_amount
    assert cents(before, "boost_funded") == 0
    assert cents(before, "boost_commission") == 195
    assert cents(before, "pending_earnings") == 500 + 195
    assert cents(before, "recognized_revenue") == 0
    assert LedgerTransaction.objects.filter(kind="boost_binding").count() == 0
    assert (
        LedgerTransaction.objects.filter(
            key=f"deal_boost_allocation:deal:{s.deal.pk}"
        ).count()
        == 1
    )
    # Immutable final-settlement event is valid earning evidence even when no
    # commission correction was needed and the Deal was not clean-completed.
    from apps.deals.models import DealEvent

    DealEvent.objects.create(
        deal=s.deal, kind="dispute_resolved", payload={"synthetic": True}
    )
    after = build_snapshot(scope())
    assert cents(after, "recognized_revenue") == 500 + 195
    assert cents(after, "pending_earnings") == 0
    assert after["integrity"]["status"] == "ok"


def test_ledger_state_discrepancies_cannot_cancel_silently(world):
    s, payout, _, capture = world
    ledger.record_correction(
        key="h5:bad-payable",
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
    report = build_snapshot(scope())
    assert cents(report, "traveler_outstanding") == 5900
    assert report["integrity"]["status"] == "mismatch"
    comparison = report["integrity"]["comparisons"]["traveler_state_to_ledger"]
    assert (
        comparison["difference_eur_cents"] == 100 and comparison["row_mismatches"] == 1
    )


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
def test_finance_permissions_and_privacy(world, role, allowed):
    import json
    from django.core.exceptions import PermissionDenied

    s, _, _, _ = world
    assign_admin_roles(s.admin, [role])
    request = RequestFactory().get("/console/finance/control-plane/", {"mode": "test"})
    request.user = s.admin
    with override_settings(FINANCE_DASHBOARD_ENABLED=True):
        if not allowed:
            with pytest.raises(PermissionDenied):
                finance_control_plane(request)
        else:
            response = finance_control_plane(request)
            assert response.status_code == 200
            assert "no-store" in response["Cache-Control"]
            body = response.content.decode()
            parsed = json.loads(body)
            assert parsed["scope"]["mode"] == "test"
            assert type(parsed["payouts"][0]["amount_eur_cents"]) is int
            assert type(parsed["rail_operations"][0]["amount_eur_cents"]) is int
            for private in (
                s.sender.email,
                s.traveler.email,
                "sk_test_",
                "ba_1TESTbank",
                "ccp_number",
                "rip_last_four",
                "provider_account_id",
            ):
                assert private not in body


def test_flag_invalid_input_and_mutation_refusal(world):
    from django.http import Http404

    s, _, _, _ = world
    from django.urls import reverse, resolve

    route = reverse("admin_console:finance-control-plane")
    assert route == "/admin/finance/control-plane/"
    assert resolve(route).func == finance_control_plane
    factory = RequestFactory()
    req = factory.get("/console/finance/control-plane/", {"mode": "test"})
    req.user = s.admin
    with override_settings(FINANCE_DASHBOARD_ENABLED=False), pytest.raises(Http404):
        finance_control_plane(req)
    with override_settings(FINANCE_DASHBOARD_ENABLED=True):
        missing = factory.get("/console/finance/control-plane/")
        missing.user = s.admin
        assert finance_control_plane(missing).status_code == 400
        post = factory.post("/console/finance/control-plane/", {"mode": "test"})
        post.user = s.admin
        assert finance_control_plane(post).status_code == 405


def test_user_dispute_is_separate_and_postgres_plan_uses_existing_indexes(world):
    import json
    from apps.disputes.models import Dispute
    from apps.finance.control_plane.queries import Queries
    from apps.finance.control_plane.snapshot import consistent_read

    s, payout, _, _ = world
    Dispute.objects.create(
        deal=s.deal,
        opened_by=s.sender,
        opened_by_role="sender",
        category="other",
        reason_text="QA private reason",
    )
    report = build_snapshot(scope())
    assert cents(report, "user_disputed_payouts") == 6000
    assert cents(report, "provider_disputed_payouts") == 0
    assert cents(report, "liability_disputed") == 6000
    with consistent_read():
        with connection.cursor() as cursor:
            # On a ten-row test table a sequential scan is the planner's
            # rational choice, so an unqualified EXPLAIN here measures how much
            # data happened to precede this test in the same database rather
            # than indexed query support. Check that the scoped payout query
            # can use one of the ledger indexes already present.
            # Accept either selective deal/account ledger index: statistics can
            # change the chosen index without changing indexed query support.
            cursor.execute("SET LOCAL enable_seqscan = off")
            constraints = connection.introspection.get_constraints(
                cursor, LedgerEntry._meta.db_table
            )
            ledger_indexes = {
                name: info["columns"][0]
                for name, info in constraints.items()
                if info["index"] and info["columns"]
                and info["columns"][0] in ("deal_id", "account")
            }
        plan = json.loads(
            Queries(scope(search=str(payout.public_reference)), as_of=timezone.now())
            .payouts.values("pk", "payable")
            .explain(format="JSON", analyze=True)
        )
    assert plan[0]["Plan"]["Actual Rows"] == 1
    def nodes(node):
        yield node
        for child in node.get("Plans", []):
            yield from nodes(child)

    index_access = [
        (node.get("Index Name"), node.get("Index Cond", ""))
        for node in nodes(plan[0]["Plan"])
        if node.get("Index Name") in ledger_indexes
    ]
    # A named index appearing anywhere is insufficient: the ledger scan must
    # constrain its indexed leading column, rather than scan an entire index.
    assert any(
        ledger_indexes[name] in condition for name, condition in index_access
    ), {"ledger_indexes": ledger_indexes, "index_access": index_access, "plan": plan}
    assert "QA private reason" not in str(
        drilldown(scope(), metric="user_disputed_payouts")
    )
