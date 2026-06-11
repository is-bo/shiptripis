from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("id", "recipient", "channel", "event_id", "read_at", "created_at")
    list_filter = ("channel", "read_at")
    search_fields = ("event_id", "recipient__email")
    readonly_fields = ("recipient", "channel", "event_id", "payload", "created_at")
    ordering = ("-created_at",)
