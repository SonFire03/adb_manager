from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.utils import DeviceInfo
from modules.data_transfer import DataTransferModule
from modules.device_health import DeviceHealthModule
from modules.health_check import HealthCheckModule


class _R:
    def __init__(
        self, ok: bool = True, stdout: str = "", stderr: str = "", returncode: int = 0
    ) -> None:
        self.ok = ok
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


class _StubADB:
    adb_bin = "adb"

    def run(self, args, serial=None, timeout=None):  # noqa: ANN001
        cmd = " ".join(args)
        demo_hash = hashlib.sha256(b"demo").hexdigest()
        if "du -sk" in cmd and "/bad" in cmd:
            return _R(False, "", "du failed", 1)
        if "push" in cmd and "/sdcard/fail" in cmd:
            return _R(False, "", "push failed", 1)
        if "ls -ld" in cmd and "/sdcard/missing" in cmd:
            return _R(False, "", "not found", 1)
        if "sha256sum" in cmd and "/sdcard/Download/file.txt" in cmd:
            return _R(True, f"{demo_hash}  /sdcard/Download/file.txt\n")
        if "du -sk" in cmd:
            return _R(True, "1024 /sdcard/DCIM\n")
        if "find" in cmd and "wc -l" in cmd:
            return _R(True, "5\n")
        if "pull" in cmd:
            return _R(True, "5 files pulled")
        if "push" in cmd:
            return _R(True, "5 files pushed")
        if "ls -ld" in cmd:
            return _R(True, "drwxrwx--- /sdcard/Download")
        if "dumpsys battery" in cmd:
            return _R(
                True, "level: 80\nscale: 100\nstatus: 2\nhealth: 2\ntemperature: 350\n"
            )
        if "df -k /data" in cmd:
            return _R(
                True,
                "Filesystem 1K-blocks Used Available Use% Mounted on\n/data 1000000 500000 500000 50% /data\n",
            )
        if "dumpsys cpuinfo" in cmd:
            return _R(True, "22.0% TOTAL: 10.0% user + 12.0% kernel")
        if "cat /proc/meminfo" in cmd:
            return _R(True, "MemTotal: 8000000 kB\nMemAvailable: 2000000 kB\n")
        if "dumpsys thermalservice" in cmd:
            return _R(True, "sensor temp=42.5")
        if "cmd wifi status" in cmd:
            return _R(True, "Wifi is enabled")
        if "ip -f inet addr show wlan0" in cmd:
            return _R(True, "inet 192.168.1.10/24 brd 192.168.1.255")
        if "settings get global bluetooth_on" in cmd:
            return _R(True, "1")
        if "shell echo ok" in cmd:
            return _R(True, "ok\n")
        if "logcat -d -t 250" in cmd:
            return _R(True, "")
        return _R(True, "")


class DataTransferTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = DataTransferModule(_StubADB())  # type: ignore[arg-type]

    def test_device_to_host_dry_run(self) -> None:
        task = self.mod.make_task(
            serial="ABC",
            direction="device_to_host",
            source="/sdcard/DCIM",
            destination="/tmp/out",
            preset="DCIM",
            dry_run=True,
        )
        res = self.mod.execute_task(task)
        self.assertTrue(res["ok"])
        self.assertEqual(res["status"], "dry_run")

    def test_host_to_device_transfer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "file.txt"
            src.write_text("demo", encoding="utf-8")
            task = self.mod.make_task(
                serial="ABC",
                direction="host_to_device",
                source=str(src),
                destination="/sdcard/Download",
                preset="Custom folders",
                dry_run=False,
            )
            res = self.mod.execute_task(task)
            self.assertTrue(res["ok"])
            self.assertEqual(res["status"], "success")
            self.assertTrue(res["integrity"]["checked"])
            self.assertTrue(res["integrity"]["ok"])

    def test_make_task_checksum_options(self) -> None:
        task = self.mod.make_task(
            serial="ABC",
            direction="host_to_device",
            source="/tmp/file.txt",
            destination="/sdcard/Download",
            verify_integrity=False,
            checksum_algorithm="md5",
        )
        self.assertFalse(task.verify_integrity)
        self.assertEqual(task.checksum_algorithm, "md5")

    def test_estimate_host_source_missing(self) -> None:
        task = self.mod.make_task(
            serial="ABC",
            direction="host_to_device",
            source="/definitely/missing/path",
            destination="/sdcard/Download",
            dry_run=False,
        )
        est = self.mod.estimate_size(task)
        self.assertFalse(est["ok"])

    def test_preset_sources_and_helpers(self) -> None:
        self.assertEqual(self.mod.preset_sources("Custom folders"), [])
        self.assertEqual(self.mod.preset_sources("Export APK only"), [])
        self.assertGreaterEqual(len(self.mod.preset_sources("DCIM")), 1)
        self.assertEqual(self.mod._parse_du_kb("invalid"), 0)
        self.assertEqual(self.mod._parse_int("files: x"), 0)

    def test_device_estimate_failure_and_parse_helpers(self) -> None:
        task = self.mod.make_task(
            serial="ABC",
            direction="device_to_host",
            source="/bad",
            destination="/tmp/out",
            dry_run=False,
        )
        est = self.mod.estimate_size(task)
        self.assertFalse(est["ok"])
        self.assertEqual(self.mod._parse_du_kb(""), 0)
        self.assertEqual(self.mod._fmt_bytes(1536), "1.5 KB")

    def test_execute_host_to_device_missing_source(self) -> None:
        task = self.mod.make_task(
            serial="ABC",
            direction="host_to_device",
            source="/missing/local/file.txt",
            destination="/sdcard/Download",
            dry_run=False,
        )
        res = self.mod.execute_task(task)
        self.assertFalse(res["ok"])
        self.assertEqual(res["status"], "error")

    def test_execute_host_to_device_push_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "file.txt"
            src.write_text("demo", encoding="utf-8")
            task = self.mod.make_task(
                serial="ABC",
                direction="host_to_device",
                source=str(src),
                destination="/sdcard/fail",
                dry_run=False,
            )
            res = self.mod.execute_task(task)
            self.assertFalse(res["ok"])
            self.assertEqual(res["status"], "error")

    def test_execute_device_to_host_partial_when_verify_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            # No file created at destination; verify_local should fail while pull succeeds.
            task = self.mod.make_task(
                serial="ABC",
                direction="device_to_host",
                source="/sdcard/DCIM",
                destination=str(Path(tmp) / "missing_target" / "out"),
                dry_run=False,
            )
            res = self.mod.execute_task(task)
            self.assertFalse(res["ok"])
            self.assertEqual(res["status"], "partial")

    def test_execute_device_to_host_estimate_error(self) -> None:
        task = self.mod.make_task(
            serial="ABC",
            direction="device_to_host",
            source="/bad",
            destination="/tmp/out",
            dry_run=False,
        )
        res = self.mod.execute_task(task)
        self.assertFalse(res["ok"])
        self.assertEqual(res["status"], "error")

    def test_verify_remote_and_local_helpers(self) -> None:
        ok_remote = self.mod._verify_remote_path("ABC", "/sdcard/Download")
        bad_remote = self.mod._verify_remote_path("ABC", "/sdcard/missing")
        self.assertTrue(ok_remote["ok"])
        self.assertFalse(bad_remote["ok"])

        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            p = d / "file.txt"
            p.write_text("x", encoding="utf-8")
            self.assertTrue(self.mod._verify_local_path(p)["ok"])

    def test_verify_local_parent_populated_branch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp) / "dest"
            parent.mkdir(parents=True)
            (parent / "seed.txt").write_text("seed", encoding="utf-8")
            target = parent / "missing_file.txt"
            res = self.mod._verify_local_path(target)
            self.assertTrue(res["ok"])
            self.assertIn("parent populated", res["detail"])

    def test_local_size_directory_and_oserror_skip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.txt").write_text("abc", encoding="utf-8")
            (root / "b.txt").write_text("defg", encoding="utf-8")

            real_stat = Path.stat

            def _stat_with_fault(path_obj: Path):  # noqa: ANN001
                if path_obj.name == "b.txt":
                    raise OSError("simulated")
                return real_stat(path_obj)

            with patch.object(Path, "stat", new=_stat_with_fault):
                size, files = self.mod._local_size(root)
            self.assertEqual(files, 1)
            self.assertEqual(size, 3)

    def test_execute_host_to_device_source_missing_after_estimate(self) -> None:
        task = self.mod.make_task(
            serial="ABC",
            direction="host_to_device",
            source="/tmp/race.txt",
            destination="/sdcard/Download",
            dry_run=False,
        )
        with patch.object(
            self.mod, "estimate_size", return_value={"ok": True, "bytes": 1, "files": 1}
        ):
            with patch("modules.data_transfer.Path.exists", return_value=False):
                res = self.mod.execute_task(task)
        self.assertFalse(res["ok"])
        self.assertEqual(res["status"], "error")


class DeviceHealthTests(unittest.TestCase):
    def test_device_health_report_shape(self) -> None:
        mod = DeviceHealthModule(_StubADB())  # type: ignore[arg-type]
        report = mod.run(
            "ABC",
            DeviceInfo(
                serial="ABC",
                state="device",
                model="Pixel",
                transport="usb",
                android_version="14",
                root=False,
            ),
        )
        self.assertIn("score", report)
        self.assertIn("status", report)
        self.assertIn("findings", report)
        self.assertIn("priority_actions", report)
        self.assertIsInstance(report["findings"], list)
        self.assertGreater(len(report["findings"]), 0)


class HealthCheckTests(unittest.TestCase):
    def test_health_check_recommendations_are_reported(self) -> None:
        mod = HealthCheckModule(_StubADB())  # type: ignore[arg-type]
        report = mod.run(
            [
                DeviceInfo(
                    serial="ABC",
                    state="unauthorized",
                    model="Pixel",
                    transport="usb",
                    android_version="14",
                    root=False,
                )
            ],
            serial="ABC",
        )
        self.assertIn("recommendations", report)
        self.assertGreaterEqual(len(report["recommendations"]), 1)
        names = {item["name"] for item in report["recommendations"]}
        self.assertTrue({"device_auth", "adb_version", "adb_server"} & names)


if __name__ == "__main__":
    unittest.main()
