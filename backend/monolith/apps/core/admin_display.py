"""Presentation helpers shared by the operations admin.

Two problems these solve, both of them operational rather than cosmetic.

**Money.** Every amount in this system is stored as an integer number of euro
cents, because that is the only representation that cannot drift. Listing that
integer raw is correct and unreadable: a refund queue that reads
``3750 3000 750`` makes a hundred-fold misread a normal-Tuesday mistake, and
the consequence of that misread is a wrong refund. These helpers render the
stored integer as ``€37.50`` and nothing else — the value is not recomputed,
converted, summed or rounded anywhere on the way to the page. The column keeps
sorting on the underlying integer field.

**Status.** A queue is scanned, not read. A status word set in the same
typeface as the row around it does not survive scanning, so statuses render as
a chip carrying the word *and* a tone. Colour is the second signal, never the
only one: the word is always present, which is what makes the chip safe for an
operator who cannot distinguish the tones.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from django.contrib import admin
from django.utils.html import format_html

# Tones are named for what an operator should do about the row, not for a
# colour, so a status can be re-toned without a rename. They resolve to the
# ShipTrip semantic palette in `static/shiptrip/admin.css`.
TONE_OK = "ok"          # terminal-good: paid, delivered, approved, completed
TONE_WAIT = "wait"      # time is passing and nobody is blocked
TONE_ATTENTION = "attn"  # a human has to do something
TONE_BAD = "bad"        # failed, cancelled, refunded-against
TONE_INFO = "info"      # neutral, informational
TONE_MUTE = "mute"      # inert: draft, expired, historical

#: Status values seen across the marketplace, mapped to the tone that says what
#: an operator should do about a row in that state. Anything unlisted falls back
#: to `TONE_MUTE`, which is the honest answer for "this is not a queue signal".
STATUS_TONES: dict[str, str] = {
    # terminal-good
    "succeeded": TONE_OK,
    "paid": TONE_OK,
    "completed": TONE_OK,
    "approved": TONE_OK,
    "verified": TONE_OK,
    "delivered": TONE_OK,
    "confirmed": TONE_OK,
    "resolved": TONE_OK,
    "closed": TONE_OK,
    "active": TONE_OK,
    "released": TONE_OK,
    "funded": TONE_OK,
    "dispatched": TONE_OK,
    # in flight, nobody blocked
    "pending": TONE_WAIT,
    "processing": TONE_WAIT,
    "running": TONE_WAIT,
    "in_progress": TONE_WAIT,
    "scheduled": TONE_WAIT,
    "awaiting_payment": TONE_WAIT,
    "eligible": TONE_WAIT,
    "submitted": TONE_WAIT,
    "open": TONE_WAIT,
    # someone has to act
    "requires_action": TONE_ATTENTION,
    "manual": TONE_ATTENTION,
    "manual_required": TONE_ATTENTION,
    "needs_review": TONE_ATTENTION,
    "under_review": TONE_ATTENTION,
    "retrying": TONE_ATTENTION,
    "unapplied": TONE_ATTENTION,
    "frozen": TONE_ATTENTION,
    "disputed": TONE_ATTENTION,
    # gone wrong
    "failed": TONE_BAD,
    "cancelled": TONE_BAD,
    "canceled": TONE_BAD,
    "rejected": TONE_BAD,
    "expired": TONE_BAD,
    "revoked": TONE_BAD,
    "refunded": TONE_BAD,
    "banned": TONE_BAD,
    # inert
    "draft": TONE_MUTE,
    "unsubmitted": TONE_MUTE,
    "none": TONE_MUTE,
    "": TONE_MUTE,
}


def format_eur(cents: int | None) -> str:
    """Render stored euro cents as a euro amount. Integer arithmetic only."""

    if cents is None:
        return "—"
    value = int(cents)
    sign = "-" if value < 0 else ""
    whole, remainder = divmod(abs(value), 100)
    return f"{sign}€{whole:,}.{remainder:02d}"


def money(field: str, label: str | None = None, *, emphasis: bool = False):
    """A sortable list column that shows `field` (euro cents) as an amount.

    `emphasis` marks the one amount on a row that carries the financial
    consequence — the total a refund would move, the amount a payout would
    send — so it is not read at the same weight as its components.
    """

    css = "st-money st-money-lead" if emphasis else "st-money"

    @admin.display(description=label or field.replace("_eur_cents", "").replace("_", " "), ordering=field)
    def column(self, obj: Any) -> str:  # noqa: ANN001 - Django admin signature
        return format_html('<span class="{}">{}</span>', css, format_eur(getattr(obj, field, None)))

    column.__name__ = f"{field}_display"
    return column


def money_of(getter: Callable[[Any], int | None], label: str, *, emphasis: bool = False):
    """As `money`, for a derived amount that is not a stored column."""

    css = "st-money st-money-lead" if emphasis else "st-money"

    @admin.display(description=label)
    def column(self, obj: Any) -> str:  # noqa: ANN001
        return format_html('<span class="{}">{}</span>', css, format_eur(getter(obj)))

    return column


def tone_for(value: object) -> str:
    return STATUS_TONES.get(str(value or "").strip().lower(), TONE_MUTE)


def status(field: str, label: str | None = None, *, tones: dict[str, str] | None = None):
    """A sortable list column that shows `field` as a toned status chip."""

    lookup = {**STATUS_TONES, **(tones or {})}

    @admin.display(description=label or field.replace("_", " "), ordering=field)
    def column(self, obj: Any) -> str:  # noqa: ANN001
        raw = getattr(obj, field, None)
        display = getattr(obj, f"get_{field}_display", None)
        text = display() if callable(display) else raw
        if text in (None, ""):
            return format_html('<span class="st-chip st-mute">—</span>')
        tone = lookup.get(str(raw or "").strip().lower(), TONE_MUTE)
        return format_html('<span class="st-chip st-{}">{}</span>', tone, text)

    column.__name__ = f"{field}_chip"
    return column


def flag(
    field: str,
    label: str,
    *,
    true_tone: str = TONE_ATTENTION,
    false_tone: str = TONE_MUTE,
    true_text: str = "Yes",
    false_text: str = "No",
):
    """A boolean shown as a chip, because `True` in a queue is not a signal.

    Defaults to the attention tone for `True`: the booleans worth a column on
    these models are the ones that mean *stop and look* — payout frozen,
    manual action required, funds unapplied. `false_tone` exists for the
    inverted case, where it is the *absence* that an operator must notice: an
    unverified provider signature is the alarming state, not the verified one.
    """

    @admin.display(description=label, boolean=False, ordering=field)
    def column(self, obj: Any) -> str:  # noqa: ANN001
        raised = bool(getattr(obj, field, False))
        return format_html(
            '<span class="st-chip st-{}">{}</span>',
            true_tone if raised else false_tone,
            true_text if raised else false_text,
        )

    column.__name__ = f"{field}_chip"
    return column


def basis_points(field: str, label: str):
    """Render a stored basis-point rate as the percentage an operator reads.

    Commission is configured in basis points because that is what the money
    code multiplies by. `750` on a settings page is a number an operator has to
    translate before they can sanity-check it, and translation under time
    pressure is where a factor-of-ten mistake comes from.
    """

    @admin.display(description=label, ordering=field)
    def column(self, obj: Any) -> str:  # noqa: ANN001
        raw = getattr(obj, field, None)
        if raw is None:
            return "—"
        whole, remainder = divmod(int(raw), 100)
        # Formatted before it reaches `format_html`: that helper escapes every
        # argument into a SafeString first, and a SafeString has no integer
        # format codes.
        return format_html('<span class="st-money">{}%</span>', f"{whole:,}.{remainder:02d}")

    column.__name__ = f"{field}_display"
    return column
