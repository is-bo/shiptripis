"""J2's mandatory H5 financial regression, on synthetic TEST data.

J2 changes economics: a Boost now arrives inside the Deal balance instead of on
its own order, its commission is a separately configured rate charged on top,
and a deposit can be any amount the sender chooses. Each of those touches a
number H5 reports, so the phase does not pass on "the unit tests are green" --
it passes on the control plane's own reconciliation coming back clean over a
world built the way a real one is built.

The world below runs the whole sender-side path through production services and
the real mock provider rail: a chosen deposit, a Boost, a guest paying the
deposit, the sender paying the balance, funding, and a settled Deal. Then every
comparison H5 makes has to report a zero difference and zero row mismatches, the
ledger has to balance transaction by transaction, and integrity has to say `ok`.

No real provider is contacted. Captures are built as rows and driven through
`reconcile_attempt`, which is the path a provider webhook takes once the network
is already behind it -- the same technique the H3/H5 harness uses -- and the
module asserts the TEST mode and the absence of any live key explicitly.

The world runs with payout profiles on, because H5's traveler comparisons read
the Payout row and a profile-less Payout is stamped `legacy_unknown` and falls
outside the mode scope entirely. That is pre-existing legacy behaviour, not a J2
effect, but it would make the traveler comparisons vacuous here.
"""

from __future__ import annotations

import pytest
from django.conf import settings
from django.db import connection
from django.db.models import Sum
from django.test import override_settings
from django.utils import timezone

from apps.boosts.services import set_boost_intent
from apps.finance.control_plane.filters import Scope
from apps.finance.control_plane.snapshot import build_snapshot
from apps.finance.models import (
    LedgerEntry,
    PaymentAttempt,
    PaymentOrder,
    Payout,
    PayoutMethodVersion,
    StripePayoutAccount,
)
from apps.finance.payout_profiles import set_preference
from apps.finance.services import (
    create_guest_link,
    ensure_posting_deposit_order,
    reconcile_attempt,
)
from apps.finance.settlement import assert_deal_reconciles

from .factories import build_scenario
from .payout_execution_harness import BANK, CONNECTED, CONTROLLER_SUMMARY, H3_SETTINGS

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        connection.vendor != "postgresql", reason="H5 requires PostgreSQL snapshots"
    ),
]

#: Reward 2000 + commission 500 + boost 800 + boost commission 200.
EXPECTED_BALANCE = 3_500
DEPOSIT = 1_000


@pytest.fixture(autouse=True)
def seeded_business_settings():
    """A transactional test truncates tables; the seeded revision must return.

    Rebuilt through J2's own migration function rather than a hand-written
    policy dict, so this test can never pass against a set of commercial inputs
    the migration does not actually produce.
    """

    from copy import deepcopy
    from importlib import import_module

    from django.apps import apps as django_apps

    from apps.core.models import BusinessSettingsVersion

    if BusinessSettingsVersion.objects.filter(status="active").exists():
        return
    phase4 = import_module("apps.core.migrations.0006_seed_phase4_business_settings")
    BusinessSettingsVersion.objects.create(
        version=1,
        status=BusinessSettingsVersion.Status.ACTIVE,
        canonical_currency="EUR",
        commission_rate_bps=2_500,
        pricing_version="v1-lifecycle-1",
        policy=deepcopy(phase4.PHASE4_POLICY),
        activated_at=timezone.now(),
    )
    # The whole tail of the chain, in order: the Phase 4 base carries no Boost
    # economics at all, and J2 layers its commission onto those.
    import_module("apps.core.migrations.0009_seed_boost_economics").seed_boost_economics(
        django_apps, None
    )
    import_module("apps.core.migrations.0010_seed_j2_boost_commission").seed_j2(
        django_apps, None
    )


def _scope(**values) -> Scope:
    return Scope.parse({"mode": "test", **values})


def _capture(order, *, tag, **extra):
    """Settle one order on the Stripe TEST rail through the webhook path."""

    outstanding = int(order.outstanding_eur_cents)
    attempt = PaymentAttempt.objects.create(
        order=order,
        provider="stripe",
        provider_mode="test",
        amount_eur_cents=outstanding,
        payment_currency="EUR",
        provider_amount_minor=outstanding,
        idempotency_key=f"j2h5-{tag}",
        provider_session_id=f"cs_j2h5_{tag}",
        provider_payment_id=f"pi_j2h5_{tag}",
        status=PaymentAttempt.Status.CHECKOUT_PENDING,
        **extra,
    )
    reconcile_attempt(
        attempt_id=attempt.pk,
        outcome="succeeded",
        provider_payment_id=f"pi_j2h5_{tag}",
        provider_amount_minor=outstanding,
        provider_currency="EUR",
    )
    attempt.refresh_from_db()
    return attempt


def _give_traveler_a_eur_payout_route(traveler):
    """The H3 payout profile a real TEST traveler has before a Deal funds."""

    method = set_preference(
        actor=traveler,
        currency="EUR",
        enabled=True,
        country="FR",
        expected_revision=0,
    )
    account = StripePayoutAccount.objects.create(
        traveler=traveler,
        platform_id=settings.STRIPE_CONNECT_PLATFORM_ACCOUNT_ID,
        provider_account_id=CONNECTED,
        provider_mode="test",
        declared_country="FR",
        verified_country="FR",
        creation_operation_key="j2h5-account",
        status="ready",
        transfers_status="active",
        payouts_enabled=True,
        details_submitted=True,
        eur_bank_present=True,
        external_account_id=BANK,
        default_currency="eur",
        controller_summary=dict(CONTROLLER_SUMMARY),
        payout_schedule_interval="manual",
        readiness_checked_at=timezone.now(),
    )
    version = PayoutMethodVersion.objects.create(
        method=method,
        sequence=2,
        rail="stripe_transfer",
        currency="EUR",
        country="FR",
        stripe_account=account,
        policy_version="payout_profile_v1",
        consent_at=timezone.now(),
        created_by=traveler,
    )
    method.current_version, method.status = version, "ready"
    method.save(update_fields=["current_version", "status"])
    return method


def _build_world():
    """One J2 delivery, paid the J2 way, through production services only."""

    scenario = build_scenario(prefix="j2h5", open_request=False)
    request = scenario.delivery_request

    # A Boost the sender chose, and a deposit they chose -- neither the
    # recommendation nor a fixed fee.
    set_boost_intent(
        delivery_request_id=request.pk,
        actor_id=scenario.sender.pk,
        amount_eur_cents=800,
    )
    request.refresh_from_db()
    deposit = ensure_posting_deposit_order(
        delivery_request=request, chosen_amount_eur_cents=DEPOSIT
    )

    # Somebody else pays the deposit. Same order, same rail, same ledger.
    issued = create_guest_link(order_id=deposit.pk, actor_id=scenario.sender.pk)
    _capture(
        deposit,
        tag="deposit",
        guest_link=issued.link,
        guest_email="relative@example.com",
    )
    request.refresh_from_db()

    deal = scenario.accept(reward_eur_cents=2_000)
    _give_traveler_a_eur_payout_route(scenario.traveler)
    balance = scenario.balance_order()
    _capture(balance, tag="balance")
    return scenario, deal, balance, deposit


@override_settings(**H3_SETTINGS)
def test_j2_economics_reconcile_in_the_finance_control_plane():
    scenario, deal, balance, deposit = _build_world()

    # --- the money is what J2 says it is ---------------------------------
    assert balance.amount_eur_cents == EXPECTED_BALANCE
    balance.refresh_from_db()
    assert balance.credited_eur_cents == DEPOSIT
    assert balance.paid_eur_cents == EXPECTED_BALANCE - DEPOSIT
    assert balance.outstanding_eur_cents == 0
    assert deal.terms.boost_amount_minor == 800
    assert deal.terms.boost_platform_fee_minor == 200
    # The Traveler is owed the reward plus the whole Boost.
    assert Payout.objects.get(deal=deal).amount_eur_cents == 2_800

    # --- the Deal's own subledger nets to zero ---------------------------
    assert assert_deal_reconciles(deal.pk)["net"] == 0

    # --- H5 reconciliation ------------------------------------------------
    snapshot = build_snapshot(_scope())
    integrity = snapshot["integrity"]

    assert integrity["status"] == "ok", integrity
    for name, comparison in integrity["comparisons"].items():
        assert comparison["difference_eur_cents"] == 0, (name, comparison)
        assert comparison["row_mismatches"] == 0, (name, comparison)
    assert integrity["unbalanced_transaction_count"] == 0
    assert not any(integrity["data_issues"].values()), integrity["data_issues"]

    metrics = snapshot["metrics"]
    # Funded volume is the cash that actually arrived: the deposit plus what
    # the balance still needed. The Boost is inside it, counted once.
    assert metrics["gross_funded"]["amount_eur_cents"] == EXPECTED_BALANCE
    assert metrics["deposits_collected"]["amount_eur_cents"] == DEPOSIT
    # No J2 Boost has a payment order, so the retired-package metric is empty
    # and the Boost commission is reported on its own.
    assert metrics["boost_funded"]["amount_eur_cents"] == 0
    assert metrics["boost_commission"]["amount_eur_cents"] == 200
    # Base commission and Boost commission are both pending until the Deal
    # closes, and neither is double counted.
    assert metrics["pending_earnings"]["amount_eur_cents"] == 700
    assert metrics["recognized_revenue"]["amount_eur_cents"] == 0
    assert metrics["traveler_outstanding"]["amount_eur_cents"] == 2_800
    assert metrics["refunds_finalized"]["amount_eur_cents"] == 0

    # --- every ledger transaction balances --------------------------------
    unbalanced = (
        LedgerEntry.objects.order_by()
        .values("transaction_id")
        .annotate(net=Sum("amount_eur_cents"))
        .exclude(net=0)
        .count()
    )
    assert unbalanced == 0

    # --- and nothing real was charged -------------------------------------
    assert not PaymentOrder.objects.filter(purpose=PaymentOrder.Purpose.BOOST).exists()
    providers = set(
        PaymentOrder.objects.filter(pk__in=[balance.pk, deposit.pk])
        .values_list("attempts__provider", flat=True)
        .distinct()
    )
    assert providers == {"stripe"}
    assert settings.STRIPE_SECRET_KEY.startswith("sk_test_")
    modes = set(
        PaymentOrder.objects.filter(pk__in=[balance.pk, deposit.pk])
        .values_list("attempts__provider_mode", flat=True)
        .distinct()
    )
    assert modes == {"test"}
    assert scenario.sender.email.endswith("@example.com")
