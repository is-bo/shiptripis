"""H2.6 — what ShipTrip asserts about a Traveler when Stripe asks.

Stripe puts `business_profile.url` in `currently_due` for a French
`business_type=individual` account that only requested `transfers`, and its
hosted onboarding therefore asks the Traveler for a business website. A
Traveler carrying parcels has no website, so the question has no truthful
answer and the account holder is left guessing.

Stripe's documented alternative is `business_profile.product_description`,
which it describes as an internal-only description of the service the account
provides. Supplying it removes the website requirement. That is the whole of
this phase, and these tests pin the three things that make it safe:

* **One field, and only one.** `business_profile.url` is never sent, by anyone,
  for any reason. There is no parameter for it to arrive through.
* **The platform decides the words.** The description is a module constant in
  the finance domain, not something a request body can influence.
* **Nothing else moved.** Individual, transfers-only, no `card_payments`, same
  controller, same readiness evaluator, same idempotent creation identity.
"""

from __future__ import annotations

import dataclasses
import json

import pytest
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.finance import payout_accounts as accounts
from apps.finance.models import PayoutProviderOperation, StripePayoutAccount
from apps.finance.payout_accounts import (
    TRAVELER_PRODUCT_DESCRIPTION,
    ensure_account,
    evaluate_readiness,
)
from apps.finance.payout_profiles import set_preference
from apps.finance.providers.base import ProviderError
from apps.finance.providers.stripe_connect import (
    MAX_PRODUCT_DESCRIPTION_CHARS,
    PRODUCT_DESCRIPTION_PARAM,
    StripeConnectGateway,
)
from .factories import make_user
from .test_phase8fh2_accounts import (  # reuse H2's harness rather than fork it
    H2,
    FakeGateway,
    bind_version,
    make_account,
    method_of,
    ready_snapshot,
    snapshot,
)
from .test_phase8fh2_adapter import PLATFORM, FakeResponse, FakeSession, account_body

pytestmark = pytest.mark.django_db


@pytest.fixture
def h2():
    with override_settings(**H2):
        yield


@pytest.fixture
def traveler(db, h2):
    user = make_user("h26-traveler@example.com")
    set_preference(
        actor=user, currency="EUR", enabled=True, country="FR", expected_revision=0
    )
    return user


def gateway(*answers):
    return StripeConnectGateway(
        secret_key="sk_test_adapter",
        api_base="https://api.stripe.test",
        api_version="2026-03-25.dahlia",
        platform_account_id=PLATFORM,
        timeout_seconds=7,
        session=FakeSession(*answers),
    )


def create_call(**kwargs):
    """Run one `create_account` and return the form data actually posted."""

    client = gateway(FakeResponse(body=account_body()))
    client.create_account(
        country="fr",
        idempotency_key="acct_create:key",
        metadata={"shiptrip_method": "method-uuid"},
        **kwargs,
    )
    return client._session.calls[0]["data"]


# --------------------------------------------------------------------------
# The adapter's outbound contract
# --------------------------------------------------------------------------


class TestOutboundBusinessProfile:
    def test_the_product_description_is_sent_as_stripes_business_profile_field(self):
        data = create_call(product_description=TRAVELER_PRODUCT_DESCRIPTION)
        assert data[PRODUCT_DESCRIPTION_PARAM] == [TRAVELER_PRODUCT_DESCRIPTION]

    def test_no_business_website_is_ever_sent(self):
        """The field Stripe defines as the account holder's own website.

        ShipTrip has no truthful value for it — not a Traveler's site, which
        does not exist, and not ShipTrip's own, which is not theirs.
        """

        data = create_call(product_description=TRAVELER_PRODUCT_DESCRIPTION)
        assert "business_profile[url]" not in data
        assert not [key for key in data if key.endswith("[url]")]
        assert not [
            value
            for values in data.values()
            for value in values
            if "http://" in value or "https://" in value
        ]

    def test_no_merchant_category_is_asserted(self):
        """Stripe does not ask for an MCC here, so ShipTrip does not invent one."""

        data = create_call(product_description=TRAVELER_PRODUCT_DESCRIPTION)
        assert "business_profile[mcc]" not in data

    def test_the_only_business_profile_field_sent_is_the_description(self):
        data = create_call(product_description=TRAVELER_PRODUCT_DESCRIPTION)
        profile_keys = [key for key in data if key.startswith("business_profile")]
        assert profile_keys == [PRODUCT_DESCRIPTION_PARAM]

    def test_the_account_stays_an_individual(self):
        data = create_call(product_description=TRAVELER_PRODUCT_DESCRIPTION)
        assert data["business_type"] == ["individual"]

    def test_transfers_is_requested_and_card_payments_is_not(self):
        data = create_call(product_description=TRAVELER_PRODUCT_DESCRIPTION)
        assert data["capabilities[transfers][requested]"] == ["true"]
        assert not [key for key in data if "card_payments" in key]

    def test_the_controller_and_country_contract_is_untouched(self):
        data = create_call(product_description=TRAVELER_PRODUCT_DESCRIPTION)
        assert data["controller[stripe_dashboard][type]"] == ["express"]
        assert data["controller[requirement_collection]"] == ["stripe"]
        assert data["controller[fees][payer]"] == ["application"]
        assert data["controller[losses][payments]"] == ["application"]
        assert data["country"] == ["FR"]
        assert data["default_currency"] == ["eur"]

    def test_omitting_the_description_sends_no_business_profile_at_all(self):
        """An empty value is an absent field, never an empty assertion."""

        for value in ("", "   ", None):
            data = create_call(product_description=value)
            assert not [key for key in data if key.startswith("business_profile")]

    def test_a_description_that_is_not_text_is_refused(self):
        with pytest.raises(ProviderError):
            create_call(product_description={"business_profile[url]": "https://x.test"})

    def test_an_oversized_description_is_refused_rather_than_truncated(self):
        with pytest.raises(ProviderError):
            create_call(product_description="x" * (MAX_PRODUCT_DESCRIPTION_CHARS + 1))

    def test_whitespace_is_normalised_so_replays_stay_byte_identical(self):
        data = create_call(product_description="  Independent   traveler.\n")
        assert data[PRODUCT_DESCRIPTION_PARAM] == ["Independent traveler."]

    def test_the_adapter_exposes_no_way_to_set_a_website(self):
        source = accounts.get_connect_gateway.__module__
        import importlib

        text = importlib.import_module(source).__file__
        body = open(text, encoding="utf-8").read()
        assert "business_profile[url]" not in body


# --------------------------------------------------------------------------
# What the wording actually claims
# --------------------------------------------------------------------------


class TestTheDescriptionItself:
    def test_it_describes_a_traveler_and_not_a_merchant(self):
        text = TRAVELER_PRODUCT_DESCRIPTION.lower()
        assert "traveler" in text
        assert "parcel" in text
        assert "shiptrip" in text
        for forbidden in ("retailer", "e-commerce", "store", "shop", "card payment"):
            assert forbidden not in text

    def test_it_never_claims_the_traveler_owns_or_operates_shiptrip(self):
        text = TRAVELER_PRODUCT_DESCRIPTION.lower()
        assert "through the shiptrip marketplace" in text
        for forbidden in ("owner of shiptrip", "operates shiptrip", "shiptrip sarl"):
            assert forbidden not in text

    def test_it_contains_no_url(self):
        assert "http" not in TRAVELER_PRODUCT_DESCRIPTION.lower()
        assert ".com" not in TRAVELER_PRODUCT_DESCRIPTION.lower()

    def test_it_fits_inside_the_adapters_own_ceiling(self):
        assert len(TRAVELER_PRODUCT_DESCRIPTION) <= MAX_PRODUCT_DESCRIPTION_CHARS


# --------------------------------------------------------------------------
# The domain supplies it, and nothing else can
# --------------------------------------------------------------------------


class TestTheDomainOwnsTheWording:
    def test_account_creation_sends_the_platform_constant(self, traveler):
        fake = FakeGateway()
        ensure_account(actor=traveler, gateway=fake)
        created = [call for name, call in fake.calls if name == "create_account"]
        assert created
        assert created[0]["product_description"] == TRAVELER_PRODUCT_DESCRIPTION

    def test_a_client_cannot_supply_a_description(self, traveler, monkeypatch):
        """The onboarding endpoint accepts a country and nothing else."""

        fake = FakeGateway()
        monkeypatch.setattr(accounts, "get_connect_gateway", lambda **kw: fake)
        client = APIClient()
        client.force_authenticate(traveler)
        with override_settings(**H2):
            response = client.post(
                reverse("payout-stripe-onboarding"),
                {
                    "country": "FR",
                    "product_description": "ShipTrip Logistics SARL, online store",
                },
                format="json",
            )
        assert response.status_code == 400
        assert not [call for name, call in fake.calls if name == "create_account"]

    def test_a_client_cannot_supply_a_business_website(self, traveler, monkeypatch):
        fake = FakeGateway()
        monkeypatch.setattr(accounts, "get_connect_gateway", lambda **kw: fake)
        client = APIClient()
        client.force_authenticate(traveler)
        with override_settings(**H2):
            response = client.post(
                reverse("payout-stripe-onboarding"),
                {"country": "FR", "business_profile": {"url": "https://evil.test"}},
                format="json",
            )
        assert response.status_code == 400
        assert not [call for name, call in fake.calls if name == "create_account"]

    def test_the_creation_identity_records_what_is_actually_asserted(self, traveler):
        """A different sentence to Stripe is a different request, not a replay."""

        method = method_of(traveler)
        _, baseline, _, _ = accounts._creation_identity(method, "FR")
        original = accounts.TRAVELER_PRODUCT_DESCRIPTION
        try:
            accounts.TRAVELER_PRODUCT_DESCRIPTION = original + " Amended."
            _, amended, _, _ = accounts._creation_identity(method, "FR")
        finally:
            accounts.TRAVELER_PRODUCT_DESCRIPTION = original
        assert baseline != amended

    def test_creation_stays_idempotent_for_one_traveler(self, traveler):
        fake = FakeGateway()
        first = ensure_account(actor=traveler, gateway=fake)
        second = ensure_account(actor=traveler, gateway=fake)
        assert first.pk == second.pk
        assert StripePayoutAccount.objects.filter(traveler=traveler).count() == 1
        assert len([1 for name, _ in fake.calls if name == "create_account"]) == 1
        assert (
            PayoutProviderOperation.objects.filter(
                method=method_of(traveler), kind="account_create"
            ).count()
            == 1
        )

    def test_a_provider_rejection_leaves_no_account_and_stays_safe(self, traveler):
        from apps.finance.providers.base import ProviderCheckoutRejected

        fake = FakeGateway(
            create=ProviderCheckoutRejected(
                "business_profile[product_description] is invalid",
                provider_code="parameter_invalid_string_empty",
            )
        )
        with pytest.raises(ProviderCheckoutRejected):
            ensure_account(actor=traveler, gateway=fake)
        assert not StripePayoutAccount.objects.filter(traveler=traveler).exists()
        operation = PayoutProviderOperation.objects.get(
            method=method_of(traveler), kind="account_create"
        )
        assert operation.status == "failed"
        assert not operation.provider_object_id


# --------------------------------------------------------------------------
# Nothing downstream changed
# --------------------------------------------------------------------------


class TestNoRegression:
    def test_readiness_still_requires_every_authoritative_gate(self, traveler):
        """Prefilling a business profile is not evidence that money can move."""

        account = make_account(traveler)
        bind_version(traveler, account)
        assert evaluate_readiness(account, holds_exist=False).ready is True

        for field, value, reason in (
            ("transfers_status", "inactive", "transfers_inactive"),
            ("payouts_enabled", False, "payouts_not_enabled"),
            ("eur_bank_present", False, "eur_bank_required"),
            ("payout_schedule_interval", "daily", "payout_schedule_unexpected"),
            ("details_submitted", False, "details_incomplete"),
        ):
            original = getattr(account, field)
            setattr(account, field, value)
            verdict = evaluate_readiness(account, holds_exist=False)
            setattr(account, field, original)
            assert verdict.ready is False
            assert verdict.reason == reason

    def test_an_outstanding_requirement_still_blocks_readiness(self, traveler):
        account = make_account(traveler, requirement_codes=["business_profile.url"])
        bind_version(traveler, account)
        verdict = evaluate_readiness(account, holds_exist=False)
        assert verdict.ready is False
        assert verdict.reason == "requirements_due"

    def test_no_business_profile_payload_is_persisted_on_the_account(self, traveler):
        fake = FakeGateway()
        account = ensure_account(actor=traveler, gateway=fake)
        stored = json.dumps(
            {
                name: str(getattr(account, name))
                for name in (
                    "provider_account_id",
                    "declared_country",
                    "verified_country",
                    "controller_summary",
                    "requirement_codes",
                    "disabled_reason",
                )
            }
        )
        assert "product_description" not in stored
        assert TRAVELER_PRODUCT_DESCRIPTION not in stored
        assert not hasattr(account, "business_profile")

    def test_the_snapshot_projection_still_carries_no_business_profile(self):
        client = gateway(
            FakeResponse(
                body=account_body(
                    business_profile={
                        "url": "https://someone.test",
                        "product_description": TRAVELER_PRODUCT_DESCRIPTION,
                        "name": "Jean Dupont",
                    }
                )
            )
        )
        projection = json.dumps(
            dataclasses.asdict(client.retrieve_account("acct_1TESTconnected"))
        )
        assert "someone.test" not in projection
        assert "Jean Dupont" not in projection
        assert "product_description" not in projection

    def test_algeria_remains_unsupported_for_stripe_eur_payouts(self, db, h2):
        from apps.finance.payout_accounts import CountryUnsupported

        user = make_user("h26-dz@example.com")
        with pytest.raises(CountryUnsupported):
            set_preference(
                actor=user,
                currency="EUR",
                enabled=True,
                country="DZ",
                expected_revision=0,
            )

    def test_the_adapter_still_sends_no_business_profile_url(self):
        """H2.6's own guarantee, unchanged by H3's execution surface.

        The blanket "this module moves no money" assertion belonged to H2 and is
        gone: H3 added the four provider calls H0 selected. What H2.6 asserted
        survives literally — a Traveler has no website, so there is no way for
        this adapter to claim they do, and the unselected top-up path stays
        absent.
        """

        import apps.finance.providers.stripe_connect as module

        body = open(module.__file__, encoding="utf-8").read()
        for path in ("business_profile[url]", "/v1/topups"):
            assert path not in body


# --------------------------------------------------------------------------
# Existing accounts
# --------------------------------------------------------------------------


class TestExistingAccountsAreLeftAlone:
    def test_an_already_bound_account_is_never_recreated_or_rewritten(self, traveler):
        """Traveler 14's shape: an account already exists and already onboarded.

        Stripe stops accepting business-profile writes for a
        `requirement_collection=stripe` account once its first Account Link
        exists, so there is nothing to backfill and this phase must not try.
        """

        account = make_account(traveler)
        bind_version(traveler, account)
        fake = FakeGateway(create=ready_snapshot())
        reused = ensure_account(actor=traveler, gateway=fake)
        assert reused.pk == account.pk
        assert [name for name, _ in fake.calls] == ["platform_identity"]
        assert StripePayoutAccount.objects.filter(traveler=traveler).count() == 1

    def test_starting_onboarding_for_a_bound_account_only_mints_a_link(
        self, traveler, monkeypatch
    ):
        account = make_account(traveler, status="setup_required")
        bind_version(traveler, account)
        fake = FakeGateway(create=snapshot())
        monkeypatch.setattr(accounts, "get_connect_gateway", lambda **kw: fake)
        with override_settings(**H2):
            accounts.start_onboarding(actor=traveler, gateway=fake)
        names = [name for name, _ in fake.calls]
        assert "create_account" not in names
        assert "create_account_link" in names
