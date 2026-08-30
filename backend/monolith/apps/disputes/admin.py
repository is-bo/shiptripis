"""Operations views over disputes, their timelines and their evidence.

Everything is registered read-only. A dispute's state machine, its evidence
budget and above all its resolution are enforced by
`apps.disputes.services` under the Deal aggregate lock: the resolution writes
three amounts that have to reconcile with the money the platform actually
collected, raises the refunds, and moves the Deal to its terminal status in one
transaction. An administrator who could edit `status` or `sender_refund_eur_cents`
by hand could produce a dispute that claims money moved when none did, which is
exactly what `disputes_resolution_reconciles` exists to prevent.

Evidence is listed but never rendered here. The file itself lives in a private
bucket and is reached through a signed URL issued by the API after an
authorization check, so `storage_bucket` and `storage_key` are deliberately
absent from every display, field list and search — an admin page is not an
audited access path.

No code material appears anywhere below, and none is reachable from here.
"""

from __future__ import annotations

from django.contrib import admin
from django.template.loader import render_to_string
from django.utils.html import format_html

from apps.core.admin_display import TONE_BAD, flag, format_eur, money, status, tone_for

from .models import Dispute, DisputeEvent, DisputeEvidence


class _ReadOnlyAdmin(admin.ModelAdmin):
    """No add, no change, no delete. A dispute's history is not editable."""

    def has_add_permission(self, request):  # noqa: ARG002
        return False

    def has_change_permission(self, request, obj=None):  # noqa: ARG002
        return False

    def has_delete_permission(self, request, obj=None):  # noqa: ARG002
        return False


class DisputeEventInline(admin.TabularInline):
    model = DisputeEvent
    extra = 0
    can_delete = False
    fields = ("kind", "actor", "payload", "created_at")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):  # noqa: ARG002
        return False


class DisputeEvidenceInline(admin.TabularInline):
    model = DisputeEvidence
    extra = 0
    can_delete = False
    fields = (
        "kind",
        "submitted_by",
        "text",
        "content_type",
        "size_bytes",
        "digest",
        "created_at",
    )
    readonly_fields = fields

    @admin.display(description="Digest")
    def digest(self, obj: DisputeEvidence) -> str:
        """A prefix, with the whole hash on hover.

        Nobody compares 64 hex characters by eye, and printing them took a
        third of the row away from the columns that are read.
        """

        if not obj.content_sha256:
            return "—"
        return format_html(
            '<code title="sha256:{}">{}…</code>',
            obj.content_sha256,
            obj.content_sha256[:12],
        )

    def has_add_permission(self, request, obj=None):  # noqa: ARG002
        return False


@admin.register(Dispute)
class DisputeAdmin(_ReadOnlyAdmin):
    # Ordered for scanning rather than for the model: what state is this in,
    # is money currently frozen, what was decided, and only then the four
    # amounts that have to reconcile with each other.
    list_display = (
        "id",
        "deal",
        "status_chip",
        "category",
        "frozen_chip",
        "settled_chip",
        "resolution_chip",
        "collected_display",
        "sender_refund_display",
        "traveler_payout_display",
        "platform_fee_display",
        "opened_by",
        "opened_at",
        "resolved_at",
    )
    status_chip = status("status", "Status")
    resolution_chip = status("resolution", "Resolution")
    # A frozen payout is the reason this queue exists, so it is an alarm; a
    # payout that already settled before the dispute opened is worse, because
    # the money is gone and any resolution has to be reconciled by hand.
    frozen_chip = flag(
        "payout_frozen", "Payout", true_text="Frozen", false_text="Not frozen"
    )
    settled_chip = flag(
        "payout_already_settled",
        "Already settled",
        true_tone=TONE_BAD,
        true_text="Already paid",
        false_text="No",
    )
    # The collected total is what the other three have to add up to, so it is
    # the anchor of the row.
    collected_display = money("collected_total_eur_cents", "Collected", emphasis=True)
    sender_refund_display = money("sender_refund_eur_cents", "Sender refund")
    traveler_payout_display = money("traveler_payout_eur_cents", "Traveler payout")
    platform_fee_display = money("platform_fee_eur_cents", "Platform fee")
    list_filter = ("status", "category", "resolution", "opened_at")
    list_select_related = ("deal", "opened_by")
    search_fields = ("public_reference", "deal__id", "opened_by__email")
    date_hierarchy = "opened_at"
    inlines = (DisputeEvidenceInline, DisputeEventInline)
    fields = (
        "public_reference",
        "deal",
        "money_position",
        "status",
        "category",
        "reason_text",
        "opened_by",
        "opened_by_role",
        "opened_at",
        "protection_ends_at",
        "frozen_chip",
        "settled_chip",
        "resolution_chip",
        "collected_display",
        "sender_refund_display",
        "traveler_payout_display",
        "platform_fee_display",
        "resolution_note",
        "resolved_by",
        "resolved_at",
        "closed_at",
        # The captured bundle holds references only: ids, amounts, statuses and
        # instants. It is shown in full because it is what a resolution is
        # reviewed from.
        "evidence_bundle",
        "created_at",
        "updated_at",
    )
    readonly_fields = fields

    @admin.display(description="Where the money is")
    def money_position(self, obj: Dispute) -> str:
        """The payment, payout and refund state of the deal under dispute.

        Resolving a dispute means deciding what happens to money that is
        already somewhere, and until now finding out where meant opening three
        other changelists and filtering each by the deal. Every value below is
        read straight off the stored row — statuses as they are, amounts as
        `format_eur` renders the stored integer. Nothing is summed, netted or
        reconciled here; the resolution service does that, under a lock, and it
        remains the only thing that may.
        """

        deal = obj.deal
        rows = []
        for order in deal.payment_orders.all().order_by("id"):
            rows.append(
                {
                    "label": f"Payment order #{order.pk} · {order.get_purpose_display()}",
                    "state": order.get_status_display(),
                    "tone": tone_for(order.status),
                    "amount": format_eur(order.amount_eur_cents),
                    "detail": (
                        f"paid {format_eur(order.paid_eur_cents)}, "
                        f"refunded {format_eur(order.refunded_eur_cents)}"
                    ),
                }
            )
            for refund in order.refunds.all().order_by("id"):
                rows.append(
                    {
                        "label": f"Refund #{refund.pk} · {refund.get_reason_display()}",
                        "state": refund.get_status_display(),
                        "tone": tone_for(refund.status),
                        "amount": format_eur(refund.amount_eur_cents),
                        "detail": (
                            "manual action required"
                            if refund.requires_manual_action
                            else refund.failure_message or "—"
                        ),
                    }
                )
        payout = getattr(deal, "payout", None)
        if payout is not None:
            rows.append(
                {
                    "label": f"Payout #{payout.pk} · {payout.get_method_display()}",
                    "state": payout.get_status_display(),
                    "tone": tone_for(payout.status),
                    "amount": format_eur(payout.amount_eur_cents),
                    "detail": (
                        f"eligible {payout.eligible_at:%Y-%m-%d %H:%M}"
                        if payout.eligible_at
                        else "not released"
                    ),
                }
            )
        return render_to_string(
            "admin/disputes/dispute/money_position.html",
            {"rows": rows, "frozen": obj.payout_frozen, "settled": obj.payout_already_settled},
        )


@admin.register(DisputeEvent)
class DisputeEventAdmin(_ReadOnlyAdmin):
    list_display = ("id", "dispute", "kind", "actor", "created_at")
    list_filter = ("kind", "created_at")
    search_fields = ("dispute__id", "actor__email")
    date_hierarchy = "created_at"
    fields = ("dispute", "kind", "actor", "payload", "created_at")
    readonly_fields = fields


@admin.register(DisputeEvidence)
class DisputeEvidenceAdmin(_ReadOnlyAdmin):
    """Metadata only. The bytes are reached through a signed URL, not from here."""

    list_display = (
        "id",
        "dispute",
        "kind",
        "submitted_by",
        "content_type",
        "size_bytes",
        "created_at",
    )
    list_filter = ("kind", "content_type", "created_at")
    search_fields = ("dispute__id", "submitted_by__email", "content_sha256")
    date_hierarchy = "created_at"
    fields = (
        "dispute",
        "kind",
        "submitted_by",
        "text",
        "content_type",
        "size_bytes",
        "content_sha256",
        "created_at",
    )
    readonly_fields = fields
