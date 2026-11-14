"""L14, spec 19.2: finance exports.

The frozen columns, who may download, the range rules, the Excel-safe cells,
the audit row, the privacy walk over every cell, the totals against the finance
dashboard, a query count that does not grow with the file, and that the page
writes no finance row.
"""

from __future__ import annotations

import csv
import io
from datetime import date, timedelta
from datetime import timezone as dt_timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from django.db import connection
from django.test import Client, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.admin_panel import exports
from apps.admin_panel.console_exports import AUDIT_ACTION
from apps.admin_panel.models import AdminAuditLog
from apps.admin_panel.permissions import AdminRole, assign_admin_roles
from apps.admin_panel.tests.two_step_helpers import staff_login
from apps.finance import ledger
from apps.finance.control_plane.filters import Scope
from apps.finance.control_plane.snapshot import build_snapshot
from apps.finance.models import LedgerEntry, PaymentAttempt, PaymentOrder, PaymentRefund
from apps.finance.payout_release import evaluate_payout_release
from apps.finance.tests.factories import build_scenario, make_user
from apps.parcels import tracking
from apps.finance.tests.test_phase8fh5_control_plane import (  # noqa: F401
    no_provider_network,
    record_capture,
    world,
)

pytestmark = [
    # The dashboard fixtures seed business settings for every test here.
    pytest.mark.django_db,
    pytest.mark.skipif(
        connection.vendor != "postgresql", reason="exports are measured on PostgreSQL"
    ),
]

PLAIN_STATIC = override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)

FROZEN_COLUMNS = {
    "transactions": (
        "Date (UTC)",
        "Type",
        "Tracking number",
        "Payment reference",
        "Provider",
        "Provider reference",
        "Purpose",
        "Paid by",
        "Amount",
        "Currency",
        "Dinar amount",
        "Status",
        "Sender id",
        "Sender name",
    ),
    "commissions": (
        "Funded date (UTC)",
        "Tracking number",
        "Traveler reward",
        "Wassla fee",
        "Sender total",
        "Refunded to sender",
        "Fee kept",
        "Currency",
        "Deal status",
        "Sender id",
        "Sender name",
        "Traveler id",
        "Traveler name",
    ),
    "payouts": (
        "Created date (UTC)",
        "Tracking number",
        "Payout reference",
        "Method",
        "Status",
        "Amount",
        "Currency",
        "Dinar amount",
        "Eligible date (UTC)",
        "Paid date (UTC)",
        "Failure reason",
        "Traveler id",
        "Traveler name",
    ),
}


def utc_today() -> date:
    return timezone.now().astimezone(dt_timezone.utc).date()


def spec(kind: str, *, mode: str = "test", days: int = 2) -> exports.ExportRequest:
    today = utc_today()
    return exports.ExportRequest(
        kind=kind,
        mode=mode,
        start=today - timedelta(days=days - 1),
        end=today,
        as_of=timezone.now(),
    )


def read(text: str) -> list[dict]:
    assert text.startswith("﻿")
    return list(csv.DictReader(io.StringIO(text[1:], newline="")))


def export(kind: str, **values) -> list[dict]:
    return read("".join(exports.csv_chunks(spec(kind, **values))))


def cents(text: str) -> int:
    return int(Decimal(text) * 100)


def finance_staff(role: str = AdminRole.FINANCE):
    user = make_user(f"{role}-{uuid4().hex[:6]}@example.test", is_staff=True)
    assign_admin_roles(user, (role,), elevate_super_admin=role == AdminRole.SUPER_ADMIN)
    return user


def signed_in(user) -> Client:
    client = Client()
    staff_login(client, user)
    return client


def form(kind="transactions", mode="test", *, start=None, end=None) -> dict:
    today = utc_today()
    return {
        "kind": kind,
        "mode": mode,
        "start": (start or today - timedelta(days=1)).isoformat(),
        "end": (end or today).isoformat(),
    }


# --- the contract ---------------------------------------------------------------------


def test_the_columns_are_frozen():
    assert exports.COLUMNS == FROZEN_COLUMNS
    assert exports.KINDS == ("transactions", "commissions", "payouts")
    assert exports.MODES == ("live", "test", "legacy_unknown")


def test_cells_that_a_spreadsheet_could_run_get_an_apostrophe():
    for text in ("=1+1", "+cmd", "-2+3", "@SUM(A1)", "\tx", "\rx", "=HYPERLINK(\"x\")"):
        assert exports.guard_cell(text) == "'" + text
    # Plain amounts stay numbers a spreadsheet can add up.
    for text in ("-12.50", "0.00", "12", "-3"):
        assert exports.guard_cell(text) == text
    assert exports.guard_cell(None) == ""
    assert exports.guard_cell("Amina") == "Amina"


def test_amounts_are_the_stored_minor_units_written_as_decimals():
    assert exports._minor(1234, 2) == "12.34"
    assert exports._minor(-5, 2) == "-0.05"
    assert exports._minor(0, 2) == "0.00"
    assert exports._minor(7, 0) == "7"
    assert exports._minor(None, 2) == ""
    assert exports._dinars("DZD", 250000, 2) == "2500.00"
    assert exports._dinars("EUR", 250000, 2) == ""


def test_the_range_rules():
    today = date(2026, 11, 14)
    exports.validate_range(today - timedelta(days=365), today, today=today)
    refusals = (
        (None, today, "both dates"),
        (today, today - timedelta(days=1), "before the start"),
        (today - timedelta(days=366), today, "at most 366 days"),
        (today, today + timedelta(days=1), "in the future"),
    )
    for start, end, message in refusals:
        with pytest.raises(exports.ExportRangeError, match=message):
            exports.validate_range(start, end, today=today)
    with pytest.raises(ValueError):
        exports.ExportRequest(
            kind="ledger", mode="test", start=today, end=today, as_of=timezone.now()
        )
    with pytest.raises(ValueError):
        exports.ExportRequest(
            kind="payouts", mode="sandbox", start=today, end=today, as_of=timezone.now()
        )


def test_the_window_is_whole_utc_days_capped_at_the_start_of_the_export():
    request = exports.ExportRequest(
        kind="payouts",
        mode="live",
        start=date(2026, 1, 1),
        end=date(2026, 1, 31),
        as_of=timezone.now(),
    )
    lower, upper = request.window
    assert lower.isoformat() == "2026-01-01T00:00:00+00:00"
    assert upper.isoformat() == "2026-02-01T00:00:00+00:00"
    assert request.filename == "wassla-payouts-live-2026-01-01-to-2026-01-31.csv"
    now = timezone.now()
    today = exports.ExportRequest(
        kind="payouts", mode="live", start=utc_today(), end=utc_today(), as_of=now
    )
    assert today.window[1] == now


# --- the page ----------------------------------------------------------------------------


@PLAIN_STATIC
@pytest.mark.parametrize(
    "role, allowed",
    [
        (AdminRole.FINANCE, True),
        (AdminRole.SUPER_ADMIN, True),
        (AdminRole.OPS, False),
        (AdminRole.SUPPORT, False),
        (AdminRole.TRUST, False),
    ],
)
def test_only_finance_and_super_admins_may_export(role, allowed):
    client = signed_in(finance_staff(role))
    url = reverse("admin_console:finance-exports")
    page = client.get(url)
    download = client.post(url, form())
    if allowed:
        assert page.status_code == 200
        assert "Finance exports" in page.content.decode()
        assert download.status_code == 200
        assert download["Content-Type"] == "text/csv; charset=utf-8"
    else:
        assert page.status_code == 403
        assert download.status_code == 403
        assert not AdminAuditLog.objects.filter(action=AUDIT_ACTION).exists()


@PLAIN_STATIC
def test_the_page_needs_the_second_step():
    client = Client()
    client.force_login(finance_staff())
    response = client.post(reverse("admin_console:finance-exports"), form())
    assert response.status_code == 302
    assert response["Location"].startswith("/admin/two-step/")
    assert not AdminAuditLog.objects.filter(action=AUDIT_ACTION).exists()


@PLAIN_STATIC
def test_a_refused_range_explains_itself_and_records_nothing():
    client = signed_in(finance_staff())
    url = reverse("admin_console:finance-exports")
    today = utc_today()
    cases = (
        (form(start=today - timedelta(days=366)), "at most 366 days"),
        (form(start=today, end=today - timedelta(days=1)), "before the start"),
        (form(end=today + timedelta(days=1)), "in the future"),
        ({**form(), "start": ""}, "This field is required"),
        ({**form(), "kind": "ledger"}, "Select a valid choice"),
        ({**form(), "mode": "sandbox"}, "Select a valid choice"),
    )
    for data, message in cases:
        response = client.post(url, data)
        assert response.status_code == 400, data
        assert message in response.content.decode(), data
    assert not AdminAuditLog.objects.filter(action=AUDIT_ACTION).exists()


@PLAIN_STATIC
def test_a_download_is_audited_before_it_streams_and_listed_afterwards():
    staff = finance_staff()
    client = signed_in(staff)
    s = build_scenario(prefix=f"exp-{uuid4().hex[:6]}")
    order = PaymentOrder.objects.create(
        owner=s.sender,
        delivery_request=s.delivery_request,
        purpose="posting_deposit",
        amount_eur_cents=500,
    )
    PaymentAttempt.objects.create(
        order=order,
        provider="stripe",
        provider_mode="test",
        amount_eur_cents=500,
        payment_currency="EUR",
        provider_amount_minor=500,
        idempotency_key=f"exp-{order.pk}",
        status="succeeded",
        succeeded_at=timezone.now(),
    )
    url = reverse("admin_console:finance-exports")
    response = client.post(url, form())
    assert response.status_code == 200
    assert response.streaming
    # The audit row exists before the first byte is read.
    audit = AdminAuditLog.objects.get(action=AUDIT_ACTION)
    body = b"".join(response.streaming_content).decode("utf-8")
    rows = read(body)
    today = utc_today()
    assert audit.actor == staff
    assert audit.target_type == "finance.export" and audit.target_id == "transactions"
    assert audit.after == {
        "kind": "transactions",
        "mode": "test",
        "from": (today - timedelta(days=1)).isoformat(),
        "to": today.isoformat(),
        "lines": 1,
    }
    assert len(rows) == audit.after["lines"]
    assert rows[0]["Amount"] == "5.00" and rows[0]["Type"] == "payment"
    assert "\r\n" in body
    assert response["Content-Disposition"] == (
        f'attachment; filename="wassla-transactions-test-'
        f'{(today - timedelta(days=1)).isoformat()}-to-{today.isoformat()}.csv"'
    )
    assert "no-store" in response["Cache-Control"]
    assert response["X-Content-Type-Options"] == "nosniff"
    # Live money is a different file; nothing test-mode is in it.
    live = client.post(url, form(mode="live"))
    assert read(b"".join(live.streaming_content).decode("utf-8")) == []
    listed = client.get(url).content.decode()
    assert "<small>Test money</small>" in listed and "<small>Live money</small>" in listed


@PLAIN_STATIC
def test_the_page_writes_no_finance_row():
    client = signed_in(finance_staff())
    s = build_scenario(prefix=f"exw-{uuid4().hex[:6]}")
    record_capture(s.sender, amount=900)
    finance_rows = LedgerEntry.objects.count(), PaymentAttempt.objects.count()
    url = reverse("admin_console:finance-exports")
    for kind in exports.KINDS:
        with CaptureQueriesContext(connection) as recorded:
            response = client.post(url, form(kind=kind))
            b"".join(response.streaming_content)
        writes = [
            q["sql"]
            for q in recorded
            if q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
        ]
        assert writes, "the audit row is written"
        for sql in writes:
            assert '"admin_panel_audit_log"' in sql or '"django_session"' in sql, sql
    assert (LedgerEntry.objects.count(), PaymentAttempt.objects.count()) == finance_rows


# --- the content ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_totals_match_the_finance_dashboard(world):  # noqa: F811
    s, payout, _, capture = world
    evaluate_payout_release(deal_id=s.deal.pk)
    board = build_snapshot(Scope.parse({"mode": "test"}))

    def total(key):
        return board["metrics"][key]["amount_eur_cents"]

    commissions = export("commissions")
    assert [row["Tracking number"] for row in commissions] == [tracking.for_deal(s.deal)]
    assert sum(cents(row["Fee kept"]) for row in commissions) == total("recognized_revenue")
    payouts = export("payouts")
    assert [row["Payout reference"] for row in payouts] == [str(payout.public_reference)]
    assert sum(cents(row["Amount"]) for row in payouts) == total("traveler_outstanding")

    order, extra = record_capture(s.sender, amount=1000)
    _, unapplied = record_capture(s.sender, amount=700, unapplied=True)
    for attempt, amount in ((extra, 400), (unapplied, 700)):
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
    board = build_snapshot(Scope.parse({"mode": "test"}))
    transactions = export("transactions")
    payments = [row for row in transactions if row["Type"] == "payment"]
    refunds = [row for row in transactions if row["Type"] == "refund"]
    assert sum(
        cents(row["Amount"]) for row in payments if row["Status"] == "succeeded"
    ) == total("gross_funded")
    assert [row["Status"] for row in payments].count("succeeded_unapplied") == 1
    assert sum(
        cents(row["Amount"]) for row in refunds if row["Status"] == "succeeded"
    ) == total("refunds_finalized")
    assert len(transactions) == exports.line_count(spec("transactions"))
    # Oldest first, payments and refunds interleaved by their own dates.
    stamps = [row["Date (UTC)"] for row in transactions]
    assert stamps == sorted(stamps)
    # Another money mode shares none of it.
    for kind in exports.KINDS:
        assert export(kind, mode="live") == []


def test_no_private_detail_reaches_any_cell():
    s = build_scenario(prefix=f"exp-{uuid4().hex[:6]}")
    secrets = []
    for person, index in ((s.sender, 1), (s.traveler, 2)):
        person.full_name = f"=HYPERLINK(\"https://x.invalid/{index}\")"
        person.phone = f"+21355500{index:04d}"
        person.save(update_fields=["full_name", "phone"])
        secrets += [person.email, person.phone, person.email.split("@")[0]]
    s.accept()
    order = s.balance_order()
    PaymentAttempt.objects.create(
        order=order,
        provider="chargily",
        provider_mode="test",
        amount_eur_cents=order.amount_eur_cents,
        payment_currency="DZD",
        fx_rate_micros=150_000_000,
        provider_amount_minor=order.amount_eur_cents * 150,
        provider_amount_exponent=2,
        idempotency_key=f"exp-dzd-{order.pk}",
        status="succeeded",
        succeeded_at=timezone.now(),
        payer=s.sender,
    )
    # A guest's provider-reported email is stored on the attempt; it never leaves.
    PaymentAttempt.objects.create(
        order=order,
        provider="stripe",
        provider_mode="test",
        amount_eur_cents=order.amount_eur_cents,
        payment_currency="EUR",
        provider_amount_minor=order.amount_eur_cents,
        idempotency_key=f"exp-guest-{order.pk}",
        status="succeeded",
        succeeded_at=timezone.now(),
        guest_email="guest-payer@example.invalid",
    )
    secrets.append("guest-payer")
    text = "".join(exports.csv_chunks(spec("transactions")))
    rows = read(text)
    assert rows and rows[0]["Dinar amount"] == exports._minor(order.amount_eur_cents * 150, 2)
    assert rows[0]["Sender name"].startswith("'=HYPERLINK")
    assert rows[0]["Paid by"] == "owner" and rows[0]["Purpose"] == "delivery"
    assert rows[1]["Paid by"] == "guest" and rows[1]["Dinar amount"] == ""
    for kind in exports.KINDS:
        body = "".join(exports.csv_chunks(spec(kind)))
        for secret in secrets:
            assert secret not in body, (kind, secret)
        assert "@" not in body, kind


def test_the_query_count_does_not_grow_with_the_file():
    s = build_scenario(prefix=f"exq-{uuid4().hex[:6]}")
    order = PaymentOrder.objects.create(
        owner=s.sender,
        delivery_request=s.delivery_request,
        purpose="posting_deposit",
        amount_eur_cents=100,
    )
    now = timezone.now()

    def grow_to(total: int) -> None:
        have = PaymentAttempt.objects.filter(order=order).count()
        PaymentAttempt.objects.bulk_create(
            PaymentAttempt(
                order=order,
                provider="stripe",
                provider_mode="test",
                amount_eur_cents=100,
                payment_currency="EUR",
                provider_amount_minor=100,
                idempotency_key=f"exq-{index}",
                status="succeeded",
                succeeded_at=now - timedelta(seconds=index),
            )
            for index in range(have, total)
        )

    def measure() -> tuple[int, int]:
        with CaptureQueriesContext(connection) as recorded:
            request = spec("transactions")
            count = exports.line_count(request)
            body = "".join(exports.csv_chunks(request))
        assert len(read(body)) == count
        return count, len(recorded)

    grow_to(10)
    small, small_queries = measure()
    grow_to(1000)
    large, large_queries = measure()
    assert (small, large) == (10, 1000)
    assert large_queries == small_queries
