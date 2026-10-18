"""Failure-path tests for operator state, secret boundaries and V1 refusal."""
import importlib.machinery
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
cli = importlib.machinery.SourceFileLoader("vps_cli", str(HERE / "vps")).load_module()
runtime = importlib.machinery.SourceFileLoader("vps_runtime", str(HERE / "runtime.py")).load_module()


class V1BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.environment = {
            "SHIPTRIP_ENVIRONMENT": "production", "DJANGO_DEBUG": "false",
            "SHIPTRIP_EMBEDDED_REDIS": "false", "PAYMENTS_ENVIRONMENT": "test",
            "PAYMENTS_ALLOW_MOCK_PROVIDER": "false", "EMAIL_ENABLED": "false",
            "PAYMENTS_MOCK_WEBHOOK_ENABLED": "false", "PAYMENTS_LEGACY_MUTATIONS_ENABLED": "false",
            "PAYOUT_DZD_EXECUTION_ENABLED": "false", "STRIPE_CONNECT_PAYOUTS_ENABLED": "false",
            "STRIPE_CONNECT_NON_STRIPE_FUNDING_ENABLED": "false", "STRIPE_CONNECT_EXPECTED_MODE": "test",
        }

    def test_every_financial_email_and_security_switch_fails_closed(self):
        for name in self.environment:
            with self.subTest(name=name), patch.dict(os.environ, {**self.environment, name: "unsafe"}, clear=True):
                with self.assertRaises(RuntimeError):
                    runtime.v1_guards()

    def test_no_alternate_database_or_redis(self):
        for name in ("DATABASE_URL", "ROUTE_PROVIDER_CACHE_URL"):
            with self.subTest(name=name), patch.dict(os.environ, {**self.environment, name: "different"}, clear=True):
                with self.assertRaises(RuntimeError):
                    runtime.v1_guards()

    def test_valid_inactive_configuration(self):
        with patch.dict(os.environ, self.environment, clear=True):
            runtime.v1_guards()

    def test_kyc_uses_the_same_private_bucket_as_django(self):
        with patch.dict(os.environ, {"S3_BUCKET_KYC": "private-reviewed-kyc"}, clear=True), \
             patch.object(sys, "argv", ["runtime", "maintenance", "check"]), \
             patch.object(runtime, "load_secrets"), patch.object(runtime, "v1_guards"), \
             patch.object(runtime, "maintenance"):
            runtime.main()
            self.assertEqual(os.environ["KYC_S3_BUCKET"], "private-reviewed-kyc")

    def test_pending_migrations_prevent_starting_any_process(self):
        with patch.dict(os.environ, {"S3_BUCKET_KYC": "private-kyc"}, clear=True), \
             patch.object(sys, "argv", ["runtime", "serve"]), \
             patch.object(runtime, "load_secrets"), patch.object(runtime, "v1_guards"), \
             patch.object(runtime.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "migrate")) as check:
            with self.assertRaises(subprocess.CalledProcessError):
                runtime.main()
            self.assertEqual(check.call_args.args[0][1:], ["manage.py", "migrate", "--check"])

    def test_unknown_secret_cannot_override_process_environment(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "app_secrets").write_text(json.dumps({"PATH": "/attacker"}))
            with self.assertRaises(RuntimeError):
                runtime.load_secrets(root)

    def test_duplicate_secret_source_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "app_secrets").write_text(json.dumps({"JWT_HS256_SECRET": "file-secret"}))
            with patch.dict(os.environ, {"JWT_HS256_SECRET": "env-secret"}), self.assertRaises(RuntimeError):
                runtime.load_secrets(root)

    def test_image_reference_must_be_immutable(self):
        for image in ("app:latest", "app:release", "app:abcdef", "app", "app:abc; rm -rf /"):
            self.assertFalse(cli.immutable(image))
        self.assertTrue(cli.immutable("registry.example/wacla:" + "a" * 40))
        self.assertTrue(cli.immutable("registry.example/wacla@sha256:" + "a" * 64))

    def test_env_parser_never_executes_shell_or_substitutions(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "stack.env"
            for payload in ("KEY=$(id)", "KEY=`id`", "KEY=one\nKEY=two", "export KEY=value"):
                path.write_text(payload)
                with self.assertRaises(ValueError):
                    cli.read_env(path)

    def test_backup_credentials_cannot_be_read_by_a_container_group(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "backup.env"
            path.write_text("placeholder-only")
            path.chmod(0o640)
            with self.assertRaises(ValueError):
                cli.private_file(path)
            path.chmod(0o600)
            cli.private_file(path)


class ReleaseRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name)
        self.old = {"APP_IMAGE": "wacla:" + "a" * 40, "RELEASE_ID": "a" * 40}
        self.new = {"APP_IMAGE": "wacla:" + "b" * 40, "RELEASE_ID": "b" * 40}
        self.config = {**self.new, "BACKUP_IMAGE": "backup:" + "b" * 40}
        (self.state / "release.json").write_text(json.dumps({"current": self.old,
            "previous": {"APP_IMAGE": "wacla:" + "c" * 40, "RELEASE_ID": "c" * 40}}))
        self.calls = []

    def execute(self, arguments, fail_ready=False):
        def record(args, **kwargs):
            self.calls.append((list(args), dict(kwargs.get("env", {}))))
            if fail_ready and "up" in args and "app" in args:
                raise subprocess.CalledProcessError(1, args)
            return subprocess.CompletedProcess(args, 0)

        with patch.object(cli, "STATE", self.state), patch.object(cli, "validate"), \
             patch.object(cli, "read_env", return_value=self.config), patch.object(cli, "run", side_effect=record), \
             patch.object(cli, "reviewed_source", return_value=self.state / "reviewed-source"), \
             patch.object(cli.subprocess, "check_output", side_effect=["b" * 40, b""]), \
             patch.object(cli.subprocess, "run", return_value=subprocess.CompletedProcess([], 1)), \
             patch.object(sys, "argv", ["vps", *arguments]):
            cli.main()

    def test_build_never_overwrites_current_release_tag(self):
        self.execute(["build"])
        builds = [(args, env) for args, env in self.calls if "build" in args]
        self.assertEqual(builds[0][1]["APP_IMAGE"], self.new["APP_IMAGE"])

    def test_email_audit_uses_locked_maintenance_without_starting_application(self):
        self.execute(["email-audit", "--limit", "25"])
        commands = [args for args, env in self.calls]
        self.assertTrue(any(args[-3:] == ["audit_email_backlog", "--limit", "25"] for args in commands))
        self.assertFalse(any("up" in args or "deploy" in args for args in commands))

    def test_incomplete_deploy_keeps_recovery_source(self):
        with self.assertRaises(subprocess.CalledProcessError):
            self.execute(["deploy", self.new["APP_IMAGE"], self.new["RELEASE_ID"]], fail_ready=True)
        self.assertEqual(json.loads((self.state / "deployment-pending.json").read_text())["source"], self.old)
        self.assertEqual(json.loads((self.state / "release.json").read_text())["current"], self.old)

    def test_rollback_recovers_source_of_incomplete_deploy(self):
        (self.state / "deployment-pending.json").write_text(json.dumps({"source": self.old, "target": self.new}))
        self.execute(["rollback", "--schema-compatibility-reviewed"])
        app_starts = [env for args, env in self.calls if "up" in args and "app" in args]
        self.assertEqual(app_starts[-1]["APP_IMAGE"], self.old["APP_IMAGE"])
        self.assertFalse((self.state / "deployment-pending.json").exists())

    def test_rollback_requires_reviewed_schema_compatibility(self):
        with self.assertRaises(ValueError):
            self.execute(["rollback"])
        self.assertEqual(self.calls, [])

    def test_start_refuses_incomplete_release(self):
        (self.state / "deployment-pending.json").write_text("{}")
        with self.assertRaises(ValueError):
            self.execute(["start"])

    def test_monitor_does_not_wait_for_backup_lock(self):
        with patch.object(cli.fcntl, "flock") as lock:
            self.execute(["monitor"])
        lock.assert_not_called()

    def test_mixed_root_and_deploy_state_is_refused_before_lock_creation(self):
        with patch.object(cli, "STATE", self.state), \
             patch.object(cli.os, "geteuid", return_value=self.state.stat().st_uid + 1):
            with self.assertRaisesRegex(ValueError, "deployment user"):
                cli.prepare_state()
        self.assertFalse((self.state / "operator.lock").exists())

    def test_shared_state_is_refused_before_release_markers_are_used(self):
        self.state.chmod(0o777)
        with patch.object(cli, "STATE", self.state):
            with self.assertRaisesRegex(ValueError, "private mode 0700"):
                cli.prepare_state()
        self.assertFalse((self.state / "operator.lock").exists())

    def test_stop_works_with_missing_configuration(self):
        with patch.object(cli, "STATE", self.state), patch.object(cli, "read_env", side_effect=FileNotFoundError), \
             patch.object(cli.subprocess, "check_output", return_value=""), patch.object(sys, "argv", ["vps", "stop"]):
            cli.main()


class CheckoutPermissionTests(unittest.TestCase):
    def test_restrictive_checkout_is_prepared_without_relaxing_secrets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in cli.PUBLIC_RUNTIME_FILES:
                path = root / name
                path.write_text("non-secret runtime fixture")
                path.chmod(0o600)
            secret = root / "app.json"
            secret.write_text("private fixture")
            secret.chmod(0o600)
            with patch.object(cli, "HERE", root), patch.object(sys, "argv", ["vps", "prepare-config"]):
                cli.main()
            for name in cli.PUBLIC_RUNTIME_FILES:
                self.assertEqual((root / name).stat().st_mode & 0o777, 0o644)
            self.assertEqual(secret.stat().st_mode & 0o777, 0o600)


class ArtifactBoundaryTests(unittest.TestCase):
    def test_reviewed_archive_excludes_ignored_secrets_and_uncommitted_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
            (repo / "tracked.txt").write_text("reviewed bytes")
            (repo / ".gitignore").write_text("*.env\n")
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "-c", "user.name=VPS test", "-c", "user.email=vps-test@example.invalid",
                            "commit", "--quiet", "-m", "fixture"], cwd=repo, check=True)
            sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
            (repo / "private.env").write_text("SECRET=fixture-only")
            (repo / "tracked.txt").write_text("uncommitted owner bytes")
            build = root / "build"
            build.mkdir()
            context = cli.reviewed_source(repo, sha, build)
            self.assertFalse((context / "private.env").exists())
            self.assertEqual((context / "tracked.txt").read_text(), "reviewed bytes")
            self.assertEqual((repo / "tracked.txt").read_text(), "uncommitted owner bytes")


if __name__ == "__main__":
    unittest.main()
