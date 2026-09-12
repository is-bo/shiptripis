"""A world in which an automatic EUR payout can actually be attempted.

Two things are worth explaining about this harness, because both are deliberate
and both would be wrong in production code.

**The clock.** H3's production gate requires an authoritative
`delivery_confirmed_at` plus a full 48 hours. No test waits for that, and no
endpoint exists that could shorten it, so the fixture writes an already-expired
protection window straight onto the Deal row. That is a database fixture, not a
bypass: `evaluate_payout_release` and `_assert_dispatchable` still read the
stored deadline and still refuse when it has not passed, which is exactly what
`test_protection_still_open_defers` proves.

**The provider.** `FakeConnect` implements the Connect adapter's surface and
nothing else, so every test drives ShipTrip's own state machine rather than a
mocked-out version of it. It records every call, which is how the duplicate and
recovery tests assert *external* effects — "exactly one Transfer was created" is
a claim about `gateway.calls`, not about a local row count.
"""

from __future__ import annotations

import base64
import copy
import json
from dataclasses import replace
from datetime import timedelta

from django.utils import timezone

from apps.core.business_settings import (
    activate_business_settings,
    get_active_business_settings,
)
from apps.core.models import BusinessSettingsVersion
from apps.admin_panel.permissions import assign_admin_roles
from apps.deals.models import Deal
from apps.finance.models import (
    PaymentAttempt,
    Payout,
    PayoutMethodVersion,
    StripePayoutAccount,
)
from apps.finance.payout_profiles import set_preference
from apps.finance.services import reconcile_attempt
from apps.finance.providers.base import ProviderCheckoutRejected, ProviderUnavailable
from apps.finance.providers.stripe_connect import (
    BalanceSnapshot,
    BankPayoutSnapshot,
    ChargeSnapshot,
    TransferSnapshot,
)

from .factories import build_scenario

PLATFORM = "acct_1TESTplatform"
CONNECTED = "acct_1TESTconnected"
BANK = "ba_1TESTbank"

H3_SETTINGS = dict(
    PAYOUT_PROFILES_ENABLED=True,
    STRIPE_CONNECT_ENABLED=True,
    STRIPE_CONNECT_PAYOUTS_ENABLED=True,
    STRIPE_CONNECT_NON_STRIPE_FUNDING_ENABLED=False,
    STRIPE_CONNECT_EXPECTED_MODE="test",
    STRIPE_CONNECT_PLATFORM_ACCOUNT_ID=PLATFORM,
    STRIPE_CONNECT_ALLOWED_COUNTRIES=["FR"],
    STRIPE_CONNECT_MINIMUM_PAYOUT_EUR_CENTS=100,
    STRIPE_SECRET_KEY="sk_test_h3",
    PAYOUT_DATA_KEYRING=json.dumps({"k1": base64.b64encode(b"e" * 32).decode()}),
    PAYOUT_DATA_ACTIVE_KEY_ID="k1",
    PAYOUT_ACCOUNT_FINGERPRINT_KEY=base64.b64encode(b"f" * 32).decode(),
    EMAIL_ENABLED=False,
)

CONTROLLER_SUMMARY = {
    "stripe_dashboard.type": "express",
    "requirement_collection": "stripe",
    "fees.payer": "application",
    "losses.payments": "application",
    "is_controller": True,
}


def authorise_auto_stripe(enabled: bool = True) -> BusinessSettingsVersion:
    """Flip the versioned business authorisation H0 requires alongside the flag.

    The deployment flag says this release *may* move money; this says the
    business has decided it *should*. Both, or nothing happens.
    """

    active = get_active_business_settings()
    policy = copy.deepcopy(active.policy)
    policy["payments"]["payout"]["auto_stripe_enabled"] = enabled
    version = BusinessSettingsVersion.objects.create(
        version=active.version + 1,
        policy=policy,
        status=BusinessSettingsVersion.Status.DRAFT,
        commission_rate_bps=active.commission_rate_bps,
        pricing_version=active.pricing_version,
    )
    return activate_business_settings(version)


class RecordedCall:
    __slots__ = ("name", "kwargs")

    def __init__(self, name, kwargs):
        self.name, self.kwargs = name, kwargs

    def __repr__(self):
        return f"{self.name}({self.kwargs})"


class FakeConnect:
    """The Connect adapter's surface, scripted and recorded.

    `fail` maps a method name to an exception the *next* call raises, which is
    how the fault-injection tests reproduce a timeout at an exact point in the
    protocol. Idempotency is modelled the way Stripe documents it: a repeated
    `create_transfer` or `create_bank_payout` under a key that has already
    executed returns the original object rather than making a second one.
    """

    def __init__(self, *, balance_available=6000):
        self.calls: list[RecordedCall] = []
        self.fail: dict = {}
        self.transfers: dict = {}
        self.payouts: dict = {}
        self.balance_available = balance_available
        self.payout_status = "pending"
        self.charge_refunded = 0
        self.charge_livemode = False
        self._transfer_seq = 0
        self._payout_seq = 0
        self.refund_detail = {}
        self.dispute_detail = {}

    # -- helpers ---------------------------------------------------------

    def _record(self, name, **kwargs):
        self.calls.append(RecordedCall(name, kwargs))
        problem = self.fail.pop(name, None)
        if problem is not None:
            raise problem

    def names(self, name):
        return [call for call in self.calls if call.name == name]

    # -- adapter surface -------------------------------------------------

    def platform_identity(self):
        self._record("platform_identity")
        return None

    def retrieve_account(self, account_id):
        self._record("retrieve_account", account_id=account_id)
        raise AssertionError("Readiness must not be re-read in these fixtures.")

    def latest_charge_for_intent(self, payment_intent_id):
        self._record("latest_charge_for_intent", payment_intent_id=payment_intent_id)
        return payment_intent_id.replace("pi_", "ch_")

    def retrieve_charge(self, charge_id):
        self._record("retrieve_charge", charge_id=charge_id)
        return ChargeSnapshot(
            charge_id=charge_id,
            payment_intent_id=charge_id.replace("ch_", "pi_"),
            status="succeeded",
            paid=True,
            captured=True,
            refunded=bool(self.charge_refunded),
            livemode=self.charge_livemode,
            currency="EUR",
            amount_minor=1_000_000,
            amount_refunded_minor=self.charge_refunded,
            balance_transaction_id="txn_charge",
            transfer_group="",
        )

    def create_transfer(
        self,
        *,
        amount_minor,
        destination,
        source_transaction,
        transfer_group,
        idempotency_key,
        metadata,
        currency="eur",
    ):
        self._record(
            "create_transfer",
            amount_minor=amount_minor,
            destination=destination,
            source_transaction=source_transaction,
            transfer_group=transfer_group,
            idempotency_key=idempotency_key,
            metadata=dict(metadata),
        )
        if not source_transaction.startswith("ch_"):
            raise ProviderCheckoutRejected("source must be a charge")
        existing = self.transfers.get(idempotency_key)
        if existing is not None:
            return existing
        self._transfer_seq += 1
        snapshot = TransferSnapshot(
            transfer_id=f"tr_{self._transfer_seq}",
            amount_minor=amount_minor,
            currency="EUR",
            destination=destination,
            source_transaction=source_transaction,
            destination_payment=f"py_{self._transfer_seq}",
            balance_transaction_id=f"txn_tr_{self._transfer_seq}",
            transfer_group=transfer_group,
            reversed=False,
            amount_reversed_minor=0,
            livemode=False,
            metadata=dict(metadata),
        )
        self.transfers[idempotency_key] = snapshot
        return snapshot

    def retrieve_transfer(self, transfer_id):
        self._record("retrieve_transfer", transfer_id=transfer_id)
        for snapshot in self.transfers.values():
            if snapshot.transfer_id == transfer_id:
                return snapshot
        raise ProviderCheckoutRejected("no such transfer")

    def find_transfer_by_metadata(self, *, key, value, transfer_group, limit=100):
        self._record(
            "find_transfer_by_metadata",
            key=key,
            value=value,
            transfer_group=transfer_group,
        )
        matches = [
            snapshot
            for snapshot in self.transfers.values()
            if snapshot.metadata.get(key) == value
        ]
        return matches[0] if len(matches) == 1 else None

    def reverse_transfer(self, *, transfer_id, amount_minor, idempotency_key, metadata):
        self._record(
            "reverse_transfer", transfer_id=transfer_id, amount_minor=amount_minor
        )
        raise AssertionError("No H3 path reverses a transfer automatically.")

    def retrieve_balance(self, *, account_id="", currency="eur"):
        self._record("retrieve_balance", account_id=account_id, currency=currency)
        return BalanceSnapshot(
            account_id=account_id or PLATFORM,
            currency="EUR",
            available_minor=self.balance_available,
            pending_minor=0,
            livemode=False,
        )

    def _payout_snapshot(self, payout_id, amount_minor, status=None):
        return BankPayoutSnapshot(
            payout_id=payout_id,
            amount_minor=amount_minor,
            currency="EUR",
            status=status or self.payout_status,
            method="standard",
            destination=BANK,
            automatic=False,
            balance_transaction_id=f"txn_{payout_id}",
            failure_balance_transaction_id="",
            failure_code="",
            arrival_date=None,
            livemode=False,
            metadata={},
        )

    def create_bank_payout(
        self,
        *,
        account_id,
        amount_minor,
        destination,
        idempotency_key,
        metadata,
        currency="eur",
        method="standard",
    ):
        self._record(
            "create_bank_payout",
            account_id=account_id,
            amount_minor=amount_minor,
            destination=destination,
            idempotency_key=idempotency_key,
            metadata=dict(metadata),
        )
        existing = self.payouts.get(idempotency_key)
        if existing is not None:
            return existing
        self._payout_seq += 1
        snapshot = self._payout_snapshot(f"po_{self._payout_seq}", amount_minor)
        snapshot = replace(snapshot, metadata=dict(metadata))
        self.payouts[idempotency_key] = snapshot
        return snapshot

    def retrieve_bank_payout(self, *, account_id, payout_id):
        self._record(
            "retrieve_bank_payout", account_id=account_id, payout_id=payout_id
        )
        for snapshot in self.payouts.values():
            if snapshot.payout_id == payout_id:
                return replace(snapshot, status=self.payout_status)
        raise ProviderCheckoutRejected("no such payout")

    def find_bank_payout_by_metadata(
        self, *, account_id, key, value, created_gte, limit=100
    ):
        self._record("find_bank_payout_by_metadata", key=key, value=value)
        matches = [
            snapshot
            for snapshot in self.payouts.values()
            if snapshot.metadata.get(key) == value
        ]
        return matches[0] if len(matches) == 1 else None

    def cancel_bank_payout(self, *, account_id, payout_id):
        self._record("cancel_bank_payout", payout_id=payout_id)
        raise ProviderCheckoutRejected("payout is no longer pending")

    def retrieve_refund(self, refund_id):
        self._record("retrieve_refund", refund_id=refund_id)
        return dict(self.refund_detail)

    def retrieve_dispute(self, dispute_id):
        self._record("retrieve_dispute", dispute_id=dispute_id)
        return dict(self.dispute_detail)


def timeout(name="stripe"):
    return ProviderUnavailable(f"{name} timed out", provider_code="timeout")


def build_stripe_payout(
    *,
    prefix="h3",
    reward_eur_cents=6000,
    protection_expired=True,
):
    """A funded, delivered Deal whose Traveler is ready to be paid in EUR.

    Funding goes through `reconcile_attempt`, the same path a real Stripe
    webhook takes, so the Deal is funded by the production service and the
    ledger holds the real `deal_funding` split. A fixture that inserted the rows
    by hand would test H3 against a world no service ever produces — and the
    traveler payable it discharges would not exist.
    """

    scenario = build_scenario(prefix=prefix)
    scenario.accept(reward_eur_cents=reward_eur_cents)
    method = set_preference(
        actor=scenario.traveler,
        currency="EUR",
        enabled=True,
        country="FR",
        expected_revision=0,
    )
    account = StripePayoutAccount.objects.create(
        traveler=scenario.traveler,
        platform_id=PLATFORM,
        provider_account_id=CONNECTED,
        provider_mode="test",
        declared_country="FR",
        verified_country="FR",
        creation_operation_key=f"{prefix}-account",
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
        created_by=scenario.traveler,
    )
    method.current_version, method.status = version, "ready"
    method.save(update_fields=["current_version", "status"])

    order = scenario.balance_order()
    outstanding = order.outstanding_eur_cents
    capture = PaymentAttempt.objects.create(
        order=order,
        provider="stripe",
        provider_mode="test",
        amount_eur_cents=outstanding,
        payment_currency="EUR",
        provider_amount_minor=outstanding,
        idempotency_key=f"{prefix}-source",
        provider_session_id=f"cs_{prefix}",
        provider_payment_id=f"pi_{prefix}",
        status=PaymentAttempt.Status.CHECKOUT_PENDING,
    )
    reconcile_attempt(
        attempt_id=capture.pk,
        outcome="succeeded",
        provider_payment_id=f"pi_{prefix}",
        provider_amount_minor=outstanding,
        provider_currency="EUR",
    )
    capture.refresh_from_db()
    payout = Payout.objects.get(deal_id=scenario.deal.pk)
    now = timezone.now()
    # A delivered Deal, with the handover timestamps the lifecycle constraints
    # require, and a protection window that has already closed. The gate itself
    # is untouched: it still reads `protection_ends_at` and still refuses while
    # that is in the future.
    Deal.objects.filter(pk=scenario.deal.pk).update(
        status=Deal.Status.PROTECTION_WINDOW,
        pickup_confirmed_at=now - timedelta(hours=96),
        delivery_code_available_at=now - timedelta(hours=95),
        delivery_code_released_at=now - timedelta(hours=95),
        delivery_confirmed_at=now - timedelta(hours=72),
        # I1A: the funded arrival basis is one of this Deal's stored deadlines,
        # so a fabricated past delivery has to bring it along. Left at the
        # future instant `build_scenario` created, this Deal would describe a
        # parcel delivered three days before its journey was due to arrive --
        # the very-early case the arrival floor exists to hold back, which is
        # not what any test below is about.
        funded_scheduled_arrival_floor_at=now - timedelta(hours=73),
        protection_ends_at=(
            now - timedelta(hours=24) if protection_expired else now + timedelta(hours=24)
        ),
    )
    Payout.objects.filter(pk=payout.pk).update(
        status="eligible",
        eligible_at=now - timedelta(hours=24),
        eligibility_basis="delivery_protection",
    )
    payout.refresh_from_db()
    assign_admin_roles(scenario.admin, ["finance"])
    return scenario, payout, account, capture
