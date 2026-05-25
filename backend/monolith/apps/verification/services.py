"""Verification write API — issue/verify/rotate HandoverCodes.

This is the single place that:
- generates 6-digit codes (server-side, cryptographically random)
- hashes them with argon2id
- flips Match.status forward on successful verify
- calls `apps.wallet.services.release_hold_to_payee` on delivery verify

No view talks to argon2 or the Hold table directly.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.core import channels, redis_bus
from apps.matching.models import Match, MatchEvent, Offer
from apps.payments.models import PaymentIntent
from apps.wallet.models import Hold
from apps.wallet.services import release_hold_to_payee

from .models import HandoverCode

_PH = PasswordHasher()
_MAX_ATTEMPTS = 5


@dataclass(frozen=True, slots=True)
class IssuedCode:
    code: str  # PLAINTEXT — shown ONCE to the issuer
    handover_id: int


def _gen_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def get_active_code(
    *,
    match: Match,
    kind: str,
    viewer: User,
) -> HandoverCode | None:
    """Return the current ACTIVE code for (match, kind) without rotating.

    Used by the sender's "view pickup code" screen — the code is auto-issued
    server-side on payment capture and the sender may reopen it any time
    until pickup. Returning the row (not plaintext) — plaintext is shown
    ONCE at issue; on re-view the mobile screen reads the same row that was
    in the `handover.code_issued` WS event payload.

    For V1 the viewer must be the party the code was issued to. Returning
    None covers both "no code yet" and "code already used/rotated".
    """
    if viewer not in (match.sender, match.traveler):
        return None
    return (
        HandoverCode.objects.filter(
            match=match, kind=kind, status=HandoverCode.Status.ACTIVE, issued_to=viewer
        )
        .order_by("-id")
        .first()
    )


@transaction.atomic
def issue_code(
    *,
    match: Match,
    kind: str,
    issued_to: User,
) -> IssuedCode:
    """Generate a fresh code and store its argon2 hash.

    If a previous ACTIVE code exists for (match, kind) it is ROTATED.
    Publishes `handover.code_issued` to both parties; the payload carries
    the plaintext code so the sender's app surfaces it without a separate
    fetch. This is V1 — the code is short-lived and rate-limited.
    """
    HandoverCode.objects.filter(
        match=match, kind=kind, status=HandoverCode.Status.ACTIVE
    ).update(status=HandoverCode.Status.ROTATED)

    code = _gen_code()
    row = HandoverCode.objects.create(
        match=match,
        kind=kind,
        code_hash=_PH.hash(code),
        issued_to=issued_to,
        status=HandoverCode.Status.ACTIVE,
    )
    redis_bus.publish_after_commit(
        channels.HANDOVER_CODE_ISSUED,
        {
            "match_id": match.id,
            "handover_id": row.id,
            "kind": kind,
            "code": code,
            "issued_to_id": issued_to.id,
        },
        targets=[match.sender_id, match.traveler_id],
    )
    return IssuedCode(code=code, handover_id=row.id)


class CodeInvalid(Exception):
    """Wrong code, or attempts exceeded."""


class CodeNotActive(Exception):
    """Code is used/locked/rotated."""


def verify_code(
    *,
    match: Match,
    kind: str,
    submitted_code: str,
    used_by: User,
) -> HandoverCode:
    """Verify the supplied code; on success mark USED and advance the match.

    Side effects on success:
      - pickup:   Match.status → in_transit
      - delivery: Match.status → delivered → completed, fires wallet release.

    Raises CodeInvalid on bad codes (after locking on too many attempts) or
    CodeNotActive if no active code exists.

    Note: NOT wrapped in @transaction.atomic at the outer scope so that an
    incorrect-code attempt can persist (attempts++ / LOCKED) even when we
    `raise CodeInvalid`. The success path uses an explicit inner atomic block.
    """
    row = (
        HandoverCode.objects.filter(
            match=match, kind=kind, status=HandoverCode.Status.ACTIVE
        )
        .order_by("-id")
        .first()
    )
    if row is None:
        raise CodeNotActive(f"No active {kind} code for match #{match.id}.")

    try:
        _PH.verify(row.code_hash, submitted_code)
    except VerifyMismatchError:
        row.attempts += 1
        if row.attempts >= _MAX_ATTEMPTS:
            row.status = HandoverCode.Status.LOCKED
        row.save(update_fields=["attempts", "status", "updated_at"])
        raise CodeInvalid("Wrong code.")

    with transaction.atomic():
        row.status = HandoverCode.Status.USED
        row.used_at = timezone.now()
        row.used_by = used_by
        row.save(update_fields=["status", "used_at", "used_by", "updated_at"])

        if kind == HandoverCode.Kind.PICKUP:
            _advance_match_to_in_transit(match)
        elif kind == HandoverCode.Kind.DELIVERY:
            _advance_match_to_delivered_and_release(match)

    return row


def _advance_match_to_in_transit(match: Match) -> None:
    if match.status != Match.Status.ACCEPTED:
        raise ValueError(
            f"Pickup verify requires match.status=accepted, got {match.status}."
        )
    match.status = Match.Status.IN_TRANSIT
    match.save(update_fields=["status", "updated_at"])
    MatchEvent.objects.create(
        match=match,
        kind=MatchEvent.Kind.MATCH_IN_TRANSIT,
        payload={"via": "handover_pickup"},
    )
    redis_bus.publish_after_commit(
        channels.MATCH_IN_TRANSIT,
        {"match_id": match.id, "sender_id": match.sender_id, "traveler_id": match.traveler_id},
        targets=[match.sender_id, match.traveler_id],
    )


def _advance_match_to_delivered_and_release(match: Match) -> None:
    """Delivery code verified → release escrow to traveler."""
    if match.status != Match.Status.IN_TRANSIT:
        raise ValueError(
            f"Delivery verify requires match.status=in_transit, got {match.status}."
        )

    accepted_offer = Offer.objects.get(
        match=match, status=Offer.Status.ACCEPTED
    )
    intent = PaymentIntent.objects.get(
        offer=accepted_offer, status=PaymentIntent.Status.SUCCEEDED
    )
    hold = Hold.objects.get(
        source="payment_intent",
        source_id=intent.id,
        status=Hold.Status.OPEN,
    )

    payee_amount = accepted_offer.base_amount_dzd
    fee = accepted_offer.commission_dzd + accepted_offer.base_fee_dzd

    release_hold_to_payee(
        hold=hold,
        payee=match.traveler,
        payee_amount_minor=payee_amount,
        platform_fee_minor=fee,
        release_source="handover_delivery",
        release_source_id=match.id,
    )

    match.status = Match.Status.COMPLETED
    match.save(update_fields=["status", "updated_at"])
    MatchEvent.objects.create(
        match=match,
        kind=MatchEvent.Kind.MATCH_COMPLETED,
        payload={"via": "handover_delivery"},
    )
    redis_bus.publish_after_commit(
        channels.MATCH_COMPLETED,
        {
            "match_id": match.id,
            "sender_id": match.sender_id,
            "traveler_id": match.traveler_id,
            "payee_amount_minor": payee_amount,
        },
        targets=[match.sender_id, match.traveler_id],
    )
