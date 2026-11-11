"""VPS boundary: secret-file injection, V1 guards, single-owner operations."""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from urllib.parse import quote
import urllib.request

sys.path.insert(0, "/app")

SECRET_KEYS = {
    "DJANGO_SECRET_KEY", "JWT_HS256_SECRET", "GRPC_BEARER_TOKEN",
    "HANDOVER_CODE_SECRET", "TRANSACTIONAL_EMAIL_SECRET",
    "S3_ACCESS_KEY", "S3_SECRET_KEY", "KYC_S3_ACCESS_KEY", "KYC_S3_SECRET_KEY",
    "PAYOUT_S3_ACCESS_KEY", "PAYOUT_S3_SECRET_KEY", "PAYOUT_DATA_KEYRING",
    "PAYOUT_DATA_ACTIVE_KEY_ID", "PAYOUT_ACCOUNT_FINGERPRINT_KEY",
    "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "STRIPE_CONNECT_WEBHOOK_SECRET",
    "CHARGILY_SECRET_KEY", "CHARGILY_WEBHOOK_SECRET", "FCM_CREDENTIALS_JSON_BASE64",
    "EMAIL_SMTP_USERNAME", "EMAIL_SMTP_PASSWORD",
}


def load_secrets(directory: Path = Path("/run/secrets")) -> None:
    payload = json.loads((directory / "app_secrets").read_text())
    if not isinstance(payload, dict) or set(payload) - SECRET_KEYS:
        raise RuntimeError("app.json contains unsupported secret keys")
    for key, value in payload.items():
        if not isinstance(value, str) or key in os.environ:
            raise RuntimeError(f"{key}: secret must be a string with one configuration source")
        os.environ[key] = value
    os.environ["POSTGRES_PASSWORD"] = (directory / "postgres_password").read_text().strip()
    password = (directory / "redis_password").read_text().strip()
    os.environ["REDIS_URL"] = f"redis://:{quote(password, safe='')}@redis:6379/0"


def v1_guards() -> None:
    for key, value in {
        "SHIPTRIP_ENVIRONMENT": "production", "DJANGO_DEBUG": "false",
        "PAYMENTS_ENVIRONMENT": "test",
        "PAYMENTS_ALLOW_MOCK_PROVIDER": "false",
        "PAYMENTS_MOCK_WEBHOOK_ENABLED": "false", "PAYMENTS_LEGACY_MUTATIONS_ENABLED": "false",
        "PAYOUT_DZD_EXECUTION_ENABLED": "false", "STRIPE_CONNECT_PAYOUTS_ENABLED": "false",
        "STRIPE_CONNECT_NON_STRIPE_FUNDING_ENABLED": "false",
        "STRIPE_CONNECT_EXPECTED_MODE": "test",
    }.items():
        if os.environ.get(key, "").lower() != value:
            raise RuntimeError(f"V1 requires {key}={value}")
    enabled = os.environ.get("EMAIL_ENABLED", "").lower()
    if enabled not in {"true", "false"}:
        raise RuntimeError("EMAIL_ENABLED must be explicitly true or false")
    if enabled == "true" and (
        os.environ.get("EMAIL_ACTIVATION_APPROVED", "false").lower() != "true"
        or os.environ.get("EMAIL_SENDING_DOMAIN_VERIFIED", "false").lower() != "true"
        or not os.environ.get("EMAIL_ACTIVATION_NOT_BEFORE")
    ):
        raise RuntimeError("Email requires explicit V3 approval, verified domain and backlog cutoff")
    if os.environ.get("DATABASE_URL") or os.environ.get("ROUTE_PROVIDER_CACHE_URL"):
        raise RuntimeError("VPS uses split POSTGRES vars and one generated Redis URL")


def health() -> None:
    # Probes need neither secret injection nor Django imports.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for port, path in ((8080, "readyz"), (8081, "readyz"), (8082, "readyz"),
                       (8083, "healthz"), (8085, "healthz")):
        request = urllib.request.Request(f"http://127.0.0.1:{port}/{path}")
        with opener.open(request, timeout=2) as response:
            if response.status != 200:
                raise RuntimeError("application probe failed")


def maintenance(command: list[str]) -> None:
    import django
    django.setup()
    from django.db import connection
    # Session lock serializes operators across different containers/hosts.
    # Not a transaction lock: migrations may contain their own atomic blocks.
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(877431104)")
        if not cursor.fetchone()[0]:
            raise RuntimeError("another VPS maintenance operation owns the database lock")
        try:
            allowed = {
                "migrate", "import_geography", "check", "showmigrations", "inspect_redis_streams",
                "flushexpiredtokens", "prune_scheduled_jobs", "prune_push_devices",
                "purge_staged_parcel_media", "sweep_published_events",
                "audit_email_backlog", "review_email_backlog",
            }
            if not command or command[0] not in allowed:
                raise RuntimeError("unsupported maintenance command")
            subprocess.run([sys.executable, "manage.py", *command], check=True)
        finally:
            cursor.execute("SELECT pg_advisory_unlock(877431104)")


def main() -> int:
    command = sys.argv[1:]
    if command == ["health"]:
        health()
        return 0
    load_secrets()
    v1_guards()
    # Go's loader names this KYC_S3_BUCKET; Django names it S3_BUCKET_KYC.
    # Keep a single owner-supplied bucket value instead of Go's dev fallback.
    os.environ["KYC_S3_BUCKET"] = os.environ["S3_BUCKET_KYC"]
    if command and command[0] == "maintenance":
        maintenance(command[1:])
        return 0
    if command != ["serve"]:
        raise RuntimeError("expected serve, health or maintenance")
    # Raw Compose startup must also refuse a partial schema before any worker
    # runs. This checks only; initialization remains an explicit locked action.
    subprocess.run([sys.executable, "manage.py", "migrate", "--check"], check=True)
    import launcher
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, launcher.request_stop)
    try:
        return launcher.run()
    finally:
        launcher.terminate_children()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        # No exception payload: transport/parser errors may carry credentials.
        print(f"VPS operation failed ({type(error).__name__}); check configuration and service health", file=sys.stderr)
        raise SystemExit(1) from None
