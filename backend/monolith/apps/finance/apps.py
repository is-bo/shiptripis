from django.apps import AppConfig


class FinanceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.finance"
    verbose_name = "Finance (V1 payments, ledger, payouts)"

    def ready(self):
        from django.conf import settings

        if settings.PAYOUT_PROFILES_ENABLED:
            from .sensitive_data import key_configuration

            key_configuration()
