from django.urls import path

from .views import (
    NotificationListView,
    mark_all_read,
    mark_read,
    unread_count,
)

urlpatterns = [
    path("notifications", NotificationListView.as_view(), name="notification-list"),
    path("notifications/unread-count", unread_count, name="notification-unread-count"),
    path("notifications/read-all", mark_all_read, name="notification-read-all"),
    path("notifications/<int:pk>/read", mark_read, name="notification-read"),
]
