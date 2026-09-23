"""Serve the monolith like the Railway container does, on a Windows box.

Production runs ``gunicorn --worker-class gthread --workers W --threads T``
behind Caddy (``backend/railway/start.py``). Gunicorn does not run on Windows,
so this supervisor starts W independent Waitress processes with T threads each
-- the same process x thread shape, one Python interpreter and one GIL per
worker -- and, with ``--caddy``, a real Caddy in front using ``least_conn`` so
a busy worker is not handed new requests while an idle one waits. That is the
closest Windows equivalent of Gunicorn's shared accept socket.

    python backend/loadtest/serve.py --workers 2 --threads 2 --caddy path/to/caddy.exe

Process ids are written to ``.data/serve.json`` for ``monitor.py``. Ctrl+C (or
killing the supervisor) stops every child.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

LOADTEST_DIR = Path(__file__).resolve().parent
DATA_DIR = LOADTEST_DIR / ".data"


def run_worker(port: int, threads: int) -> None:
    """One Gunicorn-worker equivalent: a Django WSGI app in a threaded server."""

    sys.path.insert(0, str(LOADTEST_DIR))
    import manage_loadtest

    manage_loadtest.bootstrap()
    os.chdir(manage_loadtest.MONOLITH_DIR)
    from django.core.wsgi import get_wsgi_application
    from waitress import serve

    application = get_wsgi_application()
    serve(
        application,
        host="127.0.0.1",
        port=port,
        threads=threads,
        # Gunicorn's gthread worker keeps up to 1000 client connections per
        # worker; Waitress defaults to 100 and would refuse first.
        connection_limit=1000,
        backlog=2048,
        channel_timeout=120,
        ident="shiptrip-loadtest",
        _quiet=True,
    )


def _wait_for_port(port: int, process: subprocess.Popen, timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"process on {port} exited with {process.returncode}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError(f"nothing listening on {port} after {timeout}s")


def _warm(port: int) -> None:
    """First request imports every URLconf and view module, as warm-up would."""

    with socket.create_connection(("127.0.0.1", port), timeout=30) as conn:
        conn.sendall(b"GET /healthz HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n")
        while conn.recv(4096):
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--workers", type=int, default=2, help="WEB_CONCURRENCY equivalent")
    parser.add_argument("--threads", type=int, default=2, help="WEB_THREADS equivalent")
    parser.add_argument("--base-port", type=int, default=8001)
    parser.add_argument("--caddy", help="path to a caddy binary; omit to skip the edge")
    parser.add_argument("--port", type=int, default=8080, help="Caddy listen port")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.worker:
        run_worker(args.base_port, args.threads)
        return 0

    if pgdata := os.environ.get("LOADTEST_PGDATA", "").strip():
        # Start the embedded cluster once, here. Several workers racing to
        # start it is how a pgserver data directory wedges on Windows.
        import pgserver

        pgserver.get_server(pgdata, cleanup_mode=None)

    children: list[tuple[str, subprocess.Popen]] = []
    ports =[args.base_port + index for index in range(args.workers)]

    def stop(*_: object) -> None:
        for _name, child in reversed(children):
            if child.poll() is None:
                child.terminate()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    try:
        for port in ports:
            child = subprocess.Popen(
                [
                    sys.executable,
                    __file__,
                    "--worker",
                    "--base-port",
                    str(port),
                    "--threads",
                    str(args.threads),
                ],
                env=os.environ.copy(),
            )
            children.append((f"web-{port}", child))
        for (name, child), port in zip(children, ports):
            _wait_for_port(port, child)
            _warm(port)
            print(f"{name} ready (pid {child.pid}, {args.threads} threads)", flush=True)

        if args.caddy:
            env = os.environ.copy()
            env["LOADTEST_PORT"] = str(args.port)
            env["LOADTEST_UPSTREAMS"] = " ".join(f"127.0.0.1:{port}" for port in ports)
            caddy = subprocess.Popen(
                [
                    args.caddy,
                    "run",
                    "--config",
                    str(LOADTEST_DIR / "Caddyfile"),
                    "--adapter",
                    "caddyfile",
                ],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            children.append(("caddy", caddy))
            _wait_for_port(args.port, caddy)
            print(f"caddy ready on :{args.port} -> {env['LOADTEST_UPSTREAMS']}", flush=True)

        DATA_DIR.mkdir(exist_ok=True)
        (DATA_DIR / "serve.json").write_text(
            json.dumps(
                {
                    "workers": args.workers,
                    "threads": args.threads,
                    "processes": {name: child.pid for name, child in children},
                    "entry": f"http://127.0.0.1:{args.port if args.caddy else ports[0]}",
                }
            ),
            encoding="utf-8",
        )
        print("serving; Ctrl+C to stop", flush=True)
        while True:
            for name, child in children:
                if child.poll() is not None:
                    raise RuntimeError(f"{name} exited with {child.returncode}")
            time.sleep(0.5)
    finally:
        for _name, child in reversed(children):
            if child.poll() is None:
                child.terminate()


if __name__ == "__main__":
    raise SystemExit(main())
