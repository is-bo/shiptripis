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
    "apps.parcels",
    "apps.matching",
    "apps.payments",
    "apps.wallet",
    "apps.verification",
    "apps.notifications",
    "apps.chat",
    "apps.admin_panel",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
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
        "DIRS": [],
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
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 8}},
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
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
}

# --- JWT (HS256, shared with Go services per CLAUDE.md G2) ---
SIMPLE_JWT = {
    "ALGORITHM": "HS256",
    "SIGNING_KEY": env.str("JWT_HS256_SECRET"),
    "ACCESS_TOKEN_LIFETIME": timedelta(seconds=env.int("JWT_ACCESS_TTL_SECONDS", default=300)),
    "REFRESH_TOKEN_LIFETIME": timedelta(seconds=env.int("JWT_REFRESH_TTL_SECONDS", default=2592000)),
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
    "PASSWORD_RESET_CODE_TTL_SECONDS", default=900  # 15 minutes
)
PASSWORD_RESET_MAX_ATTEMPTS = env.int("PASSWORD_RESET_MAX_ATTEMPTS", default=5)

# --- Email verification (signup OTP) ---
EMAIL_VERIFY_CODE_TTL_SECONDS = env.int(
    "EMAIL_VERIFY_CODE_TTL_SECONDS", default=900  # 15 minutes
)
EMAIL_VERIFY_MAX_ATTEMPTS = env.int("EMAIL_VERIFY_MAX_ATTEMPTS", default=5)

# --- Email ---
# Transactional OTP mail (verify/reset) is rendered here and enqueued onto the
# `email:send` Redis stream — the Go email-service does the actual SMTP send.
# Django's own EMAIL_BACKEND is only used for any incidental mail; prod.py wires
# it to SMTP. DEFAULT_FROM_EMAIL is the sender address on all outbound mail.
DEFAULT_FROM_EMAIL = env.str("DEFAULT_FROM_EMAIL", default="ShipTrip <noreply@shiptrip.dz>")

# --- Redis ---
REDIS_URL = env.str("REDIS_URL", default="redis://redis:6379/0")

# --- Object storage ---
S3_ENDPOINT_URL = env.str("S3_ENDPOINT_URL")
S3_REGION = env.str("S3_REGION", default="us-east-1")
S3_ACCESS_KEY = env.str("S3_ACCESS_KEY")
S3_SECRET_KEY = env.str("S3_SECRET_KEY")
S3_BUCKET_KYC = env.str("S3_BUCKET_KYC", default="shiptrip-kyc")
S3_BUCKET_PARCEL = env.str("S3_BUCKET_PARCEL", default="shiptrip-parcel")

# --- gRPC ---
GRPC_AUTH_MODE = env.str("GRPC_AUTH_MODE", default="bearer")
GRPC_INTERNAL_TOKEN = env.str("GRPC_INTERNAL_TOKEN", default="")
GRPC_DJANGO_BIND = env.str("GRPC_DJANGO_BIND", default="0.0.0.0:50051")

# --- I18n ---
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# --- Static ---
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# --- CORS (dev only) ---
CORS_ALLOW_ALL_ORIGINS = DEBUG
