"""H6A read model. No routing, eligibility, settlement or FX writes here."""

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from .models import FinanceHold, Payout, TravelerPayoutMethod
from .payout_accounts import allowed_countries, evaluate_readiness, expected_mode
from .payout_domain import active_holds
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
    return Payout.objects.filter(traveler=user).select_related(
        "deal", "stripe_account", "active_instruction_version__stripe_account",
        "active_instruction_version__dzd_profile_revision__evidence",
        "active_instruction_version__dzd_profile_revision__method",
    ).prefetch_related(
        "disbursement_allocations__disbursement", "funding_allocations",
        "active_instruction_version__dzd_profile_revision__reviews",
    ).order_by("-created_at", "-pk")


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


def page_context(payouts, *, user=None):
    """One bounded pass over a whole history page.

    Dispute, hold and setup lookups are per-payout facts, so a list that asks
    each row for them separately costs queries proportional to the page size.
    Everything the page needs is read here instead, and `payout_status` then
    answers from memory.
    """

    from apps.disputes.models import Dispute

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
    return {"disputed": disputed, "held": held, "account_holds": scopes["account_id"],
            "actions": payout_summary(user or payouts[0].traveler)["available_actions"],
            # Memo per DZD profile revision, not per row: a history is normally
            # many payouts bound to one or two versions of the same profile.
            "profiles": {}}


def _profile_verdict(profile, context):
    """`(approved, reviewed)` for one DZD profile revision, read at most once."""

    if profile is None:
        return False, False
    memo = context["profiles"] if context is not None else None
    if memo is None or profile.pk not in memo:
        verdict = (approved_profile(profile), profile.reviews.exists())
        if memo is None:
            return verdict
        memo[profile.pk] = verdict
    return memo[profile.pk]


def payout_status(payout, *, at=None, context=None):
    """Expired protection alone never upgrades a not-yet-released obligation."""
    from apps.disputes.models import Dispute

    at = at or timezone.now()
    deal = payout.deal
    protection_active = bool(deal.protection_ends_at and at < deal.protection_ends_at)
    state, reason = "awaiting_delivery", None
    if deal.delivery_confirmed_at:
        state = "protection_active" if protection_active else "release_pending"
    version = payout.active_instruction_version
    bank = bank_stage(payout)

    # Read from the page's single pass when there is one, and otherwise only if
    # the settlement facts above have not already decided the state.
    def disputed():
        if context is not None:
            return deal.pk in context["disputed"]
        return (Dispute.objects.filter(deal_id=deal.pk)
                .exclude(status__in=["resolved", "closed"]).exists())

    def held():
        if context is not None:
            return payout.pk in context["held"]
        return active_holds(payout).exists()

    actions = ["view_payout", "refresh"]
    if bank and bank[1]:
        # A returned or failed bank payout outranks every local status — including
        # a `paid` the same disbursement recorded before the money came back.
        state, reason = bank
    elif payout.status == "paid" or (bank and bank[0] == "paid"):
        state = "paid"
    elif payout.status == "cancelled":
        state = "cancelled"
    elif payout.status == "sent" or (bank and bank[0] == "sent"):
        state = "sent"
    elif payout.status == "failed":
        state, reason = "needs_attention", "payout_failed"
    elif disputed():
        state, reason = "needs_attention", "dispute_active"
    elif payout.status == "frozen" or held():
        state, reason = "needs_attention", "payout_on_hold"
    elif protection_active:
        state, reason = "protection_active", "protection_active"
    elif payout.status == "processing" or (bank and bank[0] == "processing"):
        state = "processing"
    elif payout.status in ("eligible", "scheduled", "blocked"):
        reason = "payout_setup_required" if payout.block_reason == "payout_setup_required" else "payout_on_hold" if payout.block_reason else None
        if payout.method == "stripe_transfer" and version and version.stripe_account:
            account = version.stripe_account
            verdict = evaluate_readiness(
                account,
                holds_exist=account.pk in context["account_holds"] if context else None,
            )
            if not verdict.ready:
                reason = "payout_profile_under_review" if verdict.status == "pending_review" else "payout_setup_required" if verdict.status == "setup_required" else "payout_profile_needs_attention"
        elif payout.method == "manual":
            profile = version.dzd_profile_revision if version else None
            approved, reviewed = _profile_verdict(profile, context)
            if not approved:
                reason = ("payout_profile_needs_attention" if reviewed
                          else "payout_profile_under_review" if profile else "payout_setup_required")
        state = "needs_attention" if reason or payout.status == "blocked" else "ready"
        if state == "needs_attention" and not reason:
            reason = "payout_on_hold"
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
            "server_time": at, "eligible_at": payout.eligible_at,
            "blocking_reason": reason, "available_actions": list(dict.fromkeys(actions)),
            "updated_at": payout.updated_at, "sent_at": payout.sent_at, "paid_at": payout.paid_at,
            "destination_scope": "funded_snapshot"}
