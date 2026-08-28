from django.urls import path

from .views import LocationDetailView, LocationListCreateView


urlpatterns = [
    path("locations", LocationListCreateView.as_view(), name="locations-list-create"),
    path("locations/<int:pk>", LocationDetailView.as_view(), name="locations-detail"),
]
