from django.urls import path

from .views import DealProblemsView

urlpatterns = [
    path("deals/<int:pk>/problems", DealProblemsView.as_view(), name="deal-problems"),
]
