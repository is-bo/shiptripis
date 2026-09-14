"""Owner-scoped SQL resolution before pagination; reading is independent.

Action notifications follow their authoritative entities. Informational events
remain in the inbox until viewed. History retains every row and original payload.
"""
from django.db.models import BigIntegerField, BooleanField, Case, CharField, Exists, OuterRef, Q, Value, When
from django.db.models.functions import Cast
from django.db.models.fields.json import KeyTextTransform
from django.utils import timezone

from .models import Notification


def resolved_notifications(user, *, at=None):
    from apps.chat.models import ChatMessage
    from apps.deals.activity import activity_q
    from apps.deals.models import Deal
    from apps.disputes.models import Dispute
    from apps.finance.payout_mobile import payout_summary, payout_read_rows, page_context, payout_attention
    from apps.finance.models import Payout
    from apps.matching.models import Offer
    from apps.ratings.models import Rating
    from apps.ratings.services import RATABLE_STATUSES, with_review_deadline
    from apps.deals.lifecycle import IN_CARRIAGE_STATUSES

    at = at or timezone.now()
    rows = Notification.objects.filter(recipient=user)
    # Legacy payloads are untyped. Bound and validate IDs before casting so a
    # malformed historic event cannot break the entire inbox.
    for name in ("deal_id", "match_id", "message_id", "offer_id"):
        rows = rows.alias(**{f"_{name}": Case(
            When(**{f"payload__{name}__regex": r"^[1-9][0-9]{0,17}$"},
                 then=Cast(KeyTextTransform(name, "payload"), BigIntegerField())),
            default=Value(None), output_field=BigIntegerField(),
        )})
    deals = Deal.objects.filter(Q(sender=user) | Q(traveler=user)).filter(
        Q(pk=OuterRef("_deal_id")) | Q(match_id=OuterRef("_match_id"))
    )
    rated = Rating.objects.filter(deal_id=OuterRef("pk"), rater=user)
    prior_dispute = Dispute.objects.filter(deal_id=OuterRef("pk"), status__in=[*Dispute.ACTIVE_STATUSES, "resolved"])
    rateable = with_review_deadline(deals).filter(
        delivery_confirmed_at__isnull=False, status__in=RATABLE_STATUSES,
        review_deadline__gt=at,
    ).alias(_rated=Exists(rated)).filter(_rated=False)
    disputable = deals.filter(
        Q(status__in=IN_CARRIAGE_STATUSES)
        | (Q(delivery_confirmed_at__isnull=False) &
           (Q(protection_ends_at__gt=at) | Q(protection_ends_at__isnull=True)))
    ).alias(_prior=Exists(prior_dispute)).filter(_prior=False)
    summary = payout_summary(user)
    # Funded setup events belong to their frozen instruction, never today's
    # preference. Reuse Finance's batched authoritative blocker projection.
    references = rows.filter(channel="payout.status_changed", payload__event="setup_required").annotate(
        reference=KeyTextTransform("payout_reference", "payload")).values("reference")
    payouts = list(payout_read_rows(Payout.objects.filter(traveler=user).exclude(status__in=["paid", "cancelled"]).alias(
        _reference=Cast("public_reference", CharField())).filter(_reference__in=references)))
    context = page_context(payouts, include_actions=False)
    setup_pending = [str(p.public_reference) for p in payouts if
                     payout_attention(p, context=context)["block_reason"] in
                     ("payout_setup_required", "payout_profile_needs_attention")]
    rows = rows.alias(
        _owned_deal=Exists(deals),
        _payment=Exists(deals.filter(activity_q("active"), sender=user, funded_at__isnull=True)),
        _arrival=Exists(deals.filter(sender=user, delivery_confirmed_at__isnull=True,
                                    arrival_reports__status="pending_confirmation").filter(activity_q("active"))),
        _rating=Exists(rateable),
        _dispute=Exists(disputable),
        _recipient=Exists(deals.filter(sender=user, funded_at__isnull=False,
                                       recipient__isnull=True).filter(activity_q("active"))),
        _delivery_code=Exists(deals.filter(sender=user, delivery_confirmed_at__isnull=True,
                                           funded_at__isnull=False).filter(activity_q("active"))),
        _chat=Exists(ChatMessage.objects.filter(pk=OuterRef("_message_id"), read_at__isnull=True)
                     .filter(Q(match__sender=user) | Q(match__traveler=user)).exclude(sender=user)),
        _offer=Exists(Offer.objects.filter(Q(match__sender=user) | Q(match__traveler=user))
                      .filter(pk=OuterRef("_offer_id"), status="pending")
                      .exclude(proposer=user)
                      .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=at))),
    )
    return rows.annotate(resolved=Case(
        When(channel__in=["offer.accepted", "payment.failed", "payment.required"], _owned_deal=True,
             then=~Q(_payment=True)),
        When(channel="deal.arrival_reported", then=~Q(_arrival=True)),
        When(channel__in=["rating.required", "rating.prompt"], then=~Q(_rating=True)),
        When(channel="dispute.action_required", then=~Q(_dispute=True)),
        When(channel="recipient.required", then=~Q(_recipient=True)),
        When(channel="handover.delivery_code_available", then=~Q(_delivery_code=True)),
        When(channel="chat.message.new", then=~Q(_chat=True)),
        When(channel__in=["offer.created", "offer.updated"], then=~Q(_offer=True)),
        When(channel="payout.status_changed", payload__event="setup_required",
             then=~Q(payload__payout_reference__in=setup_pending) if setup_pending else Value(True)),
        When(channel="payout.status_changed", payload__event="profile_needs_attention", payload__currency="EUR",
             then=Value(summary["eur"]["ready"])),
        When(channel="payout.status_changed", payload__event="profile_needs_attention", payload__currency="DZD",
             then=Value(summary["dzd"]["ready"])),
        When(channel="deal.updated", then=Value(True)),
        default=Q(read_at__isnull=False), output_field=BooleanField(),
    ))
