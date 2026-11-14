from django.urls import path

from .views import AssistantChatView, AssistantStatusView

urlpatterns = [
    path("assistant/status/", AssistantStatusView.as_view()),
    path("assistant/chat/", AssistantChatView.as_view()),
]
