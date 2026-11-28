"""Durable financial job handlers and the claim/run loop.

The scheduling contract is: the `ScheduledJob` row is the obligation. Redis may
make delivery prompt, but nothing here reads Redis, and a job that exists in
this table will run even if every cache and queue in the system is wiped.

Claiming uses `SELECT ... FOR UPDATE SKIP LOCKED` where the database supports
it, so several workers can share the queue without running the same job twice.
On SQLite (tests, local) the loop degrades to a plain locked read, which is
correct because there is only one writer.

Handlers must be idempotent in their own right. The lock stops concurrent runs;
idempotency is what makes a *retried* run safe, and every handler here is
written so a second execution is a no-op rather than a second refund.
"""

from __future__ import annotations

import logging
import os
import socket
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db import connection, models, transaction
from django.db.models import Case, F, Q, Value, When
from django.db.models.functions import Least
from django.utils import timezone

from apps.deals.models import Deal
from apps.core.financial_locks import lock_request_graph
from apps.parcels.models import DeliveryRequest, ParcelRequest

from .models import (
    OUTSTANDING,
    PaymentAttempt,
    PaymentOrder,
    PaymentProviderEvent,
    PaymentRefund,
    Payout,
    ScheduledJob,
)

logger = logging.getLogger(__name__)


class JobError(RuntimeError):
    """A classified, safe-to-store job failure."""

    code = "job_error"

    def __init__(self, message: str, *, code: str | None = None):
        super().__init__(message)
        if code:
            self.code = code


class RetryableJobError(JobError):
    """A transient failure that consumes the bounded retry budget."""

    code = "retryable_failure"


class PermanentJobError(JobError):
    """A failure that another identical execution cannot fix."""

    code = "permanent_failure"


class JobDeferred(RetryableJobError):
    """An expected wait that preserves both the obligation and retry budget."""

    code = "deferred"

    def __init__(
        self, message: str, *, code: str | None = None, delay: timedelta | None = None
    ):
        super().__init__(message, code=code)
        self.delay = delay or timedelta(hours=6)


# Backwards-compatible name for callers/tests that imported the original
# retryable exception.  New handlers should state their classification.
JobFailed = RetryableJobError


@dataclass(frozen=True, slots=True)
class JobRunReport:
    claimed: int
    succeeded: int
    deferred: int
    failed: int
    results: list[str]


def worker_identity() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"[:64]


# --- handlers ----------------------------------------------------------------


def handle_deposit_expiry_refund(payload: dict) -> str:
    """Refund a posting deposit when the request expired unmatched.

    Idempotent at three levels: the request is only expired once, the refund
    carries a stable idempotency key, and `request_refund` returns the existing
    row rather than raising when that key already exists. Running this handler
    ten times refunds once.
    """

    from .services import refund_order_in_full

    request_id = payload.get("delivery_request_id")
    if not isinstance(request_id, int):
        raise PermanentJobError(
            "deposit_expiry_refund needs an integer delivery_request_id.",
            code="invalid_payload",
        )

    with transaction.atomic():
        try:
            graph = lock_request_graph(request_id, include_negotiation=False)
        except DeliveryRequest.DoesNotExist:
            return "request_missing"
        request_row = graph.request.parcelrequest_ptr
        if request_row.status in (
            ParcelRequest.Status.MATCHED,
            ParcelRequest.Status.IN_TRANSIT,
            ParcelRequest.Status.DELIVERED,
            ParcelRequest.Status.COMPLETED,
        ):
            # It found a traveler. The deposit is credited into the deal
            # balance, not refunded.
            return "request_matched"
        if (
            request_row.deadline_at is not None
            and request_row.deadline_at > timezone.now()
        ):
            raise JobDeferred(
                "The request has not reached its deadline yet.",
                code="request_deadline_open",
                delay=request_row.deadline_at - timezone.now(),
            )
        if request_row.status == ParcelRequest.Status.OPEN:
            request_row.status = ParcelRequest.Status.EXPIRED
            request_row.save(update_fields=["status", "updated_at"])

        locked_orders = tuple(
            PaymentOrder.objects.select_for_update(no_key=True)
            .filter(delivery_request_id=request_id)
            .exclude(status=PaymentOrder.Status.CANCELLED)
            .order_by("pk")
        )

        from apps.boosts.services import close_request_boost

        # Expired unmatched: the unpaid Boost expires with the request.
        close_request_boost(delivery_request=graph.request)

        order = next(
            (
                row
                for row in locked_orders
                if row.purpose == PaymentOrder.Purpose.POSTING_DEPOSIT
            ),
            None,
        )
        if order is None:
            return "no_deposit_order"
        # `credited_into` is the reverse side of a self-referential one-to-one,
        # so it has no `_id` attribute; ask the queryset instead of the instance.
        if PaymentOrder.objects.filter(credit_source_id=order.pk).exists():
            return "deposit_already_credited"
        order_id = order.pk
        if int(order.paid_eur_cents) <= 0:
            from .services import cancel_order

            cancel_order(order_id=order_id, reason="deposit_expired_unpaid")
            return "deposit_unpaid_cancelled"

    refunds = refund_order_in_full(
        order_id=order_id,
        reason=PaymentRefund.Reason.DEPOSIT_EXPIRY,
    )
    return f"refunds_raised={len(refunds)}"


def handle_payment_grace_release(payload: dict) -> str:
    """Release a reservation whose payment grace lapsed.

    The database-backed sweep in `apps.deals.services` is the primary path; this
    job is the per-deal companion that arms at acceptance, so the obligation is
    recorded even if the sweep daemon is not running.
    """

    from apps.deals.services import release_pending_deal_reservation

    deal_id = payload.get("deal_id")
    if not isinstance(deal_id, int):
        raise PermanentJobError(
            "payment_grace_release needs an integer deal_id.", code="invalid_payload"
        )
    if not Deal.objects.filter(pk=deal_id).exists():
        return "deal_missing"
    result = release_pending_deal_reservation(
        deal_id=deal_id,
        reason="payment_grace_expired",
        require_expired=True,
    )
    return "released" if result.changed else "no_op"


def handle_attempt_expiry(payload: dict) -> str:
    """End a hosted checkout's attempt once its time is up.

    The attempt ends only once its provider confirms its checkout can take no
    payment (`expire_checkout_attempt`), so the order never opens a second
    checkout beside one that can still collect. While a payment is being made
    or settling through it, its settle job follows it to its outcome (G1).
    """

    from .providers import ProviderError
    from .services import CHECKOUT_OPENING_WINDOW, expire_checkout_attempt

    attempt_id = payload.get("attempt_id")
    if not isinstance(attempt_id, int):
        raise PermanentJobError(
            "attempt_expiry needs an integer attempt_id.", code="invalid_payload"
        )
    attempt = PaymentAttempt.objects.filter(pk=attempt_id).first()
    if attempt is None:
        return "attempt_missing"
    if attempt.status not in PaymentAttempt.OPEN_STATUSES:
        return "attempt_already_terminal"
    if attempt.expires_at is not None and attempt.expires_at > timezone.now():
        raise JobDeferred(
            "The attempt has not expired yet.",
            code="attempt_not_expired",
            delay=attempt.expires_at - timezone.now(),
        )
    try:
        result = expire_checkout_attempt(attempt_id=attempt_id)
    except ProviderError as exc:
        raise RetryableJobError(
            "The provider has not confirmed the checkout closed.", code=exc.code
        ) from exc
    if result == "attempt_opening":
        raise JobDeferred(
            "A request is still opening this checkout.",
            code="attempt_opening",
            delay=CHECKOUT_OPENING_WINDOW,
        )
    return result


def handle_provider_reconcile(payload: dict) -> str:
    """Settle one stored checkout: drive it to a fate its provider confirms (G1).

    Providers do not guarantee webhook delivery, so this reads the provider's
    own answer and records it through the path a webhook takes
    (`settle_checkout`). The job reports done only once the attempt is no
    longer `OUTSTANDING`: its checkout can take no further payment and any
    payment it reported is accounted for. Until then it is deferred, or
    retried while the provider answers nothing usable, and an outstanding
    attempt left without a pending settle job is armed again by the job loop
    (`arm_outstanding_attempts`). It never repeats a create.
    """

    from .providers import ProviderError
    from .services import (
        CHECKOUT_COLLECTING_POLL,
        CHECKOUT_OPENING_WINDOW,
        CHECKOUT_SETTLING_POLL,
        settle_checkout,
    )

    attempt_id = payload.get("attempt_id")
    if not isinstance(attempt_id, int):
        raise PermanentJobError(
            "provider_reconcile needs an integer attempt_id.", code="invalid_payload"
        )
    attempt = PaymentAttempt.objects.filter(pk=attempt_id).first()
    if attempt is None:
        return "attempt_missing"
    if not attempt.provider_session_id:
        # No checkout was ever stored for it, so its URL never left the server
        # and nobody could pay it.
        if attempt.status in PaymentAttempt.OPEN_STATUSES:
            raise JobDeferred(
                "The attempt's checkout is still being opened.",
                code="checkout_not_stored",
                delay=CHECKOUT_OPENING_WINDOW,
            )
        note = "checkout_never_handed_out"
    else:
        try:
            note = settle_checkout(attempt_id=attempt_id)
        except ProviderError as exc:
            # Unreachable or refused: the checkout's fate is still unknown, and
            # a payer may still hold its URL, so the obligation is kept.
            raise RetryableJobError(
                "The provider has not told what became of the checkout.",
                code=exc.code,
            ) from exc
    if note == "checkout_open":
        now = timezone.now()
        raise JobDeferred(
            "The checkout can still be paid.",
            code="checkout_open",
            delay=max(
                (attempt.expires_at or now + CHECKOUT_SETTLING_POLL) - now,
                timedelta(seconds=30),
            ),
        )
    if note == "checkout_settling":
        raise JobDeferred(
            "A payment through the checkout is settling.",
            code="checkout_settling",
            delay=CHECKOUT_SETTLING_POLL,
        )
    if note == "checkout_collecting":
        raise JobDeferred(
            "A payment is being made through the checkout.",
            code="checkout_collecting",
            delay=CHECKOUT_COLLECTING_POLL,
        )
    if note == "payment_held":
        # Money its provider reported is held: read again, with backoff, until
        # a verified report or the provider's read ends the hold, or staff
        # record what became of it.
        raise RetryableJobError(
            "A payment the provider reported is held.",
            code="payment_held",
        )
    if PaymentAttempt.objects.filter(OUTSTANDING, pk=attempt_id).exists():
        raise RetryableJobError(
            "The attempt is still outstanding.", code=f"outstanding_{note}"[:64]
        )
    return note


def handle_provider_event_process(payload: dict) -> str:
    """Re-drive a received provider event until its economic effect commits."""

    from .services import _mark_event_retryable, process_provider_event

    event_id = payload.get("event_id")
    if not isinstance(event_id, int):
        raise PermanentJobError(
            "provider_event_process needs an integer event_id.", code="invalid_payload"
        )
    if not PaymentProviderEvent.objects.filter(pk=event_id).exists():
        return "event_missing"
    try:
        return process_provider_event(event_id=event_id)
    except Exception as exc:
        _mark_event_retryable(event_id, exc)
        raise RetryableJobError(
            "Provider event application failed.",
            code=f"event_{type(exc).__name__}"[:64],
        ) from exc


def handle_refund_reconcile(payload: dict) -> str:
    """Drive or poll a non-terminal refund using its stable provider key."""

    from .services import _settle_refund_with_provider

    refund_id = payload.get("refund_id")
    if not isinstance(refund_id, int):
        raise PermanentJobError(
            "refund_reconcile needs an integer refund_id.", code="invalid_payload"
        )
    refund = PaymentRefund.objects.filter(pk=refund_id).first()
    if refund is None:
        return "refund_missing"
    if refund.status == PaymentRefund.Status.SUCCEEDED:
        return "already_succeeded"
    result = _settle_refund_with_provider(refund_id=refund_id)
    if result in {"provider_unavailable", "provider_pending"}:
        raise RetryableJobError(
            "Refund remains unresolved.", code=f"refund_{result}"[:64]
        )
    if result == "manual_action_required":
        # The refund row is now the explicit human obligation.  Exhausting a
        # second generic queue adds noise without improving recovery.
        return result
    return result


def handle_payout_release_check(payload: dict) -> str:
    """Re-evaluate one payout against the Phase 4 release gate.

    Armed at funding, when nobody yet knows when delivery will be confirmed, so
    it is the safety net rather than the primary trigger: `protection_expiry`
    is scheduled the moment the protection deadline exists and is what normally
    releases the money. This one exists so a Deal whose protection job was
    somehow lost still gets looked at.
    """

    from .payout_release import evaluate_payout_release

    payout_id = payload.get("payout_id")
    if not isinstance(payout_id, int):
        raise PermanentJobError(
            "payout_release_check needs an integer payout_id.", code="invalid_payload"
        )
    payout = Payout.objects.filter(pk=payout_id).first()
    if payout is None:
        return "payout_missing"
    if payout.status not in Payout.PRE_RELEASE_STATUSES:
        return f"payout_{payout.status}"
    result = evaluate_payout_release(
        deal_id=payout.deal_id, reason="payout_release_check"
    )
    if result in {
        "delivery_not_confirmed",
        "protection_not_armed",
        "protection_open",
        "scheduled_arrival_floor_open",
    }:
        # Armed at funding, when nobody knows when delivery will happen, this
        # job's first fire lands 48 hours later -- usually while the parcel is
        # still moving. Returning a string would mark the obligation
        # discharged and retire the safety net before it could ever help, which
        # is the whole reason it exists. Retry instead, like every other
        # early-fire handler here.
        raise JobDeferred(
            "Payout is not releasable yet.",
            code=f"payout_{result}"[:64],
            delay=_release_gate_delay(payout.deal_id),
        )
    return result


def _release_gate_delay(deal_id: int) -> timedelta | None:
    """How long until this Deal's payout gate can actually answer.

    Deterministic where the Deal knows the instant: the protection deadline, or
    the funded arrival floor when that is later. A genuinely early delivery can
    put the floor days out, and a generic backoff would take the whole lifecycle
    aggregate every few minutes for those days to be told "not yet" each time.

    `None` means "no instant is known" -- delivery has not been confirmed at all
    -- and `JobDeferred` then applies its own six-hour default.
    """

    from apps.deals.arrival import payout_release_gate_at

    deal = Deal.objects.filter(pk=deal_id).first()
    if deal is None:
        return None
    gate = payout_release_gate_at(deal)
    if gate is None:
        return None
    return max(gate - timezone.now(), timedelta(seconds=30)) + timedelta(seconds=1)


# --- Phase 4 lifecycle handlers ----------------------------------------------


def handle_delivery_code_release(payload: dict) -> str:
    """Release the delivery code exactly once, 30 minutes after pickup.

    This is the whole reason the job is a row rather than a timer: stop the
    worker, let the window pass, start it again, and the code becomes available
    and the recipient is emailed once - not zero times, not twice. The handler
    itself refuses to run early, so a job whose run_at was somehow moved
    forward cannot shorten the safety buffer.
    """

    from apps.handover.services import HandoverError, release_delivery_code

    deal_id = payload.get("deal_id")
    if not isinstance(deal_id, int):
        raise PermanentJobError(
            "delivery_code_release needs an integer deal_id.", code="invalid_payload"
        )
    if not Deal.objects.filter(pk=deal_id).exists():
        return "deal_missing"
    from apps.deals.lifecycle import DealLifecycleError

    try:
        return release_delivery_code(deal_id=deal_id)
    except DealLifecycleError as exc:
        # The Deal moved out from under the release -- disputed, cancelled or
        # settled. The transaction already rolled back, so nothing was
        # promoted and no email was armed. Retrying cannot change the answer,
        # so record it rather than exhausting the retry budget and raising an
        # ERROR alert for correct behaviour.
        return f"refused_{exc.code}"
    except HandoverError as exc:
        # `delivery_code_buffer_open` means this fired early. Retrying with
        # backoff is exactly right; the state check is the authority, not the
        # schedule.
        raise JobDeferred(
            "Delivery code release buffer is still open.",
            code=exc.code,
            delay=timedelta(minutes=1),
        ) from exc


def handle_protection_expiry(payload: dict) -> str:
    """Close the 48-hour protection window and decide the payout."""

    from .payout_release import evaluate_payout_release

    deal_id = payload.get("deal_id")
    if not isinstance(deal_id, int):
        raise PermanentJobError(
            "protection_expiry needs an integer deal_id.", code="invalid_payload"
        )
    if not Deal.objects.filter(pk=deal_id).exists():
        return "deal_missing"
    result = evaluate_payout_release(
        deal_id=deal_id, reason="protection_window_expired"
    )
    if result in {"protection_open", "scheduled_arrival_floor_open"}:
        # Fired before the gate. Retry rather than record a decision that has
        # not been earned yet -- and retry at the instant the gate opens, not on
        # a generic timer. `scheduled_arrival_floor_open` in particular can be
        # days away on a genuinely early delivery, and the release service has
        # already moved this job's `run_at` to the exact floor; the deferral
        # below agrees with it instead of overriding it with a shorter one.
        raise JobDeferred(
            "The payout release gate has not opened yet.",
            code=result,
            delay=_release_gate_delay(deal_id) or timedelta(minutes=15),
        )
    return result


def handle_rating_reveal(payload: dict) -> str:
    """Reveal both sides once the blind review window closes."""

    from apps.ratings.services import reveal_ratings_for_deal

    deal_id = payload.get("deal_id")
    if not isinstance(deal_id, int):
        raise PermanentJobError(
            "rating_reveal needs an integer deal_id.", code="invalid_payload"
        )
    if not Deal.objects.filter(pk=deal_id).exists():
        return "deal_missing"
    result = reveal_ratings_for_deal(deal_id=deal_id)
    if result == "not_due":
        # Fired early. `revealed_at` is only an audit stamp -- visibility is
        # recomputed from the window frozen on each rating -- but retiring the
        # obligation would mean the stamp is never written at all.
        raise JobDeferred(
            "The review window has not closed yet.",
            code="rating_window_open",
            delay=timedelta(minutes=15),
        )
    return result


def handle_outbound_message(payload: dict) -> str:
    """Carry one durable transactional message to the email transport."""

    from apps.notifications.outbox import dispatch_message

    message_id = payload.get("message_id")
    if not isinstance(message_id, int):
        raise PermanentJobError(
            "outbound_message needs an integer message_id.", code="invalid_payload"
        )
    try:
        result = dispatch_message(message_id=message_id)
    except Exception as exc:  # noqa: BLE001 - transport failures are retryable
        raise RetryableJobError(
            "Outbound message transport failed.",
            code=f"outbound_{type(exc).__name__}"[:64],
        ) from exc
    if result == "disabled":
        # Do not discharge the durable job while the operator kill switch is
        # active. The message row stays pending and the normal retry/sweep path
        # can carry it after an approved activation.
        raise JobDeferred(
            "Transactional email is disabled by the operator.",
            code="email_disabled",
            delay=timedelta(hours=6),
        )
    if result in {"activation_held", "rate_limited", "busy", "retry_wait", "awaiting_receipt"}:
        raise JobDeferred("Email delivery is waiting for its send gate.", code=f"email_{result}", delay=timedelta(minutes=1))
    return result


# --- Phase 8F-H3 automatic EUR payout execution ------------------------------


def _payout_execution_error(exc) -> str:
    """Translate a finance refusal into this loop's own vocabulary.

    The distinction that matters: an expected wait must not consume a payout's
    retry budget. "The protection window is still open", "the connected balance
    has not settled", "another worker holds this operation" and "execution is
    switched off" are all the system behaving correctly, and firing an incident
    for them would train an operator to ignore the queue.
    """

    from .payout_execution import PayoutBlocked, PayoutDeferred, PayoutUnresolved

    if isinstance(exc, PayoutDeferred):
        raise JobDeferred(str(exc), code=exc.code, delay=exc.delay) from exc
    if isinstance(exc, PayoutUnresolved):
        # Never retried by re-sending. The obligation and its reservation stand
        # until a person or a provider read establishes what happened.
        raise PermanentJobError(str(exc), code=exc.code) from exc
    if isinstance(exc, PayoutBlocked):
        return f"blocked_{exc.code}"[:255]
    raise exc


def handle_payout_execute(payload: dict) -> str:
    """Advance one Stripe EUR payout by exactly one external stage."""

    from .payout_execution import PayoutExecutionError, execute_payout

    payout_id = payload.get("payout_id")
    if not isinstance(payout_id, int):
        raise PermanentJobError(
            "payout_execute needs an integer payout_id.", code="invalid_payload"
        )
    payout = Payout.objects.filter(pk=payout_id).first()
    if payout is None:
        return "payout_missing"
    if payout.status in ("paid", "cancelled"):
        return f"payout_{payout.status}"
    try:
        return execute_payout(payout_id)
    except PayoutExecutionError as exc:
        return _payout_execution_error(exc)


def handle_payout_reconcile(payload: dict) -> str:
    """Ask Stripe what really happened to this payout's live operations.

    Runs whether or not execution is enabled. Turning off new instructions must
    never stop the system finding out what the existing ones did.
    """

    from .payout_reconciliation import reconcile_payout

    payout_id = payload.get("payout_id")
    if not isinstance(payout_id, int):
        raise PermanentJobError(
            "payout_reconcile needs an integer payout_id.", code="invalid_payload"
        )
    if not Payout.objects.filter(pk=payout_id).exists():
        return "payout_missing"
    result = reconcile_payout(payout_id)
    if "unavailable" in result:
        raise RetryableJobError(
            "Stripe was unavailable for reconciliation.", code="provider_unavailable"
        )
    return result[:255]


def handle_payout_account_refresh(payload: dict) -> str:
    """Re-read one connected account's authoritative readiness."""

    from .models import StripePayoutAccount
    from .payout_accounts import refresh_account
    from .providers.base import ProviderError, ProviderUnavailable

    account_id = payload.get("account_id")
    if not isinstance(account_id, int):
        raise PermanentJobError(
            "payout_account_refresh needs an integer account_id.",
            code="invalid_payload",
        )
    account = StripePayoutAccount.objects.filter(pk=account_id).first()
    if account is None:
        return "account_missing"
    try:
        _, applied = refresh_account(account)
    except ProviderUnavailable as exc:
        raise RetryableJobError(
            "Stripe readiness is temporarily unavailable.", code=exc.code
        ) from exc
    except ProviderError as exc:
        raise PermanentJobError(
            "Stripe refused the readiness refresh.", code=exc.code
        ) from exc
    return "refreshed" if applied else "superseded_by_newer_observation"


def handle_payout_sweep(payload: dict) -> str:
    """Bounded recovery pass over stranded payout work."""

    from .payout_sweeper import sweep_payouts

    report = sweep_payouts()
    return (
        f"execute={report['execute']} reconcile={report['reconcile']} "
        f"accounts={report['accounts']}"
    )[:255]


def handle_notification_dispatch(payload):
    from apps.notifications.transport import dispatch_event
    try:
        return dispatch_event(payload)
    except Exception:
        raise RetryableJobError("Notification transport unavailable.", code="notification_transport_unavailable") from None


def handle_discovery_route_alerts(payload: dict) -> str:
    """L2A. Notify route alerts about one newly listed trip or request."""

    from apps.discovery.alerts import handle_route_alert_fanout

    return handle_route_alert_fanout(payload)


def handle_leg_reminder(payload: dict) -> str:
    """L5A: "did you depart / arrive?" for a leg carrying a funded parcel."""

    from apps.trips.progress import handle_leg_reminder as run

    return run(payload)


def handle_schedule_change_settle(payload: dict) -> str:
    """L9A: apply a waiting schedule change once nothing blocks it any more."""

    from apps.trips.schedule_changes import handle_settle_job as run

    return run(payload)


def handle_offer_response_reminder(payload: dict) -> str:
    """L12A: remind the person who must answer a proposal before its deadline."""

    from apps.matching.offer_deadlines import handle_response_reminder as run

    return run(payload)


def handle_offer_expiry(payload: dict) -> str:
    """L12A: expire a proposal nobody answered by its deadline."""

    from apps.matching.offer_deadlines import handle_offer_expiry as run

    return run(payload)


def handle_admin_helper_call_prune(payload: dict) -> str:
    """L15: remove AI helper calls older than 30 days."""

    from apps.admin_helper.calls import handle_prune_job as run

    return run(payload)


def handle_admin_helper_action_expiry(payload: dict) -> str:
    """L16: a prepared change nobody confirmed in time stops waiting."""

    from apps.admin_helper.prepared import NotDue
    from apps.admin_helper.prepared import handle_expiry_job as run

    try:
        return run(payload)
    except NotDue as early:
        # Fired early: keep the obligation, like every other early handler.
        raise JobDeferred(str(early), code="prepared_action_not_due", delay=early.delay) from None


def handle_profile_photo_object_delete(payload: dict) -> str:
    """P3A: delete a stored profile photo once no photo row names it."""

    from apps.accounts.photos import handle_object_delete_job as run

    return run(payload)


HANDLERS = {
    ScheduledJob.Kind.NOTIFICATION_DISPATCH: handle_notification_dispatch,
    ScheduledJob.Kind.DEPOSIT_EXPIRY_REFUND: handle_deposit_expiry_refund,
    ScheduledJob.Kind.PAYMENT_GRACE_RELEASE: handle_payment_grace_release,
    ScheduledJob.Kind.ATTEMPT_EXPIRY: handle_attempt_expiry,
    ScheduledJob.Kind.PROVIDER_RECONCILE: handle_provider_reconcile,
    ScheduledJob.Kind.PROVIDER_EVENT_PROCESS: handle_provider_event_process,
    ScheduledJob.Kind.REFUND_RECONCILE: handle_refund_reconcile,
    ScheduledJob.Kind.PAYOUT_RELEASE_CHECK: handle_payout_release_check,
    ScheduledJob.Kind.DELIVERY_CODE_RELEASE: handle_delivery_code_release,
    ScheduledJob.Kind.PROTECTION_EXPIRY: handle_protection_expiry,
    ScheduledJob.Kind.RATING_REVEAL: handle_rating_reveal,
    ScheduledJob.Kind.OUTBOUND_MESSAGE: handle_outbound_message,
    ScheduledJob.Kind.PAYOUT_EXECUTE: handle_payout_execute,
    ScheduledJob.Kind.PAYOUT_RECONCILE: handle_payout_reconcile,
    ScheduledJob.Kind.PAYOUT_ACCOUNT_REFRESH: handle_payout_account_refresh,
    ScheduledJob.Kind.PAYOUT_SWEEP: handle_payout_sweep,
    ScheduledJob.Kind.DISCOVERY_ROUTE_ALERTS: handle_discovery_route_alerts,
    ScheduledJob.Kind.LEG_REMINDER: handle_leg_reminder,
    ScheduledJob.Kind.SCHEDULE_CHANGE_SETTLE: handle_schedule_change_settle,
    ScheduledJob.Kind.OFFER_RESPONSE_REMINDER: handle_offer_response_reminder,
    ScheduledJob.Kind.OFFER_EXPIRY: handle_offer_expiry,
    ScheduledJob.Kind.ADMIN_HELPER_CALL_PRUNE: handle_admin_helper_call_prune,
    ScheduledJob.Kind.ADMIN_HELPER_ACTION_EXPIRY: handle_admin_helper_action_expiry,
    ScheduledJob.Kind.PROFILE_PHOTO_OBJECT_DELETE: handle_profile_photo_object_delete,
}


# --- claim / run -------------------------------------------------------------


def _retry_delay(attempts: int) -> timedelta:
    """Exponential backoff, capped so a stuck job still retries daily."""

    return timedelta(seconds=min(60 * (2 ** max(0, attempts - 1)), 6 * 3_600))


def claim_due_jobs(*, limit: int, at: datetime | None = None) -> list[ScheduledJob]:
    """Atomically take up to `limit` due jobs for this worker."""

    at = at or timezone.now()
    if limit <= 0 or limit > 500:
        raise ValueError("Job claim limit must be between 1 and 500.")
    identity = worker_identity()
    claimed: list[ScheduledJob] = []
    with transaction.atomic():
        queryset = ScheduledJob.objects.filter(
            status=ScheduledJob.Status.PENDING, run_at__lte=at
        ).order_by("run_at", "id")
        if connection.features.has_select_for_update_skip_locked:
            queryset = queryset.select_for_update(no_key=True, skip_locked=True)
        else:
            queryset = queryset.select_for_update(no_key=True)
        rows = list(queryset[:limit])
        if rows:
            ScheduledJob.objects.filter(pk__in=[row.pk for row in rows]).update(
                status=ScheduledJob.Status.RUNNING,
                locked_at=at,
                locked_by=identity,
                updated_at=at,
            )
            claimed = list(ScheduledJob.objects.filter(pk__in=[r.pk for r in rows]))
    return claimed


def _already_satisfied_reason(job: ScheduledJob) -> str:
    """Return a safe reason when domain truth proves a failed job is obsolete."""

    payload = dict(job.payload or {})
    if job.kind in {
        ScheduledJob.Kind.ATTEMPT_EXPIRY,
        ScheduledJob.Kind.PROVIDER_RECONCILE,
    }:
        attempt_id = payload.get("attempt_id")
        if not isinstance(attempt_id, int):
            return ""
        attempt = PaymentAttempt.objects.filter(pk=attempt_id).first()
        if attempt is None:
            return "attempt_missing"
        if job.kind == ScheduledJob.Kind.ATTEMPT_EXPIRY:
            return (
                "attempt_already_terminal"
                if attempt.status not in PaymentAttempt.OPEN_STATUSES
                else ""
            )
        # Only a checkout that can take no payment, and whose reported payment
        # is accounted for, ends its settle job (G1).
        if PaymentAttempt.objects.filter(OUTSTANDING, pk=attempt.pk).exists():
            return ""
        if attempt.provider_session_id:
            return "checkout_final"
        return (
            "checkout_never_handed_out"
            if attempt.status not in PaymentAttempt.OPEN_STATUSES
            else ""
        )
    if job.kind == ScheduledJob.Kind.PROVIDER_EVENT_PROCESS:
        event_id = payload.get("event_id")
        if not isinstance(event_id, int):
            return ""
        event = PaymentProviderEvent.objects.filter(pk=event_id).first()
        if event is None:
            return "provider_event_missing"
        return (
            f"provider_event_{event.processing_result}"
            if event.processing_result
            in {
                PaymentProviderEvent.ProcessingResult.APPLIED,
                PaymentProviderEvent.ProcessingResult.IGNORED,
            }
            else ""
        )
    if job.kind == ScheduledJob.Kind.REFUND_RECONCILE:
        refund_id = payload.get("refund_id")
        if not isinstance(refund_id, int):
            return ""
        refund = PaymentRefund.objects.filter(pk=refund_id).first()
        if refund is None:
            return "refund_missing"
        return (
            "refund_already_succeeded"
            if refund.status == PaymentRefund.Status.SUCCEEDED
            else ""
        )
    if job.kind == ScheduledJob.Kind.PAYOUT_RELEASE_CHECK:
        payout_id = payload.get("payout_id")
        if not isinstance(payout_id, int):
            return ""
        payout = Payout.objects.filter(pk=payout_id).first()
        if payout is None:
            return "payout_missing"
        return (
            f"payout_{payout.status}"
            if payout.status not in Payout.PRE_RELEASE_STATUSES
            else ""
        )
    if job.kind == ScheduledJob.Kind.OUTBOUND_MESSAGE:
        from apps.notifications.models import OutboundMessage

        message_id = payload.get("message_id")
        if not isinstance(message_id, int):
            return ""
        message = OutboundMessage.objects.filter(pk=message_id).first()
        if message is None:
            return "outbound_message_missing"
        return (
            f"outbound_message_{message.status}"
            if message.status
            in {OutboundMessage.Status.DISPATCHED, OutboundMessage.Status.CANCELLED}
            else ""
        )
    return ""


def resolve_satisfied_failed_jobs(*, limit: int = 100) -> int:
    """Archive dead letters whose authoritative operation already completed."""

    if limit <= 0 or limit > 500:
        raise ValueError("Satisfied-job sweep limit must be between 1 and 500.")
    candidate_ids = list(
        ScheduledJob.objects.filter(status=ScheduledJob.Status.FAILED, resolution="")
        .order_by("completed_at", "pk")
        .values_list("pk", flat=True)[:limit]
    )
    resolved = 0
    for job_id in candidate_ids:
        with transaction.atomic():
            job = ScheduledJob.objects.select_for_update(no_key=True).get(pk=job_id)
            if job.status != ScheduledJob.Status.FAILED or job.resolution:
                continue
            reason = _already_satisfied_reason(job)
            if not reason:
                continue
            now = timezone.now()
            job.resolution = ScheduledJob.Resolution.SUPERSEDED
            job.resolved_at = now
            job.resolution_reason = reason
            job.save(
                update_fields=(
                    "resolution",
                    "resolved_at",
                    "resolution_reason",
                    "updated_at",
                )
            )
            resolved += 1
            logger.info(
                "finance.job_auto_resolved job=%s kind=%s reason=%s",
                job.pk,
                job.kind,
                reason,
            )
    return resolved


def _complete_run(
    job: ScheduledJob, *, status: str, run_at: datetime | None = None, **fields
) -> None:
    """Write the end of `job`'s run, only while its claim is still this run's (R4).

    Filtered on the `locked_at` its claim stamped: a run whose job was
    requeued (`requeue_stuck_jobs`) and claimed again writes nothing, so the
    newer claim's outcome stands. A wake recorded during the run, `run_at`
    later than the claim (`services._arm_checkout_settle`), is kept whatever
    the run answers: the job is pending again, due by the sooner of the two.
    """

    now = timezone.now()
    moment = models.DateTimeField()
    woken = Q(run_at__gt=F("locked_at"))
    due = F("run_at") if run_at is None else Value(run_at, output_field=moment)
    ended = (
        None
        if status == ScheduledJob.Status.PENDING
        else Case(
            When(woken, then=Value(None, output_field=moment)),
            default=Value(now, output_field=moment),
        )
    )
    written = ScheduledJob.objects.filter(
        pk=job.pk, status=ScheduledJob.Status.RUNNING, locked_at=job.locked_at
    ).update(
        status=Case(
            When(woken, then=Value(ScheduledJob.Status.PENDING)),
            default=Value(status),
        ),
        run_at=Case(When(woken, then=Least(F("run_at"), due)), default=due),
        completed_at=ended,
        last_attempt_at=now,
        locked_at=None,
        locked_by="",
        updated_at=now,
        **fields,
    )
    if not written:
        logger.warning("finance.job_claim_lost job=%s kind=%s", job.pk, job.kind)


def run_job(job: ScheduledJob) -> str:
    """Execute one claimed job and record its outcome. Never raises."""

    handler = HANDLERS.get(job.kind)
    if handler is None:
        _complete_run(
            job,
            status=ScheduledJob.Status.FAILED,
            attempts=int(job.attempts) + 1,
            last_error_code="handler_missing",
            last_error="No handler is registered for this job kind.",
        )
        logger.error("finance.job_no_handler job=%s kind=%s", job.pk, job.kind)
        return "no_handler"

    attempts = int(job.attempts) + 1
    try:
        result = handler(dict(job.payload or {}))
    except JobDeferred as exc:
        # A disabled kill switch or an authoritative time gate is not a
        # failure.  Keep the durable obligation live without consuming its
        # retry budget or raising a false incident.
        delay = max(exc.delay, timedelta(seconds=30))
        _complete_run(
            job,
            status=ScheduledJob.Status.PENDING,
            run_at=timezone.now() + delay,
            last_error_code="",
            last_error="",
            last_result=f"deferred:{exc.code}"[:255],
        )
        logger.info(
            "finance.job_deferred job=%s kind=%s code=%s",
            job.pk,
            job.kind,
            exc.code,
        )
        return "deferred"
    except PermanentJobError as exc:
        _complete_run(
            job,
            status=ScheduledJob.Status.FAILED,
            attempts=attempts,
            last_error_code=exc.code[:64],
            last_error=str(exc)[:500],
        )
        logger.error(
            "finance.job_terminal job=%s kind=%s key=%s attempts=%s code=%s",
            job.pk,
            job.kind,
            job.key,
            attempts,
            exc.code,
        )
        return "failed"
    except Exception as exc:  # noqa: BLE001 - a job must never kill the loop
        failed_permanently = attempts >= int(job.max_attempts)
        error_code = (
            exc.code
            if isinstance(exc, RetryableJobError)
            else f"unexpected_{type(exc).__name__}"
        )[:64]
        safe_message = (
            str(exc)[:500]
            if isinstance(exc, RetryableJobError)
            else f"Unexpected {type(exc).__name__} while running the handler."
        )
        _complete_run(
            job,
            status=(
                ScheduledJob.Status.FAILED
                if failed_permanently
                else ScheduledJob.Status.PENDING
            ),
            run_at=timezone.now() + _retry_delay(attempts),
            attempts=attempts,
            last_error_code=error_code,
            last_error=safe_message,
        )
        if failed_permanently:
            # The retry budget is gone. This is now a human obligation, not a
            # scheduling one — log it at error level so it reaches alerting
            # rather than sitting in a queue nobody reads.
            logger.error(
                "finance.job_exhausted job=%s kind=%s key=%s attempts=%s error=%s",
                job.pk,
                job.kind,
                job.key,
                attempts,
                error_code,
            )
        else:
            logger.warning(
                "finance.job_failed job=%s kind=%s attempts=%s error=%s",
                job.pk,
                job.kind,
                attempts,
                error_code,
            )
        return "failed"

    _complete_run(
        job,
        status=ScheduledJob.Status.SUCCEEDED,
        attempts=attempts,
        last_result=str(result)[:255],
        last_error_code="",
        last_error="",
        resolution="",
        resolved_at=None,
        resolved_by=None,
        resolution_reason="",
    )
    return str(result)


def _sweep_payout_backlog() -> None:
    """Re-arm payout work the ordinary paths lost, before claiming this batch.

    Deliberately in the loop rather than in a self-rescheduling job: a job that
    has to re-arm itself is exactly the thing that stops running when a worker
    dies mid-run, and this is the mechanism that is supposed to survive that.
    Every query behind it is a bounded page over an indexed predicate, so a
    deployment with no payout work pays three cheap lookups per cycle.
    """

    try:
        from .payout_sweeper import sweep_payouts

        sweep_payouts()
    except Exception:  # noqa: BLE001 - the sweep must never stop the job loop
        logger.exception("finance.payout_sweep_failed")


def _sweep_outstanding_attempts() -> None:
    """Give every outstanding attempt a pending settle job, before claiming this batch.

    In the loop for the reason `_sweep_payout_backlog` is: a checkout that may
    still take a payment, or a payment it reported that is held, must be
    followed to its fate even when the job that should have done so ran out
    of retries or was never armed (G1, R3). One bounded lookup per cycle.
    """

    try:
        from .services import arm_outstanding_attempts

        arm_outstanding_attempts()
    except Exception:  # noqa: BLE001 - the sweep must never stop the job loop
        logger.exception("finance.outstanding_attempt_sweep_failed")


def run_due_jobs(*, limit: int = 50, at: datetime | None = None) -> JobRunReport:
    """Claim and run every due job, up to `limit`."""

    resolve_satisfied_failed_jobs(limit=min(limit, 100))
    _sweep_payout_backlog()
    _sweep_outstanding_attempts()
    jobs = claim_due_jobs(limit=limit, at=at)
    results = [run_job(job) for job in jobs]
    failed = sum(1 for result in results if result in {"failed", "no_handler"})
    deferred = results.count("deferred")
    return JobRunReport(
        claimed=len(jobs),
        succeeded=len(results) - failed - deferred,
        deferred=deferred,
        failed=failed,
        results=results,
    )


def requeue_stuck_jobs(*, stale_after_seconds: int = 900) -> int:
    """Return jobs whose worker died mid-run to the pending queue."""

    cutoff = timezone.now() - timedelta(seconds=stale_after_seconds)
    return ScheduledJob.objects.filter(
        status=ScheduledJob.Status.RUNNING, locked_at__lt=cutoff
    ).update(
        status=ScheduledJob.Status.PENDING,
        locked_at=None,
        locked_by="",
        updated_at=timezone.now(),
    )
