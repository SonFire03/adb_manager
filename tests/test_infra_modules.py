from __future__ import annotations

import tempfile
import types
import unittest
from pathlib import Path

from core.device_manager import DeviceManager
from core.plugin_manager import PluginManager
from core.utils import CommandResult
from modules.automation import AutomationModule
from modules.backup_restore import BackupRestoreModule
from modules.file_manager import FileManagerModule


class _HistoryStub:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, str]] = []

    def add_device_event(self, serial: str, model: str, event: str) -> None:
        self.events.append((serial, model, event))


class _ADBStub:
    def __init__(self) -> None:
        self.history = _HistoryStub()
        self.calls: list[tuple[object, str | None, int | None]] = []

    def run(self, args, serial=None, timeout=None):  # noqa: ANN001
        self.calls.append((args, serial, timeout))
        text = " ".join(args) if isinstance(args, list) else str(args)
        if text == "devices -l":
            return CommandResult(
                ok=True,
                command=["adb", "devices", "-l"],
                stdout=(
                    "ABC123 device product:x model:Pixel_8 transport_id:3\n"
                    "XYZ999 unauthorized usb:1-1 product:y model:Pixel_6"
                ),
                stderr="",
                returncode=0,
            )
        if text == "shell getprop ro.build.version.release":
            return CommandResult(True, ["adb"], "14\n", "", 0)
        if text == "shell su -c id":
            return CommandResult(True, ["adb"], "uid=0(root)", "", 0)
        if text.startswith("connect "):
            return CommandResult(True, ["adb"], "connected to 192.168.1.3:5555", "", 0)
        if text.startswith("shell ls -la"):
            return CommandResult(True, ["adb"], "a\nb\n", "", 0)
        if text.startswith("shell find "):
            return CommandResult(
                True,
                ["adb"],
                "/sdcard/base/keep.txt\n/sdcard/base/other.log\n",
                "",
                0,
            )
        return CommandResult(True, ["adb"], "ok", "", 0)


class DeviceManagerTests(unittest.TestCase):
    def test_list_devices_parsing_and_events(self) -> None:
        adb = _ADBStub()
        mod = DeviceManager(adb)  # type: ignore[arg-type]

        captured: list[int] = []
        mod.add_listener(lambda items: captured.append(len(items)))
        items = mod.list_devices()

        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].serial, "ABC123")
        self.assertEqual(items[0].state, "device")
        self.assertEqual(items[0].android_version, "14")
        self.assertTrue(items[0].root)
        self.assertEqual(items[1].transport, "usb")
        self.assertEqual(captured, [2])
        self.assertEqual(adb.history.events[0], ("ABC123", "Pixel_8", "connected"))

        # Calling again with same set should not produce disconnect/connect churn.
        mod.list_devices()
        self.assertEqual(len(adb.history.events), 2)
        self.assertTrue(mod.connect_wifi("192.168.1.3"))
        self.assertEqual(len(mod.current_devices()), 2)
        mod.shutdown()


class PluginManagerTests(unittest.TestCase):
    def test_discover_and_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "alpha.py").write_text("X = 42\n", encoding="utf-8")
            (root / "beta.py").write_text("NAME = 'ok'\n", encoding="utf-8")
            (root / "ignore.txt").write_text("n/a\n", encoding="utf-8")

            pm = PluginManager(root)
            found = pm.discover()
            self.assertEqual([p.name for p in found], ["alpha.py", "beta.py"])

            mod = pm.load(root / "alpha.py")
            self.assertEqual(getattr(mod, "X"), 42)


class AutomationAndFilesTests(unittest.TestCase):
    def test_automation_save_list_and_run(self) -> None:
        adb = _ADBStub()
        with tempfile.TemporaryDirectory() as tmp:
            mod = AutomationModule(adb, Path(tmp))  # type: ignore[arg-type]
            mod.save_script("quick", ["shell getprop ro.build.version.release"])
            scripts = mod.list_scripts()
            self.assertEqual(len(scripts), 1)
            self.assertEqual(scripts[0]["name"], "quick")

            results = mod.run_script(
                "ABC123", ["shell getprop ro.build.version.release"]
            )
            self.assertEqual(results[0][1], True)

    def test_file_manager_and_backup_restore_commands(self) -> None:
        adb = _ADBStub()
        fm = FileManagerModule(adb)  # type: ignore[arg-type]
        br = BackupRestoreModule(adb, Path(tempfile.gettempdir()) / "adb_test_backups")  # type: ignore[arg-type]

        files = fm.list_remote("ABC123", "/sdcard")
        self.assertEqual(files, ["a", "b"])

        found = fm.search_remote("ABC123", "/sdcard/base", "keep")
        self.assertEqual(found, ["/sdcard/base/keep.txt"])

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "nested" / "out.txt"
            fm.pull("ABC123", "/sdcard/base/keep.txt", target)
            self.assertTrue(target.parent.exists())
            fm.push("ABC123", target, "/sdcard/base/out.txt")
            fm.chmod("ABC123", "755", "/sdcard/base/out.txt")

        res1 = br.full_backup("ABC123", "full")
        res2 = br.selective_backup("ABC123", ["com.demo.a"], "sel")
        res3 = br.restore("ABC123", Path("/tmp/dump.ab"))
        self.assertTrue(res1.ok and res2.ok and res3.ok)


if __name__ == "__main__":
    unittest.main()
