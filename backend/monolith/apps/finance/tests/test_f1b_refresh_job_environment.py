"""F1b: the readiness job sends an account id only to the platform that opened it.

`handle_payout_account_refresh` loads its account by id. After a switch to
another Stripe platform, or another mode, that id means nothing to the new
credential, so the job checks `in_this_environment` first, as the member's
calls do (`destination_account`), and ends as done with the reason recorded.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.test import override_settings

from apps.finance.jobs import handle_payout_account_refresh
from apps.finance.models import StripePayoutAccount

from .factories import make_user
from .test_phase8fh2_accounts import H2, PLATFORM, FakeGateway, ready_snapshot


def account_of(platform=PLATFORM, mode="test"):
    return StripePayoutAccount.objects.create(
        traveler=make_user(f"f1b-job-{platform}-{mode}@example.com"),
        platform_id=platform,
        provider_account_id="acct_1TESTconnected",
        provider_mode=mode,
        declared_country="FR",
        creation_operation_key=f"f1b-job:{platform}:{mode}",
    )


@pytest.fixture
def h2(db):
    with override_settings(**H2):
        yield


def run(account, gateway):
    with patch("apps.finance.payout_accounts.get_connect_gateway", return_value=gateway):
        return handle_payout_account_refresh({"account_id": account.pk})


def test_an_account_of_the_current_platform_is_refreshed(h2):
    account = account_of()
    gateway = FakeGateway(retrieve=ready_snapshot())

    assert run(account, gateway) == "refreshed"

    assert gateway.calls == [("retrieve_account", "acct_1TESTconnected")]
    account.refresh_from_db()
    assert account.readiness_checked_at is not None


@pytest.mark.parametrize(
    "platform, mode", [("acct_1OTHERplatform", "test"), (PLATFORM, "live")]
)
def test_an_account_of_another_platform_or_mode_makes_no_provider_call(h2, platform, mode):
    account = account_of(platform, mode)
    gateway = FakeGateway(retrieve=ready_snapshot())

    assert run(account, gateway) == "account_other_environment"

    assert gateway.calls == []
    account.refresh_from_db()
    assert account.readiness_checked_at is None
