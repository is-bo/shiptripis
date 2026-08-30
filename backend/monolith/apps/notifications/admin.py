"""Notification and transactional-email operations.

`OutboundMessage` is the durable obligation behind every transactional email:
the row exists before a send is attempted, survives a worker restart, and
carries the failure when a send does not get through. Until now it had no admin
at all, so "did the verification email go out, and why is that address
bouncing" was a question an operator could only answer from logs.

**It is registered read-only, and it never renders a secret.** The delivery
code is not stored on the row: the message carries a `secret_ref`, a sealed
reference, and the plaintext is opened only inside the final trusted renderer
at send time. This admin shows whether a message carries such a reference — it
does not show the reference, and there is nothing here that could resolve one.
"""

from django.contrib import admin

from apps.core.admin_display import TONE_MUTE, flag, status

from .models import Notification, OutboundMessage


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("id", "recipient", "channel", "event_id", "read_at", "created_at")
    list_filter = ("channel", "read_at")
    search_fields = ("event_id", "recipient__email")
    readonly_fields = ("recipient", "channel", "event_id", "payload", "created_at")
    list_select_related = ("recipient",)
    ordering = ("-created_at",)


@admin.register(OutboundMessage)
class OutboundMessageAdmin(admin.ModelAdmin):
    # A failing send is read as: what was it, who to, how many tries are left,
    # and what did the transport say. The two timestamps that used to sit here
    # pushed that last column off the table; they are on the detail page.
    list_display = (
        "id",
        "created_at",
        "kind",
        "language",
        "to_email",
        "status_chip",
        "attempt_count",
        "sealed_chip",
        "failure",
    )
    status_chip = status("status", "Status")
    #: Deliberately a yes/no, never the reference itself. It answers "is this
    #: one of the messages whose body is assembled at the trusted boundary",
    #: which is what an operator reading a failure needs to know.
    sealed_chip = flag(
        "secret_ref",
        "Sealed secret",
        true_tone=TONE_MUTE,
        false_tone=TONE_MUTE,
        true_text="Yes",
        false_text="No",
    )
    list_filter = ("status", "kind", "language", "channel", "created_at")
    search_fields = ("key", "to_email", "transport_event_id", "last_error")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    list_select_related = ("recipient_user", "deal")
    readonly_fields = (
        "key",
        "kind",
        "channel",
        "to_email",
        "recipient_user",
        "deal",
        "context",
        "language",
        "carries_sealed_secret",
        "status",
        "attempts",
        "max_attempts",
        "next_attempt_at",
        "last_error",
        "transport_event_id",
        "dispatched_at",
        "created_at",
        "updated_at",
    )
    exclude = ("secret_ref",)

    @admin.display(description="Last transport error", ordering="last_error")
    def failure(self, obj):
        if not obj.last_error:
            return "—"
        return obj.last_error if len(obj.last_error) <= 70 else obj.last_error[:69] + "…"

    @admin.display(description="Attempts", ordering="attempts")
    def attempt_count(self, obj):
        """`5 / 10` reads as a position in a budget; `5` reads as nothing."""

        return f"{obj.attempts} / {obj.max_attempts}"

    @admin.display(description="Carries a sealed secret")
    def carries_sealed_secret(self, obj):
        return "Yes — resolved only by the sender at render time" if obj.secret_ref else "No"

    def has_add_permission(self, request):  # noqa: ARG002
        return False

    def has_change_permission(self, request, obj=None):  # noqa: ARG002
        return False

    def has_delete_permission(self, request, obj=None):  # noqa: ARG002
        # The row is the record that an obligation existed. Deleting it would
        # delete the evidence, not the message.
        return False
