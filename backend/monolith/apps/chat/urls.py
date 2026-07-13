from django.urls import path

from .views import ChatMessagesView

urlpatterns = [
    path(
        "matches/<int:pk>/chat/messages",
        ChatMessagesView.as_view(),
        name="chat-messages",
    ),
]
