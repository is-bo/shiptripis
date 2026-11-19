"""Django settings for the LOCAL load harness. Never used by CI or production.

Production-shaped where it changes request cost, local where it cannot be
production:

* ``DEBUG`` off, persistent connections (``CONN_MAX_AGE`` 60, health checks
  on) exactly as ``base.py`` ships them, so the connection budget is measured
  rather than assumed.
* DRF throttles and the route cache use Redis when ``LOADTEST_REDIS_URL`` is
  set (the harness points it at ``tools/cmd/miniredis``), matching the two
  cache round trips per request production pays. Without it they fall back to
  per-process locmem and the README says the numbers are then optimistic.
* HTTPS redirects, Sentry and the production secret checks are omitted: the
  harness speaks plain HTTP on loopback.

Database: either an embedded ``pgserver`` cluster in ``LOADTEST_PGDATA`` (the
workstation path, same package the local test settings use) or any real
PostgreSQL named by the usual ``POSTGRES_*`` variables.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

LOADTEST_DIR = Path(__file__).resolve().parent
MONOLITH_DIR = LOADTEST_DIR.parent / "monolith"
if str(MONOLITH_DIR) not in sys.path:
    sys.path.insert(0, str(MONOLITH_DIR))

LOADTEST_DB_NAME = os.environ.get("LOADTEST_DB_NAME", "shiptrip_load")
_PGDATA = os.environ.get("LOADTEST_PGDATA", "").strip()

if _PGDATA:
    import pgserver  # dev-only; present in the monolith dev venv
    import psycopg

    Path(_PGDATA).mkdir(parents=True, exist_ok=True)
    # cleanup_mode=None keeps the cluster up after this process exits, so the
    # seeder, several server processes and the monitor can share it.
    _server = pgserver.get_server(_PGDATA, cleanup_mode=None)
    _uri = _server.get_uri()
    _rest = _uri.split("://", 1)[1]
    _credentials, _hostpart = _rest.split("@", 1)
    _hostport = _hostpart.split("/", 1)[0]
    _host, _port = _hostport.split(":")
    _user = _credentials.split(":", 1)[0]
    with psycopg.connect(
        host=_host, port=_port, user=_user, dbname="postgres", autocommit=True
    ) as _admin:
        _exists = _admin.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (LOADTEST_DB_NAME,)
        ).fetchone()
        if not _exists:
            _admin.execute(f'CREATE DATABASE "{LOADTEST_DB_NAME}"')
    os.environ.update(
        {
            "POSTGRES_DB": LOADTEST_DB_NAME,
            "POSTGRES_USER": _user,
            "POSTGRES_PASSWORD": "",
            "POSTGRES_HOST": _host,
            "POSTGRES_PORT": _port,
        }
    )

for _key, _value in {
    "JWT_HS256_SECRET": "loadtest-jwt-secret-local-only-0123456789abcdef",
    "S3_ENDPOINT_URL": "http://127.0.0.1:9",
    "S3_ACCESS_KEY": "loadtest",
    "S3_SECRET_KEY": "loadtest",
    # Seeded tokens must outlive a long soak; production keeps 300 s.
    "JWT_ACCESS_TTL_SECONDS": "86400",
    "DJANGO_DEBUG": "false",
    "DJANGO_ALLOWED_HOSTS": "127.0.0.1,localhost",
}.items():
    os.environ.setdefault(_key, _value)

from config.settings.base import *  # noqa: E402,F401,F403
from config.settings.base import DATABASES, REST_FRAMEWORK  # noqa: E402

SECRET_KEY = "loadtest-only-secret-key"

# Mirror base.py, but let a run override the persistent-connection lifetime to
# compare CONN_MAX_AGE semantics.
DATABASES["default"]["CONN_MAX_AGE"] = int(
    os.environ.get("DJANGO_DB_CONN_MAX_AGE", "60")
)
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True

REDIS_URL = os.environ.get("LOADTEST_REDIS_URL", "redis://127.0.0.1:6379/0")
if os.environ.get("LOADTEST_REDIS_URL"):
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
            "KEY_PREFIX": "shiptrip",
            "OPTIONS": {"socket_connect_timeout": 1, "socket_timeout": 1},
        },
        "routing": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
            "KEY_PREFIX": "shiptrip-routing",
            "OPTIONS": {"socket_connect_timeout": 1, "socket_timeout": 1},
        },
    }

# Every simulated user shares 127.0.0.1, so the per-IP anonymous budget would
# measure the throttle rather than the server. Per-user and endpoint scopes
# (matching discovery 60/min, chat 60/min) stay at their production values:
# the traffic mix is shaped to respect them, and a 429 is reported as an error.
REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["anon"] = "100000/min"

# Console pages render {% static %}; the harness does not run collectstatic.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}

# The mock payment rail lets the seeder fund Deals through the real webhook
# path. Production refuses to boot with this set.
PAYMENTS_ALLOW_MOCK_PROVIDER = True
PAYMENTS_PUBLIC_BASE_URL = "https://loadtest.shiptrip.invalid"
