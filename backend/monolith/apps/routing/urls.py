from django.urls import path

from .views import RouteProviderStatusView


urlpatterns = [
    path(
        "routes/provider-status",
        RouteProviderStatusView.as_view(),
        name="routes-provider-status",
    ),
]
