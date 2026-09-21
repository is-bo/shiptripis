"""K2 continuity for the Manual DZD operator workflow."""

from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

import pytest
from django.test import Client
from django.urls import reverse

from apps.admin_panel.finance_operations import _payout_detail_url

from .test_phase8fh4_manual import (  # noqa: F401
    build_manual,
    configured_h4,
    image_upload,
)


def _url(payout, cohort="waiting"):
    return f"{reverse('admin_console:payout-detail', args=(payout.pk,))}?cohort={cohort}"


def _assert_location(response, *, fragment, cohort="waiting"):
    assert response.status_code == 302
    split = urlsplit(response["Location"])
    assert split.fragment == fragment
    assert parse_qs(split.query) == {"cohort": [cohort]}


def test_manual_queue_detail_link_carries_only_known_cohort():
    known = _payout_detail_url(8, {"cohort": "waiting"}, manual=True)
    assert parse_qs(urlsplit(known).query) == {"cohort": ["waiting"]}
    assert urlsplit(known).path == reverse("admin_console:payout-detail", args=(8,))
    assert not urlsplit(
        _payout_detail_url(8, {"cohort": "https://evil.test"}, manual=True)
    ).query
    assert not urlsplit(
        _payout_detail_url(8, {"cohort": "waiting"}, manual=False)
    ).query


@pytest.mark.django_db
def test_prepare_release_begin_and_receipt_keep_payout_context(configured_h4):  # noqa: F811
    scenario, payout, _profile = build_manual(prefix="k2-flow")
    client = Client()
    client.force_login(scenario.admin)
    url = _url(payout)

    prepared = client.post(
        url,
        {"action": "prepare", "state_version": payout.state_version},
    )
    _assert_location(prepared, fragment="st-transfer-head")
    payout.refresh_from_db()
    attempt = payout.attempts.order_by("-sequence").first()

    released = client.post(
        url,
        {"action": "release", "sequence": attempt.sequence},
    )
    _assert_location(released, fragment="st-transfer-head")

    payout.refresh_from_db()
    prepared_again = client.post(
        url,
        {"action": "prepare", "state_version": payout.state_version},
    )
    _assert_location(prepared_again, fragment="st-transfer-head")
    attempt = payout.attempts.order_by("-sequence").first()

    begun = client.post(url, {"action": "begin", "sequence": attempt.sequence})
    _assert_location(begun, fragment="st-transfer-head")

    receipt = client.post(
        url,
        {
            "action": "receipt",
            "sequence": attempt.sequence,
            "confirmed": "on",
            "receipt": image_upload(),
        },
    )
    _assert_location(receipt, fragment="st-receipts-head")


@pytest.mark.django_db
def test_review_hold_and_clear_hold_keep_relevant_sections(configured_h4):  # noqa: F811
    scenario, payout, _profile = build_manual(prefix="k2-sections")
    client = Client()
    client.force_login(scenario.admin)
    url = _url(payout)

    with patch("apps.admin_panel.console_manual_payout.review_profile"):
        reviewed = client.post(url, {"action": "review"})
    _assert_location(reviewed, fragment="st-proof-head")

    held = client.post(url, {"action": "hold"})
    _assert_location(held, fragment="st-holds-head")
    hold = payout.holds.get(cleared_at__isnull=True)

    cleared = client.post(
        url,
        {
            "action": "clear_hold",
            "hold_id": hold.pk,
            "generation": hold.generation,
        },
    )
    _assert_location(cleared, fragment="st-holds-head")


@pytest.mark.django_db
def test_invalid_cohort_is_dropped_and_reveal_remains_request_scoped(configured_h4):  # noqa: F811
    scenario, payout, _profile = build_manual(prefix="k2-allowlist")
    client = Client()
    client.force_login(scenario.admin)

    held = client.post(_url(payout, "https://evil.test"), {"action": "hold"})
    assert held.status_code == 302
    split = urlsplit(held["Location"])
    assert split.query == ""
    assert split.fragment == "st-holds-head"

    revealed = client.post(_url(payout), {"action": "reveal"})
    assert revealed.status_code == 200
    assert "Location" not in revealed
    assert "0000000000" in revealed.content.decode()
    assert "0000000000" not in revealed.request["QUERY_STRING"]
