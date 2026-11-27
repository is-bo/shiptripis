"""H6A read model. No routing, eligibility, settlement or FX writes here."""

from dataclasses import dataclass

from django.conf import settings
from django.db.models import Prefetch, Q
from django.utils import timezone

from apps.accounts.permissions import EMAIL_VERIFICATION_REQUIRED
from apps.parcels import tracking

from .models import FinanceHold, Payout, PayoutProfileReview, TravelerPayoutMethod
from .payout_accounts import (
    ConnectUnavailable,
    CountryUnsupported,
    account_country,
    allowed_countries,
    current_creation,
    evaluate_readiness,
    in_this_environment,
    onboarding_incomplete,
    onboarding_refusal,
    require_connect_enabled,
    standing_accounts,
)
from .payout_evidence import evidence_store_configured
from .payout_manual_profiles import approved_profile
from .payout_profiles import PayoutProfilesDisabled, TravelerRequired, holds_payout_setup

#: Stripe Connect is switched on and configured, but no account country is open.
NO_COUNTRIES = "stripe_connect_no_countries"
EVIDENCE_UNAVAILABLE = "payout_evidence_unavailable"


@dataclass(frozen=True, slots=True)
class SetupGate:
    """What a member payout-setup write meets right now.

    Read from the checks that refuse the write, so every action the read model
    offers is one the server accepts. `refusal` stops every setup write; the
    other fields are the rail gates behind it.
    """

    profiles: bool
    refusal: str | None
    connect: bool
    countries: tuple
    evidence_store: bool


def setup_gate(user):
    if not settings.PAYOUT_PROFILES_ENABLED:
        refusal = PayoutProfilesDisabled.code
    elif not holds_payout_setup(user):
        refusal = TravelerRequired.code
    elif not user.is_email_verified:
        # `EmailVerifiedToWrite` refuses every unsafe setup method on this flag.
        refusal = EMAIL_VERIFICATION_REQUIRED
    else:
        refusal = None
    try:
        require_connect_enabled()
        connect = True
    except ConnectUnavailable:
        connect = False
    return SetupGate(profiles=settings.PAYOUT_PROFILES_ENABLED, refusal=refusal,
                     connect=connect, countries=allowed_countries(),
                     evidence_store=evidence_store_configured())


def eur_refusal(gate):
    """Why a new EUR account country cannot be accepted, past the member gate."""
    if gate.countries:
        return CountryUnsupported.code
    return NO_COUNTRIES if gate.connect else ConnectUnavailable.code


def methods_for(user):
    return TravelerPayoutMethod.objects.filter(traveler=user).select_related(
        "current_version__stripe_account", "current_version__dzd_profile_revision__evidence"
    ).order_by("currency")


def eur_method(method, gate):
    version = method.current_version if method else None
    bound = version.stripe_account if version else None
    # Setup is decided in the configured platform and mode only. A method still
    # bound to an account from another one keeps it as history (the method
    # projection shows it), and onboarding here binds this environment's.
    account = bound if bound is not None and in_this_environment(bound) else None
    countries = list(gate.countries)
    country = version.country if version else ""
    country_supported = not country or country in countries
    # An active account this version is not bound to: onboarding binds it when
    # it was opened for the declared country and refuses otherwise.
    held = standing_accounts(method.traveler_id).first() if method and not account else None
    standing = account or held
    held_country = account_country(standing) if standing else None
    # The decision onboarding makes, from the same facts. A closed declared
    # country is no obstacle to a new setup: it starts with the preference
    # change, which names an open country.
    refusal = (
        onboarding_refusal(country, standing=standing, creation=current_creation(method))
        if method else None
    )
    if isinstance(refusal, CountryUnsupported) and not refusal.of_account:
        refusal = None
    state, reason = "not_configured", "payout_setup_required"
    if account:
        verdict = evaluate_readiness(account)
        state = {"pending_review": "pending_verification", "unavailable": "needs_attention"}.get(
            verdict.status, verdict.status
        )
        reason = "" if verdict.ready else (
            "payout_country_unsupported" if verdict.reason == "country_unsupported"
            else "payout_profile_under_review" if state == "pending_verification"
            else "payout_setup_required" if state == "setup_required"
            else "payout_profile_needs_attention"
        )
    elif refusal is not None:
        state, reason = "needs_attention", (
            "payout_country_unsupported" if isinstance(refusal, CountryUnsupported)
            else "payout_profile_needs_attention"
        )
    elif version:
        state = "setup_required"
    if not country_supported:
        reason = "payout_country_unsupported"
    if gate.refusal:
        unavailable = gate.refusal
    elif not gate.connect:
        unavailable = ConnectUnavailable.code
    elif not countries:
        unavailable = NO_COUNTRIES
    elif refusal is not None:
        # The class's code: Django's ValidationError sets `code` on each
        # instance, to None here.
        unavailable = type(refusal).code
    else:
        unavailable = None
    # Each action follows the write it leads to: every Stripe call needs the
    # member gate and Connect; a resumed onboarding also needs the onboarding
    # decision to pass, which refresh and dashboard access do not. A new setup
    # collects the account country first, so a saved country that has closed
    # does not stop it.
    connect = gate.refusal is None and gate.connect
    actions = []
    if connect and account and account.active:
        actions.append("refresh")
        if account.details_submitted:
            actions.append("manage_eur")
        # The hosted link is the only way back into Stripe's onboarding, also
        # after a call that bound the account but got no link.
        if method.enabled and refusal is None and (
            state == "setup_required" or onboarding_incomplete(account)
        ):
            actions.append("resume_eur_setup")
    elif not account and unavailable is None:
        actions.append("configure_eur")
    return {"state": state, "ready": state == "ready", "blocking_reason": reason or None,
            "available_actions": actions, "country": country or None,
            # The saved declaration's own eligibility; None when none is saved.
            "country_supported": country in countries if country else None,
            # The country of the Traveler's Stripe account, when one exists.
            "account_country": held_country or None,
            "supported_countries": countries,
            "supported": bool(gate.connect and countries and country_supported),
            # The preference PATCH accepts EUR with any open account country;
            # it does not need Connect, which only onboarding calls.
            "selectable": bool(gate.refusal is None and countries),
            "unavailable_reason": unavailable,
            "checked_at": account.readiness_checked_at if account else None}


def dzd_method(method, gate):
    version = method.current_version if method else None
    profile = version.dzd_profile_revision if version else None
    review = profile.reviews.order_by("-pk").first() if profile else None
    state = "not_configured"
    if method:
        state = "setup_required"
    if profile:
        state = ("ready" if approved_profile(profile) else "needs_attention"
                 if review else "pending_review")
    if method and not method.enabled:
        state = "inactive"
    reason = {"not_configured": "payout_setup_required", "setup_required": "payout_setup_required",
              "pending_review": "payout_profile_under_review",
              "needs_attention": "payout_profile_needs_attention"}.get(state)
    # Submitting or replacing a profile starts with the cheque upload, so it
    # needs the private evidence store as well as the member gate.
    unavailable = gate.refusal or (None if gate.evidence_store else EVIDENCE_UNAVAILABLE)
    return {"state": state, "ready": state == "ready", "blocking_reason": reason,
            "available_actions": [] if unavailable else [
                "replace_dzd_profile" if profile else "configure_dzd"],
            "country": "DZ", "supported": gate.profiles,
            "selectable": gate.refusal is None, "unavailable_reason": unavailable,
            "profile": {"reference": str(profile.public_reference),
                        "review_state": review.status if review else "pending_review",
                        "ccp_last_four": profile.ccp_last_four, "rip_last_four": profile.rip_last_four,
                        "submitted_at": profile.submitted_at} if profile else None,
            "replacement_scope": "future_payouts_only"}


def payout_summary(user, methods=None, gate=None):
    gate = gate or setup_gate(user)
    methods = list(methods if methods is not None else methods_for(user))
    by_currency = {m.currency: m for m in methods}
    enabled = {m.currency for m in methods if m.enabled}
    preference = "both" if len(enabled) == 2 else "eur_only" if "EUR" in enabled else "dzd_only" if enabled else None
    eur, dzd = eur_method(by_currency.get("EUR"), gate), dzd_method(by_currency.get("DZD"), gate)
    options = (("eur_only", eur["selectable"]), ("dzd_only", dzd["selectable"]),
               ("both", eur["selectable"] and dzd["selectable"]))
    return {"contract_version": "f1.v1", "preference": preference,
            # Funding asks for a preference only while payout profiles are on.
            "preference_required": preference is None and gate.profiles,
            "revisions": {c: by_currency[c].revision if c in by_currency else 0 for c in ("EUR", "DZD")},
            # The stored preference above stays readable whatever this says;
            # this is only whether a new setup write would be accepted now.
            "setup": {"available": gate.refusal is None, "unavailable_reason": gate.refusal,
                      "preference_options": [value for value, usable in options if usable]},
            "eur": eur, "dzd": dzd,
            "available_actions": list(dict.fromkeys(eur["available_actions"] + dzd["available_actions"])),
            "preference_scope": "future_payouts_only"}


def setup_actions(user):
    """The setup actions this traveler can use now, by payout currency."""
    summary = payout_summary(user)
    return {"EUR": summary["eur"]["available_actions"], "DZD": summary["dzd"]["available_actions"]}


def payouts_for(user):
    return payout_read_rows(Payout.objects.filter(traveler=user)).order_by("-created_at", "-pk")


def payout_read_rows(rows):
    """Load the bounded Finance/mobile page without a query per payout."""
    return rows.select_related(
        "deal__delivery_request", "stripe_account", "active_instruction_version__stripe_account",
        "active_instruction_version__dzd_profile_revision__evidence",
        "active_instruction_version__dzd_profile_revision__method",
    ).prefetch_related(
        "disbursement_allocations__disbursement", "funding_allocations",
        Prefetch(
            "active_instruction_version__dzd_profile_revision__reviews",
            queryset=PayoutProfileReview.objects.select_related(
                "identity_attestation__kyc_submission", "identity_attestation__revocation"
            ).prefetch_related("identity_attestation__successors"),
        ),
    )


#: How H3's authoritative bank-payout state reads on the Traveler's phone.
BANK_DISPLAY = {
    "planned": ("processing", None), "committed": ("processing", None),
    "unknown": ("processing", None), "pending": ("processing", None),
    "in_transit": ("sent", None), "paid": ("paid", None),
    "failed": ("needs_attention", "payout_failed"),
    "canceled": ("needs_attention", "payout_failed"),
    "returned": ("needs_attention", "payout_returned"),
}


def bank_stage(payout):
    """The EUR settlement fact, read from the bank disbursement H3 owns.

    Deliberately *not* the platform Transfer or its attempt. A Transfer only
    moves ShipTrip's money into the connected account's Stripe balance; the
    Traveler is paid when the bank payout reaches `paid`, and a later return
    leaves that Transfer accepted and its attempt reset to `accepted`. Reading
    the attempt therefore keeps reporting money the Traveler no longer has, and
    can never say `returned` at all.

    The current stage is the active allocation when one binds, and otherwise the
    most recent one: a returned or failed bank payout releases its allocation,
    and an operator's audited retry binds a new disbursement over the top.
    """

    allocations = list(payout.disbursement_allocations.all())
    if not allocations:
        return None
    current = max(allocations, key=lambda row: (row.active, row.pk))
    return BANK_DISPLAY.get(current.disbursement.status)


def page_context(payouts, *, user=None, include_actions=True):
    """One bounded pass over a whole history page.

    Dispute, hold and setup lookups are per-payout facts, so a list that asks
    each row for them separately costs queries proportional to the page size.
    Everything the page needs is read here instead, and `payout_status` then
    answers from memory.
    """

    from apps.disputes.models import Dispute
    from .models import ProviderDispute
    from .payout_provider_events import DISPUTE_OPEN_STATUSES

    payouts = list(payouts)
    if not payouts:
        return {"disputed": set(), "held": set(), "account_holds": set(),
                "actions": {}, "profiles": {}}
    accounts, attempts = set(), set()
    for payout in payouts:
        version = payout.active_instruction_version
        accounts.update(pk for pk in (
            payout.stripe_account_id, version.stripe_account_id if version else None
        ) if pk)
        attempts.update(pk for pk in (
            [payout.funding_attempt_id]
            + [row.source_attempt_id for row in payout.funding_allocations.all()]
        ) if pk)
    deal_ids = {p.deal_id for p in payouts}
    # `active_holds` reaches a payout through any one of these four scopes, so
    # the page reads all four in one pass rather than one query per row.
    fields = ("payout_id", "deal_id", "account_id", "source_attempt_id")
    scopes = {field: set() for field in fields}
    rows = FinanceHold.objects.filter(
        Q(payout_id__in={p.pk for p in payouts}) | Q(deal_id__in=deal_ids)
        | Q(account_id__in=accounts) | Q(source_attempt_id__in=attempts),
        cleared_at__isnull=True,
    ).values_list(*fields)
    for values in rows:
        for field, value in zip(fields, values):
            if value is not None:
                scopes[field].add(value)
    held = set()
    for payout in payouts:
        version = payout.active_instruction_version
        owned_accounts = {payout.stripe_account_id,
                          version.stripe_account_id if version else None} - {None}
        owned_attempts = ({payout.funding_attempt_id} | {
            row.source_attempt_id for row in payout.funding_allocations.all()
        }) - {None}
        if (payout.pk in scopes["payout_id"] or payout.deal_id in scopes["deal_id"]
                or owned_accounts & scopes["account_id"]
                or owned_attempts & scopes["source_attempt_id"]):
            held.add(payout.pk)
    disputed = set(
        Dispute.objects.filter(deal_id__in=deal_ids)
        .exclude(status__in=["resolved", "closed"])
        .values_list("deal_id", flat=True)
    )
    provider_rows = ProviderDispute.objects.filter(
        Q(source_attempt__order__deal_id__in=deal_ids)
        | Q(source_attempt__order__credited_into__deal_id__in=deal_ids),
        status__in=DISPUTE_OPEN_STATUSES,
    ).values_list("provider_mode", "source_attempt__order__deal_id",
                  "source_attempt__order__credited_into__deal_id")
    provider_scopes = {(mode, deal) for mode, direct, credited in provider_rows
                       for deal in (direct, credited) if deal}
    disputed.update(p.deal_id for p in payouts if (p.provider_mode, p.deal_id) in provider_scopes)
    return {"disputed": disputed, "held": held, "account_holds": scopes["account_id"],
            "actions": setup_actions(user or payouts[0].traveler) if include_actions else {},
            # Approval depends on both the profile and the funding instant.
            "profiles": {}}


def _profile_verdict(profile, context, payout):
    """`(approved, reviewed)` for one DZD profile revision, read at most once."""

    if profile is None:
        return False, False
    memo = context["profiles"] if context is not None else None
    key = (profile.pk, payout.method_version_id, payout.active_instruction_version_id,
           payout.dzd_profile_revision_id, payout.snapshot_at, payout.snapshot_version)
    if memo is None or key not in memo:
        verdict = (approved_profile(profile, funded_payout=payout), bool(profile.reviews.all()))
        if memo is None:
            return verdict
        memo[key] = verdict
    return memo[key]


def payout_attention(payout, *, context=None):
    """Safe shared blocker classification, independent of delivery waiting time.

    Bank failure/return > terminal settlement > failure > dispute > hold >
    substantive stored gate > bound destination readiness > balance deferral.
    Unknown stored text is never exposed. Owners are assigned only from facts.
    """
    if context is None:
        context = page_context([payout], include_actions=False)
    bank = bank_stage(payout)
    reason, owner = None, None
    if bank and bank[1]:
        reason, owner = bank[1], "finance"
    elif payout.status in ("paid", "cancelled") or (bank and bank[0] == "paid"):
        pass
    elif payout.status == "failed":
        reason, owner = "payout_failed", "finance"
    elif payout.deal_id in context["disputed"]:
        reason = "dispute_active"
    elif payout.status == "frozen" or payout.pk in context["held"]:
        reason, owner = "payout_on_hold", "finance"
    elif payout.block_reason not in ("", "payout_setup_required", "connected_balance_pending"):
        reason = "payout_on_hold"
    elif (
        not bank
        and (payout.status != "processing" or payout.method == "manual")
        and (payout.snapshot_version or payout.active_instruction_version_id
             or payout.block_reason == "payout_setup_required")
    ):
        # Legacy obligations predate profile snapshots. Missing H1 evidence is
        # not itself a setup gate; their explicit execution gates still apply.
        version = payout.active_instruction_version
        if payout.method == "stripe_transfer" and version and version.stripe_account:
            account = version.stripe_account
            verdict = evaluate_readiness(account, holds_exist=account.pk in context["account_holds"])
            if verdict.ready and payout.block_reason == "payout_setup_required":
                # Account readiness alone cannot clear a stored execution gate.
                reason = "payout_setup_required"
            elif not verdict.ready:
                if verdict.status == "pending_review":
                    reason, owner = "payout_profile_under_review", "provider"
                elif verdict.status == "setup_required":
                    reason, owner = "payout_setup_required", "traveler"
                else:
                    reason = "payout_profile_needs_attention"
        elif payout.method == "manual":
            profile = version.dzd_profile_revision if version else None
            approved, reviewed = _profile_verdict(profile, context, payout)
            if not approved:
                reason = ("payout_profile_needs_attention" if reviewed else
                          "payout_profile_under_review" if profile else "payout_setup_required")
                owner = "finance" if profile else None
        else:
            reason = "payout_setup_required"
    if reason is None and payout.status not in ("paid", "cancelled", "sent") and not (bank and bank[0] in ("paid", "sent")):
        if payout.block_reason == "connected_balance_pending":
            reason, owner = "connected_balance_pending", "provider"
        elif payout.status == "blocked" and payout.block_reason != "payout_setup_required":
            reason = "payout_on_hold"
    return {"block_reason": reason, "needs_attention": bool(reason and reason != "connected_balance_pending"),
            "attention_owner": owner}


def payout_status(payout, *, at=None, context=None):
    """Expired protection alone never upgrades a not-yet-released obligation."""
    at = at or timezone.now()
    deal = payout.deal
    protection_active = bool(deal.protection_ends_at and at < deal.protection_ends_at)
    # Phase I1A. Both instants are Deal columns already loaded with the payout,
    # so this costs no query and the H6A page-length guard still holds.
    from apps.deals.arrival import payout_release_gate_at

    gate = payout_release_gate_at(deal)
    arrival_floor_pending = bool(gate and at < gate and not protection_active)
    state, reason = "awaiting_delivery", None
    if deal.delivery_confirmed_at:
        state = "protection_active" if protection_active else "release_pending"
    bank = bank_stage(payout)

    attention = payout_attention(payout, context=context)

    actions = ["view_payout", "refresh"]
    if bank and bank[1]:
        # A returned or failed bank payout outranks every local status — including
        # a `paid` the same disbursement recorded before the money came back.
        state, reason = bank
    elif payout.status == "paid" or (bank and bank[0] == "paid"):
        state = "paid"
    elif payout.status == "cancelled":
        state = "cancelled"
    elif attention["needs_attention"]:
        state, reason = "needs_attention", attention["block_reason"]
    elif payout.status == "sent" or (bank and bank[0] == "sent"):
        state = "sent"
    elif protection_active:
        state, reason = "protection_active", "protection_active"
    elif arrival_floor_pending:
        # Protection has closed but this Deal was delivered materially earlier
        # than the schedule it was funded against, so the release gate is the
        # arrival floor. Reported as its own reason rather than as an extended
        # protection window, because calling a schedule floor "protection" would
        # misdescribe both.
        state, reason = "release_pending", "scheduled_arrival_pending"
    elif payout.status == "processing" or (bank and bank[0] == "processing"):
        state = "processing"
    elif payout.status in ("eligible", "scheduled", "blocked"):
        state = "ready"
    if not reason:
        # Finance can describe a normal provider wait without asking for action.
        # Older mobile clients render unknown blockers as "needs attention".
        reason = attention["block_reason"] if attention["needs_attention"] else None
    rail = ("stripe_eur" if payout.method == "stripe_transfer" else "manual_dzd"
            if payout.method == "manual" and payout.payout_currency == "DZD" else "unavailable")
    if state == "needs_attention" and reason in ("payout_setup_required", "payout_profile_needs_attention"):
        # Current setup can differ from this funded destination. Do not promise
        # that editing the current method will repair a historical instruction.
        # Only the funded rail's own actions, and only those usable now; an
        # obligation without a rail may use either.
        rails = context["actions"] if context else setup_actions(payout.traveler)
        actions += {"stripe_eur": rails.get("EUR", []), "manual_dzd": rails.get("DZD", [])}.get(
            rail, rails.get("EUR", []) + rails.get("DZD", []))
    return {"reference": str(payout.public_reference), "deal_id": deal.pk,
            "tracking_number": tracking.for_deal(deal),
            "rail": rail,
            "settlement_currency": payout.payout_currency or None,
            "amount_eur_cents": int(payout.amount_eur_cents),
            "dzd_amount": payout.payout_amount_minor if payout.payout_currency == "DZD" else None,
            "fx_rate_micros": payout.fx_rate_micros if payout.payout_currency == "DZD" else None,
            "state": payout.status, "display_state": state, "message_key": f"payout.{state}",
            "protection_active": protection_active, "protection_ends_at": deal.protection_ends_at,
            "funded_scheduled_arrival_floor_at": deal.funded_scheduled_arrival_floor_at,
            "earliest_release_at": gate,
            "server_time": at, "eligible_at": payout.eligible_at,
            "blocking_reason": reason, "available_actions": list(dict.fromkeys(actions)),
            "updated_at": payout.updated_at, "sent_at": payout.sent_at, "paid_at": payout.paid_at,
            "destination_scope": "funded_snapshot"}
