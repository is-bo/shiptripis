"""Phase 8F-C: the rail decides its settlement currency, and so does nobody else.

Three device-QA findings meet in this file.

**Stripe appeared to offer a dinar payment.** It never could: `_resolve_amounts`
reads `gateway.payment_currency` and the checkout contract refuses a request
that so much as names a currency. What it *did* do was serve a rail list with
no per-rail amount in it, so one euro figure sat under two rows and the second
row said "charged in dinars". The repair is that every rail publishes the amount
it would take, in the currency it settles in, computed by the server.

**Chargily failed with a generic error.** Its key said `test_sk_` and its API
base pointed at live. Chargily answered 401, the adapter raised the catch-all
`ProviderError`, and the payer got "not your fault, try again" for a
configuration fault no retry could fix.

**Chargily was enabled while its environment was unidentifiable.** A rail whose
credentials and API base disagree must not open a checkout at all, and must not
be reported as ready.

The financial locking from Phase 8D-F is untouched here; nothing in this file
takes a lock or moves money.
"""

from __future__ import annotations

from dataclasses import replace
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from copy import deepcopy

from apps.core.business_settings import get_active_business_settings
from apps.core.models import BusinessSettingsVersion
from apps.finance.money import convert_eur_cents
from apps.finance.policy import phase3_policy
from apps.finance.providers import (
    MODE_TEST,
    MODE_UNKNOWN,
    ProviderConfigurationInvalid,
    ProviderNotConfigured,
    availability,
    resolve_gateway_for_checkout,
)
from apps.finance.providers.chargily import (
    LIVE_API_BASE,
    TEST_API_BASE,
    ChargilyGateway,
)
from apps.finance.providers.stripe import StripeGateway
from apps.finance.services import provider_options, settlement_amounts

from .factories import build_scenario

STRIPE_TEST = {
    "STRIPE_SECRET_KEY": "sk_test_phase8fc",
    "STRIPE_WEBHOOK_SECRET": "whsec_phase8fc",
}
CHARGILY_TEST = {
    "CHARGILY_SECRET_KEY": "test_sk_phase8fc",
    "CHARGILY_API_BASE": TEST_API_BASE,
}
#: The exact shape that was deployed: a test key against the live API base.
CHARGILY_MISMATCHED = {
    "CHARGILY_SECRET_KEY": "test_sk_phase8fc",
    "CHARGILY_API_BASE": LIVE_API_BASE,
}


def enable_in_active_settings(**provider_flags) -> None:
    """Turn a rail on in the *stored* policy the API itself reads.

    `_policy` builds a detached policy object for direct service calls; a view
    reads `phase3_policy()` from the active settings version, so an API test has
    to change the stored one.
    """

    version = get_active_business_settings()
    policy = deepcopy(version.policy)
    policy["payments"]["providers"].update(provider_flags)
    BusinessSettingsVersion.objects.filter(pk=version.pk).update(policy=policy)


def _policy(*, new_checkouts: bool = True, **provider_flags):
    """The active seeded policy with only the provider switches changed.

    `new_checkouts` is explicit because Chargily has two switches that mean
    different things: `providers.chargily_enabled` removes the rail from the
    payer's list, while `chargily.new_checkouts_enabled` stops *new* checkouts
    during an incident and leaves webhooks and refunds working.
    """

    policy = phase3_policy()
    return replace(
        policy,
        providers=replace(policy.providers, **provider_flags),
        chargily=replace(policy.chargily, new_checkouts_enabled=new_checkouts),
    )


class SettlementCurrencyIsTheRailsTests(TestCase):
    """Stripe settles EUR, Chargily settles DZD, and neither is negotiable."""

    def test_each_rail_publishes_its_own_settlement_currency(self):
        assert StripeGateway().payment_currency == "EUR"
        assert ChargilyGateway().payment_currency == "DZD"

    def test_stripe_refuses_a_dinar_charge_outright(self):
        gateway = StripeGateway(**{
            "secret_key": STRIPE_TEST["STRIPE_SECRET_KEY"],
            "webhook_secret": STRIPE_TEST["STRIPE_WEBHOOK_SECRET"],
        })
        from apps.finance.providers import CheckoutRequest

        request = CheckoutRequest(
            reference="r",
            amount_minor=5_625,
            currency="DZD",
            amount_exponent=0,
            idempotency_key="k",
            success_url="https://x.invalid/s",
            failure_url="https://x.invalid/f",
            webhook_url="https://x.invalid/w",
            description="d",
        )
        with self.assertRaises(Exception) as caught:
            gateway.create_checkout(request)
        assert caught.exception.provider_code == "unsupported_currency"

    def test_chargily_refuses_a_euro_charge_outright(self):
        from apps.finance.providers import CheckoutRequest

        request = CheckoutRequest(
            reference="r",
            amount_minor=3_750,
            currency="EUR",
            amount_exponent=2,
            idempotency_key="k",
            success_url="https://x.invalid/s",
            failure_url="https://x.invalid/f",
            webhook_url="https://x.invalid/w",
            description="d",
        )
        with self.assertRaises(Exception) as caught:
            ChargilyGateway(secret_key="test_sk_x").create_checkout(request)
        assert caught.exception.provider_code == "unsupported_currency"

    def test_settlement_amounts_takes_a_currency_only_from_a_rail(self):
        policy = phase3_policy()

        euro = settlement_amounts(
            payment_currency="EUR", amount_eur_cents=3_750, policy=policy
        )
        dinar = settlement_amounts(
            payment_currency="DZD", amount_eur_cents=3_750, policy=policy
        )

        # The canonical obligation is the same number in both; only the
        # settlement representation differs.
        assert euro["amount_eur_cents"] == dinar["amount_eur_cents"] == 3_750
        assert euro["payment_currency"] == "EUR"
        assert euro["fx_rate_micros"] is None
        assert dinar["payment_currency"] == "DZD"
        assert dinar["provider_amount_minor"] == convert_eur_cents(
            3_750,
            to_currency="DZD",
            rate_micros=policy.chargily.eur_dzd_rate_micros,
        )
        assert dinar["fx_rate_micros"] == policy.chargily.eur_dzd_rate_micros


@override_settings(**STRIPE_TEST, **CHARGILY_TEST)
class ProviderOptionsCarryAmountsTests(TestCase):
    """Each rail row says what that rail charges — the whole UI repair."""

    def test_a_rail_row_carries_its_own_amount_and_currency(self):
        policy = _policy(stripe_enabled=True, chargily_enabled=True)

        rows = {
            row["provider"]: row
            for row in provider_options(policy, amount_eur_cents=3_750)
        }

        stripe = rows["stripe"]
        assert stripe["settlement_currency"] == "EUR"
        assert stripe["settlement_amount_minor"] == 3_750
        assert stripe["settlement_amount_exponent"] == 2
        assert stripe["canonical_amount_eur_cents"] == 3_750
        # A euro rail has no rate and needs none.
        assert "eur_dzd_rate" not in stripe

        chargily = rows["chargily"]
        assert chargily["settlement_currency"] == "DZD"
        assert chargily["settlement_amount_exponent"] == 0
        assert chargily["canonical_amount_eur_cents"] == 3_750
        assert chargily["settlement_amount_minor"] == convert_eur_cents(
            3_750,
            to_currency="DZD",
            rate_micros=policy.chargily.eur_dzd_rate_micros,
        )
        assert chargily["eur_dzd_rate"]
        # Today's rate, not a binding one: the attempt freezes its own.
        assert chargily["rate_is_indicative"] is True

    def test_no_row_offers_a_currency_the_rail_does_not_settle_in(self):
        policy = _policy(stripe_enabled=True, chargily_enabled=True)

        for row in provider_options(policy, amount_eur_cents=3_750):
            with self.subTest(provider=row["provider"]):
                expected = {"stripe": "EUR", "chargily": "DZD", "mock": "EUR"}[
                    row["provider"]
                ]
                assert row["settlement_currency"] == expected
                # There is no list of currencies anywhere in the contract for a
                # client to render as a chooser.
                assert "currencies" not in row
                assert "settlement_currencies" not in row

    def test_the_rail_list_without_an_amount_still_names_the_currency(self):
        policy = _policy(stripe_enabled=True, chargily_enabled=True)

        rows = {row["provider"]: row for row in provider_options(policy)}

        assert rows["stripe"]["payment_currency"] == "EUR"
        assert "settlement_amount_minor" not in rows["stripe"]

    def test_a_dinar_total_under_the_provider_floor_is_unavailable_not_broken(self):
        # An *otherwise usable* rail that cannot take this particular amount.
        # The floor is the only thing wrong with it, so the floor is what it
        # reports; a rail that is also switched off says that instead.
        policy = _policy(stripe_enabled=True, chargily_enabled=True)
        policy = replace(
            policy, chargily=replace(policy.chargily, min_amount_dzd=10_000_000)
        )

        rows = {
            row["provider"]: row
            for row in provider_options(policy, amount_eur_cents=100)
        }

        assert rows["chargily"]["available"] is False
        assert rows["chargily"]["unavailable_reason"] == "amount_below_provider_minimum"
        # The euro rail is untouched by a dinar floor.
        assert rows["stripe"]["available"] is True


class ChargilyEnvironmentContractTests(TestCase):
    """A key and an API base that disagree are a stop condition, not a guess."""

    def test_the_deployed_mismatch_is_reported_as_unidentified(self):
        gateway = ChargilyGateway(
            secret_key="test_sk_deployed", api_base=LIVE_API_BASE
        )

        assert gateway.credential_mode() == MODE_UNKNOWN
        assert gateway.configuration_problem() == "chargily_environment_unidentified"

    def test_a_live_key_against_the_test_base_is_equally_refused(self):
        gateway = ChargilyGateway(
            secret_key="live_sk_deployed", api_base=TEST_API_BASE
        )

        assert gateway.credential_mode() == MODE_UNKNOWN
        assert gateway.configuration_problem() == "chargily_environment_unidentified"

    def test_agreeing_halves_are_accepted(self):
        for key, base, mode in (
            ("test_sk_x", TEST_API_BASE, "test"),
            ("live_sk_x", LIVE_API_BASE, "live"),
        ):
            with self.subTest(mode=mode):
                gateway = ChargilyGateway(secret_key=key, api_base=base)
                assert gateway.credential_mode() == mode
                assert gateway.configuration_problem() == ""

    def test_an_unrecognised_key_prefix_is_never_guessed_into_test(self):
        gateway = ChargilyGateway(secret_key="sk_mystery", api_base=TEST_API_BASE)

        assert gateway.credential_mode() == MODE_UNKNOWN
        assert gateway.configuration_problem() == "chargily_environment_unidentified"

    def test_an_unconfigured_rail_reports_no_configuration_problem(self):
        # "No key" is a different, earlier answer than "a key we cannot place".
        assert ChargilyGateway(secret_key="").configuration_problem() == ""


@override_settings(**CHARGILY_MISMATCHED, **STRIPE_TEST)
class MisconfiguredRailCannotTransactTests(TestCase):
    """The owner enabled Chargily while its environment was unknown."""

    def test_it_is_not_reported_as_available(self):
        policy = _policy(chargily_enabled=True, stripe_enabled=True)

        row = availability(policy, "chargily")

        assert row.enabled is True
        assert row.configured is True
        assert row.configuration_valid is False
        assert row.available is False
        assert row.unavailable_reason == "provider_configuration_invalid"

    def test_the_operator_view_separates_enabled_from_usable(self):
        policy = _policy(chargily_enabled=True)

        row = availability(policy, "chargily").as_operator_dict()

        assert row["enabled"] is True
        assert row["configured"] is True
        assert row["configuration_valid"] is False
        assert row["configuration_problem"] == "chargily_environment_unidentified"
        assert row["credential_mode"] == MODE_UNKNOWN

    def test_new_checkout_creation_is_refused_before_any_provider_call(self):
        policy = _policy(chargily_enabled=True)

        with self.assertRaises(ProviderConfigurationInvalid) as caught:
            resolve_gateway_for_checkout(policy, "chargily")

        assert caught.exception.code == "provider_configuration_invalid"
        assert caught.exception.provider_code == "chargily_environment_unidentified"

    def test_repairing_the_api_base_alone_makes_the_rail_usable(self):
        # The whole Phase 8F-C Chargily repair, in one assertion: the key was
        # never wrong, only the base URL it was being presented to.
        policy = _policy(chargily_enabled=True)

        with override_settings(CHARGILY_API_BASE=TEST_API_BASE):
            row = availability(policy, "chargily")
            gateway = resolve_gateway_for_checkout(policy, "chargily")

        assert row.available is True
        assert row.credential_mode == MODE_TEST
        assert gateway.payment_currency == "DZD"

    def test_webhooks_and_refunds_still_reach_a_misconfigured_rail(self):
        # Refusing new checkouts must not strand money already in flight.
        from apps.finance.providers import get_gateway

        gateway = get_gateway("chargily")

        assert gateway.configuration_problem()
        assert gateway.webhook_secret  # still able to verify an inbound event


class ProviderAuthFailuresAreNotGenericTests(TestCase):
    """The 401 the deployed mismatch produced must not read as 'try again'."""

    class _Response:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

    def test_chargily_401_is_a_configuration_answer_not_a_transient_one(self):
        session = mock.Mock()
        session.request.return_value = self._Response(401, {"message": "Unauthorized"})
        gateway = ChargilyGateway(
            secret_key="test_sk_x", api_base=LIVE_API_BASE, session=session
        )

        with self.assertRaises(ProviderNotConfigured) as caught:
            gateway._request("GET", "/checkouts/abc")

        assert caught.exception.code == "provider_not_configured"

    def test_a_definite_chargily_rejection_says_the_checkout_failed(self):
        from apps.finance.providers import ProviderCheckoutRejected

        session = mock.Mock()
        session.request.return_value = self._Response(
            422, {"message": "amount too small", "code": "amount_invalid"}
        )
        gateway = ChargilyGateway(
            secret_key="test_sk_x", api_base=TEST_API_BASE, session=session
        )

        with self.assertRaises(ProviderCheckoutRejected) as caught:
            gateway._request("POST", "/checkouts", payload={})

        assert caught.exception.code == "provider_checkout_failed"
        assert caught.exception.provider_code == "amount_invalid"

    def test_stripe_401_is_a_configuration_answer_too(self):
        session = mock.Mock()
        session.request.return_value = self._Response(
            401, {"error": {"message": "Invalid API Key"}}
        )
        gateway = StripeGateway(
            secret_key="sk_test_x", webhook_secret="whsec_x", session=session
        )

        with self.assertRaises(ProviderNotConfigured) as caught:
            gateway._request("GET", "/v1/checkout/sessions/cs_x")

        assert caught.exception.code == "provider_not_configured"

    def test_no_provider_secret_appears_in_a_raised_message(self):
        session = mock.Mock()
        session.request.return_value = self._Response(401, {"message": "no"})
        secret = "test_sk_supersecretvalue"
        gateway = ChargilyGateway(
            secret_key=secret, api_base=LIVE_API_BASE, session=session
        )

        with self.assertRaises(ProviderNotConfigured) as caught:
            gateway._request("GET", "/checkouts/abc")

        assert secret not in str(caught.exception)
        assert secret not in repr(caught.exception)


@override_settings(**STRIPE_TEST, **CHARGILY_TEST)
class CheckoutContractRefusesAClientCurrencyTests(TestCase):
    """A stale or hostile client cannot request Stripe-in-dinars."""

    def setUp(self):
        self.scenario = build_scenario(prefix="p8fc-currency")
        self.scenario.accept()
        enable_in_active_settings(stripe_enabled=True)
        self.order = self.scenario.balance_order()
        self.client = APIClient()
        self.client.force_authenticate(self.scenario.sender)
        self.url = reverse(
            "finance-order-checkout", args=(self.order.public_reference,)
        )

    def test_a_supplied_currency_is_rejected_rather_than_ignored(self):
        for field in ("currency", "payment_currency", "amount_eur_cents", "fx_rate"):
            with self.subTest(field=field):
                response = self.client.post(
                    self.url, {"provider": "stripe", field: "DZD"}, format="json"
                )
                assert response.status_code == 400
                # DRF wraps a `validate()` ValidationError dict's values in
                # lists; the code is what matters, not the shape it arrives in.
                body = response.json()
                assert "client_supplied_amount_rejected" in str(body["code"])

    def test_the_attempt_records_the_rails_currency_not_a_requested_one(self):
        with mock.patch(
            "apps.finance.providers.stripe.StripeGateway.create_checkout"
        ) as create:
            from apps.finance.providers import CheckoutResult

            create.return_value = CheckoutResult(
                provider_session_id="cs_test_x",
                checkout_url="https://checkout.stripe.invalid/cs_test_x",
            )
            response = self.client.post(
                self.url, {"provider": "stripe"}, format="json"
            )

        assert response.status_code in (200, 201), response.json()
        body = response.json()
        assert body["payment_currency"] == "EUR"
        # And the provider was asked for euros, in the amount the server owns.
        charged = create.call_args.args[0]
        assert charged.currency == "EUR"
        assert charged.amount_minor == self.order.outstanding_eur_cents


@override_settings(**STRIPE_TEST, **CHARGILY_TEST)
class FrozenFxSnapshotTests(TestCase):
    """Changing the admin rate must not move an attempt that already exists."""

    def setUp(self):
        self.scenario = build_scenario(prefix="p8fc-fx")
        self.scenario.accept()
        self.order = self.scenario.balance_order()

    def _open_chargily_attempt(self, policy):
        from apps.finance.providers import CheckoutResult
        from apps.finance.services import start_checkout

        with mock.patch(
            "apps.finance.providers.chargily.ChargilyGateway.create_checkout"
        ) as create:
            create.return_value = CheckoutResult(
                provider_session_id="chk_test_x",
                checkout_url="https://pay.chargily.invalid/chk_test_x",
            )
            session = start_checkout(
                order_id=self.order.pk,
                provider="chargily",
                actor_id=self.scenario.sender.pk,
                policy=policy,
            )
        return session.attempt, create.call_args.args[0]

    def test_the_attempt_freezes_the_rate_and_the_dinar_amount(self):
        policy = _policy(chargily_enabled=True)
        attempt, charged = self._open_chargily_attempt(policy)

        assert attempt.payment_currency == "DZD"
        assert attempt.fx_rate_micros == policy.chargily.eur_dzd_rate_micros
        assert attempt.fx_snapshot_at is not None
        assert attempt.amount_eur_cents == self.order.outstanding_eur_cents
        assert attempt.provider_amount_minor == convert_eur_cents(
            self.order.outstanding_eur_cents,
            to_currency="DZD",
            rate_micros=policy.chargily.eur_dzd_rate_micros,
        )
        # Chargily was told an amount, never a rate.
        assert charged.currency == "DZD"
        assert charged.amount_minor == attempt.provider_amount_minor

    def test_a_later_rate_change_does_not_move_the_existing_attempt(self):
        policy = _policy(chargily_enabled=True)
        attempt, _ = self._open_chargily_attempt(policy)
        original_rate = attempt.fx_rate_micros
        original_amount = attempt.provider_amount_minor

        doubled = replace(
            policy, chargily=replace(policy.chargily, eur_dzd_rate_micros=original_rate * 2)
        )
        # The preview a *new* screen would show moves...
        preview = {
            row["provider"]: row
            for row in provider_options(
                doubled, amount_eur_cents=self.order.outstanding_eur_cents
            )
        }["chargily"]
        assert preview["fx_rate_micros"] == original_rate * 2

        # ...and the attempt already created does not.
        attempt.refresh_from_db()
        assert attempt.fx_rate_micros == original_rate
        assert attempt.provider_amount_minor == original_amount
        assert attempt.amount_eur_cents == self.order.outstanding_eur_cents


@override_settings(**STRIPE_TEST, **CHARGILY_MISMATCHED)
class GuestPayerRailsTests(TestCase):
    """Guest payment keeps Stripe and never gains Chargily by accident."""

    def test_chargily_declares_it_cannot_take_a_third_party_payment(self):
        assert ChargilyGateway().supports_guest_payment is False
        assert StripeGateway().supports_guest_payment is True

    def test_the_guest_rail_list_offers_only_stripe(self):
        policy = _policy(stripe_enabled=True, chargily_enabled=True)

        rows = [
            row
            for row in provider_options(
                policy, amount_eur_cents=3_750, guest_only=True
            )
            # The mock rail is a local fixture; production refuses to boot with
            # it and it is never a real guest option.
            if row["provider"] != "mock"
        ]

        assert [row["provider"] for row in rows] == ["stripe"]
        assert rows[0]["settlement_currency"] == "EUR"
        assert rows[0]["settlement_amount_minor"] == 3_750

    def test_a_guest_checkout_on_chargily_is_refused(self):
        policy = _policy(stripe_enabled=True, chargily_enabled=True)

        with override_settings(CHARGILY_API_BASE=TEST_API_BASE):
            with self.assertRaises(Exception) as caught:
                resolve_gateway_for_checkout(policy, "chargily", guest=True)

        assert caught.exception.code == "provider_disabled"
