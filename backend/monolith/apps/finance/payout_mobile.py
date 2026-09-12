"""H6A read model. No routing, eligibility, settlement or FX writes here."""

from django.conf import settings
from django.db.models import Prefetch, Q
from django.utils import timezone

from .models import FinanceHold, Payout, PayoutProfileReview, TravelerPayoutMethod
from .payout_accounts import allowed_countries, evaluate_readiness, expected_mode
from .payout_manual_profiles import approved_profile


def methods_for(user):
    return TravelerPayoutMethod.objects.filter(traveler=user).select_related(
        "current_version__stripe_account", "current_version__dzd_profile_revision__evidence"
    ).order_by("currency")


def eur_method(method):
    version = method.current_version if method else None
    account = version.stripe_account if version else None
    countries = list(allowed_countries())
    country = version.country if version else ""
    available = bool(settings.STRIPE_CONNECT_ENABLED and countries)
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
    elif version:
        state = "setup_required"
    if country and country not in countries:
        reason = "payout_country_unsupported"
        available = False
    actions = []
    account_usable = bool(account and account.active and account.provider_mode == expected_mode()
                          and account.platform_id == settings.STRIPE_CONNECT_PLATFORM_ACCOUNT_ID)
    if available:
        if account_usable:
            actions.append("refresh")
            if account.details_submitted:
                actions.append("manage_eur")
            if state == "setup_required" and method.enabled:
                actions.append("resume_eur_setup")
        elif not account and (not method or method.enabled):
            actions.append("configure_eur")
    return {"state": state, "ready": state == "ready", "blocking_reason": reason or None,
            "available_actions": actions, "country": country or None,
            "supported_countries": countries, "supported": available,
            "checked_at": account.readiness_checked_at if account else None}


def dzd_method(method):
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
    return {"state": state, "ready": state == "ready", "blocking_reason": reason,
            "available_actions": ["replace_dzd_profile" if profile else "configure_dzd"],
            "country": "DZ", "supported": True,
            "profile": {"reference": str(profile.public_reference),
                        "review_state": review.status if review else "pending_review",
                        "ccp_last_four": profile.ccp_last_four, "rip_last_four": profile.rip_last_four,
                        "submitted_at": profile.submitted_at} if profile else None,
            "replacement_scope": "future_payouts_only"}


def payout_summary(user, methods=None):
    methods = list(methods if methods is not None else methods_for(user))
    by_currency = {m.currency: m for m in methods}
    enabled = {m.currency for m in methods if m.enabled}
    preference = "both" if len(enabled) == 2 else "eur_only" if "EUR" in enabled else "dzd_only" if enabled else None
    eur, dzd = eur_method(by_currency.get("EUR")), dzd_method(by_currency.get("DZD"))
    return {"contract_version": "h6a.v1", "preference": preference,
            "preference_required": preference is None,
            "revisions": {c: by_currency[c].revision if c in by_currency else 0 for c in ("EUR", "DZD")},
            "eur": eur, "dzd": dzd,
            "available_actions": list(dict.fromkeys(eur["available_actions"] + dzd["available_actions"])),
            "preference_scope": "future_payouts_only"}


def payouts_for(user):
    return payout_read_rows(Payout.objects.filter(traveler=user)).order_by("-created_at", "-pk")


def payout_read_rows(rows):
    """Load the bounded Finance/mobile page without a query per payout."""
    return rows.select_related(
        "deal", "stripe_account", "active_instruction_version__stripe_account",
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
                "actions": [], "profiles": {}}
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
            "actions": payout_summary(user or payouts[0].traveler)["available_actions"] if include_actions else [],
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
    if state == "needs_attention" and reason in ("payout_setup_required", "payout_profile_needs_attention"):
        # Current setup can differ from this funded destination. Do not promise
        # that editing the current method will repair a historical instruction.
        actions += context["actions"] if context else payout_summary(payout.traveler)["available_actions"]
    return {"reference": str(payout.public_reference), "deal_id": deal.pk,
            "rail": "stripe_eur" if payout.method == "stripe_transfer" else "manual_dzd" if payout.method == "manual" and payout.payout_currency == "DZD" else "unavailable",
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
