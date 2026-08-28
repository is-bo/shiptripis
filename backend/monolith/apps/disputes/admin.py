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
        "content_sha256",
        "created_at",
    )
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):  # noqa: ARG002
        return False


@admin.register(Dispute)
class DisputeAdmin(_ReadOnlyAdmin):
    list_display = (
        "id",
        "deal",
        "status",
        "category",
        "opened_by",
        "opened_by_role",
        "payout_frozen",
        "payout_already_settled",
        "resolution",
        "collected_total_eur_cents",
        "sender_refund_eur_cents",
        "traveler_payout_eur_cents",
        "platform_fee_eur_cents",
        "opened_at",
        "resolved_at",
    )
    list_filter = ("status", "category", "resolution", "opened_at")
    search_fields = ("public_reference", "deal__id", "opened_by__email")
    date_hierarchy = "opened_at"
    inlines = (DisputeEvidenceInline, DisputeEventInline)
    fields = (
        "public_reference",
        "deal",
        "status",
        "category",
        "reason_text",
        "opened_by",
        "opened_by_role",
        "opened_at",
        "protection_ends_at",
        "payout_frozen",
        "payout_already_settled",
        "resolution",
        "collected_total_eur_cents",
        "sender_refund_eur_cents",
        "traveler_payout_eur_cents",
        "platform_fee_eur_cents",
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
