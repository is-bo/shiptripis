"""H0 routing freezes intent at funding; readiness never selects currency."""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import (
    PaymentAttempt,
    PaymentOrder,
    Payout,
    PayoutEvent,
    TravelerPayoutMethod,
)
from .money import convert_eur_cents
from .policy import phase3_policy, InvalidPaymentPolicy
from apps.core.business_settings import NoActiveBusinessSettings


def funding_attempt(order):
    """Balance capture authority, with credited-deposit-only fallback."""
    attempt = (
        PaymentAttempt.objects.filter(
            order=order,
            status="succeeded",
            is_unapplied=False,
            succeeded_at__isnull=False,
        )
        .order_by("-succeeded_at", "-pk")
        .first()
    )
    if (
        attempt is None
        and order.credit_source_id
        and order.credited_eur_cents > 0
        and order.paid_eur_cents == 0
        and order.outstanding_eur_cents == 0
    ):
        attempt = (
            PaymentAttempt.objects.filter(
                order_id=order.credit_source_id,
                status="succeeded",
                is_unapplied=False,
                succeeded_at__isnull=False,
            )
            .order_by("-succeeded_at", "-pk")
            .first()
        )
    return attempt


def choose_method(methods, provider):
    by_currency = {m.currency: m for m in methods if m.enabled}
    if len(by_currency) == 2:
        return (
            by_currency.get("EUR" if provider == "stripe" else "DZD")
            if provider in ("stripe", "chargily")
            else None
        )
    return next(iter(by_currency.values()), None)


def preflight(*, order, provider, policy):
    from .services import FinanceError

    if not settings.PAYOUT_PROFILES_ENABLED or order.purpose != "deal_balance":
        return
    methods = list(
        TravelerPayoutMethod.objects.filter(
            traveler_id=order.deal.traveler_id, enabled=True
        )
    )
    method = choose_method(methods, provider)
    if method is None:
        raise FinanceError("Payout preference required before funding.")
    if method.currency == "EUR" and provider != "stripe":
        raise FinanceError("This payout requires Stripe funding.")
    if method.currency == "EUR":
        # H1 never enables multi-processor EUR, even if an env flag is set.
        source_ids = source_order_ids(order)
        if (
            PaymentAttempt.objects.filter(
                order_id__in=source_ids, status="succeeded", is_unapplied=False
            )
            .exclude(provider="stripe")
            .exists()
        ):
            raise FinanceError("Mixed funding requires payout route review.")
    elif (
        type(policy.chargily.eur_dzd_rate_micros) is not int
        or policy.chargily.eur_dzd_rate_micros <= 0
    ):
        raise FinanceError("Authoritative payout FX is unavailable.")


def source_order_ids(order):
    from apps.boosts.models import BoostPurchase

    ids = [order.pk]
    if order.credit_source_id and order.credited_eur_cents:
        ids.append(order.credit_source_id)
    ids.extend(
        BoostPurchase.objects.filter(deal_id=order.deal_id)
        .order_by("pk")
        .values_list("payment_order_id", flat=True)
    )
    return [pk for pk in ids if pk is not None]


@transaction.atomic
def create_snapshot(*, deal_id, traveler_id, amount_eur_cents, order=None):
    from apps.core.financial_locks import lock_deal_aggregate
    from .money import require_positive_cents

    require_positive_cents(amount_eur_cents)
    # Funding callers already hold the aggregate. Standalone/replay callers
    # still serialize on Deal before any payout or destination access.
    deal = lock_deal_aggregate(deal_id).deal
    if deal.traveler_id != traveler_id:
        raise ValidationError("Payout traveler does not own this Deal.")
    existing = Payout.objects.filter(deal_id=deal_id).first()
    if existing:
        return existing
    order = (
        order
        or PaymentOrder.objects.filter(deal_id=deal_id, purpose="deal_balance")
        .exclude(status="cancelled")
        .order_by("-pk")
        .first()
    )
    if order and (order.deal_id != deal_id or order.purpose != "deal_balance"):
        raise ValidationError("Payout funding order does not belong to this Deal.")
    source = funding_attempt(order) if order else None
    provider = source.provider if source else ""
    methods = list(
        TravelerPayoutMethod.objects.select_for_update(no_key=True)
        .filter(traveler_id=traveler_id)
        .order_by("pk")
    )
    method = choose_method(methods, provider)
    now = timezone.now()
    values = dict(
        deal_id=deal_id,
        traveler_id=traveler_id,
        amount_eur_cents=amount_eur_cents,
        funded_amount_eur_cents=amount_eur_cents,
        snapshot_version=1,
        routing_policy_version="payout_routing_v1",
        snapshot_at=now,
        funding_attempt=source,
        funding_provider_snapshot=provider,
        provider_mode=source.provider_mode if source else "legacy_unknown",
        state_version=1,
    )
    block = ""
    if method is None:
        values.update(method="undecided", block_reason="payout_preference_required")
    else:
        version = method.current_version
        values.update(
            method="manual" if method.currency == "DZD" else "stripe_transfer",
            payout_currency=method.currency,
            payout_amount_exponent=0 if method.currency == "DZD" else 2,
            method_version=version,
            active_instruction_version=version,
        )
        if version and (
            version.method_id != method.pk or version.currency != method.currency
        ):
            # Preserve captured money but do not trust an inconsistent binding.
            version = None
            values.update(method_version=None, active_instruction_version=None)
        if not version:
            block = "payout_setup_required"
        else:
            values.update(
                stripe_account=version.stripe_account,
                dzd_profile_revision=version.dzd_profile_revision,
            )
            if (
                version.dzd_profile_revision
                and version.dzd_profile_revision.method_id != method.pk
            ):
                values["dzd_profile_revision"] = None
                block = "payout_setup_required"
            if method.status != "ready":
                block = "payout_setup_required"
        if method.currency == "EUR":
            values.update(
                payout_amount_minor=amount_eur_cents,
                original_settlement_amount_minor=amount_eur_cents,
            )
            if provider != "stripe":
                block = "funding_route_unavailable"
            elif (
                order
                and PaymentAttempt.objects.filter(
                    order_id__in=source_order_ids(order),
                    status="succeeded",
                    is_unapplied=False,
                )
                .exclude(provider="stripe")
                .exists()
            ):
                block = "funding_route_unavailable"
            account = version.stripe_account if version else None
            if account and (
                account.traveler_id != traveler_id
                or account.provider_mode != values["provider_mode"]
            ):
                block = "provider_mode_mismatch"
                values["stripe_account"] = None
            elif (
                not account
                or not account.active
                or not account.payouts_enabled
                or account.transfers_status != "active"
                or not account.eur_bank_present
            ):
                block = block or "payout_setup_required"
        else:
            rate = settings_version = snapshot_at = fx_source = None
            if source and provider == "chargily":
                rate, settings_version, snapshot_at, fx_source = (
                    source.fx_rate_micros,
                    source.fx_settings_version,
                    source.fx_snapshot_at,
                    source.fx_source,
                )
                values["fx_source_attempt"] = source
            elif source and provider == "stripe":
                try:
                    policy = phase3_policy()
                    rate, settings_version, snapshot_at, fx_source = (
                        policy.chargily.eur_dzd_rate_micros,
                        policy.settings_version,
                        now,
                        "business_settings",
                    )
                except (InvalidPaymentPolicy, NoActiveBusinessSettings):
                    pass
            if (
                type(rate) is int
                and rate > 0
                and settings_version
                and snapshot_at
                and fx_source
            ):
                amount = convert_eur_cents(
                    amount_eur_cents, to_currency="DZD", rate_micros=rate
                )
                values.update(
                    fx_rate_micros=rate,
                    fx_settings_version=settings_version,
                    fx_snapshot_at=snapshot_at,
                    fx_source=fx_source[:64],
                    payout_amount_minor=amount,
                    original_settlement_amount_minor=amount,
                    rounding_policy="ceil_whole_dzd_v1",
                )
            else:
                block = "fx_snapshot_missing"
        if (
            values["provider_mode"] == "legacy_unknown"
            and block != "fx_snapshot_missing"
        ):
            block = "funding_mode_unknown"
        values["block_reason"] = block
    # Protection is still open; block_reason is the separate setup projection.
    payout = Payout.objects.create(**values)
    PayoutEvent.objects.create(
        payout=payout,
        sequence=1,
        new_state=payout.status,
        reason_code="funding_snapshot",
    )
    from datetime import timedelta
    from .services import schedule_job
    from .models import ScheduledJob

    schedule_job(
        kind=ScheduledJob.Kind.PAYOUT_RELEASE_CHECK,
        key=f"payout_release_check:{payout.pk}",
        run_at=now + timedelta(hours=48),
        payload={"payout_id": payout.pk},
    )
    return payout
