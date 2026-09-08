"""Base Django settings shared by dev/prod. Reads from environment via
`environ`. See backend/.env.example for the full set of variables."""

from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR.parent / ".env")

# --- Core ---
SECRET_KEY = env.str("DJANGO_SECRET_KEY", default="insecure-dev-key")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["*"])
SHIPTRIP_ENVIRONMENT = env.str("SHIPTRIP_ENVIRONMENT", default="development").lower()

# H1 dormant payout contracts. No key is needed for existing production boot.
PAYOUT_PROFILES_ENABLED = env.bool("PAYOUT_PROFILES_ENABLED", default=False)
PAYOUT_DZD_EXECUTION_ENABLED = env.bool("PAYOUT_DZD_EXECUTION_ENABLED", default=False)
STRIPE_CONNECT_ENABLED = env.bool("STRIPE_CONNECT_ENABLED", default=False)
STRIPE_CONNECT_PAYOUTS_ENABLED = env.bool(
    "STRIPE_CONNECT_PAYOUTS_ENABLED", default=False
)
STRIPE_CONNECT_NON_STRIPE_FUNDING_ENABLED = env.bool(
    "STRIPE_CONNECT_NON_STRIPE_FUNDING_ENABLED", default=False
)
FINANCE_DASHBOARD_ENABLED = env.bool("FINANCE_DASHBOARD_ENABLED", default=False)
STRIPE_CONNECT_ALLOWED_COUNTRIES = env.list(
    "STRIPE_CONNECT_ALLOWED_COUNTRIES", default=[]
)
PAYOUT_DATA_KEYRING = env.str("PAYOUT_DATA_KEYRING", default="{}")
PAYOUT_DATA_ACTIVE_KEY_ID = env.str("PAYOUT_DATA_ACTIVE_KEY_ID", default="")
PAYOUT_ACCOUNT_FINGERPRINT_KEY = env.str("PAYOUT_ACCOUNT_FINGERPRINT_KEY", default="")
S3_BUCKET_PAYOUT = env.str("S3_BUCKET_PAYOUT", default="")
PAYOUT_S3_ENDPOINT_URL = env.str("PAYOUT_S3_ENDPOINT_URL", default="")
PAYOUT_S3_REGION = env.str("PAYOUT_S3_REGION", default="")
PAYOUT_S3_ACCESS_KEY = env.str("PAYOUT_S3_ACCESS_KEY", default="")
PAYOUT_S3_SECRET_KEY = env.str("PAYOUT_S3_SECRET_KEY", default="")
PAYOUT_S3_USE_PATH_STYLE = env.bool("PAYOUT_S3_USE_PATH_STYLE", default=False)

# --- Apps ---
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "django_filters",
    "corsheaders",
    "apps.accounts",
    "apps.core",
    "apps.kyc",
    "apps.trips",
    "apps.locations",
    "apps.parcels",
    "apps.matching",
    "apps.deals",
    "apps.finance",
    "apps.handover",
    "apps.disputes",
    "apps.ratings",
    "apps.boosts",
    "apps.payments",
    "apps.wallet",
    "apps.verification",
    "apps.notifications",
    "apps.chat",
    "apps.admin_panel",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "apps.core.middleware.RequestIDMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        # Project templates take precedence over the ones shipped inside apps,
        # which is what lets `templates/admin/base_site.html` re-brand the
        # operations admin without vendoring any of Django's own admin
        # templates.
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# --- Database ---
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env.str("POSTGRES_DB"),
        "USER": env.str("POSTGRES_USER"),
        "PASSWORD": env.str("POSTGRES_PASSWORD"),
        "HOST": env.str("POSTGRES_HOST", default="postgres"),
        "PORT": env.int("POSTGRES_PORT", default=5432),
        "CONN_MAX_AGE": env.int("DJANGO_DB_CONN_MAX_AGE", default=60),
        "CONN_HEALTH_CHECKS": True,
    }
}

# --- Auth ---
AUTH_USER_MODEL = "accounts.User"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 8},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

# --- DRF ---
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_THROTTLE_CLASSES": (
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ),
    "DEFAULT_THROTTLE_RATES": {
        "anon": env.str("DRF_ANON_THROTTLE_RATE", default="60/min"),
        "user": env.str("DRF_USER_THROTTLE_RATE", default="600/min"),
        "matching_discovery": env.str(
            "DRF_MATCHING_DISCOVERY_THROTTLE_RATE", default="10/min"
        ),
        "journey_routes": env.str("DRF_JOURNEY_ROUTES_THROTTLE_RATE", default="10/min"),
        # A guest link is an unauthenticated capability, so the surface that
        # accepts it is throttled hard against token guessing.
        "guest_payment": env.str("DRF_GUEST_PAYMENT_THROTTLE_RATE", default="20/min"),
        "payment_checkout": env.str(
            "DRF_PAYMENT_CHECKOUT_THROTTLE_RATE", default="20/min"
        ),
        # Generous: a provider retry storm must not be throttled into loss.
        "payment_webhook": env.str(
            "DRF_PAYMENT_WEBHOOK_THROTTLE_RATE", default="1200/min"
        ),
        # Submitting a handover code is a guessing surface. The per-code
        # attempt budget and the sliding window in `apps.handover.services` are
        # the authoritative limits; this is the cheap outer bound that stops a
        # flood before it reaches a row lock.
        "handover_submit": env.str(
            "DRF_HANDOVER_SUBMIT_THROTTLE_RATE", default="12/min"
        ),
        # Revealing a code decrypts a stored secret and writes an audit row.
        "handover_reveal": env.str(
            "DRF_HANDOVER_REVEAL_THROTTLE_RATE", default="30/min"
        ),
        "dispute_evidence": env.str(
            "DRF_DISPUTE_EVIDENCE_THROTTLE_RATE", default="20/min"
        ),
        # Authentication and capability endpoints are deliberately scoped
        # rather than sharing the broad anonymous/user defaults.
        "registration": env.str("DRF_REGISTRATION_THROTTLE_RATE", default="5/hour"),
        "login": env.str("DRF_LOGIN_THROTTLE_RATE", default="10/min"),
        "password_reset": env.str(
            "DRF_PASSWORD_RESET_THROTTLE_RATE", default="5/hour"
        ),
        "email_verify": env.str(
            "DRF_EMAIL_VERIFY_THROTTLE_RATE", default="10/hour"
        ),
        "google_signin": env.str(
            "DRF_GOOGLE_SIGNIN_THROTTLE_RATE", default="10/min"
        ),
        "media_upload": env.str("DRF_MEDIA_UPLOAD_THROTTLE_RATE", default="20/hour"),
        "chat_message": env.str("DRF_CHAT_MESSAGE_THROTTLE_RATE", default="60/min"),
        "admin_invitation": env.str(
            "DRF_ADMIN_INVITATION_THROTTLE_RATE", default="20/hour"
        ),
    },
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
}

# --- JWT (HS256, shared with Go services per CLAUDE.md G2) ---
SIMPLE_JWT = {
    "ALGORITHM": "HS256",
    "SIGNING_KEY": env.str("JWT_HS256_SECRET"),
    "ACCESS_TOKEN_LIFETIME": timedelta(
        seconds=env.int("JWT_ACCESS_TTL_SECONDS", default=300)
    ),
    "REFRESH_TOKEN_LIFETIME": timedelta(
        seconds=env.int("JWT_REFRESH_TTL_SECONDS", default=2592000)
    ),
    "LEEWAY": timedelta(seconds=env.int("JWT_LEEWAY_SECONDS", default=30)),
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
    "TOKEN_TYPE_CLAIM": "typ",
    "JTI_CLAIM": "jti",
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
}

# --- Google OAuth ---
GOOGLE_OAUTH_CLIENT_IDS = env.list("GOOGLE_OAUTH_CLIENT_IDS", default=[])

# --- Password reset ---
PASSWORD_RESET_CODE_TTL_SECONDS = env.int(
    "PASSWORD_RESET_CODE_TTL_SECONDS",
    default=900,  # 15 minutes
)
PASSWORD_RESET_MAX_ATTEMPTS = env.int("PASSWORD_RESET_MAX_ATTEMPTS", default=5)

# --- Email verification (signup OTP) ---
EMAIL_VERIFY_CODE_TTL_SECONDS = env.int(
    "EMAIL_VERIFY_CODE_TTL_SECONDS",
    default=900,  # 15 minutes
)
EMAIL_VERIFY_MAX_ATTEMPTS = env.int("EMAIL_VERIFY_MAX_ATTEMPTS", default=5)

# --- Email ---
# Transactional obligations live in PostgreSQL. Ordinary rendered mail uses the
# `email:send` stream and Go SMTP worker; secret-bearing verification, reset,
# invitation and delivery-code messages use Django's trusted final SMTP adapter
# so plaintext never enters Redis. DEFAULT_FROM_EMAIL applies to both paths.
DEFAULT_FROM_EMAIL = env.str(
    "DEFAULT_FROM_EMAIL", default="ShipTrip <noreply@shiptrip.dz>"
)
# Public links and support identity used by transactional templates. These are
# intentionally non-secret; SMTP/API credentials remain in the email worker's
# environment and are never exposed to request handlers.
FRONTEND_BASE_URL = env.str("FRONTEND_BASE_URL", default="")
EMAIL_SUPPORT_ADDR = env.str("EMAIL_SUPPORT_ADDR", default="")
TRANSACTIONAL_EMAIL_ENABLED = env.bool("EMAIL_ENABLED", default=False)
TRANSACTIONAL_EMAIL_PROVIDER = env.str("EMAIL_PROVIDER", default="smtp").lower()
# Separate encryption root for short-lived OTP/invitation delivery copies.
# When unset, the outbox derives a key from SECRET_KEY; production deployments
# should provide a rotated, dedicated secret instead.
TRANSACTIONAL_EMAIL_SECRET = env.str("TRANSACTIONAL_EMAIL_SECRET", default="")
EMAIL_SENDING_DOMAIN_VERIFIED = env.bool(
    "EMAIL_SENDING_DOMAIN_VERIFIED", default=False
)
# One durable reminder, scheduled from the Deal's already-snapshotted
# protection deadline. Zero disables the reminder without changing lifecycle
# policy; the V1 default is 24 hours before the 48-hour deadline.
PROTECTION_ENDING_REMINDER_SECONDS = env.int(
    "PROTECTION_ENDING_REMINDER_SECONDS", default=86_400
)

# --- Redis ---
REDIS_URL = env.str("REDIS_URL", default="redis://redis:6379/0")

# --- Firebase Cloud Messaging ----------------------------------------------
# Django resolves recipients and writes localized payloads to Redis; the Go
# notification service owns Firebase Admin HTTP. Credentials never enter a
# Django response or a mobile build. Push remains dark unless explicitly
# enabled with complete server configuration.
FCM_ENABLED = env.bool("FCM_ENABLED", default=False)
FCM_PROJECT_ID = env.str("FCM_PROJECT_ID", default="")
FCM_CREDENTIALS_PATH = env.str("FCM_CREDENTIALS_PATH", default="")
FCM_STREAM = env.str("FCM_STREAM", default="notif:fcm")
FCM_RESULTS_STREAM = env.str("FCM_RESULTS_STREAM", default="notif:fcm:results")
FCM_CONSUMER_GROUP = env.str("FCM_CONSUMER_GROUP", default="notif-fcm-workers")
FCM_CONSUMER_NAME = env.str("FCM_CONSUMER_NAME", default="notif-fcm-1")
FCM_RESULTS_CONSUMER_GROUP = env.str(
    "FCM_RESULTS_CONSUMER_GROUP", default="notif-fcm-results-django"
)
FCM_RESULTS_CONSUMER_NAME = env.str(
    "FCM_RESULTS_CONSUMER_NAME", default="notif-fcm-results-django-1"
)

# --- Route/location provider -------------------------------------------------
# The domain depends only on apps.routing.providers.RouteProvider. Production
# deliberately has no synthetic fallback provider: missing configuration is
# surfaced by /api/routes/provider-status and matching labels its conservative
# spatial fallback explicitly.
ROUTE_PROVIDER_CLASS = env.str("ROUTE_PROVIDER_CLASS", default="")
ROUTE_PROVIDER_OPTIONS = env.json("ROUTE_PROVIDER_OPTIONS", default={})
ROUTE_PROVIDER_CACHE_TTL_SECONDS = env.int(
    "ROUTE_PROVIDER_CACHE_TTL_SECONDS", default=86400
)
ROUTE_PROVIDER_CACHE_ALIAS = "routing"
ROUTE_PROVIDER_CACHE_URL = env.str("ROUTE_PROVIDER_CACHE_URL", default="")
ROUTE_PROVIDER_CACHE_NAMESPACE = env.str(
    "ROUTE_PROVIDER_CACHE_NAMESPACE", default="v1"
)
ROUTE_PROVIDER_MAX_EXTERNAL_CALLS_PER_MATCHING_REQUEST = env.int(
    "ROUTE_PROVIDER_MAX_EXTERNAL_CALLS_PER_MATCHING_REQUEST", default=50
)
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "shiptrip-default",
    },
    "routing": (
        {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": ROUTE_PROVIDER_CACHE_URL,
            "KEY_PREFIX": "shiptrip-routing",
        }
        if ROUTE_PROVIDER_CACHE_URL
        else {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "shiptrip-routing",
        }
    ),
}

# --- Object storage ---
S3_ENDPOINT_URL = env.str("S3_ENDPOINT_URL")
S3_REGION = env.str("S3_REGION", default="us-east-1")
S3_ACCESS_KEY = env.str("S3_ACCESS_KEY")
S3_SECRET_KEY = env.str("S3_SECRET_KEY")
S3_USE_PATH_STYLE = env.bool("S3_USE_PATH_STYLE", default=bool(S3_ENDPOINT_URL))
S3_BUCKET_KYC = env.str("S3_BUCKET_KYC", default="shiptrip-kyc")
# The KYC bucket is not Django's. The Go KYC service writes it with its own
# key, and on the deployed environment that key is the *only* one granted on
# that bucket — Django's `S3_ACCESS_KEY` gets 403 AccessDenied. Presigning is a
# local HMAC and never fails, so pointing Django's credential at this bucket
# does not raise: it returns a URL the browser is then denied, which is exactly
# how the admin console came to render a broken KYC image.
#
# These variables already exist in the deployment contract — `railway/start.py`
# maps `KYC_S3_*` onto the KYC child process's own `S3_*` — so Django reads the
# same pair rather than a new secret being minted. They fall back to the generic
# credential, which is the correct behaviour for local/compose environments
# where one key owns every bucket.
KYC_S3_ENDPOINT_URL = env.str("KYC_S3_ENDPOINT_URL", default=S3_ENDPOINT_URL)
KYC_S3_REGION = env.str("KYC_S3_REGION", default=S3_REGION)
KYC_S3_ACCESS_KEY = env.str("KYC_S3_ACCESS_KEY", default="")
KYC_S3_SECRET_KEY = env.str("KYC_S3_SECRET_KEY", default="")
KYC_S3_USE_PATH_STYLE = env.bool("KYC_S3_USE_PATH_STYLE", default=S3_USE_PATH_STYLE)
S3_BUCKET_PARCEL = env.str("S3_BUCKET_PARCEL", default="shiptrip-parcel")
# Flight proof is journey evidence, not identity evidence, and Django writes
# it with Django's own credential. Hosting it in the KYC bucket coupled it to
# a credential that belongs to the Go KYC service instead — which is exactly
# how every deployed proof upload came to fail with AccessDenied. It shares
# the private media bucket with dispute evidence, which has the same shape:
# private objects Django writes and serves back only through a presigned,
# authorised admin redirect.
S3_BUCKET_PROOF = env.str("S3_BUCKET_PROOF", default=S3_BUCKET_PARCEL)
#: Lifetime of a signed parcel item-photo URL, in seconds. Minutes, not hours:
#: a link forwarded out of the app should stop working quickly, and the client
#: asks for a fresh one whenever it needs to render the image again.
PARCEL_MEDIA_URL_TTL_SECONDS = env.int("PARCEL_MEDIA_URL_TTL_SECONDS", default=300)
#: How long an uploaded-but-unclaimed item photo is kept before
#: `manage.py purge_staged_parcel_media` may reclaim it. Long enough that a
#: sender can leave the form, come back and still post.
PARCEL_STAGED_MEDIA_TTL_HOURS = env.int("PARCEL_STAGED_MEDIA_TTL_HOURS", default=48)

# --- gRPC ---
GRPC_AUTH_MODE = env.str("GRPC_AUTH_MODE", default="bearer")
GRPC_BEARER_TOKEN = env.str("GRPC_BEARER_TOKEN", default="")
GRPC_DJANGO_BIND = env.str("GRPC_DJANGO_BIND", default="0.0.0.0:50051")
GRPC_TLS_CA_CERT = env.str("GRPC_TLS_CA_CERT", default="")
GRPC_TLS_SERVER_CERT = env.str("GRPC_TLS_SERVER_CERT", default="")
GRPC_TLS_SERVER_KEY = env.str("GRPC_TLS_SERVER_KEY", default="")

# Development/QA only. Hosted environments leave this disabled so an
# unauthenticated caller cannot synthesize payment state transitions.
PAYMENTS_MOCK_WEBHOOK_ENABLED = env.bool("PAYMENTS_MOCK_WEBHOOK_ENABLED", default=False)
# Historical DZD PaymentIntent rows remain readable, but their old instant-mock
# mutation surface is retired by default. Tests that exercise archival behavior
# must opt in explicitly.
PAYMENTS_LEGACY_MUTATIONS_ENABLED = env.bool(
    "PAYMENTS_LEGACY_MUTATIONS_ENABLED", default=False
)

# --- V1 payments -------------------------------------------------------------
# Credentials only. Everything commercial (which providers are on, the deposit
# formula, the EUR->DZD rate) lives in the versioned BusinessSettingsVersion
# policy, not here, so it is audited and snapshotted rather than redeployed.
#
# `PAYMENTS_ALLOW_MOCK_PROVIDER` is the single switch that makes the test rail
# reachable at all. It defaults off, `config.settings.prod` refuses to start
# when it is on, and nothing anywhere falls back to mock when a real provider
# is misconfigured — a missing credential fails the checkout instead.
PAYMENTS_ALLOW_MOCK_PROVIDER = env.bool("PAYMENTS_ALLOW_MOCK_PROVIDER", default=False)
PAYMENTS_PUBLIC_BASE_URL = env.str("PAYMENTS_PUBLIC_BASE_URL", default="")

# --- V1 handover codes ---
# Root secret for pickup/delivery code hashing and sealing. Deliberately its own
# variable: rotating or losing the Django SECRET_KEY is a session/signing event,
# not a parcel-handover event, and the two should not share a blast radius.
# Production refuses to boot without it; development and tests derive a
# deterministic fallback from SECRET_KEY (see apps.handover.codes).
HANDOVER_CODE_SECRET = env.str("HANDOVER_CODE_SECRET", default="")
# Dispute evidence is Django's own write, like parcel media and flight proof,
# so it defaults to the private media bucket Django's credential owns. It must
# never fall back to the KYC bucket: that is the Go service's, and a fallback
# onto it would reproduce the 8F-A AccessDenied failure on a dispute instead.
S3_BUCKET_DISPUTE = env.str("S3_BUCKET_DISPUTE", default=S3_BUCKET_PARCEL)
#: Lifetime of a signed dispute-evidence download URL, in seconds.
DISPUTE_EVIDENCE_URL_TTL_SECONDS = env.int(
    "DISPUTE_EVIDENCE_URL_TTL_SECONDS", default=300
)
PAYMENTS_PROVIDER_TIMEOUT_SECONDS = env.int(
    "PAYMENTS_PROVIDER_TIMEOUT_SECONDS", default=15
)

STRIPE_SECRET_KEY = env.str("STRIPE_SECRET_KEY", default="")
STRIPE_WEBHOOK_SECRET = env.str("STRIPE_WEBHOOK_SECRET", default="")
STRIPE_API_BASE = env.str("STRIPE_API_BASE", default="https://api.stripe.com")
STRIPE_API_VERSION = env.str("STRIPE_API_VERSION", default="")
STRIPE_WEBHOOK_TOLERANCE_SECONDS = env.int(
    "STRIPE_WEBHOOK_TOLERANCE_SECONDS", default=300
)

# Chargily signs webhooks with the API secret key; the separate override exists
# so the two can be rotated independently if Chargily ever splits them.
CHARGILY_SECRET_KEY = env.str("CHARGILY_SECRET_KEY", default="")
CHARGILY_WEBHOOK_SECRET = env.str("CHARGILY_WEBHOOK_SECRET", default="")
CHARGILY_API_BASE = env.str(
    "CHARGILY_API_BASE", default="https://pay.chargily.net/api/v2"
)

# --- I18n ---
LANGUAGE_CODE = "en"
LANGUAGES = (
    ("en", "English"),
    ("fr", "French"),
    ("ar", "Arabic"),
)
LOCALE_PATHS = (BASE_DIR / "locale",)
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# --- Static ---
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
    },
}

# --- CORS (dev only) ---
CORS_ALLOW_ALL_ORIGINS = DEBUG
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

# Injected by the release pipeline (git SHA, image digest, or release tag).
# It is metadata only and is safe to expose on internal health responses.
RELEASE_ID = env.str("RELEASE_ID", default="unknown")

# Bound parsing before endpoint-level MIME/semantic validation. The private
# media APIs enforce a 10 MiB object limit; two extra MiB cover multipart
# framing without allowing arbitrary request bodies to spool indefinitely.
DATA_UPLOAD_MAX_MEMORY_SIZE = env.int(
    "DATA_UPLOAD_MAX_MEMORY_SIZE", default=12 * 1024 * 1024
)
FILE_UPLOAD_MAX_MEMORY_SIZE = env.int(
    "FILE_UPLOAD_MAX_MEMORY_SIZE", default=10 * 1024 * 1024
)
