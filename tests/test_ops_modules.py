from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from modules.app_change_tracker import AppChangeTrackerModule
from modules.notification_center import NotificationCenterModule
from modules.smart_sync import SmartSyncModule
from modules.support_bundle import SupportBundleModule
from modules.workflow_center import WorkflowCenterModule


class _StubADB:
    def run(self, args, serial=None, timeout=None):  # noqa: ANN001
        cmd = " ".join(args)
        class R:
            def __init__(self, ok=True, stdout="", stderr=""):
                self.ok = ok
                self.stdout = stdout
                self.stderr = stderr
        if "find" in cmd and "stat -c" in cmd:
            return R(True, "10|100|/sdcard/src/a.txt\n")
        if "pull" in cmd or "push" in cmd:
            return R(True, "ok")
        return R(True, "")


class NotificationCenterTests(unittest.TestCase):
    def test_add_list_mark_delete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mod = NotificationCenterModule(Path(tmp) / "n.db")
            nid = mod.add(severity="warning", category="health", title="Low battery", message="Battery low", device_serial="ABC")
            self.assertGreater(nid, 0)
            rows = mod.list()
            self.assertEqual(len(rows), 1)
            self.assertEqual(mod.unread_count(), 1)
            mod.mark_read(nid)
            self.assertEqual(mod.unread_count(), 0)
            mod.delete(nid)
            self.assertEqual(mod.list(), [])


class AppChangeTrackerTests(unittest.TestCase):
    def test_compare_detects_updates_and_risk_changes(self) -> None:
        mod = AppChangeTrackerModule()
        old = {
            "packages_user": ["a", "b"],
            "package_versions": {"a": "1", "b": "1"},
            "package_risks": {"a": "LOW", "b": "MEDIUM"},
        }
        new = {
            "packages_user": ["b", "c"],
            "package_versions": {"b": "2", "c": "1"},
            "package_risks": {"b": "HIGH", "c": "LOW"},
        }
        diff = mod.compare(old, new)
        self.assertEqual(diff["summary"]["added"], 1)
        self.assertEqual(diff["summary"]["removed"], 1)
        self.assertEqual(diff["summary"]["updated"], 1)
        self.assertEqual(diff["summary"]["risk_changes"], 1)


class SmartSyncTests(unittest.TestCase):
    def test_preview_and_execute(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src"
            dst = Path(tmp) / "dst"
            src.mkdir(parents=True)
            dst.mkdir(parents=True)
            (src / "a.txt").write_text("hello", encoding="utf-8")
            mod = SmartSyncModule(_StubADB())  # type: ignore[arg-type]
            preview = mod.preview(
                serial="ABC",
                direction="host_to_device",
                source=str(src),
                destination="/sdcard/dst",
                mode="copy_missing_only",
            )
            self.assertTrue(preview["ok"])
            result = mod.execute(serial="ABC", preview=preview)
            self.assertTrue(result["ok"])


class SupportBundleTests(unittest.TestCase):
    def test_bundle_creation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            mod = SupportBundleModule(base)
            out = mod.create_bundle(
                bundle_name="bundle",
                serial="ABC",
                include={"device_inspector": True, "device_health": True},
                data={"device_inspector": {"model": "Pixel"}, "device_health": {"score": 90}},
                output_dir=base / "reports",
            )
            self.assertTrue(out["ok"])
            self.assertTrue(Path(out["zip_file"]).exists())


class WorkflowCenterTests(unittest.TestCase):
    def test_definitions_exist(self) -> None:
        mod = WorkflowCenterModule()
        defs = mod.as_dicts()
        self.assertGreaterEqual(len(defs), 8)
        ids = {d["workflow_id"] for d in defs}
        self.assertIn("onboard_device", ids)
        self.assertIn("collect_debug_bundle", ids)


if __name__ == "__main__":
    unittest.main()
