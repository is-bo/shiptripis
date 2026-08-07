"""LOCAL-ONLY throwaway test settings — NOT committed (see .gitignore).

This machine has no Postgres/Docker, so tests run against in-memory SQLite.
Overrides only the DB + secret + minimal env the base module requires so it
imports without a real .env. Everything else inherits from base.
"""
import os

for _k, _v in {
    "POSTGRES_DB": "shiptrip",
    "POSTGRES_USER": "shiptrip",
    "POSTGRES_PASSWORD": "x",
    "JWT_HS256_SECRET": "test-jwt-secret",
    "S3_ENDPOINT_URL": "http://localhost:9000",
    "S3_ACCESS_KEY": "test",
    "S3_SECRET_KEY": "test",
}.items():
    os.environ.setdefault(_k, _v)

from config.settings.base import *  # noqa: E402,F401,F403

SECRET_KEY = "test-only-key"
DEBUG = True

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}
