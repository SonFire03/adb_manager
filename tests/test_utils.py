from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.adb_manager import ADBManager
from core.utils import ConfigManager, HistoryDB


class ConfigManagerTests(unittest.TestCase):
    def test_get_set_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            cfg = ConfigManager(path)
            cfg.set("app.theme", "dark")
            cfg.save()

            cfg2 = ConfigManager(path)
            self.assertEqual(cfg2.get("app.theme"), "dark")


class SafeModeTests(unittest.TestCase):
    def test_blocks_dangerous_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            cfg_path = base / "settings.json"
            cfg_path.write_text('{"app": {"safe_mode": true}, "adb": {"binary": "adb"}}', encoding="utf-8")
            cfg = ConfigManager(cfg_path)
            db = HistoryDB(base / "history.db")
            adb = ADBManager(cfg, db)
            res = adb.run("shell rm -rf /")
            self.assertFalse(res.ok)
            self.assertEqual(res.returncode, 126)


if __name__ == "__main__":
    unittest.main()

