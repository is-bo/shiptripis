"""What the helper may change, and how (spec 20.4, plan L16).

**The registry is the complete list.** An action not in `registry()` cannot be
done or prepared through the helper; `CONSOLE_POSTS` names the console page of
each, and `NEVER` the console POSTs the helper never reaches. Each entry names:

* its ``mode``: ``direct`` (runs at once: an internal note, acknowledging a
  problem) or ``prepared`` (stored for the admin to confirm on the console);
* the capabilities it needs, per target type (any of them, checked fresh);
* its parameters, which `parse` reads strictly (unknown keys, wrong types and
  missing values are refused);
* ``check``: the **console's own form validation and the console page's own
  "is this offered now" rule**, so the helper is refused what the console
  would refuse or not offer;
* ``basis``: the target's decision-relevant state, compared again at confirm;
* ``summary`` and ``details``: the server's own words for what will happen;
* ``run``: the **same function the console view calls**
  (`apps.admin_panel.staff_actions` or the domain service the view calls).
  No entry has a second implementation and none calls a model's ``save``.

The reason the action runs with fills the console form's own free-text field
(``reason`` or ``note``); for a refund, whose console reason is a reason code,
and a bank payout retry, which has none, it is kept in the audit metadata.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from functools import cache
from types import MappingProxyType

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError

from apps.admin_panel import staff_actions
from apps.admin_panel.models import AdminNote
from apps.admin_panel.permissions import has_all_admin_permissions
from apps.core.admin_display import format_eur
from apps.deals.models import Deal
from apps.disputes.models import Dispute
from apps.finance.models import PaymentAttempt, PaymentRefund, Payout, ScheduledJob
from apps.parcels import tracking
from apps.problems.models import ShipmentProblem
from apps.ratings.models import Rating, RatingModeration, RatingReport
from apps.trips.models import Journey

from .people import short_name

User = get_user_model()

DIRECT = "direct"
PREPARED = "prepared"
REASON_MAX_LENGTH = 500

# Refusal codes the API answers with.
INVALID = "admin_helper_action_invalid"
NOT_OFFERED = "admin_helper_action_not_offered"
FAILED = "admin_helper_action_failed"


class Refused(Exception):
    """The action cannot be taken as asked. ``message`` is for the admin."""

    def __init__(self, code: str, message: str, *, fields: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.fields = fields or {}


#: The domain refusals a `run` may raise. Their messages are written for staff
#: and are shown as they are; anything else is reported by its code only.
def _domain_errors() -> tuple[type[BaseException], ...]:
    from apps.deals.cancellation import CancellationError
    from apps.discovery.errors import DiscoveryError
    from apps.disputes.services import DisputeError
    from apps.finance.operations import FinanceOperationsError
    from apps.finance.payout_execution import PayoutExecutionError
    from apps.finance.providers import ProviderConfigurationInvalid
    from apps.finance.services import FinanceError
    from apps.locations.sea_crossings import SeaCrossingError
    from apps.problems.services import ProblemError
    from apps.ratings.moderation import ModerationError
    from apps.trips.services import JourneyDomainError

    return (
        staff_actions.StaffActionError,
        CancellationError,
        DiscoveryError,
        DisputeError,
        FinanceOperationsError,
        PayoutExecutionError,
        ProviderConfigurationInvalid,
        FinanceError,
        SeaCrossingError,
        ProblemError,
        ModerationError,
        JourneyDomainError,
        PermissionDenied,
        DjangoValidationError,
    )


def domain_errors() -> tuple[type[BaseException], ...]:
    return _domain_errors()


def refusal_of(exc: BaseException) -> Refused:
    """A domain error as the helper and the console report it."""

    code = getattr(exc, "code", "") or FAILED
    if isinstance(exc, PermissionDenied):
        return Refused("admin_helper_forbidden", "Your role does not allow this.")
    if isinstance(exc, DjangoValidationError):
        return Refused(code if isinstance(code, str) else FAILED, " ".join(exc.messages))
    return Refused(str(code), str(exc) or "This could not be done.")


# --- parameters -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Param:
    name: str
    #: ``text``, ``integer`` or ``choice``.
    type: str
    says: str
    required: bool = True
    choices: tuple[str, ...] = ()
    max_length: int | None = None
    minimum: int | None = None

    def describe(self) -> dict:
        shape = {"name": self.name, "type": self.type, "required": self.required, "says": self.says}
        if self.choices:
            shape["choices"] = list(self.choices)
        if self.max_length is not None:
            shape["max_length"] = self.max_length
        if self.minimum is not None:
            shape["minimum"] = self.minimum
        return shape

    def read(self, raw):
        if raw is None:
            if self.required:
                raise Refused(INVALID, f"params.{self.name} is required.", fields={self.name: "required"})
            return None
        if self.type == "integer":
            if isinstance(raw, bool) or not isinstance(raw, int):
                raise Refused(INVALID, f"params.{self.name} must be a whole number.", fields={self.name: "integer"})
            if self.minimum is not None and raw < self.minimum:
                raise Refused(INVALID, f"params.{self.name} must be at least {self.minimum}.", fields={self.name: "minimum"})
            return raw
        if not isinstance(raw, str):
            raise Refused(INVALID, f"params.{self.name} must be text.", fields={self.name: "text"})
        value = raw.strip()
        if self.required and not value:
            raise Refused(INVALID, f"params.{self.name} is required.", fields={self.name: "required"})
        if self.choices and value not in self.choices:
            raise Refused(
                INVALID,
                f"params.{self.name} must be one of: {', '.join(self.choices)}.",
                fields={self.name: "choice"},
            )
        if self.max_length is not None and len(value) > self.max_length:
            raise Refused(
                INVALID,
                f"params.{self.name} holds at most {self.max_length} characters.",
                fields={self.name: "max_length"},
            )
        return value


def _form(form_class, data: dict) -> dict:
    """The console's own form, bound to ``data``; its errors refuse the action."""

    form = form_class(data=data)
    if form.is_valid():
        return form.cleaned_data
    errors = {name: " ".join(str(error) for error in messages) for name, messages in form.errors.items()}
    raise Refused(INVALID, " ".join(errors.values()) or "These values are not valid.", fields=errors)


def _cents(value: int | None) -> Decimal | str:
    return "" if value is None else Decimal(value) / Decimal(100)


# --- the registry ----------------------------------------------------------------------


@dataclass(frozen=True)
class Action:
    code: str
    mode: str
    title: str
    #: Target type to the capabilities that allow the action on it (any of them).
    gates: dict[str, tuple[str, ...]]
    load: Callable[[str, int], object | None]
    #: ``(admin, obj, params, reason) -> cleaned params``. Raises `Refused`.
    check: Callable[..., dict]
    summary: Callable[[object, dict], str]
    #: ``(admin, obj, cleaned, reason, basis) -> what happened, in one sentence``.
    run: Callable[..., str]
    params: tuple[Param, ...] = ()
    basis: Callable[[object, dict], dict] = lambda obj, cleaned: {}
    details: Callable[[object, dict], list[tuple[str, str]]] = lambda obj, cleaned: []
    #: The cleaned values back from what was stored at preparation, for the
    #: console's list (parameters plus anything ``check`` added to the basis).
    restore: Callable[[dict, dict], dict] = lambda params, basis: dict(params)
    #: Said under the details on the confirm page, when they were computed again.
    fresh_note: str = ""
    #: Per-record authority beyond the capability (a job's kind decides who).
    allowed: Callable[[object, object], bool] | None = None
    #: The longest reason the console form's field takes.
    reason_max_length: int = REASON_MAX_LENGTH
    #: The console action has no free-text reason of its own (a refund's is a
    #: reason code; a bank payout retry has none), so the admin's typed
    #: reason is kept in the audit metadata as ``confirmed_reason``.
    reason_in_metadata: bool = False
    #: Locks, at confirm, the rows ``basis`` reads, in the same order the
    #: console's function locks them, so the record cannot change between the
    #: comparison and the run. ``None``: the function's own locks suffice.
    lock: Callable[[object], None] | None = None
    #: The task in `tasks.TASKS` that explains the same thing.
    task: str = ""
    #: Who may decide which records, when the capability alone does not say.
    who_decides: str = ""

    @property
    def target_types(self) -> tuple[str, ...]:
        return tuple(self.gates)

    def permitted(self, admin, target_type: str) -> bool:
        """The fresh check: the account is reloaded, so a downgrade, ban or
        deactivation applies to this very call."""

        return any(has_all_admin_permissions(admin, code) for code in self.gates.get(target_type, ()))

    def may_take(self, admin) -> bool:
        return any(self.permitted(admin, target_type) for target_type in self.gates)

    def parse(self, raw) -> dict:
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise Refused(INVALID, "params must be an object.")
        known = {param.name for param in self.params}
        unknown = sorted(set(raw) - known)
        if unknown:
            raise Refused(INVALID, f"Unknown params: {', '.join(unknown)}.", fields={name: "unknown" for name in unknown})
        return {param.name: param.read(raw.get(param.name)) for param in self.params}

    def describe(self, admin) -> dict:
        return {
            "code": self.code,
            "mode": self.mode,
            "does": self.title,
            "target_types": [t for t in self.gates if self.permitted(admin, t)],
            "params": [param.describe() for param in self.params],
            "reason_max_length": self.reason_max_length,
            **({"who_decides": self.who_decides} if self.who_decides else {}),
        }


def _loader(queryset_for: dict[str, Callable]):
    def load(target_type: str, target_id: int):
        make = queryset_for.get(target_type)
        return make().filter(pk=target_id).first() if make else None

    return load


def _deals():
    return Deal.objects.select_related("delivery_request", "sender", "traveler")


def _disputes():
    return Dispute.objects.select_related("deal__delivery_request")


def _people():
    return User.objects.all()


def _ref(deal) -> str:
    return tracking.for_deal(deal)


# note.add ---------------------------------------------------------------------------------


def _note_what(obj, target_type: str) -> str:
    if target_type == AdminNote.TargetType.DEAL:
        return f"the delivery {_ref(obj)}"
    if target_type == AdminNote.TargetType.DISPUTE:
        return f"the dispute on {_ref(obj.deal)}"
    return f"{short_name(obj)} (person {obj.pk})"


def _note_type(obj) -> str:
    if isinstance(obj, Deal):
        return AdminNote.TargetType.DEAL
    if isinstance(obj, Dispute):
        return AdminNote.TargetType.DISPUTE
    return AdminNote.TargetType.PERSON


def _note_check(admin, obj, params, reason):
    from apps.admin_panel.console_notes import NoteForm

    return {"body": _form(NoteForm, {"body": params["body"]})["body"]}


def _note_run(admin, obj, cleaned, reason, basis):
    target_type = _note_type(obj)
    staff_actions.add_note(
        actor=admin,
        target_type=target_type,
        target_id=obj.pk,
        body=cleaned["body"],
        reason=reason,
        via_helper=True,
    )
    return f"The note is added to {_note_what(obj, target_type)}. Only staff can see it."


# problem.acknowledge ----------------------------------------------------------------------


def _problem_check(admin, obj, params, reason):
    from apps.admin_panel.console_problems import ProblemReasonForm, acknowledgeable

    _form(ProblemReasonForm, {"reason": reason})
    if not acknowledgeable(obj):
        raise Refused(NOT_OFFERED, f"This report is not waiting for staff: it is {obj.get_status_display().lower()}.")
    return {}


def _problem_run(admin, obj, cleaned, reason, basis):
    from apps.problems.services import acknowledge_problem

    acknowledge_problem(problem_id=obj.pk, actor=admin, reason=reason)
    return f"The report on {_ref(obj.deal)} is acknowledged. Both people see that staff are on it."


# refund.request ---------------------------------------------------------------------------


def _live_refunds(attempt) -> list[list]:
    return [
        [refund.pk, refund.status, refund.amount_eur_cents]
        for refund in PaymentRefund.objects.filter(attempt=attempt).order_by("pk")
    ]


def _refund_check(admin, attempt, params, reason):
    from apps.admin_panel.console_forms import RefundRequestForm
    from apps.admin_panel.console_views import refund_offered
    from apps.finance.services import refund_capacity_refusal, refund_key

    _form(
        RefundRequestForm,
        {
            "amount_eur": _cents(params["amount_eur_cents"]),
            "reason": params["refund_reason"],
            "confirm": True,
        },
    )
    if not refund_offered(attempt):
        raise Refused(NOT_OFFERED, "Only a captured payment that an order took can be refunded.")
    exceeded = refund_capacity_refusal(attempt, params["amount_eur_cents"])
    if exceeded is not None:
        raise Refused(exceeded.code, str(exceeded))
    earlier = PaymentRefund.objects.filter(
        idempotency_key=refund_key(attempt.pk, params["refund_reason"])
    ).first()
    if earlier is not None:
        # The refund service answers the same payment and reason with the
        # refund it already has, whatever the amount: the helper would report
        # an amount that never moves.
        raise Refused(
            NOT_OFFERED,
            f"This payment already has a refund for this reason ({format_eur(earlier.amount_eur_cents)}, "
            f"{earlier.get_status_display().lower()}). Open it on the console.",
        )
    return dict(params)


def _lock_payment(attempt) -> None:
    # The refund service's first lock, taken earlier in the same transaction.
    list(PaymentAttempt.objects.select_for_update(no_key=True).filter(pk=attempt.pk).values_list("pk"))


def _refund_basis(attempt, cleaned):
    from apps.finance.payout_domain import source_reserved_cents

    return {
        "status": attempt.status,
        "refunds": _live_refunds(attempt),
        "reserved_for_payout": source_reserved_cents(attempt),
    }


def _payment_ref(attempt) -> str:
    deal = attempt.order.deal if attempt.order.deal_id else None
    if deal is not None:
        return _ref(deal)
    request = attempt.order.delivery_request
    return tracking.for_request(request) if request is not None else f"payment {attempt.pk}"


def _refund_summary(attempt, cleaned):
    label = PaymentRefund.Reason(cleaned["refund_reason"]).label
    return (
        f"Refund {format_eur(cleaned['amount_eur_cents'])} of the "
        f"{format_eur(attempt.amount_eur_cents)} payment on {_payment_ref(attempt)} "
        f"(reason: {label})."
    )


def _refund_details(attempt, cleaned):
    return [
        ("Amount to refund", format_eur(cleaned["amount_eur_cents"])),
        ("Payment", f"{format_eur(attempt.amount_eur_cents)} by {attempt.get_provider_display()}"),
        ("Refund reason", PaymentRefund.Reason(cleaned["refund_reason"]).label),
    ]


def _refund_run(admin, attempt, cleaned, reason, basis):
    refund = staff_actions.request_refund(
        actor=admin,
        attempt_id=attempt.pk,
        amount_eur_cents=cleaned["amount_eur_cents"],
        reason=cleaned["refund_reason"],
    )
    # What the service did, not what was asked.
    return (
        f"The refund of {format_eur(refund.amount_eur_cents)} is requested. "
        "It is listed under Finance, then Refunds."
    )


# dispute.set_status and dispute.resolve -----------------------------------------------------

_DISPUTE_STATES = tuple(Dispute.ACTIVE_STATUSES)


def _status_label(value: str) -> str:
    return Dispute.Status(value).label


def _dispute_status_check(admin, dispute, params, reason):
    from apps.admin_panel.console_forms import DisputeStatusForm

    _form(DisputeStatusForm, {"status": params["status"], "note": reason})
    if dispute.status not in Dispute.ACTIVE_STATUSES:
        raise Refused(NOT_OFFERED, "This dispute is already finished.")
    if dispute.status == params["status"]:
        raise Refused(NOT_OFFERED, f"The dispute is already {_status_label(dispute.status).lower()}.")
    return dict(params)


def _dispute_status_run(admin, dispute, cleaned, reason, basis):
    staff_actions.change_dispute_status(
        actor=admin, dispute_id=dispute.pk, status=cleaned["status"], note=reason
    )
    return f"The dispute on {_ref(dispute.deal)} is now {_status_label(cleaned['status']).lower()}."


def _resolution_values(params, reason) -> dict:
    from apps.admin_panel.console_forms import DisputeResolutionForm

    form = DisputeResolutionForm(
        data={
            "resolution": params["resolution"],
            "sender_refund_eur": _cents(params.get("sender_refund_eur_cents")),
            "traveler_payout_eur": _cents(params.get("traveler_payout_eur_cents")),
            "note": reason,
        }
    )
    if not form.is_valid():
        errors = {name: " ".join(str(e) for e in messages) for name, messages in form.errors.items()}
        raise Refused(INVALID, " ".join(errors.values()), fields=errors)
    return form.service_values()


def _preview(dispute, values) -> dict:
    from apps.disputes.services import DisputeError, preview_dispute_resolution

    try:
        plan = preview_dispute_resolution(
            dispute_id=dispute.pk,
            resolution=values["resolution"],
            sender_refund_eur_cents=values["sender_refund_eur_cents"],
            traveler_payout_eur_cents=values["traveler_payout_eur_cents"],
        )
    except DisputeError as exc:
        raise refusal_of(exc) from None
    return plan.as_dict()


def _dispute_resolve_check(admin, dispute, params, reason):
    values = _resolution_values(params, reason)
    if dispute.status not in Dispute.ACTIVE_STATUSES:
        raise Refused(NOT_OFFERED, "This dispute is already finished.")
    return {**params, "preview": _preview(dispute, values)}


def _dispute_resolve_basis(dispute, cleaned):
    # The money outcome is part of what the admin confirms: a fresh preview
    # with other amounts is "This no longer applies" (advisor, 2026-11-14).
    return {"status": dispute.status, "preview": cleaned["preview"]}


def _resolution_words(cleaned) -> str:
    preview = cleaned["preview"]
    return (
        f"{format_eur(preview['sender_refund_eur_cents'])} back to the sender, "
        f"{format_eur(preview['traveler_payout_eur_cents'])} to the traveler, "
        f"Wassla keeps {format_eur(preview['platform_fee_eur_cents'])}"
    )


def _dispute_resolve_summary(dispute, cleaned):
    label = Dispute.Resolution(cleaned["resolution"]).label
    return f"Resolve the dispute on {_ref(dispute.deal)} as {label}: {_resolution_words(cleaned)}."


def _dispute_resolve_details(dispute, cleaned):
    preview = cleaned["preview"]
    return [
        ("Outcome", Dispute.Resolution(cleaned["resolution"]).label),
        ("Collected from the sender", format_eur(preview["collected_eur_cents"])),
        ("Back to the sender", format_eur(preview["sender_refund_eur_cents"])),
        ("Paid to the traveler", format_eur(preview["traveler_payout_eur_cents"])),
        ("Kept by Wassla", format_eur(preview["platform_fee_eur_cents"])),
    ]


def _dispute_resolve_run(admin, dispute, cleaned, reason, basis):
    values = _resolution_values(cleaned, reason)
    staff_actions.resolve_dispute(actor=admin, dispute_id=dispute.pk, **values)
    return f"The dispute on {_ref(dispute.deal)} is resolved: {_resolution_words(cleaned)}."


# deal.record_no_show ------------------------------------------------------------------------


def _no_show_check(admin, deal, params, reason):
    from apps.admin_panel.console_problems import NoShowForm, no_show_recordable

    _form(NoShowForm, {"party": params["party"], "note": reason})
    if not no_show_recordable(deal):
        raise Refused(
            NOT_OFFERED,
            "This delivery cannot take a no-show: it is not a funded delivery waiting for "
            "pickup, or a no-show is already recorded.",
        )
    return dict(params)


def _no_show_words(party: str) -> str:
    if party == Deal.NoShowParty.TRAVELER:
        return "the traveler did not come. The sender is refunded in full and the delivery is cancelled"
    return "the sender was not there. Nobody is refunded"


def _no_show_run(admin, deal, cleaned, reason, basis):
    from apps.admin_panel.services import record_deal_no_show

    result = record_deal_no_show(actor=admin, deal_id=deal.pk, party=cleaned["party"], note=reason)
    refunded = " The sender was refunded in full." if result.get("sender_refunded") else ""
    return f"The no-show on {_ref(deal)} is recorded.{refunded}"


# user.ban and user.unban --------------------------------------------------------------------


def _ban_check(banned: bool):
    def check(admin, person, params, reason):
        from apps.admin_panel.console_account import AccountBanForm

        _form(AccountBanForm, {"intent": "ban" if banned else "restore", "reason": reason})
        refusal = staff_actions.ban_refusal(admin, person, banned=banned)
        if refusal is not None:
            raise Refused(refusal.code, str(refusal))
        return {}

    return check


def _ban_run(banned: bool):
    def run(admin, person, cleaned, reason, basis):
        staff_actions.set_account_ban(actor=admin, user_id=person.pk, banned=banned, reason=reason)
        if banned:
            return f"The account of {short_name(person)} is banned. They are signed out."
        return f"The account of {short_name(person)} is restored. They can sign in again."

    return run


# profile.hide and profile.show --------------------------------------------------------------


def _hidden(person) -> bool:
    from apps.discovery.models import PublicProfile

    return PublicProfile.objects.filter(user=person, hidden_at__isnull=False).exists()


def _profile_check(hide: bool):
    def check(admin, person, params, reason):
        from apps.admin_panel.console_discovery import ProfileVisibilityForm

        _form(ProfileVisibilityForm, {"reason": reason})
        if _hidden(person) == hide:
            raise Refused(
                NOT_OFFERED,
                "The public profile is already hidden." if hide else "The public profile is not hidden.",
            )
        return {}

    return check


def _profile_run(hide: bool):
    def run(admin, person, cleaned, reason, basis):
        from apps.discovery.profiles import set_profile_hidden

        set_profile_hidden(user=person, actor=admin, hidden=hide, reason=reason)
        if hide:
            return f"The public profile of {short_name(person)} is hidden from discovery."
        return f"The public profile of {short_name(person)} follows their own choice again."

    return run


# journey.pause and journey.resume -----------------------------------------------------------


def _journey_check(pausing: bool):
    def check(admin, journey, params, reason):
        from apps.admin_panel.console_journey_pause import JourneyPauseForm, pause_state

        _form(JourneyPauseForm, {"reason": reason})
        offered = pause_state(journey, may_manage=True)["action"]
        if offered is None or offered["name"] != ("pause" if pausing else "resume"):
            raise Refused(
                NOT_OFFERED,
                "This journey cannot be paused now." if pausing else "Staff have not paused this journey.",
            )
        return {}

    return check


def _journey_basis(journey, cleaned):
    return {
        "status": journey.status,
        "paused_at": journey.paused_at.isoformat() if journey.paused_at else None,
        "paused_by_staff": journey.paused_by_staff,
    }


def _journey_run(pausing: bool):
    def run(admin, journey, cleaned, reason, basis):
        from apps.trips.services import pause_journey, resume_journey

        (pause_journey if pausing else resume_journey)(actor=admin, journey_id=journey.pk, reason=reason)
        if pausing:
            return f"Journey {journey.pk} is paused. It is out of discovery and takes no new offers."
        return f"Journey {journey.pk} is no longer paused."

    return run


# sea_crossing.activate and sea_crossing.deactivate ------------------------------------------


def _crossings():
    from apps.locations.models import SeaCrossing

    return SeaCrossing.objects.select_related("origin_locality", "destination_locality")


def _crossing_check(on: bool):
    def check(admin, crossing, params, reason):
        from apps.admin_panel.console_sea import CrossingReasonForm

        _form(CrossingReasonForm, {"reason": reason})
        if crossing.is_active == on:
            raise Refused(NOT_OFFERED, "The crossing is already on." if on else "The crossing is already off.")
        return {}

    return check


def _crossing_line(crossing) -> str:
    from apps.admin_panel.console_sea import crossing_line

    return crossing_line(crossing)


def _crossing_run(on: bool):
    def run(admin, crossing, cleaned, reason, basis):
        from apps.locations.sea_crossings import activate_crossing, deactivate_crossing

        (activate_crossing if on else deactivate_crossing)(actor=admin, crossing_id=crossing.pk, reason=reason)
        return f"{_crossing_line(crossing)} is now {'on' if on else 'off'}."

    return run


# job.retry and job.resolve ------------------------------------------------------------------


def _job_allowed(admin, job) -> bool:
    return staff_actions.can_manage_job(admin, job)


def _job_retry_check(admin, job, params, reason):
    from apps.admin_panel.console_forms import JobRetryForm

    _form(JobRetryForm, {"reason": reason, "confirm": True})
    if not staff_actions.needs_decision(job):
        raise Refused(NOT_OFFERED, "This job is not a failure waiting for a decision.")
    return {}


def _job_resolve_check(admin, job, params, reason):
    from apps.admin_panel.console_forms import JobResolutionForm

    _form(JobResolutionForm, {"resolution": params["resolution"], "reason": reason, "confirm": True})
    if not staff_actions.needs_decision(job):
        raise Refused(NOT_OFFERED, "This job is not a failure waiting for a decision.")
    return dict(params)


def _job_basis(job, cleaned):
    return {"status": job.status, "attempts": job.attempts, "resolution": job.resolution}


def _job_retry_run(admin, job, cleaned, reason, basis):
    staff_actions.retry_job(actor=admin, job_id=job.pk, reason=reason)
    return f"Background job {job.pk} is queued for an immediate retry."


def _job_resolve_run(admin, job, cleaned, reason, basis):
    staff_actions.resolve_job(actor=admin, job_id=job.pk, resolution=cleaned["resolution"], reason=reason)
    return f"The failure of background job {job.pk} is archived. Its history is kept."


# payout.retry -------------------------------------------------------------------------------


def _payout_check(admin, payout, params, reason):
    from apps.admin_panel.console_views import _stripe_payout_panel, bank_retry_offered

    if not bank_retry_offered(payout, _stripe_payout_panel(payout)):
        raise Refused(
            NOT_OFFERED,
            "Only a failed Stripe bank payout with nothing in flight and no Finance hold can be retried.",
        )
    return {}


def _payout_basis(payout, cleaned):
    return {"status": payout.status, "state_version": payout.state_version}


def _payout_run(admin, payout, cleaned, reason, basis):
    from apps.finance.payout_execution import admin_retry_bank_payout

    # The version the admin read: a payout that moved since is refused by the
    # service itself ("This payout changed while the page was open").
    admin_retry_bank_payout(
        actor=admin, payout_id=payout.pk, expected_state_version=basis["state_version"]
    )
    return (
        "A new bank payout is authorised. The original transfer is untouched and is not repeated."
    )


# review.* -----------------------------------------------------------------------------------


def _reviews():
    return Rating.objects.select_related("deal__delivery_request")


def _open_report_ids(rating) -> list[int]:
    return list(
        RatingReport.objects.filter(rating=rating, status=RatingReport.Status.OPEN)
        .order_by("pk")
        .values_list("pk", flat=True)
    )


def _moderation(rating):
    return RatingModeration.objects.filter(rating=rating).first()


def _review_check(decision: str):
    def check(admin, rating, params, reason):
        from apps.admin_panel.console_reviews import DecisionForm, available_decisions

        _form(DecisionForm, {"reason": reason})
        if not available_decisions(rating, _moderation(rating), len(_open_report_ids(rating)))[decision]:
            raise Refused(NOT_OFFERED, "The review page does not offer this decision now.")
        return {}

    return check


def _review_basis(rating, cleaned):
    moderation = _moderation(rating)
    return {
        "moderation": moderation.state if moderation else None,
        "open_reports": _open_report_ids(rating),
    }


_REVIEW_WORDS = {
    "dismiss": ("Dismiss the reports on", "The reports are dismissed. The review is unchanged."),
    "hide_comment": ("Hide the comment of", "The comment is hidden. The score still counts."),
    "remove": ("Remove", "The rating is removed from every public average, count and list."),
    "lift": ("Lift the decision on", "The decision is lifted. The review is shown as written."),
}


def _review_summary(decision: str):
    def summary(rating, cleaned):
        writer = "sender" if rating.rater_role == Rating.RaterRole.SENDER else "traveler"
        return (
            f"{_REVIEW_WORDS[decision][0]} the review on {_ref(rating.deal)} "
            f"({rating.score} out of 5, written by the {writer})."
        )

    return summary


def _review_run(decision: str):
    def run(admin, rating, cleaned, reason, basis):
        from apps.ratings.moderation import decide

        decide(rating_id=rating.pk, actor=admin, action=decision, reason=reason)
        return _REVIEW_WORDS[decision][1]

    return run


# --- the table --------------------------------------------------------------------------------

_REASON = "Why. Recorded with the change in the audit log."


def _entries() -> tuple[Action, ...]:
    from apps.admin_panel.console_problems import NoShowForm
    from apps.locations.sea_crossings import MANAGE_CROSSINGS_PERMISSION
    from apps.problems.services import MANAGE_PROBLEMS_PERMISSION
    from apps.ratings.moderation import MODERATE_PERMISSION

    no_show_note = NoShowForm.base_fields["note"].max_length
    people = _loader({"person": _people})
    jobs = _loader({"job": lambda: ScheduledJob.objects.all()})
    journeys = _loader({"journey": lambda: Journey.objects.all()})
    crossings = _loader({"sea_crossing": _crossings})
    reviews = _loader({"review_report": _reviews})

    entries = [
        Action(
            code="note.add",
            mode=DIRECT,
            title="Add an internal note to a delivery, a dispute or a person.",
            gates={
                "deal": staff_actions.note_permission(AdminNote.TargetType.DEAL),
                "dispute": staff_actions.note_permission(AdminNote.TargetType.DISPUTE),
                "person": staff_actions.note_permission(AdminNote.TargetType.PERSON),
            },
            load=_loader({"deal": _deals, "dispute": _disputes, "person": _people}),
            params=(
                Param(
                    "body",
                    "text",
                    "The note, as staff should read it. Never a member's contact details.",
                    max_length=AdminNote.BODY_MAX_LENGTH,
                ),
            ),
            check=_note_check,
            summary=lambda obj, cleaned: f"Add an internal note to {_note_what(obj, _note_type(obj))}.",
            run=_note_run,
            task="add_note",
        ),
        Action(
            code="problem.acknowledge",
            mode=DIRECT,
            title="Acknowledge a reported problem, so both people see staff are on it.",
            gates={"problem": (MANAGE_PROBLEMS_PERMISSION,)},
            load=_loader(
                {"problem": lambda: ShipmentProblem.objects.select_related("deal__delivery_request")}
            ),
            check=_problem_check,
            summary=lambda problem, cleaned: (
                f"Acknowledge the report \"{problem.get_kind_display()}\" on {_ref(problem.deal)}."
            ),
            basis=lambda problem, cleaned: {"status": problem.status},
            run=_problem_run,
            task="handle_problem",
        ),
        Action(
            code="refund.request",
            mode=PREPARED,
            title="Ask for a refund of a captured payment.",
            gates={"payment": ("issue_refunds",)},
            load=_loader(
                {
                    "payment": lambda: PaymentAttempt.objects.select_related(
                        "order__deal__delivery_request", "order__delivery_request"
                    )
                }
            ),
            params=(
                Param("amount_eur_cents", "integer", "How much to refund, in euro cents.", minimum=1),
                Param(
                    "refund_reason",
                    "choice",
                    "Why, as one of the refund reasons.",
                    choices=tuple(PaymentRefund.Reason.values),
                ),
            ),
            check=_refund_check,
            basis=_refund_basis,
            summary=_refund_summary,
            details=_refund_details,
            run=_refund_run,
            lock=_lock_payment,
            reason_in_metadata=True,
            task="request_refund",
        ),
        Action(
            code="dispute.set_status",
            mode=PREPARED,
            title="Move a dispute's review along: open, awaiting evidence or under review.",
            gates={"dispute": ("manage_disputes",)},
            load=_loader({"dispute": _disputes}),
            params=(Param("status", "choice", "The new review state.", choices=_DISPUTE_STATES),),
            check=_dispute_status_check,
            basis=lambda dispute, cleaned: {"status": dispute.status},
            summary=lambda dispute, cleaned: (
                f"Move the dispute on {_ref(dispute.deal)} from "
                f"{_status_label(dispute.status).lower()} to {_status_label(cleaned['status']).lower()}."
            ),
            details=lambda dispute, cleaned: [
                ("Now", _status_label(dispute.status)),
                ("After", _status_label(cleaned["status"])),
            ],
            run=_dispute_status_run,
            task="decide_dispute",
        ),
        Action(
            code="dispute.resolve",
            mode=PREPARED,
            title="Decide a dispute. The money outcome is the settlement engine's, shown before you confirm.",
            gates={"dispute": ("resolve_disputes",)},
            load=_loader({"dispute": _disputes}),
            params=(
                Param("resolution", "choice", "The outcome.", choices=tuple(Dispute.Resolution.values)),
                Param(
                    "sender_refund_eur_cents",
                    "integer",
                    "For a partial split only: how much goes back to the sender, in euro cents.",
                    required=False,
                    minimum=0,
                ),
                Param(
                    "traveler_payout_eur_cents",
                    "integer",
                    "For a partial split only, optional: the traveler's part, in euro cents.",
                    required=False,
                    minimum=0,
                ),
            ),
            check=_dispute_resolve_check,
            basis=_dispute_resolve_basis,
            restore=lambda params, basis: {**params, "preview": basis["preview"]},
            summary=_dispute_resolve_summary,
            details=_dispute_resolve_details,
            fresh_note="The settlement engine computed these amounts again when this page opened.",
            run=_dispute_resolve_run,
            task="decide_dispute",
        ),
        Action(
            code="deal.record_no_show",
            mode=PREPARED,
            title="Record that the traveler or the sender did not come to a pickup.",
            gates={"deal": ("record_no_show",)},
            load=_loader({"deal": _deals}),
            params=(
                Param("party", "choice", "Who did not come.", choices=tuple(Deal.NoShowParty.values)),
            ),
            check=_no_show_check,
            basis=lambda deal, cleaned: {
                "status": deal.status,
                "no_show_party": deal.no_show_party,
                "picked_up": deal.pickup_confirmed_at is not None,
            },
            summary=lambda deal, cleaned: f"Record on {_ref(deal)} that {_no_show_words(cleaned['party'])}.",
            details=lambda deal, cleaned: [("Who did not come", Deal.NoShowParty(cleaned["party"]).label)],
            run=_no_show_run,
            reason_max_length=no_show_note,
            task="record_no_show",
        ),
    ]
    for banned in (True, False):
        entries.append(
            Action(
                code="user.ban" if banned else "user.unban",
                mode=PREPARED,
                title="Ban a member's account. They are signed out at once."
                if banned
                else "Restore a banned member's account.",
                gates={"person": (staff_actions.BAN_PERMISSION,)},
                load=people,
                check=_ban_check(banned),
                basis=lambda person, cleaned: {
                    "is_banned": person.is_banned,
                    "is_active": person.is_active,
                    "is_staff": person.is_staff,
                },
                summary=(
                    (lambda person, cleaned: (
                        f"Ban the account of {short_name(person)} (person {person.pk}). They are "
                        "signed out at once; their deliveries, payments and payouts are not changed."
                    ))
                    if banned
                    else (lambda person, cleaned: (
                        f"Restore the account of {short_name(person)} (person {person.pk}). "
                        "They can sign in again."
                    ))
                ),
                run=_ban_run(banned),
                task="ban_account",
            )
        )
    for hide in (True, False):
        entries.append(
            Action(
                code="profile.hide" if hide else "profile.show",
                mode=PREPARED,
                title="Hide a member's public profile from discovery."
                if hide
                else "Show a hidden public profile again (the member's own choice applies).",
                gates={"person": ("manage_users",)},
                load=people,
                check=_profile_check(hide),
                basis=lambda person, cleaned: {"hidden": _hidden(person)},
                summary=(
                    (lambda person, cleaned: f"Hide the public profile of {short_name(person)} (person {person.pk}).")
                    if hide
                    else (lambda person, cleaned: (
                        f"Show the public profile of {short_name(person)} (person {person.pk}) again."
                    ))
                ),
                run=_profile_run(hide),
                task="hide_public_profile",
            )
        )
    for pausing in (True, False):
        entries.append(
            Action(
                code="journey.pause" if pausing else "journey.resume",
                mode=PREPARED,
                title="Pause a traveler's journey: out of discovery, no new offers."
                if pausing
                else "Resume a journey staff paused.",
                gates={"journey": ("manage_journeys",)},
                load=journeys,
                check=_journey_check(pausing),
                basis=_journey_basis,
                summary=(
                    (lambda journey, cleaned: (
                        f"Pause journey {journey.pk}. It leaves discovery and takes no new offers; "
                        "paid deliveries are not affected."
                    ))
                    if pausing
                    else (lambda journey, cleaned: f"Resume journey {journey.pk}.")
                ),
                run=_journey_run(pausing),
                task="pause_journey",
            )
        )
    for on in (True, False):
        entries.append(
            Action(
                code="sea_crossing.activate" if on else "sea_crossing.deactivate",
                mode=PREPARED,
                title="Turn a sea crossing on." if on else "Turn a sea crossing off.",
                gates={"sea_crossing": (MANAGE_CROSSINGS_PERMISSION,)},
                load=crossings,
                check=_crossing_check(on),
                basis=lambda crossing, cleaned: {"is_active": crossing.is_active},
                summary=(
                    (lambda crossing, cleaned: f"Turn on the sea crossing {_crossing_line(crossing)}.")
                    if on
                    else (lambda crossing, cleaned: f"Turn off the sea crossing {_crossing_line(crossing)}.")
                ),
                run=_crossing_run(on),
                task="manage_sea_crossings",
            )
        )
    job_gate = {"job": ("reconcile_finance", "manage_lifecycle")}
    entries += [
        Action(
            code="job.retry",
            mode=PREPARED,
            title="Run a failed background job once more.",
            gates=job_gate,
            load=jobs,
            allowed=_job_allowed,
            check=_job_retry_check,
            basis=_job_basis,
            summary=lambda job, cleaned: f"Retry background job {job.pk} ({job.get_kind_display()}).",
            run=_job_retry_run,
            task="fix_job",
            who_decides="Finance decides money jobs; Finance or Ops decide the rest.",
        ),
        Action(
            code="job.resolve",
            mode=PREPARED,
            title="Archive a failed background job without running it again.",
            gates=job_gate,
            load=jobs,
            allowed=_job_allowed,
            params=(
                Param(
                    "resolution",
                    "choice",
                    "How it was settled.",
                    choices=tuple(ScheduledJob.Resolution.values),
                ),
            ),
            check=_job_resolve_check,
            basis=_job_basis,
            summary=lambda job, cleaned: (
                f"Archive the failure of background job {job.pk} ({job.get_kind_display()}) as "
                f"{ScheduledJob.Resolution(cleaned['resolution']).label.lower()}."
            ),
            details=lambda job, cleaned: [
                ("Archived as", ScheduledJob.Resolution(cleaned["resolution"]).label),
            ],
            run=_job_resolve_run,
            task="fix_job",
            who_decides="Finance decides money jobs; Finance or Ops decide the rest.",
        ),
        Action(
            code="payout.retry",
            mode=PREPARED,
            title="Retry a failed Stripe bank payout.",
            gates={"payout": ("retry_payouts",)},
            load=_loader(
                {"payout": lambda: Payout.objects.select_related("deal__delivery_request", "traveler")}
            ),
            check=_payout_check,
            basis=_payout_basis,
            summary=lambda payout, cleaned: (
                f"Retry the bank payout of {format_eur(payout.amount_eur_cents)} to "
                f"{short_name(payout.traveler)} for {_ref(payout.deal)}."
            ),
            run=_payout_run,
            reason_in_metadata=True,
            task="follow_payout",
        ),
    ]
    for decision, code in (
        ("hide_comment", "review.hide_comment"),
        ("remove", "review.remove"),
        ("dismiss", "review.dismiss_report"),
        ("lift", "review.lift"),
    ):
        entries.append(
            Action(
                code=code,
                mode=PREPARED,
                title={
                    "hide_comment": "Hide a review's comment; its score still counts.",
                    "remove": "Remove a rating from every public average, count and list.",
                    "dismiss": "Dismiss the reports on a review; it stays as it is.",
                    "lift": "Lift a decision, so the review is shown as written.",
                }[decision],
                gates={"review_report": (MODERATE_PERMISSION,)},
                load=reviews,
                check=_review_check(decision),
                basis=_review_basis,
                summary=_review_summary(decision),
                run=_review_run(decision),
                task="moderate_review",
            )
        )
    return tuple(entries)


# --- the console's POST pages, and what never goes through the helper -----------------

#: Every console page that takes a POST and has a helper action, with the
#: actions that do the same thing there. A test holds this, `NEVER` and
#: `NEVER_ON_PAGE` to the console's routes (plan L16).
CONSOLE_POSTS: dict[str, tuple[str, ...]] = {
    "note-add": ("note.add",),
    "problem-detail": ("problem.acknowledge",),
    "refund-new": ("refund.request",),
    "dispute-detail": ("dispute.set_status", "dispute.resolve"),
    "deal-no-show": ("deal.record_no_show",),
    "user-ban": ("user.ban", "user.unban"),
    "user-profile-visibility": ("profile.hide", "profile.show"),
    "journey-pause": ("journey.pause", "journey.resume"),
    "sea-crossing-toggle": ("sea_crossing.activate", "sea_crossing.deactivate"),
    "job-retry": ("job.retry",),
    "job-resolve": ("job.resolve",),
    "payout-detail": ("payout.retry",),
    "review-detail": ("review.hide_comment", "review.remove", "review.dismiss_report", "review.lift"),
}

_SIGNING_IN = "Signing in and the second step: the admin's own, on the console."
_STAFF = "Staff, roles and invitations: who may do what is never changed by an assistant."
_KEYS = "The helper's own keys: created behind a fresh code and stopped on the console."

#: The console's POST pages the helper never does, and why (plan L16).
NEVER: dict[str, str] = {
    "two-step-enrol": _SIGNING_IN,
    "two-step-verify": _SIGNING_IN,
    "two-step-recovery": _SIGNING_IN,
    "staff": _STAFF,
    "staff-role": _STAFF,
    "staff-access": _STAFF,
    "staff-invitation-action": _STAFF,
    "staff-two-step-reset": "Resetting a colleague's second step.",
    "settings": "Business settings, the AI helper switch among them.",
    "ai-helper-create": _KEYS,
    "ai-helper-stop": _KEYS,
    "ai-helper-change": "Confirming or rejecting a prepared change: the admin's own click.",
    "kyc-detail": "Identity reviews: they need the document, and revealing it.",
    "proof-detail": "Ticket reviews: they need the document.",
    "payout-review-detail": "Payout-method reviews and revealing payout details.",
    "identity-check-detail": "Payout-identity confirmations: they need the documents.",
    "payment-reconcile": "Reconciling a payment with its provider.",
    "payment-resolve": "Resolving a payment exception.",
    "refund-detail": "Settling a refund by hand.",
    "payout-account-retire": "Retiring a traveler's Stripe payout account.",
    "job-bulk": "Deciding background jobs in bulk: the helper prepares one job at a time.",
    "sea-crossing-new": "Adding a sea crossing to the geography.",
    "finance-exports": "Finance exports: files for the admin, never for an assistant.",
    "chat-report-detail": "Reported chat messages: chat contents never reach an assistant.",
    "user-photo-remove": "Removing a profile photo: the admin looks at the picture, which never reaches an assistant.",
}

#: Operations of a page in `CONSOLE_POSTS` that the helper still never does.
NEVER_ON_PAGE: dict[str, str] = {
    "problem-detail": "Closing a report: staff close it with the people, on the console.",
    "payout-detail": "Manual dinar payout steps, re-reading Stripe and opening a Finance hold.",
}


@cache
def registry() -> Mapping[str, Action]:
    """Every action the helper may take or prepare, by code. Built once, on
    first use (the console forms it names import late), and read only."""

    return MappingProxyType({entry.code: entry for entry in _entries()})


def get(code: str) -> Action | None:
    return registry().get(code)


def for_task(task_code: str) -> tuple[str, ...]:
    return tuple(entry.code for entry in registry().values() if entry.task == task_code)
