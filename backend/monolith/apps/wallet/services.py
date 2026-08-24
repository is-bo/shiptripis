"""Wallet write API — the ONLY place that writes WalletEntry/Hold rows.

Rules (CLAUDE.md §6 + ARCHITECTURE.md §11):
- Entries are append-only. Never UPDATE or DELETE.
- Every entry has an idempotency `key`; replays are silent no-ops.
- Balance is computed via SUM(amount_minor). Never read a cached number.
- A "hold" creates a debit-style accounting pair: deposit (+amount) and
  hold (-amount) so the available balance reflects only what's not locked.
- A "release" flips a closed hold into a payout: release (+amount) on the
  sender wallet, payout (+amount) on the traveler wallet — net zero between
  the two except for the platform fee, which is captured by `commission_dzd`
  on the Offer (we don't dock it from the traveler wallet in V1 because the
  sender's `total_dzd` already excludes platform take; see pricing.py).

This module is the boundary every other app calls through. No view writes
to WalletEntry directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from apps.accounts.models import User

from .models import Hold, Wallet, WalletEntry


# ---------- balance reads ----------


@dataclass(frozen=True, slots=True)
class WalletBalance:
    total_minor: int      # sum of all entries (available + held)
    available_minor: int  # excludes open holds
    on_hold_minor: int    # sum of open holds


def get_or_create_wallet(user: User, currency: str) -> Wallet:
    wallet, _ = Wallet.objects.get_or_create(user=user, currency=currency)
    return wallet


def get_balance(wallet: Wallet) -> WalletBalance:
    """Compute live balance from ledger entries + open holds.

    A HOLD entry is written as a negative amount alongside its positive DEPOSIT,
    so SUM(entries) already excludes locked funds — that sum is both the
    `total_minor` and the `available_minor`. `on_hold_minor` is reported
    separately from the Hold table for display.
    """
    ledger_sum = (
        wallet.entries.aggregate(s=Sum("amount_minor")).get("s") or 0
    )
    on_hold = (
        wallet.holds.filter(status=Hold.Status.OPEN)
        .aggregate(s=Sum("amount_minor"))
        .get("s")
        or 0
    )
    return WalletBalance(
        total_minor=ledger_sum,
        available_minor=ledger_sum,
        on_hold_minor=on_hold,
    )


# ---------- writes (idempotent) ----------


def _record_entry(
    *,
    wallet: Wallet,
    kind: str,
    amount_minor: int,
    currency: str,
    key: str,
    source: str = "",
    source_id: int | None = None,
    note: str = "",
) -> WalletEntry | None:
    """Insert one WalletEntry. Silent no-op if `(wallet, key)` already exists.

    Returns the row when created, None when the entry already existed
    (idempotent replay).
    """
    if currency != wallet.currency:
        raise ValueError(
            f"Currency mismatch: wallet={wallet.currency} entry={currency}"
        )
    try:
        with transaction.atomic():
            return WalletEntry.objects.create(
                wallet=wallet,
                kind=kind,
                amount_minor=amount_minor,
                currency=currency,
                key=key,
                source=source,
                source_id=source_id,
                note=note,
            )
    except IntegrityError:
        # Replay — entry already in ledger. Savepoint above isolates the
        # failure so the outer atomic block stays usable.
        return None


@transaction.atomic
def open_hold(
    *,
    user: User,
    currency: str,
    amount_minor: int,
    source: str,
    source_id: int,
    note: str = "",
) -> Hold:
    """Capture funds from a payment into an escrow hold.

    Writes a deposit entry (+amount) and a hold entry (-amount) so the
    available balance is unchanged but `on_hold` reflects the escrow.
    Creates a Hold row pinned to `(source, source_id)`.

    Idempotent: re-calling with the same `(source, source_id)` returns the
    existing Hold.
    """
    wallet = get_or_create_wallet(user, currency)

    existing = Hold.objects.filter(source=source, source_id=source_id).first()
    if existing is not None:
        return existing

    base_key = f"{source}:{source_id}"
    _record_entry(
        wallet=wallet,
        kind=WalletEntry.Kind.DEPOSIT,
        amount_minor=amount_minor,
        currency=currency,
        key=f"{base_key}:deposit",
        source=source,
        source_id=source_id,
        note=note or f"Deposit for {source}#{source_id}",
    )
    _record_entry(
        wallet=wallet,
        kind=WalletEntry.Kind.HOLD,
        amount_minor=-amount_minor,
        currency=currency,
        key=f"{base_key}:hold",
        source=source,
        source_id=source_id,
        note=note or f"Hold for {source}#{source_id}",
    )
    try:
        with transaction.atomic():
            return Hold.objects.create(
                wallet=wallet,
                amount_minor=amount_minor,
                currency=currency,
                source=source,
                source_id=source_id,
                status=Hold.Status.OPEN,
            )
    except IntegrityError:
        # Isolate the uniqueness race in a savepoint so the outer transaction
        # can safely read and return the winning row.
        return Hold.objects.get(source=source, source_id=source_id)


@transaction.atomic
def release_hold_to_payee(
    *,
    hold: Hold,
    payee: User,
    payee_amount_minor: int,
    platform_fee_minor: int = 0,
    release_source: str,
    release_source_id: int,
    note: str = "",
) -> Hold:
    """Close an open hold and pay the payee.

    Effects (atomic):
      sender wallet:
        + release entry  = +amount_minor (closes the negative hold)
        - payout entry   = -amount_minor (money leaves to payee)
      payee wallet (same currency):
        + payout entry   = +payee_amount_minor
        (platform_fee_minor stays on the platform; not in any user wallet)
      hold.status = released

    `release_source` + `release_source_id` are the trigger (e.g. handover
    confirmation), used as the idempotency key suffix. Re-calling with the
    same trigger is a no-op.
    """
    hold = (
        Hold.objects.select_for_update()
        .select_related("wallet")
        .get(pk=hold.pk)
    )
    if hold.status == Hold.Status.RELEASED:
        return hold
    if hold.status != Hold.Status.OPEN:
        raise ValueError(f"Hold {hold.id} is not open (status={hold.status}).")
    if payee_amount_minor + platform_fee_minor > hold.amount_minor:
        raise ValueError("Payee + fee exceeds held amount.")

    sender_wallet = hold.wallet
    payee_wallet = get_or_create_wallet(payee, hold.currency)

    base_key = f"{release_source}:{release_source_id}"

    _record_entry(
        wallet=sender_wallet,
        kind=WalletEntry.Kind.RELEASE,
        amount_minor=hold.amount_minor,
        currency=hold.currency,
        key=f"{base_key}:release:{hold.id}",
        source=release_source,
        source_id=release_source_id,
        note=note or f"Release hold #{hold.id}",
    )
    _record_entry(
        wallet=sender_wallet,
        kind=WalletEntry.Kind.PAYOUT,
        amount_minor=-hold.amount_minor,
        currency=hold.currency,
        key=f"{base_key}:payout:{hold.id}",
        source=release_source,
        source_id=release_source_id,
        note=note or f"Payout for hold #{hold.id}",
    )
    _record_entry(
        wallet=payee_wallet,
        kind=WalletEntry.Kind.PAYOUT,
        amount_minor=payee_amount_minor,
        currency=hold.currency,
        key=f"{base_key}:credit:{hold.id}",
        source=release_source,
        source_id=release_source_id,
        note=note or f"Credit from release #{hold.id}",
    )

    hold.status = Hold.Status.RELEASED
    hold.closed_at = timezone.now()
    hold.save(update_fields=["status", "closed_at"])
    return hold


@transaction.atomic
def reverse_hold_for_refund(
    *,
    hold: Hold,
    refund_source: str,
    refund_source_id: int,
    note: str = "",
) -> Hold:
    """Close an open hold for a refund (money goes back to the provider).

    sender wallet:
      + release entry = +amount_minor (closes hold)
      - refund entry  = -amount_minor (money leaves wallet back to provider)
    hold.status = reversed

    Idempotent.
    """
    hold = (
        Hold.objects.select_for_update()
        .select_related("wallet")
        .get(pk=hold.pk)
    )
    if hold.status != Hold.Status.OPEN:
        return hold

    sender_wallet = hold.wallet
    base_key = f"{refund_source}:{refund_source_id}"

    _record_entry(
        wallet=sender_wallet,
        kind=WalletEntry.Kind.RELEASE,
        amount_minor=hold.amount_minor,
        currency=hold.currency,
        key=f"{base_key}:release:{hold.id}",
        source=refund_source,
        source_id=refund_source_id,
        note=note or f"Release for refund #{hold.id}",
    )
    _record_entry(
        wallet=sender_wallet,
        kind=WalletEntry.Kind.REFUND,
        amount_minor=-hold.amount_minor,
        currency=hold.currency,
        key=f"{base_key}:refund:{hold.id}",
        source=refund_source,
        source_id=refund_source_id,
        note=note or f"Refund for hold #{hold.id}",
    )

    hold.status = Hold.Status.REVERSED
    hold.closed_at = timezone.now()
    hold.save(update_fields=["status", "closed_at"])
    return hold


def list_entries(wallet: Wallet, limit: int = 50) -> Iterable[WalletEntry]:
    return wallet.entries.all()[:limit]
