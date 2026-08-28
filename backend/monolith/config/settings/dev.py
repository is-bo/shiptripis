from .base import *  # noqa: F401,F403
from .base import env

PAYMENTS_MOCK_WEBHOOK_ENABLED = env.bool(
    "PAYMENTS_MOCK_WEBHOOK_ENABLED", default=True
)

# Local/CI only. `config.settings.prod` refuses to boot with this on.
PAYMENTS_ALLOW_MOCK_PROVIDER = env.bool("PAYMENTS_ALLOW_MOCK_PROVIDER", default=True)
PAYMENTS_PUBLIC_BASE_URL = env.str(
    "PAYMENTS_PUBLIC_BASE_URL", default="http://localhost:8000"
)

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {"format": "[{levelname}] {asctime} {name}: {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simple"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django.db.backends": {"level": "WARNING"},
        "apps": {"level": "DEBUG", "propagate": True},
    },
}
