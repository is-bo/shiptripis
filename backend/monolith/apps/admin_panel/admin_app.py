"""Register the secured admin site with Django's normal autodiscovery."""

from django.contrib.admin.apps import AdminConfig


class ShipTripAdminConfig(AdminConfig):
    default_site = "apps.admin_panel.admin_site.ShipTripAdminSite"
