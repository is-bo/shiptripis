"""The AI helper's API, mounted at ``/api/admin/helper/v1/`` (plans L15 and L16).

The route names are on L14's `OPEN_STAFF_API_ROUTES`: they take a helper key,
never a console session, so the session's second step does not apply to them.
"""

from django.urls import path

from . import views

urlpatterns = [
    path("guide", views.GuideView.as_view(), name="admin-helper-guide"),
    path("briefing", views.BriefingView.as_view(), name="admin-helper-briefing"),
    path("queues/<slug:code>", views.QueueView.as_view(), name="admin-helper-queue"),
    path(
        "records/<slug:record_type>/<int:pk>",
        views.RecordView.as_view(),
        name="admin-helper-record",
    ),
    path("search", views.SearchView.as_view(), name="admin-helper-search"),
    path("tasks", views.TasksView.as_view(), name="admin-helper-tasks"),
    path("actions", views.ActionsView.as_view(), name="admin-helper-actions"),
]
