import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration

from .base import *  # noqa: F401,F403
from .base import env

import ipaddress
import logging
import os
from urllib.parse import urlparse

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
X_FRAME_OPTIONS = "DENY"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
CORS_ALLOW_ALL_ORIGINS = False


def _require_explicit(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} must be set in production.")
    return value


def _valid_allowed_host(value: str) -> bool:
    """Accept an explicit DNS name or IP, never a URL/port/wildcard."""

    candidate = value.strip()
    if not candidate or candidate == "*" or candidate.startswith("."):
        return False
    if candidate.startswith("[") and candidate.endswith("]"):
        try:
            ipaddress.IPv6Address(candidate[1:-1])
            return True
        except ipaddress.AddressValueError:
            return False
    if "[" in candidate or "]" in candidate:
        return False
    try:
        ipaddress.ip_address(candidate)
        return True
    except ValueError:
        pass
    dns_name = candidate.rstrip(".")
    if not dns_name or len(dns_name) > 253:
        return False
    labels = dns_name.split(".")
    return all(
        1 <= len(label) <= 63
        and label[0].isalnum()
        and label[-1].isalnum()
        and all(character.isalnum() or character == "-" for character in label)
        for label in labels
    )


def _is_https_origin(value: str) -> bool:
    """Validate a credential-free HTTPS origin, with no URL path or query."""

    parsed = urlparse(value)
    try:
        parsed.port
    except ValueError:
        return False
    return bool(
        parsed.scheme == "https"
        and parsed.hostname
        and parsed.username is None
        and parsed.password is None
        and parsed.path in ("", "/")
        and not parsed.params
        and not parsed.query
        and not parsed.fragment
    )

if DEBUG:  # noqa: F405
    raise RuntimeError("DJANGO_DEBUG must be false in production.")
if SHIPTRIP_ENVIRONMENT != "production":  # noqa: F405
    raise RuntimeError("SHIPTRIP_ENVIRONMENT must equal 'production'.")
if len(SECRET_KEY) < 32 or SECRET_KEY.startswith("insecure-"):  # noqa: F405
    raise RuntimeError("DJANGO_SECRET_KEY must be a strong production secret.")
if not ALLOWED_HOSTS or any(not _valid_allowed_host(host) for host in ALLOWED_HOSTS):  # noqa: F405
    raise RuntimeError(
        "DJANGO_ALLOWED_HOSTS must contain only explicit hostnames or IP addresses."
    )
if len(SIMPLE_JWT["SIGNING_KEY"]) < 32:  # noqa: F405
    raise RuntimeError("JWT_HS256_SECRET must be at least 32 characters.")
if SIMPLE_JWT["SIGNING_KEY"] == SECRET_KEY:  # noqa: F405
    raise RuntimeError("JWT_HS256_SECRET must differ from DJANGO_SECRET_KEY.")

# Fail closed on deployment-only infrastructure.  Provider credentials stay
# optional until the corresponding provider is enabled in BusinessSettings.
for _required in (
    "DJANGO_SECRET_KEY",
    "JWT_HS256_SECRET",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_HOST",
    "S3_ENDPOINT_URL",
    "S3_ACCESS_KEY",
    "S3_SECRET_KEY",
    "REDIS_URL",
    "TRANSACTIONAL_EMAIL_SECRET",
):
    _require_explicit(_required)

if len(TRANSACTIONAL_EMAIL_SECRET) < 32:  # noqa: F405
    raise RuntimeError("TRANSACTIONAL_EMAIL_SECRET must be at least 32 characters.")
if TRANSACTIONAL_EMAIL_SECRET in (SECRET_KEY, SIMPLE_JWT["SIGNING_KEY"]):  # noqa: F405
    raise RuntimeError(
        "TRANSACTIONAL_EMAIL_SECRET must differ from Django and JWT secrets."
    )

_storage_url = urlparse(S3_ENDPOINT_URL)  # noqa: F405
try:
    _storage_url.port
except ValueError as exc:
    raise RuntimeError("S3_ENDPOINT_URL has an invalid port.") from exc
if (
    _storage_url.scheme != "https"
    or not _storage_url.hostname
    or _storage_url.username is not None
    or _storage_url.password is not None
    or bool(_storage_url.params)
    or bool(_storage_url.query)
    or bool(_storage_url.fragment)
):
    raise RuntimeError("S3_ENDPOINT_URL must be an https URL in production.")

_redis_url = urlparse(REDIS_URL)  # noqa: F405
try:
    _redis_url.port
except ValueError as exc:
    raise RuntimeError("REDIS_URL has an invalid port.") from exc
if _redis_url.scheme not in {"redis", "rediss"} or not _redis_url.hostname:
    raise RuntimeError("REDIS_URL must be a redis:// or rediss:// URL.")

for _origin_name, _origins in (
    ("CORS_ALLOWED_ORIGINS", CORS_ALLOWED_ORIGINS),  # noqa: F405
    ("CSRF_TRUSTED_ORIGINS", CSRF_TRUSTED_ORIGINS),  # noqa: F405
):
    if "*" in _origins or any("*" in origin for origin in _origins):
        raise RuntimeError(f"{_origin_name} must not contain wildcard origins.")
    for _origin in _origins:
        if not _is_https_origin(_origin):
            raise RuntimeError(f"{_origin_name} entries must be https origins.")

# DRF throttles must share counters across Gunicorn workers and Railway
# instances. Development/test keep the dependency-free locmem backend; the
# production profile always uses the required Redis deployment.
CACHES["default"] = {  # noqa: F405
    "BACKEND": "django.core.cache.backends.redis.RedisCache",
    "LOCATION": REDIS_URL,  # noqa: F405
    "KEY_PREFIX": "shiptrip",
}

if dsn := env.str("SENTRY_DSN", default=""):
    sentry_sdk.init(
        dsn=dsn,
        integrations=[DjangoIntegration()],
        traces_sample_rate=0.1,
        send_default_pii=False,
        environment=SHIPTRIP_ENVIRONMENT,  # noqa: F405
        release=None if RELEASE_ID == "unknown" else RELEASE_ID,  # noqa: F405
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
    if GRPC_BEARER_TOKEN in (SECRET_KEY, SIMPLE_JWT["SIGNING_KEY"]):  # noqa: F405
        raise RuntimeError("GRPC_BEARER_TOKEN must differ from Django and JWT secrets.")
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
if not _is_https_origin(PAYMENTS_PUBLIC_BASE_URL):  # noqa: F405
    raise RuntimeError("PAYMENTS_PUBLIC_BASE_URL must be an https:// origin.")
if PAYMENTS_PROVIDER_TIMEOUT_SECONDS <= 0:  # noqa: F405
    raise RuntimeError("PAYMENTS_PROVIDER_TIMEOUT_SECONDS must be greater than zero.")
# Credentials are optional at boot: a provider that is not configured is simply
# reported unavailable and its checkouts are refused. What is forbidden is a
# half-configured Stripe, where a checkout could be created but its webhook
# could never be verified.
if bool(STRIPE_SECRET_KEY) != bool(STRIPE_WEBHOOK_SECRET):  # noqa: F405
    raise RuntimeError(
        "STRIPE_SECRET_KEY and STRIPE_WEBHOOK_SECRET must be set together."
    )

# --- V1 payouts: Stripe Connect onboarding (H2) ---
# With STRIPE_CONNECT_ENABLED false this asserts only the two rules that hold
# unconditionally — the country ceiling and the money-execution flags this
# release does not implement — so existing production boots unchanged with no
# new secret. With the flag on, an incomplete or mode-contradicting
# configuration is a boot refusal rather than a first-onboarding surprise.
from .connect import ConnectConfigurationError, validate_connect_configuration  # noqa: E402

try:
    validate_connect_configuration(
        enabled=STRIPE_CONNECT_ENABLED,  # noqa: F405
        expected_mode=STRIPE_CONNECT_EXPECTED_MODE,  # noqa: F405
        platform_account_id=STRIPE_CONNECT_PLATFORM_ACCOUNT_ID,  # noqa: F405
        api_version=STRIPE_CONNECT_API_VERSION,  # noqa: F405
        webhook_secret=STRIPE_CONNECT_WEBHOOK_SECRET,  # noqa: F405
        allowed_countries=STRIPE_CONNECT_ALLOWED_COUNTRIES,  # noqa: F405
        return_url=STRIPE_CONNECT_ONBOARDING_RETURN_URL,  # noqa: F405
        refresh_url=STRIPE_CONNECT_ONBOARDING_REFRESH_URL,  # noqa: F405
        public_base_url=PAYMENTS_PUBLIC_BASE_URL,  # noqa: F405
        stripe_secret_key=STRIPE_SECRET_KEY,  # noqa: F405
        payouts_enabled=STRIPE_CONNECT_PAYOUTS_ENABLED,  # noqa: F405
        non_stripe_funding_enabled=(
            STRIPE_CONNECT_NON_STRIPE_FUNDING_ENABLED  # noqa: F405
        ),
    )
except ConnectConfigurationError as exc:
    raise RuntimeError(str(exc)) from None

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
if TRANSACTIONAL_EMAIL_PROVIDER not in {"smtp", "sender_net", "sender.net"}:  # noqa: F405
    raise RuntimeError("EMAIL_PROVIDER must be 'smtp' or 'sender_net'.")
if TRANSACTIONAL_EMAIL_ENABLED:  # noqa: F405
    if not EMAIL_HOST or not from_addr:
        raise RuntimeError(
            "EMAIL_SMTP_HOST and EMAIL_FROM_ADDR are required when EMAIL_ENABLED=true."
        )
    if not EMAIL_SENDING_DOMAIN_VERIFIED:  # noqa: F405
        raise RuntimeError(
            "EMAIL_SENDING_DOMAIN_VERIFIED must be true before enabling production email."
        )
    if TRANSACTIONAL_EMAIL_PROVIDER in {"sender_net", "sender.net"} and (  # noqa: F405
        not EMAIL_HOST_USER or not EMAIL_HOST_PASSWORD or not EMAIL_USE_TLS
    ):
        raise RuntimeError(
            "Sender.net requires SMTP username/password and TLS when email is enabled."
        )


class _JsonFormatter(logging.Formatter):
    """Emit a small allow-listed JSON envelope without request/PII leakage."""

    _fields = ("request_id", "method", "path", "status", "duration_ms")

    def format(self, record):
        import json

        is_django_request = record.name == "django.request"
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            # Django's default request message embeds the concrete path. A
            # guest-payment capability may live in that path, so keep the
            # message generic and derive only the source-defined route below.
            "message": "django request failed" if is_django_request else record.getMessage(),
            "release": RELEASE_ID,  # noqa: F405
        }
        if is_django_request:
            request = getattr(record, "request", None)
            route = getattr(getattr(request, "resolver_match", None), "route", None)
            payload["path"] = f"/{route}" if route else "<unmatched>"
            if hasattr(record, "status_code"):
                payload["status"] = record.status_code
        for field in self._fields:
            if hasattr(record, field):
                payload[field] = getattr(record, field)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, separators=(",", ":"))


LOGGING = {  # noqa: F405
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"shiptrip_json": {"()": _JsonFormatter}},
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "shiptrip_json",
        }
    },
    "loggers": {
        "shiptrip.request": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "apps": {"handlers": ["console"], "level": "INFO", "propagate": False},
        # Middleware emits safe structured 4xx records. Keep Django's own
        # request logger for 5xx tracebacks only, with the formatter above
        # replacing its concrete-path message.
        "django.request": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
    },
}
