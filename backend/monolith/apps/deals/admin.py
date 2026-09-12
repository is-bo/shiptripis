from django.contrib import admin

from apps.core.admin_display import status

from .models import (
    Deal,
    DealArrivalReport,
    DealEvent,
    DealLegAllocation,
    DealRecipient,
    DealTermsSnapshot,
)


class DealRecipientInline(admin.StackedInline):
    """The recipient, visible to operations but never editable here.

    An admin resolving a dispute has a legitimate reason to see who the parcel
    was addressed to. Nobody has a reason to *change* it from a Django admin
    page: a recipient change is a lifecycle event with a revision and a timeline
    entry, and the service that writes those is the only writer.
    """

    model = DealRecipient
    extra = 0
    can_delete = False
    readonly_fields = [field.name for field in DealRecipient._meta.fields]


class DealTermsInline(admin.StackedInline):
    model = DealTermsSnapshot
    extra = 0
    can_delete = False
    readonly_fields = [field.name for field in DealTermsSnapshot._meta.fields]


class DealLegAllocationInline(admin.TabularInline):
    model = DealLegAllocation
    extra = 0
    can_delete = False
    readonly_fields = [field.name for field in DealLegAllocation._meta.fields]


class DealArrivalReportInline(admin.TabularInline):
    """Early-arrival claims, read-only.

    An operator resolving a dispute needs to see who claimed to have arrived
    when, and what the sender answered. Nobody edits one here: a claim and its
    decision are written by `apps.deals.arrival` under the lifecycle lock, with
    a timeline event and a notification, and a second writer would make the
    audit record untrustworthy.
    """

    model = DealArrivalReport
    extra = 0
    can_delete = False
    readonly_fields = [field.name for field in DealArrivalReport._meta.fields]


class DealEventInline(admin.TabularInline):
    model = DealEvent
    extra = 0
    can_delete = False
    readonly_fields = [field.name for field in DealEvent._meta.fields]


@admin.register(Deal)
class DealAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "delivery_request",
        "journey",
        "sender",
        "traveler",
        "status_chip",
        "pickup_confirmed_at",
        "delivery_confirmed_at",
        "protection_ends_at",
        "funded_scheduled_arrival_floor_at",
        "arrival_confirmed_at",
        "created_at",
    )
    status_chip = status("status", "Status")
    list_filter = ("status", "is_legacy", "no_show_party")
    list_select_related = ("delivery_request", "journey", "sender", "traveler")
    search_fields = ("id", "delivery_request__id", "accepted_offer__id")
    date_hierarchy = "created_at"
    readonly_fields = [field.name for field in Deal._meta.fields]
    inlines = (
        DealTermsInline,
        DealRecipientInline,
        DealLegAllocationInline,
        DealArrivalReportInline,
        DealEventInline,
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
