from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.utils import DeviceInfo
from modules.data_transfer import DataTransferModule
from modules.device_health import DeviceHealthModule


class _R:
    def __init__(self, ok: bool = True, stdout: str = "", stderr: str = "", returncode: int = 0) -> None:
        self.ok = ok
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


class _StubADB:
    def run(self, args, serial=None, timeout=None):  # noqa: ANN001
        cmd = " ".join(args)
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
            return _R(True, "level: 80\nscale: 100\nstatus: 2\nhealth: 2\ntemperature: 350\n")
        if "df -k /data" in cmd:
            return _R(True, "Filesystem 1K-blocks Used Available Use% Mounted on\n/data 1000000 500000 500000 50% /data\n")
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


class DeviceHealthTests(unittest.TestCase):
    def test_device_health_report_shape(self) -> None:
        mod = DeviceHealthModule(_StubADB())  # type: ignore[arg-type]
        report = mod.run(
            "ABC",
            DeviceInfo(serial="ABC", state="device", model="Pixel", transport="usb", android_version="14", root=False),
        )
        self.assertIn("score", report)
        self.assertIn("status", report)
        self.assertIn("findings", report)
        self.assertIsInstance(report["findings"], list)
        self.assertGreater(len(report["findings"]), 0)


if __name__ == "__main__":
    unittest.main()
