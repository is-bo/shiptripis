import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration

from .base import *  # noqa: F401,F403

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

if dsn := env.str("SENTRY_DSN", default=""):
    sentry_sdk.init(
        dsn=dsn,
        integrations=[DjangoIntegration()],
        traces_sample_rate=0.1,
        send_default_pii=False,
    )

# In prod, gRPC must be mTLS — bearer is dev-only.
if GRPC_AUTH_MODE != "mtls":  # noqa: F405
    raise RuntimeError(
        "GRPC_AUTH_MODE must be 'mtls' in production. See CLAUDE.md G5."
    )

# --- Email (SMTP) ---
# The Go email-service is the primary transactional sender (verify/reset OTPs
# via the `email:send` stream). Django's own SMTP backend covers incidental
# mail. All EMAIL_* come from the environment; DEFAULT_FROM_EMAIL falls back to
# the base.py value when EMAIL_FROM_ADDR is unset.
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = env.str("EMAIL_SMTP_HOST", default="")  # noqa: F405
EMAIL_PORT = env.int("EMAIL_SMTP_PORT", default=587)  # noqa: F405
EMAIL_HOST_USER = env.str("EMAIL_SMTP_USERNAME", default="")  # noqa: F405
EMAIL_HOST_PASSWORD = env.str("EMAIL_SMTP_PASSWORD", default="")  # noqa: F405
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)  # noqa: F405
if from_addr := env.str("EMAIL_FROM_ADDR", default=""):  # noqa: F405
    DEFAULT_FROM_EMAIL = from_addr  # noqa: F405
