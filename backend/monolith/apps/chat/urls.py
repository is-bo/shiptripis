from django.urls import path

from .views import (
    ChatMessageReportView,
    ChatMessagesView,
    ChatThreadsView,
    MatchBlockView,
    MyBlocksView,
    MyBlockView,
)

urlpatterns = [
    path(
        "chat/threads",
        ChatThreadsView.as_view(),
        name="chat-threads",
    ),
    path(
        "matches/<int:pk>/chat/messages",
        ChatMessagesView.as_view(),
        name="chat-messages",
    ),
    path(
        "chat/messages/<int:pk>/report",
        ChatMessageReportView.as_view(),
        name="chat-message-report",
    ),
    path("matches/<int:pk>/block", MatchBlockView.as_view(), name="match-block"),
    path("me/blocks", MyBlocksView.as_view(), name="my-blocks"),
    path("me/blocks/<int:user_id>", MyBlockView.as_view(), name="my-block"),
]
