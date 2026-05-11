from django.apps import AppConfig


class WalletConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.wallet"
    label = "wallet"

    def ready(self) -> None:
        from . import signals  # noqa: F401  registers handlers
