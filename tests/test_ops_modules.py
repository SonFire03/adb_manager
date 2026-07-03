from __future__ import annotations

import tempfile
import unittest
import zipfile
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

        if "find" in cmd and "/bad" in cmd:
            return R(False, "", "remote find failed")
        if "find" in cmd and "stat -c" in cmd:
            return R(True, "10|100|/sdcard/src/a.txt\n")
        if "push" in cmd and "failpush" in cmd:
            return R(False, "", "push failed")
        if "pull" in cmd and "failpull" in cmd:
            return R(False, "", "pull failed")
        if "pull" in cmd or "push" in cmd:
            return R(True, "ok")
        return R(True, "")


class NotificationCenterTests(unittest.TestCase):
    def test_add_list_mark_delete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mod = NotificationCenterModule(Path(tmp) / "n.db")
            nid = mod.add(
                severity="warning",
                category="health",
                title="Low battery",
                message="Battery low",
                device_serial="ABC",
            )
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

    def test_execute_invalid_preview_and_modes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src"
            dst = Path(tmp) / "dst"
            src.mkdir(parents=True)
            dst.mkdir(parents=True)
            (src / "a.txt").write_text("hello", encoding="utf-8")
            mod = SmartSyncModule(_StubADB())  # type: ignore[arg-type]

            bad = mod.execute(serial="ABC", preview={"ok": False})
            self.assertFalse(bad["ok"])

            p2 = mod.preview(
                serial="ABC",
                direction="host_to_device",
                source=str(src),
                destination="/sdcard/dst",
                mode="skip_duplicates",
            )
            self.assertTrue(p2["ok"])
            self.assertIn("items", p2)

    def test_preview_modes_and_remote_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src"
            src.mkdir(parents=True)
            (src / "a.txt").write_text("hello", encoding="utf-8")
            mod = SmartSyncModule(_StubADB())  # type: ignore[arg-type]

            p_update = mod.preview(
                serial="ABC",
                direction="host_to_device",
                source=str(src),
                destination="/sdcard/dst",
                mode="update_newer_only",
            )
            self.assertTrue(p_update["ok"])
            self.assertIn("summary", p_update)

            p_mirror = mod.preview(
                serial="ABC",
                direction="host_to_device",
                source=str(src),
                destination="/sdcard/dst",
                mode="mirror_selected",
            )
            self.assertTrue(p_mirror["ok"])

            p_remote_fail = mod.preview(
                serial="ABC",
                direction="device_to_host",
                source="/bad",
                destination=str(src),
                mode="copy_missing_only",
            )
            self.assertFalse(p_remote_fail["ok"])

    def test_execute_collects_errors(self) -> None:
        mod = SmartSyncModule(_StubADB())  # type: ignore[arg-type]
        preview = {
            "ok": True,
            "direction": "host_to_device",
            "items": [
                {
                    "decision": "copy",
                    "source": "/tmp/a.txt",
                    "destination": "/sdcard/failpush.txt",
                },
                {
                    "decision": "update",
                    "source": "/tmp/b.txt",
                    "destination": "/sdcard/failpush2.txt",
                },
            ],
        }
        out = mod.execute(serial="ABC", preview=preview)
        self.assertFalse(out["ok"])
        self.assertGreaterEqual(len(out["errors"]), 1)

    def test_execute_device_to_host_error_branch(self) -> None:
        mod = SmartSyncModule(_StubADB())  # type: ignore[arg-type]
        preview = {
            "ok": True,
            "direction": "device_to_host",
            "items": [
                {
                    "decision": "copy",
                    "source": "/sdcard/failpull.txt",
                    "destination": "/tmp/failpull.txt",
                }
            ],
        }
        out = mod.execute(serial="ABC", preview=preview)
        self.assertFalse(out["ok"])
        self.assertEqual(out["executed"], 0)

    def test_decide_and_scan_edge_cases(self) -> None:
        mod = SmartSyncModule(_StubADB())  # type: ignore[arg-type]

        # both missing -> no item
        self.assertIsNone(
            mod._decide(
                rel="x",
                src=None,
                dst=None,
                mode="copy_missing_only",
                direction="host_to_device",
                source_root="/src",
                dest_root="/dst",
            )
        )

        # update path in update_newer_only
        item = mod._decide(
            rel="x",
            src={"size": 2, "mtime": 200},
            dst={"size": 1, "mtime": 100},
            mode="update_newer_only",
            direction="host_to_device",
            source_root="/src",
            dest_root="/dst",
        )
        assert item is not None
        self.assertEqual(item.decision, "update")

        # conflict path in skip_duplicates
        item2 = mod._decide(
            rel="x",
            src={"size": 2, "mtime": 200},
            dst={"size": 1, "mtime": 100},
            mode="skip_duplicates",
            direction="host_to_device",
            source_root="/src",
            dest_root="/dst",
        )
        assert item2 is not None
        self.assertEqual(item2.decision, "conflict")

        # scan local failure
        scan_local = mod._scan_local("/definitely/missing")
        self.assertFalse(scan_local["ok"])

        # scan dispatch remote failure path
        scan_remote = mod._scan(
            serial="ABC",
            direction="device_to_host",
            root="/bad",
            side="src",
        )
        self.assertFalse(scan_remote["ok"])


class SupportBundleTests(unittest.TestCase):
    def test_bundle_creation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            mod = SupportBundleModule(base)
            out = mod.create_bundle(
                bundle_name="bundle",
                serial="ABC",
                include={"device_inspector": True, "device_health": True},
                data={
                    "device_inspector": {"model": "Pixel"},
                    "device_health": {"score": 90},
                },
                output_dir=base / "reports",
            )
            self.assertTrue(out["ok"])
            self.assertTrue(Path(out["zip_file"]).exists())

    def test_bundle_with_logs_and_captures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            cap = base / "cap.txt"
            log = base / "log.txt"
            cap.write_text("capture", encoding="utf-8")
            log.write_text("log", encoding="utf-8")

            mod = SupportBundleModule(base)
            out = mod.create_bundle(
                bundle_name="bundle2",
                serial="XYZ",
                include={"captures": True, "logs": True},
                data={"captures": [str(cap)], "logs": [str(log)]},
                output_dir=base / "reports",
            )
            self.assertTrue(out["ok"])
            zpath = Path(out["zip_file"])
            with zipfile.ZipFile(zpath, "r") as zf:
                names = set(zf.namelist())
                self.assertIn("captures/cap.txt", names)
                self.assertIn("logs/log.txt", names)
                self.assertIn("manifest.json", names)


class WorkflowCenterTests(unittest.TestCase):
    def test_definitions_exist(self) -> None:
        mod = WorkflowCenterModule()
        defs = mod.as_dicts()
        self.assertGreaterEqual(len(defs), 8)
        ids = {d["workflow_id"] for d in defs}
        self.assertIn("onboard_device", ids)
        self.assertIn("collect_debug_bundle", ids)
        onboard = next(d for d in defs if d["workflow_id"] == "onboard_device")
        self.assertTrue(onboard["supports_dry_run"])
        self.assertGreaterEqual(len(onboard["variables"]), 1)
        self.assertIn("notes", onboard["steps"][0])


if __name__ == "__main__":
    unittest.main()
