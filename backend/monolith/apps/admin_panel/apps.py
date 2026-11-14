from django.apps import AppConfig


class AdminPanelConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.admin_panel"
    label = "admin_panel"

    def ready(self):
        from django.conf import settings
        from django.contrib.auth.signals import user_logged_in

        from .two_step import clear_on_sign_in

        user_logged_in.connect(
            clear_on_sign_in, dispatch_uid="admin_panel.two_step.clear_on_sign_in"
        )
        if settings.SHIPTRIP_ENVIRONMENT == "production":
            # Spec 19.1: staff enrol their second step at the first sign-in,
            # and the key is sealed with the payout keyring. Without it nobody
            # could enrol, so production refuses to start instead.
            from apps.finance.sensitive_data import key_configuration

            key_configuration()
