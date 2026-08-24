"""Run ShipTrip's production processes in one Railway service.

Railway's free plan limits this account to two compute/database resources. This
launcher preserves the normal ports and gateway routing inside one container,
with managed Postgres as the second resource. Redis listens only on loopback;
its pub/sub/stream state is intentionally ephemeral in this constrained layout.
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass


ROOT = "/app"
STOP_REQUESTED = False


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
    child = Child(
        name,
        subprocess.Popen(
            command,
            cwd=ROOT,
            env=env or os.environ.copy(),
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


def kyc_env() -> dict[str, str]:
    env = child_env(
        KYC_HTTP_ADDR="127.0.0.1:8083",
        KYC_GRPC_TARGET="127.0.0.1:50051",
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


def run() -> int:
    base_env = child_env(REDIS_URL="redis://127.0.0.1:6379/0")

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
            os.environ.get("WEB_CONCURRENCY", "2"),
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
        [sys.executable, "manage.py", "runkycgrpc", "--addr", "127.0.0.1:50051"],
        env=base_env,
    )
    wait_for_port(grpc, 50051)

    chat = spawn(
        "chat",
        ["/usr/local/bin/chat"],
        env=child_env(REDIS_URL=base_env["REDIS_URL"], CHAT_HTTP_ADDR="127.0.0.1:8081"),
    )
    notification = spawn(
        "notification",
        ["/usr/local/bin/notification"],
        env=child_env(
            REDIS_URL=base_env["REDIS_URL"],
            NOTIF_HTTP_ADDR="127.0.0.1:8082",
        ),
    )
    kyc = spawn("kyc", ["/usr/local/bin/kyc"], env=kyc_env())
    email = spawn(
        "email",
        ["/usr/local/bin/email"],
        env=child_env(REDIS_URL=base_env["REDIS_URL"], EMAIL_HTTP_ADDR="127.0.0.1:8085"),
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
