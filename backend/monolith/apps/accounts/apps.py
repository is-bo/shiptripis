from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"
    label = "accounts"

    def ready(self):
        # Connects `post_delete` on ProfilePhoto in every process, the job
        # worker included: a deleted row always releases its stored object.
        from . import photos  # noqa: F401
