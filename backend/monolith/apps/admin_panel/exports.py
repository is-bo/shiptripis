"""Finance exports: transactions, commissions and payouts as CSV (spec 19.2, L14).

One builder per kind, each with an explicit column list (`COLUMNS`), frozen by
a test. Three rules hold every builder:

* **Recorded amounts only.** Every amount is a stored value: the payment
  attempt, refund or payout row, the deal's terms snapshot, or the ledger. The
  only work done on money is writing integer minor units as a decimal (1.5
  rule 2). Nothing here writes a finance row.
* **Nothing private.** A person is their internal id and their name. No email,
  phone, address, bank or card detail, document data or free text a person
  wrote is ever selected, so none can reach a cell; a test walks every cell.
* **Excel-safe.** UTF-8 with a byte-order mark, RFC 4180 quoting, and any cell
  that starts with ``=``, ``+``, ``-``, ``@``, a tab or a carriage return gets a
  leading apostrophe, so a spreadsheet never runs it as a formula. A plain
  number such as ``-12.50`` is the one exception: it cannot be a formula, and
  it stays a number a spreadsheet can add up.

A row belongs to a range by its own date in UTC: a payment by when it was
captured, a refund by when it was requested, a commission by when its deal was
funded, a payout by when it was created. Rows also belong to one money mode
(live, test or unknown), the same partition the finance dashboard reports.
Membership is fixed at the moment the export starts (`as_of`), so the line
count written to the audit log is exactly the number of lines sent.
"""

from __future__ import annotations

import csv
import heapq
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from datetime import timezone as dt_timezone

from django.db.models import (
    BigIntegerField,
    Exists,
    OuterRef,
    Q,
    Subquery,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce

from apps.deals.models import Deal
from apps.finance.models import (
    LedgerAccount,
    LedgerEntry,
    LedgerTransaction,
    PaymentAttempt,
    PaymentOrder,
    PaymentRefund,
    Payout,
)
from apps.finance.money import CURRENCY_EXPONENTS
from apps.parcels import tracking

TRANSACTIONS = "transactions"
COMMISSIONS = "commissions"
PAYOUTS = "payouts"
KINDS = (TRANSACTIONS, COMMISSIONS, PAYOUTS)

#: Spec 19.2: a range of at most 366 days, both ends included.
MAX_RANGE_DAYS = 366
#: The money modes the finance dashboard reports, one export each.
MODES = ("live", "test", "legacy_unknown")

#: Rows fetched per database round trip. The query count of an export does not
#: grow with its length (a test pins it per 1,000 lines).
CHUNK_SIZE = 1000

COLUMNS: dict[str, tuple[str, ...]] = {
    TRANSACTIONS: (
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
    COMMISSIONS: (
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
    PAYOUTS: (
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

PURPOSE_LABELS = {
    PaymentOrder.Purpose.POSTING_DEPOSIT: "deposit",
    PaymentOrder.Purpose.DEAL_BALANCE: "delivery",
    PaymentOrder.Purpose.BOOST: "boost",
}

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
#: A decimal amount as `_minor` writes it; the only text left unguarded.
_PLAIN_NUMBER = re.compile(r"-?[0-9]+(\.[0-9]+)?")


class ExportRangeError(ValueError):
    """The range is missing, reversed, too long or in the future."""


@dataclass(frozen=True)
class ExportRequest:
    kind: str
    mode: str
    start: date
    end: date
    #: The instant the export started. Rows dated after it are not included,
    #: whatever the range says.
    as_of: datetime

    def __post_init__(self):
        if self.kind not in KINDS:
            raise ValueError(f"Unknown export kind: {self.kind!r}")
        if self.mode not in MODES:
            raise ValueError(f"Unknown money mode: {self.mode!r}")
        validate_range(self.start, self.end, today=self.as_of.astimezone(dt_timezone.utc).date())

    @property
    def window(self) -> tuple[datetime, datetime]:
        """``[from 00:00 UTC, the day after to 00:00 UTC)``, capped at ``as_of``."""

        lower = datetime.combine(self.start, time.min, tzinfo=dt_timezone.utc)
        upper = datetime.combine(self.end + timedelta(days=1), time.min, tzinfo=dt_timezone.utc)
        return lower, min(upper, self.as_of)

    @property
    def filename(self) -> str:
        return (
            f"wassla-{self.kind}-{self.mode}-{self.start.isoformat()}"
            f"-to-{self.end.isoformat()}.csv"
        )


def validate_range(start: date | None, end: date | None, *, today: date) -> None:
    if start is None or end is None:
        raise ExportRangeError("Choose both dates.")
    if end < start:
        raise ExportRangeError("The end date is before the start date.")
    if (end - start).days + 1 > MAX_RANGE_DAYS:
        raise ExportRangeError(f"A range covers at most {MAX_RANGE_DAYS} days.")
    if end > today:
        raise ExportRangeError("The end date is in the future.")


# --- cells -----------------------------------------------------------------------


def guard_cell(value) -> str:
    """The cell as text, with a leading apostrophe if a spreadsheet could run it."""

    text = "" if value is None else str(value)
    if text.startswith(_FORMULA_PREFIXES) and not _PLAIN_NUMBER.fullmatch(text):
        return "'" + text
    return text


def _minor(amount: int | None, exponent: int) -> str:
    """Integer minor units as a plain decimal: 1234 cents is ``12.34``."""

    if amount is None:
        return ""
    sign = "-" if amount < 0 else ""
    whole, fraction = divmod(abs(int(amount)), 10**exponent)
    if exponent == 0:
        return f"{sign}{whole}"
    return f"{sign}{whole}.{fraction:0{exponent}d}"


def _eur(cents: int | None) -> str:
    return _minor(cents, CURRENCY_EXPONENTS["EUR"])


def _dinars(currency: str, amount: int | None, exponent: int | None) -> str:
    if (currency or "").upper() != "DZD" or amount is None:
        return ""
    return _minor(
        amount, CURRENCY_EXPONENTS["DZD"] if exponent is None else int(exponent)
    )


def _when(moment: datetime | None) -> str:
    if moment is None:
        return ""
    return moment.astimezone(dt_timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _paid_by(attempt: PaymentAttempt) -> str:
    return "guest" if attempt.guest_link_id or attempt.payer_id is None else "owner"


# --- transactions ------------------------------------------------------------------


def _captures(spec: ExportRequest):
    lower, upper = spec.window
    return PaymentAttempt.objects.filter(
        status=PaymentAttempt.Status.SUCCEEDED,
        provider_mode=spec.mode,
        succeeded_at__gte=lower,
        succeeded_at__lt=upper,
    )


def _refunds(spec: ExportRequest):
    lower, upper = spec.window
    return PaymentRefund.objects.filter(
        provider_mode=spec.mode, created_at__gte=lower, created_at__lt=upper
    )


_ORDER_PATHS = (
    "order__owner",
    "order__delivery_request",
    "order__deal__delivery_request",
)


def _capture_lines(spec: ExportRequest) -> Iterator[tuple[datetime, int, list]]:
    rows = (
        _captures(spec)
        .select_related(*_ORDER_PATHS)
        .order_by("succeeded_at", "pk")
    )
    for attempt in rows.iterator(chunk_size=CHUNK_SIZE):
        order = attempt.order
        yield (
            attempt.succeeded_at,
            0,
            [
                _when(attempt.succeeded_at),
                "payment",
                order.tracking_number,
                str(order.public_reference),
                attempt.provider,
                attempt.provider_payment_id or attempt.provider_session_id,
                PURPOSE_LABELS.get(order.purpose, order.purpose),
                _paid_by(attempt),
                _eur(attempt.amount_eur_cents),
                "EUR",
                _dinars(
                    attempt.payment_currency,
                    attempt.provider_amount_minor,
                    attempt.provider_amount_exponent,
                ),
                # A capture the order could not absorb is real money awaiting
                # its automatic refund; it is listed, and says so.
                "succeeded_unapplied" if attempt.is_unapplied else attempt.status,
                order.owner_id,
                order.owner.full_name,
            ],
        )


def _refund_lines(spec: ExportRequest) -> Iterator[tuple[datetime, int, list]]:
    rows = (
        _refunds(spec)
        .select_related(*_ORDER_PATHS, "attempt")
        .order_by("created_at", "pk")
    )
    for refund in rows.iterator(chunk_size=CHUNK_SIZE):
        order = refund.order
        yield (
            refund.created_at,
            1,
            [
                _when(refund.created_at),
                "refund",
                order.tracking_number,
                str(order.public_reference),
                refund.provider,
                refund.provider_refund_id,
                PURPOSE_LABELS.get(order.purpose, order.purpose),
                _paid_by(refund.attempt),
                _eur(refund.amount_eur_cents),
                "EUR",
                # A refund records its euro amount only; a dinar figure would
                # have to be computed, so the cell stays empty.
                "",
                refund.status,
                order.owner_id,
                order.owner.full_name,
            ],
        )


def _transaction_lines(spec: ExportRequest) -> Iterator[list]:
    merged = heapq.merge(
        _capture_lines(spec), _refund_lines(spec), key=lambda item: (item[0], item[1])
    )
    for _, _, line in merged:
        yield line


# --- commissions ------------------------------------------------------------------------


def _funded_deals(spec: ExportRequest):
    lower, upper = spec.window
    funding = LedgerEntry.objects.filter(
        deal_id=OuterRef("pk"),
        transaction__kind=LedgerTransaction.Kind.DEAL_FUNDING,
        transaction__provider_mode=spec.mode,
    )
    return Deal.objects.filter(
        funded_at__gte=lower, funded_at__lt=upper, terms__isnull=False
    ).filter(Exists(funding))


def _deal_ledger_total(mode: str, condition: Q):
    """Sum of one deal's ledger entries matching ``condition``, in this mode."""

    rows = (
        LedgerEntry.objects.filter(
            condition, deal_id=OuterRef("pk"), transaction__provider_mode=mode
        )
        .order_by()
        .values("deal_id")
        .annotate(total=Sum("amount_eur_cents"))
        .values("total")[:1]
    )
    return Coalesce(
        Subquery(rows, output_field=BigIntegerField()),
        Value(0),
        output_field=BigIntegerField(),
    )


def _commission_lines(spec: ExportRequest) -> Iterator[list]:
    rows = (
        _funded_deals(spec)
        .select_related("terms", "sender", "traveler", "delivery_request")
        .annotate(
            # Money sent back to the sender for this deal: the provider leg of
            # each refund transaction (negative on the clearing asset).
            refunded=_deal_ledger_total(
                spec.mode,
                Q(
                    transaction__kind=LedgerTransaction.Kind.REFUND,
                    account=LedgerAccount.PROVIDER_CLEARING,
                ),
            ),
            # What Wassla holds as commission for this deal now: every
            # platform-commission entry, recognition and corrections alike
            # (revenue is negative in this ledger's sign convention).
            commission=_deal_ledger_total(
                spec.mode, Q(account=LedgerAccount.PLATFORM_COMMISSION)
            ),
        )
        .order_by("funded_at", "pk")
    )
    for deal in rows.iterator(chunk_size=CHUNK_SIZE):
        terms = deal.terms
        yield [
            _when(deal.funded_at),
            tracking.for_deal(deal),
            _eur(terms.traveler_total_minor),
            _eur(terms.platform_total_minor),
            _eur(terms.sender_total_with_boost_minor),
            _eur(-deal.refunded),
            _eur(-deal.commission),
            terms.currency,
            deal.status,
            deal.sender_id,
            deal.sender.full_name,
            deal.traveler_id,
            deal.traveler.full_name,
        ]


# --- payouts -------------------------------------------------------------------------------


def _payouts(spec: ExportRequest):
    lower, upper = spec.window
    return Payout.objects.filter(
        provider_mode=spec.mode, created_at__gte=lower, created_at__lt=upper
    )


def _payout_lines(spec: ExportRequest) -> Iterator[list]:
    rows = (
        _payouts(spec)
        .select_related("traveler", "deal__delivery_request")
        .order_by("created_at", "pk")
    )
    for payout in rows.iterator(chunk_size=CHUNK_SIZE):
        yield [
            _when(payout.created_at),
            tracking.for_deal(payout.deal),
            str(payout.public_reference),
            payout.method,
            payout.status,
            _eur(payout.amount_eur_cents),
            "EUR",
            _dinars(
                payout.payout_currency,
                payout.payout_amount_minor,
                payout.payout_amount_exponent,
            ),
            _when(payout.eligible_at),
            _when(payout.paid_at),
            payout.failure_code,
            payout.traveler_id,
            payout.traveler.full_name,
        ]


# --- the export -----------------------------------------------------------------------------


def line_count(spec: ExportRequest) -> int:
    """How many lines the export holds, header not counted."""

    if spec.kind == TRANSACTIONS:
        return _captures(spec).count() + _refunds(spec).count()
    if spec.kind == COMMISSIONS:
        return _funded_deals(spec).count()
    return _payouts(spec).count()


def lines(spec: ExportRequest) -> Iterator[list]:
    """The export's lines, oldest first, header not included."""

    builder = {
        TRANSACTIONS: _transaction_lines,
        COMMISSIONS: _commission_lines,
        PAYOUTS: _payout_lines,
    }[spec.kind]
    return builder(spec)


class _Echo:
    """A file-like object whose ``write`` hands the text straight back."""

    def write(self, value: str) -> str:
        return value


def csv_chunks(spec: ExportRequest) -> Iterator[str]:
    """The whole file, as text pieces for a streamed response."""

    writer = csv.writer(_Echo(), quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    yield "﻿" + writer.writerow([guard_cell(name) for name in COLUMNS[spec.kind]])
    for line in lines(spec):
        yield writer.writerow([guard_cell(value) for value in line])
