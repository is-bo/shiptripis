import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration

from .base import *  # noqa: F401,F403
from .base import env

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

if DEBUG:  # noqa: F405
    raise RuntimeError("DJANGO_DEBUG must be false in production.")
if len(SECRET_KEY) < 32 or SECRET_KEY.startswith("insecure-"):  # noqa: F405
    raise RuntimeError("DJANGO_SECRET_KEY must be a strong production secret.")
if "*" in ALLOWED_HOSTS:  # noqa: F405
    raise RuntimeError("DJANGO_ALLOWED_HOSTS must not contain '*' in production.")
if len(SIMPLE_JWT["SIGNING_KEY"]) < 32:  # noqa: F405
    raise RuntimeError("JWT_HS256_SECRET must be at least 32 characters.")

if dsn := env.str("SENTRY_DSN", default=""):
    sentry_sdk.init(
        dsn=dsn,
        integrations=[DjangoIntegration()],
        traces_sample_rate=0.1,
        send_default_pii=False,
    )

# mTLS is the normal production transport. Railway can explicitly opt into a
# strong bearer token because the service is reachable only over its private
# project network; this exception fails closed unless both safeguards are set.
if GRPC_AUTH_MODE == "bearer":  # noqa: F405
    if not env.bool("GRPC_ALLOW_PRIVATE_BEARER", default=False):  # noqa: F405
        raise RuntimeError(
            "Production bearer gRPC requires GRPC_ALLOW_PRIVATE_BEARER=true."
        )
    if len(GRPC_BEARER_TOKEN) < 32:  # noqa: F405
        raise RuntimeError("GRPC_BEARER_TOKEN must be at least 32 characters.")
elif GRPC_AUTH_MODE == "mtls":  # noqa: F405
    if not all((GRPC_TLS_CA_CERT, GRPC_TLS_SERVER_CERT, GRPC_TLS_SERVER_KEY)):  # noqa: F405
        raise RuntimeError(
            "mTLS requires GRPC_TLS_CA_CERT, GRPC_TLS_SERVER_CERT and "
            "GRPC_TLS_SERVER_KEY paths."
        )
else:
    raise RuntimeError(
        "GRPC_AUTH_MODE must be 'mtls' or the explicit private-network bearer mode."
    )

# --- V1 payments: production safety ---
# The mock rail must never be reachable in production. This is a boot-time
# refusal rather than a runtime check, so a deployment that sets the flag never
# starts and cannot take a single payment.
if PAYMENTS_ALLOW_MOCK_PROVIDER:  # noqa: F405
    raise RuntimeError(
        "PAYMENTS_ALLOW_MOCK_PROVIDER must be false in production; the mock "
        "payment provider is for tests and local development only."
    )
if PAYMENTS_MOCK_WEBHOOK_ENABLED:  # noqa: F405
    raise RuntimeError(
        "PAYMENTS_MOCK_WEBHOOK_ENABLED must be false in production."
    )
if PAYMENTS_LEGACY_MUTATIONS_ENABLED:  # noqa: F405
    raise RuntimeError(
        "PAYMENTS_LEGACY_MUTATIONS_ENABLED must be false in production."
    )
# A checkout cannot be created without a public base URL for the provider's
# success/failure redirects and its webhook endpoint. Fail at boot rather than
# at the first payment.
if not PAYMENTS_PUBLIC_BASE_URL:  # noqa: F405
    raise RuntimeError(
        "PAYMENTS_PUBLIC_BASE_URL must be set so providers can reach the "
        "webhook and redirect endpoints."
    )
if not PAYMENTS_PUBLIC_BASE_URL.startswith("https://"):  # noqa: F405
    raise RuntimeError("PAYMENTS_PUBLIC_BASE_URL must be an https:// origin.")
# Credentials are optional at boot: a provider that is not configured is simply
# reported unavailable and its checkouts are refused. What is forbidden is a
# half-configured Stripe, where a checkout could be created but its webhook
# could never be verified.
if bool(STRIPE_SECRET_KEY) != bool(STRIPE_WEBHOOK_SECRET):  # noqa: F405
    raise RuntimeError(
        "STRIPE_SECRET_KEY and STRIPE_WEBHOOK_SECRET must be set together."
    )

# --- V1 handover: production safety ---
# Without its own secret the handover key derivation falls back to SECRET_KEY.
# That is a fine developer convenience and an unacceptable production posture:
# it would tie parcel-code secrecy to the same value used for session signing.
if len(HANDOVER_CODE_SECRET) < 32:  # noqa: F405
    raise RuntimeError(
        "HANDOVER_CODE_SECRET must be set to at least 32 characters in "
        "production; pickup and delivery code secrecy depends on it."
    )
if HANDOVER_CODE_SECRET == SECRET_KEY:  # noqa: F405
    raise RuntimeError(
        "HANDOVER_CODE_SECRET must differ from DJANGO_SECRET_KEY."
    )

# --- Email (SMTP) ---
# The Go email-service carries ordinary transactional mail from `email:send`.
# Django's SMTP backend is also the trusted final boundary for secret-bearing
# messages that must never be serialized into Redis. Both use environment-only
# credentials; DEFAULT_FROM_EMAIL falls back to base.py when unset.
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = env.str("EMAIL_SMTP_HOST", default="")  # noqa: F405
EMAIL_PORT = env.int("EMAIL_SMTP_PORT", default=587)  # noqa: F405
EMAIL_HOST_USER = env.str("EMAIL_SMTP_USERNAME", default="")  # noqa: F405
EMAIL_HOST_PASSWORD = env.str("EMAIL_SMTP_PASSWORD", default="")  # noqa: F405
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)  # noqa: F405
if from_addr := env.str("EMAIL_FROM_ADDR", default=""):  # noqa: F405
    DEFAULT_FROM_EMAIL = from_addr  # noqa: F405
