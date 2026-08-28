"""Reusable conservation checks for payment races and recovery tests."""

from __future__ import annotations

from django.db.models import Sum

from apps.finance.models import (
    LedgerEntry,
    LedgerTransaction,
    PaymentAttempt,
    PaymentOrder,
    PaymentRefund,
)
from apps.finance.providers.mock import MockGateway


def assert_financial_conservation(
    *, external_success_eur_cents: int, order_ids: list[int] | tuple[int, ...]
) -> None:
    """Assert provider truth, application truth, obligations and books agree."""

    attempts = list(
        PaymentAttempt.objects.select_related("order")
        .filter(
            order_id__in=order_ids,
            status=PaymentAttempt.Status.SUCCEEDED,
        )
        .order_by("pk")
    )
    accounted = sum(int(row.amount_eur_cents) for row in attempts)
    applied = sum(
        int(row.amount_eur_cents) for row in attempts if not row.is_unapplied
    )
    unapplied = sum(
        int(row.amount_eur_cents) for row in attempts if row.is_unapplied
    )
    assert external_success_eur_cents == accounted, (
        external_success_eur_cents,
        accounted,
    )
    assert accounted == applied + unapplied

    locally_applied = int(
        PaymentOrder.objects.filter(pk__in=order_ids).aggregate(
            total=Sum("paid_eur_cents")
        )["total"]
        or 0
    )
    assert locally_applied == applied, (locally_applied, applied)

    obligation_statuses = (
        PaymentRefund.Status.PENDING,
        PaymentRefund.Status.PROCESSING,
        PaymentRefund.Status.SUCCEEDED,
    )
    for attempt in attempts:
        invalid = attempt.is_unapplied or attempt.order.cancelled_at is not None
        if invalid:
            obligated = int(
                PaymentRefund.objects.filter(
                    attempt=attempt,
                    status__in=obligation_statuses,
                ).aggregate(total=Sum("amount_eur_cents"))["total"]
                or 0
            )
            assert obligated == int(attempt.amount_eur_cents), (
                attempt.pk,
                obligated,
                attempt.amount_eur_cents,
            )

        assert LedgerTransaction.objects.filter(
            kind=LedgerTransaction.Kind.CUSTOMER_PAYMENT,
            entries__attempt=attempt,
        ).exists(), f"Succeeded attempt {attempt.pk} has no payment ledger fact."

    for ledger_transaction in LedgerTransaction.objects.filter(
        entries__order_id__in=order_ids
    ).distinct():
        total = int(
            LedgerEntry.objects.filter(transaction=ledger_transaction).aggregate(
                total=Sum("amount_eur_cents")
            )["total"]
            or 0
        )
        assert total == 0, f"{ledger_transaction.key} nets {total}."


def assert_provider_funds_are_locally_accounted(
    *,
    order_ids: list[int] | tuple[int, ...],
    session_ids: list[str] | tuple[str, ...],
) -> None:
    """Cross-check local accounting against the provider double's own record.

    `MockGateway` keeps its captures in module-level dictionaries that Django
    never writes to, so this is genuinely external truth: if a transaction
    rolled back and lost a successful payment locally, the provider still
    believes the customer was charged and this assertion fails.

    Pass the session ids captured *before* the code under test ran. Deriving
    them from the database instead would let a lost attempt row hide itself.
    """

    external = MockGateway.successful_funds_minor(session_ids=tuple(session_ids))
    assert external > 0, "The provider double recorded no successful capture."
    assert_financial_conservation(
        external_success_eur_cents=external, order_ids=order_ids
    )
