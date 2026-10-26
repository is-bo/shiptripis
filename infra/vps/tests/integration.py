#!/usr/bin/env python3
"""Destructive ONLY to a freshly generated test Compose project and its volumes.

Run with backend/.venv/bin/python infra/vps/tests/integration.py.
Images must already be built (see README). No deployed endpoint is accepted.
"""
from __future__ import annotations

import json
import http.client
import os
from pathlib import Path
import secrets
import socket
import ssl
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import uuid

import jwt
import psycopg
import redis

HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parents[1]


def main():
    subprocess.run([os.sys.executable, str(HERE / "vps"), "prepare-config"], check=True)
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    root = Path(tempfile.mkdtemp(prefix="wacla-vps-integration-"))
    project = f"wacla-v1-test-{uuid.uuid4().hex[:8]}"
    private = root / "secrets"
    private.mkdir(mode=0o750)
    from importlib.util import spec_from_file_location, module_from_spec
    spec = spec_from_file_location("runtime", HERE / "runtime.py")
    runtime = module_from_spec(spec)
    spec.loader.exec_module(runtime)
    payload = {key: secrets.token_hex(32) for key in (
        "DJANGO_SECRET_KEY", "JWT_HS256_SECRET", "GRPC_BEARER_TOKEN",
        "HANDOVER_CODE_SECRET", "TRANSACTIONAL_EMAIL_SECRET", "S3_ACCESS_KEY", "S3_SECRET_KEY",
        "KYC_S3_ACCESS_KEY", "KYC_S3_SECRET_KEY",
    )}
    (private / "app.json").write_text(json.dumps(payload))
    pg_password, redis_password = secrets.token_hex(32), secrets.token_hex(32)
    for name, value in (("postgres-password", pg_password), ("redis-password", redis_password),
                        ("restic-password", secrets.token_hex(32))):
        (private / name).write_text(value + "\n")
    for file in private.iterdir():
        file.chmod(0o640)
    # Only this new test directory: app UID 10001 must be able to read bind secrets.
    subprocess.run(["docker", "run", "--rm", "--entrypoint", "sh", "-v", f"{private}:/test-secrets",
                    "postgres:16-alpine", "-c", "chgrp -R 10001 /test-secrets"], check=True)
    config = {}
    for line in (HERE / "stack.env.example").read_text().splitlines():
        if line and not line.startswith("#"):
            key, _, value = line.partition("=")
            config[key] = value
    for key, value in list(config.items()):
        if "REPLACE_" in value:
            config[key] = ""
    config.update({
        "APP_IMAGE": os.environ.get("WACLA_TEST_IMAGE", f"wacla-v1-test:{sha}"),
        "BACKUP_IMAGE": os.environ.get("WACLA_BACKUP_TEST_IMAGE", f"wacla-backup-test:{sha}"),
        "RELEASE_ID": sha, "SECRETS_DIR": str(private), "STACK_ENV_FILE": str(root / "stack.env"),
        "BACKUP_ENV_FILE": str(root / "backup.env"), "SITE_ADDRESS": "localhost", "ACME_EMAIL": "",
        "DJANGO_ALLOWED_HOSTS": "localhost", "BIND_IP": "127.0.0.1",
        "ADMIN_CIDRS": "127.0.0.1/32", "WEBSOCKET_ORIGINS": "https://localhost",
        "CORS_ALLOWED_ORIGINS": "https://localhost", "CSRF_TRUSTED_ORIGINS": "https://localhost",
        "PAYMENTS_PUBLIC_BASE_URL": "https://localhost", "FRONTEND_BASE_URL": "https://localhost",
        "S3_ENDPOINT_URL": "https://storage.invalid", "S3_REGION": "test-region",
        "KYC_S3_ENDPOINT_URL": "https://storage.invalid", "KYC_S3_REGION": "test-region",
        "S3_BUCKET_PARCEL": "test-private-media", "S3_BUCKET_PROOF": "test-private-proof",
        "S3_BUCKET_DISPUTE": "test-private-dispute", "S3_BUCKET_KYC": "test-private-kyc",
    })
    envfile = root / "stack.env"
    envfile.write_text("\n".join(f"{k}={v}" for k, v in config.items()) + "\n")
    envfile.chmod(0o600)
    (root / "backup.env").write_text("RESTIC_REPOSITORY=/repository\nBACKUP_TEST_MODE=true\nBACKUP_KEEP_DAILY=2\nBACKUP_KEEP_WEEKLY=2\nBACKUP_KEEP_MONTHLY=2\n")
    (root / "backup.env").chmod(0o600)
    override = root / "test.yml"
    override.write_text("""services:
  postgres:
    ports: ['127.0.0.1::5432']
    networks: [data, egress]
  redis:
    ports: ['127.0.0.1::6379']
    networks: [data, egress]
  backup:
    volumes: [test_repository:/repository]
volumes:
  test_repository: {}
""")
    env = {**os.environ, **config}
    base = ["docker", "compose", "--project-name", project, "--env-file", str(envfile),
            "-f", str(HERE / "compose.yml"), "-f", str(HERE / "compose.local.yml"), "-f", str(override)]

    def dc(*args, **kwargs):
        return subprocess.run([*base, *args], env=env, check=True, **kwargs)

    def captured(*args):
        return dc(*args, stdout=subprocess.PIPE, text=True).stdout.strip()

    def sql(query):
        return captured("exec", "-T", "postgres", "psql", "-U", "wacla", "-d", "wacla", "-Atqc", query)

    def maintain(*args, **kwargs):
        return dc("run", "--rm", "--no-deps", "maintenance", "maintenance", *args, **kwargs)

    def request(path, **headers):
        req = urllib.request.Request("https://localhost:18443" + path, headers=headers)
        try:
            return opener.open(req, timeout=15)
        except urllib.error.HTTPError as error:
            return error

    passed = []
    try:
        production = json.loads(subprocess.check_output([*base[:8], "config", "--format", "json"], env=env, text=True))
        assert production["networks"]["data"]["internal"] is True
        for name, service in production["services"].items():
            assert not service.get("ports") or name == "caddy", name
        assert set(production["services"]["postgres"]["networks"]) == {"data"}
        assert set(production["services"]["redis"]["networks"]) == {"data"}
        resolved = json.loads(captured("config", "--format", "json"))
        for service, data in resolved["services"].items():
            if service not in {"postgres", "redis", "caddy"}:
                assert not data.get("ports"), service
        assert subprocess.check_output(["docker", "image", "inspect", "--format", "{{.Config.User}}", config["BACKUP_IMAGE"]], text=True).strip() == "10001:10001"
        dc("config", "--quiet")
        dc("up", "-d", "--wait", "--wait-timeout", "120", "postgres", "redis")
        pgport = int(captured("port", "postgres", "5432").rsplit(":", 1)[1])
        redisport = int(captured("port", "redis", "6379").rsplit(":", 1)[1])
        client = redis.Redis(host="127.0.0.1", port=redisport, password=redis_password, decode_responses=True)
        # Pending FCM and email work, consumer offsets and a retry survive recreation.
        ids = {}
        for stream in ("notif:fcm", "email:send", "notif:fcm:results"):
            client.xgroup_create(stream, "v1-test-workers", id="0", mkstream=True)
            ids[stream] = client.xadd(stream, {"event_id": uuid.uuid4().hex, "attempt": "1"})
            client.xreadgroup("v1-test-workers", "crashed-consumer", {stream: ">"}, count=1)
            assert client.xpending(stream, "v1-test-workers")["pending"] == 1
        client.save()
        dc("stop", "redis")
        dc("up", "-d", "--force-recreate", "--wait", "redis")
        client.close()
        redisport = int(captured("port", "redis", "6379").rsplit(":", 1)[1])
        client = redis.Redis(host="127.0.0.1", port=redisport, password=redis_password, decode_responses=True)
        assert client.config_get("maxmemory-policy")["maxmemory-policy"] == "noeviction"
        assert client.config_get("appendonly")["appendonly"] == "yes"
        for stream, message_id in ids.items():
            assert client.xpending(stream, "v1-test-workers")["pending"] == 1
            recovered = client.xautoclaim(stream, "v1-test-workers", "recovery-consumer", 0, "0-0")[1]
            assert recovered[0][0] == message_id
            assert recovered[0][1]["attempt"] == "1"
            assert client.xack(stream, "v1-test-workers", message_id) == 1
            next_id = client.xadd(stream, {"event_id": uuid.uuid4().hex})
            next_work = client.xreadgroup("v1-test-workers", "recovery-consumer", {stream: ">"}, count=1)
            assert next_work[0][1][0][0] == next_id
            client.xack(stream, "v1-test-workers", next_id)
        passed.append("Redis streams, pending work, retry metadata, consumer groups and continued processing after recreation")
        maintain("migrate", "--noinput")
        maintain("check", "--deploy", "--fail-level", "WARNING")
        # A second maintenance container must fail while the lock is held.
        with psycopg.connect(host="127.0.0.1", port=pgport, dbname="wacla", user="wacla", password=pg_password, autocommit=True) as conn:
            conn.execute("SELECT pg_advisory_lock(877431104)")
            refused = subprocess.run([*base, "run", "--rm", "--no-deps", "maintenance", "maintenance", "migrate", "--noinput"], env=env, capture_output=True)
            assert refused.returncode != 0
        maintain("migrate", "--check")
        sql("CREATE TABLE v1_durability_probe (id integer PRIMARY KEY, amount_minor bigint CHECK (amount_minor >= 0)); INSERT INTO v1_durability_probe VALUES (1,12345)")
        # Incompressible >1 MiB data exercises pipe buffering and real dump blocks.
        sql("CREATE TABLE v1_backup_payload AS SELECT n, md5(random()::text) || md5(random()::text) AS payload FROM generate_series(1,50000) AS n")
        dc("restart", "postgres")
        dc("up", "-d", "--wait", "postgres")
        assert sql("SELECT amount_minor FROM v1_durability_probe WHERE id=1") == "12345"
        passed.append("PostgreSQL durability, all migrations, production checks and concurrent-migration refusal")
        dc("up", "-d", "--no-build", "--wait", "--wait-timeout", "240", "app", "caddy")
        caddy_id = captured("ps", "-q", "caddy")
        ca = root / "local-ca.crt"
        subprocess.run(["docker", "cp", f"{caddy_id}:/data/caddy/pki/authorities/local/root.crt", str(ca)], check=True)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=str(ca))))
        for path in ("/", "/en/", "/fr/", "/ar/", "/terms", "/privacy", "/support", "/assets/site.css", "/assets/hero.css", "/assets/site.js", "/assets/hero-globe.mjs", "/static/admin/css/base.css", "/healthz", "/readyz"):
            response = request(path)
            assert response.status == 200, (path, response.status)
            assert response.headers.get("X-Content-Type-Options") == "nosniff"
        assert "Wassla" in request("/").read().decode("utf-8"), "owner rename must survive the VPS build"
        assert json.load(request("/readyz"))["checks"] == {"database": "ok", "migrations": "ok", "rate_limit_cache": "ok"}
        assert request("/readyz", **{"X-Forwarded-Proto": "http"}).status == 200
        redirect = http.client.HTTPConnection("127.0.0.1", 18080, timeout=10)
        redirect.request("GET", "/readyz", headers={"Host": "localhost"})
        assert redirect.getresponse().status == 308
        redirect.close()
        assert request("/api/matches").status == 401
        assert request("/kyc/submit").status in (401, 405)
        assert request("/api/kyc/submit").status in (401, 405)
        assert request("/admin/").status == 403
        assert request("/admin/invitations/accept?language=ar").status == 403
        assert request("/api/admin/health/deep").status == 403
        assert request("/debug/vars").status == 404
        assert request("/ws/chat", Origin="https://attacker.invalid").status == 403
        assert request("/ws/chat").status == 401
        # The outer edge must strip spoofed XFF, while preserving distinct
        # client identities through the second proxy for Django throttles.
        network = project + "_egress"
        client_script = '''import json, socket, ssl, sys
ctx=ssl.create_default_context(cadata=sys.argv[2]); statuses=[]
for attempt in range(int(sys.argv[1])):
 with socket.create_connection(('caddy',443),timeout=10) as raw:
  with ctx.wrap_socket(raw,server_hostname='localhost') as connection:
   connection.sendall(('POST /api/auth/sign-up HTTP/1.1\\r\\nHost: localhost\\r\\nContent-Type: application/json\\r\\nContent-Length: 2\\r\\nConnection: close\\r\\nX-Forwarded-For: 203.0.113.%d\\r\\n\\r\\n{}' % (attempt+1)).encode())
   statuses.append(int(connection.recv(8192).split()[1]))
print(json.dumps(statuses))
'''
        def attempts(in_app, count):
            # Docker-assigned addresses avoid a fixed subnet and work with the
            # default Compose IPAM. Keep app alive as one identity; the client
            # container provides a second identity without recycling its IP.
            command = (["docker", "exec", captured("ps", "-q", "app"), "python"] if in_app else
                       ["docker", "run", "--rm", "--network", network, "--entrypoint", "python", config["APP_IMAGE"]])
            return json.loads(subprocess.check_output([*command, "-c", client_script,
                str(count), ca.read_text()], text=True))
        assert attempts(True, 6) == [400, 400, 400, 400, 400, 429]
        assert attempts(False, 1) == [400]
        passed.append("Distinct client IP throttles and spoofed forwarded-header rejection through both proxies")
        # Actual TLS + HTTP/1.1 upgrade; no provider or account write needed.
        token = jwt.encode({"user_id": 999999, "typ": "access", "role": "sender", "exp": int(time.time()) + 60}, payload["JWT_HS256_SECRET"], algorithm="HS256")
        context = ssl.create_default_context(cafile=str(ca))
        for path in ("/ws/chat", "/ws/notifications"):
            with socket.create_connection(("127.0.0.1", 18443), timeout=10) as raw:
                with context.wrap_socket(raw, server_hostname="localhost") as connection:
                    frame = f"GET {path} HTTP/1.1\r\nHost: localhost\r\nAuthorization: Bearer {token}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nOrigin: https://localhost\r\n\r\n"
                    connection.sendall(frame.encode())
                    response = connection.recv(8192)
                    assert b"101 Switching Protocols" in response, response[:100]
        passed.append("Trusted local TLS, public/legal/API/KYC/Admin routes, browser-origin refusal and both WebSocket upgrades")
        # A failed child must take down the entire unit; no hidden missing workers.
        app_id = captured("ps", "-q", "app")
        state = json.loads(subprocess.check_output(["docker", "inspect", app_id], text=True))[0]
        assert state["Config"]["User"] == "10001:10001"
        assert state["HostConfig"]["ReadonlyRootfs"]
        assert not state["HostConfig"].get("PortBindings")
        dc("stop", "-t", "40", "app")
        stopped = json.loads(subprocess.check_output(["docker", "inspect", app_id], text=True))[0]
        assert stopped["State"]["ExitCode"] == 0
        dc("up", "-d", "--wait", "--wait-timeout", "180", "app")
        passed.append("Non-root read-only app, private ports, clean shutdown and restart readiness")
        before = json.loads(subprocess.check_output(["docker", "inspect", app_id], text=True))[0]["RestartCount"]
        dc("exec", "-T", "app", "python", "-c", """import os, signal
from pathlib import Path
for item in Path('/proc').glob('[0-9]*/cmdline'):
 try:
  if item.read_bytes().split(b'\\0')[0] == b'/usr/local/bin/email':
   os.kill(int(item.parent.name),signal.SIGTERM); break
 except (OSError, ValueError): pass
else: raise RuntimeError('email worker not found')
""")
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            state = json.loads(subprocess.check_output(["docker", "inspect", app_id], text=True))[0]
            if state["RestartCount"] > before and state["State"].get("Health", {}).get("Status") == "healthy":
                break
            time.sleep(2)
        else:
            raise AssertionError("worker crash did not recover to full application health")
        passed.append("Worker crash propagates to the supervisor and bounded restart restores every process")
        # Only the disposable loopback stack: permit its Docker bridge client
        # to exercise the invitation page through both production proxies.
        # The deployed CIDR policy and the denied-path checks above stay intact.
        env["ADMIN_CIDRS"] = "0.0.0.0/0"
        dc("up", "-d", "--force-recreate", "--wait", "caddy")
        response = request("/admin/invitations/accept?language=ar")
        assert response.status == 200
        assert response.headers["Referrer-Policy"] == "no-referrer"
        assert "no-store" in response.headers["Cache-Control"]
        assert "script-src 'nonce-" in response.headers["Content-Security-Policy"]
        assert 'lang="ar" dir="rtl"' in response.read().decode()
        env["ADMIN_CIDRS"] = config["ADMIN_CIDRS"]
        dc("up", "-d", "--force-recreate", "--wait", "caddy")
        assert request("/admin/invitations/accept").status == 403
        passed.append("Localized invitation landing, capability headers and unchanged admin CIDR enforcement through both proxies")
        dc("run", "--rm", "--no-deps", "backup", "init")
        dc("run", "--rm", "--no-deps", "backup", "backup")
        # Failed pg_dump must fail the backup and never become a good snapshot.
        failed_backup = subprocess.run([*base, "run", "--rm", "--no-deps", "-e", "PGDATABASE=missing_v1_test_database", "backup", "backup"], env=env, capture_output=True)
        assert failed_backup.returncode != 0
        snapshots = json.loads(captured("run", "--rm", "--no-deps", "--entrypoint", "restic", "backup", "snapshots", "--json"))
        assert len(snapshots) == 1, "failed pg_dump must not create a recovery point"
        snapshot = snapshots[-1]["id"]
        dc("run", "--rm", "--no-deps", "backup", "verify", snapshot)
        dump = root / "restore.dump"
        with dump.open("wb") as handle:
            dc("run", "--rm", "--no-deps", "-T", "backup", "export", snapshot, stdout=handle)
        assert dump.stat().st_size > 1024 * 1024
        restore = ["docker", "compose", "-p", project + "-restore", "-f", str(HERE / "restore.yml")]
        try:
            subprocess.run([*restore, "up", "-d", "--wait"], check=True)
            with dump.open("rb") as handle:
                subprocess.run([*restore, "exec", "-T", "restore", "pg_restore", "--exit-on-error", "--no-owner", "--no-privileges", "-U", "restore_verify", "-d", "restore_verify"], check=True, stdin=handle)
            result = subprocess.check_output([*restore, "exec", "-T", "restore", "psql", "-U", "restore_verify", "-d", "restore_verify", "-Atqc", "SELECT amount_minor FROM v1_durability_probe WHERE id=1"], text=True)
            assert result.strip() == "12345"
        finally:
            subprocess.run([*restore, "down", "--volumes"], check=True)
            dump.unlink(missing_ok=True)
        passed.append("Encrypted backup, checksums, full repository read verification, isolated restore and restored value")
        # Corrupt ONLY the freshly created test repository after successful restore.
        dc("run", "--rm", "--no-deps", "--entrypoint", "sh", "backup", "-c",
           "find /repository/data -type f -exec sh -c 'chmod u+w \"$1\" && printf corrupted > \"$1\"' _ {} \\;")
        damaged = subprocess.run([*base, "run", "--rm", "--no-deps", "backup", "verify", snapshot], env=env, capture_output=True)
        assert damaged.returncode != 0
        passed.append("Corrupted repository refusal and failed-dump failure detection")
        print(json.dumps({"passed": passed, "project": project, "test_directory": str(root)}, indent=2))
    finally:
        if os.environ.get("WACLA_KEEP_TEST_STACK") == "true":
            # Contains no secret values. Useful for full regression against this isolated DB.
            (Path("/tmp") / "wacla-vps-test-session.json").write_text(json.dumps({"compose": base, "directory": str(root), "project": project}))
        else:
            dc("down", "--volumes", "--remove-orphans")


if __name__ == "__main__":
    main()
