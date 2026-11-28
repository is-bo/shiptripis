"""Neither proxy writes a guest payment token to its logs (G1).

The path of a guest payment link is the credential: `/pay/guest/<token>` for
the page and `/api/payments/guest/<token>[/checkout]` for the app. Neither
Caddy keeps access logs, but Caddy's error logger is separate from access
logging and records the request of every failed one -- a 502 while an upstream
is down, for instance. Caddy logs the URI as the client sent it, so a regex on
the guest prefix is defeated by an encoded separator (`/pay%2Fguest/...`) that
the application still routes. Both Caddyfiles therefore drop `request>uri` and
`request>headers>Referer` from every log entry.

The proxy also answers that 502 itself, so Django's private headers are never
set on it. Both Caddyfiles add `Referrer-Policy: no-referrer` and
`Cache-Control: private, no-store` to every error they answer.

Each case runs the shipped Caddyfile unchanged, with its upstream deliberately
absent, sends a synthetic token under plain and encoded paths and Referers, and
reads what Caddy logged. The 502s, their headers and one `http.log.error` line
per request are asserted too, so the check cannot pass because nothing was
logged at all.

Uses `CADDY_BIN` or a `caddy` on PATH when present, otherwise Docker with the
pinned production image; skips when neither is available.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
#: The production image, read from compose.yml so the pin lives in one place.
IMAGE = re.search(
    r"^\s*image:\s*(caddy:\S+)", (HERE / "compose.yml").read_text(), re.M
).group(1)


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _get(url: str, **headers: str):
    """The status and headers of one GET, an HTTP error included."""

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        response = opener.open(urllib.request.Request(url, headers=headers), timeout=15)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        return response.status, response.headers


def _fragments(token: str, width: int = 8) -> set[str]:
    """Every run of `width` characters of the token."""

    return {token[start : start + width] for start in range(len(token) - width + 1)}


class _Caddy:
    """One Caddy process or container running a config; yields its log."""

    def __init__(self, config: Path, env: dict[str, str], port: int):
        self.config, self.env, self.port = config, env, port
        self.binary = os.environ.get("CADDY_BIN") or shutil.which("caddy")

    def __enter__(self):
        self.log = tempfile.TemporaryFile()
        if self.binary:
            self.process = subprocess.Popen(
                [self.binary, "run", "--config", str(self.config), "--adapter", "caddyfile"],
                env={**os.environ, **self.env},
                stdout=self.log,
                stderr=subprocess.STDOUT,
            )
        else:
            self.name = f"wassla-proxy-logs-{secrets.token_hex(4)}"
            subprocess.run(
                [
                    "docker", "run", "-d", "--name", self.name,
                    "-p", f"127.0.0.1:{self.port}:{self.port}",
                    *[arg for key, value in self.env.items() for arg in ("-e", f"{key}={value}")],
                    "-v", f"{self.config}:/etc/caddy/Caddyfile:ro",
                    IMAGE, "caddy", "run", "--config", "/etc/caddy/Caddyfile",
                    "--adapter", "caddyfile",
                ],
                check=True,
                stdout=subprocess.DEVNULL,
            )
        # A published Docker port accepts connections before Caddy serves, so
        # readiness is Caddy saying so, not an open socket.
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if "serving initial configuration" in self._read():
                return self
            time.sleep(0.2)
        self.__exit__(None, None, None)
        raise AssertionError(f"Caddy did not start:\n{self.output}")

    def _read(self) -> str:
        if self.binary:
            self.log.seek(0)
            return self.log.read().decode("utf-8", "replace")
        logs = subprocess.run(["docker", "logs", self.name], capture_output=True, text=True)
        return logs.stdout + logs.stderr

    def __exit__(self, *exc):
        if self.binary:
            self.process.terminate()
            self.process.wait(timeout=30)
            self.output = self._read()
        else:
            self.output = self._read()
            subprocess.run(["docker", "rm", "-f", self.name], capture_output=True)
        self.log.close()
        return False


@unittest.skipUnless(
    os.environ.get("CADDY_BIN") or shutil.which("caddy") or shutil.which("docker"),
    "needs a caddy binary or Docker",
)
class ProxyErrorLogTests(unittest.TestCase):
    def _assert_tokens_redacted(self, config: Path, env: dict[str, str], port: int):
        token = "g1" + secrets.token_urlsafe(32)
        # Plain, then encodings the application decodes to the same route: an
        # encoded separator, in either case, an encoded letter, and an encoded
        # separator before the token.
        paths = (
            f"/pay/guest/{token}?lang=en",
            f"/api/payments/guest/{token}",
            f"/api/payments/guest/{token}/checkout",
            f"/pay%2Fguest/{token}",
            f"/pay%2fguest/{token}",
            f"/api%2Fpayments%2Fguest/{token}/checkout",
            f"/%70ay/guest/{token}",
            f"/pay/guest%2F{token}",
        )
        # A browser that ignored the page's no-referrer policy would name the
        # page in Referer on its next request, encoded or not.
        referers = (
            f"https://wassla.example/pay/guest/{token}",
            f"https://wassla.example/pay%2Fguest/{token}",
        )
        with _Caddy(config, env, port) as caddy:
            answers = [
                _get(f"http://127.0.0.1:{port}{path}", Referer=referer)
                for path in paths
                for referer in referers
            ]
        log = caddy.output
        self.assertEqual({status for status, _ in answers}, {502}, log)
        # The proxy answers the 502 itself, with the guest page's headers.
        for _, headers in answers:
            self.assertEqual(headers["Referrer-Policy"], "no-referrer")
            directives = {part.strip() for part in headers["Cache-Control"].split(",")}
            self.assertEqual(directives, {"private", "no-store"})
        errors = []
        for line in log.splitlines():
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if entry.get("logger") == "http.log.error":
                errors.append(entry)
        # The error logger fired for every request, without the URI or Referer.
        self.assertEqual(len(errors), len(answers), log)
        for entry in errors:
            self.assertEqual(entry["status"], 502)
            self.assertNotIn("uri", entry["request"])
            self.assertNotIn("Referer", entry["request"].get("headers", {}))
        leaked = sorted(part for part in _fragments(token) if part in log)
        self.assertEqual(leaked, [], log)

    def test_the_gateway_redacts_the_token_when_django_is_down(self):
        # Nothing listens on the gateway's Django upstream, 127.0.0.1:8000.
        port = _free_port()
        self._assert_tokens_redacted(
            HERE / "gateway.Caddyfile", {"PORT": str(port)}, port
        )

    def test_the_edge_redacts_the_token_when_the_app_is_down(self):
        # The edge's upstream, `app`, does not resolve outside the stack. The
        # site is served over plain HTTP on a free port for the test only.
        port = _free_port()
        self._assert_tokens_redacted(
            HERE / "Caddyfile",
            {
                "SITE_ADDRESS": f"http://:{port}",
                "TLS_DIRECTIVE": "",
                "ACME_EMAIL": "owner@example.invalid",
                "ADMIN_CIDRS": "127.0.0.1/32",
                "WEBSOCKET_ORIGINS": "https://localhost",
            },
            port,
        )


if __name__ == "__main__":
    unittest.main()
