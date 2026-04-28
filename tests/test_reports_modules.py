from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from modules.session_audit import SessionAuditModule
from modules.snapshot_compare import SnapshotCompareModule


class SessionAuditTests(unittest.TestCase):
    def test_session_lifecycle_and_filters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "audit.db"
            audit = SessionAuditModule(db)
            sid = "s1"
            audit.start_session(sid)
            audit.log_event(
                sid,
                event_type="debug",
                action="adb_command",
                status="ok",
                device_serial="ABC",
                message="ok",
                payload={"cmd": "shell getprop"},
            )
            audit.log_event(
                sid,
                event_type="file",
                action="push_file",
                status="error",
                device_serial="ABC",
                message="failed",
            )
            summary = audit.summarize_session(sid)
            self.assertEqual(summary["events_total"], 2)
            self.assertEqual(summary["events_error"], 1)
            audit.end_session(sid, summary=summary)

            sessions = audit.list_sessions()
            self.assertEqual(len(sessions), 1)
            events_debug = audit.list_events(session_id=sid, event_type="debug")
            self.assertEqual(len(events_debug), 1)

            out_json = Path(tmp) / "s1.json"
            payload = audit.export_session_json(sid, out_json)
            self.assertTrue(out_json.exists())
            self.assertEqual(payload["session"]["session_id"], sid)

            out_html = Path(tmp) / "s1.html"
            audit.export_session_html(sid, out_html)
            self.assertTrue(out_html.exists())

    def test_health_timeline_extracts_health_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "audit.db"
            audit = SessionAuditModule(db)
            sid = "s-health"
            audit.start_session(sid)
            audit.log_event(
                sid,
                event_type="system",
                action="device_health_checks",
                status="ok",
                device_serial="ABC",
                message="Healthy (92/100)",
                payload={"score": 92, "status": "Healthy"},
            )
            audit.log_event(
                sid,
                event_type="system",
                action="manual_refresh",
                status="ok",
                device_serial="ABC",
                message="refresh",
            )
            rows = audit.list_health_timeline(device_serial="ABC", limit=20)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["score"], 92)
            self.assertEqual(rows[0]["status"], "Healthy")


class _StubADB:
    def __init__(self) -> None:
        self.calls = []

    def run(self, args, serial=None, timeout=None):
        self.calls.append((tuple(args), serial, timeout))

        class R:
            def __init__(self, ok=True, stdout="", stderr=""):
                self.ok = ok
                self.stdout = stdout
                self.stderr = stderr

        key = " ".join(args)
        if "getprop ro.build.version.release" in key:
            return R(True, "14")
        if "getprop ro.build.version.sdk" in key:
            return R(True, "34")
        if "getprop ro.product.brand" in key:
            return R(True, "google")
        if "getprop ro.product.model" in key:
            return R(True, "Pixel")
        if "getprop ro.product.cpu.abi" in key:
            return R(True, "arm64-v8a")
        if "getprop ro.debuggable" in key:
            return R(True, "1")
        if "dumpsys cpuinfo" in key:
            return R(True, "12.3% TOTAL: 5.1% user + 7.2% kernel")
        if "cat /proc/meminfo" in key:
            return R(True, "MemTotal:       8000000 kB\nMemAvailable:   2000000 kB\n")
        return R(True, "")


class _StubAppModule:
    def list_packages(self, serial, include_system=False):
        return ["com.demo.a", "com.demo.b"]


class _StubInspector:
    def inspect(self, serial, device=None):
        return {
            "model": "Pixel",
            "transport": "usb",
            "state": "device",
            "root": "no",
            "debug_status": "enabled",
            "storage_available": "10.0 GB",
        }


class SnapshotCompareTests(unittest.TestCase):
    def test_compare_detects_package_and_state_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mod = SnapshotCompareModule(
                _StubADB(),
                _StubAppModule(),
                _StubInspector(),
                Path(tmp),
            )
            old = {
                "captured_at": "2026-01-01T00:00:00Z",
                "serial": "A",
                "packages_user": ["com.a", "com.b"],
                "inspector": {"storage_available": "10.0 GB"},
                "device": {"transport": "usb", "state": "device", "root": False, "debug": "enabled"},
                "system_properties": {"ro.product.model": "Pixel"},
                "monitor": {"cpu_total": 10.0, "mem_available_kb": 1000},
            }
            new = {
                "captured_at": "2026-01-01T01:00:00Z",
                "serial": "A",
                "packages_user": ["com.b", "com.c"],
                "inspector": {"storage_available": "8.0 GB"},
                "device": {"transport": "wifi", "state": "device", "root": False, "debug": "enabled"},
                "system_properties": {"ro.product.model": "Pixel 2"},
                "monitor": {"cpu_total": 12.5, "mem_available_kb": 800},
            }
            diff = mod.compare(old, new)
            self.assertIn("com.c", diff["packages"]["added"])
            self.assertIn("com.a", diff["packages"]["removed"])
            self.assertIn("transport", diff["device_changes"])
            self.assertGreater(diff["summary"]["system_properties_changed"], 0)


if __name__ == "__main__":
    unittest.main()
