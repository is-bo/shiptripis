"""F1b: Finance retires a Stripe payout account opened for the wrong country.

A connected account never changes country, and a Traveler has one active
account per platform and mode, so an account opened for FR blocks a Traveler
who now wants DE (`stripe_account_country_mismatch`). Finance retires it
(`payout_accounts.retire_account`): it stops being the standing account, the
creation that produced it is passed over, and the next onboarding opens a new
account for the country now declared. Funded payout instructions are not
touched, and a payout in progress to the account refuses the retirement.
"""

from __future__ import annotations

import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, connections, transaction
from django.forms.models import model_to_dict
from django.test import TransactionTestCase, override_settings
from django.urls import reverse

from apps.admin_panel.models import AdminAuditLog
from apps.admin_panel.permissions import assign_admin_roles
from apps.admin_panel.tests.two_step_helpers import staff_login
from apps.finance import payout_accounts
from apps.finance.models import (
    Payout,
    PayoutMethodVersion,
    PayoutProviderOperation,
    TravelerPayoutMethod,
)
from apps.finance.payout_accounts import (
    AccountCountryMismatch,
    ensure_account,
    retire_account,
)
from apps.finance.payout_execution import (
    PayoutBlocked,
    _assert_dispatchable,
    _lock_payout_aggregate,
)
from apps.finance.payout_mobile import payout_summary
from apps.finance.payout_profiles import set_preference

from .factories import make_user
from .payout_execution_harness import H3_SETTINGS, build_stripe_payout
from .test_f1_setup_freeze import in_own_connection, pausing, wait_for_a_lock_wait
from .test_phase8fh2_accounts import H2, FakeGateway, snapshot
from .test_phase8fh3_concurrency import _seed_admin_roles, _seed_settings

TWO_COUNTRIES = {**H2, "STRIPE_CONNECT_ALLOWED_COUNTRIES": ["FR", "DE"]}


def finance_staff(name="finance"):
    staff = make_user(f"{name}@f1b.test", is_staff=True)
    assign_admin_roles(staff, [name])
    return staff


def eur_actions(user):
    return payout_summary(user)["eur"]["available_actions"]


@pytest.fixture
def two_countries(db):
    with override_settings(**TWO_COUNTRIES):
        yield


@pytest.fixture
def stuck(two_countries):
    """A traveler whose only account was opened for FR, who now declares DE."""

    user = make_user("f1b-traveler@example.com", is_email_verified=True)
    set_preference(actor=user, currency="EUR", enabled=True, country="FR", expected_revision=0)
    fr = ensure_account(
        actor=user, gateway=FakeGateway(create=snapshot(account_id="acct_1TESTfr", country="FR"))
    )
    method = TravelerPayoutMethod.objects.get(traveler=user, currency="EUR")
    set_preference(
        actor=user, currency="EUR", enabled=True, country="DE", expected_revision=method.revision
    )
    return user, fr


def test_retiring_the_account_lets_the_next_onboarding_open_one_for_the_declared_country(stuck):
    user, fr = stuck
    with pytest.raises(AccountCountryMismatch):
        ensure_account(actor=user, gateway=FakeGateway())
    assert "configure_eur" not in eur_actions(user)
    staff = finance_staff()
    fr.refresh_from_db()
    was = {"active": True, "status": fr.status, "status_reason": fr.status_reason, "country": "FR"}

    retire_account(actor=staff, account_id=fr.pk, reason="Opened for FR; traveler lives in DE.")

    fr.refresh_from_db()
    assert (fr.active, fr.status, fr.status_reason) == (False, "unavailable", "account_replaced")
    assert not payout_accounts.standing_accounts(user.pk).exists()
    method = TravelerPayoutMethod.objects.get(traveler=user, currency="EUR")
    assert payout_accounts.current_creation(method) is None
    assert eur_actions(user) == ["configure_eur"]
    row = AdminAuditLog.objects.get(action="payout_account.retired")
    assert (row.actor_id, row.target_id) == (staff.pk, str(fr.pk))
    assert row.reason == "Opened for FR; traveler lives in DE."
    assert row.before == was
    assert row.after == {"active": False, "status": "unavailable",
                         "status_reason": "account_replaced"}

    gateway = FakeGateway(create=snapshot(account_id="acct_1TESTde", country="DE"))
    de = ensure_account(actor=user, gateway=gateway)

    assert (de.provider_account_id, de.declared_country, de.active) == ("acct_1TESTde", "DE", True)
    assert gateway.calls.count(("create_account", gateway.calls[1][1])) == 1
    assert gateway.calls[1][1]["country"] == "DE"
    method.refresh_from_db()
    assert (method.current_version.country, method.current_version.stripe_account_id) == ("DE", de.pk)
    assert de.creation_operation_key.endswith(":v2")
    assert PayoutProviderOperation.objects.filter(method=method, kind="account_create").count() == 2


@pytest.mark.parametrize("role", ["ops", "support", "trust_verification"])
def test_retiring_needs_the_finance_permission(stuck, role):
    _, fr = stuck
    with pytest.raises(PermissionDenied):
        retire_account(actor=finance_staff(role), account_id=fr.pk, reason="Wrong country.")
    fr.refresh_from_db()
    assert fr.active
    assert not AdminAuditLog.objects.filter(action="payout_account.retired").exists()


@pytest.mark.parametrize("reason", ["", "   ", None])
def test_retiring_needs_a_reason(stuck, reason):
    _, fr = stuck
    with pytest.raises(ValidationError) as refused:
        retire_account(actor=finance_staff(), account_id=fr.pk, reason=reason)
    assert refused.value.code == "reason_required"
    fr.refresh_from_db()
    assert fr.active
    assert not AdminAuditLog.objects.filter(action="payout_account.retired").exists()


def test_retiring_twice_reports_it_is_already_retired_and_writes_nothing(stuck):
    _, fr = stuck
    staff = finance_staff()
    retire_account(actor=staff, account_id=fr.pk, reason="Wrong country.")
    audit_rows = AdminAuditLog.objects.count()
    fr.refresh_from_db()
    before = model_to_dict(fr)

    with pytest.raises(ValidationError) as refused:
        retire_account(actor=staff, account_id=fr.pk, reason="Again.")

    assert refused.value.code == "already_retired"
    assert "already retired" in refused.value.messages[0]
    assert AdminAuditLog.objects.count() == audit_rows
    fr.refresh_from_db()
    assert model_to_dict(fr) == before


@pytest.fixture
def funded(db):
    with override_settings(**H3_SETTINGS):
        yield build_stripe_payout(prefix="f1b")


@pytest.mark.parametrize("status", ["processing", "sent", "failed"])
def test_retiring_is_refused_while_a_payout_to_the_account_is_in_progress(funded, status):
    scenario, payout, account, _ = funded
    Payout.objects.filter(pk=payout.pk).update(status=status)

    with pytest.raises(ValidationError) as refused:
        retire_account(actor=scenario.admin, account_id=account.pk, reason="Wrong country.")

    assert refused.value.code == "payout_in_progress"
    account.refresh_from_db()
    assert account.active
    assert not AdminAuditLog.objects.filter(action="payout_account.retired").exists()


def test_funded_payout_instructions_are_unchanged_and_no_longer_dispatch(funded):
    scenario, payout, account, _ = funded
    versions = lambda: [model_to_dict(v) for v in PayoutMethodVersion.objects.order_by("pk")]  # noqa: E731
    payout_rows = lambda: [model_to_dict(p) for p in Payout.objects.order_by("pk")]  # noqa: E731
    before_versions, before_payouts = versions(), payout_rows()

    retire_account(actor=scenario.admin, account_id=account.pk, reason="Wrong country.")

    assert versions() == before_versions
    assert payout_rows() == before_payouts
    with transaction.atomic():
        locked, _, _ = _lock_payout_aggregate(payout.pk)
        with pytest.raises(PayoutBlocked) as blocked:
            _assert_dispatchable(locked)
    assert blocked.value.code == "account_missing"


@pytest.fixture
def client(client):
    with override_settings(STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }):
        yield client


class TestConsoleForm:
    def url(self, account):
        return reverse("admin_console:payout-account-retire", args=(account.pk,))

    def test_finance_retires_with_a_reason_from_the_travelers_payout_page(self, stuck, client):
        user, fr = stuck
        staff = finance_staff()
        staff_login(client, staff)
        page = client.get(reverse("admin_console:user-detail", args=(user.pk,)) + "?tab=payouts")
        assert self.url(fr) in page.content.decode()
        assert client.get(self.url(fr)).status_code == 200

        response = client.post(self.url(fr), {"reason": "Opened for FR by mistake."})

        assert response.status_code == 302
        fr.refresh_from_db()
        assert not fr.active
        assert AdminAuditLog.objects.get(action="payout_account.retired").reason == (
            "Opened for FR by mistake."
        )

    def test_the_form_refuses_an_empty_reason(self, stuck, client):
        _, fr = stuck
        staff_login(client, finance_staff())
        response = client.post(self.url(fr), {"reason": ""})
        assert response.status_code == 200
        fr.refresh_from_db()
        assert fr.active

    def test_staff_without_the_permission_get_no_form(self, stuck, client):
        user, fr = stuck
        staff_login(client, finance_staff("ops"))
        assert client.get(self.url(fr)).status_code == 403
        assert client.post(self.url(fr), {"reason": "x"}).status_code == 403
        fr.refresh_from_db()
        assert fr.active


@unittest.skipUnless(connection.vendor == "postgresql", "Row locks and snapshots are PostgreSQL's.")
@override_settings(**H3_SETTINGS)
class RetireRacesDispatchTests(TransactionTestCase):
    """Execution reads the destination again once it holds the Payout lock."""

    def setUp(self):
        publisher = patch("apps.core.redis_bus.publish_after_commit")
        publisher.start()
        self.addCleanup(publisher.stop)
        _seed_settings()
        _seed_admin_roles()
        self.scenario, self.payout, self.account, _ = build_stripe_payout(prefix="f1brace")

    def test_a_dispatch_waiting_on_the_payout_lock_sees_the_account_retired(self):
        paused, release = Event(), Event()
        real = payout_accounts.record_admin_action

        def retire():
            retire_account(actor=self.scenario.admin, account_id=self.account.pk, reason="Race.")

        def dispatch_reads_destination():
            with transaction.atomic():
                payout, _, _ = _lock_payout_aggregate(self.payout.pk)
                return payout.active_instruction_version.stripe_account.active

        with patch.object(payout_accounts, "record_admin_action",
                          pausing(real, paused, release, after=True)), \
                ThreadPoolExecutor(max_workers=2) as pool:
            retiring = pool.submit(in_own_connection(retire))
            assert paused.wait(30)
            reading = pool.submit(in_own_connection(dispatch_reads_destination))
            wait_for_a_lock_wait()
            release.set()
            retiring.result(30)
            assert reading.result(30) is False
        connections.close_all()


def test_a_retired_account_still_bound_to_the_method_is_offered_setup_again(two_countries):
    """Retired before the traveler changed country: the bound account no longer counts."""

    user = make_user("f1b-bound@example.com", is_email_verified=True)
    set_preference(actor=user, currency="EUR", enabled=True, country="FR", expected_revision=0)
    fr = ensure_account(
        actor=user, gateway=FakeGateway(create=snapshot(account_id="acct_1TESTfr", country="FR"))
    )
    assert "configure_eur" not in eur_actions(user)

    retire_account(actor=finance_staff(), account_id=fr.pk, reason="Wrong country.")

    assert eur_actions(user) == ["configure_eur"]
    second = ensure_account(
        actor=user, gateway=FakeGateway(create=snapshot(account_id="acct_1TESTfr2", country="FR"))
    )
    assert (second.provider_account_id, second.active) == ("acct_1TESTfr2", True)
    method = TravelerPayoutMethod.objects.get(traveler=user, currency="EUR")
    assert method.current_version.stripe_account_id == second.pk
