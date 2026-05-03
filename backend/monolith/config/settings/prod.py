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
