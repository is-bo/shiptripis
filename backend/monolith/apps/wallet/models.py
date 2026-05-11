"""Wallet schema — append-only ledger, balance computed from entries.

Per CLAUDE.md §6 + ARCHITECTURE.md §11:

- Wallet has NO stored balance column. Balance is `SUM(entries.amount_minor)`
  for that wallet+currency. Append-only means entries are never UPDATEd or
  DELETEd — a correction is a NEW entry with the opposing sign.
- Each entry has a `kind` (deposit, hold, release, payout, refund, fee,
  adjustment) and a signed `amount_minor` (negative = debit, positive =
  credit). Every entry has an idempotency `key` so the same upstream event
  can't credit twice (G6 + payment-webhook replays).
- A Wallet is scoped to (user, currency). Same user with DZD + EUR wallets
  is two separate rows.

Escrow shape (driven by `apps.payments` events):
  payment.captured  → deposit + hold on sender wallet
  handover.confirmed → release on sender hold + payout to traveler
  payment.refunded  → refund on sender wallet (and reverse-hold if held)

Withdrawal is a separate path; sender/traveler can request a payout to
their bank/card. V1 only models the request schema; the actual disbursement
is a manual ops action.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models


class Wallet(models.Model):
    """One row per (user, currency). Balance is computed, not stored."""

    class Currency(models.TextChoices):
        DZD = "DZD", "Algerian Dinar"
        EUR = "EUR", "Euro"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="wallets",
    )
    currency = models.CharField(max_length=3, choices=Currency.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "wallet_wallet"
        ordering = ["user_id", "currency"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "currency"], name="wallet_unique_user_currency"
            ),
        ]

    def __str__(self) -> str:
        return f"Wallet user={self.user_id} {self.currency}"


class WalletEntry(models.Model):
    """Append-only ledger entry.

    `amount_minor` is SIGNED — positive = credit (money in), negative =
    debit (money out). The wallet's available balance is the sum of all
    non-hold entries; the on-hold balance is the sum of all OPEN hold
    entries minus matched releases.

    `key` is the idempotency key — `(wallet, key)` is unique so replays
    can't double-credit. The format is `<source>:<source_id>:<purpose>`,
    e.g. `payment:42:deposit`, `payment:42:hold`, `handover:7:release`.
    """

    class Kind(models.TextChoices):
        DEPOSIT = "deposit", "Deposit"
        HOLD = "hold", "Hold (escrow start)"
        RELEASE = "release", "Hold release"
        PAYOUT = "payout", "Payout (to other wallet)"
        REFUND = "refund", "Refund (to provider)"
        FEE = "fee", "Platform fee"
        ADJUSTMENT = "adjustment", "Manual adjustment"

    wallet = models.ForeignKey(
        Wallet, on_delete=models.PROTECT, related_name="entries"
    )
    kind = models.CharField(max_length=12, choices=Kind.choices)
    amount_minor = models.BigIntegerField(
        help_text="Signed. + = credit, - = debit. Integer minor units."
    )
    currency = models.CharField(max_length=3, choices=Wallet.Currency.choices)
    key = models.CharField(
        max_length=128,
        help_text="Idempotency key, unique per wallet: <source>:<id>:<purpose>.",
    )
    # Free-form linkage to whichever domain row drove this entry. Keep loose
    # so we can attach a payment, refund, handover, etc. without N FKs.
    source = models.CharField(max_length=24, blank=True, default="")
    source_id = models.BigIntegerField(null=True, blank=True)

    note = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "wallet_entry"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["wallet", "-created_at"], name="wallet_entry_wallet_idx"),
            models.Index(fields=["source", "source_id"], name="wallet_entry_source_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["wallet", "key"], name="wallet_entry_unique_key"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.kind} {self.amount_minor:+d}{self.currency} wallet={self.wallet_id}"


class Hold(models.Model):
    """Tracks an escrow hold for cross-referencing with releases.

    A Hold is opened when payment captures (sender's funds locked for the
    Offer) and is closed when the handover confirms (release) or when the
    payment refunds (reverse-hold).

    Holds are derived state — the source of truth is the matching pair of
    `WalletEntry` rows. This model just lets us query "which holds are still
    open" without a heavy aggregate.
    """

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        RELEASED = "released", "Released"
        REVERSED = "reversed", "Reversed (refund)"

    wallet = models.ForeignKey(
        Wallet, on_delete=models.PROTECT, related_name="holds"
    )
    amount_minor = models.PositiveBigIntegerField()
    currency = models.CharField(max_length=3, choices=Wallet.Currency.choices)

    # Loose linkage — see WalletEntry.source/source_id rationale.
    source = models.CharField(max_length=24)
    source_id = models.BigIntegerField()

    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.OPEN, db_index=True
    )
    opened_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "wallet_hold"
        ordering = ["-opened_at"]
        indexes = [
            models.Index(fields=["wallet", "status"], name="wallet_hold_wallet_idx"),
            models.Index(fields=["source", "source_id"], name="wallet_hold_source_idx"),
        ]
        constraints = [
            # One hold per (source, source_id) — e.g. one hold per payment intent.
            models.UniqueConstraint(
                fields=["source", "source_id"], name="wallet_hold_unique_source"
            ),
        ]

    def __str__(self) -> str:
        return f"Hold {self.amount_minor}{self.currency} {self.source}:{self.source_id} ({self.status})"


class Withdrawal(models.Model):
    """A user-requested payout from their wallet to an external destination.

    V1: schema + create endpoint only. Operations team disburses manually
    (Stripe Transfer, Edahabia transfer, bank wire). When disbursed, ops
    sets `status = sent` which writes a debit WalletEntry.
    """

    class Status(models.TextChoices):
        REQUESTED = "requested", "Requested"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    class Destination(models.TextChoices):
        BANK = "bank", "Bank transfer"
        CARD = "card", "Card payout"
        EDAHABIA = "edahabia", "Edahabia"
        STRIPE = "stripe", "Stripe payout"

    wallet = models.ForeignKey(
        Wallet, on_delete=models.PROTECT, related_name="withdrawals"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="withdrawals",
    )
    amount_minor = models.PositiveBigIntegerField()
    currency = models.CharField(max_length=3, choices=Wallet.Currency.choices)
    destination = models.CharField(max_length=12, choices=Destination.choices)
    destination_ref = models.CharField(
        max_length=128, blank=True, default="", help_text="IBAN / card last 4 / etc."
    )
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.REQUESTED, db_index=True
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "wallet_withdrawal"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "-created_at"], name="wallet_wd_user_idx"),
            models.Index(fields=["status"], name="wallet_wd_status_idx"),
        ]

    def __str__(self) -> str:
        return f"Withdrawal {self.amount_minor}{self.currency} {self.destination} ({self.status})"
