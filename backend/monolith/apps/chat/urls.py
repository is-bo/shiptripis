from django.urls import path

from .views import ChatMessagesView, ChatThreadsView

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
]
