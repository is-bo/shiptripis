"""Problem reports on a parcel (spec 12, plan L9A).

A problem is a party's statement that something went wrong with a delivery.
It is recorded, the other party is told, and the serious kinds go straight to
staff. It never changes the deal: no status, no column, no money. The existing
dispute, cancellation and no-show actions remain the only paths with money
consequences (plan 1.5 rule 3).
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q


class ShipmentProblem(models.Model):
    class Kind(models.TextChoices):
        SENDER_UNAVAILABLE = "sender_unavailable", "The sender did not come"
        TRAVELER_NO_SHOW = "traveler_no_show", "The traveler did not come"
        RECIPIENT_UNAVAILABLE = "recipient_unavailable", "Recipient unavailable"
        PARCEL_MISMATCH = "parcel_mismatch", "Parcel does not match"
        PARCEL_DAMAGED = "parcel_damaged", "Parcel damaged"
        TRIP_DISRUPTED = "trip_disrupted", "Trip cancelled or delayed"
        CUSTOMS_DELAY = "customs_delay", "Customs delay"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        #: Recorded and the other party told; not in front of staff yet.
        OPEN = "open", "Open"
        #: In front of staff, waiting for someone to look at it.
        ESCALATED = "escalated", "Escalated to staff"
        #: A staff member has looked at it and is on it.
        ACKNOWLEDGED = "acknowledged", "Acknowledged"
        CLOSED = "closed", "Closed"

    class Role(models.TextChoices):
        SENDER = "sender", "Sender"
        TRAVELER = "traveler", "Traveler"

    #: The two no-show kinds (spec 12). Each may be reported only by the party
    #: it names the other side of, and only inside the no-show window.
    NO_SHOW_KINDS = frozenset({Kind.SENDER_UNAVAILABLE, Kind.TRAVELER_NO_SHOW})
    #: Kinds that go to staff the moment they are reported.
    ESCALATED_KINDS = frozenset(
        {
            Kind.PARCEL_DAMAGED,
            Kind.PARCEL_MISMATCH,
            Kind.SENDER_UNAVAILABLE,
            Kind.TRAVELER_NO_SHOW,
        }
    )
    LIVE_STATUSES = (Status.OPEN, Status.ESCALATED, Status.ACKNOWLEDGED)

    deal = models.ForeignKey(
        "deals.Deal", on_delete=models.PROTECT, related_name="problems"
    )
    reported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    reporter_role = models.CharField(max_length=10, choices=Role.choices)
    kind = models.CharField(max_length=24, choices=Kind.choices)
    #: The reporter's own words. Both parties of the deal and staff read it.
    note = models.TextField(blank=True, default="", max_length=1000)
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.OPEN, db_index=True
    )
    escalated_at = models.DateTimeField(null=True, blank=True)
    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    #: Staff-internal, like every staff reason: never sent to a member.
    acknowledged_reason = models.CharField(max_length=500, blank=True, default="")
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_reason = models.CharField(max_length=500, blank=True, default="")
    #: Set when the report was closed by recording a no-show: the audit row of
    #: that decision.
    closed_by_audit = models.ForeignKey(
        "admin_panel.AdminAuditLog",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "problems_shipment_problem"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["deal", "-created_at"], name="problems_deal_idx"),
            models.Index(fields=["status", "-created_at"], name="problems_queue_idx"),
        ]
        constraints = [
            # One live report per person, deal and kind. This is the spec's
            # "one open no-show report per person per delivery" (each person
            # has exactly one no-show kind) and it keeps a double tap or a
            # retried request from filing the same problem twice.
            models.UniqueConstraint(
                fields=["deal", "reported_by", "kind"],
                condition=~Q(status="closed"),
                name="problems_one_live_per_reporter_kind",
            ),
            models.CheckConstraint(
                condition=(
                    Q(status="closed")
                    & Q(closed_by__isnull=False, closed_at__isnull=False)
                    & ~Q(closed_reason="")
                )
                | (
                    ~Q(status="closed")
                    & Q(
                        closed_by__isnull=True, closed_at__isnull=True, closed_reason=""
                    )
                ),
                name="problems_closed_consistent",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        acknowledged_by__isnull=True,
                        acknowledged_at__isnull=True,
                        acknowledged_reason="",
                    )
                    | (
                        Q(acknowledged_by__isnull=False, acknowledged_at__isnull=False)
                        & ~Q(acknowledged_reason="")
                    )
                ),
                name="problems_acknowledged_consistent",
            ),
            models.CheckConstraint(
                condition=~Q(status="acknowledged") | Q(acknowledged_at__isnull=False),
                name="problems_acknowledged_has_decision",
            ),
            models.CheckConstraint(
                condition=~Q(status="escalated") | Q(escalated_at__isnull=False),
                name="problems_escalated_has_time",
            ),
        ]

    @property
    def is_no_show(self) -> bool:
        return self.kind in self.NO_SHOW_KINDS

    def __str__(self) -> str:
        return f"Problem #{self.pk} {self.kind} on deal #{self.deal_id} ({self.status})"
