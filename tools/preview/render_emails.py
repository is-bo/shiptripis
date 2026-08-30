"""Render one representative message per transactional kind, for visual review.

Local review only. `resolve_secret` is stubbed here with a fixed sample string
so this script never touches real secret material — including the delivery
code, whose plaintext is opened only by the outbox itself at send time. What is
being reviewed is presentation; the secrecy guarantee is held by the tests in
`apps/notifications/tests/`, not by this file.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

from apps.notifications import outbox
from apps.notifications.models import OutboundMessage

OUT = Path("build/emailshots")
OUT.mkdir(parents=True, exist_ok=True)

Kind = OutboundMessage.Kind

REFERENCE = "SHP-4821-JIJ"

COMMON = {
    "deal_reference": REFERENCE,
    "origin_city": "Paris",
    "destination_city": "Jijel",
    "payment_reference": "PAY-9F2C-4471",
}

CASES: list[tuple[str, str, dict]] = [
    ("email-verification", Kind.EMAIL_VERIFICATION, {}),
    ("password-reset", Kind.PASSWORD_RESET, {}),
    (
        "admin-invitation",
        Kind.ADMIN_INVITATION,
        {"frontend_base_url": "https://ops.example", "role_label": "Finance operator"},
    ),
    ("recipient-delivery-code", Kind.RECIPIENT_DELIVERY_CODE, COMMON),
    ("pickup-confirmed", Kind.PICKUP_CONFIRMED, {**COMMON, "buffer_minutes": 30}),
    ("delivery-code-released", Kind.DELIVERY_CODE_RELEASED, COMMON),
    (
        "delivery-confirmed",
        Kind.DELIVERY_CONFIRMED,
        {**COMMON, "protection_ends_at": "31 August 2026, 18:40 CET"},
    ),
    ("protection-ended", Kind.PROTECTION_ENDED, COMMON),
    ("protection-ending", Kind.PROTECTION_ENDING, COMMON),
    (
        "dispute-opened",
        Kind.DISPUTE_OPENED,
        {**COMMON, "dispute_reference": "DSP-3E5D-32B6", "category": "Parcel damaged"},
    ),
    (
        "dispute-resolved",
        Kind.DISPUTE_RESOLVED,
        {
            **COMMON,
            "dispute_reference": "DSP-3E5D-32B6",
            "resolution": "Partial split",
        },
    ),
    ("rating-available", Kind.RATING_AVAILABLE, COMMON),
    ("payout-status", Kind.PAYOUT_STATUS, {**COMMON, "status": "eligible"}),
    ("deal-cancelled", Kind.DEAL_CANCELLED, {**COMMON, "reason": "Sender cancelled"}),
    (
        "kyc-status",
        Kind.KYC_STATUS,
        {"status": "rejected", "reason": "The document photo is cut off at the top."},
    ),
    (
        "flight-proof-status",
        Kind.FLIGHT_PROOF_STATUS,
        {"status": "approved", "reason": ""},
    ),
    ("payment-required", Kind.PAYMENT_REQUIRED, COMMON),
    ("payment-processing", Kind.PAYMENT_PROCESSING, COMMON),
    ("payment-failed", Kind.PAYMENT_FAILED, COMMON),
    ("payment-succeeded", Kind.PAYMENT_SUCCEEDED, COMMON),
    ("guest-payment", Kind.GUEST_PAYMENT, COMMON),
    ("refund-status", Kind.REFUND_STATUS, {**COMMON, "status": "processing"}),
    ("evidence-request", Kind.EVIDENCE_REQUEST, {**COMMON, "dispute_reference": "DSP-3E5D-32B6"}),
    (
        "security-event",
        Kind.SECURITY_EVENT,
        {"summary": "Your password was changed from a new device in Algiers."},
    ),
]

index = ["<h1>ShipTrip transactional email — rendered review</h1><ul>"]

with mock.patch.object(outbox, "resolve_secret", return_value="A7K2Q9"):
    for slug, kind, context in CASES:
        message = OutboundMessage(
            key=f"preview-{slug}",
            kind=kind,
            to_email="review@example.invalid",
            context=context,
        )
        subject, text, html = outbox.render_parts(message)
        (OUT / f"{slug}.html").write_text(html, encoding="utf-8")
        (OUT / f"{slug}.txt").write_text(
            f"Subject: {subject}\n\n{text}", encoding="utf-8"
        )
        index.append(
            f'<li><a href="{slug}.html">{slug}</a> — {subject} '
            f'(<a href="{slug}.txt">text</a>)</li>'
        )
        print(f"{slug:26} {len(html):6} bytes html   {len(text):5} bytes text")

index.append("</ul>")
(OUT / "index.html").write_text(
    '<meta charset="utf-8">' + "\n".join(index), encoding="utf-8"
)
(OUT / "manifest.json").write_text(
    json.dumps([slug for slug, _, _ in CASES], indent=2), encoding="utf-8"
)
print(f"\n{len(CASES)} documents written to {OUT}")
