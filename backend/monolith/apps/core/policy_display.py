"""Read the operationally important knobs out of a stored policy document.

The `policy` JSON on a settings revision is the whole commercial
configuration — around eighty keys, nested four deep, with durations in
seconds, rates in basis points and money in euro cents. Printed as a blob it is
technically complete and operationally useless: an operator checking "is the
protection window still 48 hours" has to find `payments.payout.protection_window_seconds`
inside it and divide by 3600, and dividing under time pressure is where a
factor-of-ten answer comes from.

Everything below **reads** stored values and renders them in the units an
operator thinks in. Nothing is recomputed, defaulted or inferred: a key that is
absent renders as "not set" rather than as a plausible number, because a
plausible number is the failure mode that matters here. The stored document
stays on the page underneath, and it remains the authority.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from apps.core.admin_display import format_eur

MISSING = "not set"


@dataclass(frozen=True)
class PolicyRow:
    label: str
    value: str
    #: Where the value came from, so the reading can be checked against the
    #: document rather than trusted.
    source: str
    tone: str = ""


def _dig(policy: dict, path: str) -> Any:
    node: Any = policy
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _duration(seconds: Any) -> str:
    """Seconds as the unit a person would say out loud."""

    if not isinstance(seconds, int) or isinstance(seconds, bool):
        return MISSING
    # Days only once a window is long enough that nobody counts it in hours.
    # The product says "48-hour protection" and "30-minute buffer", and an
    # operations page that answered "2 days" would be describing a different
    # rule in the operator's ear than the one the app and the site state.
    if seconds % 86_400 == 0 and seconds >= 7 * 86_400:
        days = seconds // 86_400
        return f"{days} day{'' if days == 1 else 's'} ({seconds:,} s)"
    if seconds % 3_600 == 0 and seconds >= 3_600:
        hours = seconds // 3_600
        return f"{hours} hour{'' if hours == 1 else 's'} ({seconds:,} s)"
    if seconds % 60 == 0 and seconds >= 60:
        minutes = seconds // 60
        return f"{minutes} minute{'' if minutes == 1 else 's'} ({seconds:,} s)"
    return f"{seconds:,} s"


def _percent(bps: Any) -> str:
    if not isinstance(bps, int) or isinstance(bps, bool):
        return MISSING
    whole, remainder = divmod(bps, 100)
    return f"{whole:,}.{remainder:02d}% ({bps:,} bps)"


def _money(cents: Any) -> str:
    if not isinstance(cents, int) or isinstance(cents, bool):
        return MISSING
    return format_eur(cents)


def _switch(value: Any) -> tuple[str, str]:
    if value is True:
        return "Enabled", "ok"
    if value is False:
        return "Disabled", "mute"
    return MISSING, "mute"


def _micros(value: Any) -> str:
    """A rate stored in millionths, shown as the rate it represents."""

    if not isinstance(value, int) or isinstance(value, bool):
        return MISSING
    whole, remainder = divmod(value, 1_000_000)
    return f"{whole:,}.{remainder:06d} ({value:,} micros)"


def policy_rows(
    policy: dict | None, *, commission_rate_bps: int | None
) -> list[PolicyRow]:
    """The knobs §12 of the operations brief names, in operator units."""

    policy = policy if isinstance(policy, dict) else {}
    rows: list[PolicyRow] = [
        PolicyRow("Commission", _percent(commission_rate_bps), "commission_rate_bps"),
        PolicyRow(
            "Posting deposit",
            _percent(_dig(policy, "payments.posting_deposit.percent_bps")),
            "payments.posting_deposit.percent_bps",
        ),
        PolicyRow(
            "Posting deposit floor",
            _money(_dig(policy, "payments.posting_deposit.min_eur_cents")),
            "payments.posting_deposit.min_eur_cents",
        ),
        PolicyRow(
            "Posting deposit ceiling",
            _money(_dig(policy, "payments.posting_deposit.max_eur_cents")),
            "payments.posting_deposit.max_eur_cents",
        ),
        PolicyRow(
            "Pricing floor per delivery",
            _money(_dig(policy, "pricing.global_floor_cents")),
            "pricing.global_floor_cents",
        ),
        PolicyRow(
            "Delivery-code buffer after pickup",
            _duration(_dig(policy, "handover.delivery_code_buffer_seconds")),
            "handover.delivery_code_buffer_seconds",
        ),
        PolicyRow(
            "Payout protection window",
            _duration(_dig(policy, "payments.payout.protection_window_seconds")),
            "payments.payout.protection_window_seconds",
        ),
        PolicyRow(
            "Payment grace after acceptance",
            _duration(_dig(policy, "reservation.payment_grace_seconds")),
            "reservation.payment_grace_seconds",
        ),
        PolicyRow(
            "Checkout attempt lifetime",
            _duration(_dig(policy, "payments.checkout.attempt_ttl_seconds")),
            "payments.checkout.attempt_ttl_seconds",
        ),
        PolicyRow(
            "Guest payment link lifetime",
            _duration(_dig(policy, "payments.guest.link_ttl_seconds")),
            "payments.guest.link_ttl_seconds",
        ),
        PolicyRow(
            "Sender free-cancellation cutoff",
            _duration(_dig(policy, "cancellation.sender_free_cutoff_seconds")),
            "cancellation.sender_free_cutoff_seconds",
        ),
        PolicyRow(
            "Late-cancellation compensation",
            _percent(_dig(policy, "cancellation.sender_late_compensation_bps")),
            "cancellation.sender_late_compensation_bps",
        ),
        PolicyRow(
            "Late-cancellation compensation cap",
            _money(_dig(policy, "cancellation.sender_late_compensation_cap_eur_cents")),
            "cancellation.sender_late_compensation_cap_eur_cents",
        ),
        PolicyRow(
            "Rating review window",
            _duration(_dig(policy, "ratings.review_window_seconds")),
            "ratings.review_window_seconds",
        ),
        PolicyRow(
            "Dispute evidence limit",
            (
                f"{_dig(policy, 'disputes.max_evidence_items')} items"
                if isinstance(_dig(policy, "disputes.max_evidence_items"), int)
                else MISSING
            ),
            "disputes.max_evidence_items",
        ),
        PolicyRow(
            "Chargily EUR→DZD rate",
            _micros(_dig(policy, "payments.chargily.eur_dzd_rate_micros")),
            "payments.chargily.eur_dzd_rate_micros",
        ),
    ]

    for label, path in (
        ("Boosts", "boost.enabled"),
        ("Stripe rail", "payments.providers.stripe_enabled"),
        ("Chargily rail", "payments.providers.chargily_enabled"),
        ("Automatic Stripe payouts", "payments.payout.auto_stripe_enabled"),
    ):
        text, tone = _switch(_dig(policy, path))
        rows.append(PolicyRow(label, text, path, tone))

    # The test rail is the one switch whose *enabled* state is the alarming
    # one. Production refuses to boot with it on; a revision that carries it is
    # worth seeing without reading the document.
    mock_text, _ = _switch(_dig(policy, "payments.providers.mock_enabled"))
    rows.append(
        PolicyRow(
            "Mock rail (tests and local only)",
            mock_text,
            "payments.providers.mock_enabled",
            "bad"
            if _dig(policy, "payments.providers.mock_enabled") is True
            else "mute",
        )
    )
    return rows


def boost_packages(policy: dict | None) -> Sequence[dict]:
    """Boost visibility packages; amount is chosen separately by the sender."""

    policy = policy if isinstance(policy, dict) else {}
    packages = _dig(policy, "boost.packages")
    if not isinstance(packages, list):
        return ()
    rendered = []
    for package in packages:
        if not isinstance(package, dict):
            continue
        rendered.append(
            {
                "code": package.get("code", "—"),
                "label": package.get("label", "—"),
                "duration": _duration(package.get("duration_seconds")),
                "weight": package.get("ranking_weight", "—"),
            }
        )
    return rendered
