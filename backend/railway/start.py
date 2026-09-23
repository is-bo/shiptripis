"""Run ShipTrip's production processes in one Railway service.

Railway uses one externally managed Redis for cache, throttling, realtime and
stream transport.  An embedded loopback Redis remains available only through
an explicit local-development switch; it is never the production default.
"""

from __future__ import annotations

import base64
import binascii
import ipaddress
import json
import os
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from urllib.parse import urlparse


ROOT = "/app"
STOP_REQUESTED = False
LOCAL_REDIS_URL = "redis://127.0.0.1:6379/0"
# Railway's private network can take a few seconds to route after a container
# starts; a shared Redis that is still silent after this is a real outage.
REDIS_PREFLIGHT_TIMEOUT_SECONDS = 30.0

# The combined 1 GiB Railway container cannot safely buy concurrency by adding
# Python processes. Two gthread workers keep the measured worker RSS bounded
# while allowing one slow provider call per worker without starving all HTTP.
WEB_WORKERS_DEFAULT = 2
WEB_THREADS_DEFAULT = 2
GRPC_WORKERS_DEFAULT = 4

# Standalone Go defaults were sized for separate pods. These smaller ceilings
# are authoritative for the combined container and leave rolling-deploy room
# under the current PostgreSQL max_connections=100 budget.
CHAT_DB_MAX_CONNS_DEFAULT = 5
NOTIF_DB_MAX_CONNS_DEFAULT = 5
EMAIL_DB_MAX_CONNS_DEFAULT = 2
GO_DB_MIN_CONNS = 2
POSTGRES_CONNECTION_LIMIT_DEFAULT = 100
POSTGRES_CONNECTION_RESERVE_DEFAULT = 10


@dataclass
class Child:
    name: str
    process: subprocess.Popen[bytes]


CHILDREN: list[Child] = []


def child_env(**overrides: str) -> dict[str, str]:
    env = os.environ.copy()
    env.update(overrides)
    return env


def spawn(name: str, command: list[str], *, env: dict[str, str] | None = None) -> Child:
    print(f"starting {name}", flush=True)
    process_env = (env or os.environ).copy()
    if name in {"chat", "notification", "kyc", "email", "gateway"}:
        # Payout and payment secrets belong to Django alone. None of the Go
        # services or the gateway verifies a Stripe signature, decrypts a payout
        # profile or reads a payout bucket, so inheriting these would widen the
        # blast radius of any one of those processes for no capability at all.
        for key in (
            "PAYOUT_DATA_KEYRING",
            "PAYOUT_DATA_ACTIVE_KEY_ID",
            "PAYOUT_ACCOUNT_FINGERPRINT_KEY",
            "PAYOUT_S3_ACCESS_KEY",
            "PAYOUT_S3_SECRET_KEY",
            # H2: the connected-accounts endpoint's own signing secret, plus
            # the platform payment credentials it sits beside. Django's own
            # children (web, grpc, workers) keep them.
            "STRIPE_CONNECT_WEBHOOK_SECRET",
            "STRIPE_SECRET_KEY",
            "STRIPE_WEBHOOK_SECRET",
            "CHARGILY_SECRET_KEY",
            "CHARGILY_WEBHOOK_SECRET",
        ):
            process_env.pop(key, None)
    child = Child(
        name,
        subprocess.Popen(
            command,
            cwd=ROOT,
            env=process_env,
            start_new_session=True,
        ),
    )
    CHILDREN.append(child)
    return child


def wait_for_port(child: Child, port: int, timeout: float = 90.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        code = child.process.poll()
        if code is not None:
            raise RuntimeError(f"{child.name} exited during startup with code {code}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.25)
    raise RuntimeError(f"{child.name} did not listen on 127.0.0.1:{port}")


def terminate_children() -> None:
    for child in reversed(CHILDREN):
        if child.process.poll() is None:
            try:
                os.killpg(child.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    deadline = time.monotonic() + 20
    for child in reversed(CHILDREN):
        remaining = max(0.0, deadline - time.monotonic())
        try:
            child.process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(child.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def request_stop(_signum: int, _frame: object) -> None:
    global STOP_REQUESTED
    STOP_REQUESTED = True


FCM_CREDENTIALS_ENV = "FCM_CREDENTIALS_JSON_BASE64"
FCM_CREDENTIALS_DEFAULT_PATH = "/tmp/shiptrip/firebase-admin.json"


def install_fcm_credentials() -> None:
    """Materialise the Firebase Admin service account as a private file.

    Railway has no secret-file primitive: the platform secret store holds
    strings, and the Go notification worker's `FCM_CREDENTIALS_PATH` contract
    wants a real JSON file. So the credential travels as base64 in the secret
    store and is written here, once, before any child process is spawned.

    Three properties matter:

    * **It never reaches the image or the repository.** The file is created at
      boot inside the container's own writable tree with owner-only
      permissions, so it exists exactly as long as the container does.
    * **Children see the path, never the payload.** The base64 variable is
      removed from this process's environment after the write, so every
      `child_env()` copy below carries `FCM_CREDENTIALS_PATH` alone.
    * **A malformed credential fails loudly but quietly.** Errors name the
      variable and the failure kind and never echo decoded bytes, so a bad
      secret cannot leak itself through a crash log.

    Absent variable is not an error: `FCM_ENABLED=false` is the safe default
    state, and `config.LoadFCM` already refuses `FCM_ENABLED=true` without a
    credentials path.
    """

    encoded = os.environ.pop(FCM_CREDENTIALS_ENV, "").strip()
    if not encoded:
        return

    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise RuntimeError(f"{FCM_CREDENTIALS_ENV} is not valid base64") from exc
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{FCM_CREDENTIALS_ENV} does not decode to JSON") from exc
    if not isinstance(parsed, dict) or parsed.get("type") != "service_account":
        raise RuntimeError(
            f"{FCM_CREDENTIALS_ENV} must hold a service_account credential"
        )
    credential_project = str(parsed.get("project_id") or "")
    if not credential_project:
        raise RuntimeError(f"{FCM_CREDENTIALS_ENV} has no project_id")
    # A credential for the wrong Firebase project is the failure that would
    # otherwise be discovered as silently undelivered push, so refuse it here.
    configured_project = os.environ.get("FCM_PROJECT_ID", "").strip()
    if configured_project and configured_project != credential_project:
        raise RuntimeError(
            "FCM_PROJECT_ID does not match the service account's project"
        )

    path = os.environ.get("FCM_CREDENTIALS_PATH", "").strip()
    if not path:
        path = FCM_CREDENTIALS_DEFAULT_PATH
    directory = os.path.dirname(path) or "/"
    os.makedirs(directory, mode=0o700, exist_ok=True)
    try:
        os.chmod(directory, 0o700)
    except OSError:
        # A pre-existing mount we do not own is acceptable; the file mode below
        # is the control that matters.
        pass
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(raw)
    os.chmod(path, 0o600)
    os.environ["FCM_CREDENTIALS_PATH"] = path
    print(
        f"installed Firebase Admin credential for project {credential_project} "
        f"at {path}",
        flush=True,
    )


def _enabled(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _bounded_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.environ.get(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} must be between {minimum} and {maximum}")
    return value


def _validate_redis_url(value: str, *, allow_loopback: bool) -> str:
    try:
        parsed = urlparse(value)
        parsed.port
    except ValueError as exc:
        raise RuntimeError("REDIS_URL is malformed") from exc
    if parsed.scheme not in {"redis", "rediss"} or not parsed.hostname:
        raise RuntimeError("REDIS_URL must be a redis:// or rediss:// URL")
    hostname = parsed.hostname.lower().rstrip(".")
    try:
        loopback = ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        loopback = hostname in {"localhost", "localhost.localdomain"}
    if loopback and not allow_loopback:
        raise RuntimeError(
            "REDIS_URL must use shared external Redis; loopback is local mode only"
        )
    return value


def redis_topology() -> tuple[str, bool]:
    """Resolve the one Redis URL every process in this container must use."""

    embedded = _enabled("SHIPTRIP_EMBEDDED_REDIS")
    configured = os.environ.get("REDIS_URL", "").strip()
    if embedded:
        if configured not in {"", LOCAL_REDIS_URL, "redis://localhost:6379/0"}:
            raise RuntimeError(
                "SHIPTRIP_EMBEDDED_REDIS requires REDIS_URL to be empty or local"
            )
        return LOCAL_REDIS_URL, True
    if not configured:
        raise RuntimeError("REDIS_URL must point at shared external Redis")
    return _validate_redis_url(configured, allow_loopback=False), False


def probe_shared_redis(
    redis_url: str, *, timeout: float = REDIS_PREFLIGHT_TIMEOUT_SECONDS
) -> None:
    """Prove the shared Redis can hold durable streams before anything uses it.

    The Go workers already refuse to start without Redis, but only after the
    migrations and the Django processes; this names the failure first and
    plainly. Three outcomes:

    * **Unreachable or rejected credentials fail startup.** There is no
      fallback to the embedded daemon: a silent fallback would split cache,
      throttles and queues across two Redis servers.
    * **An `allkeys-*` eviction policy fails startup.** Stream keys carry no
      TTL, so only those policies can evict `notif:fcm` or `email:send`, which
      would drop queued work without an error anywhere.
    * **Missing persistence is a loud warning, not a failure.** The instance is
      still shared; the runbook's restart proof is what certifies durability.

    Only the host and port are printed; the URL carries the password.
    """

    import redis  # Django's requirement, installed in the image.

    parsed = urlparse(redis_url)
    endpoint = f"{parsed.hostname}:{parsed.port or 6379}"
    client = redis.Redis.from_url(
        redis_url,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )
    try:
        deadline = time.monotonic() + timeout
        while True:
            try:
                client.ping()
                break
            except redis.AuthenticationError as exc:
                raise RuntimeError(
                    f"shared Redis at {endpoint} rejected the REDIS_URL credentials"
                ) from exc
            except redis.RedisError as exc:
                if time.monotonic() >= deadline:
                    raise RuntimeError(
                        f"shared Redis at {endpoint} is unreachable "
                        f"({type(exc).__name__}); refusing to start"
                    ) from exc
                time.sleep(1)

        def config(name: str) -> str | None:
            try:
                return str(client.config_get(name).get(name, ""))
            except redis.ResponseError:
                # Some managed providers disable CONFIG; report, never guess.
                return None

        policy = config("maxmemory-policy")
        if policy is not None and policy.startswith("allkeys-"):
            raise RuntimeError(
                f"shared Redis at {endpoint} uses maxmemory-policy={policy}, "
                "which can evict durable streams; set noeviction"
            )
        appendonly = config("appendonly")
        save = config("save")
        print(
            f"shared redis {endpoint} "
            f"maxmemory-policy={policy if policy is not None else 'unverifiable'} "
            f"maxmemory={config('maxmemory')} appendonly={appendonly} "
            f"appendfsync={config('appendfsync')} save={save!r}",
            flush=True,
        )
        if policy is None:
            print(
                f"WARNING: shared Redis at {endpoint} hides its configuration; "
                "confirm noeviction and persistence before trusting streams",
                file=sys.stderr,
                flush=True,
            )
        if appendonly == "no" and save == "":
            print(
                f"WARNING: shared Redis at {endpoint} has no AOF and no RDB "
                "snapshots; queued push and email transport will not survive "
                "a Redis restart",
                file=sys.stderr,
                flush=True,
            )
    finally:
        client.close()


def kyc_env(redis_url: str) -> dict[str, str]:
    """Give KYC the same Redis used by Django and every Go transport."""

    env = child_env(
        KYC_HTTP_ADDR="127.0.0.1:8083",
        KYC_GRPC_TARGET="127.0.0.1:50051",
        REDIS_URL=redis_url,
    )
    # The combined container still gives KYC its own bucket credentials.
    # Mapping is per child, so Django continues to use the parcel-media bucket.
    for target in (
        "S3_ENDPOINT_URL",
        "S3_REGION",
        "S3_ACCESS_KEY",
        "S3_SECRET_KEY",
        "S3_USE_PATH_STYLE",
    ):
        source = f"KYC_{target}"
        if value := os.environ.get(source):
            env[target] = value
    return env


def connection_budget() -> dict[str, int]:
    """Return the configured per-container PostgreSQL connection ceiling.

    Django opens one connection per active thread. The gRPC server has its own
    four-thread executor and the two durable Python loops each use one. Go's
    chat/notification/email pools have two idle connections apiece. KYC has no
    direct database dependency; its authenticated gRPC recorder owns writes.
    """

    workers = _bounded_int("WEB_CONCURRENCY", WEB_WORKERS_DEFAULT, minimum=1, maximum=4)
    threads = _bounded_int("WEB_THREADS", WEB_THREADS_DEFAULT, minimum=1, maximum=4)
    grpc_workers = _bounded_int(
        "KYC_GRPC_WORKERS", GRPC_WORKERS_DEFAULT, minimum=1, maximum=8
    )
    chat_max = _bounded_int(
        "CHAT_DB_MAX_CONNS", CHAT_DB_MAX_CONNS_DEFAULT, minimum=2, maximum=15
    )
    notif_max = _bounded_int(
        "NOTIF_DB_MAX_CONNS", NOTIF_DB_MAX_CONNS_DEFAULT, minimum=2, maximum=10
    )
    email_max = _bounded_int(
        "EMAIL_DB_MAX_CONNS", EMAIL_DB_MAX_CONNS_DEFAULT, minimum=2, maximum=5
    )
    connection_limit = _bounded_int(
        "POSTGRES_CONNECTION_LIMIT",
        POSTGRES_CONNECTION_LIMIT_DEFAULT,
        minimum=20,
        maximum=10_000,
    )
    connection_reserve = _bounded_int(
        "POSTGRES_CONNECTION_RESERVE",
        POSTGRES_CONNECTION_RESERVE_DEFAULT,
        minimum=1,
        maximum=1_000,
    )
    if connection_reserve >= connection_limit:
        raise RuntimeError(
            "POSTGRES_CONNECTION_RESERVE must be below POSTGRES_CONNECTION_LIMIT"
        )
    django_peak = workers * threads + grpc_workers + 2
    go_peak = chat_max + notif_max + email_max
    # At idle, one connection per long-lived Django process is the observed
    # conservative floor: two web workers, gRPC, and the two job loops.
    steady_min = workers + 3 + (3 * GO_DB_MIN_CONNS)
    steady_peak = django_peak + go_peak
    rolling_peak = steady_peak * 2
    if rolling_peak > connection_limit - connection_reserve:
        raise RuntimeError(
            "configured rolling deployment database peak "
            f"{rolling_peak} exceeds safe budget "
            f"{connection_limit - connection_reserve}"
        )
    return {
        "web_workers": workers,
        "web_threads": threads,
        "grpc_workers": grpc_workers,
        "chat_max": chat_max,
        "notif_max": notif_max,
        "email_max": email_max,
        "steady_min": steady_min,
        "steady_peak": steady_peak,
        "rolling_peak": rolling_peak,
    }


def apply_geography_catalogue(base_env: dict[str, str]) -> None:
    """Apply the reviewed catalogue that shipped with this image, once.

    The 56k-row geography catalogue is deliberately not a migration, and the
    active V1 write contract refuses a request or a journey that does not
    reference a canonical Place — so a deployment without the catalogue is a
    deployment nobody can create anything on. Shipping the manifest inside the
    image and applying it here makes one release identifier carry both the code
    and the exact reviewed data it needs.

    Two properties matter more than speed:

    * **It is not destructive on every boot.** `--skip-if-current` compares the
      shipped manifest's content digest against what the database records and
      returns after one indexed read when they match, which is every boot after
      the first.
    * **It never blocks readiness.** It runs after the gateway is listening, so
      a slow first import cannot fail a health check and roll the deployment
      back. The import is one transaction, so until it commits the catalogue
      reads as its previous state rather than as a half-built one.

    A failure here is loud and non-fatal: the service keeps serving, and the
    operations console reports a catalogue that is not at the shipped digest.
    """

    print("applying bundled geography catalogue (skip-if-current)", flush=True)
    result = subprocess.run(
        [
            sys.executable,
            "manage.py",
            "import_geography",
            "--skip-if-current",
        ],
        cwd=ROOT,
        env=base_env,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        print(f"geography catalogue: {result.stdout.strip()}", flush=True)
        return
    print(
        "geography catalogue import FAILED; the service is still serving but "
        "canonical place selection will be unavailable until this is resolved",
        file=sys.stderr,
        flush=True,
    )
    print(result.stderr.strip()[-4000:], file=sys.stderr, flush=True)


def run() -> int:
    install_fcm_credentials()
    redis_url, embedded_redis = redis_topology()
    budget = connection_budget()
    kyc_process_env = kyc_env(redis_url)
    base_env = child_env(
        REDIS_URL=redis_url,
        DJANGO_SETTINGS_MODULE="config.settings.prod",
    )
    print(
        "postgres connection budget "
        f"steady_min={budget['steady_min']} steady_peak={budget['steady_peak']} "
        f"rolling_peak={budget['rolling_peak']}",
        flush=True,
    )

    if embedded_redis:
        redis = spawn(
            "redis",
            [
                "redis-server",
                "--bind",
                "127.0.0.1",
                "--protected-mode",
                "yes",
                "--save",
                "",
                "--appendonly",
                "no",
                "--port",
                "6379",
            ],
            env=base_env,
        )
        wait_for_port(redis, 6379)
    else:
        probe_shared_redis(redis_url)

    print("applying database migrations", flush=True)
    subprocess.run(
        [sys.executable, "manage.py", "migrate", "--noinput"],
        cwd=ROOT,
        env=base_env,
        check=True,
    )
    print("collecting static files", flush=True)
    subprocess.run(
        [sys.executable, "manage.py", "collectstatic", "--noinput"],
        cwd=ROOT,
        env=base_env,
        check=True,
    )

    web = spawn(
        "django-web",
        [
            "gunicorn",
            "config.wsgi:application",
            "--bind",
            "127.0.0.1:8000",
            "--workers",
            str(budget["web_workers"]),
            "--worker-class",
            "gthread",
            "--threads",
            str(budget["web_threads"]),
            "--timeout",
            "120",
            "--access-logfile",
            "-",
            "--error-logfile",
            "-",
        ],
        env=base_env,
    )
    wait_for_port(web, 8000)

    grpc = spawn(
        "django-grpc",
        [
            sys.executable,
            "manage.py",
            "runkycgrpc",
            "--addr",
            "127.0.0.1:50051",
            "--max-workers",
            str(budget["grpc_workers"]),
        ],
        env=base_env,
    )
    wait_for_port(grpc, 50051)

    spawn(
        "reservation-releaser",
        [
            sys.executable,
            "manage.py",
            "run_reservation_releaser",
            "--interval",
            os.environ.get("RESERVATION_RELEASE_INTERVAL_SECONDS", "60"),
        ],
        env=base_env,
    )

    # Durable financial work: deposit expiry refunds, checkout expiry, provider
    # reconciliation for webhooks that never arrived, and the Phase 4 payout
    # release gate. The `finance_scheduled_job` table is the obligation store,
    # so this process holds no state — killing it loses nothing, and a second
    # one is safe because claiming is row-locked.
    spawn(
        "finance-jobs",
        [
            sys.executable,
            "manage.py",
            "run_finance_worker",
            "--interval",
            os.environ.get("FINANCE_JOB_INTERVAL_SECONDS", "30"),
        ],
        env=base_env,
    )

    chat = spawn(
        "chat",
        ["/usr/local/bin/chat"],
        env=child_env(
            REDIS_URL=redis_url,
            CHAT_HTTP_ADDR="127.0.0.1:8081",
            CHAT_DB_MAX_CONNS=str(budget["chat_max"]),
        ),
    )
    notification = spawn(
        "notification",
        ["/usr/local/bin/notification"],
        env=child_env(
            REDIS_URL=redis_url,
            NOTIF_HTTP_ADDR="127.0.0.1:8082",
            NOTIF_DB_MAX_CONNS=str(budget["notif_max"]),
        ),
    )
    kyc = spawn("kyc", ["/usr/local/bin/kyc"], env=kyc_process_env)
    email = spawn(
        "email",
        ["/usr/local/bin/email"],
        env=child_env(
            REDIS_URL=redis_url,
            EMAIL_HTTP_ADDR="127.0.0.1:8085",
            EMAIL_DB_MAX_CONNS=str(budget["email_max"]),
        ),
    )
    for child, port in (
        (chat, 8081),
        (notification, 8082),
        (kyc, 8083),
        (email, 8085),
    ):
        wait_for_port(child, port)

    gateway = spawn(
        "gateway",
        ["caddy", "run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"],
        env=base_env,
    )
    wait_for_port(gateway, int(os.environ.get("PORT", "8080")))
    print("ShipTrip is ready", flush=True)

    # Deliberately after readiness. See `apply_geography_catalogue`.
    apply_geography_catalogue(base_env)

    while not STOP_REQUESTED:
        for child in CHILDREN:
            if (code := child.process.poll()) is not None:
                raise RuntimeError(f"{child.name} exited with code {code}")
        time.sleep(0.5)
    return 0


def main() -> int:
    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    try:
        return run()
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"startup failed: {exc}", file=sys.stderr, flush=True)
        return 1
    finally:
        terminate_children()


if __name__ == "__main__":
    raise SystemExit(main())
