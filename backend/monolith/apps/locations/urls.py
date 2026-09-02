from django.urls import path

from .geography_views import GeographyCountryListView, GeographyPlaceSearchView
from .views import LocationDetailView, LocationListCreateView


urlpatterns = [
    path("locations", LocationListCreateView.as_view(), name="locations-list-create"),
    path("locations/<int:pk>", LocationDetailView.as_view(), name="locations-detail"),
    path(
        "geography/countries",
        GeographyCountryListView.as_view(),
        name="geography-countries",
    ),
    path(
        "geography/places",
        GeographyPlaceSearchView.as_view(),
        name="geography-places",
    ),
]
