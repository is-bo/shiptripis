"""Django's technical admin shares the ShipTrip staff revocation boundary."""

from django.contrib.admin import AdminSite
from django.contrib.auth.views import PasswordChangeView
from django.urls import reverse

from .permissions import has_admin_access


class ShipTripAdminSite(AdminSite):
    def has_permission(self, request):
        return has_admin_access(request.user)

    def password_change(self, request, extra_context=None):
        """Django's own view, with a form that saves through the one password
        writer (N1, N-D); `AdminSite` offers no setting for the form."""

        from apps.accounts.admin import OwnPasswordForm

        request.current_app = self.name
        return PasswordChangeView.as_view(
            form_class=OwnPasswordForm,
            success_url=reverse("admin:password_change_done", current_app=self.name),
            extra_context={**self.each_context(request), **(extra_context or {})},
        )(request)
