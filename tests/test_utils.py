from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.adb_manager import ADBManager
from core.utils import ConfigManager, HistoryDB, setup_logging
from gui.styles import get_theme


class ConfigManagerTests(unittest.TestCase):
    def test_get_set_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            cfg = ConfigManager(path)
            cfg.set("app.theme", "dark")
            cfg.save()

            cfg2 = ConfigManager(path)
            self.assertEqual(cfg2.get("app.theme"), "dark")

    def test_invalid_json_fallbacks_to_empty_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text("{invalid", encoding="utf-8")
            cfg = ConfigManager(path)
            self.assertEqual(cfg.get("app.theme", "light"), "light")

    def test_get_missing_nested_returns_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = ConfigManager(Path(tmp) / "settings.json")
            self.assertEqual(cfg.get("missing.path", "fallback"), "fallback")


class HistoryDBTests(unittest.TestCase):
    def test_add_events_and_recent_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = HistoryDB(Path(tmp) / "history.db")
            db.add_device_event("ABC", "Pixel", "connected")
            db.add_command_event("ABC", "shell echo ok", True, "ok", "")
            db.add_command_event(None, "devices -l", False, "", "err")
            rows = db.recent_device_history(limit=10)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0][0], "ABC")
            self.assertEqual(rows[0][2], "connected")

    def test_command_event_output_is_trimmed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "history.db"
            db = HistoryDB(db_path)
            long_out = "x" * 5000
            long_err = "y" * 5000
            db.add_command_event("ABC", "shell logcat", False, long_out, long_err)
            import sqlite3

            with sqlite3.connect(db_path) as conn:
                row = conn.execute(
                    "SELECT stdout, stderr FROM command_history ORDER BY id DESC LIMIT 1"
                ).fetchone()
            self.assertIsNotNone(row)
            stdout, stderr = row
            self.assertEqual(len(stdout), 4000)
            self.assertEqual(len(stderr), 4000)


class SetupLoggingTests(unittest.TestCase):
    def test_setup_logging_creates_directory_and_resets_handlers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            cfg_path = base / "settings.json"
            cfg_path.write_text(
                '{"logging":{"file":"logs/app.log","level":"DEBUG","max_bytes":4096,"backup_count":2}}',
                encoding="utf-8",
            )
            cfg = ConfigManager(cfg_path)
            setup_logging(base, cfg)
            setup_logging(base, cfg)
            self.assertTrue((base / "logs").exists())
            root = __import__("logging").getLogger()
            self.assertEqual(len(root.handlers), 2)


class SafeModeTests(unittest.TestCase):
    def test_blocks_dangerous_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            cfg_path = base / "settings.json"
            cfg_path.write_text(
                '{"app": {"safe_mode": true}, "adb": {"binary": "adb"}}',
                encoding="utf-8",
            )
            cfg = ConfigManager(cfg_path)
            db = HistoryDB(base / "history.db")
            adb = ADBManager(cfg, db)
            res = adb.run("shell rm -rf /")
            self.assertFalse(res.ok)
            self.assertEqual(res.returncode, 126)


class ThemeTests(unittest.TestCase):
    def test_theme_uses_new_accent_and_modes(self) -> None:
        dark = get_theme("dark")
        light = get_theme("light")
        self.assertIn("#f59e0b", dark)
        self.assertIn("#f59e0b", light)
        self.assertIn("background-color", dark)
        self.assertIn("background-color", light)


if __name__ == "__main__":
    unittest.main()
