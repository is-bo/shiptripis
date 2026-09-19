"""Django's technical admin shares the ShipTrip staff revocation boundary."""

from django.contrib.admin import AdminSite

from .permissions import has_admin_access


class ShipTripAdminSite(AdminSite):
    def has_permission(self, request):
        return has_admin_access(request.user)
