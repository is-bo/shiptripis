"""Handover: issue, reveal, rotate and verify Deal pickup and delivery codes.

Every rule the specification locks about handover is enforced here, and the two
that matter most are enforced structurally rather than by convention:

**The traveler never reads a delivery code.** There is no argument to
`reveal_code` that yields one to them. `_assert_can_reveal` refuses any actor
who is not the Deal's sender, before the seal is ever opened, and the API layer
exposes no other route to the plaintext. The traveler's only interaction with a
code is `submit_code`, which takes a candidate and returns a boolean outcome.

**The delivery code does not exist for anybody during the safety buffer.** It is
created `buffered` with a stored `available_at`, and `release_delivery_code` is
the only transition out of that state. It compares against the stored instant
under a row lock, so an early job, a clock skew or a retry cannot shorten the
window -- and because the recipient's email is armed *by* that same transition,
"the code was revealed early" and "the recipient was emailed early" are the same
impossible event rather than two separate risks.

Everything enters through `lock_deal_lifecycle`, so handover rows are always
taken after the Deal, never before it. That is the specific defect in the legacy
`apps.verification` path, which locks `HandoverCode` and then `Match`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.financial_locks import LockedLifecycleAggregate, lock_deal_lifecycle
from apps.core.phase4_policy import HandoverPolicy, phase4_policy
from apps.deals import lifecycle
from apps.deals.models import Deal, DealEvent

from .codes import (
    format_code,
    generate_code,
    hash_code,
    code_matches,
    normalize_code,
    seal_code,
    unseal_code,
)
from .models import DealHandoverCode, HandoverAttempt, HandoverCodeAccess

logger = logging.getLogger(__name__)


class HandoverError(RuntimeError):
    """A handover operation was refused. Carries a stable machine code."""

    code = "handover_error"

    def __init__(self, message: str, *, code: str | None = None, **details):
        super().__init__(message)
        if code:
            self.code = code
        self._details = details

    def details(self) -> dict:
        return dict(self._details)


class NotAuthorized(HandoverError):
    code = "not_authorized"


#: The one message a failed submission may produce. Every rejection reason that
#: depends on the submitted value -- wrong code, wrong length, wrong alphabet --
#: collapses into this, so the endpoint cannot be used to narrow a search.
_UNIFORM_REJECTION = "That code is not valid for this delivery."


@dataclass(frozen=True, slots=True)
class RevealedCode:
    code: str
    formatted: str
    kind: str
    available_at: datetime | None
    rotation: int


@dataclass(frozen=True, slots=True)
class SubmissionResult:
    deal_id: int
    kind: str
    status: str
    changed: bool


#: The documented seeds, used when neither the Deal's own snapshot nor the
#: active settings revision can supply a handover policy.
#:
#: This is not a convenience. Phase 4's degradation contract says a settings
#: revision that predates it must still be able to take payments -- and a Deal
#: is funded and issued its pickup code in the same transaction, so a policy
#: lookup that raised here would turn "the operator rolled settings back" into
#: "no payment can be funded". Falling back keeps the 30-minute buffer and the
#: attempt caps in force, which is the conservative reading rather than an
#: absent one.
DEFAULT_HANDOVER_POLICY = HandoverPolicy(
    delivery_code_buffer_seconds=1_800,
    code_length=8,
    max_failed_attempts=5,
    attempt_lockout_seconds=900,
    max_lockouts=3,
    attempt_window_seconds=3_600,
    max_attempts_per_window=12,
)


def _live_handover_policy() -> HandoverPolicy:
    from apps.core.business_settings import NoActiveBusinessSettings
    from apps.core.phase4_policy import InvalidPhase4Policy

    try:
        return phase4_policy().handover
    except (InvalidPhase4Policy, NoActiveBusinessSettings):
        logger.warning(
            "handover.phase4_policy_unavailable; documented defaults apply"
        )
        return DEFAULT_HANDOVER_POLICY


def _policy_for(deal: Deal) -> HandoverPolicy:
    """Attempt limits for one Deal, from its frozen snapshot where possible.

    A Deal funded under a Phase 4 revision carries its own limits. Anything
    older falls back to the live policy, and to the documented defaults if even
    that is unavailable, so an attempt budget always exists.
    """

    snapshot = (deal.lifecycle_policy or {}).get("handover")
    if isinstance(snapshot, dict):
        try:
            return HandoverPolicy(
                delivery_code_buffer_seconds=lifecycle.lifecycle_value(
                    deal, "delivery_code_buffer_seconds", 1_800
                ),
                code_length=int(snapshot["code_length"]),
                max_failed_attempts=int(snapshot["max_failed_attempts"]),
                attempt_lockout_seconds=int(snapshot["attempt_lockout_seconds"]),
                max_lockouts=int(snapshot["max_lockouts"]),
                attempt_window_seconds=int(snapshot["attempt_window_seconds"]),
                max_attempts_per_window=int(snapshot["max_attempts_per_window"]),
            )
        except (KeyError, TypeError, ValueError):
            logger.warning(
                "handover.policy_snapshot_unreadable deal=%s; using live policy",
                deal.pk,
            )
    return _live_handover_policy()


# --- issuing ------------------------------------------------------------------


def _issue(
    *,
    deal: Deal,
    kind: str,
    length: int,
    status: str,
    available_at: datetime | None,
    rotation: int,
    actor_id: int | None = None,
) -> DealHandoverCode:
    """Create one code row. The plaintext exists only inside this function."""

    plaintext = generate_code(length)
    row = DealHandoverCode.objects.create(
        deal=deal,
        kind=kind,
        status=status,
        code_hash=hash_code(deal_id=deal.pk, kind=kind, code=plaintext),
        sealed_code=seal_code(deal_id=deal.pk, kind=kind, code=plaintext),
        code_length=length,
        available_at=available_at,
        released_at=(
            timezone.now() if status == DealHandoverCode.Status.ACTIVE else None
        ),
        issued_to_id=deal.sender_id,
        rotation=rotation,
    )
    # `plaintext` goes out of scope here. Nothing logs it, publishes it or
    # writes it to a timeline payload; the only way back to it is the seal.
    del plaintext
    return row


def ensure_pickup_code(
    deal: Deal, *, actor_id: int | None = None
) -> DealHandoverCode:
    """The sender's pickup code, created when the Deal is funded. Idempotent.

    Called from `fund_deal` while the Deal aggregate is held, so this is a plain
    insert after the Deal in the lock order. A duplicate call loses the race on
    `handover_one_live_code_per_kind` and returns the winner's row.
    """

    existing = (
        DealHandoverCode.objects.filter(
            deal_id=deal.pk,
            kind=DealHandoverCode.Kind.PICKUP,
            status__in=DealHandoverCode.LIVE_STATUSES,
        )
        .order_by("-pk")
        .first()
    )
    if existing is not None:
        return existing
    policy = _policy_for(deal)
    try:
        with transaction.atomic():
            row = _issue(
                deal=deal,
                kind=DealHandoverCode.Kind.PICKUP,
                length=policy.code_length,
                status=DealHandoverCode.Status.ACTIVE,
                available_at=None,
                rotation=1,
                actor_id=actor_id,
            )
    except IntegrityError:
        return DealHandoverCode.objects.get(
            deal_id=deal.pk,
            kind=DealHandoverCode.Kind.PICKUP,
            status__in=DealHandoverCode.LIVE_STATUSES,
        )
    lifecycle.record_event(
        deal,
        DealEvent.Kind.PICKUP_CODE_ISSUED,
        {"code_id": row.pk, "rotation": row.rotation},
        actor_id=actor_id,
    )
    return row


def arm_delivery_code(
    aggregate: LockedLifecycleAggregate, *, actor_id: int | None = None
) -> DealHandoverCode:
    """Create the delivery code in its buffered state, at pickup confirmation.

    The code material is generated now and sealed now, but the row is
    `buffered`: no reveal path will open it and no notification references it
    until `release_delivery_code` promotes it. Generating early and gating on
    state is deliberate -- it means the release transition is a state change on
    an existing row rather than a creation that could partially fail 30 minutes
    later, with the parcel already delivered and nobody able to prove anything.
    """

    deal = aggregate.deal
    if deal.delivery_code_available_at is None:
        raise HandoverError(
            "The delivery-code window has not been armed on this deal.",
            code="delivery_code_not_armed",
        )
    existing = aggregate.code(DealHandoverCode.Kind.DELIVERY)
    if existing is not None:
        return existing
    policy = _policy_for(deal)
    row = _issue(
        deal=deal,
        kind=DealHandoverCode.Kind.DELIVERY,
        length=policy.code_length,
        status=DealHandoverCode.Status.BUFFERED,
        available_at=deal.delivery_code_available_at,
        rotation=1,
        actor_id=actor_id,
    )
    return row


# --- releasing ----------------------------------------------------------------


def release_delivery_code(*, deal_id: int, at: datetime | None = None) -> str:
    """Promote the buffered delivery code and arm the recipient's email.

    The durable `delivery_code_release` job calls this, and so does any reveal
    attempt that arrives after the window has elapsed but before the worker has
    run -- so a stopped worker delays nothing except the email, and a worker
    that runs twice changes nothing the second time.

    Both effects commit together. There is no ordering in which the sender can
    see the code and the recipient's obligation does not exist, or the reverse.
    """

    at = at or timezone.now()
    with transaction.atomic():
        aggregate = lock_deal_lifecycle(deal_id)
        deal = aggregate.deal
        if deal.status not in lifecycle.IN_CARRIAGE_STATUSES:
            # The precise condition rather than a list of closed statuses that
            # has to be kept in step with three others. `disputed` is the case
            # a list kept missing: a Deal disputed while in carriage can never
            # return to carriage, so the release must stop here rather than
            # promote a code and then have the transition refuse it -- which
            # rolled back correctly but retried twenty-four times and finally
            # raised an ERROR alert for behaviour that was right all along.
            return "deal_not_in_carriage"
        if deal.delivery_code_released_at is not None:
            return "already_released"
        if deal.delivery_code_available_at is None:
            return "not_armed"
        if at < deal.delivery_code_available_at:
            raise HandoverError(
                "The delivery-code safety window has not elapsed.",
                code="delivery_code_buffer_open",
                delivery_code_available_at=(
                    deal.delivery_code_available_at.isoformat()
                ),
            )

        code = aggregate.code(DealHandoverCode.Kind.DELIVERY)
        if code is None:
            code = arm_delivery_code(aggregate)
        if code.status == DealHandoverCode.Status.BUFFERED:
            code.status = DealHandoverCode.Status.ACTIVE
            code.released_at = at
            code.save(update_fields=["status", "released_at", "updated_at"])

        lifecycle.apply_delivery_code_released(aggregate, at=at)
        _arm_recipient_notification(aggregate, code)
    return "released"


def _arm_recipient_notification(
    aggregate: LockedLifecycleAggregate, code: DealHandoverCode
) -> None:
    """Record the obligation to email the recipient their code.

    The plaintext is not put into the message. `secret_ref` names the sealed
    row and the outbox opens it at render time, so the code is never at rest in
    the notification table, never in the in-app inbox, and never in the
    published-event audit -- which stores only a payload hash anyway.
    """

    from apps.notifications.models import OutboundMessage
    from apps.notifications.outbox import enqueue_message

    deal = aggregate.deal
    recipient = aggregate.recipient
    if recipient is None:
        # Should be unreachable: the recipient is required before pickup. If it
        # ever happens the sender still has the code and can pass it on, so the
        # right response is a loud log rather than blocking the release.
        logger.error(
            "handover.release_without_recipient deal=%s code=%s", deal.pk, code.pk
        )
        return
    message = enqueue_message(
        kind=OutboundMessage.Kind.RECIPIENT_DELIVERY_CODE,
        key=f"recipient_delivery_code:{deal.pk}:{code.pk}",
        to_email=recipient.email,
        deal_id=deal.pk,
        secret_ref=f"handover_code:{code.pk}",
        language=recipient.communication_language,
        context={
            "recipient_name": recipient.full_name,
            "deal_reference": f"ST-{deal.pk}",
            # Leave a missing name blank so the final renderer can translate
            # its own "Your sender" fallback in the snapshotted locale.
            "sender_name": getattr(deal.sender, "full_name", ""),
        },
        max_attempts=12,
    )
    lifecycle.record_event(
        deal,
        DealEvent.Kind.RECIPIENT_NOTIFICATION_QUEUED,
        {"message_id": message.pk, "code_id": code.pk},
    )

    # The sender is told in the same breath. Without this the only signal that
    # the window has closed is the sender happening to reopen the app, and the
    # recipient would hold a code the sender does not yet know exists.
    sender_email = getattr(deal.sender, "email", "")
    if sender_email:
        enqueue_message(
            kind=OutboundMessage.Kind.DELIVERY_CODE_RELEASED,
            key=f"delivery_code_released:{deal.pk}:{code.pk}",
            to_email=sender_email,
            recipient_user_id=deal.sender_id,
            deal_id=deal.pk,
            context={"deal_reference": f"ST-{deal.pk}"},
        )


# --- revealing ----------------------------------------------------------------


def _assert_can_reveal(
    aggregate: LockedLifecycleAggregate, *, kind: str, actor_id: int, at: datetime
) -> DealHandoverCode:
    """Authorization and state, in that order, before any seal is opened."""

    deal = aggregate.deal
    if actor_id != deal.sender_id:
        # The traveler is refused here for the delivery code and for the pickup
        # code alike. There is no branch below that could ever return a
        # plaintext to them.
        raise NotAuthorized("Only the sender can view a handover code.")

    code = aggregate.code(kind)
    if code is None:
        raise HandoverError(
            "There is no active code of this kind for this delivery.",
            code="code_not_available",
            deal_status=deal.status,
        )
    if kind == DealHandoverCode.Kind.PICKUP:
        if deal.pickup_confirmed_at is not None:
            raise HandoverError(
                "Pickup has already been confirmed for this delivery.",
                code="pickup_already_confirmed",
            )
        if deal.status not in lifecycle.PRE_PICKUP_STATUSES:
            raise HandoverError(
                "The pickup code is available once the delivery is funded.",
                code="deal_not_funded",
                deal_status=deal.status,
            )
        return code

    # Delivery code. This is the branch the 30-minute rule protects.
    if code.status == DealHandoverCode.Status.BUFFERED or (
        code.available_at is not None and at < code.available_at
    ):
        raise HandoverError(
            "The delivery code is inside its safety window.",
            code="delivery_code_buffer_open",
            delivery_code_available_at=(
                code.available_at.isoformat() if code.available_at else None
            ),
        )
    if deal.delivery_confirmed_at is not None:
        raise HandoverError(
            "Delivery has already been confirmed.",
            code="delivery_already_confirmed",
        )
    return code


def reveal_code(*, deal_id: int, kind: str, actor_id: int) -> RevealedCode:
    """Return the plaintext to the sender. The only human-facing unseal path.

    If the buffer has elapsed but no worker has released the code yet, the
    release runs first, inside this call. Handing the sender their code and
    arming the recipient's email stay a single committed transition either way.
    """

    at = timezone.now()
    with transaction.atomic():
        aggregate = lock_deal_lifecycle(deal_id)
        deal = aggregate.deal
        if actor_id != deal.sender_id:
            raise NotAuthorized("Only the sender can view a handover code.")
        if (
            kind == DealHandoverCode.Kind.DELIVERY
            and deal.delivery_code_released_at is None
            and deal.delivery_code_available_at is not None
            and at >= deal.delivery_code_available_at
        ):
            code = aggregate.code(DealHandoverCode.Kind.DELIVERY)
            if code is None:
                code = arm_delivery_code(aggregate)
            if code.status == DealHandoverCode.Status.BUFFERED:
                code.status = DealHandoverCode.Status.ACTIVE
                code.released_at = at
                code.save(update_fields=["status", "released_at", "updated_at"])
            lifecycle.apply_delivery_code_released(aggregate, at=at)
            _arm_recipient_notification(aggregate, code)
            aggregate = lock_deal_lifecycle(deal_id)

        code = _assert_can_reveal(aggregate, kind=kind, actor_id=actor_id, at=at)
        plaintext = unseal_code(
            deal_id=code.deal_id, kind=code.kind, sealed=code.sealed_code
        )
        HandoverCodeAccess.objects.create(
            code=code,
            deal_id=code.deal_id,
            purpose=HandoverCodeAccess.Purpose.SENDER_REVEAL,
            actor_id=actor_id,
        )
    return RevealedCode(
        code=plaintext,
        formatted=format_code(plaintext),
        kind=code.kind,
        available_at=code.available_at,
        rotation=code.rotation,
    )


def rotate_code(*, deal_id: int, kind: str, actor_id: int) -> RevealedCode:
    """Replace a code the sender can no longer use.

    Real deliveries need this: a recipient loses the email, a lockout has to be
    cleared, a code is read out to the wrong person. Rotation supersedes the old
    row and issues a new one in the same transaction, so the two can never both
    open the handover, and a rotated delivery code re-arms the recipient's email
    under a new idempotency key rather than silently leaving them with a code
    that no longer works.
    """

    at = timezone.now()
    with transaction.atomic():
        aggregate = lock_deal_lifecycle(deal_id)
        deal = aggregate.deal
        if actor_id != deal.sender_id:
            raise NotAuthorized("Only the sender can rotate a handover code.")
        if kind == DealHandoverCode.Kind.PICKUP:
            if deal.pickup_confirmed_at is not None:
                raise HandoverError(
                    "Pickup has already been confirmed for this delivery.",
                    code="pickup_already_confirmed",
                )
            if deal.status not in lifecycle.PRE_PICKUP_STATUSES:
                raise HandoverError(
                    "The pickup code is available once the delivery is funded.",
                    code="deal_not_funded",
                    deal_status=deal.status,
                )
        else:
            if deal.delivery_confirmed_at is not None:
                raise HandoverError(
                    "Delivery has already been confirmed.",
                    code="delivery_already_confirmed",
                )
            if deal.status not in lifecycle.IN_CARRIAGE_STATUSES:
                # A refunded or cancelled Deal has no delivery left to make.
                # Without this the sender could still mint a live code and the
                # platform would email a third party a code for a delivery
                # that no longer exists. The pickup branch has always checked
                # its own statuses; this branch never did.
                raise HandoverError(
                    "This delivery is no longer active.",
                    code="deal_not_in_carriage",
                    deal_status=deal.status,
                )
            if (
                deal.delivery_code_available_at is None
                or at < deal.delivery_code_available_at
            ):
                # Rotating inside the buffer would be a way to ask for a code
                # early. It is refused for exactly the same reason revealing is.
                raise HandoverError(
                    "The delivery code is inside its safety window.",
                    code="delivery_code_buffer_open",
                    delivery_code_available_at=(
                        deal.delivery_code_available_at.isoformat()
                        if deal.delivery_code_available_at
                        else None
                    ),
                )

        previous = aggregate.code(kind)
        rotation = (previous.rotation + 1) if previous is not None else 1
        if previous is not None:
            previous.status = DealHandoverCode.Status.SUPERSEDED
            previous.superseded_at = at
            previous.save(update_fields=["status", "superseded_at", "updated_at"])
        row = _issue(
            deal=deal,
            kind=kind,
            length=_policy_for(deal).code_length,
            status=DealHandoverCode.Status.ACTIVE,
            available_at=(
                deal.delivery_code_available_at
                if kind == DealHandoverCode.Kind.DELIVERY
                else None
            ),
            rotation=rotation,
            actor_id=actor_id,
        )
        lifecycle.record_event(
            deal,
            (
                DealEvent.Kind.PICKUP_CODE_ROTATED
                if kind == DealHandoverCode.Kind.PICKUP
                else DealEvent.Kind.DELIVERY_CODE_ROTATED
            ),
            {
                "code_id": row.pk,
                "rotation": rotation,
                "superseded_code_id": previous.pk if previous else None,
            },
            actor_id=actor_id,
        )
        if kind == DealHandoverCode.Kind.DELIVERY:
            aggregate = lock_deal_lifecycle(deal_id)
            _arm_recipient_notification(aggregate, row)
        plaintext = unseal_code(deal_id=deal.pk, kind=kind, sealed=row.sealed_code)
        HandoverCodeAccess.objects.create(
            code=row,
            deal_id=deal.pk,
            purpose=HandoverCodeAccess.Purpose.SENDER_REVEAL,
            actor_id=actor_id,
        )
    return RevealedCode(
        code=plaintext,
        formatted=format_code(plaintext),
        kind=kind,
        available_at=row.available_at,
        rotation=rotation,
    )


# --- verifying ----------------------------------------------------------------


def _record_attempt(
    *, deal_id: int, kind: str, actor_id: int | None, result: str, code_id: int | None
) -> None:
    HandoverAttempt.objects.create(
        deal_id=deal_id,
        code_id=code_id,
        kind=kind,
        actor_id=actor_id,
        result=result,
    )


def _window_attempts(*, deal_id: int, kind: str, since: datetime) -> int:
    return HandoverAttempt.objects.filter(
        deal_id=deal_id, kind=kind, created_at__gte=since
    ).count()


def submit_code(
    *, deal_id: int, kind: str, actor_id: int, submitted_code: str
) -> SubmissionResult:
    """The traveler's only interaction with a code.

    Takes a candidate, answers with an outcome. Every refusal -- wrong code,
    wrong state, rate limited, wrong actor -- records its attempt row and then
    defers the exception until after the transaction commits. Raising inside the
    block would roll back the very audit row that records the refusal, which is
    the one record most worth keeping when somebody is probing a handover.
    """

    at = timezone.now()
    failure: HandoverError | None = None
    result: SubmissionResult | None = None

    with transaction.atomic():
        aggregate = lock_deal_lifecycle(deal_id)
        deal = aggregate.deal
        policy = _policy_for(deal)

        if actor_id != deal.traveler_id:
            _record_attempt(
                deal_id=deal_id,
                kind=kind,
                actor_id=actor_id,
                result=HandoverAttempt.Result.NOT_AUTHORIZED,
                code_id=None,
            )
            # Deferred, not raised here. Raising inside the transaction would
            # roll back the very audit row that records somebody probing a
            # handover they are not party to -- which is the one attempt most
            # worth keeping.
            failure = NotAuthorized("Only the traveler can submit a handover code.")
        elif (
            _window_attempts(
                deal_id=deal_id,
                kind=kind,
                since=at - timedelta(seconds=policy.attempt_window_seconds),
            )
            >= policy.max_attempts_per_window
        ):
            _record_attempt(
                deal_id=deal_id,
                kind=kind,
                actor_id=actor_id,
                result=HandoverAttempt.Result.RATE_LIMITED,
                code_id=None,
            )
            failure = HandoverError(
                "Too many attempts. Try again later.",
                code="handover_rate_limited",
                retry_after_seconds=policy.attempt_window_seconds,
            )
        elif not _deal_accepts(deal, kind):
            _record_attempt(
                deal_id=deal_id,
                kind=kind,
                actor_id=actor_id,
                result=HandoverAttempt.Result.WRONG_STATE,
                code_id=None,
            )
            failure = HandoverError(
                _state_refusal_message(kind),
                code=_state_refusal_code(deal, kind),
                deal_status=deal.status,
            )
        else:
            failure, result = _verify_against_live_code(
                aggregate=aggregate,
                kind=kind,
                actor_id=actor_id,
                submitted_code=submitted_code,
                policy=policy,
                at=at,
            )

    if failure is not None:
        raise failure
    assert result is not None
    return result


def _deal_accepts(deal: Deal, kind: str) -> bool:
    if kind == DealHandoverCode.Kind.PICKUP:
        # `pickup_ready` and not merely `funded`. The difference between the
        # two is exactly one thing: a recorded recipient. Accepting a pickup
        # without one would hand the parcel over and then discover, thirty
        # minutes later at release time, that the delivery code has nowhere to
        # go -- with the parcel already gone and nobody able to receive it.
        # The sender may still *see* their pickup code while merely funded;
        # what is gated here is the traveler's confirmation.
        return (
            deal.status == Deal.Status.PICKUP_READY
            and deal.pickup_confirmed_at is None
        )
    return (
        deal.status == Deal.Status.DELIVERY_READY
        and deal.delivery_code_released_at is not None
        and deal.delivery_confirmed_at is None
    )


def _state_refusal_code(deal: Deal, kind: str) -> str:
    if kind == DealHandoverCode.Kind.PICKUP:
        if deal.pickup_confirmed_at is not None:
            return "pickup_already_confirmed"
        if deal.status == Deal.Status.FUNDED:
            return "recipient_required"
        return "deal_not_pickup_ready"
    if deal.delivery_confirmed_at is not None:
        return "delivery_already_confirmed"
    if deal.pickup_confirmed_at is None:
        return "pickup_not_confirmed"
    return "delivery_code_buffer_open"


def _state_refusal_message(kind: str) -> str:
    if kind == DealHandoverCode.Kind.PICKUP:
        return "This delivery is not ready for a pickup code."
    return "This delivery is not ready for a delivery code."


def _verify_against_live_code(
    *,
    aggregate: LockedLifecycleAggregate,
    kind: str,
    actor_id: int,
    submitted_code: str,
    policy: HandoverPolicy,
    at: datetime,
) -> tuple[HandoverError | None, SubmissionResult | None]:
    deal = aggregate.deal
    code = aggregate.code(kind)
    if code is None or code.status != DealHandoverCode.Status.ACTIVE:
        _record_attempt(
            deal_id=deal.pk,
            kind=kind,
            actor_id=actor_id,
            result=HandoverAttempt.Result.NOT_AVAILABLE,
            code_id=code.pk if code else None,
        )
        return (
            HandoverError(
                "There is no code to check for this delivery right now.",
                code="code_not_available",
                deal_status=deal.status,
            ),
            None,
        )

    if code.locked_until is not None and code.locked_until > at:
        _record_attempt(
            deal_id=deal.pk,
            kind=kind,
            actor_id=actor_id,
            result=HandoverAttempt.Result.LOCKED,
            code_id=code.pk,
        )
        return (
            HandoverError(
                "This code is temporarily locked after too many failed attempts.",
                code="handover_code_locked",
                locked_until=code.locked_until.isoformat(),
            ),
            None,
        )

    normalized = normalize_code(submitted_code)
    if not code_matches(
        deal_id=deal.pk, kind=kind, code=normalized, code_hash=code.code_hash
    ):
        return _apply_failed_attempt(
            aggregate=aggregate,
            code=code,
            kind=kind,
            actor_id=actor_id,
            policy=policy,
            at=at,
        )

    return None, _apply_successful_submission(
        aggregate=aggregate, code=code, kind=kind, actor_id=actor_id, at=at
    )


def _apply_failed_attempt(
    *,
    aggregate: LockedLifecycleAggregate,
    code: DealHandoverCode,
    kind: str,
    actor_id: int,
    policy: HandoverPolicy,
    at: datetime,
) -> tuple[HandoverError, None]:
    deal = aggregate.deal
    code.failed_attempts = int(code.failed_attempts) + 1
    locked_until = None
    permanently_locked = False
    if code.failed_attempts >= policy.max_failed_attempts:
        code.failed_attempts = 0
        code.lockout_count = int(code.lockout_count) + 1
        if code.lockout_count >= policy.max_lockouts:
            # The attempt budget is exhausted. Only a sender rotation issues a
            # usable code again, which puts a human back in the loop rather
            # than letting an automated guesser wait out one more lockout.
            code.status = DealHandoverCode.Status.LOCKED
            permanently_locked = True
        else:
            locked_until = at + timedelta(seconds=policy.attempt_lockout_seconds)
            code.locked_until = locked_until
    code.save(
        update_fields=[
            "failed_attempts",
            "lockout_count",
            "locked_until",
            "status",
            "updated_at",
        ]
    )
    _record_attempt(
        deal_id=deal.pk,
        kind=kind,
        actor_id=actor_id,
        result=HandoverAttempt.Result.MISMATCH,
        code_id=code.pk,
    )
    lifecycle.record_event(
        deal,
        (
            DealEvent.Kind.PICKUP_CODE_FAILED
            if kind == DealHandoverCode.Kind.PICKUP
            else DealEvent.Kind.DELIVERY_CODE_FAILED
        ),
        {"code_id": code.pk, "lockout_count": int(code.lockout_count)},
        actor_id=actor_id,
    )
    if permanently_locked or locked_until is not None:
        lifecycle.record_event(
            deal,
            (
                DealEvent.Kind.PICKUP_CODE_LOCKED
                if kind == DealHandoverCode.Kind.PICKUP
                else DealEvent.Kind.DELIVERY_CODE_LOCKED
            ),
            {
                "code_id": code.pk,
                "permanent": permanently_locked,
                "locked_until": locked_until.isoformat() if locked_until else None,
            },
        )
    remaining = max(0, policy.max_failed_attempts - int(code.failed_attempts))
    return (
        HandoverError(
            _UNIFORM_REJECTION,
            code="handover_code_invalid",
            attempts_remaining=(0 if permanently_locked else remaining),
            locked_until=locked_until.isoformat() if locked_until else None,
            requires_new_code=permanently_locked,
        ),
        None,
    )


def _apply_successful_submission(
    *,
    aggregate: LockedLifecycleAggregate,
    code: DealHandoverCode,
    kind: str,
    actor_id: int,
    at: datetime,
) -> SubmissionResult:
    """Consume the code and advance the Deal, atomically and exactly once.

    Consumption and the transition share one transaction under one Deal lock, so
    a duplicate submission -- a retried request, two taps, two devices -- finds
    the code already `used` and is refused as `code_not_available` rather than
    running the side effects twice.
    """

    deal = aggregate.deal
    code.status = DealHandoverCode.Status.USED
    code.used_at = at
    code.used_by_id = actor_id
    code.failed_attempts = 0
    code.locked_until = None
    code.save(
        update_fields=[
            "status",
            "used_at",
            "used_by",
            "failed_attempts",
            "locked_until",
            "updated_at",
        ]
    )
    _record_attempt(
        deal_id=deal.pk,
        kind=kind,
        actor_id=actor_id,
        result=HandoverAttempt.Result.SUCCEEDED,
        code_id=code.pk,
    )

    if kind == DealHandoverCode.Kind.PICKUP:
        lifecycle.apply_pickup_confirmed(aggregate, actor_id=actor_id, at=at)
        arm_delivery_code(aggregate, actor_id=actor_id)
        lifecycle.schedule_delivery_code_release(deal)
        _notify_pickup_confirmed(aggregate)
    else:
        lifecycle.apply_delivery_confirmed(aggregate, actor_id=actor_id, at=at)
        lifecycle.schedule_protection_expiry(deal)
        lifecycle.schedule_rating_reveal(deal)
        _notify_delivery_confirmed(aggregate)

    return SubmissionResult(
        deal_id=deal.pk, kind=kind, status=deal.status, changed=True
    )


def _notify_pickup_confirmed(aggregate: LockedLifecycleAggregate) -> None:
    from apps.notifications.models import OutboundMessage
    from apps.notifications.outbox import enqueue_message

    deal = aggregate.deal
    sender_email = getattr(deal.sender, "email", "")
    if not sender_email:
        return
    enqueue_message(
        kind=OutboundMessage.Kind.PICKUP_CONFIRMED,
        key=f"pickup_confirmed:{deal.pk}",
        to_email=sender_email,
        recipient_user_id=deal.sender_id,
        deal_id=deal.pk,
        context={
            "deal_reference": f"ST-{deal.pk}",
            "buffer_minutes": max(
                1,
                lifecycle.lifecycle_value(deal, "delivery_code_buffer_seconds", 1_800)
                // 60,
            ),
        },
    )


def _notify_delivery_confirmed(aggregate: LockedLifecycleAggregate) -> None:
    from apps.notifications.models import OutboundMessage
    from apps.notifications.outbox import enqueue_message

    deal = aggregate.deal
    context = {
        "deal_reference": f"ST-{deal.pk}",
        "protection_ends_at": (
            deal.protection_ends_at.isoformat() if deal.protection_ends_at else ""
        ),
    }
    for user_id, email in (
        (deal.sender_id, getattr(deal.sender, "email", "")),
        (deal.traveler_id, getattr(deal.traveler, "email", "")),
    ):
        if not email:
            continue
        enqueue_message(
            kind=OutboundMessage.Kind.DELIVERY_CONFIRMED,
            key=f"delivery_confirmed:{deal.pk}:{user_id}",
            to_email=email,
            recipient_user_id=user_id,
            deal_id=deal.pk,
            context=context,
        )
        reminder_seconds = max(
            0,
            int(getattr(settings, "PROTECTION_ENDING_REMINDER_SECONDS", 86_400)),
        )
        if deal.protection_ends_at and reminder_seconds:
            reminder_at = deal.protection_ends_at - timedelta(
                seconds=reminder_seconds
            )
            if reminder_at > timezone.now():
                enqueue_message(
                    kind=OutboundMessage.Kind.PROTECTION_ENDING,
                    key=f"protection_ending:{deal.pk}:{user_id}:v1",
                    to_email=email,
                    recipient_user_id=user_id,
                    deal_id=deal.pk,
                    run_at=reminder_at,
                    context={
                        **context,
                        "reminder_seconds": reminder_seconds,
                    },
                )
        # The review window opens at the same moment, so the invitation goes
        # out with the confirmation rather than waiting for a separate sweep.
        enqueue_message(
            kind=OutboundMessage.Kind.RATING_AVAILABLE,
            key=f"rating_available:{deal.pk}:{user_id}",
            to_email=email,
            recipient_user_id=user_id,
            deal_id=deal.pk,
            context={
                "deal_reference": f"ST-{deal.pk}",
                "rating_window_ends_at": (
                    deal.rating_window_ends_at.isoformat()
                    if deal.rating_window_ends_at
                    else ""
                ),
            },
        )


# --- read model ---------------------------------------------------------------


def handover_state(*, deal: Deal, viewer_id: int, at: datetime | None = None) -> dict:
    """What each party may know about the codes, without ever being one.

    The sender is told whether a code can be revealed and when. The traveler is
    told whether a submission would be accepted and how many attempts remain.
    Neither projection contains code material, and the traveler's contains no
    availability instant they could use to time anything they should not.
    """

    at = at or timezone.now()
    is_sender = viewer_id == deal.sender_id
    is_traveler = viewer_id == deal.traveler_id
    codes = {
        row.kind: row
        for row in DealHandoverCode.objects.filter(
            deal_id=deal.pk, status__in=DealHandoverCode.LIVE_STATUSES
        ).order_by("pk")
    }
    pickup = codes.get(DealHandoverCode.Kind.PICKUP)
    delivery = codes.get(DealHandoverCode.Kind.DELIVERY)

    buffer_open = bool(
        deal.delivery_code_available_at is not None
        and at < deal.delivery_code_available_at
    )
    state = {
        "deal_status": deal.status,
        "pickup_confirmed_at": deal.pickup_confirmed_at,
        "delivery_code_available_at": deal.delivery_code_available_at,
        "delivery_code_released_at": deal.delivery_code_released_at,
        "delivery_confirmed_at": deal.delivery_confirmed_at,
        "in_delivery_code_buffer": buffer_open,
        "pickup": {
            "exists": pickup is not None,
            "status": pickup.status if pickup else None,
            "locked_until": pickup.locked_until if pickup else None,
            "rotation": pickup.rotation if pickup else None,
        },
        "delivery": {
            "exists": delivery is not None,
            # `buffered` is reported as such: the traveler learning that a code
            # exists but is not yet live tells them nothing they cannot already
            # read from the Deal status, and it is what the sender's countdown
            # is built from.
            "status": delivery.status if delivery else None,
            "locked_until": delivery.locked_until if delivery else None,
            "rotation": delivery.rotation if delivery else None,
        },
        "can_reveal_pickup_code": bool(
            is_sender
            and pickup is not None
            and pickup.status == DealHandoverCode.Status.ACTIVE
            and deal.pickup_confirmed_at is None
            and deal.status in lifecycle.PRE_PICKUP_STATUSES
        ),
        "can_reveal_delivery_code": bool(
            is_sender
            and delivery is not None
            and not buffer_open
            and deal.delivery_confirmed_at is None
            and deal.pickup_confirmed_at is not None
        ),
        # Stated explicitly and always false. It is a contract the client can
        # assert against, and a line a future change has to consciously edit.
        "traveler_can_view_delivery_code": False,
        "can_submit_pickup_code": bool(
            is_traveler and _deal_accepts(deal, DealHandoverCode.Kind.PICKUP)
        ),
        "can_submit_delivery_code": bool(
            is_traveler and _deal_accepts(deal, DealHandoverCode.Kind.DELIVERY)
        ),
    }
    return state
