import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("monitor", Path(__file__).resolve().parents[1] / "monitor.py")
monitor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(monitor)


class MonitorTests(unittest.TestCase):
    def check(self, broken):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "backup-last-success"
            marker.write_text("0" if broken else str(time.time()))
            def capture(*args):
                if "stats" in args:
                    return json.dumps({"Name": "wacla-app-1", "CPUPerc": "25%", "MemPerc": "99%" if broken else "12%"})
                if "ps" in args:
                    return "\n".join(json.dumps({"Service": name, "State": "running", "Health": "healthy"})
                                     for name in ("app", "postgres", "redis", "caddy"))
                if "exec" in args:
                    return f"aof_enabled:{0 if broken else 1}\naof_last_write_status:ok\nrdb_last_bgsave_status:ok\n"
                return json.dumps({"event": "ops_snapshot", "ops": {"jobs_oldest_overdue_seconds": None,
                    "outbound_oldest_overdue_seconds": None, "jobs_failed_unresolved": int(broken),
                    "connections": 95 if broken else 10, "max_connections": 100}})
            output = io.StringIO()
            with patch.dict(os.environ, {"WACLA_STATE": directory, "STACK_ENV_FILE": "/unused"}), \
                 patch.object(monitor, "capture", side_effect=capture), \
                 patch.object(monitor.shutil, "disk_usage", return_value=SimpleNamespace(total=100, used=40)), \
                 patch.object(monitor.os, "getloadavg", return_value=(0.1, 0.1, 0.1)), \
                 patch("sys.stdout", output):
                result = monitor.main()
            return result, json.loads(output.getvalue())

    def test_empty_backlogs_with_null_ages_are_healthy(self):
        result, report = self.check(False)
        self.assertEqual(result, 0)
        self.assertEqual(report["problems"], [])

    def test_persistence_backlog_memory_connections_and_backup_failure_alert(self):
        result, report = self.check(True)
        self.assertEqual(result, 1)
        self.assertTrue({"redis_persistence_unhealthy", "financial_job_backlog", "database_connection_pressure",
                         "container_memory_over_85_percent", "backup_missing_or_stale"} <= set(report["problems"]))


if __name__ == "__main__":
    unittest.main()
